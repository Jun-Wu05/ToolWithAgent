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
