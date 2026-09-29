"""#294：KV body 校验删除形态假设 + header 边界以 body 正则为唯一权威。

夹具取自真实验收数据 KvHeadShanshi.xlsx 的代表行：冒号类 KV（tab=':'）、
@ 型类型标签、body 为自然语言或冒号键值（39 行中 0 行含 `=`）。
旧逻辑（kv_start 硬校验）对这类数据任何正则都必败，见 app_20260929_092258.log。
"""

from __future__ import annotations

import json
import re as _re

import agent.tools.log_pattern_store as log_pattern_store
import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.log_header_processor as lhp
from agent.tools.pipeline.log_header_processor import classify_header_features

SHANSHI_LINES = [
    '<188>May 14 16:19:32 SG-6000(root) 460c5408 Security@FLOW: Port scan attack:DROP! srcip 10.23.127.49. Occurred 38 times in the last 4 seconds',
    '<188>May 14 16:19:29 SG-6000(root) 460c5401 Security@FLOW: Port scan attack:DROP! trust::ethernet0/0 10.23.127.49->192.168.246.122',
    '<188>May 12 16:14:49 SG-6000(root) 460c5408 Security@FLOW: Port scan attack:DROP! srcip 10.23.127.49. Occurred 23 times in the last 5 seconds',
    '<188>Sep 15 11:22:27 1304410182005635(root) 46a49401 Threat@FLOW: From 172.30.133.106:63049(xethernet1/1) to 61.139.2.69:53(xethernet1/0), threat name: Botnet C&C domain, threat type: Malware, threat subtype: Trojan, App/Protocol: DNS, action: reset, defender: BOTNET DETECT, CC server: da.testiu.com, profile: lqy, threat severity: High, policy id: 1',
    '<188>Sep 15 11:22:26 1304410182005635(root) 46a49401 Threat@FLOW: From 172.30.133.106:40008(xethernet1/1) to 61.139.2.69:53(xethernet1/0), threat name: Botnet C&C domain, threat type: Malware, threat subtype: Trojan, App/Protocol: DNS, action: reset, defender: BOTNET DETECT, CC server: db.testyk.com, profile: lqy, threat severity: High, policy id: 1',
    '<188>Sep 15 11:22:26 1304410182005635(root) 46a49401 Threat@FLOW: From 172.30.133.106:65295(xethernet1/1) to 61.139.2.69:53(xethernet1/0), threat name: Botnet C&C domain, threat type: Malware, threat subtype: Trojan, App/Protocol: DNS, action: reset, defender: BOTNET DETECT, CC server: db.testyk.com, profile: lqy, threat severity: High, policy id: 1',
    '<188>Sep 15 11:10:02 1304410182005938(root) 421c0403 Event@MGMT: Admin user "hillstone" logined  through SSH, from 172.16.101.42:59286 to 172.16.106.242:22(TCP)',
    '<188>Sep 15 11:10:02 1304410182005938(root) 421c0403 Event@MGMT: Admin user "zhangxuesong" logined through https, from 172.24.252.178:5978 to 59.197.232.101:443(TCP)',
    '<188>Sep 15 11:10:02 1304410182005938(root) 421c0403 Event@MGMT: Admin user "hillstone" logined  through SSH, from 172.16.101.42:59286 to 172.16.106.242:22(TCP)',
    '<190>Aug 14 16:25:36 1204305150001830(root) 47040614 Event@AAA: receive authentication request from SCVPND module for user xiansvn.',
    '<190>Jul 18 16:18:18 261030KSA4647986(root) 47040611 Event@AAA: receive authentication request from LOGIN module for administrator admin.',
    '<190>Aug 14 16:25:36 1204305150001830(root) 47040614 Event@AAA: receive authentication request from SCVPND module for user xiansvn.',
]
SHANSHI_LOGS = "\n".join(SHANSHI_LINES)
SHANSHI_TAGS = ["Security@FLOW", "Threat@FLOW", "Event@MGMT", "Event@AAA"]
# 与 09-29 真实运行中 LLM 4 次生成一致的 body 正则（结构正确，旧校验必拒）
SHANSHI_BODY_REGEX = r"<\d+>\w+\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+\s+\S+:\s+(.*)"
SHANSHI_LOGTYPE_REGEX = r"([A-Za-z0-9_]+@[A-Za-z0-9_]+):$"


def _classify_shanshi(logs: str) -> dict:
    return json.loads(
        classify_header_features(
            logs,
            format_type="KV",
            format_detail="日志头+KV",
            header_end_marker=": ",
            format_info={"delimit": ",", "tab": ":"},
        )
    )


def _mock_llm(monkeypatch) -> dict:
    """打桩三处 LLM：body 正则 / 类型正则 / meaning 分批（沿用 #190 测试模式）。"""
    counters = {"body_calls": 0, "logtype_calls": 0, "meaning_calls": 0}

    def _header_llm(prompt, *args, **kwargs):
        if "日志头样例" in prompt:
            counters["logtype_calls"] += 1
            return f"r'{SHANSHI_LOGTYPE_REGEX}'"
        if "分隔符" in prompt:
            counters["body_calls"] += 1
            return f"r'{SHANSHI_BODY_REGEX}'"
        raise AssertionError(f"意外的日志头路径 LLM 调用: {prompt[:80]}")

    def _meaning_llm(prompt, *args, **kwargs):
        counters["meaning_calls"] += 1
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

    monkeypatch.setattr(lhp, "_call_llm_direct", _header_llm)
    monkeypatch.setattr(log_classifier, "_call_llm_direct", _meaning_llm)
    monkeypatch.setattr(
        log_pattern_store, "generate_structured_fingerprint", lambda **kw: ""
    )
    monkeypatch.setattr(log_pattern_store, "store_log_knowledge", lambda **kw: True)
    return counters


# ---------- 校验：自由文本 body 合法，坏正则家族仍被拒 ----------


def test_validate_接受自然语言body的正则() -> None:
    """山石 12 行全匹配、捕获完整 body：结构校验通过（旧 kv_start 校验必败）。"""
    is_valid, err_msg, body_length = lhp._validate_regex(
        SHANSHI_BODY_REGEX, SHANSHI_LINES, ":"
    )
    assert is_valid, err_msg
    assert body_length > 0


def test_validate_坏正则家族仍被结构校验拒绝() -> None:
    """PRI 捕获 / 整行捕获 / 空捕获 / 不命中，四类坏正则必须被拒。"""
    cases = [
        (r"(<\d+>\w+\s\w+\s\d+)", "body_contains_syslog_pri"),
        (r"(.*)", "body_is_full_line"),
        (r"()", "body_empty"),
        (r"^ZZZ(.*)$", "regex_no_match"),
    ]
    for regex, expected_reason in cases:
        is_valid, err_msg, _ = lhp._validate_regex(regex, SHANSHI_LINES, ":")
        assert not is_valid
        assert f"reason={expected_reason}" in err_msg, (regex, err_msg)


def test_validate_键值对body的既有行为不变() -> None:
    """Qiming 型 `=` 数据的正则仍通过（结构校验不引入新拒绝）。"""
    qiming = [
        '<220>May 22 14:39:41 ips IPS: src_ip="120.55.65.26" dst_port=443',
        '<414>May 22 09:06:28 ips AUDIT: log_type=2 src_ip="172.18.34.208"',
    ]
    regex = r"<\d+>\w+\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+:\s*(.*)"
    is_valid, err_msg, _ = lhp._validate_regex(regex, qiming, "=")
    assert is_valid, err_msg


# ---------- 边界权威：header = body 正则捕获组之前的文本 ----------


def test_kv_header_cut_保留类型标签且避开时间戳冒号() -> None:
    """冒号类数据 header 不再被时间戳冒号截断，@ 型标签完整保留。"""
    pattern = _re.compile(SHANSHI_BODY_REGEX)
    for line in SHANSHI_LINES:
        header = lhp._kv_header_cut(line, pattern, ":")
        tag = _re.search(r"(\S+@\w+): ", line).group(1)
        assert header.endswith(f"{tag}:"), header
        assert header.startswith("<1"), header


def test_select_kv_body_samples_按marker聚类保持样本多样性() -> None:
    """marker 聚类下 4 类标签都进入样例（分隔符猜测会把全部行塌缩成单簇）。"""
    samples = lhp._select_kv_body_samples(SHANSHI_LOGS, ":", ": ")
    assert len(samples) >= 4
    for tag in SHANSHI_TAGS:
        assert any(tag in s for s in samples), tag


# ---------- 失配反馈：携带上次捕获内容 ----------


def test_failing_sample_block_反馈上次捕获内容() -> None:
    """body 链路的失配反馈展示捕获内容与失败类别，重试才有新信息。"""
    block = lhp._failing_sample_block(
        r"(.*)",
        SHANSHI_LINES[:1],
        classify=lambda p, t: lhp._classify_body_error(p, t, ":"),
    )
    assert "未能被上次正则匹配" in block
    assert "body_is_full_line" in block
    assert "上次捕获" in block


def test_failing_sample_block_缺省判定保持类型正则链路行为() -> None:
    """无 classify 参数时维持 #290 的"未命中或捕获为空"语义。"""
    block = lhp._failing_sample_block(r"([A-Za-z]+/\d+/\w+)", ["ips IPS: src=1"])
    assert "ips IPS:" in block


# ---------- 端到端：山石 4 类完整标签全覆盖 ----------


def test_端到端_山石自由文本body_四类完整标签(monkeypatch) -> None:
    counters = _mock_llm(monkeypatch)

    result = _classify_shanshi(SHANSHI_LOGS)

    assert result["status"] == "SUCCESS", result.get("fail_reason")
    assert result["feature_count"] == 4
    assert result["covered_lines"] == len(SHANSHI_LINES)
    assert result["coverage"]["unmatched_lines"] == 0
    assert {d["logtype"] for d in result["classification_details"]} == set(SHANSHI_TAGS)
    assert counters["body_calls"] == 1
    assert counters["logtype_calls"] == 1
    details = {d["logtype"]: d for d in result["classification_details"]}
    # 自由文本 body 被完整提取为 real_samples，不再要求键值对形态
    assert details["Security@FLOW"]["real_samples"].startswith("Port scan attack")
    assert details["Threat@FLOW"]["real_samples"].startswith("From 172.30.133.106")
    assert details["Event@MGMT"]["real_samples"].startswith("Admin user")
    assert details["Event@AAA"]["real_samples"].startswith("receive authentication")


def test_端到端_body正则两轮失败仍严格FAILED(monkeypatch) -> None:
    """维持严格契约：body 正则两连败 → FAILED，无兜底（用户决策 #294）。"""
    monkeypatch.setattr(
        lhp, "_call_llm_direct", lambda *a, **kw: "r'ZZZ(.*)'"
    )

    result = _classify_shanshi(SHANSHI_LOGS)

    assert result["status"] == "FAILED"
    assert result["error"] == "kv_body_regex_validation_failed"
