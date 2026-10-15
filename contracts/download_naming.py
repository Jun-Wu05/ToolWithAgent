"""下载文件名契约：Chainlit 与 V2 共用的唯一事实源。

CONTEXT.md「V2 导出文件名兼容」与 ADR-0013 把下载文件名定为跨入口兼容
接口：前缀、扩展名与时间戳格式不得因入口不同而漂移。本模块自
web/plan_renderer.py 迁入（#311），web 与 v2 都必须消费此处实现，
禁止在渲染层或入口层复制映射表。

下载类型词汇表也以本模块为单一事实源（#337）：``ConfigDownloadKind``
自 planner_models 迁入（planner_models 经导入保持既有导入路径不变），
``FieldMappingDownloadKind`` 具名化后由 ``FieldMappingArtifact``
消费，``DownloadKind`` 联合渲染层三类产物字符串后覆盖映射表全集。
依赖方向 planner_models → download_naming 单向、无环。
"""

from __future__ import annotations

from typing import Literal, Union

ConfigDownloadKind = Literal[
    "enummapping_config",
    "threatmapping_config",
    "cancelmapping_config",
    "current_config",
    "mappedconfig_subrules",
    "mappedconfig_mainrules",
    "unmappedconfig_subrules",
    "field_adjusted_config",
]
"""配置导出产物的下载类型（ConfigExportArtifact 与执行结果共用的 8 值词汇表）。"""

FieldMappingDownloadKind = Literal["mapped_config", "mapped_sub_rules"]
"""字段映射产物的下载类型（FieldMappingArtifact.download_kind 的 2 值子词汇表）。"""

RendererArtifactKind = Literal["threat_mapping", "enum_values", "log_classification"]
"""渲染层以 artifact_type 字符串直接调用的三类产物（plan_renderer 已收紧消费）。"""

DownloadKind = Union[ConfigDownloadKind, FieldMappingDownloadKind, RendererArtifactKind]
"""全部下载产物类型的 13 值全集——文件名映射表键集的契约来源（#337）。"""

DOWNLOAD_NAME_TEMPLATES: dict[str, str] = {
    "log_classification": "logclassification_{timestamp}.json",
    "enum_values": "enumvalues_{timestamp}.json",
    "threat_mapping": "threatmapping_{timestamp}.xlsx",
    "mapped_config": "fieldmapped_config_{timestamp}.txt",
    "mapped_sub_rules": "fieldmapped_subrules_{timestamp}.txt",
    "enummapping_config": "enummapping_config_{timestamp}.txt",
    "threatmapping_config": "threatmapping_config_{timestamp}.txt",
    "cancelmapping_config": "cancelmapping_config_{timestamp}.txt",
    "current_config": "current_config_{timestamp}.txt",
    "mappedconfig_subrules": "mappedconfig_subrules_{timestamp}.txt",
    "mappedconfig_mainrules": "mappedconfig_mainrules_{timestamp}.txt",
    "unmappedconfig_subrules": "unmappedconfig_subrules_{timestamp}.txt",
    "field_adjusted_config": "fieldadjusted_config_{timestamp}.txt",
}
"""kind → 文件名模板（{timestamp} 占位）；键集与 DownloadKind 全集由测试双向钉死。"""


def download_filename(kind: DownloadKind, timestamp: str) -> str:
    """按产物语义生成用户可见下载名；未知类型抛 ValueError。"""
    template = DOWNLOAD_NAME_TEMPLATES.get(kind)
    if template is not None:
        return template.format(timestamp=timestamp)
    raise ValueError(f"不支持的下载产物类型: {kind}")
