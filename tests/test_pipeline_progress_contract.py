"""共享进度契约只接受稳定的 pipeline 阶段与错误码。"""

import pytest
from pydantic import ValidationError

from contracts.progress import PipelineErrorCode, PipelineStage, ProgressEvent, ProgressPhase, ProgressStatus


def test_pipeline_progress_accepts_safe_stage_and_error_code():
    event = ProgressEvent(
        plan_id="plan", step_id="parse", phase=ProgressPhase.EXECUTION,
        status=ProgressStatus.FAILED, message_code="log_parse_failed",
        pipeline_stage=PipelineStage.KV_FEATURE_IDENTIFIER,
        error_code=PipelineErrorCode.KV_FEATURE_IDENTIFIER_FAILED,
        elapsed_seconds=2.5,
    )
    assert event.model_dump(mode="json")["pipeline_stage"] == "kv_feature_identifier"


@pytest.mark.parametrize("field,value", [
    ("pipeline_stage", "password=secret"),
    ("error_code", "raw log text"),
    ("raw_log", "secret"),
])
def test_pipeline_progress_rejects_unlisted_or_extra_content(field, value):
    payload = dict(plan_id="plan", step_id="parse", phase="execution",
                   status="failed", message_code="log_parse_failed", **{field: value})
    with pytest.raises(ValidationError):
        ProgressEvent.model_validate(payload)
