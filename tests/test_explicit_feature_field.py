"""显式分类特征字段（feature_field）与 Step 2a 定位器的交互契约。

用户点名「作为日志类型」的日志体键由显式意图传入，定位器不得改写或改道；
自动探测模式保持定位器修正的现状行为（PRD #110「适配器显式优先」）。
"""

import json

import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.log_feature_locator as log_feature_locator
import agent.tools.pipeline.common.knowledge_store as knowledge_store
from agent.tools import classify_log_features_headless


HEADER_KV_LOGS = (
    "<134>Aug 24 10:00:00 host app: category=attack src=10.0.0.1\n"
    "<134>Aug 24 10:00:01 host app: category=scan src=10.0.0.2"
)
FORMAT_INFO = json.dumps(
    {"format": "kv", "format_detail": "日志头+KV", "delimit": " ", "tab": "="},
    ensure_ascii=False,
)


def _locate_tries_other_field(**kwargs):
    """模拟 Step 2a 定位器把特征字段改写为 other_field 的修正结果。"""
    return {
        "feature_location": "body",
        "feature_field": "other_field",
        "reason": "mock 定位器试图改写字段",
        "body_candidates": 0,
    }


def test显式分类特征字段压制定位器修正(monkeypatch):
    """用户点名 category 作为日志类型时，定位器的 other_field 修正不得生效。"""
    monkeypatch.setattr(log_feature_locator, "locate_feature", _locate_tries_other_field)
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "category",
                "Diversion_method": "日志类型",
                "log_format": "KV",
                "feature_field": "category",
                "feature_count": 2,
                "classification_details": [
                    {"logtype": "attack", "meaning": "攻击"},
                    {"logtype": "scan", "meaning": "扫描"},
                ],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(knowledge_store, "store_classification_knowledge", lambda *a, **kw: True)

    result = json.loads(
        classify_log_features_headless(
            HEADER_KV_LOGS,
            "kv",
            "日志头+KV",
            "category",
            FORMAT_INFO,
            "",
            feature_field_explicit=True,
        )
    )

    assert result["status"] == "SUCCESS"
    assert result["feature_field"] == "category"
    assert {detail["logtype"] for detail in result["classification_details"]} == {"attack", "scan"}


def test纯KV显式特征字段format_info为空时不抛NameError(monkeypatch):
    """format_info 空串解析为 None 时，纯 KV 聚合必须回退默认分隔符而非 NameError（#179）。"""
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "category",
                "Diversion_method": "日志类型",
                "log_format": "KV",
                "feature_field": "category",
                "feature_count": 2,
                "classification_details": [
                    {"logtype": "attack", "meaning": "攻击"},
                    {"logtype": "scan", "meaning": "扫描"},
                ],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(knowledge_store, "store_classification_knowledge", lambda *a, **kw: True)

    result = json.loads(
        classify_log_features_headless(
            "category=attack src=10.0.0.1\ncategory=scan src=10.0.0.2",
            "kv",
            "KV",
            "category",
            "",
            "",
            feature_field_explicit=True,
        )
    )

    assert result["status"] == "SUCCESS"
    assert {detail["logtype"] for detail in result["classification_details"]} == {"attack", "scan"}


def test未显式指定时定位器修正仍然生效(monkeypatch):
    """自动探测模式保持现状：特征键不在行内时定位器修正后按修正字段聚合失败。

    注意：特征键作为日志体键覆盖绝大多数行的场景现在走确定性路由
    （见 test_log_parser_marker_fix），定位器修正只发生在键不在行内时。
    """
    monkeypatch.setattr(log_feature_locator, "locate_feature", _locate_tries_other_field)

    result = json.loads(
        classify_log_features_headless(
            # 行内不含 category 键（真头部特征/未知键场景），触发 Step 2a 路由
            "<134>Aug 24 10:00:00 host app: event=attack src=10.0.0.1\n"
            "<134>Aug 24 10:00:01 host app: event=scan src=10.0.0.2",
            "kv",
            "日志头+KV",
            "category",
            FORMAT_INFO,
            "",
        )
    )

    assert result["status"] == "FAILED"
    assert "other_field" in result["error"]


NESTED_JSON_LOGS = (
    '{"detail":{"event_type":"attack","src":"10.0.0.1"}}\n'
    '{"detail":{"event_type":"scan","src":"10.0.0.2"}}'
)


def test显式分类特征字段支持JSON点分路径(monkeypatch):
    """点分路径键（detail.event_type）可作为显式分类特征字段并被真实聚合提取。"""
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": "detail.event_type",
                "Diversion_method": "日志类型",
                "log_format": "JSON",
                "feature_field": "detail.event_type",
                "feature_count": 2,
                "classification_details": [
                    {"logtype": "attack", "meaning": "攻击"},
                    {"logtype": "scan", "meaning": "扫描"},
                ],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(knowledge_store, "store_classification_knowledge", lambda *a, **kw: True)

    result = json.loads(
        classify_log_features_headless(
            NESTED_JSON_LOGS,
            "json",
            "JSON",
            "detail.event_type",
            json.dumps({"format": "json", "format_detail": "JSON"}, ensure_ascii=False),
            "",
            feature_field_explicit=True,
        )
    )

    assert result["status"] == "SUCCESS"
    assert result["feature_field"] == "detail.event_type"
    assert {detail["logtype"] for detail in result["classification_details"]} == {"attack", "scan"}
