"""Issue #129：入口/子规则的数据源字段契约与纯生成逻辑。"""

import pytest


def _classification(log_format: str = "JSON") -> dict:
    return {
        "log_format": log_format,
        "log_format_detail": "纯JSON" if log_format == "JSON" else "纯KV",
        "feature_field": "categoryName",
        "Diversion_method": "日志类型",
        "analysis": {"delimit": " ", "tab": "="},
        "classification_details": [
            {
                "logtype": "审计事件",
                "sample": '{"categoryName":"审计事件","src_ip":"10.0.0.1"}',
                "real_samples": '{"categoryName":"审计事件","src_ip":"10.0.0.1"}',
            }
        ],
    }


def test_rule_source_fields_normalizes_and_composes_default_data_source() -> None:
    from contracts.rule_source import RuleSourceFields

    fields = RuleSourceFields.create(
        product="  XX产品 ", log_vendor=" XX厂商  ", data_source="  "
    )

    assert fields.product == "XX产品"
    assert fields.log_vendor == "XX厂商"
    assert fields.data_source == "XX产品(XX厂商)"


def test_rule_source_fields_preserves_explicit_data_source() -> None:
    from contracts.rule_source import RuleSourceFields

    fields = RuleSourceFields.create(
        product="XX产品", log_vendor="XX厂商", data_source="自定义来源"
    )

    assert fields.data_source == "自定义来源"


@pytest.mark.parametrize("missing", ["product", "log_vendor"])
def test_rule_source_fields_requires_product_and_vendor(missing: str) -> None:
    from contracts.rule_source import RuleSourceFields

    values = {"product": "XX产品", "log_vendor": "XX厂商"}
    values[missing] = "  "

    with pytest.raises(ValueError, match="数据源产品|数据源厂商"):
        RuleSourceFields.create(**values)


def test_entry_rule_appends_source_filter_normalize_and_properties() -> None:
    from agent.tools.rule_generator import generate_entry_rule
    from contracts.rule_source import RuleSourceFields

    fields = RuleSourceFields.create(product="XX产品", log_vendor="XX厂商")
    rule = generate_entry_rule(
        _classification(),
        date_str="20260901",
        uuid_str="entry-id",
        rule_source_fields=fields,
    )

    assert rule["name"] == "XX厂商_XX产品_通用_入口规则0901"
    assert rule["parser"]["filter"][-1] == {
        "fields": {
            "data_source": "XX产品(XX厂商)",
            "log_vendor": "XX厂商",
            "product": "XX产品",
        },
        "name": "addFields",
        "id": "",
    }
    assert rule["parser"]["filter"][0]["id"] == "additional_fields_filter"

    source_normalize = {item["index"]: item for item in rule["normalize"][-3:]}
    assert list(source_normalize) == ["product", "log_vendor", "data_source"]
    assert source_normalize["product"] | {"result": []} == {
        "mappings": [], "field": "product", "sim": False,
        "result": [], "info": None, "entity": "日志", "required": False,
        "core": True, "value": None, "index": "product",
    }
    assert source_normalize["product"]["result"] == ["XX产品"]
    assert source_normalize["log_vendor"]["core"] is True
    assert source_normalize["log_vendor"]["result"] == ["XX厂商"]
    assert source_normalize["data_source"]["core"] is False
    assert source_normalize["data_source"]["result"] == ["XX产品(XX厂商)"]

    source_properties = {item["key"]: item for item in rule["properties"][-3:]}
    assert [item["key"] for item in rule["properties"][-3:]] == [
        "product", "log_vendor", "data_source"
    ]
    assert source_properties["product"]["name"] == "数据源产品"
    assert source_properties["product"]["sample"] == ["XX产品"]
    assert source_properties["log_vendor"]["name"] == "数据源厂商"
    assert source_properties["data_source"]["name"] == "数据源"
    assert source_properties["data_source"]["sample"] == ["XX产品(XX厂商)"]
    assert not any(item.get("key") == "original_log" for item in rule["properties"])


@pytest.mark.parametrize(
    ("log_format", "expected_name"),
    [
        ("JSON", "XX厂商_XX产品_审计事件_json_子规则"),
        ("KV", "XX厂商_XX产品_审计事件_kv_子规则"),
        ("REGEX", "XX厂商_XX产品_审计事件_日志类型_子规则"),
    ],
)
def test_sub_rule_names_include_vendor_and_product(
    log_format: str, expected_name: str
) -> None:
    from agent.tools.rule_generator import generate_sub_rules
    from contracts.rule_source import RuleSourceFields

    classification = _classification(log_format)
    if log_format == "REGEX":
        classification["classification_details"][0]["real_samples"] = "raw sample"
    fields = RuleSourceFields.create(product="XX产品", log_vendor="XX厂商")

    rules = generate_sub_rules(classification, rule_source_fields=fields)

    assert rules[0]["name"] == expected_name


def test_legacy_generator_names_and_source_structures_remain_unchanged() -> None:
    from agent.tools.rule_generator import generate_entry_rule, generate_sub_rules

    classification = _classification()
    entry = generate_entry_rule(
        classification, date_str="20260901", uuid_str="entry-id"
    )
    sub_rule = generate_sub_rules(classification, date_str="20260901")[0]

    assert entry["name"] == "入口规则_20260901"
    assert sub_rule["name"] == "审计事件_categoryName_json_子规则"
    assert not any(item.get("index") == "product" for item in entry["normalize"])
    assert not any(item.get("key") == "product" for item in entry["properties"])
