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


def _meaning_response(prompt: str) -> str:
    """meaning 分批的标准成功响应（按 prompt 中 aggregation_statistics 回显类型）。"""
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
        return _meaning_response(prompt)

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


# ---------- #296：marker 边界下限守卫（H3C出口防火墙20000条 回归） ----------

# 真实行取自 H3C出口防火墙20000条 .xlsx：年份后有 4 个 token
# （主机 %%前缀 VsysId:1 类型路径:），SSLVPN 两类标签冒号后无空格（无 ': '）。
H3C_LINES = [
    '<6> Sep 04 17:00:09 2026 OA_OUT_F5000 %%10 VsysId:1 TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG: Protocol(1001)=TCP;Application(1002)=https;Category(1174)=Protocol;SrcIPAddr(1003)=10.20.109.9;SrcPort(1004)=57160',
    '<6> Sep 04 17:00:09 2026 OA_OUT_F5000 %%10 VsysId:1 session/6/SESSION_IPV4_FLOW: Protocol(1001)=TCP;Application(1002)=https;Category(1174)=Protocol;SrcIPAddr(1003)=10.31.248.248;SrcPort(1004)=56912',
    '<6> Sep 04 17:00:09 2026 OA_OUT_F5000 %%10 VsysId:1 LB/6/OUTBOUND_LLB: SrcIPAddr(1003)=10.20.185.1;SrcPort(1004)=57802;DstIPAddr(1007)=116.130.220.34;DstPort(1008)=443',
    '<189> Sep 04 16:58:18 2026 OA_OUT_F5000 %%10 VsysId:1 SSLVPN/5/SSLVPN_USER_LOGIN:Context(1257)=SSLVPN; Username(1113)=91370113MABXRLNQ0E; LoginIPAddr(1247)=112.224.142.83',
    '<188> Sep 04 17:00:06 2026 OA_OUT_F5000 %%10 VsysId:1 WAF/4/WAF_IPV4_INTERZONE: Protocol(1001)=TCP; Application(1002)=baidu; SrcIPAddr(1003)=10.20.184.107; SrcPort(1004)=55590',
]
H3C_LOGS = "\n".join(H3C_LINES)
H3C_TYPES = [
    "TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG",
    "session/6/SESSION_IPV4_FLOW",
    "LB/6/OUTBOUND_LLB",
    "SSLVPN/5/SSLVPN_USER_LOGIN",
    "WAF/4/WAF_IPV4_INTERZONE",
]
# 用户验收运行（app_20260929_111822.log）中 LLM 实际生成的边界错位正则：
# 年份后只有 3 个 \S+，回溯后把 VsysId:1 的内部冒号当边界。
H3C_WRONG_REGEX = r"<\d+>\s+\w+\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\d{4}\s+\S+\s+\S+\s+\S+:\s*(.*)"
# 正确边界：4 个 token（%%前缀、标识:数字、类型路径）。
H3C_GOOD_REGEX = r"<\d+>\s+\w+\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\d{4}\s+\S+\s+%%\d+\s+\S+:\d+\s+\S+:\s*(.*)"
H3C_LOGTYPE_REGEX = r"([A-Za-z]+\/\d+\/[A-Za-z0-9_]+)"


def test_validate_边界切在头部中段被marker下限拒绝() -> None:
    """#296 回归现场：错位正则捕获 VsysId: 内部冒号之后，起点早于 marker。"""
    is_valid, err_msg, _ = lhp._validate_regex(
        H3C_WRONG_REGEX, H3C_LINES, "=", header_end_marker=": "
    )
    assert not is_valid
    assert "reason=body_starts_in_header" in err_msg


def test_validate_H3C正确4token正则通过() -> None:
    r"""正确边界（含 %%\d+ 与 标识:\d+ token）全部行通过。"""
    is_valid, err_msg, _ = lhp._validate_regex(
        H3C_GOOD_REGEX, H3C_LINES, "=", header_end_marker=": "
    )
    assert is_valid, err_msg


def test_validate_无marker行不设下限() -> None:
    """用户决策：marker 不出现的行不做连接符兜底（错位正则也放行，
    交给提示词与重试反馈）；锁定该语义防回归。"""
    sslvpn_only = [H3C_LINES[3]]
    is_valid, _, _ = lhp._validate_regex(H3C_WRONG_REGEX, sslvpn_only, "=")
    assert is_valid


def test_validate_山石时间戳冒号切法被marker下限拒绝() -> None:
    """守卫与分隔符无关：冒号世界（tab=':'）切在时间戳冒号的正则同样被拒。"""
    ts_cut_regex = r"<\d+>\w+\s+\d+\s+\d{2}:(.*)"
    is_valid, err_msg, _ = lhp._validate_regex(
        ts_cut_regex, SHANSHI_LINES, ":", header_end_marker=": "
    )
    assert not is_valid
    assert "reason=body_starts_in_header" in err_msg


def test_failing_sample_block_边界错位反馈上次捕获() -> None:
    """重试反馈携带捕获内容，LLM 可据此发现捕到了头部残片。"""
    block = lhp._failing_sample_block(
        H3C_WRONG_REGEX,
        H3C_LINES[:1],
        classify=lambda p, t: lhp._classify_body_error(p, t, "=", ": "),
    )
    assert "body_starts_in_header" in block
    assert "上次捕获 `1 TRAFFICLOG" in block


def test_select_kv_body_samples_无marker行退回extract切分() -> None:
    """H3C 混合批：有 ': ' 的行按 marker 分簇、SSLVPN 行退 extract 切分，
    5 类各成一簇（marker-only 聚类会把 SSLVPN 行退化为整行键）。"""
    samples = lhp._select_kv_body_samples(H3C_LOGS, "=", ": ")
    assert len(samples) == len(H3C_LINES)
    for tag in H3C_TYPES:
        assert any(tag in s for s in samples), tag


def test_prompt资产_示例3存在() -> None:
    """#296：恢复 24f29bc 的 H3C 专项 few-shot（含 %%前缀/标识:数字/年份）。"""
    from agent.prompts import load_kv_feature_identifier_prompt

    prompt = load_kv_feature_identifier_prompt()
    assert "示例3" in prompt
    assert "%%\\d+" in prompt
    assert "VsysId" in prompt
    assert "\\d{4}" in prompt


def test_端到端_H3C边界错位_反馈重试后成功(monkeypatch) -> None:
    """复刻用户失败路径：首轮错位正则被拒 → 反馈携带上次捕获 → 修正通过，
    5 类全路径类型、全覆盖（#296 修复前：错位被静默接受、聚成单类型伪 SUCCESS）。"""
    prompts: list[str] = []
    body_responses = [f"r'{H3C_WRONG_REGEX}'", f"r'{H3C_GOOD_REGEX}'"]

    def _header_llm(prompt, *args, **kwargs):
        prompts.append(prompt)
        if "日志头样例" in prompt:
            return f"r'{H3C_LOGTYPE_REGEX}'"
        if "分隔符" in prompt:
            return body_responses.pop(0)
        raise AssertionError(f"意外的日志头路径 LLM 调用: {prompt[:80]}")

    monkeypatch.setattr(lhp, "_call_llm_direct", _header_llm)
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: _meaning_response(a[0] if a else ""),
    )
    monkeypatch.setattr(
        log_pattern_store, "generate_structured_fingerprint", lambda **kw: ""
    )
    monkeypatch.setattr(log_pattern_store, "store_log_knowledge", lambda **kw: True)

    result = json.loads(
        lhp.classify_header_features(
            H3C_LOGS,
            format_type="KV",
            format_detail="日志头+KV",
            header_end_marker=": ",
            format_info={"delimit": ";", "tab": "="},
        )
    )

    assert result["status"] == "SUCCESS", result.get("fail_reason")
    assert result["feature_count"] == 5
    assert result["covered_lines"] == len(H3C_LINES)
    assert {d["logtype"] for d in result["classification_details"]} == set(H3C_TYPES)
    # 重试反馈携带边界错位类别与上次捕获内容
    assert "body_starts_in_header" in prompts[1]
    assert "上次捕获 `1 TRAFFICLOG" in prompts[1]
    details = {d["logtype"]: d for d in result["classification_details"]}
    assert details["TRAFFICLOG/6/TRAFFICLOG_IPV4_LOG"]["real_samples"].startswith(
        "Protocol(1001)=TCP"
    )
    assert details["SSLVPN/5/SSLVPN_USER_LOGIN"]["real_samples"].startswith(
        "Context(1257)=SSLVPN"
    )


# ---------- #298：生成门过半覆盖，异构行交由 unmatched 降级 ----------

# KvHeadH3C.xlsx 中的管道异构行（0.95%，无 syslog 头与类型标签）。
PIPE_LINE = "H3C|*0|*0|*10.10.88.5|*|*2026-06-11 15:55:08|*V7.1.064|*34"


def _h3c_headers() -> list[str]:
    body_pattern = _re.compile(H3C_GOOD_REGEX)
    return [lhp._kv_header_cut(line, body_pattern, "=") for line in H3C_LINES]


def test_validate_logtype_过半覆盖被接受_异构样本放行() -> None:
    """5/6 命中（唯一未命中是无类型标签的管道行）→ 接受（#298 前必拒）。"""
    headers = _h3c_headers() + [PIPE_LINE]
    is_valid, err_msg, _ = lhp._validate_logtype_regex(H3C_LOGTYPE_REGEX, headers)
    assert is_valid, err_msg


def test_validate_logtype_不过半被拒() -> None:
    """只命中 1/6（未抓住主导结构）→ 拒绝并进入重试。"""
    narrow_regex = r"(TRAFFICLOG\/6\/[A-Za-z0-9_]+)"
    headers = _h3c_headers() + [PIPE_LINE]
    is_valid, err_msg, _ = lhp._validate_logtype_regex(narrow_regex, headers)
    assert not is_valid
    assert "matched=1; total=6" in err_msg


def test_端到端_混合批异构行进unmatched降级PARTIAL(monkeypatch) -> None:
    """复刻 KvHeadH3C：5 行 syslog+KV + 1 行管道异构 → 类型正则 5/6 过半
    接受 → 全量扫描管道行 unmatched → PARTIAL + "1 行未匹配任何类型"（#298 前
    生成门 100% 卡死整批 FAILED，unmatched 计数从未执行）。"""
    mixed_logs = "\n".join(H3C_LINES + [PIPE_LINE])

    def _header_llm(prompt, *args, **kwargs):
        if "日志头样例" in prompt:
            return f"r'{H3C_LOGTYPE_REGEX}'"
        if "分隔符" in prompt:
            return f"r'{H3C_GOOD_REGEX}'"
        raise AssertionError(f"意外的日志头路径 LLM 调用: {prompt[:80]}")

    monkeypatch.setattr(lhp, "_call_llm_direct", _header_llm)
    monkeypatch.setattr(
        log_classifier, "_call_llm_direct", lambda *a, **kw: _meaning_response(a[0] if a else "")
    )
    monkeypatch.setattr(
        log_pattern_store, "generate_structured_fingerprint", lambda **kw: ""
    )
    monkeypatch.setattr(log_pattern_store, "store_log_knowledge", lambda **kw: True)

    result = json.loads(
        lhp.classify_header_features(
            mixed_logs,
            format_type="KV",
            format_detail="日志头+KV",
            header_end_marker=": ",
            format_info={"delimit": ";", "tab": "="},
        )
    )

    assert result["status"] == "PARTIAL"
    assert result["feature_count"] == 5
    assert result["covered_lines"] == 5
    assert result["coverage"]["unmatched_lines"] == 1
    assert any("|" in s for s in result["coverage"]["unmatched_samples"])
    assert "1 行未匹配任何类型" in result["fail_reason"]
    assert {d["logtype"] for d in result["classification_details"]} == set(H3C_TYPES)


def test_端到端_类型正则不过半两轮仍FAILED(monkeypatch) -> None:
    """未抓住主导结构的正则：重试一次后仍不过半 → FAILED（严格契约不变）。"""
    narrow = f"r'(TRAFFICLOG\\/6\\/[A-Za-z0-9_]+)'"

    def _header_llm(prompt, *args, **kwargs):
        if "日志头样例" in prompt:
            return narrow
        if "分隔符" in prompt:
            return f"r'{H3C_GOOD_REGEX}'"
        raise AssertionError(f"意外的日志头路径 LLM 调用: {prompt[:80]}")

    monkeypatch.setattr(lhp, "_call_llm_direct", _header_llm)

    result = json.loads(
        lhp.classify_header_features(
            "\n".join(H3C_LINES + [PIPE_LINE]),
            format_type="KV",
            format_detail="日志头+KV",
            header_end_marker=": ",
            format_info={"delimit": ";", "tab": "="},
        )
    )

    assert result["status"] == "FAILED"
    assert result["error"] == "header_logtype_regex_validation_failed"
