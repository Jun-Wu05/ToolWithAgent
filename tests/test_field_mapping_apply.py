"""字段映射回填到配置的回归测试。"""


def test字段映射回填到配置normalize条目():
    from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_config

    config = {
        "name": "rule-1",
        "normalize": [
            {"index": "src_ip"},
            {"index": "unknown_field"},
            {"index": "original_log"},
        ],
    }
    mappings = [
        {"原始字段名": "src_ip", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
        {"原始字段名": "unknown_field", "系统属性名称": "未匹配", "匹配状态": "未匹配"},
    ]
    result = apply_field_mapping_to_config(config, mappings, {"源IP": "网络对象"})
    norm = {entry["index"]: entry for entry in result["normalize"]}

    assert norm["src_ip"]["field"] == "源IP"
    assert norm["src_ip"]["entity"] == "网络对象"
    assert norm["src_ip"]["sim"] is True
    assert norm["src_ip"]["core"] is False
    # 未匹配不回填
    assert "field" not in norm["unknown_field"]
    # 系统元字段不回填
    assert "field" not in norm["original_log"]
    # 原对象未被修改
    assert "field" not in config["normalize"][0]


def test字段映射回填递归嵌套normalize():
    from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_config

    config = {"rules": [{"sub": {"normalize": [{"index": "dst_port"}]}}]}
    mappings = [{"原始字段名": "dst_port", "系统属性名称": "目的端口", "匹配状态": "匹配成功"}]
    result = apply_field_mapping_to_config(config, mappings)

    target = result["rules"][0]["sub"]["normalize"][0]
    assert target["field"] == "目的端口"
    assert target["entity"] == "事件"  # 无 object_entity_map 时默认「事件」


def test上传配置已映射条目保留原值且未映射条目正常写入():
    """写回层保护外部已有映射，同时允许 mappings 非空的未映射字段参与。"""
    from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_config

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
        {"原始字段名": "src_ip", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
        {"原始字段名": "threat_code", "系统属性名称": "威胁等级", "匹配状态": "匹配成功"},
    ]

    result = apply_field_mapping_to_config(
        config,
        mappings,
        {"源IP": "网络对象", "威胁等级": "事件"},
    )
    normalized = {entry["index"]: entry for entry in result["normalize"]}

    assert normalized["src_ip"] == config["normalize"][0]
    assert normalized["threat_code"]["field"] == "威胁等级"
    assert normalized["threat_code"]["mappings"] == config["normalize"][1]["mappings"]
    assert "field" not in config["normalize"][1] or config["normalize"][1]["field"] == ""


def test子规则重映射时显式未匹配行清空旧字段映射():
    """#165 冲突落选行不得在 mapped_sub_rules 中残留上次映射。"""
    from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_sub_rules

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


def test多子规则共享字段全部回写且不新增normalize():
    """#23: 共享字段复用到所有子规则、独有字段按作用域回写，且不新增 normalize 项。

    复现条件：rule-a 仅含 src_ip，rule-b 含 src_ip 与 dst_mac；标准字段映射得到
    src_ip→src_ip、dst_mac→dst_mac。适配器按每条子规则的字段集合分发映射后回写。
    """
    from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_sub_rules

    sub_rules = [
        {"name": "rule-a", "normalize": [{"index": "src_ip"}]},
        {"name": "rule-b", "normalize": [{"index": "src_ip"}, {"index": "dst_mac"}]},
    ]
    # 全局映射结果按唯一原始字段计算一次
    mapping_rows = [
        {"原始字段名": "src_ip", "系统属性名称": "src_ip", "匹配状态": "匹配成功"},
        {"原始字段名": "dst_mac", "系统属性名称": "dst_mac", "匹配状态": "匹配成功"},
    ]
    # 与 _execute_field_mapping 一致：按每条子规则的字段集合分发映射
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

    # 共享字段 src_ip：两条子规则的既有 normalize 项都得到同一映射（原始==标准名亦正确）。
    assert rule_a["src_ip"]["field"] == "src_ip"
    assert rule_b["src_ip"]["field"] == "src_ip"
    # rule-b 独有字段 dst_mac：在原位置回写，不误报未找到。
    assert rule_b["dst_mac"]["field"] == "dst_mac"
    # 不新增 normalize 项：各规则条目数不变，rule-a 不会被追加 dst_mac。
    assert len(result[0]["normalize"]) == 1
    assert len(result[1]["normalize"]) == 2
    assert "dst_mac" not in rule_a
    # 原始子规则未被修改
    assert "field" not in sub_rules[0]["normalize"][0]


def test映射无法对应既有normalize项时跳过且不新增():
    """#23: 映射结果无法对应任何既有 normalize 项时跳过，不创建新条目。"""
    from agent.tools.rule_generator.field_mapping import apply_field_mapping_to_sub_rules

    sub_rules = [{"name": "rule-a", "normalize": [{"index": "src_ip"}]}]
    # 唯一字段 src_ip 映射成功；extra_field 在任何子规则都不存在
    per_rule_results = [
        {
            "rule_name": "rule-a",
            "mappings": [
                {"原始字段名": "src_ip", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
                {"原始字段名": "extra_field", "系统属性名称": "额外", "匹配状态": "匹配成功"},
            ],
        }
    ]

    result = apply_field_mapping_to_sub_rules(sub_rules, per_rule_results)

    # src_ip 回写，extra_field 不创建新条目，normalize 条目数保持 1
    norm = result[0]["normalize"]
    assert len(norm) == 1
    assert norm[0]["index"] == "src_ip"
    assert norm[0]["field"] == "源IP"
