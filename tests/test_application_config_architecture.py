"""Issue #139：配置写回、取消映射与导出的 Application 契约。"""

from __future__ import annotations

import ast
import asyncio
import base64
import copy
import json
from pathlib import Path

import pytest


def _import_roots(path: Path) -> set[str]:
    """读取静态导入根，用于阻止 Application 反向依赖界面层。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test取消映射由application唯一实现并由生产组合直接注册() -> None:
    """Web 配置操作只重导出同一对象，不保留第二份业务实现。"""
    root = Path(__file__).parents[1]
    module_path = root / "application/adapters/remove_mapping.py"
    assert module_path.exists()
    assert _import_roots(module_path).isdisjoint({"web", "chainlit"})

    from application.adapters.remove_mapping import RemoveMappingAdapter
    from application.adapters import create_default_adapters

    adapters = create_default_adapters(None)
    assert isinstance(adapters["remove_mapping"], RemoveMappingAdapter)
    assert not any((root / "web/adapters").glob("*.py"))


def test取消映射通过标准字段名原子写回原配置来源() -> None:
    """全部解析成功后只提交一次，并保留标准字段名到原始 index 的提示。"""
    from application.adapters.remove_mapping import RemoveMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import RemoveMappingStep, StepStatus

    class RecordingSession(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.writes: list[str] = []

        def __setitem__(self, key, value):
            self.writes.append(key)
            super().__setitem__(key, value)

    original = [{
        "name": "规则一",
        "normalize": [{
            "index": "alarm_type",
            "field": "威胁类型",
            "mappings": [
                {"mappingType": "REGULAR", "orgValue": "攻击", "mappingValue": "网络攻击"},
                {"mappingType": "REGULAR", "orgValue": "扫描", "mappingValue": "扫描行为"},
            ],
        }],
    }]
    session = RecordingSession(mapped_sub_rules=copy.deepcopy(original))
    step = RemoveMappingStep(
        step_id="remove",
        type="remove_mapping",
        target_fields=("威胁类型",),
        config_ref="session.mapped_sub_rules",
    )

    result = asyncio.run(RemoveMappingAdapter().execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {},
    ))

    assert result.status == StepStatus.SUCCESS
    assert result.changed_count == 2
    assert result.message == "目标字段映射已取消；字段解析：威胁类型→alarm_type"
    assert session.writes == ["mapped_sub_rules"]
    assert session["mapped_sub_rules"][0]["normalize"][0]["mappings"] == []
    assert original[0]["normalize"][0]["mappings"] != []


@pytest.mark.parametrize(
    ("config", "target", "stale", "status_name", "error_code"),
    (
        (
            [{"normalize": [{"index": "alarm", "field": "威胁类型", "mappings": [{}]}]}],
            "alarm", True, "NEEDS_INPUT", "enum_refill_required",
        ),
        (
            [{"normalize": [{"index": "alarm", "field": "威胁类型", "mappings": [{}]}]}],
            "missing", False, "FAILED", "field_not_found",
        ),
        (
            [{"normalize": [
                {"index": "alarm_a", "field": "威胁类型", "mappings": [{}]},
                {"index": "alarm_b", "field": "威胁类型", "mappings": [{}]},
            ]}],
            "威胁类型", False, "FAILED", "field_name_ambiguous",
        ),
        (
            [{"normalize": [{"index": "alarm", "field": "威胁类型", "mappings": []}]}],
            "alarm", False, "NEEDS_INPUT", "mapping_not_found",
        ),
    ),
)
def test取消映射失败关闭且不留下部分状态(
    config, target, stale, status_name, error_code
) -> None:
    """过期、歧义、缺字段和无映射均在唯一写回前停止。"""
    from application.adapters.remove_mapping import RemoveMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import RemoveMappingStep

    class RecordingSession(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.writes: list[str] = []

        def __setitem__(self, key, value):
            self.writes.append(key)
            super().__setitem__(key, value)

    original = copy.deepcopy(config)
    session = RecordingSession(
        decoded_data=config,
        stale_enum_config_refs={"session.decoded_config"} if stale else set(),
    )
    step = RemoveMappingStep(
        step_id="remove",
        type="remove_mapping",
        target_fields=(target,),
        config_ref="session.decoded_config",
    )

    result = asyncio.run(RemoveMappingAdapter().execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {},
    ))

    assert result.status.name == status_name
    assert result.error_code == error_code
    assert session.writes == []
    assert session["decoded_data"] == original


@pytest.mark.parametrize(
    "config",
    (
        {"name": "规则一", "normalize": [{
            "index": "alarm", "field": "威胁类型",
            "mappings": [{"mappingType": "REGULAR", "orgValue": "攻击", "mappingValue": "网络攻击"}],
        }]},
        [{"name": "规则一", "normalize": [{
            "index": "alarm", "field": "威胁类型",
            "mappings": [{"mappingType": "REGULAR", "orgValue": "攻击", "mappingValue": "网络攻击"}],
        }]}],
    ),
)
def test取消映射产物保持根类型键顺序默认空格中文与base64文本(config) -> None:
    """取消映射沿用该业务的 JSON→UTF-8→Base64 ASCII 精确字节契约。"""
    from application.adapters.remove_mapping import RemoveMappingAdapter
    from application.execution import ExecutionContext
    from application.session_projection import build_session_facts
    from contracts.planner_models import RemoveMappingStep, StepStatus

    session = {"decoded_data": copy.deepcopy(config)}
    step = RemoveMappingStep(
        step_id="remove",
        type="remove_mapping",
        target_fields=("alarm",),
        config_ref="session.decoded_config",
    )
    result = asyncio.run(RemoveMappingAdapter().execute(
        step,
        ExecutionContext(session=session, session_facts=build_session_facts(session)),
        {},
    ))

    assert result.status == StepStatus.SUCCESS
    decoded = base64.b64decode(result.artifact.content).decode("utf-8")
    assert decoded == json.dumps(session["decoded_data"], ensure_ascii=False)
    assert decoded.startswith('{"name": "规则一"' if isinstance(config, dict) else '[{"name": "规则一"')
    assert '"field": "威胁类型", "mappings": []' in decoded
    assert result.artifact.download_kind == "cancelmapping_config"
    assert result.artifact.item_count == 0
