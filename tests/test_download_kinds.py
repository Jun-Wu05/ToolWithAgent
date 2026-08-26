"""渲染层下载文件名与产物契约的完整性测试。

背景（2026-08-26 线上报错）：#124 新增 field_adjusted_config 下载类型时
漏更新 _download_filename 字典，字段调整成功后在渲染阶段抛
「不支持的下载产物类型」。本文件用契约遍历锁死：ConfigDownloadKind
的每一个合法值都必须能生成下载文件名，FieldSkillAdapter 产物必须
可被渲染器消费。
"""

from typing import get_args

from web.plan_renderer import _download_filename
from contracts.planner_models import ConfigDownloadKind


def test所有下载类型都能生成文件名():
    """ConfigDownloadKind 的每个合法值在渲染器文件名字典中都有条目。"""
    for kind in get_args(ConfigDownloadKind):
        filename = _download_filename(kind, "20260826_0000")
        assert isinstance(filename, str) and filename, kind
        assert "不支持" not in filename


def test字段调整下载文件名格式():
    """field_adjusted_config 生成 txt 文件名并带时间戳。"""
    filename = _download_filename("field_adjusted_config", "20260826_2018")
    assert filename == "fieldadjusted_config_20260826_2018.txt"
