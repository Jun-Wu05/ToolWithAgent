# -*- coding: utf-8 -*-
"""
LLM API 调用封装 + JSON 解析 + log_format 枚举归一化。
被 Step 1 (log_format_identifier) 和 Step 3 (log_classifier) 共用。
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from agent.core import model_config
from agent.core.model_config import THINKING_DISABLED_MODELS as _THINKING_DISABLED_MODELS
from agent.core.model_config import ModelConfig
from agent.shared.logger import get_logger

logger = get_logger("log_parser_pipeline")

# ============================================================================
# 内部工具：直接调 LLM API（零 Agno 开销）
# ============================================================================


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

    端点、密钥与 JSON 能力按当前提供商规格每次解析（ADR-0007），
    运行时切换提供商后随切换刷新，不做懒加载缓存。

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
    spec = model_config.get_provider_spec(ModelConfig.get_provider())
    api_url = model_config.get_chat_completions_url(spec.name)
    api_key = ModelConfig.get_api_key()
    if model_id is None:
        model_id = ModelConfig.get_model_id()

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
    # 能力按提供商规格声明；不支持的提供商靠提示词约束与健壮解析兜底
    if force_json and spec.supports_json_response_format:
        payload["response_format"] = {"type": "json_object"}
        logger.debug(f"[_call_llm_direct] 使用 response_format 强制 JSON 输出")

    logger.info(
        f"[LLM_DIRECT] 调用 {api_url}, model={model_id}, prompt_len={len(prompt)}"
    )
    resp = httpx.post(
        api_url,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
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
