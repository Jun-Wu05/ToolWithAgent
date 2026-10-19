"""V2 typed 运行态、旧保护 Blob 与共享事务副本的边界契约。"""
import json
from dataclasses import asdict

import pytest

from application.request_runtime import clear_session_data
from application.session_state import SessionState
from application.threat_chain import stage_threat_chain_session
from contracts.planner_models import EnumValuesArtifact, ThreatMappingArtifact, ThreatMappingRow
from contracts.rule_source import RuleSourceFields
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
from contracts.session_facts import ExecutionSummary, StepSummary
from toolwithagent_v2.runtime.postprocessing import BusinessSession, freeze_session, restore_session


def test_legacy_blob_restores_typed_values_and_ignores_private_runtime_fields():
    """旧 JSON 字段形状不变，模型/集合恢复为原类型，额外密钥字段不可注入。"""
    enum = EnumArtifactSlot(artifact=EnumValuesArtifact(item_count=1, values=("PRIVATE",), field="alarm"), source_field="alarm")
    threat = ThreatArtifactSlot(artifact=ThreatMappingArtifact(item_count=1,
        mappings=(ThreatMappingRow(mappingType="EQUAL", orgValue="PRIVATE", mappingValue="SQL注入"),), source_field="alarm"), source_field="alarm")
    source = RuleSourceFields.create(product="p", log_vendor="v")
    summary = ExecutionSummary(plan_id="safe", steps=(StepSummary(step_id="enum", type="enum_extract", status="success", artifact_kinds=("enum_values",), artifact_count=1),))
    legacy = {"decoded_data": {"meta": "中文"}, "mapped_sub_rules": [{"normalize": [{"index": "alarm"}]}],
        "raw_log_lines": ["alarm=PRIVATE"], "latest_enum_artifact": enum.model_dump(mode="json"),
        "latest_threat_artifact": threat.model_dump(mode="json"), "rule_source_fields": asdict(source),
        "current_execution": summary.model_dump(mode="json"), "previous_execution": summary.model_dump(mode="json"),
        "enum_mapping_sheets": {"结果": [{"orgValue": "PRIVATE", "mappingValue": "中文"}]},
        "enum_fill_contributions": {"session.decoded_config": {"结果": [{"mapping": {"orgValue": "PRIVATE"}}]}},
        "stale_enum_config_refs": ["session.decoded_config"], "enum_pending_refills": {"session.decoded_config": ["结果"]},
        "applied_attachment_ids": ["attachment-1"], "team": "TEAM-SECRET", "api_key": "API-SECRET", "submitter_id": "FORGED-OWNER"}
    session = restore_session(json.loads(json.dumps(legacy)))
    assert isinstance(session, BusinessSession) and isinstance(session, SessionState)
    assert session.latest_enum_artifact == enum and session.latest_threat_artifact == threat
    assert session.rule_source_fields == source and session.current_execution == session.previous_execution == summary
    assert session.stale_enum_config_refs == {"session.decoded_config"}
    assert session.enum_pending_refills == {"session.decoded_config": {"结果"}}
    assert session.enum_fill_contributions == legacy["enum_fill_contributions"]
    assert session.applied_attachment_ids == ["attachment-1"]
    assert session.team is None and session.api_key is None and session.submitter_id == "session-user"
    session.team = object()
    session.api_key = "NEW-API-SECRET"
    frozen = freeze_session(session)
    assert all(frozen[key] == value for key, value in legacy.items() if key not in {"team", "api_key", "submitter_id"})
    assert all(key not in frozen for key in ("team", "api_key", "submitter_id"))
    assert "SECRET" not in json.dumps(frozen)
    assert freeze_session(restore_session(frozen)) == frozen
    with pytest.raises(TypeError, match="typed_session_required"):
        freeze_session(legacy)


def test_shared_transaction_clone_preserves_typed_subclass_and_clear_resets_v2_ids():
    """共享事务保持 V2 子类身份和元数据，主数据清空覆盖附件去重状态。"""
    session = BusinessSession(mapped_sub_rules=[{"normalize": [{"index": "alarm"}]}],
        applied_attachment_ids=["attachment-1"], submitter_id="owner-1")
    cloned = stage_threat_chain_session(session)
    assert type(cloned) is BusinessSession
    assert cloned.applied_attachment_ids == ["attachment-1"] and cloned.submitter_id == "owner-1"
    cloned.mapped_sub_rules[0]["normalize"].append({"index": "new"})
    assert session.mapped_sub_rules == [{"normalize": [{"index": "alarm"}]}]
    clear_session_data(session)
    assert session.applied_attachment_ids == [] and session.mapped_sub_rules is None
    assert session.submitter_id == "owner-1" and cloned.applied_attachment_ids == ["attachment-1"]
