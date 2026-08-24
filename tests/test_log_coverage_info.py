"""日志分类未匹配行覆盖信息契约（Issue #112 / PRD #110）。

不含分类特征字段的日志行不归入任何类型；其数量与样本作为覆盖信息单独输出，
不进入 classification_details，也不参与规则生成与导出。
"""

import json

import agent.tools.pipeline.log_classifier as log_classifier
import agent.tools.pipeline.common.knowledge_store as knowledge_store
from agent.tools import classify_log_features_headless
from web.utils import render_log_parser_result


MIXED_KV_LOGS = (
    "category=attack src=10.0.0.1\n"
    "category=scan src=10.0.0.2\n"
    "src=10.0.0.3 action=deny"
)
MIXED_JSON_LOGS = (
    '{"detail":{"event_type":"attack"}}\n'
    '{"detail":{"event_type":"scan"}}\n'
    '{"src":"10.0.0.3"}'
)


def _mock_llm(monkeypatch, feature_field: str, logtypes: list[str]):
    """固定语义分类模型输出，让真实聚合与渲染逻辑跑通。"""
    monkeypatch.setattr(
        log_classifier,
        "_call_llm_direct",
        lambda *a, **kw: json.dumps(
            {
                "status": "SUCCESS",
                "categorical_features": feature_field,
                "Diversion_method": "日志类型",
                "log_format": "KV",
                "feature_field": feature_field,
                "feature_count": len(logtypes),
                "classification_details": [
                    {"logtype": item, "meaning": item} for item in logtypes
                ],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(knowledge_store, "store_classification_knowledge", lambda *a, **kw: True)


def test自动探测模式KV混合样本输出未匹配覆盖信息(monkeypatch):
    """缺 category 的行不归入任何类型，数量与样本进入覆盖信息块。"""
    _mock_llm(monkeypatch, "category", ["attack", "scan"])

    result = json.loads(
        classify_log_features_headless(
            MIXED_KV_LOGS,
            "kv",
            "KV",
            "category",
            json.dumps(
                {"format": "kv", "format_detail": "KV", "delimit": " ", "tab": "="},
                ensure_ascii=False,
            ),
            "",
        )
    )

    coverage = result["coverage"]
    assert coverage["total_lines"] == 3
    assert coverage["matched_lines"] == 2
    assert coverage["unmatched_lines"] == 1
    assert coverage["unmatched_samples"] == ["src=10.0.0.3 action=deny"]
    # 分类明细只来自匹配行，未匹配行不进入分类。
    assert {detail["logtype"] for detail in result["classification_details"]} == {"attack", "scan"}


def test显式模式JSON点分路径混合样本输出未匹配覆盖信息(monkeypatch):
    """显式分类特征字段同样携带覆盖信息，嵌套键正常匹配。"""
    _mock_llm(monkeypatch, "detail.event_type", ["attack", "scan"])

    result = json.loads(
        classify_log_features_headless(
            MIXED_JSON_LOGS,
            "json",
            "JSON",
            "detail.event_type",
            json.dumps({"format": "json", "format_detail": "JSON"}, ensure_ascii=False),
            "",
            feature_field_explicit=True,
        )
    )

    coverage = result["coverage"]
    assert coverage["total_lines"] == 3
    assert coverage["matched_lines"] == 2
    assert coverage["unmatched_lines"] == 1
    assert coverage["unmatched_samples"] == ['{"src":"10.0.0.3"}']
    assert {detail["logtype"] for detail in result["classification_details"]} == {"attack", "scan"}


def test全匹配时覆盖信息为全匹配且无样本():
    """所有行都含分类特征字段时，未匹配为 0、样本为空。"""
    result = json.loads(
        classify_log_features_headless(
            MIXED_KV_LOGS.split("\n")[0],
            "kv",
            "KV",
            "category",
            json.dumps({"format": "kv", "format_detail": "KV"}, ensure_ascii=False),
            "",
        )
    )

    coverage = result["coverage"]
    assert coverage["matched_lines"] == coverage["total_lines"] == 1
    assert coverage["unmatched_lines"] == 0
    assert coverage["unmatched_samples"] == []


def test渲染未匹配行覆盖提示与样本():
    """分类摘要渲染未匹配行数、样本和“可能存在其他日志类型字段”提示。"""
    markdown = render_log_parser_result(
        {
            "status": "SUCCESS",
            "log_format": "KV",
            "feature_field": "category",
            "feature_count": 2,
            "classification_details": [
                {"logtype": "attack", "meaning": "攻击"},
                {"logtype": "scan", "meaning": "扫描"},
            ],
            "coverage": {
                "total_lines": 3,
                "matched_lines": 2,
                "unmatched_lines": 1,
                "unmatched_samples": ["src=10.0.0.3 action=deny"],
            },
        },
        None,
    )

    assert "未归入任何类型" in markdown
    assert "1/3" in markdown
    assert "src=10.0.0.3 action=deny" in markdown
    assert "其他日志类型字段" in markdown


def test全匹配渲染不含未匹配提示():
    """未匹配为 0 时渲染不出现未归入提示块。"""
    markdown = render_log_parser_result(
        {
            "status": "SUCCESS",
            "log_format": "KV",
            "feature_field": "category",
            "feature_count": 2,
            "classification_details": [
                {"logtype": "attack", "meaning": "攻击"},
                {"logtype": "scan", "meaning": "扫描"},
            ],
            "coverage": {
                "total_lines": 2,
                "matched_lines": 2,
                "unmatched_lines": 0,
                "unmatched_samples": [],
            },
        },
        None,
    )

    assert "未归入任何类型" not in markdown
