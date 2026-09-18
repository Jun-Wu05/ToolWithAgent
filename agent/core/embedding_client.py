"""SiliconFlow 嵌入客户端 — 认证、请求、超时、重试与查询向量缓存（#246）。

本模块是标准字段候选检索的 embedding 唯一 HTTP 出口。
检索层（field_retriever）只调用这里的公共入口，不接触 URL/密钥/重试细节。
embedding 固定走硅基流动、不属于提供商接入范围；日志解析知识不使用本模块。
（ADR-0007 / CONTEXT.md「模型提供商」），本模块不提供多供应商抽象。
"""

import os
import time
from collections.abc import Callable
from typing import Any, Optional

import numpy as np

from agent.shared.logger import get_logger

logger = get_logger("embedding_client")

# Embedding 模型配置（自 field_retriever 迁入，#246）
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIM = 4096
EMBEDDING_API_URL = "https://api.siliconflow.cn/v1/embeddings"
# CHANGED: 调整为更稳健的配置（适配 Qwen3-Embedding-8B 大模型批量推理）
EMBEDDING_BATCH_SIZE = 15  # 每次 API 调用最多嵌入 15 个文本（减半，降低服务端单次负载，防 413）
EMBEDDING_BATCH_SLEEP = 0.3  # 每批请求间隔（秒），防止 API 429 限流（保持不变）
EMBEDDING_TIMEOUT = 30.0  # 单次 API 调用超时（秒）— 8B 模型批量推理需更长时间，原 10s 易误超时
EMBEDDING_MAX_RETRIES = 1  # 瞬时故障最多重试一次，避免批处理长时间无反馈


def retry_delay_seconds(response: Any, default_seconds: float) -> float:
    """优先采用 Retry-After 响应头，并把等待建议钳制在 [0, 10] 秒内。

    #246 前与 application/adapters/shared.py 各有一份平行实现，现合一于此，
    两处消费点（嵌入客户端重试循环、适配层等待计算）共用本函数。
    """
    headers = getattr(response, "headers", None)
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        return min(max(float(retry_after), 0.0), 10.0)
    except (TypeError, ValueError):
        return default_seconds


def get_api_key() -> Optional[str]:
    """获取 SiliconFlow API Key，先从环境变量，优先生效的 Key"""
    primary = os.getenv("SILICONFLOW_API_KEY", "")
    if primary:
        return primary
    return os.getenv("FALLBACK_API_KEY", "") or None


def call_embedding_api(texts: list[str], retries: int = EMBEDDING_MAX_RETRIES) -> Optional[np.ndarray]:
    """调用 Embedding API；只对瞬时故障重试且不记录输入或响应原文。"""
    import requests

    api_key = get_api_key()
    if not api_key:
        logger.warning("[EMBEDDING] 未设置 SILICONFLOW_API_KEY，跳过 embedding")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": EMBEDDING_MODEL,
        "input": texts,
        "encoding_format": "float",
    }

    for attempt in range(retries + 1):
        call_started_at = time.monotonic()
        response = None
        logger.info(
            "[MODEL_CALL_START] Embedding API 调用开始: model=%s input_count=%s "
            "attempt=%s timeout_seconds=%s",
            EMBEDDING_MODEL,
            len(texts),
            attempt + 1,
            EMBEDDING_TIMEOUT,
        )
        try:
            response = requests.post(
                EMBEDDING_API_URL,
                headers=headers,
                json=payload,
                timeout=EMBEDDING_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            embeddings = sorted(data["data"], key=lambda item: item["index"])
            vectors = np.array([item["embedding"] for item in embeddings], dtype=np.float32)
            logger.info(
                "[MODEL_CALL_END] Embedding API 调用完成: model=%s input_count=%s "
                "output_count=%s elapsed_seconds=%.3f",
                EMBEDDING_MODEL,
                len(texts),
                vectors.shape[0],
                time.monotonic() - call_started_at,
            )
            return vectors
        except requests.exceptions.Timeout:
            retriable = True
            logger.warning(
                "[MODEL_CALL_TIMEOUT] Embedding API 调用超时: model=%s attempt=%s "
                "timeout_seconds=%s",
                EMBEDDING_MODEL,
                attempt + 1,
                EMBEDDING_TIMEOUT,
            )
        except requests.exceptions.RequestException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            retriable = status_code is None or status_code == 429 or (
                isinstance(status_code, int) and status_code >= 500
            )
            logger.warning(
                "[MODEL_CALL_FAILED] Embedding API 请求失败: model=%s attempt=%s "
                "status_code=%s error_category=%s retriable=%s",
                EMBEDDING_MODEL,
                attempt + 1,
                status_code if status_code is not None else "none",
                type(error).__name__,
                retriable,
            )
        except (KeyError, IndexError, ValueError) as error:
            logger.warning(
                "[MODEL_CALL_FAILED] Embedding 响应结构非法: model=%s attempt=%s "
                "error_category=%s",
                EMBEDDING_MODEL,
                attempt + 1,
                type(error).__name__,
            )
            return None

        if not retriable or attempt >= retries:
            break
        delay_seconds = retry_delay_seconds(response, 2.0)
        logger.info(
            "[BATCH_RETRY] Embedding API 准备重试: model=%s next_attempt=%s "
            "delay_seconds=%s",
            EMBEDDING_MODEL,
            attempt + 2,
            delay_seconds,
        )
        time.sleep(delay_seconds)

    logger.error(
        "[MODEL_CALL_FAILED] Embedding API 调用最终失败: model=%s attempt_count=%s",
        EMBEDDING_MODEL,
        retries + 1,
    )
    return None


# 进程内查询向量缓存（#245 随 #246 迁入客户端）：{query_cache_key(text): 向量}。
# 键取最终嵌入文本，tag_rules/synonyms 变更会改变文本、自然产生新键；
# 模型/维度为模块常量，缓存随进程生命周期失效，无需持久化与手动失效。
QUERY_EMBEDDING_CACHE: dict[tuple[str, int, str], np.ndarray] = {}


def query_cache_key(query_text: str) -> tuple[str, int, str]:
    return (EMBEDDING_MODEL, EMBEDDING_DIM, query_text)


def embed_query_texts(
    query_texts: list[str],
    *,
    failure_label: str,
    api_call: Optional[Callable[[list[str]], Optional[np.ndarray]]] = None,
) -> np.ndarray:
    """
    查询向量生成：请求内保序去重 + 进程内缓存，仅对 miss 批次调 Embedding API。

    api_call 注入点（#246）：检索层传入自身的兼容接缝 ``_call_embedding_api``，
    使既有 monkeypatch 该名字的测试不经改动继续生效；缺省直连本客户端。

    Args:
        query_texts: 最终复合查询文本（field_retriever._build_query_text_for_embedding 的输出）
        failure_label: 失败异常信息中的场景名（主字段轮/变体轮）
        api_call: 实际执行嵌入的函数（测试接缝），缺省为 call_embedding_api

    Returns:
        与 query_texts 等长、按输入顺序对齐的向量矩阵

    Raises:
        RuntimeError: 任一 miss 批次 API 返回 None（与既有失败语义一致）
    """
    if api_call is None:
        api_call = call_embedding_api
    unique_texts = list(dict.fromkeys(query_texts))
    missing = [
        t for t in unique_texts if query_cache_key(t) not in QUERY_EMBEDDING_CACHE
    ]
    for batch_start in range(0, len(missing), EMBEDDING_BATCH_SIZE):
        batch = missing[batch_start:batch_start + EMBEDDING_BATCH_SIZE]
        vectors = api_call(batch)
        if vectors is None:
            raise RuntimeError(
                f"[EMBEDDING] {failure_label}（第 {batch_start // EMBEDDING_BATCH_SIZE + 1} 批），"
                f"共 {len(missing)} 个待嵌入文本，批次大小 {EMBEDDING_BATCH_SIZE}"
            )
        for text, vector in zip(batch, vectors):
            QUERY_EMBEDDING_CACHE[query_cache_key(text)] = vector
        # 批次间休眠，防止 API 429 限流（最后一批不睡）
        if batch_start + EMBEDDING_BATCH_SIZE < len(missing):
            time.sleep(EMBEDDING_BATCH_SLEEP)
    return np.array([QUERY_EMBEDDING_CACHE[query_cache_key(t)] for t in query_texts])
