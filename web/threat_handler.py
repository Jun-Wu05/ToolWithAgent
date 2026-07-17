"""
威胁类型填充处理器 — 威胁填充模式分流与执行

提供:
- handle_threat_fill_flow(user_session, user_text) → bool   (分流入口)
- execute_threat_fill(user_session, file_content) → None    (Base64 执行填充)
- _try_execute_threat_fill(user_session, target_field) → bool (数据源优先级封装)
"""
import json

import chainlit as cl

from agent.shared.logger import get_logger
from agent.shared.threat_fill import apply_threat_mapping, export_to_base64
from agent.shared.mapping_utils import apply_fill_to_sub_rules

logger = get_logger("threat_handler")


async def handle_threat_fill_flow(user_session: dict, user_text: str) -> bool:
    """
    威胁填充模式专属流程

    在用户已触发"带字段填充"按钮后，处理后续消息流：
    1. 读取目标字段名
    2. 等待用户上传 Base64 文件

    Returns:
        True 表示已处理（调用方应直接 return），False 表示未命中威胁填充模式
    """
    # ====== 威胁填充模式 ======
    if user_session.get("threat_fill_mode") is True:
        # 阶段1: 用户输入字段名
        target_field = user_session.get("threat_target_field")
        if not target_field:
            # 用户输入字段名
            field_text = user_text.strip().replace("目标字段:", "").replace("字段:", "").strip()
            if field_text:
                user_session["threat_target_field"] = field_text
                logger.info(f"[HANDLE] 目标字段设置为: {field_text}")
                # 尝试用已有数据执行填充（mapped_sub_rules > pending_base64 > raw_base64）
                if not await _try_execute_threat_fill(user_session, field_text):
                    # 所有数据源都没命中 → 提示上传
                    await cl.Message(
                        content=f"✅ 目标字段已设置为：**{field_text}**\n\n现在请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"
                    ).send()
            else:
                await cl.Message(
                    content="⚠️ 请输入有效的字段名，例如：`original_log`"
                ).send()
            return True

        # 阶段2: 用户上传文件（由 on_message 中的文件处理逻辑处理）
        logger.info(f"[HANDLE] 威胁填充模式，等待Base64上传，目标字段: {target_field}")
        await cl.Message(
            content=f"""📌 **威胁填充模式**
目标字段：**{target_field}**
已在等待上传 Base64 文件，请直接上传您的配置文件来填充。"""
        ).send()
        return True

    return False


async def _try_execute_threat_fill(user_session, target_field: str) -> bool:
    """尝试用已有数据执行威胁填充（不要求重传）。

    数据源优先级：mapped_sub_rules > pending_base64 > raw_base64。
    成功执行返回 True；所有数据源都没命中返回 False（调用方提示上传）。
    """
    # 优先 mapped_sub_rules（字段映射产出，支持链式回写）
    sub_rules = user_session.get("mapped_sub_rules")
    if sub_rules:
        logger.info("[HANDLE] 检测到 mapped_sub_rules，直接用子规则填充（无需重传）")
        await _execute_threat_fill_with_sub_rules(user_session, sub_rules, target_field)
        return True

    # pending_base64（用户先传文件后输字段名的场景）
    pending = user_session.pop("pending_base64", None)
    if pending:
        logger.info("[HANDLE] 检测到 pending_base64，执行填充")
        try:
            await execute_threat_fill(user_session, pending)
        except Exception:
            user_session["pending_base64"] = pending  # 失败恢复
            raise
        return True

    # raw_base64 缓存
    raw_base64 = user_session.get("raw_base64")
    if raw_base64:
        logger.info("[HANDLE] 检测到 raw_base64 缓存，执行填充")
        await execute_threat_fill(user_session, raw_base64)
        return True

    return False


async def _execute_threat_fill_with_sub_rules(user_session, sub_rules: list, target_field: str):
    """用已有 mapped_sub_rules 执行威胁填充（复用 apply_fill_to_sub_rules + 链式回写）。"""
    from agent.tools.rule_generator import rules_to_base64_text

    logger.info(f"[threat_fill_sub_rules] 开始（target={target_field}）")
    threat_data = user_session.get("threat_mapping_table") or user_session.get("last_threat_data")

    if not threat_data:
        await cl.Message(content="❌ 威胁映射数据丢失，请重新执行威胁类型映射").send()
        return

    try:
        # 威胁映射表是 flat list，包装为 {target_field: mappings} 供 apply_fill_to_sub_rules 使用
        mapping_table = {target_field: threat_data}
        updated_sub_rules = apply_fill_to_sub_rules(sub_rules, mapping_table, target_field)
        logger.info("[threat_fill_sub_rules] 填充应用成功")

        # 链式回写：后续填充基于本次结果
        user_session["mapped_sub_rules"] = updated_sub_rules

        # 重置威胁填充模式
        user_session["threat_fill_mode"] = False
        user_session["threat_target_field"] = None
        user_session["threat_mapping_table"] = None

        # 导出下载
        base64_result = rules_to_base64_text(updated_sub_rules)
        logger.info(f"[threat_fill_sub_rules] 导出成功，长度: {len(base64_result)}")

        await cl.Message(
            content=f"""✅ **威胁类型填充完成！**

📊 **填充统计：**
- 目标字段：{target_field}
- 映射数量：{len(threat_data)} 条
- 数据源：已映射子规则（链式更新）

💾 点击下方按钮下载填充后的配置文件。"""
        ).send()

        base64_file = cl.File(
            name=f"threat_filled_{target_field}.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain",
        )
        await cl.Message(content="**📥 点击下载填充后的配置：**", elements=[base64_file]).send()

    except Exception as e:
        logger.error(f"[threat_fill_sub_rules] 填充异常: {e}")
        import traceback
        logger.error(f"[threat_fill_sub_rules] 详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 威胁填充异常：{str(e)}").send()


async def execute_threat_fill(user_session: dict, file_content: str):
    """
    执行威胁类型填充

    使用已保存的 threat_mapping_table 和 threat_target_field，
    解码 base64 数据后调用 apply_threat_mapping，导出处理结果并重置模式。

    Args:
        user_session: 用户会话状态
        file_content: Base64 编码的原始文件内容
    """
    logger.info("[execute_threat_fill] 开始执行威胁类型填充")

    target_field = user_session.get("threat_target_field")
    mapping_table = user_session.get("threat_mapping_table")

    logger.info(f"[execute_threat_fill] 目标字段: {target_field}, 映射数量: {len(mapping_table) if mapping_table else 0}")

    if not mapping_table:
        await cl.Message(content="❌ 威胁映射表格丢失，请重新执行威胁类型映射").send()
        user_session["threat_fill_mode"] = False
        return

    # 尝试解析 Base64 文件内容
    from agent.core.agent import simple_decode
    result = simple_decode(file_content)

    if result["status"] == "success":
        decoded_data = result["decoded_json"]
        logger.info("[execute_threat_fill] Base64 解码成功")
    else:
        # 如果解码失败，尝试直接使用文件内容作为 JSON
        logger.info("[execute_threat_fill] Base64解码失败，尝试直接解析")
        try:
            decoded_data = json.loads(file_content)
        except Exception:
            await cl.Message(content=f"❌ 文件解析失败：{result.get('error_message', '未知错误')}").send()
            return

    # 执行威胁映射填充
    try:
        # 转换 mapping_table 格式（从 Dataframe 格式转换为 threat_fill_handler 格式）
        formatted_mapping = []
        for item in mapping_table:
            if isinstance(item, dict):
                formatted_mapping.append({
                    "mappingType": item.get("mappingType", "REGULAR"),
                    "orgValue": item.get("orgValue", ""),
                    "mappingValue": item.get("mappingValue", "")
                })
            else:
                formatted_mapping.append({
                    "mappingType": str(item.get("mappingType", "REGULAR")),
                    "orgValue": str(item.get("orgValue", "")),
                    "mappingValue": str(item.get("mappingValue", ""))
                })

        logger.info(f"[execute_threat_fill] 格式化映射数量: {len(formatted_mapping)}")

        # 应用映射
        updated_data = apply_threat_mapping(decoded_data, formatted_mapping, target_field)
        logger.info("[execute_threat_fill] 映射应用成功")

        # 导出 Base64
        base64_result = export_to_base64(updated_data)
        logger.info(f"[execute_threat_fill] Base64导出成功，长度: {len(base64_result)}")

        # 重置威胁填充模式
        user_session["threat_fill_mode"] = False
        user_session["threat_target_field"] = None
        user_session["threat_mapping_table"] = None
        user_session["pending_base64"] = None

        # 发送成功消息
        await cl.Message(
            content=f"""✅ **威胁类型填充完成！**

📊 **填充统计：**
- 目标字段：{target_field}
- 映射数量：{len(formatted_mapping)} 条

💾 点击下方按钮下载填充后的配置文件。"""
        ).send()

        # 发送可下载的 Base64 文件
        base64_file = cl.File(
            name="threat_filled_config.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain",
        )

        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()

    except ValueError as e:
        logger.error(f"[execute_threat_fill] 填充失败: {e}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()
    except Exception as e:
        logger.error(f"[execute_threat_fill] 填充异常: {str(e)}")
        import traceback
        logger.error(f"[execute_threat_fill] 详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 填充异常：{str(e)}").send()