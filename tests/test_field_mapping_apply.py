"""字段映射回填到配置的回归测试（#177 后：标准字段目录是名称/对象 SSOT）。"""

from agent.tools.rule_generator.field_mapping import (
    apply_field_mapping_to_config,
    apply_field_mapping_to_sub_rules,
    find_non_catalog_field_entities,
    resolve_standard_field,
)


def test字段映射回填到配置normalize条目():
    config = {
        "name": "rule-1",
        "normalize": [
            {"index": "src_ip"},
            {"index": "unknown_field"},
            {"index": "original_log"},
        ],
    }
    mappings = [
        {"原始字段名": "src_ip", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
        {"原始字段名": "unknown_field", "系统属性名称": "未匹配", "匹配状态": "未匹配"},
    ]
    result = apply_field_mapping_to_config(config, mappings)
    norm = {entry["index"]: entry for entry in result["normalize"]}

    # 目录：源地址 对象列 '流量,登录' → 取首个「流量」（与 对象.xlsx 历史语义一致）
    assert norm["src_ip"]["field"] == "源地址"
    assert norm["src_ip"]["entity"] == "流量"
    assert norm["src_ip"]["sim"] is True
    assert norm["src_ip"]["core"] is False
    # 未匹配不回填
    assert "field" not in norm["unknown_field"]
    # 系统元字段不回填
    assert "field" not in norm["original_log"]
    # 原对象未被修改
    assert "field" not in config["normalize"][0]


def test英文字段名变体在目录可唯一定位时规范化写入():
    """模型输出英文字段名/前后空白时接受并改写为目录规范系统属性名称。"""
    config = {"rules": [{"sub": {"normalize": [{"index": "dst_port"}]}}]}
    mappings = [
        {"原始字段名": "dst_port", "系统属性名称": "  dst_port ", "匹配状态": "匹配成功"}
    ]
    result = apply_field_mapping_to_config(config, mappings)

    target = result["rules"][0]["sub"]["normalize"][0]
    assert target["field"] == "目的端口"
    assert target["entity"] == "流量"


def test目录外名称不写入配置条目():
    """目录外系统属性名称不得写入配置：条目保持原样（field 仍为空）。"""
    config = {"normalize": [{"index": "src_ip"}]}
    mappings = [
        {"原始字段名": "src_ip", "系统属性名称": "外部源IP", "匹配状态": "匹配成功"}
    ]
    result = apply_field_mapping_to_config(config, mappings)
    assert "field" not in result["normalize"][0]


def test上传配置已映射条目保留原值且未映射条目正常写入():
    """写回层保护外部已有映射，同时允许 mappings 非空的未映射字段参与。"""
    config = {
        "normalize": [
            {
                "index": "src_ip",
                "field": "外部源IP",
                "entity": "外部对象",
                "sim": False,
                "core": True,
            },
            {
                "index": "threat_code",
                "field": "",
                "mappings": [
                    {"mappingType": "EQUAL", "orgValue": "1", "mappingValue": "高"}
                ],
            },
        ]
    }
    mappings = [
        {"原始字段名": "src_ip", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
        {"原始字段名": "threat_code", "系统属性名称": "威胁等级", "匹配状态": "匹配成功"},
    ]

    result = apply_field_mapping_to_config(config, mappings)
    normalized = {entry["index"]: entry for entry in result["normalize"]}

    assert normalized["src_ip"] == config["normalize"][0]
    assert normalized["threat_code"]["field"] == "威胁等级"
    assert normalized["threat_code"]["entity"] == "威胁"
    assert normalized["threat_code"]["mappings"] == config["normalize"][1]["mappings"]
    assert "field" not in config["normalize"][1] or config["normalize"][1]["field"] == ""


def test子规则重映射时显式未匹配行清空旧字段映射():
    """#165 冲突落选行不得在 mapped_sub_rules 中残留上次映射。"""
    sub_rules = [
        {
            "name": "rule-a",
            "normalize": [
                {
                    "index": "src_ip",
                    "field": "旧标准字段",
                    "entity": "旧对象",
                    "sim": True,
                    "core": False,
                }
            ],
        }
    ]
    mapping_results = [
        {
            "rule_name": "rule-a",
            "mappings": [
                {
                    "原始字段名": "src_ip",
                    "系统属性名称": "未匹配",
                    "匹配状态": "未匹配",
                }
            ],
        }
    ]

    result = apply_field_mapping_to_sub_rules(sub_rules, mapping_results)
    normalized = result[0]["normalize"][0]

    assert normalized["field"] is None
    assert normalized["entity"] is None
    assert normalized["sim"] is None
    assert normalized["core"] is None
    assert sub_rules[0]["normalize"][0]["field"] == "旧标准字段"


def test子规则目录外名称降级清空而非默认对象():
    """#177：目录外名称 + 匹配成功 → 子规则条目降级清空，不默认「事件」。"""
    sub_rules = [{"name": "rule-a", "normalize": [{"index": "src_ip"}]}]
    mapping_results = [
        {
            "rule_name": "rule-a",
            "mappings": [
                {"原始字段名": "src_ip", "系统属性名称": "天眼ID", "匹配状态": "匹配成功"}
            ],
        }
    ]

    result = apply_field_mapping_to_sub_rules(sub_rules, mapping_results)
    normalized = result[0]["normalize"][0]
    assert normalized["field"] is None
    assert normalized["entity"] is None


def test多子规则共享字段全部回写且不新增normalize():
    """#23: 共享字段复用到所有子规则、独有字段按作用域回写，且不新增 normalize 项。

    映射行使用英文/变体字段名（src_address/dst_mac），回写时规范化为目录中文名。
    """
    sub_rules = [
        {"name": "rule-a", "normalize": [{"index": "src_ip"}]},
        {"name": "rule-b", "normalize": [{"index": "src_ip"}, {"index": "dst_mac"}]},
    ]
    mapping_rows = [
        {"原始字段名": "src_ip", "系统属性名称": "src_address", "匹配状态": "匹配成功"},
        {"原始字段名": "dst_mac", "系统属性名称": "dst_mac", "匹配状态": "匹配成功"},
    ]
    per_rule_results = [
        {
            "rule_name": str(sub_rule.get("name", "")),
            "mappings": [
                row
                for row in mapping_rows
                if str(row.get("原始字段名", ""))
                in {str(item.get("index", "")) for item in sub_rule.get("normalize", []) or []}
            ],
        }
        for sub_rule in sub_rules
    ]

    result = apply_field_mapping_to_sub_rules(sub_rules, per_rule_results)

    rule_a = {entry["index"]: entry for entry in result[0]["normalize"]}
    rule_b = {entry["index"]: entry for entry in result[1]["normalize"]}

    # 共享字段 src_ip：两条子规则规范名称一致（src_ip → 源地址）。
    assert rule_a["src_ip"]["field"] == "源地址"
    assert rule_b["src_ip"]["field"] == "源地址"
    assert rule_a["src_ip"]["entity"] == rule_b["src_ip"]["entity"] == "流量"
    # rule-b 独有字段 dst_mac：规范名称 目的MAC，在原位置回写。
    assert rule_b["dst_mac"]["field"] == "目的MAC"
    assert rule_b["dst_mac"]["entity"] == "流量"
    # 不新增 normalize 项
    assert len(result[0]["normalize"]) == 1
    assert len(result[1]["normalize"]) == 2
    assert "dst_mac" not in rule_a
    # 原始子规则未被修改
    assert "field" not in sub_rules[0]["normalize"][0]


def test映射无法对应既有normalize项时跳过且不新增():
    """#23: 映射结果无法对应任何既有 normalize 项时跳过，不创建新条目。"""
    sub_rules = [{"name": "rule-a", "normalize": [{"index": "src_ip"}]}]
    per_rule_results = [
        {
            "rule_name": "rule-a",
            "mappings": [
                {"原始字段名": "src_ip", "系统属性名称": "源地址", "匹配状态": "匹配成功"},
                {"原始字段名": "extra_field", "系统属性名称": "额外", "匹配状态": "匹配成功"},
            ],
        }
    ]

    result = apply_field_mapping_to_sub_rules(sub_rules, per_rule_results)

    norm = result[0]["normalize"]
    assert len(norm) == 1
    assert norm[0]["index"] == "src_ip"
    assert norm[0]["field"] == "源地址"


def test非目录组合诊断扫描只报告不改写():
    """上传配置非法组合（目录外 field / 对象不一致）被扫描发现，数据不动。"""
    config = {
        "normalize": [
            {"index": "a", "field": "外部源IP", "entity": "外部对象"},
            {"index": "b", "field": "源地址", "entity": "错误对象"},
            {"index": "c", "field": "源地址", "entity": "流量"},
            {"index": "d"},
        ]
    }
    illegal = find_non_catalog_field_entities(config)

    assert [item[0] for item in illegal] == ["a", "b"]
    assert illegal[0] == ("a", "外部源IP", "外部对象")
    # 原数据未被改写
    assert config["normalize"][1]["entity"] == "错误对象"


def test目录解析助手接受空白与英文变体拒绝目录外():
    assert resolve_standard_field("  源地址 ") is not None
    assert resolve_standard_field("src_address") is not None
    assert resolve_standard_field("src_address").system_property_name == "源地址"
    assert resolve_standard_field("") is None
    assert resolve_standard_field("天眼ID") is None
    assert resolve_standard_field(None) is None
