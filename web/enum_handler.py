"""
枚举处理器 — 枚举填充 / 枚举提取分流

提供:
- handle_enum_fill_flow(user_session, user_text) → bool         (枚举填充模式分流)
- execute_enum_fill(user_session, file_content) → None          (执行枚举填充)
- handle_enum_extract_flow(user_session, team, user_text) → None (枚举提取流程)
"""
import json
import os
import re

import chainlit as cl

from agent.shared.logger import get_logger

# 枚举工具函数
from agent.tools.enum_field_tool import (
    apply_enum_fill,
    export_enum_to_base64,
)
from agent.tools.enum_extract_tool import (
    sample_logs,
    validate_and_fix_regex,
    validate_regex_with_stats,
    extract_enum_with_field,
    format_mapping_table,
    generate_output_json,
)

logger = get_logger("enum_handler")

# 加载枚举提取提示词
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)


def _load_enum_extract_prompt() -> str:
    """加载枚举提取提示词"""
    _prompt_path = os.path.join(_project_root, "agent", "prompts", "enum_extract.md")
    try:
        with open(_prompt_path, "r", encoding="utf-8") as _f:
            return _f.read()
    except Exception as _e:
        logger.warning(f"[CONFIG] 加载 enum_extract.md 失败: {_e}，使用默认提示词")
        return "请分析日志格式，为指定字段生成正则表达式提取枚举值。"


ENUM_EXTRACT_PROMPT = _load_enum_extract_prompt()


# ============= 枚举填充 =============

async def handle_enum_fill_flow(user_session: dict, user_text: str) -> bool:
    """
    枚举填充模式专属流程

    Returns:
        True 表示已处理（调用方应直接 return），False 表示未命中枚举填充模式
    """
    if not user_session.get("enum_fill_mode"):
        return False

    logger.info(f"[HANDLE] 枚举填充模式，检查用户输入: {user_text}")

    enum_excel_path = user_session.get("enum_excel_path")
    if not enum_excel_path:
        await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
        user_session["enum_fill_mode"] = False
        return True

    # 枚举模式需要用户上传 Base64 文件
    logger.info("[HANDLE] 枚举模式，等待用户上传Base64文件")
    await cl.Message(
        content=f"""📋 **枚举填充模式已开启**

已选择映射表：{enum_excel_path}

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
    ).send()
    return True


async def execute_enum_fill(user_session: dict, file_content: str):
    """
    执行枚举字段填充

    Args:
        user_session: 用户会话状态
        file_content: Base64 文件内容
    """
    logger.info("[execute_enum_fill] 开始执行枚举填充")

    enum_excel_path = user_session.get("enum_excel_path")
    enum_preview = user_session.get("enum_preview")

    logger.info(f"[execute_enum_fill] Excel路径: {enum_excel_path}")

    if not enum_excel_path:
        await cl.Message(content="❌ 枚举映射表路径丢失，请重新上传Excel映射表").send()
        user_session["enum_fill_mode"] = False
        return

    # 尝试解析 Base64 文件内容
    from agent.core.agent import simple_decode
    result = simple_decode(file_content)

    if result["status"] == "success":
        decoded_data = result["decoded_json"]
        logger.info("[execute_enum_fill] Base64 解码成功")
    else:
        # 如果解码失败，尝试直接使用文件内容作为 JSON
        logger.info("[execute_enum_fill] Base64解码失败，尝试直接解析")
        try:
            decoded_data = json.loads(file_content)
        except Exception:
            await cl.Message(content=f"❌ 文件解析失败：{result.get('error_message', '未知错误')}").send()
            return

    # 执行枚举填充
    try:
        # 应用枚举填充
        updated_data = apply_enum_fill(decoded_data, enum_excel_path)
        logger.info("[execute_enum_fill] 枚举填充应用成功")

        # 导出 Base64
        base64_result = export_enum_to_base64(updated_data)
        logger.info(f"[execute_enum_fill] Base64导出成功，长度: {len(base64_result)}")

        # 重置枚举填充模式
        user_session["enum_fill_mode"] = False
        user_session["enum_excel_path"] = None
        user_session["enum_preview"] = None

        # 计算填充统计
        field_count = len(enum_preview) if enum_preview else 0

        # 发送成功消息
        await cl.Message(
            content=f"""✅ **枚举字段填充完成！**

📊 **填充统计：**
- 映射表：{enum_excel_path}
- 映射数量：{field_count} 条

💾 点击下方按钮下载填充后的配置文件。"""
        ).send()

        # 发送可下载的 Base64 文件
        base64_file = cl.File(
            name="enum_filled_config.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain",
        )

        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()

    except FileNotFoundError as e:
        logger.error(f"[execute_enum_fill] 文件未找到: {e}")
        await cl.Message(content=f"❌ Excel 文件未找到：{str(e)}").send()
    except ValueError as e:
        logger.error(f"[execute_enum_fill] 填充失败: {e}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()
    except Exception as e:
        logger.error(f"[execute_enum_fill] 填充异常: {str(e)}")
        import traceback
        logger.error(f"[execute_enum_fill] 详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 填充异常：{str(e)}").send()


# ============= 枚举提取 =============

async def handle_enum_extract_flow(user_session: dict, team, user_text: str):
    """
    枚举提取模式专属流程
    从日志中提取指定字段的枚举值
    """
    logger.info(f"[ENUM_EXTRACT] 开始枚举提取流程: {user_text}")

    # 检查是否有原始日志数据
    original_log = user_session.get("original_log")
    if not original_log:
        await cl.Message(
            content="""❌ **没有找到原始日志数据**

请先上传包含日志的配置文件（如 Base64/TXT），然后再提取枚举值。"""
        ).send()
        return

    # 字段名由 LLM 从用户输入中推断，不再使用硬编码正则
    # 如果 decoded_fields 有值，作为提示传给 LLM；否则传空
    decoded_fields = user_session.get("decoded_fields")
    fields_hint = ", ".join(decoded_fields) if decoded_fields else "(请从日志样本中分析)"

    logger.info(f"[ENUM_EXTRACT] 字段名由 LLM 从用户输入推断，字段提示: {fields_hint}")

    # 发送 loading 消息
    loading_msg = cl.Message(content="⏳ **正在提取枚举值...**\n\n💭 分析日志格式并生成正则表达式...")
    await loading_msg.send()

    try:
        # 1. 从原始日志中采样
        logs_str = '\n'.join(original_log)
        sampled_logs = sample_logs(logs_str, sample_size=20)
        logger.info(f"[ENUM_EXTRACT] 采样日志行数: {sampled_logs.count(chr(10)) + 1}")

        # 2. 构建 LLM 输入（字段名由 LLM 从 user_text 中推断）
        import asyncio
        llm_input = f"""{ENUM_EXTRACT_PROMPT}

用户输入：{user_text}
可用字段提示：{fields_hint}

采样日志（20行）：
{sampled_logs}

请先从用户输入中提取目标字段名，然后分析日志格式，为该字段生成提取正则表达式。只输出 JSON 格式结果，不要输出其他内容。"""

        # 3. 调用 LLM 生成正则表达式
        result = await asyncio.to_thread(team.run, llm_input)

        # 删除 loading 消息
        await loading_msg.remove()

        # 4. 解析 LLM 输出（field_name 也从 LLM 响应中提取）
        result_content = result.content if hasattr(result, 'content') else str(result)
        logger.info(f"[ENUM_EXTRACT] LLM输出: {result_content[:500]}...")

        # 尝试解析 JSON
        regex_result = None
        field_name_from_llm = None
        try:
            json_match = re.search(r'\{[^}]+\}', result_content, re.DOTALL)
            if json_match:
                regex_data = json.loads(json_match.group())
                regex_result = regex_data.get("regex", "")
                field_name_from_llm = regex_data.get("field", "")
                logger.info(f"[ENUM_EXTRACT] LLM 推断字段: {field_name_from_llm}, 正则: {regex_result}")
        except json.JSONDecodeError:
            logger.warning(f"[ENUM_EXTRACT] JSON解析失败，尝试直接使用输出")

        # 使用 LLM 推断的字段名，回退方案
        if field_name_from_llm:
            field_name = field_name_from_llm
        elif decoded_fields and len(decoded_fields) > 0:
            field_name = decoded_fields[0]
            logger.info(f"[ENUM_EXTRACT] LLM未返回字段名，使用第一个字段: {field_name}")
        else:
            await cl.Message(content='❌ **无法确定目标字段**，请更明确地指定字段名，如"提取 alter_name 的枚举值"。').send()
            return

        # 如果没有解析到正则，使用默认正则
        if not regex_result:
            regex_result = f'"{field_name}":"([^"]+)"'
            logger.info(f"[ENUM_EXTRACT] 使用默认正则: {regex_result}")

        # 5. 验证正则（使用增强版验证，支持自动修复）
        validation = validate_regex_with_stats(regex_result, sampled_logs)
        logger.info(f"[ENUM_EXTRACT] 正则验证结果: valid={validation.get('valid')}, match_rate={validation.get('match_rate', 0)*100:.1f}%")

        # 5.1 如果匹配率低，尝试自动修复
        if not validation.get("valid") or validation.get("match_rate", 0) < 0.5:
            logger.info("[ENUM_EXTRACT] 正则匹配率低，尝试自动修复...")
            fixed = validate_and_fix_regex(regex_result, sampled_logs, field_name)

            if fixed["valid"]:
                regex_result = fixed["regex"]
                confidence = fixed["confidence"]
                source = fixed["source"]
                fallback_type = fixed.get("fallback_type", "")
                logger.info(f"[ENUM_EXTRACT] 自动修复成功，来源: {source}, 置信度: {confidence}")

                if source == "fallback":
                    await cl.Message(
                        content=f"⚠️ 原正则匹配率 {validation.get('match_rate', 0)*100:.0f}%，已自动优化为 **{fallback_type}** 格式。\n置信度: {confidence}"
                    ).send()
                else:
                    await cl.Message(
                        content=f"ℹ️ 正则匹配率 {validation.get('match_rate', 0)*100:.0f}%，已使用优化版本。\n置信度: {confidence}"
                    ).send()
            else:
                await cl.Message(
                    content=f"""❌ **正则提取失败**

原正则: `{regex_result}`
匹配率: {validation.get('match_rate', 0)*100:.0f}%

建议：
1. 更换字段名重试
2. 上传格式更统一的日志""").send()
                return

        # 6. 用正则扫描全量日志提取枚举值
        enum_result = extract_enum_with_field(logs_str, field_name, regex_result)
        logger.info(f"[ENUM_EXTRACT] 提取结果: {enum_result.get('unique_count')} 个唯一枚举值")

        # 7. 展示结果
        enum_values = enum_result.get("value", [])
        unique_count = enum_result.get("unique_count", 0)
        total_count = enum_result.get("total_count", 0)

        if not enum_values:
            await cl.Message(
                content=f"""❌ **未提取到枚举值**

正则表达式：`{regex_result}`
错误信息：正则未匹配到任何值

请检查日志格式是否正确，或尝试其他字段。"""
            ).send()
            return

        # 构建结果消息
        top_values = enum_values[:10]  # 只显示前10个
        values_display = '\n'.join([f"- `{v}`" for v in top_values])

        if unique_count > 10:
            values_display += f"\n- ... 还有 {unique_count - 10} 个"

        summary = f"""✅ **枚举提取完成！**

📊 **提取统计：**
- 目标字段：{field_name}
- 唯一枚举值：{unique_count} 个
- 总匹配行数：{total_count} 条

🔍 **正则表达式：**
```
{regex_result}
```

📋 **枚举值列表（前10个）：**
{values_display}

💡 **下一步操作：**
- 可以基于这些枚举值生成映射表
- 点击上方"枚举处理"上传 Excel 映射表进行填充"""

        await cl.Message(content=summary).send()

        # 保存枚举提取结果到会话
        user_session["last_enum_extract_result"] = enum_result

        # 8. 展示 mapping 表格
        mapping_table = format_mapping_table(enum_result)
        if mapping_table:
            import pandas as pd
            df = pd.DataFrame(mapping_table)
            elements = [
                cl.Dataframe(data=df, display="inline", title="📋 枚举值映射表", pagination=0)
            ]
            await cl.Message(
                content="**映射表（mappingType | orgValue | mappingValue）**",
                elements=elements
            ).send()

        # 9. 下载 JSON 文件
        output_json = generate_output_json({
            "field": field_name,
            "regex": regex_result,
            "original_log": enum_result.get("original_log", []),
            "value": enum_values
        })

        safe_name = field_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        json_file = cl.File(
            name=f"enum_{safe_name}.json",
            content=output_json.encode('utf-8'),
            mime="application/json"
        )

        await cl.Message(
            content=f"**📥 下载枚举值 JSON 文件（{unique_count} 个枚举值）**",
            elements=[json_file]
        ).send()

    except Exception as e:
        logger.error(f"[ENUM_EXTRACT] 枚举提取异常: {str(e)}")
        import traceback
        logger.error(f"[ENUM_EXTRACT] 详细错误: {traceback.format_exc()}")
        try:
            await loading_msg.remove()
        except Exception:
            pass
        await cl.Message(content=f"❌ 枚举提取失败：{str(e)}").send()