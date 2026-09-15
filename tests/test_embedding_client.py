"""Issue #246：嵌入客户端抽取与 Retry-After 钳制合一。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from agent.core import embedding_client, field_retriever


class _Response:
    """只带 Retry-After 头的极简响应替身。"""

    def __init__(self, retry_after):
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}


def test_retry_delay_seconds_clamps_and_falls_back() -> None:
    """合一实现：优先 Retry-After，钳制 [0, 10]，缺失/非法回落默认值。"""
    assert embedding_client.retry_delay_seconds(None, 2.0) == 2.0
    assert embedding_client.retry_delay_seconds(_Response(None), 2.0) == 2.0
    assert embedding_client.retry_delay_seconds(_Response("3"), 2.0) == 3.0
    assert embedding_client.retry_delay_seconds(_Response("100"), 2.0) == 10.0
    assert embedding_client.retry_delay_seconds(_Response("-5"), 2.0) == 0.0
    assert embedding_client.retry_delay_seconds(_Response("abc"), 2.0) == 2.0


def test_adapter_retry_delay_delegates_to_client() -> None:
    """适配层等待计算委托单一实现，行为不变（clamp 0-10、解析失败取默认）。"""
    from application.adapters import shared

    class _Error(Exception):
        def __init__(self, response):
            super().__init__("boom")
            self.response = response

    assert shared._retry_delay_seconds(_Error(_Response("4")), 1.5) == 4.0
    assert shared._retry_delay_seconds(_Error(None), 1.5) == 1.5
    assert shared._retry_delay_seconds(_Error(_Response("999")), 1.5) == 10.0
    assert shared._retry_delay_seconds(_Error(_Response("bad")), 1.5) == 1.5


def test_retriever_keeps_compat_seams_and_zero_http_details() -> None:
    """兼容接缝原样保留；检索层源码不得再出现网络细节。"""
    assert field_retriever._call_embedding_api is embedding_client.call_embedding_api
    assert field_retriever._get_api_key is embedding_client.get_api_key
    assert field_retriever._QUERY_EMBEDDING_CACHE is embedding_client.QUERY_EMBEDDING_CACHE
    assert field_retriever._query_cache_key is embedding_client.query_cache_key

    source = Path(field_retriever.__file__).read_text(encoding="utf-8")
    assert "api.siliconflow.cn" not in source
    assert "SILICONFLOW_API_KEY" not in source


def test_embed_query_texts_uses_injected_api_call() -> None:
    """查询向量生成：注入的 api_call 仅收到去重后的 miss 文本，命中不再调用。"""
    calls: list[list[str]] = []

    def _fake_api(texts):
        calls.append(list(texts))
        return np.array([[1.0, 0.0] for _ in texts])

    vectors = embedding_client.embed_query_texts(
        ["a", "a", "b"], failure_label="测试", api_call=_fake_api
    )
    assert vectors.shape == (3, 2)
    assert calls == [["a", "b"]]

    embedding_client.embed_query_texts(["a"], failure_label="测试", api_call=_fake_api)
    assert calls == [["a", "b"]]
