"""Single-leader deterministic file-ingest worker."""
import argparse
import asyncio
import hashlib
import json
import threading
import time
import zipfile
from xml.etree.ElementTree import ParseError
from uuid import uuid4

from openpyxl import load_workbook
from application.log_privacy import private_business_logging, bind_run_log_recorder, reset_run_log_recorder, bind_run_context, reset_run_context
from agent.shared.logger import get_logger
from openpyxl.utils.exceptions import InvalidFileException
from contracts.model_call_diagnostics import bind_recorder, reset_recorder, set_scope, reset_scope

from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.fake_application import FakeApplication
from toolwithagent_v2.runtime.business_application import BusinessApplication
from toolwithagent_v2.settings import Settings
from toolwithagent_v2.runtime.progress import RunProgressSink
from toolwithagent_v2.runtime import suggestions as suggestion_catalog

# 豁免脱敏的诊断通道：消息只允许由稳定错误码/ID/计数构造（#433）。
_DIAGNOSTICS = get_logger("v2.diagnostics")


class Worker:
    def __init__(self, store: Store, worker_id: str | None = None, lease_seconds: float = 30, application: FakeApplication | None = None, business_application: BusinessApplication | None = None):
        self.store = store
        self.worker_id = worker_id or str(uuid4())
        self.lease_seconds = lease_seconds
        self.application = application or FakeApplication()
        self.business_application = business_application or BusinessApplication(store.path)

    def _validate(self, snapshot):
        key = snapshot["storage_key"]
        if not key.startswith("uploads/") or ".." in key.split("/"):
            return "file_missing"
        try:
            path = (self.store.root / key).resolve()
            if not path.is_relative_to((self.store.root / "uploads").resolve()) or not path.is_file():
                return "file_missing"
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != snapshot["sha256"]:
                return "file_hash_mismatch"
            try:
                media = snapshot["media_type"]
                if media == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                    with path.open("rb") as source:
                        workbook = load_workbook(source, read_only=True, data_only=True)
                        try:
                            for sheet in workbook.worksheets:
                                sheet.reset_dimensions()
                                for _ in sheet.iter_rows(values_only=True):
                                    pass
                        finally:
                            workbook.close()
                elif media == "application/json":
                    json.loads(path.read_text(encoding="utf-8-sig"))
                elif media == "application/x-ndjson":
                    for line in path.read_text(encoding="utf-8-sig").splitlines():
                        if line.strip():
                            json.loads(line)
                else:
                    path.read_text(encoding="utf-8-sig")
            except (ValueError, UnicodeError, zipfile.BadZipFile, InvalidFileException, ParseError, KeyError, TypeError):
                return "invalid_file_content"
            return None
        except OSError:
            return "file_unreadable"

    @staticmethod
    def _summary(classification: dict, total_lines: int) -> dict:
        source = classification.get("classification", {})
        details = source.get("classification_details", [])
        types = []
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("logtype") or item.get("name") or "未命名类型")[:120]
                count = item.get("count", 0)
                types.append({"name": name, "count": count if isinstance(count, int) and count >= 0 else 0})
        coverage = source.get("coverage", {})
        matched = coverage.get("matched_lines", 0) if isinstance(coverage, dict) else 0
        if not isinstance(matched, int) or matched < 0:
            matched = 0
        format_name = str(source.get("log_format") or "未识别")[:40]
        feature = str(source.get("feature_field") or "自动识别")[:120]
        analysis = source.get("analysis")
        separator = analysis.get("tab") if isinstance(analysis, dict) else None
        rule = f"格式 {format_name}；分类字段 {feature}"
        if isinstance(separator, str) and separator and separator != "判断失败":
            rule += f"；键值分隔符 {separator[:12]!r}"
        return {"log_types": types, "coverage": {"matched_lines": matched, "total_lines": total_lines},
                "rule_summary": rule}

    def _run_log_parse(self, claim):
        snapshot = claim["input"]
        error = self._validate(snapshot)
        if error:
            return self.store.finish(self.worker_id, claim, error)
        try:
            path = self.store.root / snapshot["storage_key"]
            with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                outcome = asyncio.run(self.business_application.parse(path, {**snapshot, "_progress_sink": RunProgressSink(self.store, self.worker_id, claim)}))
            if "classification" not in outcome:
                return self.store.finish(self.worker_id, claim, outcome.get("error") or "log_parse_failed",
                                         message="日志类型提取失败，请检查文件后重试",
                                         suggestions=suggestion_catalog.failed())
            if outcome["classification"].get("status") != "SUCCESS":
                return self.store.finish(self.worker_id, claim, "log_parse_failed",
                                         message="日志类型提取未完整成功",
                                         suggestions=suggestion_catalog.failed())
            summary = self._summary(outcome, outcome["total_lines"])
            content = json.dumps(outcome, ensure_ascii=False, sort_keys=True).encode("utf-8")
            type_text = "、".join(f"{item['name']} {item['count']}" for item in summary["log_types"]) or "无"
            coverage = summary["coverage"]
            message = (f"日志类型提取完成：{type_text}；覆盖率 "
                       f"{coverage['matched_lines']}/{coverage['total_lines']}；"
                       f"解析规则：{summary['rule_summary']}")
            return self.store.publish(self.worker_id, claim, content, kind="log_classification",
                                      metadata={"summary": summary, "submission_eligible": bool(outcome["submission_eligible"])},
                                      message=message, suggestions=suggestion_catalog.classification_done())
        except Exception:
            return self.store.finish(self.worker_id, claim, "log_parse_failed",
                                     message="日志类型提取失败，请检查文件后重试",
                                     suggestions=suggestion_catalog.failed())

    def _run_log_knowledge_submit(self, claim):
        try:
            if not self.store.submission_is_current(claim):
                return self.store.finish(self.worker_id, claim, "log_knowledge_submission_stale",
                                         message="主数据或分类结果已变化，请重新提取")
            classification = self.store.read_classification(claim)
            error = self._validate(claim["input"])
            if error:
                return self.store.finish(self.worker_id, claim, error)
            if not self.store.submission_is_current(claim):
                return self.store.finish(self.worker_id, claim, "log_knowledge_submission_stale",
                                         message="主数据或分类结果已变化，请重新提取")
            return self.store.publish_submission(
                self.worker_id, claim,
                lambda db: asyncio.run(self.business_application.submit(
                    self.store.root / claim["input"]["storage_key"],
                    {**claim["input"], "owner_id": claim["owner_id"]},
                    classification, connection=db)),
                lease_seconds=self.lease_seconds)
        except (OSError, ValueError, KeyError, TypeError):
            return self.store.finish(self.worker_id, claim, "log_knowledge_submission_stale",
                                     message="主数据或分类结果已变化，请重新提取")
        except Exception:
            return self.store.finish(self.worker_id, claim, "log_knowledge_submission_error",
                                     message="知识申请暂时失败，请重试")

    def _run_field_mapping(self, claim):
        from toolwithagent_v2.runtime.mapping_projection import mapping_summary
        try:
            stage_start = time.monotonic()
            if not self.store.mapping_is_current(claim):
                return self.store.finish(self.worker_id, claim, "mapping_input_stale",
                                         message="主数据或分类结果已变化，请重新执行字段映射")
            error = self._validate(claim["input"])
            if error:
                return self.store.finish(self.worker_id, claim, error)
            classification = self.store.read_classification(claim) if claim["input"].get("source_artifact_id") else None
            initial_session = None
            if claim["input"].get("business_inputs"):
                with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                    initial_session, _ = self.store.read_business_session(claim)
            _DIAGNOSTICS.info("映射阶段 输入校验与会话恢复完成 run_id=%s duration_ms=%d", claim["id"], round((time.monotonic() - stage_start) * 1000))
            snapshot = {**claim["input"], "initial_session": initial_session, "_progress_sink": RunProgressSink(self.store, self.worker_id, claim)}
            with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                outcome = asyncio.run(self.business_application.field_mapping(
                    self.store.root / claim["input"]["storage_key"], snapshot, classification))
            if outcome.get("error") or not outcome.get("config") or not outcome.get("download_content"):
                return self.store.finish(self.worker_id, claim, outcome.get("error") or "field_mapping_failed",
                                         message="字段映射失败，请检查输入后重试",
                                         suggestions=suggestion_catalog.failed())
            stage_start = time.monotonic()
            summary = mapping_summary(outcome)
            _DIAGNOSTICS.info("映射阶段 摘要计算完成 run_id=%s duration_ms=%d fields=%d", claim["id"], round((time.monotonic() - stage_start) * 1000), summary["field_count"])
            message = (f"字段映射完成：{summary['rule_count']} 条子规则，{summary['field_count']} 个字段；"
                       f"映射成功 {summary['matched_count']}，未匹配 {summary['unmatched_count']}，解析异常 {summary['parse_error_count']}")
            if summary["uncertain_annotation_count"]:
                message += f"；事件名称待确认 {summary['uncertain_annotation_count']} 条"
            if summary["warning_codes"]:
                message += "；自动威胁类型链路有提醒，请查看结果"
            state = outcome.pop("business_state", None)
            new_types = outcome.pop("new_typed_artifact_types", ())
            artifact_sources = outcome.pop("artifact_sources", {})
            if state is not None:
                from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
                artifacts = [{"kind": "field_mapping", "payload": outcome}, {"kind": "business_state", "payload": state}]
                for key, kind, model in (("latest_enum_artifact", "enum_values", EnumArtifactSlot), ("latest_threat_artifact", "threat_mapping", ThreatArtifactSlot)):
                    if state.get(key) and kind in new_types:
                        artifacts.append({"kind": kind, "payload": model.model_validate(state[key]).artifact.model_dump(mode="json")})
                for artifact in artifacts:
                    artifact["source_kinds"] = artifact_sources.get(artifact["kind"], [])
                stage_start = time.monotonic()
                result = self.store.publish_business(self.worker_id, claim, artifacts, message,
                                                     suggestions=suggestion_catalog.mapping_done())
                _DIAGNOSTICS.info("映射阶段 产物发布完成 run_id=%s duration_ms=%d artifacts=%d", claim["id"], round((time.monotonic() - stage_start) * 1000), len(artifacts))
                return result
            return self.store.publish(self.worker_id, claim, json.dumps(outcome, ensure_ascii=False).encode("utf-8"),
                kind="field_mapping", metadata={"summary":summary}, message=message,
                suggestions=suggestion_catalog.mapping_done())
        except Exception:
            _DIAGNOSTICS.exception("映射执行失败 run_id=%s", claim["id"])
            return self.store.finish(self.worker_id, claim, "field_mapping_failed",
                                     message="字段映射失败，请检查输入后重试",
                                     suggestions=suggestion_catalog.failed())

    def _run_mapping_draft_apply(self, claim):
        from toolwithagent_v2.runtime.mapping_projection import mapping_summary
        try:
            base = self.store.read_mapping_draft_apply(claim)
            outcome = self.business_application.apply_mapping_draft(base,claim["input"])
            summary = mapping_summary(outcome)
            return self.store.publish(self.worker_id,claim,json.dumps(outcome,ensure_ascii=False).encode("utf-8"),
                kind="field_mapping",metadata={"summary":summary},
                message=f"字段映射修改已应用：{summary['matched_count']} 个字段已映射，{summary['unmatched_count']} 个未匹配")
        except (ValueError,LookupError):
            return self.store.finish(self.worker_id,claim,"mapping_draft_apply_stale",message="映射修改未应用，请检查草稿和来源后重试")
        except Exception:
            return self.store.finish(self.worker_id,claim,"mapping_draft_apply_failed",message="映射修改未应用，草稿已保留，请重试")

    def _run_business(self, claim):
        """独立 Run 内执行冻结业务输入，失败不发布 staging 的部分结果。"""
        try:
            if not self.store.business_is_current(claim):
                return self.store.finish(self.worker_id, claim, "business_input_stale", "输入或配置版本已变化，请重新发起操作。")
            if claim["input"].get("file_id"):
                error = self._validate(claim["input"])
                if error:
                    return self.store.finish(self.worker_id, claim, error)
            with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                session, base = self.store.read_business_session(claim)
                outcome = asyncio.run(self.business_application.postprocess(session, claim["input"], base, self.store.continuation(claim["id"]), progress_sink=RunProgressSink(self.store, self.worker_id, claim)))
            if "field_changes" in outcome:
                from toolwithagent_v2.infrastructure.field_changes import FieldChanges
                return FieldChanges(self.store).prepare(self.worker_id, claim, outcome["field_changes"])
            if "continuation" in outcome:
                return self.store.wait_for_confirmation(self.worker_id, claim, outcome["continuation"], kind="business_plan", payload=outcome["confirmation"]) is not None
            if "artifacts" in outcome:
                return self.store.publish_business(self.worker_id, claim, outcome["artifacts"], outcome.get("message"),
                                                   suggestions=suggestion_catalog.business_done())
            return self.store.finish(self.worker_id, claim, outcome.get("error"), outcome.get("message"),
                                     suggestions=suggestion_catalog.failed() if outcome.get("error") else None)
        except (ValueError, LookupError):
            return self.store.finish(self.worker_id, claim, "business_input_invalid", "业务来源已不可用，请检查输入后重试。",
                                     suggestions=suggestion_catalog.failed())
        except Exception:
            return self.store.finish(self.worker_id, claim, "business_operation_failed", "操作失败，请检查输入后重试。",
                                     suggestions=suggestion_catalog.failed())

    def _run_field_change(self, claim):
        from toolwithagent_v2.infrastructure.field_changes import FieldChanges
        from toolwithagent_v2.runtime.field_changes import apply_fields
        from toolwithagent_v2.runtime.postprocessing import restore_session, freeze_session, config_payload
        try:
            prepared = FieldChanges(self.store).read_command(claim)
            with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                if claim["task_type"] == "field_change_undo":
                    session = restore_session(prepared["initial_state"])
                    source = prepared["groups"][0]["steps"][0]["config_ref"]
                    payload = config_payload(session, source, prepared.get("base_payload"))
                else:
                    session, payload = asyncio.run(apply_fields(prepared, claim["input"]["selected_group_ids"]))
            payload["field_change_run_id"] = claim["input"]["field_preview_run_id"]
            payload["undo_of"] = claim["input"].get("undo_artifact_id")
            artifacts = [{"kind": "field_mapping", "payload": payload}]
            if claim["task_type"] == "field_change_undo":
                for kind, slot in (("enum_values", session.latest_enum_artifact), ("threat_mapping", session.latest_threat_artifact)):
                    if slot is not None:
                        artifacts.append({"kind": kind, "payload": slot.artifact.model_dump(mode="json"), "source_kinds": ["field_mapping"]})
            artifacts.append({"kind": "business_state", "payload": freeze_session(session)})
            return self.store.publish_business(self.worker_id, claim, artifacts,
                "本次字段变更已撤销，已生成恢复版本。" if claim["task_type"] == "field_change_undo" else "字段变更已应用；未选组已记为用户未应用。")
        except (ValueError, LookupError) as error:
            return self.store.finish(self.worker_id, claim, str(error), "变更未发布，请重新检查来源与选择。")
        except Exception:
            return self.store.finish(self.worker_id, claim, "field_change_failed", "变更未发布，请重试。")

    def _run_enum_attachment(self, claim):
        """附件校验完整后才生效，不把枚举 Excel 切成主数据。"""
        from toolwithagent_v2.runtime.postprocessing import attach_enum
        error = self._validate(claim["input"])
        if error:
            return self.store.finish(self.worker_id, claim, error)
        try:
            with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                from toolwithagent_v2.runtime.postprocessing import BusinessSession
                attach_enum(BusinessSession(), self.store.root / claim["input"]["storage_key"], self.store.root / "staging")
            return self.store.finish(self.worker_id, claim)
        except Exception:
            return self.store.finish(self.worker_id, claim, "enum_attachment_invalid", "枚举映射附件未完整通过校验，请检查工作表。")

    def _log_model_call_failure(self, claim, event):
        """失败模型调用的稳定类别行：仅异常分类学/HTTP 状态/ID/计数（#433）。"""
        if event.get("status") != "failed":
            return
        _DIAGNOSTICS.error(
            "model_call_failed run_id=%s task=%s operation=%s attempt=%s error_code=%s "
            "http_status=%s duration_ms=%s provider=%s model=%s",
            claim["id"], claim["task_type"], event.get("operation") or "-",
            event.get("attempt") or "-", event.get("error_code") or "model_unclassified",
            event.get("http_status") or "-", event.get("duration_ms") or "-",
            event.get("provider"), event.get("model"),
        )

    def once(self) -> bool:
        claim = self.store.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if claim is None:
            return False
        stop = threading.Event()
        def record_call(event):
            self.store.record_model_call(self.worker_id, claim, event)
            _DIAGNOSTICS.info("模型调用 run_id=%s operation=%s provider=%s model=%s duration_ms=%s\n请求:\n%s\n响应:\n%s",
                              claim["id"], event.get("operation") or claim["task_type"], event.get("provider"),
                              event.get("model"), event.get("duration_ms"), event.get("request") or "未采集",
                              event.get("response") or "未采集")
            self._log_model_call_failure(claim, event)

        diagnostic_token = bind_recorder(record_call)
        log_token = bind_run_log_recorder(lambda record: self.store.record_run_log(self.worker_id, claim, record))
        context_token = bind_run_context(run_id=claim["id"], step=claim["task_type"])
        scope_token = set_scope(None)

        def heartbeat():
            while not stop.wait(min(5, self.lease_seconds / 3)):
                if not self.store.renew(self.worker_id, claim, lease_seconds=self.lease_seconds):
                    break

        keeper = threading.Thread(target=heartbeat, daemon=True)
        keeper.start()
        try:
            if claim["task_type"] == "business_clear":
                with private_business_logging(run_id=claim["id"], step=claim["task_type"]):
                    return self.store.clear_business(self.worker_id, claim)
            if claim["task_type"] in {"user_request", "business_operation"}:
                return self._run_business(claim)
            if claim["task_type"] == "file_ingest" and claim["input"].get("role") == "enum_mapping":
                return self._run_enum_attachment(claim)
            if claim["task_type"] == "file_ingest":
                error = self._validate(claim["input"])
                if error:
                    return self.store.finish(self.worker_id, claim, error)
                # 主数据校验通过后的意图气泡（#435）：下一步由用户按目标选择或直接输入。
                return self.store.finish(self.worker_id, claim, None,
                                         message="文件校验完成。想做什么？可以直接输入一句话，或从下面的建议开始。",
                                         suggestions=suggestion_catalog.upload_validated(claim["input"].get("file_id")))
            if claim["task_type"] in {"field_change_apply", "field_change_undo"}:
                return self._run_field_change(claim)
            if claim["task_type"] == "mapping_draft_apply":
                return self._run_mapping_draft_apply(claim)
            if claim["task_type"] == "field_mapping":
                return self._run_field_mapping(claim)
            if claim["task_type"] == "log_parse":
                return self._run_log_parse(claim)
            if claim["task_type"] == "log_knowledge_submit":
                return self._run_log_knowledge_submit(claim)
            if "scenario" in claim["input"]:
                if self.store.settings.development:
                    outcome = self.application.execute(claim["input"], self.store.continuation(claim["id"]))
                else:
                    outcome = {"error": "fake_runs_disabled"}
            else:
                outcome = {"error": self._validate(claim["input"])}
            if "field_changes" in outcome:
                from toolwithagent_v2.infrastructure.field_changes import FieldChanges
                return FieldChanges(self.store).prepare(self.worker_id, claim, outcome["field_changes"])
            if "continuation" in outcome:
                return self.store.wait_for_confirmation(self.worker_id, claim, outcome["continuation"],
                                                        payload=outcome.get("confirmation")) is not None
            if "artifact" in outcome:
                return self.store.publish(self.worker_id, claim, outcome["artifact"])
            return self.store.finish(self.worker_id, claim, outcome.get("error"))
        finally:
            reset_scope(scope_token)
            reset_recorder(diagnostic_token)
            reset_run_log_recorder(log_token)
            reset_run_context(context_token)
            stop.set()
            keeper.join()

    def run_forever(self, poll_seconds: float = 0.5):
        while True:
            if not self.once():
                time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = Worker(Store(Settings.from_env()))
    if args.once:
        worker.once()
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()
