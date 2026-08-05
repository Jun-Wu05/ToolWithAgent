"""
Chainlit 用户消息处理器 - 从 chainlit_app.py 提取

本模块处理用户文本消息：
- 清空数据快捷键
- 意图检测（威胁、映射、枚举、日志解析）
- 调用对应的分流 handler
- 分批字段映射
- 通用 LLM 调用
"""

import asyncio
import chainlit as cl
from agent.shared.logger import get_logger

logger = get_logger("user_message_handlers")

# 从拆分模块导入业务函数
from web.route_config import (
    MAPPING_KEYWORDS, THREAT_KEYWORDS, ENUM_KEYWORDS,
    ENUM_EXTRACT_KEYWORDS, LOG_PARSER_KEYWORDS, detect_intent
)
from web.llm_client import call_team
from web.input_builder import build_llm_input
from web.response_handler import process_team_response, _check_session_action
from web.history_store import append_history
from web.threat_handler import handle_threat_fill_flow
from web.enum_handler import handle_enum_fill_flow, handle_enum_extract_flow
from web.log_parser_handler import handle_log_parser
from web.parsers import parse_json_mapping_result, create_dataframe_elements
from web.utils import content_to_str

# 延迟导入 action_callbacks 避免循环依赖
_action_callbacks = None


def get_action_callbacks():
    """延迟导入 action_callbacks 避免循环依赖"""
    global _action_callbacks
    if _action_callbacks is None:
        from web import action_callbacks
        _action_callbacks = action_callbacks
    return _action_callbacks


async def handle_user_message(user_session, team, user_text: str):
    """
    处理用户消息 - 主编排函数
    
    职责：
    1. 记录用户输入
    2. 清空/切换数据快捷路径
    3. 意图检测与分流
    4. 分批字段映射
    5. 通用 LLM 调用与重试
    
    Args:
        user_session: 用户会话状态
        team: Agno Team 实例
        user_text: 用户输入的文本
    """
    # 记录用户输入 + 追加到对话历史（让 Agent 记住多轮上下文）
    logger.info(f"[USER_INPUT] 用户消息: {user_text[:500]}")
    append_history(user_session, "user", user_text)
    
    user_lower = user_text.lower()
    
    # ====== 清空/切换数据快捷路径（避免LLM处理，秒级响应） ======
    _clear_keywords = ("清空", "切换数据", "新文件", "换一个", "换文件",
                       "重新上传", "丢弃", "丢掉", "清除数据", "clear", "reset",
                       "从头开始", "新建", "重开")
    if any(kw in user_lower for kw in _clear_keywords):
        logger.info(f"[SHORTCUT] 检测到清空/切换数据意图: {user_text[:100]}，执行快捷清空")
        await _clear_session_data(user_session)
        return
    # ====================================================================
    
    # 意图检测（带消歧规则的 detect_intent + 保留布尔标志用于早期分流）
    is_enum_extract = any(kw in user_lower for kw in ENUM_EXTRACT_KEYWORDS)
    is_log_parser = any(kw in user_lower for kw in LOG_PARSER_KEYWORDS)
    # enum/threat/mapping 的冲突消歧交给 detect_intent
    detected_intent, route_reason = detect_intent(user_text, user_session)
    is_enum = detected_intent == "enum"
    is_threat = detected_intent == "threat"
    is_mapping = detected_intent == "mapping"
    logger.info(f"[ROUTE] '{user_text[:60]}' → {detected_intent}（{route_reason}）")
    
    # 1. 威胁填充模式分流 → threat_handler（按钮驱动的两阶段流程）
    if await handle_threat_fill_flow(user_session, user_text):
        return

    # 2. 枚举填充模式分流 → enum_handler（按钮驱动的两阶段流程）
    if await handle_enum_fill_flow(user_session, user_text):
        return

    # 2.5 统一填充（自然语言驱动）：route_config 返回 "fill" 时委托 fill_dispatcher
    if detected_intent == "fill":
        from web.fill_dispatcher import handle_fill
        if await handle_fill(user_session, user_text):
            return

    # 2.6 取消字段映射：「取消xxx的映射」
    if any(kw in user_lower for kw in ("取消", "删除", "清除")) and "映射" in user_text:
        from web.fill_dispatcher import handle_remove_fill
        if await handle_remove_fill(user_session, user_text):
            return
    
    # 3. 枚举提取分流（精确匹配优先：含"提取"/"列举"/"列出"等词）
    if is_enum_extract:
        await handle_enum_extract_flow(user_session, team, user_text)
        return
    
    # 4. 枚举处理分流（宽泛匹配：仅含"枚举"但无提取意图）
    if is_enum:
        await cl.Message(
            content="""📋 **枚举字段处理**

请上传 **Excel 映射表** 文件来定义枚举映射规则。

Excel 格式说明：
- Sheet 名 = 目标字段名
- 第一列：mappingType（EQUAL 或 REGULAR）
- 第二列：orgValue（原始值）
- 第三列：mappingValue（映射值）

上传后将展示映射预览，确认后可执行填充。"""
        ).send()
        return
    
    # 4.5 日志解析分流
    if is_log_parser:
        await handle_log_parser(user_session, user_text)
        return
    
    # 5. 构建 LLM 输入（detected_intent 已由 detect_intent 带消歧规则确定）
    # detect_intent 未覆盖 log_parser 时兜底（日志解析早期分流可能已 return）
    if is_log_parser and detected_intent == "general":
        detected_intent = "log_parser"
    # ambiguous（威胁+映射无法消歧）→ 走 RouterAgent（当 general 处理，注入 session_context）
    if detected_intent == "ambiguous":
        logger.info("[ROUTE] 模糊意图，fallback RouterAgent（按 general 走 team.run）")
        detected_intent = "general"
    
    # ====== P2 自动分批：字段 > 25 时分批调用，避免超时 ======
    BATCH_SIZE = 25
    if detected_intent == "mapping":
        simplified_data = user_session.get("simplified_data", {})
        fields_list = simplified_data.get("fields", []) if isinstance(simplified_data, dict) else []
        
        if len(fields_list) > BATCH_SIZE:
            import math
            total_batches_preview = math.ceil(len(fields_list) / BATCH_SIZE)
            logger.info(f"[BATCH] 字段数 {len(fields_list)} > {BATCH_SIZE}，进入分批模式，共 {total_batches_preview} 批")

            loading_msg = cl.Message(content=f"⏳ **正在处理字段映射（第 1/{total_batches_preview} 批）...**")

            from web.batch_mapping_helper import run_batched_mapping
            all_mapping_data, total_batches = await run_batched_mapping(
                team=team,
                fields_list=fields_list,
                user_text=user_text,
                user_session=user_session,
                parse_fn=parse_json_mapping_result,
                batch_size=BATCH_SIZE,
                loading_msg=loading_msg,
            )
            
            if all_mapping_data:
                user_session["last_mapping_data"] = all_mapping_data
                
                matched_count = sum(1 for item in all_mapping_data if item.get("匹配状态") == "匹配成功")
                unmatched_count = len(all_mapping_data) - matched_count
                
                # 保存批量映射数据供 Excel 导出使用
                batch_mapping_results = [{
                    "rule_name": "批量映射",
                    "mappings": [
                        {
                            "原始字段名": item.get("原始字段名", ""),
                            "系统属性名称": item.get("系统属性名称", ""),
                            "匹配状态": item.get("匹配状态", "")
                        }
                        for item in all_mapping_data
                    ]
                }]
                user_session["batch_mapping_results"] = batch_mapping_results
                
                summary = f"""✅ **字段映射完成！（分 {total_batches} 批处理）**

📊 **映射统计：**
- 总字段数：{len(all_mapping_data)}
- 匹配成功：{matched_count} 个
- 未匹配：{unmatched_count} 个

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- ✏️ 点击单元格编辑系统属性名称
- 📥 导出CSV文件"""
                
                msg = cl.Message(content="")
                await msg.send()
                for i in range(0, len(summary), 50):
                    await msg.stream_token(summary[i:i + 50])
                await msg.update()
                
                elements = create_dataframe_elements(all_mapping_data)
                if elements:
                    await cl.Message(
                        content="**📋 字段映射表：**\n\n请确认映射结果，点击下方按钮填充到原始数据中。",
                        elements=elements,
                        actions=[
                            cl.Action(name="confirm_fill", label="✅ 确认填充", description="确认后将映射结果填充到原始数据", payload={}),
                            cl.Action(
                                name="export_batch_field_mapping_excel",
                                label="📥 导出字段映射 Excel",
                                description="下载字段映射表为 Excel 文件",
                                payload={}
                            ),
                        ]
                    ).send()
                return
            else:
                await cl.Message(content="❌ 所有批次均未返回有效映射结果，请缩短输入内容或联系管理员。").send()
                return
    # ====================================================================
    
    full_input = build_llm_input(user_text, user_session, intent=detected_intent)
    
    # 6. 发送 loading 消息
    loading_msg = cl.Message(content="⏳ **AI正在处理中，请稍候...**\n\n💭 正在分析您的请求...")
    await loading_msg.send()
    
    max_retries = 2
    for retry_attempt in range(max_retries + 1):
        try:
            # 7. 调用 Team → llm_client（传递 intent 跳过 RouterAgent）
            result = await call_team(team, full_input, loading_msg, intent=detected_intent)
            
            # 7.5 Agent 自决清空：检测 [SESSION_ACTION:clear] 标记
            result_content = result.content if hasattr(result, 'content') else result
            result_content = content_to_str(result_content)
            session_action_cleared = await _check_session_action(result_content, user_session, loading_msg)
            if session_action_cleared:
                # Agent 判定需要清空会话，已通过 _check_session_action 发送通知
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                return
            
            # 8. 删除 loading 消息（重试时不删除，保留状态）
            if retry_attempt == 0:
                await loading_msg.remove()
            else:
                # 重试前更新 loading 消息
                try:
                    loading_msg.content = f"⏳ **AI正在重新分析，请稍候...**\n\n⚠️ 上次未返回有效结果，尝试 {retry_attempt + 1}/{max_retries + 1}"
                    await loading_msg.update()
                except Exception:
                    pass
            
            # 9. 创建流式消息显示结果
            msg = cl.Message(content="")
            await msg.send()
            
            # 10. 解析响应 → response_handler（传 intent 让 general 跳过 JSON 解析）
            handled = await process_team_response(result, user_lower, user_session, loading_msg, msg, intent=detected_intent)
            
            # 11. 如果成功处理，退出重试循环
            if handled:
                # 确保 loading 消息被移除
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                return
            
            # 12. 未成功处理（LLM 拒绝响应），记录并重试
            if retry_attempt < max_retries:
                logger.warning(
                    f"[HANDLE] LLM 未返回有效结果（尝试 {retry_attempt + 1}/{max_retries + 1}），"
                    f"重试，提示数据已提供但允许说明缺失项"
                )
                # 重试指令：数据已提供，但允许 LLM 说明具体缺什么（而非一律禁止提问）
                full_input = (
                    f"[SYSTEM NOTE: 所有数据已在上述消息中提供。请基于现有数据完成处理。"
                    f"如果确实缺少关键字段，请明确说明需要哪个字段及其用途，而非笼统索要数据。]\n\n{full_input}"
                )
                try:
                    await msg.remove()
                except Exception:
                    pass
            else:
                # 最后一次重试也失败，移除 loading
                try:
                    await loading_msg.remove()
                except Exception:
                    pass
                raise RuntimeError(
                    f"LLM 在 {max_retries + 1} 次尝试中均未返回有效的映射/处理结果，"
                    f"请缩短输入内容或联系管理员。"
                )
        
        except asyncio.TimeoutError as e:
            logger.error(f"Team调用超时: {e}")
            try:
                await loading_msg.remove()
            except Exception:
                pass
            await cl.Message(
                content=f"⏰ **请求超时**\n\nLLM 在 120 秒内未返回结果，请稍后重试。\n\n"
                        f"建议：减少上传数据量或检查网络连接。"
            ).send()
            return
        
        except Exception as e:
            logger.error(f"Team调用异常: {e}")
            try:
                await loading_msg.remove()
            except Exception:
                pass
            await cl.Message(content=f"❌ 处理异常：{str(e)}").send()
            return


async def _clear_session_data(user_session):
    """清空会话数据"""
    # 清空解码数据
    if hasattr(user_session, "clear_decoded_data"):
        user_session.clear_decoded_data()
    else:
        for key in ["decoded_data", "decoded_fields", "simplified_data",
                     "decoded_text", "original_log", "uploaded_file_name",
                     "uploaded_file_time", "last_mapping_data", "last_threat_data"]:
            user_session.pop(key, None)
    
    await cl.Message(
        content="🗑️ **数据已清空** — 请上传新文件继续处理。"
    ).send()