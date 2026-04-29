"""
LLM 输入构建 — 将用户请求与上传数据拼接为 Team 的输入文本

提供:
- build_llm_input(user_text, user_session) → str
"""
import json

from agent.shared.logger import get_logger

logger = get_logger("input_builder")


def build_llm_input(user_text: str, user_session: dict) -> str:
    """
    构建发送给 LLM / Team 的完整输入。

    只要有数据就拼接字段列表，由 RouterAgent 自己判断任务类型。
    """
    has_data = user_session.get("decoded_data") or user_session.get("decoded_fields")

    if has_data:
        simplified_data = user_session.get("simplified_data", {})
        fields_list = simplified_data.get("fields", [])
        original_log_sample = simplified_data.get("original_log_sample", "")

        fields_json_str = json.dumps(fields_list, ensure_ascii=False)

        full_input = f"""用户请求：{user_text}

📋 可用数据字段列表：
{fields_json_str}"""

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
        full_input = user_text

    return full_input