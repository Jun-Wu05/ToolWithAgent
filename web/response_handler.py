"""
响应处理器 — 解析 Team 返回结果并渲染 UI 表格/按钮

提供:
- process_team_response(result, user_lower, user_session, loading_msg, msg) → bool
- send_action_buttons(msg, mapping_data)
"""
import datetime
import io
import json

import chainlit as cl

from agent.shared.logger import get_logger

# 从本地 parsers 导入解析函数
from web.parsers import create_dataframe_elements, parse_json_mapping_result, parse_json_threat_result

logger = get_logger("response_handler")


async def process_team_response(
    result,
    user_lower: str,
    user_session: dict,
    loading_msg,
    msg
) -> bool:
    """
    解析 Team 返回结果：识别映射/威胁类型并渲染表格，或流式输出原文

    Returns:
        True 表示已处理（调用方可 return）
    """
    result_content = result.content if hasattr(result, 'content') else str(result)
    
    # v3: 兼容 output_schema 返回的 Pydantic 对象 → dict
    if not isinstance(result_content, str):
        if hasattr(result_content, 'model_dump'):          # Pydantic v2
            result_content = json.dumps(result_content.model_dump(), ensure_ascii=False)
        elif hasattr(result_content, 'dict'):              # Pydantic v1
            result_content = json.dumps(result_content.dict(), ensure_ascii=False)
        else:
            result_content = str(result_content)

    # [Step2 改造] 不再依赖用户消息关键词判断响应类型，
    # 而是尝试解析两种 JSON 格式，以实际解析结果为准。

    # 先尝试字段映射解析
    mapping_data = parse_json_mapping_result(result_content)
    
    if mapping_data:
        user_session["last_mapping_data"] = mapping_data
        matched_count = sum(1 for item in mapping_data if item.get("匹配状态") == "匹配成功")
        unmatched_count = len(mapping_data) - matched_count

        summary = f"""✅ **字段映射完成！**

📊 **映射统计：**
- 总字段数：{len(mapping_data)}
- 匹配成功：{matched_count} 个
- 未匹配：{unmatched_count} 个

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- ✏️ 点击单元格编辑系统属性名称
- 📥 导出CSV文件"""

        for i in range(0, len(summary), 50):
            await msg.stream_token(summary[i:i+50])
        await msg.update()

        elements = create_dataframe_elements(mapping_data)
        if elements:
            await cl.Message(
                content="**📋 字段映射表：**\n\n请确认映射结果，点击下方按钮填充到原始数据中。",
                elements=elements,
                actions=[
                    cl.Action(name="confirm_fill", label="✅ 确认填充", description="确认后将映射结果填充到原始数据", payload={})
                ]
            ).send()
        return True

    # 威胁类型结果处理（以实际解析结果为准）
    threat_data = parse_json_threat_result(result_content)
    if threat_data:
        logger.info("[HANDLE] 进入威胁类型处理分支")
        # 去重：以 (orgValue, mappingValue) 为键，保留首次出现
        seen = set()
        deduped = []
        for item in threat_data:
            key = (item.get("orgValue", ""), item.get("mappingValue", ""))
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        if len(deduped) < len(threat_data):
            logger.info(f"[HANDLE] 威胁类型去重: {len(threat_data)} -> {len(deduped)} 条")
        threat_data = deduped
        user_session["last_threat_data"] = threat_data
        threat_count = len(threat_data)

        summary = f"""✅ **威胁类型映射完成！**

📊 **映射统计：**
- 映射数量：{threat_count} 条

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- 📥 导出CSV文件"""

        for i in range(0, len(summary), 50):
            await msg.stream_token(summary[i:i+50])
        await msg.update()

        elements = create_dataframe_elements(threat_data)
        if elements:
            await cl.Message(
                content="**📋 威胁类型映射表：**\n\n请先输入目标字段名并上传Base64文件，然后点击下方按钮进行填充。",
                elements=elements,
                actions=[
                    cl.Action(name="fill_threat_with_field", label="📥 带字段填充", description="输入目标字段并上传Base64文件进行填充", payload={})
                ]
            ).send()
        return True

    # 两个解析都失败后，才检查拒绝响应（避免威胁JSON前面的中文解释触发误判）
    if not mapping_data and not threat_data:
        result_lower = result_content.lower()
        refusal_signatures = [
            ("请提供", "provide"), ("需要", "need"), ("无法", "cannot"),
            ("原始日志", "original log"), ("解码", "decode"), ("更多数据", "more data"),
            ("日志样本", "log sample"), ("缺少", "missing"), ("不足", "insufficient"),
        ]
        is_refusal = any(sig[0] in result_content for sig in refusal_signatures)
        if is_refusal:
            logger.warning("[HANDLE] 检测到 LLM 拒绝/索要数据响应，标记为重试候选")
            return False  # 返回 False 表示未成功处理，需要重试

    # 流式输出原文
    for i in range(0, len(result_content), 50):
        await msg.stream_token(result_content[i:i+50])
    await msg.update()
    return True


async def _check_session_action(result_content: str, user_session, msg) -> bool:
    """
    Agent 自决动作：检测 LLM 响应中的 [SESSION_ACTION:xxx] 标记并执行对应操作。

    支持的标记：
    - [SESSION_ACTION:clear] — 清空旧文件数据
    - [SESSION_ACTION:activate_enum_fill] — 激活枚举填充流程
    - [SESSION_ACTION:activate_threat_fill] — 激活威胁填充流程

    Returns:
        True 表示已执行操作，调用方应跳过后续处理。
    """
    # 清空数据
    if "[SESSION_ACTION:clear]" in result_content:
        logger.info("[SESSION_ACTION] Agent 判定需要清空会话旧数据，执行 clear_decoded_data()")
        if hasattr(user_session, "clear_decoded_data"):
            user_session.clear_decoded_data()
        else:
            for key in ["decoded_data", "decoded_fields", "simplified_data", "decoded_text",
                         "original_log", "uploaded_file_name", "uploaded_file_time"]:
                user_session.pop(key, None)
        clean_content = result_content.replace("[SESSION_ACTION:clear]", "").strip()
        await msg.stream_token(clean_content[:50])
        await msg.update()
        await cl.Message(
            content="🗑️ **会话数据已清空** — 旧文件字段数据已清除，请上传新文件继续处理。"
        ).send()
        return True

    # 激活枚举填充
    if "[SESSION_ACTION:activate_enum_fill]" in result_content:
        logger.info("[SESSION_ACTION] Agent 判定需要激活枚举填充")
        user_session["enum_fill_mode"] = True
        clean_content = result_content.replace("[SESSION_ACTION:activate_enum_fill]", "").strip()
        await msg.stream_token(clean_content[:50])
        await msg.update()
        # 委托 handle_enum_fill_flow（阶段1已让它支持 mapped_sub_rules 数据源）
        from web.enum_handler import handle_enum_fill_flow
        await handle_enum_fill_flow(user_session, "")
        return True

    # 激活威胁填充
    if "[SESSION_ACTION:activate_threat_fill]" in result_content:
        logger.info("[SESSION_ACTION] Agent 判定需要激活威胁填充")
        user_session["threat_fill_mode"] = True
        clean_content = result_content.replace("[SESSION_ACTION:activate_threat_fill]", "").strip()
        await msg.stream_token(clean_content[:50])
        await msg.update()
        from web.threat_handler import handle_threat_fill_flow
        await handle_threat_fill_flow(user_session, "")
        return True

    return False


async def send_action_buttons(msg, mapping_data: list):
    """发送操作按钮消息（Excel + JSON 下载）"""
    import pandas as pd

    # 创建Excel文件
    df = pd.DataFrame(mapping_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='字段映射表', index=False)
    excel_data = output.getvalue()

    # 创建CSV文件
    csv_content = df.to_csv(index=False, encoding='utf-8-sig')
    csv_bytes = csv_content.encode('utf-8-sig')

    # 保存到会话中供下载
    user_session = cl.user_session.get("user_session")
    user_session["excel_data"] = excel_data
    user_session["excel_filename"] = f"字段映射表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    # 发送Excel下载按钮
    excel_file = cl.File(
        name=user_session["excel_filename"],
        content=excel_data,
    )

    # 发送JSON复制内容
    json_str = json.dumps(mapping_data, ensure_ascii=False, indent=2)
    json_file = cl.File(
        name="映射结果.json",
        content=json_str.encode('utf-8'),
    )

    # 发送操作提示和下载元素
    action_msg = cl.Message(
        content="""
---

**📋 操作选项：**

- 📥 **下载 Excel** - 导出映射表为Excel文件
- 📋 **下载 JSON** - 复制映射结果为JSON格式
- 🔢 **复制内容** - 直接复制下方JSON字符串
""",
        elements=[excel_file, json_file]
    )
    await action_msg.send()

    # 发送可复制的JSON内容
    json_msg = cl.Message(
        content=f"```json\n{json_str}\n```"
    )
    await json_msg.send()