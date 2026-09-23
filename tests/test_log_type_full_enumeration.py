"""Issue #190：日志类型全量确定性枚举。

锁定四层修复：聚合默认全量（不截 2000）、format_type 大小写无关、
类型集合由「LLM 生成结构正则 + 代码校验 + 全量扫描」决定（聚类仅作结构样本源）、
>20 类型分批补 meaning（批失败只降 PARTIAL 不删类型）。
"""

from __future__ import annotations

import json
import re as _re

import agent.tools.log_pattern_store as log_pattern_store
import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.log_header_processor as log_header_processor
from agent.tools.pipeline.common.aggregator import aggregate_by_field
from agent.tools.pipeline.extractors.header_extractor import extract_header
from agent.tools.pipeline.log_header_processor import classify_header_features

H3C_TYPES = [
    "TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG",
    "session/6/SESSION_IPV4_FLOW",
    "LB/6/OUTBOUND_LLB",
    "IPS/4/IPS_IPV4_INTERZONE",
    "SSLVPN/6/SSLVPN_IP_RESOURCE_PERMIT",
    "UFLT/6/UFLT_MATCH_IPV4_LOG",
    "WAF/4/WAF_IPV4_INTERZONE",
    "SSLVPN/5/SSLVPN_USER_LOGIN",
]
SLASH_TYPES_9 = H3C_TYPES + ["WEB/6/WEB_FILTER_BLOCK"]
STRUCTURAL_LOGTYPE_REGEX = r"([A-Za-z0-9]+/\d+/[A-Za-z0-9_]+)"


def _h3c_line(type_path: str, i: int) -> str:
    return (
        f"<189>2026-09-15 10:00:00 host{i % 7} %%10VFW:1 {type_path}: "
        f"Src=10.1.{i % 250}.{i % 250}; Dst=10.2.{i % 250}.{i % 250};"
    )


def _classify_header(logs: str) -> dict:
    return json.loads(
        classify_header_features(
            logs,
            format_type="KV",
            format_detail="日志头+KV",
            format_info={"delimit": ";", "tab": "="},
        )
    )


def _mock_llm(
    monkeypatch,
    *,
    regex_responses=None,
    body_regex_responses=None,
    meaning_fail_batches=0,
) -> dict:
    """打桩三处 LLM：类型正则生成 / KV body 正则生成 / meaning 分批分类。

    regex_responses：类型正则生成的响应序列（耗尽后回落结构正则）；
    meaning_fail_batches：前 N 个 meaning 批次返回非法 JSON。
    """
    counters = {
        "regex_calls": 0,
        "body_regex_calls": 0,
        "body_prompts": [],
        "meaning_calls": 0,
    }
    regex_responses = list(regex_responses or [])
    body_regex_responses = list(body_regex_responses or [])

    def _header_llm(prompt, *args, **kwargs):
        if "日志头样例" in prompt:
            counters["regex_calls"] += 1
            if regex_responses:
                return regex_responses.pop(0)
            return f"r'{STRUCTURAL_LOGTYPE_REGEX}'"
        if "分隔符" in prompt:
            counters["body_regex_calls"] += 1
            counters["body_prompts"].append(prompt)
            if body_regex_responses:
                return body_regex_responses.pop(0)
            return r"r'^.*?\S+/\d+/\S+:\s*(.*)$'"
        raise AssertionError(f"意外的日志头路径 LLM 调用: {prompt[:80]}")

    def _meaning_llm(prompt, *args, **kwargs):
        counters["meaning_calls"] += 1
        if meaning_fail_batches and counters["meaning_calls"] <= meaning_fail_batches:
            return "这不是 JSON"
        m = _re.search(
            r"<aggregation_statistics>\s*(.*?)\s*</aggregation_statistics>",
            prompt,
            _re.S,
        )
        values = list(json.loads(m.group(1)).keys()) if m else []
        return json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "__header__",
                "Diversion_method": "日志头特征分类",
                "log_format": "KV",
                "feature_field": "__header__",
                "feature_count": len(values),
                "classification_details": [
                    {"logtype": v, "meaning": f"{v} 业务含义"} for v in values
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(log_header_processor, "_call_llm_direct", _header_llm)
    monkeypatch.setattr(log_classifier, "_call_llm_direct", _meaning_llm)
    monkeypatch.setattr(
        log_pattern_store, "generate_structured_fingerprint", lambda **kw: ""
    )
    monkeypatch.setattr(log_pattern_store, "store_log_knowledge", lambda **kw: True)
    return counters


# ---------- 截断修复 ----------


def test_aggregate_by_field_defaults_to_all_lines() -> None:
    """公共聚合入口默认处理全部有效行，不再截断前 2000 条。"""
    logs = "\n".join(f"line-{i}" for i in range(2100))
    agg = aggregate_by_field(logs, "f", lambda line, field: "x")
    assert agg["total_lines"] == 2100
    assert agg["matched_lines"] == 2100


def test_extractor_aggregate_default_keeps_tail_rare_type() -> None:
    """JSON extractor 默认全量聚合：第 2000 条之后的稀有类型仍被计数。"""
    from agent.tools.pipeline.extractors.json_extractor import JsonExtractor

    lines = [json.dumps({"event_type": "common"}, ensure_ascii=False) for _ in range(2050)]
    lines.append(json.dumps({"event_type": "rare_tail"}, ensure_ascii=False))
    agg = JsonExtractor().extract_and_aggregate("\n".join(lines), "event_type")
    assert agg["total_lines"] == 2051
    assert agg["values"]["rare_tail"]["count"] == 1


def test_extract_header_format_type_case_insensitive() -> None:
    """format_type 大小写无关：生产侧大写 KV 同样进入 KV 头部分支。"""
    line = "<189>2026-09-15 host1 %%01INFO: Type=auth;"
    upper = extract_header(line, "KV", "=")
    assert upper == extract_header(line, "kv", "=")
    assert upper.endswith("INFO:")


# ---------- header 路径：确定性全量枚举 ----------


def test_header_types_enumerated_deterministically_with_coverage(monkeypatch) -> None:
    """类型集合来自正则全量扫描：8 类型全覆盖、coverage 四字段、真实样例。"""
    _mock_llm(monkeypatch)
    logs = "\n".join(
        _h3c_line(t, i) for i in range(5) for t in H3C_TYPES
    )

    result = _classify_header(logs)

    assert result["status"] == "SUCCESS"
    assert result["feature_count"] == 8
    assert result["covered_lines"] == 40
    assert result["coverage"]["total_lines"] == 40
    assert result["coverage"]["matched_lines"] == 40
    assert result["coverage"]["unmatched_lines"] == 0
    assert {d["logtype"] for d in result["classification_details"]} == set(H3C_TYPES)
    for detail in result["classification_details"]:
        assert detail["logtype"] in detail["sample"]


def test_header_success_does_not_call_knowledge_storage(monkeypatch) -> None:
    import agent.tools.pipeline.common.knowledge_store as knowledge_store

    _mock_llm(monkeypatch)
    monkeypatch.setattr(
        knowledge_store,
        "store_classification_knowledge",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("storage must not be called")
        ),
    )
    logs = "\n".join(_h3c_line(t, i) for i, t in enumerate(H3C_TYPES[:2]))

    result = _classify_header(logs)

    assert result["status"] == "SUCCESS"
    assert result["feature_count"] == 2


def test_20k_lines_full_enumeration(monkeypatch) -> None:
    """20000 行 8 类型：feature_count=8、covered_lines=20000、SUCCESS。"""
    _mock_llm(monkeypatch)
    logs = "\n".join(_h3c_line(H3C_TYPES[i % 8], i) for i in range(20000))

    result = _classify_header(logs)

    assert result["status"] == "SUCCESS"
    assert result["feature_count"] == 8
    assert result["covered_lines"] == 20000
    assert result["coverage"]["unmatched_lines"] == 0


def test_kv_body_regex_retries_until_mixed_boundaries_are_fully_covered(
    monkeypatch,
) -> None:
    """同批次 ``: body`` / ``:body`` 必须由一个全覆盖正则提取。"""
    counters = _mock_llm(
        monkeypatch,
        body_regex_responses=[
            r"r'^.*?\S+/\d+/\S+:\s+(.*)$'",
            r"r'^.*?\S+/\d+/\S+:\s*(.*)$'",
        ],
    )
    spaced = _h3c_line("TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG", 1)
    tight = _h3c_line("SSLVPN/5/SSLVPN_USER_LOGIN", 2).replace(": Src=", ":Src=")

    result = _classify_header("\n".join([spaced, tight]))

    assert result["status"] == "SUCCESS"
    assert counters["body_regex_calls"] == 2
    assert "TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG" in counters["body_prompts"][0]
    assert "SSLVPN/5/SSLVPN_USER_LOGIN" in counters["body_prompts"][0]
    assert "kv_body_regex_validation_failed" in counters["body_prompts"][1]
    assert "matched=1; total=2" in counters["body_prompts"][1]
    details = {d["logtype"]: d for d in result["classification_details"]}
    assert details["TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG"]["real_samples"].startswith(
        "Src="
    )
    assert details["SSLVPN/5/SSLVPN_USER_LOGIN"]["real_samples"].startswith("Src=")
    assert all(not d["real_samples"].startswith("<") for d in details.values())


def test_kv_body_regex_returns_failed_when_retry_still_misses_a_variant(
    monkeypatch,
) -> None:
    """两次生成均未覆盖全部有效行时不得返回伪 SUCCESS。"""
    strict = r"r'^.*?\S+/\d+/\S+:\s+(.*)$'"
    counters = _mock_llm(
        monkeypatch,
        body_regex_responses=[strict, strict],
    )
    spaced = _h3c_line("TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG", 1)
    tight = _h3c_line("SSLVPN/5/SSLVPN_USER_LOGIN", 2).replace(": Src=", ":Src=")

    result = _classify_header("\n".join([spaced, tight]))

    assert result["status"] == "FAILED"
    assert result["error"] == "kv_body_regex_validation_failed"
    assert counters["body_regex_calls"] == 2


def test_mixed_structure_minority_reported_as_unmatched_partial(monkeypatch) -> None:
    """不同主结构（管道格式）不被捕获，进 coverage unmatched，状态 PARTIAL。"""
    _mock_llm(monkeypatch)
    slash_lines = [_h3c_line(SLASH_TYPES_9[i % 9], i) for i in range(99)]
    pipe_lines = [f"alpha{i}|beta|gamma{i}" for i in range(5)]

    result = _classify_header("\n".join(slash_lines + pipe_lines))

    assert result["status"] == "PARTIAL"
    assert result["feature_count"] == 9
    assert result["covered_lines"] == 99
    assert result["coverage"]["unmatched_lines"] == 5
    assert any("|" in s for s in result["coverage"]["unmatched_samples"])


def test_more_than_20_types_batched_meaning_all_kept(monkeypatch) -> None:
    """21 个类型全部保留；meaning 按每批 ≤20 分两次调用。"""
    counters = _mock_llm(monkeypatch)
    types = [f"TYPE{i:02d}/6/TYPE{i:02d}_EVENT" for i in range(21)]
    logs = "\n".join(_h3c_line(types[i % 21], i) for i in range(63))

    result = _classify_header(logs)

    assert result["feature_count"] == 21
    assert len({d["logtype"] for d in result["classification_details"]}) == 21
    assert counters["meaning_calls"] == 2
    assert result["status"] == "SUCCESS"
    # #281：每批（尤其第 2 批仅 TYPE20）的每个类型都要拿到真实样例行；
    # 旧逻辑按"任意不同值"计数提前退出，第 2 扫描收集 1 个干扰值即停。
    for detail in result["classification_details"]:
        assert detail["logtype"] in detail["sample"], (
            f"{detail['logtype']} 样例缺失（sample={detail['sample']!r}），"
            "分批扫描不得因干扰值提前退出"
        )


def test_meaning_batch_failure_downgrades_partial_not_deleting_types(monkeypatch) -> None:
    """meaning 批次失败只降级 PARTIAL，类型集合不受影响。"""
    _mock_llm(monkeypatch, meaning_fail_batches=1)
    types = [f"TYPE{i:02d}/6/TYPE{i:02d}_EVENT" for i in range(21)]
    logs = "\n".join(_h3c_line(types[i % 21], i) for i in range(63))

    result = _classify_header(logs)

    assert result["status"] == "PARTIAL"
    assert result["feature_count"] == 21


def test_meaning_batches_propagate_body_extraction_failure_reason(monkeypatch) -> None:
    """后处理的 body 失败原因必须穿透批处理结果。"""
    import agent.tools.pipeline.common.llm_postprocessor as postprocessor

    monkeypatch.setattr(log_classifier, "_call_llm_direct", lambda *a, **kw: "{}")
    monkeypatch.setattr(
        postprocessor,
        "postprocess_llm_classification",
        lambda *a, **kw: {
            "status": "PARTIAL",
            "fail_reason": "1 个日志类型的 KV body 提取失败",
            "classification_details": [{"logtype": "TYPE"}],
        },
    )

    result = log_classifier._meaning_fill_batches(
        {
            "values": {"TYPE": {"count": 1, "samples": ["type=TYPE"]}},
            "top_values": ["TYPE"],
        },
        "type=TYPE",
        format_type="KV",
        format_detail="日志头+KV",
        feature_field="__header__",
        extractor_func=lambda line, field: "TYPE",
    )

    assert result["status"] == "PARTIAL"
    assert result["fail_reason"] == "1 个日志类型的 KV body 提取失败"


# ---------- 正则生成失败语义 ----------


def test_regex_generation_failure_returns_failed_after_one_repair(monkeypatch) -> None:
    """正则生成两连败 → FAILED，无模型自由枚举兜底。"""
    counters = _mock_llm(
        monkeypatch, regex_responses=["r'([unclosed'", "r'(['"]
    )
    logs = "\n".join(_h3c_line(t, i) for i in range(3) for t in H3C_TYPES[:3])

    result = _classify_header(logs)

    assert result["status"] == "FAILED"
    assert result["error"] == "header_logtype_regex_validation_failed"
    assert counters["regex_calls"] == 2


def test_regex_generation_repairs_once_then_succeeds(monkeypatch) -> None:
    """首次正则失败 → 附错误反馈修复一次 → 成功。"""
    counters = _mock_llm(
        monkeypatch, regex_responses=["r'(['", f"r'{STRUCTURAL_LOGTYPE_REGEX}'"]
    )
    logs = "\n".join(_h3c_line(t, i) for i in range(3) for t in H3C_TYPES[:3])

    result = _classify_header(logs)

    assert result["status"] == "SUCCESS"
    assert counters["regex_calls"] == 2
