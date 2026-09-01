"""Issue #170：冻结旧 confirmation tool 的公开兼容行为。"""

from __future__ import annotations

import json

import pytest

from agent.tools.confirmation_tool import (
    confirm_mapping_table,
    confirm_output,
    confirm_threat_mapping,
    request_modification,
)


def test_confirm_mapping_table保持合法与空值json结构() -> None:
    mappings = [{"原始字段": "src", "标准字段": "源地址"}]
    populated = json.loads(
        confirm_mapping_table.entrypoint(json.dumps(mappings, ensure_ascii=False))
    )
    empty = json.loads(confirm_mapping_table.entrypoint("[]"))

    assert populated == {
        "status": "waiting_confirmation",
        "step_name": "字段映射",
        "confirmation_message": "请确认以下字段映射表",
        "data": mappings,
        "summary": "等待确认 字段映射，共 1 个映射项",
        "action_required": "请确认是否执行此映射",
    }
    assert empty["data"] == []
    assert empty["summary"] == "等待确认 字段映射，共 0 个映射项"


def test_confirm_threat_mapping保持稳定json结构() -> None:
    mappings = [{"原始值": "scan", "威胁类型": "网络攻击"}]
    result = json.loads(
        confirm_threat_mapping.entrypoint(
            json.dumps(mappings, ensure_ascii=False),
            confirmation_message="确认威胁映射",
        )
    )

    assert result == {
        "status": "waiting_confirmation",
        "step_name": "威胁类型映射",
        "confirmation_message": "确认威胁映射",
        "data": mappings,
        "summary": "等待确认威胁类型映射，共 1 个映射项",
        "action_required": "请确认是否应用此威胁类型映射",
    }


@pytest.mark.parametrize("tool", [confirm_mapping_table, confirm_threat_mapping])
def test_mapping确认入口保持不可解析输入的现有异常(tool) -> None:
    with pytest.raises(UnboundLocalError):
        tool.entrypoint("not-json")


def test_confirm_output与request_modification保持空值返回结构() -> None:
    output = json.loads(confirm_output.entrypoint("", output_type="JSON"))
    modification = json.loads(request_modification.entrypoint("", modification_type="枚举"))

    assert output == {
        "status": "waiting_confirmation",
        "step_name": "最终输出",
        "output_type": "JSON",
        "summary": "",
        "confirmation_message": "请确认是否生成 JSON 输出",
        "action_required": "确认后将生成最终输出",
    }
    assert modification == {
        "status": "modification_requested",
        "modification_type": "枚举",
        "current_mapping": "",
        "instruction": "请提供修改后的 枚举 映射",
        "format": "JSON数组格式，每项包含原始值和目标值",
    }


def test_confirmation_tools保持名称确认元数据与可调用入口() -> None:
    expected = (
        (confirm_mapping_table, "confirm_mapping_table", True, ["mapping_table"]),
        (confirm_threat_mapping, "confirm_threat_mapping", True, ["mapping_table"]),
        (confirm_output, "confirm_output", True, ["output_summary"]),
        (request_modification, "request_modification", None, ["current_mapping"]),
    )

    for tool, name, requires_confirmation, required in expected:
        assert tool.name == name
        assert tool.requires_confirmation is requires_confirmation
        assert tool.parameters["required"] == required
        assert callable(tool.entrypoint)
