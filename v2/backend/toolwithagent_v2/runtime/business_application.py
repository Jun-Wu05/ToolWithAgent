"""Small bridge from durable V2 runs to the existing Application executor."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from openpyxl import load_workbook

from application.file_input import simple_decode
from application.adapters.composition import create_default_adapters
from application.adapters.log_knowledge_submit import LogKnowledgeSubmitAdapter
from application.log_knowledge_submission import build_submission_snapshot
from application.progress import NullProgressSink
from application.request_runtime import run_deterministic_plan
from contracts.planner_models import DeterministicPlan, FieldMappingStep, LogKnowledgeSubmitStep, LogParseStep, StepStatus


def raw_log_lines(path: Path, media_type: str) -> list[str]:
    if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        with path.open("rb") as source:
            workbook = load_workbook(source, read_only=True, data_only=True)
            try:
                sheet = workbook.active
                rows = sheet.iter_rows(values_only=True)
                header = next(rows, ())
                index = next((i for i, value in enumerate(header) if "原始日志" in str(value)), None)
                if index is None:
                    raise ValueError("raw_log_column_missing")
                values = [str(row[index]) for row in rows if index < len(row) and row[index] is not None]
                lines = [re.sub(r"[\r\n]+", " ", value) for value in values if value.strip()]
            finally:
                workbook.close()
    elif media_type == "text/csv":
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            column = next((name for name in (reader.fieldnames or []) if "原始日志" in name), None)
            lines = [str(row[column]) if column else json.dumps(row, ensure_ascii=False)
                     for row in reader if row]
    else:
        text = path.read_text(encoding="utf-8-sig")
        if media_type == "application/x-ndjson":
            lines = [line for line in text.splitlines() if line.strip()]
        elif media_type == "application/json":
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
    return lines


class BusinessApplication:
    """Invoke one existing typed step per durable V2 run."""

    def __init__(self, knowledge_db_path: Path, *, team_factory=None, adapters_factory=None):
        from agent.tools.log_pattern_store import LogKnowledgeRepository

        self.repository = LogKnowledgeRepository(knowledge_db_path)
        self.team_factory = team_factory
        self.adapters_factory = adapters_factory

    async def parse(self, path: Path, snapshot: dict) -> dict:
        lines = raw_log_lines(path, snapshot["media_type"])
        session = {"raw_log_lines": lines, "original_log": lines}
        plan = DeterministicPlan(plan_id="v2-log-parse", steps=(
            LogParseStep(step_id="log-parse", type="log_parse", feature_field=snapshot.get("feature_field")),))
        report = await run_deterministic_plan(session=session, team=None, plan=plan, progress_sink=NullProgressSink())
        if report.status != StepStatus.SUCCESS or not report.results or report.results[0].artifact is None:
            return {"error": (report.results[0].error_code if report.results else None) or "log_parse_failed"}
        artifact = report.results[0].artifact
        if artifact.artifact_type != "log_classification" or session.get("log_classification") is None:
            return {"error": "log_parse_failed"}
        return {"classification": session["log_classification"],
                "submission_eligible": artifact.submission_eligible,
                "submission_token": artifact.submission_token,
                "coverage": session["log_knowledge_submission"].coverage, "total_lines": len(lines)}

    async def submit(self, path: Path, snapshot: dict, classification: dict, connection=None) -> dict:
        lines = raw_log_lines(path, snapshot["media_type"])
        session = {"raw_log_lines": lines, "original_log": lines,
                   "log_classification": classification["classification"],
                   "submitter_id": snapshot.get("owner_id", "session-user")}
        evidence = build_submission_snapshot(
            classification["classification"], lines,
            selection_mode="explicit" if snapshot.get("feature_field") else "automatic",
            feature_field=snapshot.get("feature_field"))
        session["log_knowledge_submission"] = evidence
        plan = DeterministicPlan(plan_id="v2-log-knowledge-submit", steps=(
            LogKnowledgeSubmitStep(step_id="submit", type="log_knowledge_submit",
                                   submission_token=classification["submission_token"]),))
        adapters = create_default_adapters(None)
        adapters["log_knowledge_submit"] = LogKnowledgeSubmitAdapter(
            repository=self.repository, connection=connection)
        report = await run_deterministic_plan(
            session=session, team=None, plan=plan, progress_sink=NullProgressSink(), adapters=adapters)
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

        lines = raw_log_lines(path, snapshot["media_type"])
        session = {"raw_log_lines": lines, "original_log": lines}
        team = (self.team_factory or create_data_mapping_team)()
        adapters = self.adapters_factory(team) if self.adapters_factory else create_default_adapters(team)
        if classification is not None:
            session["log_classification"] = classification["classification"]
        else:
            parse_plan = DeterministicPlan(plan_id="v2-mapping-log-parse", steps=(
                LogParseStep(step_id="log-parse", type="log_parse", feature_field=snapshot.get("feature_field")),))
            parsed = await run_deterministic_plan(session=session, team=team, plan=parse_plan,
                progress_sink=NullProgressSink(), adapters=adapters)
            if parsed.status != StepStatus.SUCCESS or not session.get("log_classification"):
                return {"error": "log_parse_failed"}
        session["rule_source_fields"] = RuleSourceFields.from_value(snapshot["source_fields"])
        plan = DeterministicPlan(plan_id="v2-field-mapping", steps=(
            FieldMappingStep(step_id="field-mapping", type="field_mapping", source_ref="session.fields"),))
        report = await run_deterministic_plan(session=session, team=team, plan=plan,
            progress_sink=NullProgressSink(), adapters=adapters)
        mapped = next((result.artifact for result in report.results
            if result.operation_type == "field_mapping" and result.status == StepStatus.SUCCESS
            and result.artifact is not None), None)
        config = session.get("mapped_sub_rules")
        if report.status != StepStatus.SUCCESS or mapped is None or not config:
            result = next((item for item in report.results if item.status != StepStatus.SUCCESS), None)
            return {"error": (result.error_code if result else None) or "field_mapping_failed"}
        warnings = [{"code": "threat_chain_warning", "message": result.message}
            for result in report.results
            if result.operation_type == "threat_chain" and result.message and "⚠️" in result.message]
        return {"config": config, "mapping_rows": [row.model_dump(by_alias=True) for row in mapped.mappings],
            "event_annotations": [row.model_dump() for row in mapped.event_annotations],
            "warnings": warnings,
            "samples": collect_samples(config, lines, session["log_classification"]),
            "download_kind": mapped.download_kind or "mapped_sub_rules",
            "download_content": rules_to_base64_text(config)}


    def apply_mapping_draft(self, base: dict, snapshot: dict) -> dict:
        """Apply a frozen Draft deterministically; no team, adapters or model calls."""
        from toolwithagent_v2.runtime.mapping_drafts import project_payload
        return project_payload(base, snapshot["draft_operations"])
