"""
LLM 输入构建 — 将用户请求与上传数据拼接为 Team 的输入文本

提供:
- build_llm_input(user_text, user_session, intent) → str
"""
import json

from agent.shared.logger import get_logger
from agent.core.field_retriever import batch_retrieve_candidates
from web.history_store import format_history_for_prompt

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


def build_llm_input(user_text: str, user_session: dict, intent: str = "general") -> str:
    """
    构建发送给 LLM / Team 的完整输入。

    Args:
        user_text: 用户输入的文本
        user_session: 用户会话状态
        intent: 意图类型 — "threat"（威胁类型处理）/ "mapping"（字段映射）/ "general"（通用路由）

    上下文隔离原则：
    - intent="threat"：只传用户文本，不拼接字段数据（避免旧缓存污染威胁处理）
    - intent="mapping"：拼接字段数据 + 日志样本，供 LLM 做字段映射
    - intent="general"：由 RouterAgent 自己判断
    """
    # 威胁类型处理：上下文隔离 — 不拼字段数据，但结构化注入上一步的枚举值（若有）
    # CHANGED (2026-07-28): threat 路径显式注入 last_enum_extract_result 的枚举值，
    # 让 ThreatAgent 直接拿到要映射的数据，而非依赖被截断的对话历史回忆。
    if intent == "threat":
        history_block = format_history_for_prompt(user_session)
        # 结构化注入枚举值（来自上一步「提取枚举值」）
        enum_result = user_session.get("last_enum_extract_result") or {}
        enum_values = enum_result.get("value", []) if isinstance(enum_result, dict) else []
        enum_context = ""
        if enum_values:
            values_text = "\n".join(f"- {v}" for v in enum_values)
            enum_context = f"\n\n📋 待映射的枚举值（来自上一步提取，共 {len(enum_values)} 个）：\n{values_text}"
            logger.info(f"[LLM_INPUT] 威胁路由：注入 {len(enum_values)} 个枚举值")

        if history_block or enum_context:
            logger.info(f"[LLM_INPUT] 威胁路由：拼接历史（{len(history_block)} 字符）+ 枚举上下文 + 用户文本")
            return f"{history_block}{enum_context}\n\n用户请求：{user_text}"
        logger.info(f"[LLM_INPUT] 威胁路由：仅传递用户文本（长度: {len(user_text)}）")
        return user_text

    # 映射 / 通用路由：拼接字段数据
    has_data = user_session.get("decoded_data") or user_session.get("decoded_fields")

    if has_data:
        simplified_data = user_session.get("simplified_data", {})
        fields_list = simplified_data.get("fields", [])
        original_log_sample = simplified_data.get("original_log_sample", "")

        # CHANGED (2026-07-28): 优先用日志真实字段（uuid/srcIp/...），而非 Excel 列头
        # （decoded_fields/simplified_data.fields 存的是「发生时间/事件名称」等列头）。
        # CHANGED (2026-07-29): 从仅 mapping 扩展到 mapping+general，两条路径都用日志字段。
        if intent in ("mapping", "general"):
            from web.field_source import extract_log_fields_for_mapping
            log_fields = extract_log_fields_for_mapping(
                user_session.get("log_classification"),
                user_session.get("raw_log_lines"),
            )
            if log_fields:
                fields_list = log_fields
                logger.info(f"[LLM_INPUT] {intent} 意图：使用日志真实字段（{len(fields_list)} 个），而非 Excel 列头")

        fields_json_str = json.dumps(fields_list, ensure_ascii=False)

        # 上下文长度控制：字段列表超长时摘要显示（>30 个字段或 JSON >4000 字符）
        # 映射任务走分批路径（>25 字段），此处 general 意图无需完整列表
        _FIELDS_SUMMARY_THRESHOLD = 4000
        _FIELDS_PREVIEW_COUNT = 30
        if len(fields_json_str) > _FIELDS_SUMMARY_THRESHOLD:
            preview_fields = fields_list[:_FIELDS_PREVIEW_COUNT]
            fields_json_str = (
                json.dumps(preview_fields, ensure_ascii=False)
                + f"\n...（共 {len(fields_list)} 个字段，已截断显示前 {_FIELDS_PREVIEW_COUNT} 个）"
            )
            logger.info(f"[LLM_INPUT] 字段列表超长，摘要显示：{len(fields_list)} 个字段 → 前 {_FIELDS_PREVIEW_COUNT} 个")

        # 语义检索候选：仅在 mapping 意图时预查询（general 不需要，省 embedding API 调用）
        pre_query_candidates = ""
        if intent == "mapping":
            try:
                pre_query_candidates = _pre_query_field_candidates(fields_list)
            except RuntimeError as e:
                # embedding API 故障时降级：不带候选继续（避免 crash）
                logger.warning(f"[LLM_INPUT] 语义检索候选获取失败，降级为无候选输入: {e}")

        # ====== Agent 自决动作 — general 意图下注入会话摘要 + 动作标记说明 ======
        session_context = ""
        if intent == "general":
            session_summary = user_session.get_session_summary() if hasattr(user_session, "get_session_summary") else ""
            if session_summary:
                session_context = f"""
📋 当前会话状态：
{session_summary}

⚠️ 可用动作标记（仅在需要时输出，放在回复末尾）：
- [SESSION_ACTION:clear] — 用户要切换/清空数据时输出，系统自动清空旧文件数据
- [SESSION_ACTION:activate_enum_fill] — 用户要做枚举填充时输出，系统自动激活填充流程
- [SESSION_ACTION:activate_threat_fill] — 用户要做威胁填充时输出，系统自动激活填充流程
"""
                logger.info(f"[LLM_INPUT] General 意图：注入会话摘要 + 动作标记（字段数: {len(fields_list)}）")
        # ========================================================================

        full_input = f"""用户请求：{user_text}
{session_context}
📋 可用数据字段列表：
{fields_json_str}"""

        # 拼接对话历史（让 Agent 感知之前的交互，如已上传文件、已完成映射）
        history_block = format_history_for_prompt(user_session)
        if history_block:
            full_input = f"{history_block}\n\n{full_input}"
            logger.info(f"[LLM_INPUT] 已拼接对话历史（{len(history_block)} 字符）")

        # 注入预查询的候选字段数据
        if pre_query_candidates:
            full_input += f"\n\n{pre_query_candidates}\n"

        if original_log_sample:
            sample_str = original_log_sample if len(original_log_sample) <= 2000 else original_log_sample[:2000] + "...(已截断)"
            full_input += f"""

📋 原始日志样本（用于理解字段语义）：
{sample_str}"""
        else:
            # 无日志样本时，提供解码后的原始 JSON 内容作为数据上下文（字段名+值）
            decoded_text = user_session.get("decoded_text", "")
            if not decoded_text:
                # 兜底：从 decoded_data（即 decoded_json）重建
                decoded_data = user_session.get("decoded_data", {})
                if decoded_data:
                    decoded_text = json.dumps(decoded_data, ensure_ascii=False)
            if decoded_text:
                context_str = decoded_text if len(decoded_text) <= 3000 else decoded_text[:3000] + "...(已截断)"
                full_input += f"""

📋 解码后的原始数据（包含字段值，用于理解字段语义）：
{context_str}"""

        logger.info(f"[LLM_INPUT] 发送给LLM的字段列表: {fields_json_str[:500]}...")
    else:
        # 无数据场景：拼接历史 + 用户文本（让 Agent 至少知道之前聊了什么）
        history_block = format_history_for_prompt(user_session)
        if history_block:
            full_input = f"{history_block}\n\n用户请求：{user_text}"
        else:
            full_input = user_text

    logger.info(f"[LLM_INPUT] 输入构建完成，总长度: {len(full_input)} 字符")
    return full_input


def build_batch_llm_input(user_text: str, user_session: dict, fields_batch: list,
                          batch_idx: int, total_batches: int) -> str:
    """
    构建分批字段的 LLM 输入（用于 >50 字段场景，每批独立调用 Team）

    Args:
        user_text: 用户请求文本
        user_session: 用户会话
        fields_batch: 当前批次的字段列表
        batch_idx: 当前批次索引（1-based）
        total_batches: 总批次数

    Returns:
        完整 LLM 输入字符串（结构同 build_llm_input 的 mapping 分支）
    """
    simplified_data = user_session.get("simplified_data", {})
    original_log_sample = simplified_data.get("original_log_sample", "")

    fields_json_str = json.dumps(fields_batch, ensure_ascii=False)

    # 对当前批次字段做语义检索
    try:
        pre_query_candidates = _pre_query_field_candidates(fields_batch)
    except RuntimeError as e:
        logger.warning(f"[BATCH] 第 {batch_idx}/{total_batches} 批语义检索失败: {e}")
        pre_query_candidates = ""

    full_input = f"""用户请求：{user_text}

📋 当前批次字段列表（第 {batch_idx}/{total_batches} 批，共 {len(fields_batch)} 个字段）：
{fields_json_str}"""

    if pre_query_candidates:
        full_input += f"\n\n{pre_query_candidates}\n"

    if original_log_sample:
        sample_str = (original_log_sample
                      if len(original_log_sample) <= 2000
                      else original_log_sample[:2000] + "...(已截断)")
        full_input += f"""

📋 原始日志样本（理解字段语义，所有批次共享同一份样本）：
{sample_str}"""

    logger.info(f"[BATCH] 第 {batch_idx}/{total_batches} 批输入构建完成，{len(fields_batch)} 个字段")
    return full_input
