"""下载文件名契约：Chainlit 与 V2 共用的唯一事实源。

CONTEXT.md「V2 导出文件名兼容」与 ADR-0013 把下载文件名定为跨入口兼容
接口：前缀、扩展名与时间戳格式不得因入口不同而漂移。本模块自
web/plan_renderer.py 迁入（#311），web 与 v2 都必须消费此处实现，
禁止在渲染层或入口层复制映射表。
"""

from __future__ import annotations


def download_filename(kind: str, timestamp: str) -> str:
    """按产物语义生成用户可见下载名；未知类型抛 ValueError。"""
    names = {
        "log_classification": f"logclassification_{timestamp}.json",
        "enum_values": f"enumvalues_{timestamp}.json",
        "threat_mapping": f"threatmapping_{timestamp}.xlsx",
        "mapped_config": f"fieldmapped_config_{timestamp}.txt",
        "mapped_sub_rules": f"fieldmapped_subrules_{timestamp}.txt",
        "enummapping_config": f"enummapping_config_{timestamp}.txt",
        "threatmapping_config": f"threatmapping_config_{timestamp}.txt",
        "cancelmapping_config": f"cancelmapping_config_{timestamp}.txt",
        "current_config": f"current_config_{timestamp}.txt",
        "mappedconfig_subrules": f"mappedconfig_subrules_{timestamp}.txt",
        "mappedconfig_mainrules": f"mappedconfig_mainrules_{timestamp}.txt",
        "unmappedconfig_subrules": f"unmappedconfig_subrules_{timestamp}.txt",
        "field_adjusted_config": f"fieldadjusted_config_{timestamp}.txt",
    }
    if kind in names:
        return names[kind]
    raise ValueError(f"不支持的下载产物类型: {kind}")
