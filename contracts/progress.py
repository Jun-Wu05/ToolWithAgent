"""定义执行进度事件及与界面无关的发布接口。"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProgressPhase(str, Enum):
    """限定可展示的安全业务阶段，禁止传递模型隐藏推理。"""

    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    MODEL_CALL = "model_call"
    VALIDATION = "validation"
    WRITEBACK = "writeback"
    EXECUTION = "execution"
    COMPLETED = "completed"


class ProgressStatus(str, Enum):
    """描述一个进度阶段的生命周期状态。"""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class PlannedStep(BaseModel):
    """仅供诊断投影的计划步骤；V2 入口会哈希所有原始标识。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()


class PipelineStage(str, Enum):
    """可公开的日志解析阶段；不包含输入值或模型内容。"""

    FORMAT_IDENTIFICATION = "format_identification"
    FEATURE_LOCATION = "feature_location"
    KV_FEATURE_IDENTIFIER = "kv_feature_identifier"
    CLASSIFICATION = "classification"
    SAMPLE_FILL = "sample_fill"


class PipelineErrorCode(str, Enum):
    """阶段失败的稳定分类，具体原文留在授权诊断日志中。"""

    FORMAT_INVALID = "format_invalid"
    FEATURE_LOCATION_FAILED = "feature_location_failed"
    KV_FEATURE_IDENTIFIER_FAILED = "kv_feature_identifier_failed"
    CLASSIFICATION_FAILED = "classification_failed"
    SAMPLE_FILL_FAILED = "sample_fill_failed"


class ProgressEvent(BaseModel):
    """保存可安全发送到日志和界面的类型化进度。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    phase: ProgressPhase
    status: ProgressStatus
    message_code: str = Field(min_length=1)
    # 执行器声明的依赖只供入口转换为安全 scope，不传参数或业务值。
    dependency_step_ids: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
    planned_steps: tuple[PlannedStep, ...] = ()
    pipeline_stage: PipelineStage | None = None
    error_code: PipelineErrorCode | None = None
    current_batch: int | None = Field(default=None, ge=1)
    total_batches: int | None = Field(default=None, ge=1)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)


class ProgressSink(Protocol):
    """接收进度事件；实现方不得反向承担领域执行职责。"""

    async def publish(self, event: ProgressEvent) -> None:
        """发布一个不含敏感原值的进度事件。"""
