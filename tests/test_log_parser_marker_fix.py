"""幻觉 header_end_marker 与特征路由的确定性防护（PR #121 修复）。

真实缺陷：Step 1 可能把字段分隔符输出为 header_end_marker（如 "; "），
剥离把每行第一个 KV 字段（常为用户指定的分类特征字段）当日志头删掉；
自动模式则因走头部聚类采样丢失类型覆盖。本文件用合成混合行（带 Alarm:
前缀与不带前缀两种形态）锁定四层机制修复。
"""

import json

import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.log_feature_locator as log_feature_locator
import agent.tools.pipeline.log_header_processor as log_header_processor
import agent.tools.pipeline.log_format_identifier as log_format_identifier
import agent.tools.pipeline.common.knowledge_store as knowledge_store
from agent.tools import classify_log_features_headless, identify_log_format_headless

EXPECTED_TYPES = {"AuthLog", "Mail", "SMTP Content", "Firewall drop"}

MIXED_KV_LINES = "\n".join(
    [
        "Type=AuthLog; Sip=10.10.34.127; User=zhangsan; Result=fail;",
        "Type=Mail; Source=172.16.102.12:49300; Action=1;",
        "Alarm: Type=SMTP Content; Src=1.2.3.4; Action=2;",
        "Alarm: Type=Firewall drop; Src=2.3.4.5; Action=3;",
    ]
)

# 模拟真实缺陷现场的格式识别输出：marker 恰为字段分隔符 "; "
HALLUCINATED_MARKER_INFO = json.dumps(
    {
        "format": "kv",
        "format_detail": "日志头+KV",
        "delimiter": ";",
        "kv_connector": "=",
        "delimit": ";",
        "tab": "=",
        "header_end_marker": "; ",
        "feature_field": "Type",
    },
    ensure_ascii=False,
)


def _mock_classifier_llm(
    monkeypatch,
    logtypes=EXPECTED_TYPES,
    feature_identifier_regex=r"^(.*)$",
):
    """固定分类 LLM 输出，并允许测试指定特征 body 正则。

    log_header_processor 模块有独立的 LLM 导入，需一并替换，避免测试触网。
    """

    def _fake_llm(prompt, *args, **kwargs):
        if "classification_details" in prompt:
            return json.dumps(
                {
                    "status": "SUCCESS",
                    "categorical_features": "Type",
                    "Diversion_method": "日志类型",
                    "log_format": "KV",
                    "feature_field": "Type",
                    "feature_count": len(logtypes),
                    "classification_details": [
                        {"logtype": item, "meaning": item} for item in sorted(logtypes)
                    ],
                },
                ensure_ascii=False,
            )
        return f"r'{feature_identifier_regex}'"

    monkeypatch.setattr(log_classifier, "_call_llm_direct", _fake_llm)
    monkeypatch.setattr(log_header_processor, "_call_llm_direct", _fake_llm)
    monkeypatch.setattr(knowledge_store, "store_classification_knowledge", lambda *a, **kw: True)


def test显式特征字段在幻觉marker下不剥离首字段(monkeypatch):
    """用户点名 Type 时，marker='; ' 不得剥掉行首的 Type 字段（回归 20260825 现场）。"""
    _mock_classifier_llm(monkeypatch)

    result = json.loads(
        classify_log_features_headless(
            MIXED_KV_LINES,
            "kv",
            "日志头+KV",
            "Type",
            HALLUCINATED_MARKER_INFO,
            "",
            feature_field_explicit=True,
        )
    )

    assert result["status"] == "SUCCESS"
    assert {d["logtype"] for d in result["classification_details"]} == EXPECTED_TYPES
    assert result["coverage"]["matched_lines"] == 4
    assert result["coverage"]["unmatched_lines"] == 0


def test自动模式特征键全行出现时跳过定位器直接聚合(monkeypatch):
    """特征键覆盖绝大多数行时跳过 Step 2a；无效 marker 仍由探针回退。"""
    _mock_classifier_llm(monkeypatch)
    locator_calls = []

    def _fake_locate(**kwargs):
        locator_calls.append(kwargs)
        return {
            "feature_location": "header",
            "feature_field": "__header__",
            "reason": "mock",
            "body_candidates": 0,
        }

    monkeypatch.setattr(log_feature_locator, "locate_feature", _fake_locate)

    result = json.loads(
        classify_log_features_headless(
            MIXED_KV_LINES,
            "kv",
            "日志头+KV",
            "Type",
            HALLUCINATED_MARKER_INFO,
            "",
        )
    )

    assert locator_calls == []
    assert result["status"] == "SUCCESS"
    assert {d["logtype"] for d in result["classification_details"]} == EXPECTED_TYPES
    assert result["coverage"]["matched_lines"] == 4


def test自动模式特征键低覆盖时仍走定位器路由(monkeypatch):
    """特征键不在行内（真头部特征场景）时保持现状：Step 2a 定位器照常参与。"""
    _mock_classifier_llm(monkeypatch)
    locator_calls = []

    def _fake_locate(**kwargs):
        locator_calls.append(kwargs)
        return {"feature_location": "header", "feature_field": "__header__", "reason": "mock"}

    monkeypatch.setattr(log_feature_locator, "locate_feature", _fake_locate)
    monkeypatch.setattr(
        log_header_processor,
        "classify_header_features",
        lambda **kwargs: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "在日志头中",
                "classification_details": [{"logtype": "header-type", "meaning": "头特征"}],
                "feature_identifier": "^(.*)$",
                "feature_count": 1,
            },
            ensure_ascii=False,
        ),
    )

    result = json.loads(
        classify_log_features_headless(
            "<134>Aug 24 10:00:00 host app[1]: traffic flow event",
            "kv",
            "日志头+KV",
            "log_type",
            json.dumps(
                {
                    "format": "kv",
                    "format_detail": "日志头+KV",
                    "delimit": " ",
                    "tab": "=",
                    "header_end_marker": ": ",
                },
                ensure_ascii=False,
            ),
            "",
        )
    )

    assert len(locator_calls) == 1
    assert result["status"] == "SUCCESS"


def testidentify输出marker与分隔符相同时被清空(monkeypatch):
    """marker 与字段分隔符相同（如 '; ' vs ';'）时在 Step 1 输出前清空。"""
    monkeypatch.setattr(
        log_format_identifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "format": "kv",
                "format_detail": "日志头+KV",
                "delimiter": ";",
                "confidence": 1.0,
                "kv_connector": "=",
                "kv_separator": "semicolon",
                "has_header": True,
                "header_end_marker": "; ",
                "feature_field": "Type",
            },
            ensure_ascii=False,
        ),
    )

    result = json.loads(identify_log_format_headless(MIXED_KV_LINES))

    assert result["header_end_marker"] == ""
    assert result["delimit"] == ";"


def testidentify输出真实日志头marker时保留(monkeypatch):
    """真实 syslog 头标记（如 ' - '）不等于分隔符，必须保留。"""
    monkeypatch.setattr(
        log_format_identifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "format": "kv",
                "format_detail": "日志头+KV",
                "delimiter": ";",
                "confidence": 1.0,
                "kv_connector": "=",
                "kv_separator": "semicolon",
                "has_header": True,
                "header_end_marker": " - ",
                "feature_field": "Type",
            },
            ensure_ascii=False,
        ),
    )

    result = json.loads(identify_log_format_headless(MIXED_KV_LINES))

    assert result["header_end_marker"] == " - "


def test剥离使特征键存在率骤降时回退不剥离(monkeypatch):
    """body 路径剥离后特征键行存在率大幅下降 → 判定 marker 无效，回退原始行。

    本测试直接驱动 KV 分类私有层（不经过路由层的行规范化）：
    回退后直开头行恢复可提取（修复前该场景 matched=0 且整体 FAILED）；
    Alarm 前缀行的完整提取由确定性路由的规范化负责（见前两个测试）。
    """
    _mock_classifier_llm(monkeypatch, logtypes={"AuthLog", "Mail"})

    result = json.loads(
        log_classifier._classify_kv_features(
            MIXED_KV_LINES,
            "kv",
            "日志头+KV",
            "Type",
            {"delimit": ";", "tab": "="},
            header_end_marker="; ",
        )
    )

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 2
    assert {d["logtype"] for d in result["classification_details"]} == {"AuthLog", "Mail"}
    assert all(
        detail["real_samples"].startswith("Type=")
        for detail in result["classification_details"]
    )


def test_header_kv_real_sample去头且不误截内嵌json(monkeypatch):
    """RFC5424-ish Header + KV 的真实样例应从 msg_type 开始。"""
    _mock_classifier_llm(
        monkeypatch,
        logtypes={"cloudwalker-suspicious-command"},
        feature_identifier_regex=r"^.*? - (.*)$",
    )
    body = (
        'msg_type="cloudwalker-suspicious-command" '
        'process_tree=[{"pname":"init","pid":1}] src_ip="10.0.0.1"'
    )
    line = (
        "<14>1 2026-04-14T05:57:55Z sensor01 cloudwalker 123 ID47"
        f" - {body}"
    )

    result = json.loads(
        classify_log_features_headless(
            line,
            "kv",
            "日志头+KV",
            "msg_type",
            json.dumps({"delimit": " ", "tab": "="}),
            " - ",
        )
    )

    detail = result["classification_details"][0]
    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 1
    assert result["coverage"]["unmatched_lines"] == 0
    assert detail["sample"] == line
    assert detail["real_samples"].startswith("msg_type=")
    assert detail["real_samples"] == body
    assert 'process_tree=[{"pname":"init","pid":1}]' in detail["real_samples"]


def test_header_kv分类运行日志不泄露原始样例(monkeypatch, caplog):
    """运行日志只能记录计数和结构信息，不得记录原始日志内容。"""
    secret = "S258LEAK"
    lines = (
        "<14>1 2026-04-14T05:57:55Z sensor01 app 123 ID47 - "
        f'msg_type="AuthLog" token="{secret}"'
    )
    _mock_classifier_llm(
        monkeypatch,
        logtypes={"AuthLog"},
        feature_identifier_regex=r"^.*? - (.*)$",
    )
    caplog.set_level("INFO", logger="log_parser_pipeline")

    result = json.loads(
        classify_log_features_headless(
            lines,
            "kv",
            "日志头+KV",
            "msg_type",
            json.dumps({"delimit": " ", "tab": "="}),
            " - ",
        )
    )

    assert result["status"] == "SUCCESS"
    assert result["coverage"]["matched_lines"] == 1
    assert result["coverage"]["unmatched_lines"] == 0
    assert secret not in caplog.text
