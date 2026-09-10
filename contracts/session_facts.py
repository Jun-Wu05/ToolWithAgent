"""定义供 Planner 使用的不可变会话事实契约。"""

from pydantic import BaseModel, ConfigDict, Field

from contracts.planner_models import ConfigRef
from contracts.session_artifacts import ReferenceableArtifactFact


class EventAnnotationFact(BaseModel):
    """一条子规则的事件标注事实。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_name: str = Field(min_length=1)
    event_name: str = ""
    event_level: str = ""


class SessionFacts(BaseModel):
    """仅暴露意图理解所需的状态，不泄露路径、密钥或原始内容。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    has_decoded_config: bool = False
    has_logs: bool = False
    has_log_classification: bool = False
    has_mapped_sub_rules: bool = False
    available_config_refs: tuple[ConfigRef, ...] = ()
    # Planner 点名词典：包含原始字段名和已映射的标准字段名。
    available_fields: tuple[str, ...] = ()
    # 字段映射输入：只包含仍可送入映射批次的原始字段名。
    mappable_fields: tuple[str, ...] = ()
    # 所有已判定威胁子规则共同拥有的真实原始字段，可供用户选择来源。
    threat_source_fields: tuple[str, ...] = ()
    # 上传配置中以 normalize[].field 是否非空判定的映射状态计数。
    decoded_mapped_field_count: int = Field(default=0, ge=0)
    decoded_unmapped_field_count: int = Field(default=0, ge=0)
    enum_mapping_target_fields: tuple[str, ...] = ()
    enum_mapping_row_count: int = Field(default=0, ge=0)
    existing_enum_value_count: int = Field(default=0, ge=0)
    existing_threat_mapping_count: int = Field(default=0, ge=0)
    mapped_sub_rule_count: int = Field(default=0, ge=0)
    mapped_sub_rule_names: tuple[str, ...] = ()
    decoded_config_rule_names: tuple[str, ...] = ()
    event_annotations: tuple[EventAnnotationFact, ...] = ()
    referenceable_artifacts: tuple[ReferenceableArtifactFact, ...] = ()
