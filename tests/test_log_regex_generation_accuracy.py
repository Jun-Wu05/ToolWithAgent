"""#290：正则生成确定性事实注入与失配样例反馈（全离线假件）。

夹具取自真实验收数据 KvHeadQiming.xlsx 的代表行：syslog PRI 后无空格、
类型标识为程序名型（IPS/AUDIT/RUN_INFO:）。
"""

import agent.tools.pipeline.log_header_processor as lhp

KV_LINES = [
    '<220>May 22 14:39:41 ips IPS: src_ip="120.55.65.26" dst_port=443',
    '<414>May 22 09:06:28 ips AUDIT: log_type=2 src_ip="172.18.34.208" result="0"',
    '<414>May 22 09:06:28 ips RUN_INFO: cpu=30 mem=50',
]
KV_LOGS = "\n".join(KV_LINES)

BAD_RESPONSE = (
    "r'<\\d+>\\s+\\w+\\s+\\d+\\s+\\d{2}:\\d{2}:\\d{2}\\s+\\S+\\s+\\S+:\\s+(.*)'"
)
GOOD_RESPONSE = (
    "r'<\\d+>\\w+\\s+\\d+\\s+\\d{2}:\\d{2}:\\d{2}\\s+\\S+\\s+\\S+:\\s*(.*)'"
)
GOOD_INNER = (
    "<\\d+>\\w+\\s+\\d+\\s+\\d{2}:\\d{2}:\\d{2}\\s+\\S+\\s+\\S+:\\s*(.*)"
)


def test观察事实_PRI后无空格被代码显式指出():
    facts = lhp._observe_kv_header_facts(KV_LINES, "IPS: ")
    assert "没有空格" in facts
    assert "禁止插入" in facts
    assert "HH:MM:SS" in facts
    assert "'IPS: '" in facts


def test观察事实_混合空格批要求可选空白():
    lines = ["<1>May 22 10:00:00 host app: a=1", "<2> May 22 10:00:01 host app: b=2"]
    facts = lhp._observe_kv_header_facts(lines)
    assert "可选空白" in facts


def test观察事实_无结构时返回空串():
    assert lhp._observe_kv_header_facts(["plain line without structure"]) == ""


def test失配样例块_包含真实行原文():
    block = lhp._failing_sample_block(GOOD_INNER.replace("\\w+", "\\w+X", 1), KV_LINES)
    assert "未能被上次正则匹配" in block
    assert "<220>May 22 14:39:41 ips IPS:" in block


def testKV正则生成_事实注入与失配行反馈闭环(monkeypatch):
    prompts: list[str] = []
    responses = [BAD_RESPONSE, GOOD_RESPONSE]

    def fake_call(prompt, **kwargs):
        prompts.append(prompt)
        return responses[len(prompts) - 1]

    monkeypatch.setattr(lhp, "_call_llm_direct", fake_call)
    result = lhp._generate_kv_feature_identifier(
        KV_LOGS, "=", header_end_marker="IPS: "
    )
    assert result == GOOD_INNER
    # 首次 prompt 注入代码观察事实
    assert "没有空格" in prompts[0]
    assert "'IPS: '" in prompts[0]
    # 重试反馈附带真实失配样例
    assert "未能被上次正则匹配" in prompts[1]
    assert "<220>May 22 14:39:41 ips IPS:" in prompts[1]


def test类型正则生成_程序名型闭环与失配反馈(monkeypatch):
    prompts: list[str] = []
    responses = [
        "r'([A-Za-z]+\\/\\d+\\/[A-Za-z0-9_]+)'",  # 斜杠路径模板（对程序名型错误）
        "r'([A-Za-z][A-Za-z0-9_]+):$'",            # 程序名型（正确）
    ]

    def fake_call(prompt, **kwargs):
        prompts.append(prompt)
        return responses[len(prompts) - 1]

    monkeypatch.setattr(lhp, "_call_llm_direct", fake_call)
    pattern = lhp._generate_header_logtype_regex(KV_LINES, "kv", "=")
    assert pattern.search("<220>May 22 14:39:41 ips IPS:").group(1) == "IPS"
    assert pattern.search("<414>May 22 09:06:28 ips AUDIT:").group(1) == "AUDIT"
    assert "未能被上次正则匹配" in prompts[1]
    assert "ips IPS:" in prompts[1]


def testPrompt资产_占位符与程序名型示例存在():
    from agent.prompts import (
        load_kv_feature_identifier_prompt,
        load_log_header_regex_identifier_prompt,
    )

    assert "{observed_facts}" in load_kv_feature_identifier_prompt()
    logtype_prompt = load_log_header_regex_identifier_prompt()
    assert "示例3" in logtype_prompt
    assert "程序名型" in logtype_prompt
    assert "禁止硬套斜杠路径模板" in logtype_prompt
