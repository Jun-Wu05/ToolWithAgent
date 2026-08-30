"""字段映射解析器对结构化输出与空结果的回归测试。"""

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
