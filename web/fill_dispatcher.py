"""
统一填充分流器 — 集中威胁填充/枚举填充的类型判定与执行。

替代 user_message_handlers 2.5段 + route_config 的填充类型猜测。
route_config 只返回 "fill"（不猜类型），本函数根据用户语义 + session 状态决定具体类型。

支持：
- 自然语言：「填充到alarm_category里」「威胁填充到event_type1」「枚举填充到content」
- 多字段迭代：填充后写回 mapped_sub_rules，后续填充基于上次结果（链式回写）
- 取消映射：「取消alarm_category的映射」
"""
import re

import chainlit as cl

from agent.shared.logger import get_logger
from agent.shared.mapping_utils import apply_fill_to_sub_rules, remove_field_mappings

logger = get_logger("fill_dispatcher")

# 填充指令里的目标字段提取正则：「填充到xxx里」「填充到xxx字段」「填充到xxx」
# [a-zA-Z0-9_]+ 只匹配 ASCII（避免匹配到中文「里」「字段」等后缀）
_TARGET_FIELD_RE = re.compile(r'填充(?:到|进)\s*([a-zA-Z0-9_]+)')

# 取消映射指令：「取消xxx的映射」「删除xxx的映射」「清除xxx的映射」
_REMOVE_RE = re.compile(r'(?:取消|删除|清除)\s*([\w_]+)\s*(?:的)?(?:映射|填充|枚举)?')


def _extract_target_field(user_text: str) -> str | None:
    """从用户文本提取目标字段名。

    「填充到alarm_category里」→ alarm_category
    「填充到event_type1字段」→ event_type1
    """
    m = _TARGET_FIELD_RE.search(user_text)
    if m:
        return m.group(1)
    return None


def _detect_fill_type(user_text: str, user_session) -> str:
    """判定填充类型（threat / enum）。

    优先级：
    1. 用户文本显式指定（「威胁填充」→ threat，「枚举填充」→ enum）
    2. last_fill_type 标记（最近一次映射是什么类型）
    3. 有 last_threat_data → threat；有 enum_excel_path → enum
    4. 默认 enum
    """
    lower = user_text.lower()

    # 1. 文本显式指定
    if "威胁" in user_text or "threat" in lower:
        return "threat"
    if "枚举" in user_text or "enum" in lower:
        return "enum"

    # 2. last_fill_type 标记
    last_type = user_session.get("last_fill_type") if user_session else None
    if last_type in ("threat", "enum"):
        return last_type

    # 3. session 状态推断
    if user_session:
        if user_session.get("last_threat_data"):
            return "threat"
        if user_session.get("enum_excel_path"):
            return "enum"

    # 4. 默认
    return "enum"


def _get_mapping_table(fill_type: str, user_session, target_field: str | None) -> tuple:
    """获取映射表。

    Returns:
        (mapping_table, error_msg)。mapping_table 为 dict（{field: [mappings]}）或 list。
        失败时 mapping_table 为 None，error_msg 为错误描述。
    """
    if fill_type == "threat":
        # 威胁填充：last_threat_data 或 threat_mapping_table
        threat_data = user_session.get("last_threat_data") or user_session.get("threat_mapping_table")
        if not threat_data:
            return None, "未找到威胁映射结果，请先执行威胁类型映射"
        return threat_data, None  # list 格式，apply_fill_to_sub_rules 会用 target_field 包装

    # 枚举填充：从 enum_excel_path 读取
    enum_excel_path = user_session.get("enum_excel_path")
    if not enum_excel_path:
        return None, "未找到枚举映射表，请先上传 Excel 映射表"
    from agent.tools.enum_field_tool import read_enum_mappings_from_excel
    mapping_table = read_enum_mappings_from_excel(enum_excel_path)
    if not mapping_table:
        return None, f"枚举映射表未读取到有效规则：{enum_excel_path}"
    return mapping_table, None  # dict 格式


async def handle_fill_from_params(
    user_session, target_field: str | None, fill_type: str, source: str | None = None
) -> bool:
    """填充分发核心接口 — 接收显式参数（ADR-0004 步骤指令自包含）。

    step_planner 从 PLAN 计划的 params 提取 target_field / fill_type 后调用本函数。
    内部不做正则提取、不做隐式类型推断——参数由调用方提供。

    Args:
        user_session: 会话状态
        target_field: 回填目标字段名（如 "vul_name"）。threat 类型必填，enum 可选
        fill_type: 填充类型（"threat" 或 "enum"）
        source: 数据来源（"threat"/"enum"，用于日志，可选）

    Returns:
        True 表示已处理（调用方应 return），False 表示未命中填充（无数据）
    """
    # 检查是否有可供填充的数据
    sub_rules = user_session.get("mapped_sub_rules")
    raw_base64 = user_session.get("raw_base64")

    if not sub_rules and not raw_base64:
        return False  # 无数据，不是填充场景

    # threat 类型必须有 target_field（last_threat_data 是 flat list，不知填到哪）
    if not target_field:
        if fill_type == "enum":
            logger.info("[FILL] 枚举填充未指定字段，用映射表 sheet 名作为目标字段")
        else:
            logger.info("[FILL] 威胁填充未指定目标字段，提示用户明确")
            await cl.Message(
                content="💡 请明确目标字段名，例如：`威胁填充到alarm_category里`"
            ).send()
            return True

    logger.info(f"[FILL] target_field={target_field}, fill_type={fill_type}, source={source}")

    # 获取映射表
    mapping_table, error_msg = _get_mapping_table(fill_type, user_session, target_field)
    if mapping_table is None:
        await cl.Message(content=f"❌ {error_msg}").send()
        return True

    # 执行填充（优先 mapped_sub_rules，链式回写）
    if sub_rules:
        try:
            updated_sub_rules = apply_fill_to_sub_rules(sub_rules, mapping_table, target_field)
            logger.info(f"[FILL] 填充应用成功（target={target_field}）")

            # 链式回写：更新 mapped_sub_rules，供后续填充使用
            user_session["mapped_sub_rules"] = updated_sub_rules

            # 导出下载
            from agent.tools.rule_generator import rules_to_base64_text
            base64_result = rules_to_base64_text(updated_sub_rules)
            logger.info(f"[FILL] 导出成功，长度: {len(base64_result)}")

            # 统计
            mapping_count = len(mapping_table) if isinstance(mapping_table, list) else sum(len(v) for v in mapping_table.values())
            await cl.Message(
                content=f"""✅ **字段填充完成！**

📊 **填充统计：**
- 目标字段：{target_field or '(映射表 sheet 名)'}
- 填充类型：{'威胁类型' if fill_type == "threat" else '枚举'}
- 映射数量：{mapping_count} 条
- 数据源：已映射子规则（链式更新）

💾 点击下方按钮下载填充后的配置文件。"""
            ).send()

            base64_file = cl.File(
                name=f"filled_{target_field or 'enum'}.txt",
                content=base64_result.encode('utf-8'),
                mime="text/plain",
            )
            await cl.Message(
                content="**📥 点击下载填充后的配置：**",
                elements=[base64_file]
            ).send()
            return True

        except Exception as e:
            logger.error(f"[FILL] 填充异常: {e}")
            import traceback
            logger.error(f"[FILL] 详细错误: {traceback.format_exc()}")
            await cl.Message(content=f"❌ 填充失败：{str(e)}").send()
            return True

    # 有 raw_base64 但无 sub_rules：走旧路径（Base64 填充）
    if fill_type == "enum" and raw_base64:
        logger.info("[FILL] 走枚举 Base64 填充路径")
        from web.enum_handler import execute_enum_fill
        await execute_enum_fill(user_session, raw_base64)
        return True

    return False


async def handle_fill_from_text(user_session, user_text: str) -> bool:
    """自然语言填充分流适配器 — 从 user_text 提取参数后调核心接口。

    单意图自然语言入口（detect_intent="fill"）调用。
    内部做正则提取 + 类型推断，然后调用 handle_fill_from_params。

    Args:
        user_session: 会话状态
        user_text: 用户自然语言文本

    Returns:
        True 表示已处理，False 表示未命中填充（无数据/无字段）
    """
    fill_type = _detect_fill_type(user_text, user_session)
    target_field = _extract_target_field(user_text)
    return await handle_fill_from_params(user_session, target_field, fill_type)


# 向后兼容别名：旧代码可能直接调 handle_fill
# 阶段 4（#20）统一替换后可移除
async def handle_fill(user_session, user_text: str) -> bool:
    """向后兼容入口，等价于 handle_fill_from_text。

    .. deprecated::
        新代码应直接调用 handle_fill_from_params（参数化）或 handle_fill_from_text（适配器）。
        本别名在 ADR-0004 阶段 4（#20）清理旧代码时移除。
    """
    return await handle_fill_from_text(user_session, user_text)


async def handle_remove_fill(user_session, user_text: str) -> bool:
    """取消字段映射（清空指定字段的 mappings）。

    「取消alarm_category的映射」→ 清空 alarm_category 的 mappings

    Returns:
        True 表示已处理
    """
    m = _REMOVE_RE.search(user_text)
    if not m:
        return False

    target_field = m.group(1)
    sub_rules = user_session.get("mapped_sub_rules")
    if not sub_rules:
        await cl.Message(content="❌ 未找到已映射的子规则数据").send()
        return True

    updated = remove_field_mappings(sub_rules, target_field)
    user_session["mapped_sub_rules"] = updated
    logger.info(f"[FILL] 已取消 {target_field} 的映射")

    from agent.tools.rule_generator import rules_to_base64_text
    base64_result = rules_to_base64_text(updated)
    await cl.Message(
        content=f"✅ **已取消 {target_field} 的映射**\n\n💾 点击下载更新后的配置文件。"
    ).send()

    base64_file = cl.File(
        name=f"removed_{target_field}.txt",
        content=base64_result.encode('utf-8'),
        mime="text/plain",
    )
    await cl.Message(content="**📥 点击下载：**", elements=[base64_file]).send()
    return True
