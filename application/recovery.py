"""有界自恢复的瞬时错误分类与计划级预算。"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.planner_models import StepResult, StepStatus


RETRYABLE_STEP_TYPES = frozenset({"enum_extract", "field_mapping", "log_parse"})

_TRANSIENT_EXCEPTION_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "RateLimitError",
        "ReadTimeout",
        "WriteTimeout",
    }
)

# ponytail: 错误码保持静态白名单；适配器新增模型结构错误时显式加入。
_TRANSIENT_RESULT_CODES = frozenset(
    {
        "enum_regex_invalid",
        "event_classify_failed",
        "field_mapping_timeout",
        "log_format_invalid",
        "log_parse_failed",
    }
)


@dataclass(frozen=True)
class RecoveryBudget:
    """限制单份计划的恢复次数；零预算保持既有失败即停行为。"""

    max_per_plan: int = 2
    max_per_step: int = 1
    max_rederive: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.max_per_plan <= 2:
            raise ValueError("max_per_plan 必须在 0..2 内")
        if not 0 <= self.max_per_step <= 1:
            raise ValueError("max_per_step 必须在 0..1 内")
        if not 0 <= self.max_rederive <= 1:
            raise ValueError("max_rederive 必须在 0..1 内")


def is_transient(error_or_result: Exception | StepResult) -> bool:
    """只识别超时、连接、429/5xx 与模型结构解析失败。"""
    if isinstance(error_or_result, (TimeoutError, ConnectionError)):
        return True
    if isinstance(error_or_result, Exception):
        if type(error_or_result).__name__ in _TRANSIENT_EXCEPTION_NAMES:
            return True
        status_code = getattr(error_or_result, "status_code", None)
        if status_code is None:
            status_code = getattr(
                getattr(error_or_result, "response", None), "status_code", None
            )
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            return False
        return status_code == 429 or status_code >= 500
    return error_or_result.status == StepStatus.FAILED and (
        error_or_result.error_code in _TRANSIENT_RESULT_CODES
    )
