"""日志格式识别一致性校验回归（#22）。"""

import json


RFC5424_KV_LOGS = (
    '<14>1 2026-04-14T05:57:55Z host app 1 event - msg_type="type-a" host_ip="192.0.2.10"\n'
    '<14>1 2026-04-14T05:57:50Z host app 1 event - msg_type="type-b" host_ip="192.0.2.11"'
)


def test_rfc5424头加kv_body被误报json时纠正为kv(monkeypatch):
    """LLM 把 RFC5424 头+KV body 误报为 JSON 时，确定性一致性校验纠正为 KV（回归 #22）。"""
    import agent.tools.pipeline.log_format_identifier as identifier

    monkeypatch.setattr(
        identifier,
        "_call_llm_direct",
        lambda *a, **k: json.dumps(
            {
                "format": "json",
                "format_detail": "日志头+JSON",
                "header_end_marker": " - ",
                "has_header": True,
                "feature_field": "msg_type",
                "confidence": 0.8,
            },
            ensure_ascii=False,
        ),
    )

    out = json.loads(identifier._do_identify_log_format(RFC5424_KV_LOGS))

    assert out["format"] == "KV"
    assert out["format_detail"] == "日志头+KV"
    assert out["header_end_marker"] == " - "
    assert out["tab"] == "="
    assert out["delimit"] == "space"


def test真实json_body不被误纠正为kv(monkeypatch):
    """body 含真实 JSON 对象时保持 JSON，不被一致性校验误纠（回归 #22 反例）。"""
    import agent.tools.pipeline.log_format_identifier as identifier

    monkeypatch.setattr(
        identifier,
        "_call_llm_direct",
        lambda *a, **k: json.dumps(
            {
                "format": "json",
                "format_detail": "JSON",
                "header_end_marker": "",
                "has_header": False,
                "feature_field": "msg_type",
                "confidence": 0.9,
            },
            ensure_ascii=False,
        ),
    )
    logs = '{"msg_type": "type-a", "src": "10.0.0.1"}\n{"msg_type": "type-b", "src": "10.0.0.2"}'

    out = json.loads(identifier._do_identify_log_format(logs))

    assert out["format"] == "JSON"


def test纠正后的kv分隔符可使聚合器匹配全部行():
    """一致性校验纠正为 KV 后，KvExtractor 用检测到的分隔符聚合 msg_type 全部行（回归 #22 seam）。"""
    from agent.tools.pipeline.common.json_utils import strip_header_to_body
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    lines = RFC5424_KV_LOGS.split("\n")
    bodies = [strip_header_to_body(line, " - ", is_json=False) for line in lines]
    aggregation = KvExtractor(field_delimit=" ", kv_delimit="=").extract_and_aggregate(
        "\n".join(bodies), "msg_type"
    )

    assert aggregation["matched_lines"] == 2
    assert set(aggregation["values"].keys()) == {"type-a", "type-b"}


def test外层json内嵌kv文本时纠正格式并限定特征字段重试(monkeypatch):
    """整行可解析为 JSON 时，字符串值内的 Key : Value 不得改变外层格式。"""
    import agent.tools.pipeline.log_format_identifier as identifier

    logs = "\n".join(
        json.dumps(
            {
                "logType": log_type,
                "value": f"Index : {index} EventID : {event_id} Source : Windows",
            }
        )
        for index, event_id, log_type in (
            (1, 6417, "security"),
            (2, 4624, "audit"),
        )
    )
    responses = iter(
        [
            json.dumps(
                {
                    "format": "kv",
                    "format_detail": "纯KV",
                    "kv_connector": ":",
                    "kv_separator": "space",
                    "has_header": False,
                    "feature_field": "EventID",
                    "feature_location": "body",
                }
            ),
            json.dumps(
                {
                    "format": "json",
                    "format_detail": "JSON",
                    "has_header": False,
                    "feature_field": "logType",
                    "feature_location": "body",
                }
            ),
        ]
    )
    prompts = []

    def fake_call(prompt, **_kwargs):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(identifier, "_call_llm_direct", fake_call)

    out = json.loads(identifier._do_identify_log_format(logs))

    assert out["format"] == "JSON"
    assert out["format_detail"] == "JSON"
    assert out["feature_field"] == "logType"
    assert len(prompts) == 2
    assert "EventID" not in prompts[1].split("可选外层 JSON 字段：", 1)[1]
    assert "logType" in prompts[1]


def test_syslog头加外层json内嵌kv文本时保留json格式(monkeypatch):
    """Syslog 头后的完整 JSON body 优先于字符串值的 KV 外观。"""
    import agent.tools.pipeline.log_format_identifier as identifier

    logs = "\n".join(
        f"<14>1 2026-09-15T12:00:0{i}Z host app 1 event - "
        + json.dumps(
            {
                "logType": log_type,
                "value": f"Index : {i} EventID : {event_id} Source : Windows",
            }
        )
        for i, event_id, log_type in (
            (1, 6417, "security"),
            (2, 4624, "audit"),
        )
    )
    responses = iter(
        [
            json.dumps(
                {
                    "format": "kv",
                    "format_detail": "日志头+KV",
                    "kv_connector": ":",
                    "kv_separator": "space",
                    "has_header": True,
                    "header_end_marker": " - ",
                    "feature_field": "EventID",
                    "feature_location": "body",
                }
            ),
            json.dumps({"format": "json", "feature_field": "logType"}),
        ]
    )
    monkeypatch.setattr(identifier, "_call_llm_direct", lambda *_a, **_k: next(responses))

    out = json.loads(identifier._do_identify_log_format(logs))

    assert out["format"] == "JSON"
    assert out["format_detail"] == "日志头+JSON"
    assert out["has_header"] is True
    assert out["header_end_marker"] == " - "
    assert out["feature_field"] == "logType"


def test_kv值中仅含局部json片段时保持kv(monkeypatch):
    """只有完整 body 可解析为 JSON 对象时才允许 KV→JSON 纠正。"""
    import agent.tools.pipeline.log_format_identifier as identifier

    logs = 'type=a payload={"event":"x"}\ntype=b payload={"event":"y"}'
    monkeypatch.setattr(
        identifier,
        "_call_llm_direct",
        lambda *_a, **_k: json.dumps(
            {
                "format": "kv",
                "format_detail": "KV",
                "kv_connector": "=",
                "kv_separator": "space",
                "has_header": False,
                "feature_field": "type",
                "feature_location": "body",
            }
        ),
    )

    out = json.loads(identifier._do_identify_log_format(logs))

    assert out["format"] == "KV"
    assert out["feature_field"] == "type"


def test外层json特征字段有界重试仍无效时明确失败(monkeypatch):
    """两次都选到字符串内容中的名称时，不得继续伪装成可用格式结果。"""
    import agent.tools.pipeline.log_format_identifier as identifier

    logs = json.dumps(
        {
            "logType": "security",
            "value": "Index : 1 EventID : 6417 Source : Windows",
        }
    )
    responses = iter(
        [
            json.dumps({"format": "kv", "feature_field": "EventID"}),
            json.dumps({"format": "json", "feature_field": "EventID"}),
        ]
    )
    monkeypatch.setattr(identifier, "_call_llm_direct", lambda *_a, **_k: next(responses))

    out = json.loads(identifier._do_identify_log_format(logs))

    assert out["format"] == "UNKNOWN"
    assert out["status"] == "UNSUPPORTED"
    assert out["feature_field"] == ""
    assert "外层 JSON 字段" in out["error"]
