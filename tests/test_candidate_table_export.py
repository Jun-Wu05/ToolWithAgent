"""#180 结构化候选出口：markdown 渲染与历史输出逐字节一致的构造性证明。"""

from __future__ import annotations

import numpy as np


def _mock_retrieval(monkeypatch):
    """复用表征测试的缓存/嵌入假件：源地址与查询同向，目的地址正交。"""
    from agent.core import field_retriever

    records = [
        {"系统属性名称": "事件名称", "字段名称": "event_name"},
        {"系统属性名称": "源地址", "字段名称": "src_address"},
        {"系统属性名称": "目的地址", "字段名称": "dst_address"},
    ]
    embeddings = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    monkeypatch.setattr(field_retriever, "_load_cache", lambda: (embeddings, records))
    monkeypatch.setattr(
        field_retriever,
        "_call_embedding_api",
        lambda texts: np.array([[1.0, 0.0] for _ in texts]),
    )


def test结构化出口与markdown出口逐字节一致(monkeypatch) -> None:
    """同输入下：table → render 与历史 batch_retrieve_candidates 输出完全相同。"""
    _mock_retrieval(monkeypatch)
    from agent.core.field_retriever import (
        batch_retrieve_candidates,
        batch_retrieve_candidates_table,
        render_candidates_markdown,
    )

    table = batch_retrieve_candidates_table(["srcAddress"], top_k=2)
    assert table == {"srcAddress": [("源地址", 1.0, "src_address", "")]}

    markdown = render_candidates_markdown(table, top_k=2)
    assert markdown == batch_retrieve_candidates(["srcAddress"], top_k=2)
    assert markdown == (
        "## 标准字段候选（语义检索 top-2，按相似度降序）：\n"
        "srcAddress → 源地址(1.00, src_address)"
    )


def test结构化出口空输入与空表的契约(monkeypatch) -> None:
    """空字段列表返回空表；空表渲染为空字符串，与 markdown 出口行为对齐。"""
    _mock_retrieval(monkeypatch)
    from agent.core.field_retriever import (
        batch_retrieve_candidates,
        batch_retrieve_candidates_table,
        render_candidates_markdown,
    )

    assert batch_retrieve_candidates_table([]) == {}
    assert render_candidates_markdown({}, top_k=5) == ""
    assert batch_retrieve_candidates([]) == ""


def test候选行渲染包含by_stripped后缀() -> None:
    """变体候选行（第 4 元非空）渲染为与历史格式一致的 by_stripped 后缀。"""
    from agent.core.field_retriever import _format_candidate, render_candidates_markdown

    assert _format_candidate(("威胁等级", 0.71, "threat_level", "threat")) == (
        "威胁等级(0.71, threat_level, by_stripped=threat)"
    )
    table = {"x.threat": [("威胁等级", 0.71, "threat_level", "threat")]}
    assert render_candidates_markdown(table, top_k=5) == (
        "## 标准字段候选（语义检索 top-5，按相似度降序）：\n"
        "x.threat → 威胁等级(0.71, threat_level, by_stripped=threat)"
    )
