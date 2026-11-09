"""进度契约：V2 只保存白名单进度，批次计数与操作标识来自真实事件。"""
import asyncio

from contracts.progress import PipelineErrorCode, PipelineStage, ProgressEvent, ProgressPhase, ProgressStatus

from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.progress import RunProgressSink
from toolwithagent_v2.settings import Settings


def setup(tmp_path):
    store = Store(Settings(data_dir=tmp_path / "data"))
    conversation = store.create_conversation("dev-user", "进度契约")
    return store, conversation["id"]


def running_claim(store, conversation_id):
    store.create_message("dev-user", conversation_id, "请提取日志类型")
    claim = store.claim("worker-a")
    assert claim is not None
    return claim


def publish(store, claim, **overrides):
    params = dict(plan_id="plan-1", step_id="step-1", phase=ProgressPhase.RETRIEVAL,
                  status=ProgressStatus.RUNNING, message_code="field_candidates_retrieving",
                  current_batch=2, total_batches=5, elapsed_seconds=1.25)
    params.update(overrides)
    asyncio.run(RunProgressSink(store, "worker-a", claim).publish(ProgressEvent(**params)))
    return store.get_run("dev-user", claim["id"])["events"][-1]["summary"]


def test_batch_counts_and_operation_survive_sink(tmp_path):
    store, conversation_id = setup(tmp_path)
    claim = running_claim(store, conversation_id)
    summary = publish(store, claim)
    assert summary["operation"] == "field_mapping"
    assert summary["phase"] == "retrieval"
    assert summary["progress_status"] == "running"
    assert summary["current_batch"] == 2
    assert summary["total_batches"] == 5
    assert summary["elapsed_seconds"] == 1.25
    progress_events = [e for e in store.events("dev-user", conversation_id, 0) if e["event_type"] == "run_progress"]
    assert progress_events[-1]["payload"]["current_batch"] == 2


def test_absent_counts_stay_absent_and_step_prefix_maps_operation(tmp_path):
    store, conversation_id = setup(tmp_path)
    claim = running_claim(store, conversation_id)
    summary = publish(store, claim, message_code="fill_started", current_batch=None, total_batches=None, elapsed_seconds=0.0)
    assert summary["operation"] == "fill"
    assert "current_batch" not in summary
    assert "total_batches" not in summary
    assert "elapsed_seconds" not in summary


def test_unknown_message_code_keeps_operation_none(tmp_path):
    store, conversation_id = setup(tmp_path)
    claim = running_claim(store, conversation_id)
    summary = publish(store, claim, message_code="planner_understanding")
    assert summary["operation"] is None


def test_record_progress_stores_only_whitelist(tmp_path):
    store, conversation_id = setup(tmp_path)
    claim = running_claim(store, conversation_id)
    store.record_progress("worker-a", claim, "step-x",
                          {"phase": "retrieval", "progress_status": "running", "operation": "field_mapping",
                           "dependency_scope_ids": [], "current_batch": 1, "raw_detail": "机密"})
    summary = store.get_run("dev-user", claim["id"])["events"][-1]["summary"]
    assert summary["current_batch"] == 1
    assert "raw_detail" not in summary


def test_pipeline_stage_and_error_survive_without_body(tmp_path):
    store, conversation_id = setup(tmp_path)
    claim = running_claim(store, conversation_id)
    summary = publish(
        store, claim, message_code="log_parse_kv_feature_identifier_failed",
        pipeline_stage=PipelineStage.KV_FEATURE_IDENTIFIER,
        error_code=PipelineErrorCode.KV_FEATURE_IDENTIFIER_FAILED,
    )
    assert summary["operation"] == "log_parse"
    assert summary["pipeline_stage"] == "kv_feature_identifier"
    assert summary["error_code"] == "kv_feature_identifier_failed"
    store.record_progress("worker-a", claim, "step-x", {"pipeline_stage": "kv_feature_identifier", "raw_log": "secret body"})
    assert "raw_log" not in store.get_run("dev-user", claim["id"])["events"][-1]["summary"]


def test_failed_run_keeps_readable_reason_and_masks_secret(tmp_path):
    store, conversation_id = setup(tmp_path)
    claim = running_claim(store, conversation_id)
    store.finish("worker-a", claim, "log_parse_failed",
                 "KV 特征生成失败；Authorization: Bearer top-secret")
    run = store.get_run("dev-user", claim["id"])
    assert "KV 特征生成失败" in run["error_message"]
    assert "top-secret" not in run["error_message"]
    assert store.diagnostic_run(claim["id"])["conclusion"]["reason"] == run["error_message"]
