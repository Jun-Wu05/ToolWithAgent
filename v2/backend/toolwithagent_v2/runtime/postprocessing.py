"""持久化输入与既有 Application 业务运行时之间的确定性转换。"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from dataclasses import asdict, dataclass, field, is_dataclass

from application.file_input import simple_decode, build_simplified_data, commit_primary_dataset
from application.session_state import PrimaryDatasetSnapshot, SessionState
from application.enum_mapping_attachments import commit_enum_mapping_attachment
from contracts.session_artifacts import EnumArtifactSlot, ThreatArtifactSlot
from contracts.rule_source import RuleSourceFields

@dataclass
class BusinessSession(SessionState):
    """V2 运行态附加身份和附件 ID；共享业务逻辑只消费 typed SessionState。"""
    applied_attachment_ids: list[str] = field(default_factory=list)
    submitter_id: str = "session-user"

    def clear_decoded_data(self) -> None:
        """沿用共享主数据生命周期，并清除 V2 附件提交去重状态。"""
        super().clear_decoded_data()
        self.applied_attachment_ids = []


STATE_KEYS = (
    "current_execution", "previous_execution", "applied_attachment_ids", "decoded_data", "decoded_fields", "original_log", "simplified_data", "decoded_text",
    "raw_log_lines", "raw_base64", "uploaded_file_name", "uploaded_file_time",
    "mapped_sub_rules", "log_classification", "rule_source_fields", "threat_source_field_override",
    "latest_enum_artifact", "latest_threat_artifact", "enum_mapping_sheets", "enum_preview",
    "enum_fill_contributions", "stale_enum_config_refs", "enum_pending_refills", "conversation_history",
)


def plain(value):
    """把类型化槽位和集合编码为稳定 JSON，真实内容仅进入受保护 Blob。"""
    if is_dataclass(value):
        return plain(asdict(value))
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, set):
        return sorted(plain(item) for item in value)
    return value


def freeze_session(session: SessionState) -> dict:
    """只冻结明确的业务白名单属性，不序列化 Team、密钥或运行时路径。"""
    if not isinstance(session, SessionState):
        raise TypeError("typed_session_required")
    return {key: plain(value) for key in STATE_KEYS if (value := getattr(session, key, None)) is not None}


def restore_session(state: dict) -> BusinessSession:
    """旧保护 Blob 仍是 JSON；运行态始终重建为 typed 子类，不恢复 dict 垫片。"""
    values = {key: copy.deepcopy(state[key]) for key in STATE_KEYS if key in state}
    for key, model in (("latest_enum_artifact", EnumArtifactSlot), ("latest_threat_artifact", ThreatArtifactSlot)):
        if values.get(key) is not None:
            values[key] = model.model_validate(values[key])
    if values.get("rule_source_fields") is not None:
        values["rule_source_fields"] = RuleSourceFields.from_value(values["rule_source_fields"])
    from contracts.session_facts import ExecutionSummary
    for key in ("current_execution", "previous_execution"):
        if values.get(key) is not None:
            values[key] = ExecutionSummary.model_validate(values[key])
    values["stale_enum_config_refs"] = set(values.get("stale_enum_config_refs") or ())
    values["enum_pending_refills"] = {key: set(items) for key, items in (values.get("enum_pending_refills") or {}).items()}
    return BusinessSession(**values)


def state_digest(state):
    """完整输入内容哈希补充安全事实摘要，防止同计数内容变化绕过确认。"""
    return hashlib.sha256(json.dumps(plain(state), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def primary_session(path, snapshot):
    """复用文件输入的原子主数据提交，日志与规则保留原始根结构。"""
    from toolwithagent_v2.runtime.business_application import raw_log_lines
    media = snapshot["media_type"]
    if media in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv", "application/x-ndjson"):
        lines = raw_log_lines(path, media)
        result = {"decoded_json": None, "decoded_text": "\n".join(lines), "fields": [], "original_log": lines}
        text = None
    else:
        text = path.read_text(encoding="utf-8-sig")
        result = simple_decode(text)
        if result.get("status") != "success":
            raise ValueError("invalid_file_content")
        lines = raw_log_lines(path, media)
    session = BusinessSession()
    commit_primary_dataset(session, PrimaryDatasetSnapshot(
        decoded_data=result.get("decoded_json") if result.get("fields") else None, decoded_fields=result.get("fields", []),
        original_log=result.get("original_log"), simplified_data=build_simplified_data(result),
        decoded_text=result.get("decoded_text", ""), raw_log_lines=lines,
        raw_base64=text, uploaded_file_name=snapshot.get("original_name", "主数据"), uploaded_file_time=""))
    return session


def attach_enum(session, path, staging_dir):
    """复用完整工作簿解析与 Sheet 原子替换，临时 XLSX 不进入会话引用。"""
    from agent.tools import read_enum_mappings_from_excel
    with tempfile.TemporaryDirectory(dir=staging_dir, prefix="enum-") as folder:
        source = Path(folder) / "attachment.xlsx"
        source.write_bytes(path.read_bytes())
        sheets = read_enum_mappings_from_excel(str(source))
    commit_enum_mapping_attachment(session, "enum-mapping-attachment", sheets)


def configuration_root(payload):
    """将表格中的子规则投影回原配置路径，保持 dict/list 根类型与其他键。"""
    if "config_root" not in payload:
        return copy.deepcopy(payload["config"])
    root = copy.deepcopy(payload["config_root"])
    for path, rule in zip(payload["rule_paths"], payload["config"]):
        if not path:
            root = copy.deepcopy(rule)
        else:
            target = root
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = copy.deepcopy(rule)
    return root


def config_payload(session, source, base=None, download=None):
    """把最新正式配置放入兼容映射族，Draft 始终编辑该版本而非旧配置。"""
    from agent.shared.mapping_utils import iter_normalize_entries
    from application.adapters.shared import _build_config_artifact
    root = session.decoded_data if source == "session.decoded_config" else session.mapped_sub_rules
    rules, paths, seen = [], [], set()
    for path, _, owner, _ in iter_normalize_entries(root, require_index=False):
        if path not in seen:
            seen.add(path); paths.append(list(path)); rules.append(copy.deepcopy(owner))
    payload = copy.deepcopy(base or {})
    payload.update({"config": rules, "configuration_source": source})
    if source == "session.decoded_config":
        payload.update({"config_root": copy.deepcopy(root), "rule_paths": paths})
    else:
        payload.pop("config_root", None); payload.pop("rule_paths", None)
    if not payload.get("mapping_rows"):
        rows = {}
        for rule in rules:
            for entry in rule.get("normalize", []):
                index = str(entry.get("index") or "")
                if index:
                    rows.setdefault(index, {"原始字段名": index, "系统属性名称": entry.get("field") or "未匹配", "匹配状态": "已上传配置"})
        payload["mapping_rows"] = list(rows.values())
    payload.setdefault("samples", {})
    payload.setdefault("event_annotations", [])
    payload.setdefault("warnings", [])
    artifact = download or _build_config_artifact(root, len(rules), "current_config" if source == "session.decoded_config" else "mappedconfig_subrules")
    payload.update({"download_content": artifact.content, "download_kind": artifact.download_kind})
    return payload
