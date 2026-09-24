"""
Application LLM 输入构建 — 为字段映射批处理拼接专业 Agent 输入文本。

提供:
- build_batch_llm_input(user_text, user_session, fields_batch, batch_idx, total_batches) → str
"""
import json

from agent.shared.logger import get_logger
from agent.core.field_retriever import batch_retrieve_candidates

logger = get_logger("input_builder")


def _pre_query_field_candidates(fields_list: list) -> str:
    """
    语义检索候选，返回紧凑格式字符串（空字符串表示无候选）。

    异常直接抛出（不吞），让调用方感知 embedding API 故障，
    避免无候选时 LLM 产生幻觉映射（如自造"天眼ID"）。

    Args:
        fields_list: 原始字段名列表

    Returns:
        紧凑格式候选字符串（LLM 可读），无候选时返回 ""

    Raises:
        RuntimeError: embedding API 调用失败时抛出
    """
    if not fields_list:
        return ""
    result = batch_retrieve_candidates(fields_list, top_k=5)
    if result and result.strip():
        logger.info(f"[PRE_QUERY] 语义检索完成，{len(fields_list)} 个字段")
        return result
    return ""


def _render_value_profiles(value_profiles: dict, fields_batch: list) -> str:
    """把按字段分组的值画像渲染为紧凑文本块（#189 第一阶段证据增强）。

    画像对象鸭子类型：owner/field/values/empty_count/scanned_lines/hit_lines/source。
    只渲染当前批次字段；块内只含去重值与计数，不包含任何原始日志行。
    """
    lines: list[str] = []
    for name in fields_batch:
        profiles = value_profiles.get(name) or []
        if not profiles:
            continue
        entries = []
        for profile in profiles:
            values_text = ", ".join(
                f"{value}×{count}" for value, count in list(profile.values.items())[:10]
            )
            entries.append(
                f"  · {profile.owner}（来源 {profile.source}，扫描 {profile.scanned_lines} 行，"
                f"命中 {profile.hit_lines} 行，空值 {profile.empty_count} 个）：{values_text}"
            )
        lines.append(f"- 字段 {name}：\n" + "\n".join(entries))
    if not lines:
        return ""
    return (
        "📋 字段值画像（按日志类型分组，由代码全量扫描提供，"
        "仅用于辅助判断字段语义与值域）：\n" + "\n".join(lines)
    )


def build_batch_llm_input(user_text: str, user_session: dict, fields_batch: list,
                          batch_idx: int, total_batches: int,
                          prequery=None, value_profiles=None) -> str:
    """
    构建分批字段的 LLM 输入（用于 >50 字段场景，每批独立调用 Team）

    Args:
        user_text: 用户请求文本
        user_session: 用户会话
        fields_batch: 当前批次的字段列表
        batch_idx: 当前批次索引（1-based）
        total_batches: 总批次数
        prequery: 可选候选检索函数（Issue #88 注入接缝）；缺省用模块默认
            ``_pre_query_field_candidates``，测试可构造注入假件替代 monkeypatch
        value_profiles: 可选字段值画像（#189 注入接缝）：{原始字段名: [画像, ...]}。
            缺省 None 时输出与历史逐字节一致；传入时只为批次内字段追加画像块

    Returns:
        完整 LLM 输入字符串（字段批次 + 语义候选 + 值画像 + 原始日志样本）
    """
    simplified_data = user_session.get("simplified_data", {})
    original_log_sample = simplified_data.get("original_log_sample", "")

    fields_json_str = json.dumps(fields_batch, ensure_ascii=False)

    # 对当前批次字段做语义检索（注入优先，未注入时回落模块默认实现）
    retriever = prequery or _pre_query_field_candidates
    try:
        pre_query_candidates = retriever(fields_batch)
    except RuntimeError as e:
        logger.warning(f"[BATCH] 第 {batch_idx}/{total_batches} 批语义检索失败: {e}")
        pre_query_candidates = ""

    full_input = f"""用户请求：{user_text}

📋 当前批次字段列表（第 {batch_idx}/{total_batches} 批，共 {len(fields_batch)} 个字段）：
{fields_json_str}"""

    if pre_query_candidates:
        full_input += f"\n\n{pre_query_candidates}\n"

    if value_profiles:
        profiles_block = _render_value_profiles(value_profiles, fields_batch)
        if profiles_block:
            full_input += f"\n{profiles_block}\n"

    if original_log_sample:
        sample_str = (original_log_sample
                      if len(original_log_sample) <= 2000
                      else original_log_sample[:2000] + "...(已截断)")
        full_input += f"""

📋 原始日志样本（理解字段语义，所有批次共享同一份样本）：
{sample_str}"""

    logger.info(f"[BATCH] 第 {batch_idx}/{total_batches} 批输入构建完成，{len(fields_batch)} 个字段")
    return full_input
