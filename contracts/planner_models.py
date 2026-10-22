"""统一 Planner 与执行器之间的类型化公共契约。"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.download_naming import (
    ConfigDownloadKind,
    FieldMappingDownloadKind,
)


class StrictContract(BaseModel):
    """为跨模块契约提供禁止额外字段的共同约束。"""

    model_config = ConfigDict(extra="forbid")


ConfigRef = Literal["session.decoded_config", "session.mapped_sub_rules"]
THREAT_TYPE_FIELD = "威胁类型"
"""威胁类型链路独占产出的系统固定字段（#173）：填充目标固定、映射目标黑名单成员。

契约层单一来源：执行器/适配器（application）不得依赖 agent 层取此常量；
agent.shared.event_classify 反向 re-export 保持既有导入路径不变。
"""
SessionEnumArtifactRef = Literal["session.artifacts.enum_values"]
SessionThreatArtifactRef = Literal["session.artifacts.threat_mapping"]
SessionArtifactRef = Union[SessionEnumArtifactRef, SessionThreatArtifactRef]
# ConfigDownloadKind / FieldMappingDownloadKind 已迁至 contracts.download_naming（#337），
# 上方导入即再导出——既有 `from contracts.planner_models import ConfigDownloadKind`
# 导入路径保持不变。


class ConversationTurn(StrictContract):
    """描述一条可提供给 Planner 的受限对话历史。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)

class LogParseStep(StrictContract):
    """描述日志类型提取步骤，不允许执行器再从原文猜测参数。"""

    step_id: str = Field(min_length=1)
    type: Literal["log_parse"]
    # 显式分类特征字段：用户点名「作为日志类型」的日志体键；缺省时由 Step1 自动探测。
    feature_field: str | None = Field(default=None, min_length=1)
    depends_on: tuple[str, ...] = ()


class LogKnowledgeSubmitStep(StrictContract):
    """描述由结果区按钮创建的日志知识申请步骤；Planner 不得生成。"""

    step_id: str = Field(min_length=1)
    type: Literal["log_knowledge_submit"]
    submission_token: str = Field(min_length=1)
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
    """描述威胁映射步骤，输入必须为显式值、当前步骤或白名单会话产物。"""

    step_id: str = Field(min_length=1)
    type: Literal["threat_mapping"]
    source_ref: str = Field(min_length=1)
    values: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_direct_values(self) -> "ThreatMappingStep":
        """保证三类来源互斥，避免读取未声明的旧 session 结果兜底。"""
        if self.source_ref == "user.values" and not self.values:
            raise ValueError("直接威胁映射必须提供 values")
        if self.source_ref == "session.artifacts.enum_values":
            if self.values or self.depends_on:
                raise ValueError("会话枚举产物来源不能携带 values 或步骤依赖")
            return self
        if self.source_ref != "user.values":
            if not self.source_ref.startswith("step:"):
                raise ValueError("威胁映射来源必须是 user.values、本次步骤或会话枚举产物")
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
        """保证枚举填充使用表内结构，威胁填充只消费显式类型化来源。"""
        if self.fill_kind == "enum":
            if self.source_ref != "session.enum_mapping_table" or self.depends_on:
                raise ValueError("枚举填充必须使用 session.enum_mapping_table 且不声明步骤依赖")
            return self
        if self.source_ref == "session.artifacts.threat_mapping":
            if self.depends_on:
                raise ValueError("会话威胁产物来源不能声明步骤依赖")
            if len(self.target_fields) != 1:
                raise ValueError("跨轮威胁填充必须声明唯一目标字段")
            return self
        if not self.source_ref.startswith("step:"):
            raise ValueError("威胁填充必须引用本次威胁步骤或会话威胁产物")
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


class AddFieldsStep(StrictContract):
    """描述在解析规则上添加一个字段的步骤。

    值来源两种：固定值或 ``%{index}`` 引用；添加【事件名称】时值必须是
    合法事件分类名，且事件级别由绑定表联动（执行器保证，契约不承载）。
    ``target_rule_names`` 为空表示全部 entity；``skip_existing`` 为真时
    已有同名字段的子规则跳过而不是整体失败（#126）。
    """

    step_id: str = Field(min_length=1)
    type: Literal["add_fields"]
    field_name: str = Field(min_length=1)
    field_value: str = ""
    value_type: Literal["fixed", "reference"] = "fixed"
    skip_existing: bool = False
    target_rule_names: tuple[str, ...] = ()
    rule_group: Literal["all", "threat", "non_threat"] = "all"
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_value_type(self) -> "AddFieldsStep":
        """引用型值必须是 %{index} 占位格式；寻址参数互斥。"""
        if self.value_type == "reference" and not (
            self.field_value.startswith("%{") and self.field_value.endswith("}")
        ):
            raise ValueError("引用型字段值必须是 %{index} 占位格式")
        if self.target_rule_names and self.rule_group != "all":
            raise ValueError("target_rule_names 与 rule_group 互斥，不能同时指定")
        return self


class DeleteFieldsStep(StrictContract):
    """描述从解析规则删除一个或多个字段的步骤。"""

    step_id: str = Field(min_length=1)
    type: Literal["delete_fields"]
    fields: tuple[str, ...] = Field(min_length=1)
    target_rule_names: tuple[str, ...] = ()
    rule_group: Literal["all", "threat", "non_threat"] = "all"
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> "DeleteFieldsStep":
        """寻址参数互斥。"""
        if self.target_rule_names and self.rule_group != "all":
            raise ValueError("target_rule_names 与 rule_group 互斥，不能同时指定")
        return self


class MergeFieldsStep(StrictContract):
    """描述把多个源字段合并为一个目标字段的步骤。"""

    step_id: str = Field(min_length=1)
    type: Literal["merge_fields"]
    source_fields: tuple[str, ...] = Field(min_length=2)
    target_field: str = Field(min_length=1)
    sep: str = ""
    target_rule_names: tuple[str, ...] = ()
    rule_group: Literal["all", "threat", "non_threat"] = "all"
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> "MergeFieldsStep":
        """寻址参数互斥。"""
        if self.target_rule_names and self.rule_group != "all":
            raise ValueError("target_rule_names 与 rule_group 互斥，不能同时指定")
        return self


class DecodeFieldsStep(StrictContract):
    """描述对解析规则指定字段启用 base64 运行时解码的步骤。"""

    step_id: str = Field(min_length=1)
    type: Literal["decode_fields"]
    fields: tuple[str, ...] = Field(min_length=1)
    target_rule_names: tuple[str, ...] = ()
    rule_group: Literal["all", "threat", "non_threat"] = "all"
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> "DecodeFieldsStep":
        """寻址参数互斥。"""
        if self.target_rule_names and self.rule_group != "all":
            raise ValueError("target_rule_names 与 rule_group 互斥，不能同时指定")
        return self


class RegexExtractStep(StrictContract):
    """描述用正则从已有字段提取新字段的步骤。

    正则由执行器按样本生成并做全匹配校验，Planner 不生成正则；
    ``pattern`` 仅当用户直接提供正则表达式时携带。
    """

    step_id: str = Field(min_length=1)
    type: Literal["regex_extract"]
    source_field: str = Field(min_length=1)
    description: str = Field(min_length=1)
    new_field: str = ""
    pattern: str = ""
    target_rule_names: tuple[str, ...] = ()
    rule_group: Literal["all", "threat", "non_threat"] = "all"
    config_ref: ConfigRef
    depends_on: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> "RegexExtractStep":
        """寻址参数互斥。"""
        if self.target_rule_names and self.rule_group != "all":
            raise ValueError("target_rule_names 与 rule_group 互斥，不能同时指定")
        return self


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
        AddFieldsStep,
        DeleteFieldsStep,
        MergeFieldsStep,
        DecodeFieldsStep,
        RegexExtractStep,
        ExportStep,
    ],
    Field(discriminator="type"),
]

# 确定性动作可以比 Planner 多拥有受控步骤，但不能反向扩大 Planner schema。
ExecutableStep = Union[StepSpec, LogKnowledgeSubmitStep]


class DeterministicPlan(StrictContract):
    """按钮等可信入口构造的类型化计划，不经过 Planner 输出协议。"""

    decision: Literal["execute"] = "execute"
    plan_id: str = Field(min_length=1)
    steps: tuple[ExecutableStep, ...] = Field(min_length=1)


class PlanDecision(StrictContract):
    """表达 Planner 唯一允许返回的执行、授权控制、澄清或帮助决策。"""

    decision: Literal[
        "execute",
        "proposal",
        "confirm",
        "cancel",
        "clarification",
        "guidance",
    ]
    plan_id: str = Field(default="pending", min_length=1)
    steps: tuple[StepSpec, ...] = ()
    pending_plan_id: str | None = Field(default=None, min_length=1)
    reason_code: str | None = None
    question: str | None = None
    choices: tuple[str, ...] = ()
    guidance_code: str | None = None
    answer: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "PlanDecision":
        """强制三类决策互斥，并校验依赖仅引用已声明的前序步骤。"""
        if self.decision == "execute":
            if not self.steps:
                raise ValueError("执行决策至少需要一个步骤")
            if self.pending_plan_id or self.question or self.guidance_code or self.answer:
                raise ValueError("执行决策不能同时携带澄清、帮助或作答字段")
        elif self.decision == "proposal":
            if (
                not self.steps
                or not self.reason_code
                or not self.question
                or not self.choices
                or self.pending_plan_id
                or self.guidance_code
                or self.answer
            ):
                raise ValueError("提案必须包含步骤、原因、问题和选项，且不能引用待执行计划")
        elif self.decision in {"confirm", "cancel"}:
            if (
                not self.pending_plan_id
                or self.steps
                or self.reason_code
                or self.question
                or self.choices
                or self.guidance_code
                or self.answer
            ):
                raise ValueError("确认或取消只能引用待执行计划，不能携带计划或展示字段")
        elif self.decision == "clarification":
            if (
                self.steps
                or self.pending_plan_id
                or self.answer
                or not self.question
                or not self.reason_code
            ):
                raise ValueError("澄清决策必须包含原因和问题，且不能包含步骤或作答")
        elif self.steps or self.pending_plan_id or not (self.guidance_code or self.answer):
            raise ValueError("帮助决策必须包含 guidance_code 或 answer，且不能包含步骤")

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


class PendingPlan(StrictContract):
    """保存等待用户确认的一次性类型化计划及其事实版本。"""

    plan_id: str = Field(min_length=1)
    steps: tuple[StepSpec, ...] = Field(min_length=1)
    session_facts_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


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
    """保存威胁映射及其字段血缘；直接值来源允许没有来源字段。"""

    artifact_type: Literal["threat_mapping"] = "threat_mapping"
    mappings: tuple[ThreatMappingRow, ...]
    source_field: str | None = None


class FieldMappingRow(StrictContract):
    """描述一条字段映射，中文别名对应既有专业 Agent 输出。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    original_field: str = Field(alias="原始字段名", min_length=1)
    standard_field: str = Field(alias="系统属性名称", min_length=1)
    match_status: str = Field(alias="匹配状态", min_length=1)


class EventAnnotationRow(StrictContract):
    """一条子规则的事件标注及最终威胁链报告明细。"""

    rule_name: str = Field(min_length=1)
    event_name: str = ""
    event_level: str = ""
    threat_source_field: str = ""
    threat_types: tuple[str, ...] = ()
    status: Literal["judged", "uncertain"] = "judged"


class FieldMappingArtifact(ArtifactContract):
    """保存已校验的字段映射行，避免跨模块传递任意字典列表。"""

    artifact_type: Literal["field_mapping"] = "field_mapping"
    mappings: tuple[FieldMappingRow, ...]
    event_annotations: tuple[EventAnnotationRow, ...] = ()
    download_kind: FieldMappingDownloadKind | None = None
    download_content: str | None = None

    @model_validator(mode="after")
    def validate_download_contract(self) -> "FieldMappingArtifact":
        """下载类型与内容必须同时存在，避免渲染器根据载荷结构猜测语义。"""
        if (self.download_kind is None) != (self.download_content is None):
            raise ValueError("字段映射下载类型与内容必须同时提供")
        return self


class LogClassificationArtifact(ArtifactContract):
    """保存日志分类结构；值限定为可序列化对象而非任意运行时对象。"""

    artifact_type: Literal["log_classification"] = "log_classification"
    classification: dict[str, object]
    submission_eligible: bool = False
    submission_token: str | None = None


class LogKnowledgeSubmissionArtifact(ArtifactContract):
    """保存显式提交的稳定终态，不携带原始日志或样例。"""

    artifact_type: Literal["log_knowledge_submission"] = "log_knowledge_submission"
    submission_status: Literal[
        "created", "pending_duplicate", "already_approved", "stale", "error"
    ]
    application_id: int | None = Field(default=None, ge=1)


class ConfigExportArtifact(ArtifactContract):
    """保存可下载的配置文本，是 Renderer 唯一允许输出的文件产物。"""

    artifact_type: Literal["config_export"] = "config_export"
    content: str
    download_kind: ConfigDownloadKind = "current_config"


StepArtifact = Annotated[
    Union[
        EnumValuesArtifact,
        ThreatMappingArtifact,
        FieldMappingArtifact,
        LogClassificationArtifact,
        LogKnowledgeSubmissionArtifact,
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
    choices: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    recovered: bool = Field(default=False, exclude_if=lambda value: not value)
    idempotent_no_change: bool = Field(
        default=False, exclude_if=lambda value: not value
    )


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
