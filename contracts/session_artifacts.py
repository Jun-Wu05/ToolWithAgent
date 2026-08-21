"""定义可引用会话产物及其暴露给 Planner 的安全目录。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from contracts.planner_models import (
    ConfigRef,
    EnumValuesArtifact,
    SessionArtifactRef,
    StrictContract,
    ThreatMappingArtifact,
)


class EnumArtifactSlot(StrictContract):
    """保存最近一次成功枚举产物，并锁定其来源字段。"""

    artifact: EnumValuesArtifact
    source_field: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_field(self) -> "EnumArtifactSlot":
        """防止产物字段与槽位血缘不一致。"""
        if self.artifact.field and self.artifact.field != self.source_field:
            raise ValueError("枚举产物字段与来源字段不一致")
        return self


class ThreatArtifactSlot(StrictContract):
    """保存最近一次成功威胁产物；直接值来源允许没有字段血缘。"""

    artifact: ThreatMappingArtifact
    source_field: str | None = None

    @model_validator(mode="after")
    def validate_source_field(self) -> "ThreatArtifactSlot":
        """防止槽位字段与威胁产物血缘不一致。"""
        if self.artifact.source_field != self.source_field:
            raise ValueError("威胁产物字段与来源字段不一致")
        return self


class ArtifactTargetBinding(StrictContract):
    """描述一个产物来源字段在指定配置中的唯一标准目标。"""

    config_ref: ConfigRef
    target_field: str = Field(min_length=1)


class ReferenceableArtifactFact(StrictContract):
    """提供给 Planner 的产物目录项，不包含任何原始业务值。"""

    source_ref: SessionArtifactRef
    artifact_type: Literal["enum_values", "threat_mapping"]
    source_field: str | None = None
    item_count: int = Field(ge=0)
    target_bindings: tuple[ArtifactTargetBinding, ...] = ()
