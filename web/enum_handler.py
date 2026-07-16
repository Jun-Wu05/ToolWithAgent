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

    数据源优先级（避免要求用户重传已上传的数据）：
    1. mapped_sub_rules（Excel→解析→映射路径产出）→ apply_enum_fill_to_sub_rules
    2. raw_base64（Base64 上传缓存）→ execute_enum_fill
    3. 都没有 → 提示上传 Base64 文件

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

    # 数据源 1：已有 mapped_sub_rules（Excel 数据表格 → 日志解析 → 字段映射 产出）
    mapped_sub_rules = user_session.get("mapped_sub_rules")
    if mapped_sub_rules:
        logger.info("[HANDLE] 检测到已有 mapped_sub_rules，用子规则数据源直接填充（无需重传）")
        await _execute_enum_fill_with_sub_rules(user_session, mapped_sub_rules, enum_excel_path)
        return True

    # 数据源 2：已有 raw_base64 缓存
    raw_base64 = user_session.get("raw_base64")
    if raw_base64:
        logger.info("[HANDLE] 检测到已有 raw_base64 缓存，直接执行填充")
        await execute_enum_fill(user_session, raw_base64)
        return True

    # 数据源 3：都没有，提示上传
    logger.info("[HANDLE] 无已解码数据，等待用户上传Base64文件")
    await cl.Message(
        content=f"""📋 **枚举填充模式已开启**

已选择映射表：{enum_excel_path}

请上传 **Base64 配置文件**（拖拽或点击上传）来完成填充。"""
    ).send()
    return True


async def _execute_enum_fill_with_sub_rules(user_session: dict, sub_rules: list, enum_excel_path: str):
    """用已有 mapped_sub_rules 执行枚举填充（读 Excel 映射表 → apply_enum_fill_to_sub_rules → 导出）"""
    from agent.tools.enum_field_tool import read_enum_mappings_from_excel
    from agent.tools.rule_generator import apply_enum_fill_to_sub_rules, rules_to_base64_text

    logger.info("[enum_fill_sub_rules] 开始执行（复用 mapped_sub_rules）")
    enum_preview = user_session.get("enum_preview")

    try:
        # 读取枚举映射表（{字段名: [{mappingType, orgValue, mappingValue}, ...]}）
        mapping_table = read_enum_mappings_from_excel(enum_excel_path)
        if not mapping_table:
            await cl.Message(content=f"❌ 枚举映射表未读取到有效规则：{enum_excel_path}").send()
            return

        updated_sub_rules = apply_enum_fill_to_sub_rules(sub_rules, mapping_table)
        logger.info("[enum_fill_sub_rules] 枚举填充应用成功")

        # 导出 Base64
        base64_result = rules_to_base64_text(updated_sub_rules)
        logger.info(f"[enum_fill_sub_rules] 导出成功，长度: {len(base64_result)}")

        # 重置枚举填充模式
        user_session["enum_fill_mode"] = False
        user_session["enum_excel_path"] = None
        user_session["enum_preview"] = None

        field_count = len(enum_preview) if enum_preview else 0
        await cl.Message(
            content=f"""✅ **枚举字段填充完成！**

📊 **填充统计：**
- 映射表：{enum_excel_path}
- 映射数量：{field_count} 条
- 数据源：已映射子规则（无需重传）

💾 点击下方按钮下载填充后的配置文件。"""
        ).send()

        base64_file = cl.File(
            name="enum_filled_sub_rules.txt",
            content=base64_result.encode('utf-8'),
            mime="text/plain",
        )
        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()

    except FileNotFoundError as e:
        logger.error(f"[enum_fill_sub_rules] 文件未找到: {e}")
        await cl.Message(content=f"❌ Excel 文件未找到：{str(e)}").send()
    except Exception as e:
        logger.error(f"[enum_fill_sub_rules] 填充异常: {e}")
        import traceback
        logger.error(f"[enum_fill_sub_rules] 详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 枚举填充异常：{str(e)}").send()


def _resolve_fill_data_source(file_content: str) -> tuple:
    """解析填充数据源：Base64 → JSON 两级降级。

    Args:
        file_content: 原始文件内容（Base64 字符串或 JSON 文本）

    Returns:
        (decoded_data, error_msg)：成功时 decoded_data 为 dict/list，error_msg 为 None；
        失败时 decoded_data 为 None，error_msg 为错误描述。
    """
    from agent.core.agent import simple_decode
    result = simple_decode(file_content)
    if result["status"] == "success":
        logger.info("[data_source] Base64 解码成功")
        return result["decoded_json"], None

    # Base64 解码失败，尝试直接作为 JSON
    logger.info("[data_source] Base64解码失败，尝试直接解析 JSON")
    try:
        data = json.loads(file_content)
        logger.info("[data_source] JSON 直接解析成功")
        return data, None
    except Exception:
        error_msg = result.get('error_message', '未知错误')
        logger.warning(f"[data_source] 数据源解析失败: {error_msg}")
        return None, error_msg


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

    # 解析数据源（委托 _resolve_fill_data_source）
    decoded_data, error_msg = _resolve_fill_data_source(file_content)
    if decoded_data is None:
        await cl.Message(content=f"❌ 文件解析失败：{error_msg}").send()
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

def _extract_log_type_filter(user_text: str, user_session) -> str | None:
    """从用户文本提取日志类型限定词（如「把IPS的alarm_name」→ IPS）。

    用 session.log_classification 的已知日志类型列表做精确匹配，避免误匹配。

    Returns:
        日志类型字符串（如 "IPS"），或 None（未指定类型限定词）
    """
    # 从 log_classification 获取已知日志类型列表
    classification = user_session.get("log_classification") if user_session else None
    if not classification or not isinstance(classification, dict):
        return None

    known_types: list[str] = []
    for detail in classification.get("classification_details", []):
        if isinstance(detail, dict):
            logtype = detail.get("logtype", "")
            if logtype:
                known_types.append(str(logtype))

    if not known_types:
        return None

    # 在用户文本中查找已知日志类型（精确匹配，大小写敏感——日志类型通常大写）
    for log_type in known_types:
        if log_type in user_text:
            return log_type
    return None


async def handle_enum_extract_flow(user_session: dict, team, user_text: str):
    """
    枚举提取模式专属流程
    从日志中提取指定字段的枚举值
    """
    logger.info(f"[ENUM_EXTRACT] 开始枚举提取流程: {user_text}")

    # 日志数据源：优先 raw_log_lines（Excel 原始日志列的干净文本），回退 original_log（JSON 包装行）
    log_lines = user_session.get("raw_log_lines") or user_session.get("original_log")
    if not log_lines:
        await cl.Message(
            content="""❌ **没有找到原始日志数据**

请先上传包含日志的配置文件（如 Base64/TXT），然后再提取枚举值。"""
        ).send()
        return

    # 按日志类型过滤（用户「把IPS的alarm_name...」→ 只保留 IPS 行，提升匹配精准度）
    log_type_filter = _extract_log_type_filter(user_text, user_session)
    if log_type_filter:
        original_count = len(log_lines)
        log_lines = [l for l in log_lines if log_type_filter in l]
        logger.info(f"[ENUM_EXTRACT] 按日志类型 {log_type_filter} 过滤：{original_count} → {len(log_lines)} 行")

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
        logs_str = '\n'.join(log_lines)
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

        # 格式遵从度检测
        has_preamble = not result_content.strip().startswith('{')
        if has_preamble:
            logger.warning(f"[ENUM_EXTRACT] LLM 未遵守纯 JSON 输出格式，输出包含前导文本: {result_content[:200].strip()}")
        else:
            logger.info(f"[ENUM_EXTRACT] LLM 严格遵循了 JSON 输出格式")

        # 自平衡括号提取 JSON（支持正则内含 {} 等特殊字符）
        def _extract_json_from_llm(text: str) -> dict | None:
            """从 LLM 响应中提取 JSON，支持嵌套括号和内嵌正则字符"""
            text = text.strip()
            # 第一级：直接 json.loads 整个文本（LLM 严格遵守格式时）
            if text.startswith('{'):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass

            # 第二级：自平衡括号提取（LLM 前后加了说明文字时）
            stack = []
            start = -1
            in_string = False
            for i, ch in enumerate(text):
                if ch == '"' and (i == 0 or text[i - 1] != '\\'):
                    in_string = not in_string
                if in_string:
                    continue
                if ch == '{':
                    if not stack:
                        start = i
                    stack.append(i)
                elif ch == '}':
                    if stack:
                        stack.pop()
                        if not stack and start >= 0:
                            try:
                                return json.loads(text[start:i + 1])
                            except json.JSONDecodeError:
                                return None
            return None

        # 尝试解析 JSON
        regex_result = None
        field_name_from_llm = None
        try:
            regex_data = _extract_json_from_llm(result_content)
            if regex_data:
                regex_result = regex_data.get("regex", "")
                field_name_from_llm = regex_data.get("field", "")
                logger.info(f"[ENUM_EXTRACT] LLM 推断字段: {field_name_from_llm}, 正则: {regex_result}")
            else:
                logger.warning(f"[ENUM_EXTRACT] 无法从 LLM 输出中提取 JSON")
        except Exception as exc:
            logger.warning(f"[ENUM_EXTRACT] JSON解析异常: {exc}")

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

        # 5.1 只有零匹配（valid=False）才尝试自动修复
        # 注：混合日志里某字段只存在于子类型是正常现象（如 alarm_name 只在 IPS 行），
        # 30%匹配率不代表正则错了，不应判定为低匹配率需要修复
        if not validation.get("valid"):
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
        user_session["last_fill_type"] = "enum"  # 标记最近映射类型，供 fill_dispatcher 判定

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