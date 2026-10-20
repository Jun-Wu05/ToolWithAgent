"""日志特征分类路由器（_do_classify_log_features）分支钉桩。

批次十二（#387）结构收口前的 characterization 基线：既有测试覆盖显式字段、
体键覆盖率路由、头+KV 的 header/body 子路径；本文件钉住其余分支与安全失败
子路径的现行为，改前改后均须逐字节保持。
"""

import json

import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.log_feature_locator as log_feature_locator
from agent.tools import classify_log_features_headless


HEADER_KV_LOGS = (
    "<134>Aug 24 10:00:00 host app: event=attack src=10.0.0.1\n"
    "<134>Aug 24 10:00:01 host app: event=scan src=10.0.0.2"
)
FORMAT_INFO = json.dumps(
    {"format": "kv", "format_detail": "日志头+KV", "delimit": " ", "tab": "="},
    ensure_ascii=False,
)


def _locate_sentinel(calls):
    def _fake_locate(**kwargs):
        calls.append(kwargs)
        return {"feature_location": "unknown", "feature_field": "", "reason": "sentinel"}

    return _fake_locate


def test不支持的格式返回十键UNSUPPORTED载荷():
    """非 KV/JSON 格式在守卫处返回稳定的十键 UNSUPPORTED 载荷。"""
    result = json.loads(
        classify_log_features_headless(HEADER_KV_LOGS, "unknown", "未知", "log_type", "", "")
    )

    assert set(result) == {
        "status", "error", "log_format", "log_format_detail", "feature_field",
        "feature_identifier", "feature_count", "total_valid_lines",
        "covered_lines", "classification_details",
    }
    assert result["status"] == "UNSUPPORTED"
    assert result["error"] == "不支持的日志格式: unknown"
    assert result["log_format_detail"] == "未知"
    assert result["feature_field"] == "log_type"
    assert result["feature_identifier"] == ""
    assert result["feature_count"] == 0
    assert result["total_valid_lines"] == 0
    assert result["covered_lines"] == 0
    assert result["classification_details"] == []


def test头加KV定位unknown时安全失败(monkeypatch):
    """Step 2a 返回 unknown 不得猜测，按特征定位失败拒绝。"""
    monkeypatch.setattr(
        log_feature_locator,
        "locate_feature",
        lambda **kwargs: {
            "feature_location": "unknown",
            "feature_field": "",
            "reason": "mock 定位不可用",
        },
    )

    result = json.loads(
        classify_log_features_headless(
            HEADER_KV_LOGS, "kv", "日志头+KV", "category", FORMAT_INFO, ""
        )
    )

    assert result["status"] == "FAILED"
    assert "特征定位失败: mock 定位不可用" in result["error"]


def test头加KV定位body但无字段时判定失败(monkeypatch):
    """body 路径必须携带 feature_field，缺失即 Step 2a 判断错误。"""
    monkeypatch.setattr(
        log_feature_locator,
        "locate_feature",
        lambda **kwargs: {
            "feature_location": "body",
            "feature_field": "",
            "reason": "mock",
            "body_candidates": 0,
        },
    )

    result = json.loads(
        classify_log_features_headless(
            HEADER_KV_LOGS, "kv", "日志头+KV", "category", FORMAT_INFO, ""
        )
    )

    assert result["status"] == "FAILED"
    assert "body 路径必须有 feature_field" in result["error"]


def test头加KV定位header但字段非header哨兵时判定失败(monkeypatch):
    """header 路径的 feature_field 必须为 __header__，其他值即判断错误。"""
    monkeypatch.setattr(
        log_feature_locator,
        "locate_feature",
        lambda **kwargs: {
            "feature_location": "header",
            "feature_field": "event",
            "reason": "mock",
            "body_candidates": 0,
        },
    )

    result = json.loads(
        classify_log_features_headless(
            HEADER_KV_LOGS, "kv", "日志头+KV", "category", FORMAT_INFO, ""
        )
    )

    assert result["status"] == "FAILED"
    assert "header 路径 feature_field 必须为 __header__（实际为 event）" in result["error"]


def test纯KV特征键低覆盖时直落PathKV且不调用定位器(monkeypatch):
    """无日志头的 KV 且特征键不在行内时走纯 KV 聚合，Step 2a 不得被调用。"""
    calls = []
    monkeypatch.setattr(log_feature_locator, "locate_feature", _locate_sentinel(calls))

    result = json.loads(
        classify_log_features_headless(
            "event=attack src=10.0.0.1\nevent=scan src=10.0.0.2",
            "kv",
            "KV",
            "category",
            json.dumps({"format": "kv", "format_detail": "KV"}, ensure_ascii=False),
            "",
        )
    )

    assert calls == []
    assert result["status"] == "FAILED"
    assert "category" in result["error"]


HEADER_JSON_LOGS = (
    '<134>Aug 24 10:00:00 host app: {"app_protocol":"ssh","src":"10.0.0.1"}\n'
    '<134>Aug 24 10:00:01 host app: {"app_protocol":"dns","src":"10.0.0.2"}'
)


def test头加JSON定位body后按修正字段走PathMain且不传fmt(monkeypatch, caplog):
    """日志头+JSON 的 Step 2a 不传 FormatContext（与 KV 版刻意不对称）。"""
    calls = []
    monkeypatch.setattr(
        log_feature_locator,
        "locate_feature",
        lambda **kwargs: (
            calls.append(kwargs),
            {
                "feature_location": "body",
                "feature_field": "app_protocol",
                "reason": "mock",
            },
        )[1],
    )
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "app_protocol",
                "Diversion_method": "日志类型",
                "log_format": "JSON",
                "feature_field": "app_protocol",
                "feature_count": 2,
                "classification_details": [
                    {"logtype": "ssh", "meaning": "SSH"},
                    {"logtype": "dns", "meaning": "DNS"},
                ],
            },
            ensure_ascii=False,
        ),
    )

    result = json.loads(
        classify_log_features_headless(
            HEADER_JSON_LOGS,
            "json",
            "日志头+JSON",
            "category",
            json.dumps({"format": "json", "format_detail": "日志头+JSON"}, ensure_ascii=False),
            "",
        )
    )

    assert len(calls) == 1
    assert "fmt" not in calls[0]
    assert result["status"] == "SUCCESS"
    assert result["feature_field"] == "app_protocol"


def test纯JSON低覆盖时直落PathMain失败且无LLM兜底(monkeypatch):
    """无日志头的 JSON 且特征键不在行内时走纯 JSON 聚合并 FAILED，
    即使 _call_llm_direct 可用也不得触发 LLM 兜底（现行为钉桩）。"""
    calls = []
    monkeypatch.setattr(log_feature_locator, "locate_feature", _locate_sentinel(calls))
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "protocol",
                "Diversion_method": "日志类型",
                "log_format": "JSON",
                "feature_field": "protocol",
                "feature_count": 2,
                "classification_details": [{"logtype": "ssh", "meaning": "SSH"}],
            },
            ensure_ascii=False,
        ),
    )

    result = json.loads(
        classify_log_features_headless(
            '{"app_protocol":"ssh"}\n{"app_protocol":"dns"}',
            "json",
            "JSON",
            "category",
            json.dumps({"format": "json", "format_detail": "JSON"}, ensure_ascii=False),
            "",
        )
    )

    assert calls == []
    assert result["status"] == "FAILED"
    assert "category" in result["error"]
