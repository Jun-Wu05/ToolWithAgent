"""统一 Planner 与执行器之间的类型化公共契约。"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictContract(BaseModel):
    """为跨模块契约提供禁止额外字段的共同约束。"""

    model_config = ConfigDict(extra="forbid")


ConfigRef = Literal["session.decoded_config", "session.mapped_sub_rules"]


class ConversationTurn(StrictContract):
    """描述一条可提供给 Planner 的受限对话历史。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)

class LogParseStep(StrictContract):
    """描述日志类型提取步骤，不允许执行器再从原文猜测参数。"""

    step_id: str = Field(min_length=1)
    type: Literal["log_parse"]
    depends_on: tuple[str, ...] = ()


class FieldMappingStep(StrictContract):
    """描述字段映射步骤及其明确的数据来源。"""

    step_id: str = Field(min_length=1)
    type: Literal["field_mapping"]
    source_ref: Literal["session.fields"]
    depends_on: tuple[str, ...] = ()


class EnumExtractStep(StrictContract):
    """描述从日志中提取指定字段枚举值的步骤。"""

    step_id: str = Field(min_length=1)
    type: Literal["enum_extract"]
    target_field: str = Field(min_length=1)
    source_ref: Literal["session.logs"] = "session.logs"
    depends_on: tuple[str, ...] = ()


class ThreatMappingStep(StrictContract):
    """描述威胁映射步骤，输入必须为显式值或本次计划的步骤引用。"""

    step_id: str = Field(min_length=1)
    type: Literal["threat_mapping"]
    source_ref: str = Field(min_length=1)
    values: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_direct_values(self) -> "ThreatMappingStep":
        """保证直接输入来源携带值，避免读取旧 session 结果兜底。"""
        if self.source_ref == "user.values" and not self.values:
            raise ValueError("直接威胁映射必须提供 values")
        if self.source_ref != "user.values":
            if not self.source_ref.startswith("step:"):
                raise ValueError("威胁映射来源必须是 user.values 或本次步骤引用")
            dependency_id = self.source_ref.removeprefix("step:")
            if dependency_id not in self.depends_on:
                raise ValueError("威胁映射的 source_ref 必须出现在 depends_on 中")
            if self.values:
                raise ValueError("步骤依赖来源不能同时携带直接 values")
        return self


class FillStep(StrictContract):
    """描述显式目标字段和显式来源的填充步骤。"""

    step_id: str = Field(min_length=1)
    type: Literal["fill"]
    fill_kind: Literal["enum", "threat"]
    target_fields: tuple[str, ...] = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_fill_source(self) -> "FillStep":
        """保证枚举填充使用表内结构，威胁填充只消费本次声明依赖。"""
        if self.fill_kind == "enum":
            if self.source_ref != "session.enum_mapping_table" or self.depends_on:
                raise ValueError("枚举填充必须使用 session.enum_mapping_table 且不声明步骤依赖")
            return self
        if not self.source_ref.startswith("step:"):
            raise ValueError("威胁填充必须引用本次威胁映射步骤")
        dependency_id = self.source_ref.removeprefix("step:")
        if dependency_id not in self.depends_on:
            raise ValueError("威胁填充的 source_ref 必须出现在 depends_on 中")
        return self


class RemoveMappingStep(StrictContract):
    """描述取消映射步骤及其目标字段。"""

    step_id: str = Field(min_length=1)
    type: Literal["remove_mapping"]
    target_fields: tuple[str, ...] = Field(min_length=1)
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()


class ExportStep(StrictContract):
    """描述导出步骤，来源必须指向 session 或本次计划产物。"""

    step_id: str = Field(min_length=1)
    type: Literal["export"]
    source_ref: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_export_source(self) -> "ExportStep":
        """保证导出来源为当前子规则或本次声明的配置产物。"""
        session_sources = {
            "session.decoded_config",
            "session.mapped_sub_rules",
            "session.log_classification.entry_rules",
            "session.log_classification.sub_rules",
        }
        if self.source_ref in session_sources:
            if self.depends_on:
                raise ValueError("session 导出不应声明步骤依赖")
            return self
        if not self.source_ref.startswith("step:"):
            raise ValueError("导出来源必须是受支持的 session 产物或本次步骤引用")
        dependency_id = self.source_ref.removeprefix("step:")
        if dependency_id not in self.depends_on:
            raise ValueError("导出的 source_ref 必须出现在 depends_on 中")
        return self


StepSpec = Annotated[
    Union[
        LogParseStep,
        FieldMappingStep,
        EnumExtractStep,
        ThreatMappingStep,
        FillStep,
        RemoveMappingStep,
        ExportStep,
    ],
    Field(discriminator="type"),
]


class PlanDecision(StrictContract):
    """表达 Planner 唯一允许返回的执行、澄清或帮助决策。"""

    decision: Literal["execute", "clarification", "guidance"]
    plan_id: str = Field(default="pending", min_length=1)
    steps: tuple[StepSpec, ...] = ()
    reason_code: str | None = None
    question: str | None = None
    choices: tuple[str, ...] = ()
    guidance_code: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "PlanDecision":
        """强制三类决策互斥，并校验依赖仅引用已声明的前序步骤。"""
        if self.decision == "execute":
            if not self.steps:
                raise ValueError("执行决策至少需要一个步骤")
            if self.question or self.guidance_code:
                raise ValueError("执行决策不能同时携带澄清或帮助字段")
        elif self.decision == "clarification":
            if self.steps or not self.question or not self.reason_code:
                raise ValueError("澄清决策必须包含原因和问题，且不能包含步骤")
        elif self.steps or not self.guidance_code:
            raise ValueError("帮助决策必须包含 guidance_code，且不能包含步骤")

        seen_step_ids: set[str] = set()
        for step in self.steps:
            if step.step_id in seen_step_ids:
                raise ValueError(f"步骤标识重复: {step.step_id}")
            missing_dependencies = set(step.depends_on) - seen_step_ids
            if missing_dependencies:
                raise ValueError(
                    f"步骤 {step.step_id} 引用了未声明的前序依赖: "
                    f"{sorted(missing_dependencies)}"
                )
            seen_step_ids.add(step.step_id)
        return self


class StepStatus(str, Enum):
    """限定步骤执行状态，禁止用任意字符串表达执行结果。"""

    SUCCESS = "success"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"


class ArtifactContract(StrictContract):
    """定义所有步骤产物共享的数量元数据，禁止使用无约束 payload。"""

    item_count: int = Field(ge=0)


class EnumValuesArtifact(ArtifactContract):
    """保存本次枚举提取得到的值，供显式依赖步骤消费。"""

    artifact_type: Literal["enum_values"] = "enum_values"
    values: tuple[str, ...]
    field: str = ""
    regex: str = ""
    original_log: tuple[str, ...] = ()


class ThreatMappingRow(StrictContract):
    """描述一条威胁映射，字段别名与现有领域工具协议保持一致。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mapping_type: str = Field(alias="mappingType", min_length=1)
    original_value: str = Field(alias="orgValue")
    mapped_value: str = Field(alias="mappingValue")


class ThreatMappingArtifact(ArtifactContract):
    """保存本次威胁映射结果，不允许后续步骤读取旧 session 结果。"""

    artifact_type: Literal["threat_mapping"] = "threat_mapping"
    mappings: tuple[ThreatMappingRow, ...]


class FieldMappingRow(StrictContract):
    """描述一条字段映射，中文别名对应既有专业 Agent 输出。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    original_field: str = Field(alias="原始字段名", min_length=1)
    standard_field: str = Field(alias="系统属性名称", min_length=1)
    match_status: str = Field(alias="匹配状态", min_length=1)


class FieldMappingArtifact(ArtifactContract):
    """保存已校验的字段映射行，避免跨模块传递任意字典列表。"""

    artifact_type: Literal["field_mapping"] = "field_mapping"
    mappings: tuple[FieldMappingRow, ...]
    # 回填后的配置（Base64），存在时渲染器附下载，供用户取回填充后的配置；无回填目标时为 None。
    filled_config: str | None = None


class LogClassificationArtifact(ArtifactContract):
    """保存日志分类结构；值限定为可序列化对象而非任意运行时对象。"""

    artifact_type: Literal["log_classification"] = "log_classification"
    classification: dict[str, object]


class ConfigExportArtifact(ArtifactContract):
    """保存可下载的配置文本，是 Renderer 唯一允许输出的文件产物。"""

    artifact_type: Literal["config_export"] = "config_export"
    content: str


StepArtifact = Annotated[
    Union[
        EnumValuesArtifact,
        ThreatMappingArtifact,
        FieldMappingArtifact,
        LogClassificationArtifact,
        ConfigExportArtifact,
    ],
    Field(discriminator="artifact_type"),
]

class StepResult(StrictContract):
    """记录单个步骤结果、稳定错误码及可供依赖消费的产物。"""

    step_id: str = Field(min_length=1)
    operation_type: str = Field(min_length=1)
    status: StepStatus
    artifact: StepArtifact | None = None
    changed_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    message: str | None = None


class ExecutionReport(StrictContract):
    """保存本次计划的步骤账本，供统一渲染器生成一次汇总。"""

    plan_id: str = Field(min_length=1)
    results: tuple[StepResult, ...]

    @property
    def status(self) -> StepStatus:
        """根据步骤账本计算本次计划的最终状态。"""
        if any(item.status == StepStatus.FAILED for item in self.results):
            return StepStatus.FAILED
        if any(item.status == StepStatus.NEEDS_INPUT for item in self.results):
            return StepStatus.NEEDS_INPUT
        return StepStatus.SUCCESS
