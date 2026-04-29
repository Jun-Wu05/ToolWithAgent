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

from src.logger import get_logger

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

    # 流式输出原文
    for i in range(0, len(result_content), 50):
        await msg.stream_token(result_content[i:i+50])
    await msg.update()
    return True


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