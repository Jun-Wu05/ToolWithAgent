"""Issue #245：Query embedding 进程内缓存与请求内去重。"""

from __future__ import annotations

import numpy as np
import pytest

from agent.core import field_retriever


RECORDS = [
    {"系统属性名称": "事件名称", "字段名称": "event_name"},
    {"系统属性名称": "源地址", "字段名称": "src_address"},
    {"系统属性名称": "严重程度", "字段名称": "severity"},
]
EMBEDDINGS = np.array(
    [
        [1.0, 0.0],
        [0.0, 1.0],
        [0.70710678, 0.70710678],
    ]
)


@pytest.fixture
def api_calls(monkeypatch):
    """记录器桩：记录每次 Embedding API 调用的文本批次，返回固定向量。"""
    calls: list[list[str]] = []

    def _fake_api(texts):
        calls.append(list(texts))
        return np.array([[1.0, 0.0] for _ in texts])

    monkeypatch.setattr(field_retriever, "_load_cache", lambda: (EMBEDDINGS, RECORDS))
    monkeypatch.setattr(field_retriever, "_call_embedding_api", _fake_api)
    return calls


def test_duplicate_fields_within_batch_embed_once(api_calls) -> None:
    """同批重复字段只对唯一复合文本发起一次 API 调用。"""
    table = field_retriever.batch_retrieve_candidates_table(
        ["src_ip", "src_ip", "src_ip"]
    )

    assert "src_ip" in table
    assert len(api_calls) == 1
    assert len(api_calls[0]) == 1


def test_second_retrieval_in_process_hits_cache(api_calls) -> None:
    """同一字段集在本进程第二次检索零 API 调用，结果与首轮一致。"""
    first = field_retriever.batch_retrieve_candidates_table(["src_ip", "dst_ip"])
    assert len(api_calls) == 1

    second = field_retriever.batch_retrieve_candidates_table(["src_ip", "dst_ip"])

    assert len(api_calls) == 1
    assert second == first


def test_variant_round_reuses_main_round_vectors(api_calls) -> None:
    """去前缀变体与主字段复合文本相同时，变体轮不再调 API。"""
    # 主轮：severity 与 data.severity 两个唯一文本 → 单批一次调用；
    # 变体轮：data.severity → severity 已在主轮嵌入 → 缓存命中。
    field_retriever.batch_retrieve_candidates_table(["severity", "data.severity"])

    assert len(api_calls) == 1
    assert len(api_calls[0]) == 2


def test_failure_on_miss_propagates_and_caches_nothing(monkeypatch) -> None:
    """miss 失败语义与现状一致：主轮 raise，且失败结果不写缓存。"""
    monkeypatch.setattr(field_retriever, "_load_cache", lambda: (EMBEDDINGS, RECORDS))
    monkeypatch.setattr(field_retriever, "_call_embedding_api", lambda _texts: None)

    with pytest.raises(RuntimeError):
        field_retriever.batch_retrieve_candidates_table(["src_ip"])

    calls: list[list[str]] = []

    def _fake_api(texts):
        calls.append(list(texts))
        return np.array([[1.0, 0.0] for _ in texts])

    monkeypatch.setattr(field_retriever, "_call_embedding_api", _fake_api)
    field_retriever.batch_retrieve_candidates_table(["src_ip"])

    assert len(calls) == 1


def test_variant_failure_degrades_without_raising(monkeypatch) -> None:
    """主轮命中缓存、变体轮 miss 失败时仅跳过变体，不抛异常（现状降级语义）。"""
    monkeypatch.setattr(field_retriever, "_load_cache", lambda: (EMBEDDINGS, RECORDS))
    monkeypatch.setattr(
        field_retriever,
        "_call_embedding_api",
        lambda _texts: np.array([[1.0, 0.0] for _ in _texts]),
    )
    field_retriever.batch_retrieve_candidates_table(["data.severity"])

    # 只剔除变体文本的缓存，模拟「主轮命中、变体轮 miss」
    variant_text = field_retriever._build_query_text_for_embedding("severity")
    field_retriever._QUERY_EMBEDDING_CACHE.pop(
        field_retriever._query_cache_key(variant_text), None
    )
    monkeypatch.setattr(field_retriever, "_call_embedding_api", lambda _texts: None)

    table = field_retriever.batch_retrieve_candidates_table(["data.severity"])

    assert "data.severity" in table
