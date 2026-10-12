"""下载文件名契约的完整性测试（自 contracts 层消费，#311 迁移）。

背景（2026-08-26 线上报错）：#124 新增 field_adjusted_config 下载类型时
漏更新文件名字典，字段调整成功后在渲染阶段抛「不支持的下载产物类型」。
本文件用契约遍历锁死：ConfigDownloadKind 的每一个合法值都必须能生成下载
文件名；同时以字面量表逐字钉死全部 13 个 kind 的输出（前缀、扩展名与
时间戳拼接），任何改名都会在此红——文件名是跨入口兼容接口。
"""

from typing import get_args

import pytest

from contracts.download_naming import download_filename
from contracts.planner_models import ConfigDownloadKind


def test所有下载类型都能生成文件名():
    """ConfigDownloadKind 的每个合法值在文件名契约中都有条目。"""
    for kind in get_args(ConfigDownloadKind):
        filename = download_filename(kind, "20260826_0000")
        assert isinstance(filename, str) and filename, kind
        assert "不支持" not in filename


def test全部下载类型的精确文件名():
    """13 个 kind 的前缀、扩展名与时间戳拼接逐字锁定（兼容接口）。"""
    expected = {
        "log_classification": "logclassification_20260826_0000.json",
        "enum_values": "enumvalues_20260826_0000.json",
        "threat_mapping": "threatmapping_20260826_0000.xlsx",
        "mapped_config": "fieldmapped_config_20260826_0000.txt",
        "mapped_sub_rules": "fieldmapped_subrules_20260826_0000.txt",
        "enummapping_config": "enummapping_config_20260826_0000.txt",
        "threatmapping_config": "threatmapping_config_20260826_0000.txt",
        "cancelmapping_config": "cancelmapping_config_20260826_0000.txt",
        "current_config": "current_config_20260826_0000.txt",
        "mappedconfig_subrules": "mappedconfig_subrules_20260826_0000.txt",
        "mappedconfig_mainrules": "mappedconfig_mainrules_20260826_0000.txt",
        "unmappedconfig_subrules": "unmappedconfig_subrules_20260826_0000.txt",
        "field_adjusted_config": "fieldadjusted_config_20260826_0000.txt",
    }
    assert len(expected) == 13
    for kind, filename in expected.items():
        assert download_filename(kind, "20260826_0000") == filename, kind


def test未知下载类型抛ValueError():
    """未知 kind 沿用原错误文案，异常行为不因迁移改变。"""
    with pytest.raises(ValueError, match="不支持的下载产物类型"):
        download_filename("nonexistent_kind", "20260826_0000")
