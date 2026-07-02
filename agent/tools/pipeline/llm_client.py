# -*- coding: utf-8 -*-
"""
LLM API 调用封装 + JSON 解析 + log_format 枚举归一化。
被 Step 1 (log_format_identifier) 和 Step 3 (log_classifier) 共用。
"""

from __future__ import annotations

import json
import re as _re
import time
from typing import Any

import httpx

from agent.core.model_config import ModelConfig
from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")

# ============================================================================
# 内部工具：直接调 LLM API（零 Agno 开销）
# ============================================================================

_LLM_API_URL: str = ""
_LLM_API_KEY: str = ""

# 🔧 修复：需要禁用思考模式的 Thinking Model 列表
# 这些模型默认启用思考模式，会导致 JSON 输出时 content 为空
_THINKING_DISABLED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


def _init_llm_config() -> None:
    """懒加载 LLM API 配置"""
    global _LLM_API_URL, _LLM_API_KEY
    if _LLM_API_URL:
        return
    _LLM_API_KEY = ModelConfig.get_api_key()
    if ModelConfig.MODEL_PROVIDER == "siliconflow":
        _LLM_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
    else:
        base = "https://api.deepseek.com"
        _LLM_API_URL = f"{base}/v1/chat/completions"


def _call_llm_direct(
    prompt: str,
    model_id: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: float = 60.0,
    # CHANGED: 新增 force_json 参数，强制 JSON 输出
    force_json: bool = True,
) -> str:
    """
    直接调 LLM API（httpx），跳过 Agno，零 Agent 路由开销。

    Args:
        prompt: 用户 prompt
        model_id: 模型 ID，默认使用配置的主模型
        temperature: 温度，默认 0.1 保证格式稳定
        max_tokens: 最大输出 token
        timeout: 超时秒数
        force_json: 是否强制 JSON 输出（默认 True）

    Returns:
        LLM 返回的文本内容

    Raises:
        httpx.HTTPStatusError: API 返回非 2xx
    """
    _init_llm_config()
    if model_id is None:
        model_id = ModelConfig.MAIN_MODEL

    start = time.time()
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    
    # 🔧 修复：对 Thinking Model 禁用思考模式
    # Thinking Model（deepseek-v4-flash, deepseek-v4-pro）默认启用思考模式
    # 会导致 JSON 输出时 content 为空（所有 token 被思考内容占用）
    if model_id in _THINKING_DISABLED_MODELS:
        payload["thinking"] = {"type": "disabled"}
        logger.debug(f"[_call_llm_direct] 已禁用思考模式：{model_id}")
    
    # CHANGED: 条件性添加 response_format，强制 JSON 输出
    # 支持的 API：DeepSeek、OpenAI 兼容接口（如硅基流动）
    # 不支持的 API：智谱 GLM 系列（需要在 prompt 中明确要求）
    if force_json:
        supports_json_format = ModelConfig.MODEL_PROVIDER in ("deepseek", "siliconflow")
        if supports_json_format:
            payload["response_format"] = {"type": "json_object"}
            logger.debug(f"[_call_llm_direct] 使用 response_format 强制 JSON 输出")

    logger.info(
        f"[LLM_DIRECT] 调用 {_LLM_API_URL}, model={model_id}, prompt_len={len(prompt)}"
    )
    resp = httpx.post(
        _LLM_API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {_LLM_API_KEY}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    content: str = data["choices"][0]["message"]["content"]
    elapsed = time.time() - start
    usage = data.get("usage", {})
    
    # 🔧 新增：记录 LLM 原始响应内容
    logger.info(f"[LLM_DIRECT] 原始响应内容（前500字符）: {content[:500]}")
    if not content or not content.strip():
        logger.error(f"[LLM_DIRECT] LLM 返回空内容！完整响应: {data}")
    
    logger.info(
        f"[LLM_DIRECT] 完成, elapsed={elapsed:.2f}s, "
        f"input_tokens={usage.get('prompt_tokens', '?')}, "
        f"output_tokens={usage.get('completion_tokens', '?')}"
    )
    return content


def _try_parse_json(text: str) -> dict | None:
    """尝试从 LLM 响应中提取 JSON"""
    text = text.strip()
    
    # 🔧 新增：记录原始文本
    logger.debug(f"[_try_parse_json] 原始文本长度: {len(text)}, 前200字符: {text[:200]}")
    
    # 去掉可能的 markdown 代码块包装
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
        logger.debug(f"[_try_parse_json] 去除 markdown 后: {text[:200]}")
    
    try:
        result = json.loads(text)
        logger.debug(f"[_try_parse_json] JSON 解析成功: {result}")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"[_try_parse_json] JSON 解析失败: {e}, 文本: {text[:500]}")
        # 尝试提取第一个 { ... } 块
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
                logger.debug(f"[_try_parse_json] 提取 JSON 块成功: {result}")
                return result
            except json.JSONDecodeError as e2:
                logger.warning(f"[_try_parse_json] 提取 JSON 块失败: {e2}")
        return None


def normalize_log_format(format_type: str) -> str:
    """将格式类型映射为固定枚举值。

    支持的格式：JSON、KV、UNKNOWN
    """
    type_lower = (format_type or "").lower()
    if type_lower in ("json",):
        return "JSON"
    if type_lower in ("kv", "key-value", "keyvalue"):
        return "KV"
    return "UNKNOWN"
