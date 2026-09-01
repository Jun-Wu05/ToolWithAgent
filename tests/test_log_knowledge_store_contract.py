"""Issue #158：日志知识库存储的延迟导入与非致命契约。"""

from __future__ import annotations

import json
import sys
from types import ModuleType


def _install_fake_store(monkeypatch, *, fingerprint="fp", error=None):
    calls = {}
    module = ModuleType("agent.tools.log_pattern_store")

    def generate_structured_fingerprint(**kwargs):
        calls["fingerprint"] = kwargs
        return fingerprint

    def store_log_knowledge(**kwargs):
        calls["store"] = kwargs
        if error:
            raise error
        return 1

    module.generate_structured_fingerprint = generate_structured_fingerprint
    module.store_log_knowledge = store_log_knowledge
    monkeypatch.setitem(sys.modules, "agent.tools.log_pattern_store", module)
    return calls


def test_structured_fingerprint_normalizes_the_classification_shape():
    from agent.tools.log_pattern_store import generate_structured_fingerprint

    assert generate_structured_fingerprint(
        {"feature_identifier": r"  (\S+)  "},
        format_detail="KV",
        feature_field="Type",
    ) == r"KV|Type|(\s+)"


def test_wrapper_uses_delayed_production_import_and_preserves_arguments(monkeypatch):
    from agent.tools.pipeline.common.knowledge_store import store_classification_knowledge

    calls = _install_fake_store(monkeypatch)
    result = {"status": "SUCCESS", "feature_identifier": "(.*)"}

    assert store_classification_knowledge(
        result, "kv", "日志头+KV", "Type", ["Type=A"]
    ) is True
    assert calls["fingerprint"] == {
        "classify_result": result,
        "format_detail": "日志头+KV",
        "feature_field": "Type",
    }
    assert calls["store"] == {
        "fingerprint": "fp",
        "format_type": "kv",
        "meta": result,
        "sample_logs": ["Type=A"],
    }


def test_empty_fingerprint_and_storage_exception_are_non_fatal(monkeypatch, caplog):
    from agent.tools.pipeline.common.knowledge_store import store_classification_knowledge

    calls = _install_fake_store(monkeypatch, fingerprint="")
    assert store_classification_knowledge({}, "json") is False
    assert "store" not in calls

    _install_fake_store(monkeypatch, error=RuntimeError("disk unavailable"))
    assert store_classification_knowledge({}, "json") is False
    assert "Storage failed (non-fatal)" in caplog.text


def test_successful_classification_survives_knowledge_store_failure(monkeypatch):
    import agent.tools.pipeline.log_classifier as classifier

    _install_fake_store(monkeypatch, error=RuntimeError("disk unavailable"))

    def fake_llm(*_args, **_kwargs):
        return json.dumps(
            {
                "status": "SUCCESS",
                "classification_details": [
                    {"logtype": "Auth", "meaning": "auth"},
                    {"logtype": "Mail", "meaning": "mail"},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(classifier, "_call_llm_direct", fake_llm)
    output = json.loads(
        classifier._classify_kv_features(
            "Type=Auth; User=a;\nType=Mail; User=b;",
            "kv",
            "KV",
            "Type",
            {"delimit": ";", "tab": "="},
        )
    )

    assert output["status"] == "SUCCESS"
    assert {row["logtype"] for row in output["classification_details"]} == {
        "Auth",
        "Mail",
    }
