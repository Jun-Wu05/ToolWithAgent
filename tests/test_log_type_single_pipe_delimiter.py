"""单竖线 KV 分隔符全链路一致与零匹配数据裁决回归（#259）。

真实缺陷：提示词词汇表把单 `|` 与 `||` 塌缩为代码词 pipe，Step 1 的
separator_map 又把 pipe 硬编码映射为 `||`，LLM 原样 delimiter 字段无人消费；
执行/聚合按 `||` 构造锚点后非首键特征字段永不匹配 → matched=0；
分类器 FAILED 字典又被适配器"非空 dict"检查放行，报 SUCCESS + 空产物。

修复原则："LLM 提议、数据裁决"——
1. Step 1 保留 pipe 族的原始 delimiter 观察，不再塌缩；
2. Step 2 零匹配时候选分隔符集（声称值 + LLM 原样 + 常见符号 + 数据派生）
   逐个用特征键行覆盖率探针裁决，取最高且达阈值者重试聚合；
3. 适配器拦截 status=FAILED 的分类结果，不再提交空产物。
"""

import json

import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.log_format_identifier as log_format_identifier
import agent.tools.pipeline.log_header_processor as log_header_processor
import agent.tools.pipeline.common.knowledge_store as knowledge_store
from agent.tools import classify_log_features_headless, identify_log_format_headless

# 奇安信语料形态的最小脱敏夹具：纯 KV、单竖线分隔、name 为分类特征字段
SINGLE_PIPE_LOGS = "\n".join(
    [
        "SIP=10.1.1.1|name=auth|dip=2.2.2.2",
        "SIP=10.1.1.2|name=mail|dip=2.2.2.3",
        "SIP=10.1.1.3|name=auth|dip=2.2.2.4",
    ]
)
TILDE_LOGS = "\n".join(
    [
        "id=1~name=gateway~act=allow",
        "id=2~name=proxy~act=deny",
        "id=3~name=gateway~act=allow",
    ]
)
DOUBLE_PIPE_LOGS = "\n".join(
    [
        "SIP=10.1.1.1||name=auth||dip=2.2.2.2",
        "SIP=10.1.1.2||name=mail||dip=2.2.2.3",
        "SIP=10.1.1.3||name=auth||dip=2.2.2.4",
    ]
)
SPACE_LOGS = "\n".join(
    [
        "SIP=10.1.1.1 name=auth dip=2.2.2.2",
        "SIP=10.1.1.2 name=mail dip=2.2.2.3",
        "SIP=10.1.1.3 name=auth dip=2.2.2.4",
    ]
)
COMMA_LOGS = "\n".join(
    [
        "SIP=10.1.1.1,name=auth,dip=2.2.2.2",
        "SIP=10.1.1.2,name=mail,dip=2.2.2.3",
        "SIP=10.1.1.3,name=auth,dip=2.2.2.4",
    ]
)
SEMICOLON_LOGS = "\n".join(
    [
        "SIP=10.1.1.1;name=auth;dip=2.2.2.2",
        "SIP=10.1.1.2;name=mail;dip=2.2.2.3",
        "SIP=10.1.1.3;name=auth;dip=2.2.2.4",
    ]
)


def _mock_classifier_llm(monkeypatch, logtypes):
    """固定分类 LLM 输出；非分类提示词（特征正则生成）返回全行正则。

    log_header_processor 模块有独立的 LLM 导入，需一并替换，避免测试触网。
    """

    def _fake_llm(prompt, *args, **kwargs):
        if "classification_details" in prompt:
            return json.dumps(
                {
                    "status": "SUCCESS",
                    "categorical_features": "name",
                    "Diversion_method": "日志类型",
                    "log_format": "KV",
                    "feature_field": "name",
                    "feature_count": len(logtypes),
                    "classification_details": [
                        {"logtype": item, "meaning": item} for item in sorted(logtypes)
                    ],
                },
                ensure_ascii=False,
            )
        return "r'^(.*)$'"

    monkeypatch.setattr(log_classifier, "_call_llm_direct", _fake_llm)
    monkeypatch.setattr(log_header_processor, "_call_llm_direct", _fake_llm)
    monkeypatch.setattr(
        knowledge_store, "store_classification_knowledge", lambda *a, **kw: True
    )


def _identify(monkeypatch, logs, parsed):
    monkeypatch.setattr(
        log_format_identifier,
        "_call_llm_direct",
        lambda *_a, **_k: json.dumps(parsed, ensure_ascii=False),
    )
    return json.loads(log_format_identifier._do_identify_log_format(logs))


def _classify_kv(monkeypatch, logs, format_info, feature_field="name"):
    _mock_classifier_llm(monkeypatch, {"auth", "mail", "gateway", "proxy"})
    return json.loads(
        log_classifier._classify_kv_features(
            logs_str=logs,
            format_type="kv",
            format_detail="KV",
            feature_field=feature_field,
            format_info=format_info,
            header_end_marker="",
        )
    )


# ---------------------------------------------------------------------------
# Step 1：词表归一化不销毁 LLM 的精确观察
# ---------------------------------------------------------------------------

def test_词表pipe族保留llm原始单竖线delimiter(monkeypatch):
    """kv_separator=pipe 且 LLM 原样 delimiter='|' 时，delimit 保持 '|' 不塌缩为 '||'。"""
    out = _identify(
        monkeypatch,
        SINGLE_PIPE_LOGS,
        {
            "format": "kv",
            "format_detail": "KV",
            "delimiter": "|",
            "kv_connector": "=",
            "kv_separator": "pipe",
            "has_header": False,
            "feature_field": "name",
            "feature_location": "body",
        },
    )

    assert out["delimit"] == "|"


def test_词表pipe族保留llm原始双竖线delimiter(monkeypatch):
    """kv_separator=pipe 且原样 delimiter='||' 时，delimit 保持 '||'。"""
    out = _identify(
        monkeypatch,
        DOUBLE_PIPE_LOGS,
        {
            "format": "kv",
            "format_detail": "KV",
            "delimiter": "||",
            "kv_connector": "=",
            "kv_separator": "pipe",
            "has_header": False,
            "feature_field": "name",
            "feature_location": "body",
        },
    )

    assert out["delimit"] == "||"


def test_词表pipe族无原始delimiter时维持双竖线(monkeypatch):
    """LLM 未返回原样 delimiter 时，pipe 族维持既有 '||' 归一化（兼容）。"""
    out = _identify(
        monkeypatch,
        SINGLE_PIPE_LOGS,
        {
            "format": "kv",
            "format_detail": "KV",
            "kv_connector": "=",
            "kv_separator": "pipe",
            "has_header": False,
            "feature_field": "name",
            "feature_location": "body",
        },
    )

    assert out["delimit"] == "||"


def test_误报json的单竖线kv被一致性探测纠正(monkeypatch):
    """LLM 误报 JSON 且 body 为单竖线 KV 时，一致性探测纠正为 KV 且 delimit='|'。"""
    out = _identify(
        monkeypatch,
        SINGLE_PIPE_LOGS,
        {
            "format": "json",
            "format_detail": "JSON",
            "has_header": False,
            "feature_field": "name",
            "confidence": 0.8,
        },
    )

    assert out["format"] == "KV"
    assert out["delimit"] == "|"


# ---------------------------------------------------------------------------
# Step 2：零匹配时候选分隔符数据裁决
# ---------------------------------------------------------------------------

def test_单竖线kv声称双竖线时探针自愈(monkeypatch):
    """声称 delimit='||' 零匹配时，探针从候选集选出 '|' 并自愈聚合。"""
    result = _classify_kv(monkeypatch, SINGLE_PIPE_LOGS, {"delimit": "||", "tab": "="})

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 3
    assert {d["logtype"] for d in result["classification_details"]} == {"auth", "mail"}


def test_新奇分隔符llm未描述时数据派生自愈(monkeypatch):
    """'~' 分隔、LLM 未描述且不在常见符号集：数据派生候选经探针裁决自愈。"""
    result = _classify_kv(monkeypatch, TILDE_LOGS, {"delimit": "||", "tab": "="})

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 3
    assert {d["logtype"] for d in result["classification_details"]} == {"gateway", "proxy"}


def test_候选全不达阈值时明确失败(monkeypatch):
    """所有候选分隔符的特征键覆盖率都不达阈值时，返回稳定 FAILED 而非空产物。"""
    logs = "\n".join(["hello world foo", "bar baz qux", "quux corge grault"])

    result = _classify_kv(monkeypatch, logs, {"delimit": "||", "tab": "="})

    assert result["status"] == "FAILED"
    assert "未找到字段 'name' 的有效值" in result["error"]


def test_端到端单竖线全链路name非空(monkeypatch):
    """Step 1 识别出的单竖线分隔符在 Step 2 执行链路保持一致，name 提取非空。"""
    monkeypatch.setattr(
        log_format_identifier,
        "_call_llm_direct",
        lambda *_a, **_k: json.dumps(
            {
                "format": "kv",
                "format_detail": "KV",
                "delimiter": "|",
                "kv_connector": "=",
                "kv_separator": "pipe",
                "has_header": False,
                "feature_field": "name",
                "feature_location": "body",
            },
            ensure_ascii=False,
        ),
    )
    _mock_classifier_llm(monkeypatch, {"auth", "mail"})

    format_text = identify_log_format_headless(SINGLE_PIPE_LOGS)
    assert json.loads(format_text)["delimit"] == "|"

    result = json.loads(
        classify_log_features_headless(
            SINGLE_PIPE_LOGS,
            "kv",
            "KV",
            "name",
            format_text,
            "",
            feature_field_explicit=True,
        )
    )

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 3
    assert {d["logtype"] for d in result["classification_details"]} == {"auth", "mail"}


def test_既有分隔符行为零回归(monkeypatch):
    """双竖线/空格/逗号/分号与已保真的单竖线：声称正确时首次聚合即命中。"""
    cases = [
        (DOUBLE_PIPE_LOGS, "||"),
        (SINGLE_PIPE_LOGS, "|"),
        (SPACE_LOGS, "space"),
        (COMMA_LOGS, ","),
        (SEMICOLON_LOGS, ";"),
    ]
    for logs, delimit in cases:
        result = _classify_kv(monkeypatch, logs, {"delimit": delimit, "tab": "="})

        assert result["status"] == "SUCCESS", f"delimit={delimit!r} 应保持既有行为"
        assert result["coverage"]["matched_lines"] == 3
        assert {d["logtype"] for d in result["classification_details"]} == {"auth", "mail"}


def test_派生候选来自高频结构符号并排除结构字符():
    """派生通道只提数据中高频出现的结构符号，排除 = : . - 等结构/噪声字符。"""
    derived = log_classifier._derive_separator_candidates(TILDE_LOGS)
    assert derived == ["~"]

    derived_pipe = log_classifier._derive_separator_candidates(SINGLE_PIPE_LOGS)
    assert derived_pipe == ["|"]

    noisy = "\n".join(
        [
            "ts=2026-09-22T10:00:00Z|name=auth|src=1.2.3.4",
            "ts=2026-09-22T10:00:01Z|name=mail|src=1.2.3.5",
            "ts=2026-09-22T10:00:02Z|name=auth|src=1.2.3.6",
        ]
    )
    derived_noisy = log_classifier._derive_separator_candidates(noisy)
    assert derived_noisy == ["|"]
    for structural in (":", ".", "-", "="):
        assert structural not in derived_noisy


# ---------------------------------------------------------------------------
# 默认分隔符零匹配时的对称备选重试（#382 钉桩：先锁现行为再收口实现）
# ---------------------------------------------------------------------------

COLON_KV_LOGS = "\n".join(
    [
        "name:auth sip:1.1.1.1",
        "name:mail sip:2.2.2.2",
        "name:auth sip:3.3.3.3",
    ]
)
EQUALS_KV_LOGS = "\n".join(
    [
        "name=auth sip=1.1.1.1",
        "name=mail sip=2.2.2.2",
        "name=auth sip=3.3.3.3",
    ]
)


def test_空格等号零匹配时冒号备选成功且回显修正分隔符(monkeypatch):
    """声称 tab='=' 但日志实为冒号 KV：备选 ':' 重试成功，analysis.tab 回显修正值。"""
    result = _classify_kv(monkeypatch, COLON_KV_LOGS, {"delimit": " ", "tab": "="})

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 3
    assert result["analysis"]["tab"] == ":"
    assert {d["logtype"] for d in result["classification_details"]} == {"auth", "mail"}


def test_空格冒号零匹配时等号备选成功且回显修正分隔符(monkeypatch):
    """声称 tab=':' 但日志实为等号 KV：备选 '=' 重试成功，analysis.tab 回显修正值。"""
    result = _classify_kv(monkeypatch, EQUALS_KV_LOGS, {"delimit": " ", "tab": ":"})

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 3
    assert result["analysis"]["tab"] == "="
    assert {d["logtype"] for d in result["classification_details"]} == {"auth", "mail"}
