"""日志知识申请资格快照：只计算可审核证据，不执行持久化。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal


MIN_REPLAYABLE_SAMPLES = 3
MIN_COVERAGE = 0.8
MAX_REVIEW_SAMPLES = 10


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def normalize_feature_field(value: str) -> str:
    """规范化显式分类特征字段，使等价 Unicode、空白和大小写身份一致。"""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _dataset_lines(raw_lines: Any) -> tuple[str, ...]:
    if isinstance(raw_lines, str):
        source = raw_lines.splitlines()
    elif isinstance(raw_lines, (list, tuple)):
        source = raw_lines
    else:
        source = ()
    return tuple(str(line).strip() for line in source if str(line).strip())


def dataset_digest(raw_lines: Any) -> str:
    """返回仅用于新鲜度比较的主数据摘要，不暴露日志正文。"""
    return _digest(_dataset_lines(raw_lines))


def classification_digest(classification: dict[str, Any]) -> str:
    """返回分类快照摘要，避免提交时混用另一轮分类。"""
    return _digest(classification)


def _json_path_exists(line: str, path: str) -> bool:
    start, end = line.find("{"), line.rfind("}")
    if start < 0 or end < start:
        return False
    try:
        value: Any = json.loads(line[start : end + 1])
    except (TypeError, ValueError):
        return False
    for part in path.split("."):
        if not isinstance(value, dict):
            return False
        keys = [key for key in value if normalize_feature_field(str(key)) == part]
        if len(keys) != 1:
            return False
        value = value[keys[0]]
    return value is not None


def _field_path_exists(line: str, path: str, format_type: str, tab: str) -> bool:
    if "json" in format_type.casefold():
        return _json_path_exists(line, path)
    separator = re.escape(tab or "=")
    return re.search(
        rf"(?<![\w.]){re.escape(path)}\s*{separator}\s*\S+",
        line,
        flags=re.IGNORECASE,
    ) is not None


@dataclass(frozen=True, slots=True)
class LogKnowledgeSubmissionSnapshot:
    """绑定主数据、分类、可执行配方和有限真实样例的提交证据。"""

    eligible: bool
    ineligible_reason: str | None
    dataset_digest: str
    classification_digest: str
    identity_digest: str
    submission_token: str
    structure_hash: str
    structure_tokens: tuple[str, ...]
    format_type: str
    format_spec: dict[str, Any]
    selection_mode: Literal["automatic", "explicit"]
    feature_field: str
    extractor_type: Literal["regex", "field_path"]
    extractor_spec: dict[str, Any]
    samples: tuple[str, ...]
    sample_hashes: tuple[str, ...]
    coverage: float
    recipe_version: int = 1


def build_submission_snapshot(
    classification: dict[str, Any],
    raw_lines: Any,
    *,
    selection_mode: Literal["automatic", "explicit"],
    feature_field: str | None = None,
) -> LogKnowledgeSubmissionSnapshot:
    """从一次分类结果构建快照；任何门槛失败只标记不合格，不影响分类。"""
    lines = _dataset_lines(raw_lines)
    raw_feature = str(feature_field or classification.get("feature_field", "") or "")
    normalized_field = normalize_feature_field(raw_feature)
    identity_field = normalized_field if selection_mode == "explicit" else ""
    format_type = str(
        classification.get("log_format", classification.get("format", "")) or ""
    )
    analysis = classification.get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    format_spec = {
        "format_detail": str(classification.get("log_format_detail", "") or ""),
        "delimit": str(analysis.get("delimit", "") or ""),
        "tab": str(analysis.get("tab", "") or ""),
    }
    pattern = str(classification.get("feature_identifier", "") or "")
    extractor_type: Literal["regex", "field_path"] = (
        "regex" if pattern else "field_path"
    )
    extractor_spec = (
        {"pattern": pattern}
        if pattern
        else {"path": normalized_field, "tab": format_spec["tab"] or "="}
    )
    replayable: list[str] = []
    matched_line_count = 0
    recipe_available = bool(pattern or normalized_field)
    compiled = None
    if pattern:
        try:
            compiled = re.compile(pattern)
        except re.error:
            recipe_available = False
    if recipe_available:
        for line in lines:
            matched = (
                compiled.search(line) is not None
                if compiled is not None
                else _field_path_exists(
                    line,
                    normalized_field,
                    format_type,
                    str(extractor_spec.get("tab", "=")),
                )
            )
            if not matched:
                continue
            matched_line_count += 1
            if line not in replayable and len(replayable) < MAX_REVIEW_SAMPLES:
                replayable.append(line)

    coverage = matched_line_count / len(lines) if lines else 0.0
    reason = None
    if str(classification.get("status", "")).upper() != "SUCCESS":
        reason = "classification_incomplete"
    elif not recipe_available:
        reason = "recipe_unavailable"
    elif coverage < MIN_COVERAGE:
        reason = "coverage_insufficient"
    elif len(replayable) < MIN_REPLAYABLE_SAMPLES:
        reason = "samples_insufficient"

    structure_tokens = tuple(
        token
        for token in (
            format_type.casefold(),
            normalize_feature_field(format_spec["format_detail"]),
            extractor_type,
        )
        if token
    )
    structure_hash = _digest({"tokens": structure_tokens, "spec": format_spec})
    identity_digest = _digest(
        {
            "recipe_version": 1,
            "structure_hash": structure_hash,
            "selection_mode": selection_mode,
            "feature_field": identity_field,
            "extractor_type": extractor_type,
            "extractor_spec": extractor_spec,
        }
    )
    current_dataset_digest = dataset_digest(lines)
    current_classification_digest = classification_digest(classification)
    submission_token = _digest(
        {
            "dataset": current_dataset_digest,
            "classification": current_classification_digest,
            "identity": identity_digest,
        }
    )
    samples = tuple(replayable)
    return LogKnowledgeSubmissionSnapshot(
        eligible=reason is None,
        ineligible_reason=reason,
        dataset_digest=current_dataset_digest,
        classification_digest=current_classification_digest,
        identity_digest=identity_digest,
        submission_token=submission_token,
        structure_hash=structure_hash,
        structure_tokens=structure_tokens,
        format_type=format_type,
        format_spec=format_spec,
        selection_mode=selection_mode,
        feature_field=identity_field,
        extractor_type=extractor_type,
        extractor_spec=extractor_spec,
        samples=samples,
        sample_hashes=tuple(hashlib.sha256(line.encode("utf-8")).hexdigest() for line in samples),
        coverage=coverage,
    )
