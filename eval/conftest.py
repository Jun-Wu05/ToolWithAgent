"""标准字段映射评估 — 公共 fixture"""

import json
import os
import pytest
from typing import Any

# 项目根目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")


@pytest.fixture(scope="session")
def golden_cases() -> list[dict[str, Any]]:
    """加载 golden dataset（field_mapping_cases.json）"""
    path = os.path.join(_GOLDEN_DIR, "field_mapping_cases.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def positive_cases(golden_cases: list[dict]) -> list[dict]:
    """仅正例（期望匹配到标准字段的 case）"""
    return [c for c in golden_cases if c["expected_standard_field"] != "UNMATCHED"]


@pytest.fixture(scope="session")
def negative_cases(golden_cases: list[dict]) -> list[dict]:
    """仅负例（期望标为"未匹配"的 case）"""
    return [c for c in golden_cases if c["expected_standard_field"] == "UNMATCHED"]


@pytest.fixture(scope="session")
def standard_fields_table() -> list[dict[str, Any]]:
    """加载标准字段表（config/标准字段.txt → list[dict]）"""
    # 确保项目根目录在 sys.path 中
    import sys
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    from agent.tools.standard_mapper import _load_standard_fields_list
    table = _load_standard_fields_list()
    assert table, "标准字段表加载失败"
    return table


@pytest.fixture(scope="session")
def all_standard_names(standard_fields_table: list[dict]) -> set[str]:
    """所有标准字段系统属性名称集合"""
    return {entry["系统属性名称"] for entry in standard_fields_table}