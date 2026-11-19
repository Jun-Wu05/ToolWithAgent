"""Small bridge from durable V2 runs to the existing Application executor."""
from __future__ import annotations

import csv
import copy
import json
import re
from pathlib import Path
from itertools import islice

from openpyxl import load_workbook

from application.file_input import simple_decode
from toolwithagent_v2.runtime.postprocessing import BusinessSession, freeze_session
from application.adapters.composition import create_default_adapters
from application.adapters.log_knowledge_submit import LogKnowledgeSubmitAdapter
from application.clarification import compose_clarification
from application.log_knowledge_submission import build_submission_snapshot
from application.progress import NullProgressSink
from application.request_runtime import run_deterministic_plan
from application.session_projection import build_session_facts
from contracts.planner_models import DeterministicPlan, FieldMappingStep, LogKnowledgeSubmitStep, LogParseStep, StepStatus



def artifact_sources(report, plan, published):
    """仅保留成功发布步骤实际读取的同轮产物依赖。"""
    results = {item.step_id: item for item in report.results if item.status == StepStatus.SUCCESS}
    sources = {kind: set() for kind in published}
    def published_result(item, kind):
        return kind in published and (kind not in {"enum_values", "threat_mapping"}
            or item.artifact.model_dump(mode="json") == published[kind])
    for step in plan.steps:
        consumer = results.get(step.step_id)
        kind = getattr(consumer.artifact, "artifact_type", None) if consumer else None
        if step.type == "fill":
            kind = "field_mapping"
        if not consumer or not published_result(consumer, kind):
            continue
        for ref in (getattr(step, "source_ref", None), getattr(step, "config_ref", None)):
            if not ref or not ref.startswith("step:"):
                continue
            producer = results.get(ref.removeprefix("step:"))
            source_kind = getattr(producer.artifact, "artifact_type", None) if producer else None
            if producer and published_result(producer, source_kind) and source_kind != kind:
                sources[kind].add(source_kind)
    # 运行时把自动链账本附加到外层报告；末步填充成功证明全部暂存产物已提交。
    from application.threat_chain_policy import ENUM_STEP_ID, MAPPING_STEP_ID, FILL_STEP_ID
    if all(step_id in results for step_id in (ENUM_STEP_ID, MAPPING_STEP_ID, FILL_STEP_ID)):
        if (published_result(results[ENUM_STEP_ID], "enum_values")
                and published_result(results[MAPPING_STEP_ID], "threat_mapping")):
            sources["threat_mapping"].add("enum_values")
            if "field_mapping" in sources:
                sources["field_mapping"].add("threat_mapping")
    return {kind: sorted(values) for kind, values in sources.items() if values}

def raw_log_lines(path: Path, media_type: str, *, limit: int | None = None) -> list[str]:
    """Read full execution input, or stop early for read-only presence summaries."""
    if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        with path.open("rb") as source:
            workbook = load_workbook(source, read_only=True, data_only=True)
            try:
                sheet = workbook.active
                # Some exports declare A1 even when the XML contains the full table.
                sheet.reset_dimensions()
                rows = sheet.iter_rows(values_only=True)
                header = next(rows, ())
                index = next((i for i, value in enumerate(header) if "原始日志" in str(value)), None)
                if index is None:
                    raise ValueError("raw_log_column_missing")
                values = (str(row[index]) for row in rows if index < len(row) and row[index] is not None)
                lines = list(islice((re.sub(r"[\r\n]+", " ", value) for value in values if value.strip()), limit))
            finally:
                workbook.close()
    elif media_type == "text/csv":
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            column = next((name for name in (reader.fieldnames or []) if "原始日志" in name), None)
            values = (str(row[column]) if column else json.dumps(row, ensure_ascii=False) for row in reader if row)
            lines = list(islice((value for value in values if value.strip()), limit))
    elif media_type == "application/x-ndjson":
        with path.open(encoding="utf-8-sig") as source:
            values = (value for line in source for value in line.splitlines() if value.strip())
            lines = list(islice(values, limit))
    else:
        text = path.read_text(encoding="utf-8-sig")
        if media_type == "application/json":
            payload = json.loads(text)
            if isinstance(payload, list):
                lines = [json.dumps(item, ensure_ascii=False) for item in payload]
            elif isinstance(payload, dict):
                lines = [json.dumps(payload, ensure_ascii=False)]
            else:
                decoded = simple_decode(text)
                original = decoded.get("original_log") if decoded.get("status") == "success" else None
                if isinstance(original, list):
                    lines = [json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item) for item in original]
                elif isinstance(original, (dict, str)):
                    lines = [json.dumps(original, ensure_ascii=False) if isinstance(original, dict) else original]
                else:
                    lines = []
        else:
            decoded = simple_decode(text)
            original = decoded.get("original_log") if decoded.get("status") == "success" else None
            if isinstance(original, str):
                lines = original.splitlines()
            elif isinstance(original, list):
                lines = [json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                         for value in original]
            elif isinstance(original, dict):
                lines = [json.dumps(original, ensure_ascii=False)]
            else:
                lines = []
    lines = [line for line in lines if line.strip()]
    if not lines:
        raise ValueError("empty_log")
    return lines if limit is None else lines[:limit]


class BusinessApplication:
    """Invoke one existing typed step per durable V2 run."""

    def __init__(self, knowledge_db_path: Path, *, team_factory=None, adapters_factory=None, planner=None, clarification_runner=None):
        from agent.tools.log_pattern_store import LogKnowledgeRepository

        self.repository = LogKnowledgeRepository(knowledge_db_path)
        self.team_factory = team_factory
        self.adapters_factory = adapters_factory
        self.planner = planner
        self.clarification_runner = clarification_runner

    async def parse(self, path: Path, snapshot: dict) -> dict:
        lines = raw_log_lines(path, snapshot["media_type"])
        session = BusinessSession(raw_log_lines=lines, original_log=lines)
        plan = DeterministicPlan(plan_id="v2-log-parse", steps=(
            LogParseStep(step_id="log-parse", type="log_parse", feature_field=snapshot.get("feature_field")),))
        report = await run_deterministic_plan(session=session, team=None, plan=plan, progress_sink=snapshot.get("_progress_sink") or NullProgressSink(),
            adapters=self.adapters_factory(None) if self.adapters_factory else None)
        if report.status != StepStatus.SUCCESS or not report.results or report.results[0].artifact is None:
            return {"error": (report.results[0].error_code if report.results else None) or "log_parse_failed"}
        artifact = report.results[0].artifact
        if artifact.artifact_type != "log_classification" or session.log_classification is None:
            return {"error": "log_parse_failed"}
        return {"classification": session.log_classification,
                "submission_eligible": artifact.submission_eligible,
                "submission_token": artifact.submission_token,
                "coverage": session.log_knowledge_submission.coverage, "total_lines": len(lines)}

    async def submit(self, path: Path, snapshot: dict, classification: dict, connection=None) -> dict:
        lines = raw_log_lines(path, snapshot["media_type"])
        session = BusinessSession(raw_log_lines=lines, original_log=lines,
                   log_classification=classification["classification"],
                   submitter_id=snapshot.get("owner_id", "session-user"))
        evidence = build_submission_snapshot(
            classification["classification"], lines,
            selection_mode="explicit" if snapshot.get("feature_field") else "automatic",
            feature_field=snapshot.get("feature_field"))
        session.log_knowledge_submission = evidence
        plan = DeterministicPlan(plan_id="v2-log-knowledge-submit", steps=(
            LogKnowledgeSubmitStep(step_id="submit", type="log_knowledge_submit",
                                   submission_token=classification["submission_token"]),))
        adapters = create_default_adapters(None)
        adapters["log_knowledge_submit"] = LogKnowledgeSubmitAdapter(
            repository=self.repository, connection=connection)
        report = await run_deterministic_plan(
            session=session, team=None, plan=plan, progress_sink=snapshot.get("_progress_sink") or NullProgressSink(), adapters=adapters)
        result = report.results[0]
        artifact = result.artifact
        if artifact is None or artifact.artifact_type != "log_knowledge_submission":
            return {"submission_status": "error", "application_id": None}
        return {"submission_status": artifact.submission_status, "application_id": artifact.application_id}

    async def field_mapping(self, path: Path, snapshot: dict, classification: dict | None = None) -> dict:
        """Run the existing mapping pipeline against one frozen input in memory."""
        from agent.core.team import create_data_mapping_team
        from contracts.rule_source import RuleSourceFields
        from toolwithagent_v2.runtime.mapping_projection import collect_samples
        from agent.tools.rule_generator import rules_to_base64_text
        from agent.shared.logger import get_logger
        from time import perf_counter

        logger = get_logger("v2.field_mapping")
        started = perf_counter()

        lines = raw_log_lines(path, snapshot["media_type"])
        logger.info("映射阶段 文件读取完成 duration_ms=%d rows=%d", round((perf_counter() - started) * 1000), len(lines))
        session = copy.copy(snapshot.get("initial_session") or BusinessSession())
        session.raw_log_lines = lines
        session.original_log = lines
        before_slots = {"enum_values": session.latest_enum_artifact, "threat_mapping": session.latest_threat_artifact}
        team = (self.team_factory or create_data_mapping_team)()
        adapters = self.adapters_factory(team) if self.adapters_factory else create_default_adapters(team)
        # 分叉②定稿（#435）：映射只消费当前分类产物，不再隐式重解析（与 #432 的同源入口一致）。
        if classification is None:
            return {"error": "classification_required"}
        from application.session_state import commit_log_classification
        commit_log_classification(session, classification["classification"])
        session.rule_source_fields = RuleSourceFields.from_value(snapshot["source_fields"])
        plan = DeterministicPlan(plan_id="v2-field-mapping", steps=(
            FieldMappingStep(step_id="field-mapping", type="field_mapping", source_ref="session.fields"),))
        started = perf_counter()
        report = await run_deterministic_plan(session=session, team=team, plan=plan,
            progress_sink=snapshot.get("_progress_sink") or NullProgressSink(), adapters=adapters)
        logger.info("映射阶段 业务步骤完成 duration_ms=%d rows=%d", round((perf_counter() - started) * 1000), len(lines))
        mapped = next((result.artifact for result in report.results
            if result.operation_type == "field_mapping" and result.status == StepStatus.SUCCESS
            and result.artifact is not None), None)
        config = session.mapped_sub_rules
        if report.status != StepStatus.SUCCESS or mapped is None or not config:
            result = next((item for item in report.results if item.status != StepStatus.SUCCESS), None)
            return {"error": (result.error_code if result else None) or "field_mapping_failed"}
        warnings = [{"code": "threat_chain_warning", "message": result.message}
            for result in report.results
            if result.operation_type == "threat_chain" and result.message and "⚠️" in result.message]
        new_types = [kind for slot, kind in ((session.latest_enum_artifact, "enum_values"), (session.latest_threat_artifact, "threat_mapping")) if slot is not None and slot is not before_slots[kind]]
        published = {kind: slot.artifact.model_dump(mode="json") for slot, kind in ((session.latest_enum_artifact, "enum_values"), (session.latest_threat_artifact, "threat_mapping")) if kind in new_types}
        published["field_mapping"] = {}
        started = perf_counter()
        samples = collect_samples(config, lines, session.log_classification)
        logger.info("映射阶段 结果样例收集完成 duration_ms=%d rows=%d fields=%d", round((perf_counter() - started) * 1000), len(lines), sum(map(len, samples.values())))
        started = perf_counter()
        frozen = freeze_session(session)
        logger.info("映射阶段 会话冻结完成 duration_ms=%d rows=%d", round((perf_counter() - started) * 1000), len(lines))
        return {"artifact_sources": artifact_sources(report, plan, published),
            "config": config, "mapping_rows": [row.model_dump(by_alias=True) for row in mapped.mappings],
            "event_annotations": [row.model_dump() for row in mapped.event_annotations],
            "warnings": warnings,
            "samples": samples,
            "download_kind": mapped.download_kind or "mapped_sub_rules",
            "download_content": rules_to_base64_text(config),
            "business_state": frozen,
            "new_typed_artifact_types": new_types}


    def apply_mapping_draft(self, base: dict, snapshot: dict) -> dict:
        """Apply a frozen Draft deterministically; no team, adapters or model calls."""
        from toolwithagent_v2.runtime.mapping_drafts import project_payload
        outcome = project_payload(base, snapshot["draft_operations"])
        if "config_root" in outcome:
            from toolwithagent_v2.runtime.postprocessing import configuration_root
            from application.adapters.shared import _build_config_artifact
            root = configuration_root(outcome)
            outcome["config_root"] = root
            outcome["download_content"] = _build_config_artifact(root, len(outcome["config"])).content
            outcome["download_kind"] = "current_config"
        return outcome


    async def postprocess(self, session: BusinessSession, snapshot: dict, base=None, continuation=None, *, progress_sink=None):
        """自然指令恰好规划一次；确认执行冻结计划，不重复 Planner 或成功步骤。"""
        from agent.core.team import create_data_mapping_team
        from application.request_runtime import run_user_request
        from application.execution_continuation import ExecutionContinuation
        from application.recovery import RecoveryBudget
        from contracts.planner_models import PlanDecision, ConfigExportArtifact, FieldMappingArtifact
        from toolwithagent_v2.runtime.postprocessing import freeze_session, restore_session, state_digest, config_payload
        from dataclasses import asdict

        progress_sink = progress_sink or NullProgressSink()
        from toolwithagent_v2.runtime.field_changes import FieldPlanCaptured, capture_field_plan, prepare_fields
        initial = freeze_session(session)
        captured, checkpoint = {}, {}
        before_slots = {"enum_values": session.latest_enum_artifact, "threat_mapping": session.latest_threat_artifact}
        team = (self.team_factory or create_data_mapping_team)()
        adapters = self.adapters_factory(team) if self.adapters_factory else create_default_adapters(team)
        if continuation is not None:
            if continuation.session_facts_digest != state_digest(initial):
                return {"error": "continuation_stale"}
            plan = DeterministicPlan.model_validate(continuation.frozen_plan)
            session = restore_session(continuation.staging_state)
            before_slots = {"enum_values": session.latest_enum_artifact, "threat_mapping": session.latest_threat_artifact}
            result = await run_deterministic_plan(session=session, team=team, plan=plan,
                progress_sink=progress_sink, adapters=adapters, continuation=continuation, checkpoint=checkpoint)
        elif "plan" in snapshot:
            plan = DeterministicPlan.model_validate(snapshot["plan"])
            from contracts.planner_models import PlanDecision
            if any(step.type in {"add_fields", "delete_fields", "merge_fields", "decode_fields", "regex_extract"} for step in plan.steps):
                return {"field_changes": await prepare_fields(session, PlanDecision(decision="execute", plan_id=plan.plan_id, steps=plan.steps), base=base)}
            result = await run_deterministic_plan(session=session, team=team, plan=plan,
                progress_sink=progress_sink, adapters=adapters, checkpoint=checkpoint)
        else:
            def on_plan(decision):
                captured.update(plan=decision)
                capture_field_plan(decision)
            try:
                result = await run_user_request(session=session, team=team, user_text=snapshot["user_text"],
                    progress_sink=progress_sink, progress_plan_id=snapshot["message_id"],
                    planner=self.planner, adapters=adapters, on_plan=on_plan, checkpoint=checkpoint)
            except FieldPlanCaptured as pending:
                if snapshot.get("field_followup"):
                    return {"error": "field_followup_requires_review", "message": "后续计划再次涉及字段变更，请在新一轮明确要求后继续。"}
                from application.adapters.field_skill import FieldSkillAdapter
                adapter = next((value for value in adapters.values() if isinstance(value, FieldSkillAdapter)), None)
                return {"field_changes": await prepare_fields(session, pending.plan, adapter=adapter, base=base)}
        if isinstance(result, PlanDecision):
            if result.decision == "proposal":
                frozen = DeterministicPlan(plan_id=result.plan_id, steps=result.steps)
                return {"continuation": ExecutionContinuation(
                    next_action="execute_plan", completed_step_refs=(), recovery_budget=asdict(RecoveryBudget()),
                    session_facts_digest=state_digest(initial), frozen_plan=frozen.model_dump(mode="json"),
                    staging_state=freeze_session(session)),
                    "confirmation": {"question": result.question, "choices": list(result.choices), "operations": [step.type for step in result.steps]}}
            if result.decision == "clarification" and result.question:
                # 与 V1 render_decision 对齐（#226）：会话事实富化追问，任何失败回退原文案。
                enriched = await compose_clarification(
                    "clarification", build_session_facts(session), result.reason_code,
                    result.choices, "", runner=self.clarification_runner)
                return {"message": enriched or result.question}
            return {"message": result.question or result.answer or "请补充明确的业务要求。"}
        if result.status != StepStatus.SUCCESS:
            failed = next(item for item in result.results if item.status != StepStatus.SUCCESS)
            if checkpoint.get("resumable_failure") and (continuation is None or (continuation.next_action == "execute_plan" and continuation.recovery_count == 0)):
                # 仅允许一次人工恢复；再次失败结束 Run，自动恢复预算始终沿用原值。
                completed = tuple(checkpoint.get("completed_results", ()))
                return {"continuation": ExecutionContinuation(
                    next_action="resume_after_failure", completed_step_refs=tuple(item["step_id"] for item in completed),
                    recovery_budget=checkpoint["recovery_budget"], session_facts_digest=state_digest(initial),
                    frozen_plan=checkpoint["frozen_plan"], completed_results=completed,
                    staging_state=freeze_session(checkpoint["execution_session"]),
                    recovery_count=checkpoint["recovery_count"], step_recovery_counts=checkpoint["step_recovery_counts"]),
                    "confirmation": {"question": "自动恢复次数已用完，是否继续未完成的步骤？", "choices": ["确认继续", "取消"],
                        "reason_code": "recovery_exhausted", "operations": [failed.operation_type]}}
            return {"error": failed.error_code or "business_operation_failed", "message": failed.message or "操作未完成，请补充参数或重试。"}
        artifacts = []
        for item in result.results:
            if getattr(item.artifact, "artifact_type", None) == "log_classification":
                artifact = item.artifact
                submission = session.log_knowledge_submission
                artifacts.append({"kind": "log_classification", "payload": {
                    "classification": artifact.classification, "submission_eligible": artifact.submission_eligible,
                    "submission_token": artifact.submission_token, "total_lines": len((session.raw_log_lines or [])),
                    "coverage": submission.coverage if submission else {}}})
        download = next((item.artifact for item in reversed(result.results) if isinstance(item.artifact, ConfigExportArtifact)), None)
        mapping = next((item.artifact for item in result.results if isinstance(item.artifact, FieldMappingArtifact)), None)
        if mapping is not None:
            base = {"mapping_rows": [row.model_dump(by_alias=True) for row in mapping.mappings],
                    "event_annotations": [row.model_dump() for row in mapping.event_annotations]}
        executed_plan = plan if continuation is not None or "plan" in snapshot else captured.get("plan")
        source = next((step.config_ref for step in reversed(executed_plan.steps) if hasattr(step, "config_ref")), None) if executed_plan else None
        source = source or ("session.mapped_sub_rules" if session.mapped_sub_rules else "session.decoded_config")
        config_changed = (session.mapped_sub_rules != initial.get("mapped_sub_rules") or session.decoded_data != initial.get("decoded_data"))
        if config_changed and (session.decoded_data if source == "session.decoded_config" else session.mapped_sub_rules):
            payload = config_payload(session, source, base)
            artifacts.append({"kind": "field_mapping", "payload": payload})
        reported_kinds = {getattr(item.artifact, "artifact_type", None) for item in result.results}
        # 执行器已按冻结计划校验成功前缀；同内容的新提交也必须获得本轮产物身份。
        from contracts.planner_models import StepResult
        completed_artifacts = [StepResult.model_validate(item).artifact for item in continuation.completed_results] if continuation else []
        for slot, key, kind in ((session.latest_enum_artifact, "latest_enum_artifact", "enum_values"), (session.latest_threat_artifact, "latest_threat_artifact", "threat_mapping")):
            resumed_commit = slot and any(
                artifact is not None and artifact.artifact_type == kind
                and artifact == slot.artifact for artifact in completed_artifacts)
            if slot and (resumed_commit or (kind in reported_kinds and slot is not before_slots[kind]) or freeze_session(session).get(key) != initial.get(key)):
                artifacts.append({"kind": kind, "payload": slot.artifact.model_dump(mode="json")})
        if download is not None:
            artifacts.append({"kind": "config_export", "payload": download.model_dump(mode="json")})
        sources = artifact_sources(result, executed_plan, {artifact["kind"]: artifact["payload"] for artifact in artifacts}) if executed_plan else {}
        for artifact in artifacts:
            artifact["source_kinds"] = sources.get(artifact["kind"], [])
        artifacts.append({"kind": "business_state", "payload": freeze_session(session)})
        return {"artifacts": artifacts, "message": "操作完成：" + "、".join(item.operation_type for item in result.results)}
