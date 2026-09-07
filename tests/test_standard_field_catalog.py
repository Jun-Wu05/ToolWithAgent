"""Issue #156：只读 StandardFieldCatalog 的领域契约。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


def test_catalog_loads_immutable_schema_and_resource_facts() -> None:
    from agent.core.standard_field_catalog import (
        STANDARD_FIELD_COLUMNS,
        StandardFieldCatalog,
    )

    catalog = StandardFieldCatalog.from_default_resources()

    assert STANDARD_FIELD_COLUMNS == (
        "系统属性名称",
        "属性分类",
        "字段名称",
        "属性类型",
        "描述",
        "枚举值",
        "对象",
    )
    assert len(catalog.fields) == 625
    assert catalog.fields[0].as_record().keys() == dict.fromkeys(
        STANDARD_FIELD_COLUMNS
    ).keys()
    assert catalog.synonyms["src"]["en"] == "source"
    assert catalog.tag_rules

    with pytest.raises(FrozenInstanceError):
        catalog.fields[0].field_name = "changed"
    with pytest.raises(TypeError):
        catalog.synonyms["src"] = {"en": "changed", "zh": ()}
    with pytest.raises(TypeError):
        catalog.tag_rules["network"] = ()


def test_catalog_lookup_supports_normalized_names_chinese_and_aliases() -> None:
    from agent.core.standard_field_catalog import StandardFieldCatalog

    catalog = StandardFieldCatalog.from_default_resources()

    assert catalog.lookup("srcAddress").system_property_name == "源地址"
    assert catalog.lookup("源地址").field_name == "src_address"
    assert catalog.lookup("HTTP方法").field_name == "http_method"
    assert catalog.lookup("does_not_exist") is None


def test_catalog_index_is_deterministic_and_records_are_defensive_copies() -> None:
    from agent.core.standard_field_catalog import StandardFieldCatalog

    first = StandardFieldCatalog.from_default_resources()
    second = StandardFieldCatalog.from_default_resources()

    assert tuple(first.name_index.items()) == tuple(second.name_index.items())
    assert first.name_index["src_address"] == first.name_index["srcaddress"]
    records = first.records()
    records[0]["系统属性名称"] = "changed"
    assert first.fields[0].system_property_name != "changed"


def test_catalog_has_no_retrieval_or_network_dependencies() -> None:
    """Catalog 边界不拥有 embedding、模型调用、排序或检索缓存生命周期。"""
    import agent.core.standard_field_catalog as catalog_module

    source = Path(catalog_module.__file__).read_text(encoding="utf-8")

    assert "import numpy" not in source
    assert "import requests" not in source
    assert "embedding" not in source.lower()
    assert "candidate" not in source.lower()
    assert "rank" not in source.lower()


def test_field_retriever_delegates_catalog_facts_and_index(monkeypatch) -> None:
    from agent.core import field_retriever

    class FakeCatalog:
        synonyms = {"src": {"en": "source", "zh": ("源",)}}
        tag_rules = {"network": ("src",)}

        def records(self):
            return [
                {
                    "系统属性名称": "源地址",
                    "属性分类": "业务属性",
                    "字段名称": "src_address",
                    "属性类型": "IP",
                    "描述": "",
                    "枚举值": "",
                    "对象": "流量",
                }
            ]

        def build_name_index(self, records):
            assert records[0]["字段名称"] == "src_address"
            return {"delegated": 0}

    monkeypatch.setattr(
        field_retriever, "get_standard_field_catalog", lambda: FakeCatalog()
    )

    assert field_retriever._load_synonyms() == FakeCatalog.synonyms
    assert field_retriever._load_tag_rules() == FakeCatalog.tag_rules
    records = field_retriever._load_standard_fields()
    assert records[0]["_tags"] == ["network"]
    assert field_retriever._build_field_name_index(records) == {"delegated": 0}


def test_remaining_consumers_delegate_to_catalog_and_keep_prompt_policy(monkeypatch) -> None:
    """standard_mapper 与 Prompt 公共入口共享 Catalog，且保留旧返回策略。"""
    from types import SimpleNamespace

    import agent.prompts as prompts
    from agent.tools import standard_mapper

    class FakeCatalog:
        fields = (SimpleNamespace(system_property_name="源地址"),)
        synonyms = {"src": {"en": "source", "zh": ("源",)}}
        standard_fields_text = "系统属性名称\t字段名称\n源地址\tsrc_address\n"

        def records(self):
            return [{"系统属性名称": "源地址", "字段名称": "src_address"}]

    fake = FakeCatalog()
    monkeypatch.setattr(standard_mapper, "get_standard_field_catalog", lambda: fake)
    monkeypatch.setattr(prompts, "get_standard_field_catalog", lambda: fake)
    monkeypatch.setattr(standard_mapper, "_synonyms_cache", None)

    # #177：白名单集合已由目录解析（resolve_standard_field）取代
    assert standard_mapper._load_standard_fields_list() == fake.records()
    assert standard_mapper._load_synonyms() is fake.synonyms
    assert prompts.load_standard_fields() == fake.standard_fields_text

    monkeypatch.setattr(
        prompts,
        "get_standard_field_catalog",
        lambda: (_ for _ in ()).throw(FileNotFoundError),
    )
    assert prompts.load_standard_fields() == "标准字段表加载失败"
