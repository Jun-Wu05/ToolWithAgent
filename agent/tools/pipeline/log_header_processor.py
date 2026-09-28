# -*- coding: utf-8 -*-
"""
日志头特征处理（Path A）。

当日志类型的分类特征位于日志头中时（Step 2a 判定 feature_location=header），
使用此模块处理：header 聚类仅作结构样本源 → LLM 生成类型提取正则（代码校验）
→ 正则只作用于日志头、经 aggregate_by_field 全量去重/计数 → 分批补 meaning。

CHANGED (#190): 类型集合改由确定性正则全量扫描决定，聚类与 LLM 不再枚举类型；
                coverage 四字段随聚合结果输出，不同主结构行计入 unmatched。
CHANGED (2026-05-29): 集成 HeaderExtractor 消除重复代码；
                       增加 header_end_marker 传递和 real_samples 提取。
CHANGED (2026-06-02): 支持 KV 格式，feature_identifier 和 analysis 动态设置。
CHANGED (2026-06-18): _generate_kv_feature_identifier 增加重试机制（最多1次），
                       失败时将错误反馈拼入 prompt 并输出详细调试日志。
"""

from __future__ import annotations

import json
import re as _re

from agent.prompts import (
    load_kv_feature_identifier_prompt,
    load_log_header_regex_identifier_prompt,
)
from agent.shared.logger import get_logger
from agent.tools.pipeline.common.aggregator import aggregate_by_field
from agent.tools.pipeline.extractors.header_extractor import (
    aggregate_headers,
    extract_header,
)
from agent.tools.pipeline.llm_client import (
    _call_llm_direct,
    normalize_log_format,
)

logger = get_logger("log_parser_pipeline")

# JSON 格式的 feature_identifier 固定正则
_JSON_FEATURE_IDENTIFIER = r"(\{[\S\s]*\})"

# KV body 正则提示只携带有界结构样本；最终正确性仍由全量日志校验保证。
_KV_BODY_SAMPLE_LIMIT = 20
_KV_BODY_SAMPLE_MAX_CHARS = 600


def _parse_regex_response(response: str) -> str:
    """从 LLM 响应中鲁棒提取正则字符串。

    支持格式:
    - r'...' 或 r"..."
    - <regex>（纯字符串）
    - ```<regex>```（markdown 围栏）
    - 带解释文字的混合输出

    Returns:
        提取出的正则字符串，失败返回空字符串。
    """
    text = response.strip()

    # 尝试提取 r'...' 格式
    m = _re.search(r"r['\"](.+?)['\"]", text)
    if m:
        return m.group(1)
    
    # 尝试提取 markdown 代码块
    m = _re.search(r"```\w*\n?(.*?)\n?```", text, _re.DOTALL)
    if m:
        content = m.group(1).strip()
        # 可能带 r'...' 前缀
        inner = _re.search(r"r['\"](.+?)['\"]", content)
        if inner:
            return inner.group(1)
        return content
    
    # 兜底：去掉首尾引号
    text = text.strip("'\"")
    # 如果只有一行，直接返回
    if "\n" not in text and len(text) < 500:
        return text
    
    return ""


def _observe_kv_header_facts(lines: list[str], header_end_marker: str = "") -> str:
    """代码预观察日志头结构事实，注入 prompt 供 LLM 直接采用（#290）。

    观察错误（空格假设、冒号误判）是历史多次正则翻车点；这些事实由代码
    确定性统计，LLM 只负责组合，不负责观察。无事实时返回空串。
    """
    facts: list[str] = []
    pri_gaps: list[bool] = []
    for line in lines:
        pri = _re.match(r"^<\d+>", line)
        if not pri:
            continue
        nxt = line[pri.end():pri.end() + 1]
        pri_gaps.append(nxt.isspace())
    if pri_gaps:
        facts.append("样例行以 syslog 优先级 `<数字>` 开头")
        if all(pri_gaps):
            facts.append("优先级 `>` 之后紧跟一个空格（正则应写 `<\\d+>\\s`）")
        elif not any(pri_gaps):
            facts.append(
                "优先级 `>` 之后**没有空格**（正则应写 `<\\d+>\\w`，禁止插入 `\\s+`）"
            )
        else:
            facts.append(
                "优先级 `>` 之后有的行有空格、有的行没有（正则必须写 `<\\d+>\\s*` 可选空白）"
            )
    if any(_re.search(r"\d{2}:\d{2}:\d{2}", line) for line in lines):
        facts.append("存在 HH:MM:SS 时间戳（其中的冒号属于时间，不是分隔符）")
    if header_end_marker:
        facts.append(
            f"格式识别已确定日志头结束标记为 {header_end_marker!r}"
            "（捕获组应从其后的 KV body 开始）"
        )
    if not facts:
        return ""
    block = "\n\n# 代码观察到的确定事实（必须直接采用，禁止与事实冲突的假设）\n"
    return block + "\n".join(f"- {fact}" for fact in facts)


def _failing_sample_block(regex_str: str, texts: list[str], limit: int = 2) -> str:
    """取前几条未被正则匹配（或捕获为空）的真实样例，供重试反馈展示（#290）。"""
    try:
        pattern = _re.compile(regex_str)
    except _re.error:
        pattern = None
    shown: list[str] = []
    for text in texts:
        if len(shown) >= limit:
            break
        match = pattern.search(text) if pattern is not None else None
        if match is None or not (match.group(1) or "").strip():
            shown.append(f"- `{text[:80]}`")
    if not shown:
        return ""
    return (
        "\n以下真实样例未能被上次正则匹配（或捕获为空），"
        "请逐字符对照其真实结构：\n" + "\n".join(shown)
    )


def _select_kv_body_samples(logs_str: str, kv_delimit: str) -> list[str]:
    """按日志头结构选择有界 KV 样本，避免只观察首行。"""
    clusters = aggregate_headers(
        logs_str,
        format_type="kv",
        delimit=kv_delimit,
        max_clusters=_KV_BODY_SAMPLE_LIMIT,
    ).get("clusters", [])
    samples = [c.get("raw_sample", "") for c in clusters if c.get("raw_sample")]
    if not samples:
        samples = [line for line in logs_str.splitlines() if line.strip()]
    return [
        sample[:_KV_BODY_SAMPLE_MAX_CHARS]
        for sample in samples[:_KV_BODY_SAMPLE_LIMIT]
    ]


def _validate_regex(
    regex_str: str,
    lines: list[str],
    kv_delimit: str = "=",
) -> tuple[bool, str, int]:
    """验证 KV body 正则：结构合法且覆盖本批全部有效日志。

    Args:
        regex_str: 待验证的正则字符串。
        lines: 本批全部有效日志行。
        kv_delimit: KV 键值连接符。

    Returns:
        (is_valid, error_msg, body_length)
        - is_valid: 验证是否通过。
        - error_msg: 稳定失败类别与计数（成功时为空字符串）。
        - body_length: 首个成功提取 body 的长度。
    """
    # 编译检查
    try:
        pattern = _re.compile(regex_str)
    except _re.error:
        return False, "regex_compile_failed", 0

    # 捕获组检查
    if pattern.groups != 1:
        return False, f"regex_capture_group_count_invalid; groups={pattern.groups}", 0

    total = len(lines)
    matched = 0
    first_error = ""
    body_length = 0
    kv_start = _re.compile(
        rf"^[\w.-]+(?:\(\d+\))?\s*{_re.escape(kv_delimit)}"
    )
    for line in lines:
        match = pattern.search(line)
        body = (match.group(1) or "").strip() if match else ""
        error = ""
        if not match:
            error = "regex_no_match"
        elif not body:
            error = "body_empty"
        elif body == line.strip() and extract_header(line, "kv", kv_delimit):
            error = "body_is_full_line"
        elif body.startswith("<") and _re.match(r"^<\d+>", body):
            error = "body_contains_syslog_pri"
        elif not kv_start.match(body):
            error = "body_not_kv"
        else:
            matched += 1
            if not body_length:
                body_length = len(body)
        if error and not first_error:
            first_error = error

    if matched != total:
        return (
            False,
            "kv_body_regex_validation_failed; "
            f"matched={matched}; total={total}; reason={first_error}",
            0,
        )
    return True, "", body_length


def _generate_kv_feature_identifier(
    logs_str: str, kv_delimit: str = "=", header_end_marker: str = ""
) -> str:
    """用 LLM 生成 KV body 提取正则（单个捕获组，Group1 = KV body）。

    CHANGED (2026-06-18): 增加重试机制（最多 1 次重试），重试时将错误反馈
                          拼入 prompt，并输出详细调试日志。失败仍抛出异常，
                          不使用兜底策略。
    CHANGED (#290): 注入代码预观察的结构事实（PRI 后空格、时间戳、
                    header_end_marker），失败反馈附带真实失配样例。

    Args:
        logs_str: 原始日志字符串（多行）。
        kv_delimit: KV 键值连接符。
        header_end_marker: 格式识别确定的日志头结束标记（可为空）。

    Returns:
        正则字符串，失败抛出 ValueError。

    Raises:
        ValueError: 所有重试均失败时抛出。
    """
    all_lines = [l.strip() for l in logs_str.strip().split("\n") if l.strip()]
    if not all_lines:
        raise ValueError("日志内容为空，无法生成 feature_identifier")

    kv_pair = _re.compile(
        rf"[\w.-]+(?:\(\d+\))?\s*{_re.escape(kv_delimit)}"
    )
    lines = [line for line in all_lines if kv_pair.search(line)]
    if not lines:
        raise ValueError("没有可识别的 KV 日志行，无法生成 feature_identifier")

    valid_logs_str = "\n".join(lines)
    sample_lines = _select_kv_body_samples(valid_logs_str, kv_delimit)
    sample_block = "\n".join(f"- `{line}`" for line in sample_lines)
    base_prompt = load_kv_feature_identifier_prompt()
    observed_facts = _observe_kv_header_facts(lines, header_end_marker)

    max_attempts = 2  # 初次 + 1 次重试
    last_error = ""
    last_regex = ""

    for attempt in range(1, max_attempts + 1):
        logger.debug(f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} 开始")

        # CHANGED: 重试时附加错误反馈
        prompt = base_prompt.replace("{sample_logs}", sample_block)
        prompt = prompt.replace("{observed_facts}", observed_facts)
        if attempt > 1 and last_error:
            feedback = (
                f"\n\n# ⚠️ 上次生成的正则有误，请修正\n"
                f"- 上次错误：{last_error}\n"
                f"- 上次正则：`{last_regex}`\n"
                f"- 本批有效日志数：{len(lines)}\n"
                f"\n请仔细检查样例日志中各部分的实际分隔情况，重新生成。"
            )
            feedback += _failing_sample_block(last_regex, lines)
            prompt += feedback
            logger.debug(
                f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
                f"已附加错误反馈（上次错误: {last_error}）"
            )

        # 调用 LLM
        try:
            response = _call_llm_direct(
                prompt, temperature=0.1, max_tokens=500, timeout=30, force_json=False
            )
        except Exception as e:
            last_error = "llm_call_failed"
            last_regex = ""
            logger.debug(
                f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
                f"LLM 调用失败; exception_type={type(e).__name__}"
            )
            continue

        logger.debug(
            f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
            f"LLM 响应长度: {len(response)}"
        )

        # 解析 LLM 输出
        regex_str = _parse_regex_response(response)
        if not regex_str:
            last_error = "LLM 输出无法解析为正则"
            last_regex = response[:200]
            logger.debug(
                f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
                f"解析失败（无法从响应中提取正则）"
            )
            continue

        logger.debug(
            f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
            f"解析得到正则; regex_length={len(regex_str)}"
        )

        # 验证正则
        is_valid, err_msg, body_length = _validate_regex(
            regex_str, lines, kv_delimit
        )
        if is_valid:
            logger.info(
                f"[_generate_kv_feature_identifier] 生成成功 "
                f"(尝试 {attempt}/{max_attempts}); regex_length={len(regex_str)}, "
                f"body_length={body_length}"
            )
            return regex_str
        else:
            last_error = err_msg
            last_regex = regex_str
            logger.debug(
                f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
                f"验证失败: {err_msg}; regex_length={len(regex_str)}"
            )

    raise ValueError(
        f"kv_body_regex_generation_failed; attempts={max_attempts}; "
        f"reason={last_error}"
    )


# 结构样本上限（#190）：header 聚类降级为结构样本源，最多取 20 条供正则生成
_LOGTYPE_SAMPLE_LIMIT = 20


def _validate_logtype_regex(regex_str: str, header_texts: list[str]) -> tuple[bool, str, int]:
    """校验类型提取正则：编译 + 恰 1 捕获组 + 对全部结构样本提取非空值。"""
    try:
        pattern = _re.compile(regex_str)
    except _re.error:
        return False, "regex_compile_failed", 0
    if pattern.groups != 1:
        return False, f"regex_capture_group_count_invalid; groups={pattern.groups}", 0
    matched = 0
    first_error = ""
    value_length = 0
    for text in header_texts:
        m = pattern.search(text)
        if not m:
            first_error = first_error or "regex_no_match"
            continue
        value = (m.group(1) or "").strip()
        if not value:
            first_error = first_error or "captured_value_empty"
            continue
        matched += 1
        if not value_length:
            value_length = len(value)
    if matched != len(header_texts):
        return (
            False,
            "header_logtype_regex_validation_failed; "
            f"matched={matched}; total={len(header_texts)}; reason={first_error}",
            0,
        )
    return True, "", value_length


def _generate_header_logtype_regex(
    sample_lines: list[str], format_type: str, delimit: str
) -> _re.Pattern:
    """用 LLM 生成日志类型路径提取正则（1 捕获组，≤2 次尝试，#190）。

    类型集合由该正则全量扫描决定；首次失败附错误反馈修复一次，
    再失败抛 ValueError（调用方返回 FAILED），禁止降级为模型自由枚举。

    Args:
        sample_lines: header 聚类分层的原始日志行样本。
        format_type:  日志格式（大小写无关）。
        delimit:      KV 键值分隔符（用于从样本行提取日志头）。

    Returns:
        编译后的正则对象。

    Raises:
        ValueError: 全部尝试均失败。
    """
    header_texts = [
        h for h in (extract_header(l, format_type, delimit) or l for l in sample_lines)
        if h.strip()
    ]
    if not header_texts:
        raise ValueError("无有效日志头样本")

    base_prompt = load_log_header_regex_identifier_prompt()
    max_attempts = 2  # 初次 + 1 次修复
    last_error, last_regex = "", ""

    for attempt in range(1, max_attempts + 1):
        prompt = base_prompt.replace(
            "{sample_logs}", "\n".join(header_texts[:_LOGTYPE_SAMPLE_LIMIT])
        )
        if attempt > 1 and last_error:
            feedback = (
                f"\n\n# ⚠️ 上次生成的正则有误，请修正\n"
                f"- 上次错误：{last_error}\n"
                f"- 上次正则：`{last_regex}`\n"
                f"\n请重新观察样例结构，生成泛化的类型路径提取正则。"
            )
            feedback += _failing_sample_block(last_regex, header_texts)
            prompt += feedback
        try:
            response = _call_llm_direct(
                prompt, temperature=0.1, max_tokens=500, timeout=30, force_json=False
            )
        except Exception as e:
            last_error, last_regex = "llm_call_failed", ""
            logger.debug(
                f"[_generate_header_logtype_regex] 尝试 {attempt}/{max_attempts} "
                f"LLM 调用失败; exception_type={type(e).__name__}"
            )
            continue

        regex_str = _parse_regex_response(response)
        if not regex_str:
            last_error, last_regex = "LLM 输出无法解析为正则", response[:200]
            continue

        is_valid, err_msg, value_length = _validate_logtype_regex(
            regex_str, header_texts
        )
        if is_valid:
            logger.info(
                f"[_generate_header_logtype_regex] 生成成功 "
                f"(尝试 {attempt}/{max_attempts}); "
                f"regex_length={len(regex_str)}, value_length={value_length}"
            )
            return _re.compile(regex_str)
        last_error, last_regex = err_msg, regex_str
        logger.debug(
            f"[_generate_header_logtype_regex] 尝试 {attempt}/{max_attempts} "
            f"验证失败: {err_msg}; regex_length={len(regex_str)}"
        )

    raise ValueError(
        f"header_logtype_regex_generation_failed; attempts={max_attempts}; "
        f"reason={last_error}"
    )


def _make_header_logtype_extractor(pattern: _re.Pattern, format_type: str, delimit: str):
    """构造类型提取器：正则只作用于日志头文本（#190）。

    不同主结构的行（如管道格式）在日志头中匹配不到类型路径，
    由聚合器计入 unmatched，不参与分类。
    """

    def extract(line: str, feature_field: str):
        header = extract_header(line, format_type, delimit)
        if not header:
            return None
        m = pattern.search(header)
        if not m or not (m.group(1) or "").strip():
            return None
        return m.group(1).strip()

    return extract


def classify_header_features(
    logs_str: str,
    format_type: str = "json",
    format_detail: str = "",
    header_end_marker: str = "",
    format_info: dict | None = None,
) -> str:
    """Path A: 日志头分类特征提取主函数（#190 全量确定性枚举）。

    类型集合由「LLM 生成 + 代码校验的类型提取正则」全量扫描决定；
    header 聚类只提供结构样本；LLM 另按 ≤20 值/批补充 meaning，
    批次或覆盖不完整只降级 PARTIAL，不删类型、不自由枚举。

    CHANGED (2026-06-18): 新增 format_info 参数，优先使用 Step1 确定的 delimit/tab。
    """
    is_kv = (format_type or "").lower() == "kv"
    kv_feature_identifier = ""
    kv_delimit = "="
    if is_kv and format_info:
        kv_delimit = format_info.get("tab", "=")

    def _get_feature_identifier(fmt_type: str) -> str:
        return "" if (fmt_type or "").lower() == "kv" else _JSON_FEATURE_IDENTIFIER

    def _failed(error: str, total_valid_lines: int = 0) -> str:
        return json.dumps(
            {
                "status": "FAILED",
                "error": error,
                "log_format": normalize_log_format(format_type),
                "log_format_detail": format_detail or format_type,
                "feature_field": "__header__",
                "feature_identifier": kv_feature_identifier or _get_feature_identifier(format_type),
                "feature_count": 0,
                "total_valid_lines": total_valid_lines,
                "covered_lines": 0,
                "classification_details": [],
            },
            ensure_ascii=False,
        )

    if not logs_str or not logs_str.strip():
        return _failed("日志内容为空")

    # CHANGED: KV 格式时，用 LLM 生成 body 提取正则（feature_identifier）
    if is_kv:
        try:
            kv_feature_identifier = _generate_kv_feature_identifier(
                logs_str, kv_delimit, header_end_marker=header_end_marker
            )
        except ValueError:
            logger.error(
                "[classify_header_features] kv_body_regex_validation_failed; "
                f"valid_lines={len([line for line in logs_str.splitlines() if line.strip()])}"
            )
            return _failed("kv_body_regex_validation_failed")

    # CHANGED: 确定 KV 格式的键值连接符，用于 header 提取
    try:
        # 1) 结构样本：header 聚类降级为样本源，不再决定类型集合与计数（#190）
        clusters = aggregate_headers(
            logs_str, format_type=format_type, delimit=kv_delimit
        )["clusters"]
        sample_lines = [
            c["raw_sample"] for c in clusters if c.get("raw_sample")
        ][:_LOGTYPE_SAMPLE_LIMIT]
        if not sample_lines:
            logger.warning("[classify_header_features] 无结构样本（日志头聚合结果为空）")
            return _failed("日志头聚合结果为空")

        # 2) 类型提取正则：失败自动附错误反馈修复一次，再败即 FAILED（无自由枚举兜底）
        try:
            logtype_pattern = _generate_header_logtype_regex(
                sample_lines, format_type, kv_delimit
            )
        except ValueError:
            logger.error(
                "[classify_header_features] "
                "header_logtype_regex_validation_failed; "
                f"sample_count={len(sample_lines)}"
            )
            return _failed("header_logtype_regex_validation_failed")

        # 3) 确定性全量枚举：正则只作用于日志头文本，不同主结构行自然落入 unmatched
        # ponytail: 正则仅从 top 结构样本习得；共主导结构的文件次结构会进
        # unmatched 并报 PARTIAL，升级路径 = 按 cluster 迭代生成多个类型正则
        logtype_extractor = _make_header_logtype_extractor(
            logtype_pattern, format_type, kv_delimit
        )
        aggregation = aggregate_by_field(
            logs_str,
            "__header__",
            logtype_extractor,
            kv_delimit=kv_delimit if is_kv else None,
            header_end_marker="",  # 透传原始行：类型在日志头中，不得剥离
            is_json=False,
        )
        total_lines = aggregation.get("total_lines", 0)
        matched_lines = aggregation.get("matched_lines", 0)
        if matched_lines == 0:
            logger.warning("[classify_header_features] 类型提取正则未匹配到任何日志行")
            return _failed("类型提取正则未匹配到任何日志行", total_valid_lines=total_lines)

        # 4) 语义解释：复用 body 分类链路，分批 ≤20；批失败只降级 PARTIAL、类型不动
        from agent.tools.pipeline.log_classifier import (
            _build_coverage_block,
            _meaning_fill_batches,
        )

        try:
            fill = _meaning_fill_batches(
                aggregation,
                logs_str,
                format_type=format_type,
                format_detail=format_detail or format_type,
                feature_field="__header__",
                header_end_marker=header_end_marker,
                sample_format="kv" if is_kv else "json",
                extractor_func=logtype_extractor,
                feature_identifier=kv_feature_identifier,
                feature_body_group=1 if kv_feature_identifier else 0,
            )
        except Exception as e:
            logger.error(
                "[classify_header_features] semantic_classification_failed; "
                f"exception_type={type(e).__name__}; total_lines={total_lines}"
            )
            return _failed(
                "semantic_classification_failed",
                total_valid_lines=total_lines,
            )

        unmatched_lines = aggregation.get("unmatched_lines", 0)
        status = (
            "SUCCESS"
            if fill["status"] == "SUCCESS" and unmatched_lines == 0
            else "PARTIAL"
        )
        fail_reason = ""
        if status != "SUCCESS":
            fail_reason = (
                f"{unmatched_lines} 行未匹配任何类型"
                if unmatched_lines
                else fill.get("fail_reason") or "部分批次语义解释降级"
            )

        # 5) 组装结果：沿用 header 元数据契约 + coverage 四字段（format_info 优先）
        fi_delimit = (format_info or {}).get("delimit") if format_info else None
        fi_tab = (format_info or {}).get("tab") if format_info else None
        result = {
            "status": status,
            "fail_reason": fail_reason,
            "log_format": normalize_log_format(format_type),
            "log_format_detail": format_detail or format_type,
            "feature_field": "__header__",
            "feature_identifier": kv_feature_identifier or _get_feature_identifier(format_type),
            "feature_body_group": 1 if (is_kv and kv_feature_identifier) else 0,
            "feature_value_group": 0,
            "feature_count": fill["feature_count"],
            "total_valid_lines": total_lines,
            "covered_lines": matched_lines,
            "coverage": _build_coverage_block(aggregation),
            "classification_details": fill["classification_details"],
            "analysis": {
                "has_json_structure": not is_kv,
                "has_cef_prefix": False,
                "has_key_value_pairs": is_kv,
                "has_delimited_structure": False,
                "delimit": fi_delimit or "判断失败",
                "tab": fi_tab or "判断失败",
            },
            "categorical_features": "在日志头中",
            "Diversion_method": "日志头特征分类",
            "header_end_marker": header_end_marker,
        }
        logger.info(
            f"[classify_header_features] 全量枚举完成: types={fill['feature_count']}, "
            f"covered={matched_lines}/{total_lines}, unmatched={unmatched_lines}, "
            f"status={status}"
        )

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(
            "[classify_header_features] header_classification_failed; "
            f"exception_type={type(e).__name__}"
        )
        return _failed("header_classification_failed")
