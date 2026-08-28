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
    available_fields: tuple[str, ...] = ()
    enum_mapping_target_fields: tuple[str, ...] = ()
    enum_mapping_row_count: int = Field(default=0, ge=0)
    existing_enum_value_count: int = Field(default=0, ge=0)
    existing_threat_mapping_count: int = Field(default=0, ge=0)
    mapped_sub_rule_count: int = Field(default=0, ge=0)
    mapped_sub_rule_names: tuple[str, ...] = ()
    decoded_config_rule_names: tuple[str, ...] = ()
    event_annotations: tuple[EventAnnotationFact, ...] = ()
    referenceable_artifacts: tuple[ReferenceableArtifactFact, ...] = ()
