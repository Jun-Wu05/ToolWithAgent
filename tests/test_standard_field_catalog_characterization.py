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
