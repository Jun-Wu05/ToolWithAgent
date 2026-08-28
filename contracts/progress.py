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


class ProgressEvent(BaseModel):
    """保存可安全发送到日志和界面的类型化进度。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    phase: ProgressPhase
    status: ProgressStatus
    message_code: str = Field(min_length=1)
    current_batch: int | None = Field(default=None, ge=1)
    total_batches: int | None = Field(default=None, ge=1)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)


class ProgressSink(Protocol):
    """接收进度事件；实现方不得反向承担领域执行职责。"""

    async def publish(self, event: ProgressEvent) -> None:
        """发布一个不含敏感原值的进度事件。"""
