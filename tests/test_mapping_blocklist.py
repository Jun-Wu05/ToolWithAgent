"""映射目标黑名单测试（issue #125）。

系统固定字段（事件名称/事件级别/日志类型）不允许被用户字段映射占用：
- 常量单一来源（与 event_classify 一致）
- 白名单校验降级（standard_mapper）
- 检索候选剔除（field_retriever._apply_mapping_exclusions）
"""

from __future__ import annotations

import numpy as np

from agent.shared.event_classify import EVENT_LEVEL_FIELD, EVENT_NAME_FIELD
from agent.tools.rule_generator.field_mapping import (
    EXCLUDED_FIELD_INDICES,
    MAPPING_EXCLUDED_STANDARD_FIELDS,
)


def test黑名单与固定字段常量单一来源一致():
    """黑名单引用 event_classify 常量并覆盖日志类型；与 index 排除集相互独立。"""
    assert EVENT_NAME_FIELD in MAPPING_EXCLUDED_STANDARD_FIELDS
    assert EVENT_LEVEL_FIELD in MAPPING_EXCLUDED_STANDARD_FIELDS
    assert "日志类型" in MAPPING_EXCLUDED_STANDARD_FIELDS
    assert len(MAPPING_EXCLUDED_STANDARD_FIELDS) == 3
    # index 侧排除集（映射输入）与目标侧黑名单是两个概念，互不替代
    assert MAPPING_EXCLUDED_STANDARD_FIELDS != EXCLUDED_FIELD_INDICES


def test黑名单命中时映射被强制降级为未匹配():
    """映射目标命中黑名单 → 降级「未匹配」并注明系统固定字段原因。"""
    from agent.tools.standard_mapper import _validate_and_correct_mapping

    for target in ("事件名称", "事件级别", "日志类型"):
        mapping = {
            "原始字段名": "vendor_event_name",
            "系统属性名称": target,
            "匹配状态": "匹配成功",
        }
        corrected = _validate_and_correct_mapping(mapping)
        assert corrected["系统属性名称"] == "未匹配"
        assert corrected["匹配状态"] == "未匹配"
        assert "系统固定字段" in corrected["_校正原因"]
        assert target in corrected["_校正原因"]


def test非黑名单映射不被误降级():
    """普通映射目标不受黑名单影响（原对象引用返回，未被复制）。"""
    from agent.tools.standard_mapper import _validate_and_correct_mapping

    mapping = {
        "原始字段名": "src_ip",
        "系统属性名称": "源地址",
        "匹配状态": "匹配成功",
    }
    corrected = _validate_and_correct_mapping(mapping)
    assert corrected["系统属性名称"] == "源地址"
    assert corrected is mapping


def test未匹配终态跳过黑名单校验():
    """「未匹配」是合法终态，不触发降级分支。"""
    from agent.tools.standard_mapper import _validate_and_correct_mapping

    mapping = {"原始字段名": "x", "系统属性名称": "未匹配", "匹配状态": "未匹配"}
    assert _validate_and_correct_mapping(mapping) is mapping


def test检索候选剔除固定字段并保持嵌入对齐():
    """_apply_mapping_exclusions 同步删除记录行与嵌入行，顺序保持。"""
    from agent.core.field_retriever import _apply_mapping_exclusions

    records = [
        {"系统属性名称": "源地址", "字段名称": "src_address"},
        {"系统属性名称": "事件名称", "字段名称": "event_name"},
        {"系统属性名称": "目的端口", "字段名称": "dst_port"},
        {"系统属性名称": "事件级别", "字段名称": "event_level"},
        {"系统属性名称": "日志类型", "字段名称": "log_type"},
    ]
    embeddings = np.arange(10, dtype=float).reshape(5, 2)

    filtered_embeddings, filtered_records = _apply_mapping_exclusions(embeddings, records)

    assert [rec["系统属性名称"] for rec in filtered_records] == ["源地址", "目的端口"]
    # 嵌入行与保留记录按索引对齐（第 0、2 行保留）
    assert filtered_embeddings.shape == (2, 2)
    assert np.array_equal(filtered_embeddings, embeddings[[0, 2]])


def test无命中时原样返回不复制():
    """候选不含黑名单字段时零开销直通（同一对象）。"""
    from agent.core.field_retriever import _apply_mapping_exclusions

    records = [{"系统属性名称": "源地址"}, {"系统属性名称": "目的端口"}]
    embeddings = np.ones((2, 3))
    out_embeddings, out_records = _apply_mapping_exclusions(embeddings, records)
    assert out_records is records
    assert out_embeddings is embeddings


def test空输入安全直通():
    """records 为空或 embeddings 为 None 时安全返回。"""
    from agent.core.field_retriever import _apply_mapping_exclusions

    assert _apply_mapping_exclusions(None, []) == (None, [])
    assert _apply_mapping_exclusions(None, [{"系统属性名称": "事件名称"}]) == (
        None,
        [{"系统属性名称": "事件名称"}],
    )
