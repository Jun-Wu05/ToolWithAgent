"""Issue #155：冻结标准字段目录迁移前的兼容行为。"""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "config"
EXPECTED_HEADER = (
    "系统属性名称\t属性分类\t字段名称\t属性类型\t描述\t枚举值\t对象"
)


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_standard_field_resources_keep_current_schema_and_record_count() -> None:
    """目录迁移不得静默改变字段表及其辅助资源的外部 schema。"""
    from agent.prompts import load_standard_fields

    raw_table = load_standard_fields()
    lines = raw_table.splitlines()
    synonyms = json.loads((CONFIG / "field_synonyms.json").read_text(encoding="utf-8"))
    tag_rules = json.loads((CONFIG / "tag_rules.json").read_text(encoding="utf-8"))

    assert lines[0] == EXPECTED_HEADER
    assert len(lines) - 1 == 625
    assert all(len(line.split("\t")) == 7 for line in lines[1:])
    assert synonyms["src"] == {"en": "source", "zh": ["源", "源地址"]}
    assert synonyms["src_ip"] == {
        "en": "source_ip",
        "zh": ["源IP地址", "源IP", "源地址"],
    }
    assert isinstance(tag_rules["rules"], dict)
    assert tag_rules["rules"]


def test_cache_metadata_matches_all_index_inputs() -> None:
    """现有缓存兼容键必须覆盖字段表、标签规则、同义词及模型配置。"""
    from agent.core import field_retriever

    meta = json.loads(
        (CONFIG / "标准字段_cache_meta.json").read_text(encoding="utf-8")
    )

    assert meta == {
        "schema_version": field_retriever.CACHE_SCHEMA_VERSION,
        "standard_fields_md5": _md5(CONFIG / "标准字段.txt"),
        "tag_rules_md5": _md5(CONFIG / "tag_rules.json"),
        "synonyms_md5": _md5(CONFIG / "field_synonyms.json"),
        "record_count": 625,
        "embedding_model": field_retriever.EMBEDDING_MODEL,
        "embedding_dim": field_retriever.EMBEDDING_DIM,
        "created_at": meta["created_at"],
    }
    assert datetime.fromisoformat(meta["created_at"])


def test_public_runtime_entry_preserves_lookup_exclusions_and_format(monkeypatch) -> None:
    """公共入口保持名称归一化、固定字段排除及文本返回格式。"""
    import application.field_runtime as runtime
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

    assert runtime.__all__ == ["batch_retrieve_candidates", "init_field_cache"]
    assert list(inspect.signature(runtime.batch_retrieve_candidates).parameters) == [
        "raw_field_names",
        "top_k",
    ]
    assert runtime.batch_retrieve_candidates([]) == ""
    assert runtime.batch_retrieve_candidates(["srcAddress"], top_k=2) == (
        "## 标准字段候选（语义检索 top-2，按相似度降序）：\n"
        "srcAddress → 源地址(1.00, src_address)"
    )


def test_nested_field_variant_exact_match_pins_stripped_hit(monkeypatch) -> None:
    """Layer 1.5：嵌套字段的去前缀变体精确命中目录时置顶 1.00 候选（#363）。"""
    import application.field_runtime as runtime
    from agent.core import field_retriever

    records = [
        {"系统属性名称": "事件名称", "字段名称": "event_name"},
        {"系统属性名称": "严重程度", "字段名称": "severity"},
    ]
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
    monkeypatch.setattr(field_retriever, "_load_cache", lambda: (embeddings, records))
    monkeypatch.setattr(
        field_retriever,
        "_call_embedding_api",
        lambda texts: np.array([[0.0, 1.0] for _ in texts]),
    )

    table = field_retriever.batch_retrieve_candidates_table(["data.severity"])
    assert table["data.severity"][0] == ("严重程度", 1.0, "severity", "severity")

    assert runtime.batch_retrieve_candidates(["data.severity"], top_k=2) == (
        "## 标准字段候选（语义检索 top-2，按相似度降序）：\n"
        "data.severity → 严重程度(1.00, severity, by_stripped=severity)"
    )


def test_stale_cache_without_api_key_fails_closed_without_rebuild(monkeypatch) -> None:
    """缓存元数据缺失且无法重建时，公共初始化入口稳定返回 False。"""
    from agent.core import field_retriever

    # 只借用仓库内已存在的缓存文件触发校验分支；测试不会读取或改写它们。
    assert field_retriever._CACHE_EMBEDDINGS_PATH.exists()
    assert field_retriever._CACHE_RECORDS_PATH.exists()
    monkeypatch.setattr(field_retriever, "_get_cache_meta", lambda: None)
    monkeypatch.setattr(field_retriever, "_get_api_key", lambda: None)
    monkeypatch.setattr(
        field_retriever,
        "_build_cache",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("无 API Key 时不应尝试重建缓存")
        ),
    )

    assert field_retriever.init_field_cache() is False


def _build_matching_cache_meta() -> dict:
    """构造与当前常量及索引输入文件全部匹配的缓存元数据。"""
    from agent.core import field_retriever

    return {
        "schema_version": field_retriever.CACHE_SCHEMA_VERSION,
        "standard_fields_md5": _md5(CONFIG / "标准字段.txt"),
        "tag_rules_md5": _md5(CONFIG / "tag_rules.json"),
        "synonyms_md5": _md5(CONFIG / "field_synonyms.json"),
        "embedding_model": field_retriever.EMBEDDING_MODEL,
        "embedding_dim": field_retriever.EMBEDDING_DIM,
    }


def _stub_rebuild_path(monkeypatch, stale_meta: dict) -> list:
    """接上重建路径记录桩：API Key、标准字段表与缓存构建全部打桩。"""
    from agent.core import field_retriever

    rebuild_calls: list = []
    records = [{"_composite_text": "事件名称"}]
    monkeypatch.setattr(field_retriever, "_get_cache_meta", lambda: stale_meta)
    monkeypatch.setattr(field_retriever, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(field_retriever, "_load_standard_fields", lambda: records)
    monkeypatch.setattr(
        field_retriever,
        "_build_cache",
        lambda texts, recs: rebuild_calls.append((texts, recs)),
    )
    return rebuild_calls


def test_stale_cache_model_mismatch_triggers_rebuild(monkeypatch) -> None:
    """meta 的 embedding_model 与当前模型不一致时必须触发重建，不得静默复用旧向量。"""
    from agent.core import field_retriever

    assert field_retriever._CACHE_EMBEDDINGS_PATH.exists()
    assert field_retriever._CACHE_RECORDS_PATH.exists()
    stale_meta = _build_matching_cache_meta()
    stale_meta["embedding_model"] = "Other/Embedding-Model"

    rebuild_calls = _stub_rebuild_path(monkeypatch, stale_meta)

    assert field_retriever.init_field_cache() is True
    assert len(rebuild_calls) == 1


def test_stale_cache_dim_mismatch_triggers_rebuild(monkeypatch) -> None:
    """meta 的 embedding_dim 与当前维度不一致时必须触发重建。"""
    from agent.core import field_retriever

    assert field_retriever._CACHE_EMBEDDINGS_PATH.exists()
    assert field_retriever._CACHE_RECORDS_PATH.exists()
    stale_meta = _build_matching_cache_meta()
    stale_meta["embedding_dim"] = field_retriever.EMBEDDING_DIM + 1024

    rebuild_calls = _stub_rebuild_path(monkeypatch, stale_meta)

    assert field_retriever.init_field_cache() is True
    assert len(rebuild_calls) == 1


def test_fresh_cache_with_matching_model_and_dim_skips_rebuild(monkeypatch) -> None:
    """模型/维度与当前常量一致且其余键匹配时不得触发重建（防止过度失效）。"""
    from agent.core import field_retriever

    assert field_retriever._CACHE_EMBEDDINGS_PATH.exists()
    assert field_retriever._CACHE_RECORDS_PATH.exists()
    monkeypatch.setattr(
        field_retriever, "_get_cache_meta", lambda: _build_matching_cache_meta()
    )
    monkeypatch.setattr(
        field_retriever,
        "_build_cache",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("匹配的缓存元数据不应触发重建")
        ),
    )

    assert field_retriever.init_field_cache() is True
