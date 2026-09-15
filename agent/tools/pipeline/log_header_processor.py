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


def _validate_regex(regex_str: str, sample_line: str) -> tuple[bool, str, str]:
    """验证正则：编译 + 匹配 + 恰好 1 个捕获组。

    Args:
        regex_str: 待验证的正则字符串。
        sample_line: 样例日志行。

    Returns:
        (is_valid, error_msg, body_preview)
        - is_valid: 验证是否通过。
        - error_msg: 失败原因（成功时为空字符串）。
        - body_preview: 提取到的 body 前 100 字符（成功时）。
    """
    # 编译检查
    try:
        pattern = _re.compile(regex_str)
    except _re.error as e:
        return False, f"正则编译失败: {e}", ""

    # 匹配检查
    m = pattern.search(sample_line)
    if not m:
        return False, "正则无法匹配样例日志", ""

    # 捕获组检查
    if len(m.groups()) != 1:
        return False, f"正则捕获组数≠1 (实际={len(m.groups())})", ""

    return True, "", m.group(1)[:100]


def _generate_kv_feature_identifier(logs_str: str) -> str:
    """用 LLM 生成 KV body 提取正则（单个捕获组，Group1 = KV body）。

    CHANGED (2026-06-18): 增加重试机制（最多 1 次重试），重试时将错误反馈
                          拼入 prompt，并输出详细调试日志。失败仍抛出异常，
                          不使用兜底策略。

    Args:
        logs_str: 原始日志字符串（多行）。

    Returns:
        正则字符串，失败抛出 ValueError。

    Raises:
        ValueError: 所有重试均失败时抛出。
    """
    lines = [l.strip() for l in logs_str.strip().split("\n") if l.strip()]
    if not lines:
        raise ValueError("日志内容为空，无法生成 feature_identifier")

    sample_line = lines[0]
    base_prompt = load_kv_feature_identifier_prompt()

    max_attempts = 2  # 初次 + 1 次重试
    last_error = ""
    last_regex = ""

    for attempt in range(1, max_attempts + 1):
        logger.debug(f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} 开始")

        # CHANGED: 重试时附加错误反馈
        prompt = base_prompt.replace("{sample_log}", sample_line)
        if attempt > 1 and last_error:
            feedback = (
                f"\n\n# ⚠️ 上次生成的正则有误，请修正\n"
                f"- 上次错误：{last_error}\n"
                f"- 上次正则：`{last_regex}`\n"
                f"- 样例日志：`{sample_line[:200]}`\n"
                f"\n请仔细检查样例日志中各部分的实际分隔情况，重新生成。"
            )
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
            last_error = f"LLM API 调用失败: {e}"
            last_regex = ""
            logger.debug(
                f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
                f"LLM 调用异常: {e}"
            )
            continue

        logger.debug(
            f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
            f"LLM 原始响应: {response[:200]}"
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
            f"解析得到正则: {regex_str}"
        )

        # 验证正则
        is_valid, err_msg, body_preview = _validate_regex(regex_str, sample_line)
        if is_valid:
            logger.info(
                f"[_generate_kv_feature_identifier] 生成成功 (尝试 {attempt}/{max_attempts}): {regex_str}"
            )
            logger.info(f"[_generate_kv_feature_identifier] body 提取: {body_preview}...")
            return regex_str
        else:
            last_error = err_msg
            last_regex = regex_str
            logger.debug(
                f"[_generate_kv_feature_identifier] 尝试 {attempt}/{max_attempts} "
                f"验证失败: {err_msg}（正则: {regex_str}）"
            )

    raise ValueError(
        f"正则生成失败（共尝试 {max_attempts} 次），最后错误: {last_error}"
    )


# 结构样本上限（#190）：header 聚类降级为结构样本源，最多取 20 条供正则生成
_LOGTYPE_SAMPLE_LIMIT = 20


def _validate_logtype_regex(regex_str: str, header_texts: list[str]) -> tuple[bool, str, str]:
    """校验类型提取正则：编译 + 恰 1 捕获组 + 对全部结构样本提取非空值。"""
    try:
        pattern = _re.compile(regex_str)
    except _re.error as e:
        return False, f"正则编译失败: {e}", ""
    if pattern.groups != 1:
        return False, f"正则捕获组数≠1 (实际={pattern.groups})", ""
    preview = ""
    for text in header_texts:
        m = pattern.search(text)
        if not m:
            return False, f"正则无法匹配结构样本: {text[:60]}", ""
        value = (m.group(1) or "").strip()
        if not value:
            return False, f"捕获值为空: {text[:60]}", ""
        preview = value[:100]
    return True, "", preview


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
            prompt += (
                f"\n\n# ⚠️ 上次生成的正则有误，请修正\n"
                f"- 上次错误：{last_error}\n"
                f"- 上次正则：`{last_regex}`\n"
                f"\n请重新观察样例结构，生成泛化的类型路径提取正则。"
            )
        try:
            response = _call_llm_direct(
                prompt, temperature=0.1, max_tokens=500, timeout=30, force_json=False
            )
        except Exception as e:
            last_error, last_regex = f"LLM API 调用失败: {e}", ""
            logger.debug(
                f"[_generate_header_logtype_regex] 尝试 {attempt}/{max_attempts} "
                f"LLM 调用异常: {e}"
            )
            continue

        regex_str = _parse_regex_response(response)
        if not regex_str:
            last_error, last_regex = "LLM 输出无法解析为正则", response[:200]
            continue

        is_valid, err_msg, preview = _validate_logtype_regex(regex_str, header_texts)
        if is_valid:
            logger.info(
                f"[_generate_header_logtype_regex] 生成成功 "
                f"(尝试 {attempt}/{max_attempts}): {regex_str}（示例值: {preview}）"
            )
            return _re.compile(regex_str)
        last_error, last_regex = err_msg, regex_str
        logger.debug(
            f"[_generate_header_logtype_regex] 尝试 {attempt}/{max_attempts} "
            f"验证失败: {err_msg}（正则: {regex_str}）"
        )

    raise ValueError(
        f"日志类型提取正则生成失败（共尝试 {max_attempts} 次），最后错误: {last_error}"
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
            kv_feature_identifier = _generate_kv_feature_identifier(logs_str)
        except ValueError as e:
            logger.error(f"[classify_header_features] KV feature_identifier 生成失败: {e}")
            return _failed(f"KV feature_identifier 生成失败: {e}")

    # CHANGED: 确定 KV 格式的键值连接符，用于 header 提取
    kv_delimit = "="
    if is_kv and format_info:
        kv_delimit = format_info.get("tab", "=")

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
        except ValueError as e:
            logger.error(f"[classify_header_features] {e}")
            return _failed(f"日志类型提取正则生成失败: {e}")

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
            )
        except Exception as e:
            logger.error(
                f"[classify_header_features] 语义解释失败: {type(e).__name__}: {e}"
            )
            return _failed(f"LLM 语义分类失败: {e}", total_valid_lines=total_lines)

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
                else "部分批次语义解释降级"
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

        if status == "SUCCESS":
            try:
                from agent.tools.log_pattern_store import (
                    generate_structured_fingerprint,
                    store_log_knowledge,
                )
                structured_fp = generate_structured_fingerprint(
                    classify_result=result, format_detail=format_detail,
                    feature_field="__header__",
                )
                if structured_fp:
                    _sl = [l for l in logs_str.strip().split("\n") if l.strip()][:10]
                    store_log_knowledge(
                        fingerprint=structured_fp, format_type=format_type,
                        meta=result, sample_logs=_sl,
                    )
                    logger.info(f"[classify_header_features] 知识库存储成功: {structured_fp[:80]}...")
            except Exception as store_err:
                logger.warning(f"[classify_header_features] 知识库存储失败: {store_err}")

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[classify_header_features] 异常: {type(e).__name__}: {e}")
        return _failed(str(e))
