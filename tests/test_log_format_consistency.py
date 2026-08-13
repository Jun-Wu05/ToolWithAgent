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
