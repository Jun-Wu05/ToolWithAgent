"""模型输出解析器（威胁映射/字段映射）容错阶梯的回归测试。"""

import logging


def test空结构化结果不再误报解析失败(caplog):
    """模型返回空 FieldMappingList 是合法的"无映射"，不应落入字符串兜底误报失败。"""
    from agent.core.team import FieldMappingList
    from application.parsing import parse_json_mapping_result

    caplog.set_level(logging.DEBUG)
    result = parse_json_mapping_result(FieldMappingList(items=[]))

    assert result == []
    assert "获得 0 条有效记录" in caplog.text
    assert "所有方法均解析失败" not in caplog.text


def test结构化结果记录模型原始返回(caplog):
    """字段映射解析时在 DEBUG 记录模型原始返回，便于排查（仅字段名，无原值）。"""
    from agent.core.team import FieldMappingItem, FieldMappingList
    from application.parsing import parse_json_mapping_result

    caplog.set_level(logging.DEBUG)
    payload = FieldMappingList(
        items=[
            FieldMappingItem(原始字段名="src_ip", 系统属性名称="源IP", 匹配状态="匹配成功"),
        ]
    )
    result = parse_json_mapping_result(payload)

    assert len(result) == 1
    assert result[0]["原始字段名"] == "src_ip"
    assert "src_ip" in caplog.text  # DEBUG 记录了模型原始返回


def test威胁解析器从噪声文本截取JSON数组():
    """威胁映射：方法2 从首尾方括号截取合法数组并按三列白名单过滤多余键。"""
    from application.parsing import parse_json_threat_result

    content = (
        '前置噪声 [{"mappingType":"归一化","orgValue":"a",'
        '"mappingValue":"b","extra":"x"}] 后置噪声'
    )
    result = parse_json_threat_result(content)
    assert result == [{"mappingType": "归一化", "orgValue": "a", "mappingValue": "b"}]


def test威胁解析器整体JSON字典经items解包():
    """威胁映射：json_unwrap 开启，整体 JSON 字典的 items 子数组在方法1即解包。"""
    from application.parsing import parse_json_threat_result

    content = '{"items":[{"mappingType":"t","orgValue":"o","mappingValue":"m"}]}'
    result = parse_json_threat_result(content)
    assert result == [{"mappingType": "t", "orgValue": "o", "mappingValue": "m"}]


def test映射解析器修复中文标点后重试():
    """字段映射：方法4 将弯引号等中文标点修复为 ASCII 后重新 json.loads。"""
    from application.parsing import parse_json_mapping_result

    content = (
        "[{\u201c原始字段名\u201d:\u201c源IP\u201d,"
        "\u201c系统属性名称\u201d:\u201c源IP\u201d,"
        "\u201c匹配状态\u201d:\u201c匹配成功\u201d}]"
    )
    result = parse_json_mapping_result(content)
    assert result == [
        {"原始字段名": "源IP", "系统属性名称": "源IP", "匹配状态": "匹配成功"}
    ]


def test映射解析器正则逐项提取兜底():
    """字段映射：JSON 全失败但正文含完整三列条目时，方法5 逐项提取。"""
    from application.parsing import parse_json_mapping_result

    content = (
        "模型输出损坏，但可见条目："
        '{"原始字段名":"源IP","系统属性名称":"源IP","匹配状态":"匹配成功"} 请核对'
    )
    result = parse_json_mapping_result(content)
    assert result == [
        {"原始字段名": "源IP", "系统属性名称": "源IP", "匹配状态": "匹配成功"}
    ]


def test映射解析器拒绝响应识别(caplog):
    """字段映射：索要数据类拒绝文本应识别为疑似拒绝响应并返回空。"""
    from application.parsing import parse_json_mapping_result

    caplog.set_level(logging.WARNING)
    result = parse_json_mapping_result("无法完成映射，请提供原始日志")

    assert result == []
    assert "疑似拒绝响应" in caplog.text


def test映射解析器未匹配矛盾自动修正(caplog):
    """字段映射：标准属性为「未匹配」而状态不是时，条目在解析中原地修正。"""
    from application.parsing import parse_json_mapping_result

    caplog.set_level(logging.WARNING)
    content = (
        '[{"原始字段名":"a","系统属性名称":"未匹配","匹配状态":"匹配成功"}]'
    )
    result = parse_json_mapping_result(content)

    assert result[0]["匹配状态"] == "未匹配"
    assert "未匹配状态矛盾" in caplog.text
