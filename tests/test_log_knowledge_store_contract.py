"""Issue #158：日志知识库存储的延迟导入与非致命契约。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType


def _install_fake_store(monkeypatch, *, fingerprint="fp", error=None, store_result=1):
    calls = {}
    module = ModuleType("agent.tools.log_pattern_store")

    def generate_structured_fingerprint(**kwargs):
        calls["fingerprint"] = kwargs
        return fingerprint

    def store_log_knowledge(**kwargs):
        calls["store"] = kwargs
        if error:
            raise error
        return store_result

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


def test_wrapper_reports_failure_when_repository_creates_no_row(monkeypatch):
    from agent.tools.pipeline.common.knowledge_store import store_classification_knowledge

    _install_fake_store(monkeypatch, store_result=None)
    assert store_classification_knowledge({}, "json") is False


def test_successful_kv_classification_does_not_auto_store_knowledge(monkeypatch):
    import agent.tools.pipeline.log_classifier as classifier

    calls = _install_fake_store(monkeypatch)

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
    assert calls == {}


def test_successful_json_classification_does_not_auto_store_knowledge(monkeypatch):
    import agent.tools.pipeline.log_classifier as classifier

    calls = _install_fake_store(monkeypatch)

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
        classifier._classify_json_features(
            '{"Type":"Auth","User":"a"}\n'
            '{"Type":"Mail","User":"b"}',
            "json",
            "JSON",
            "Type",
        )
    )

    assert output["status"] == "SUCCESS"
    assert calls == {}


def test_kv_feature_identifier_failure_log_excludes_raw_logs(
    monkeypatch, caplog
):
    import agent.tools.pipeline.log_classifier as classifier
    import agent.tools.pipeline.log_header_processor as header_processor

    secret = "raw-secret-must-not-appear"

    def fake_llm(*_args, **_kwargs):
        return json.dumps(
            {
                "status": "SUCCESS",
                "classification_details": [
                    {"logtype": "Auth", "meaning": "auth"},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(classifier, "_call_llm_direct", fake_llm)
    monkeypatch.setattr(
        header_processor,
        "_generate_kv_feature_identifier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError(f"invalid sample: {secret}")
        ),
    )

    output = json.loads(
        classifier._classify_kv_features(
            f"Type=Auth; payload={secret};\nType=Auth; payload=second;",
            "kv",
            "日志头+KV",
            "Type",
            {"delimit": ";", "tab": "="},
        )
    )

    assert output["status"] == "PARTIAL"
    assert secret in caplog.text  # 授权诊断日志保留失败原文；run_events 另走白名单
    assert "source_lines=2" in caplog.text
    assert "matched_lines=2" in caplog.text


def test_log_knowledge_runtime_has_no_embedding_or_sidecar_dependency():
    source = Path("agent/tools/log_pattern_store.py").read_text(encoding="utf-8")

    assert "import numpy" not in source
    assert "field_retriever" not in source
    assert "_EMBEDDING_PATH" not in source
    assert "_META_PATH" not in source
    assert "np.load" not in source
    assert "np.save" not in source


def test_normal_classification_paths_do_not_auto_store_knowledge():
    sources = [
        Path("agent/tools/pipeline/log_classifier.py").read_text(encoding="utf-8"),
        Path("agent/tools/pipeline/log_header_processor.py").read_text(
            encoding="utf-8"
        ),
    ]

    for source in sources:
        assert "pipeline.common.knowledge_store import" not in source
        assert "store_classification_knowledge(" not in source
        assert "store_log_knowledge" not in source


def test_header_kv_regex_validation_failure_does_not_expose_raw_sample(
    monkeypatch, caplog
):
    import agent.tools.pipeline.log_header_processor as header_processor

    secret = "header-regex-secret-7f21"
    monkeypatch.setattr(
        header_processor,
        "_call_llm_direct",
        lambda *_args, **_kwargs: r"r'^(.*)$'",
    )
    logs = (
        "<189>2026-09-15 host %%10VFW:1 TYPE/6/EVENT: "
        f"Type=Auth; payload={secret};"
    )

    result_text = header_processor.classify_header_features(
        logs,
        format_type="KV",
        format_detail="日志头+KV",
        format_info={"delimit": ";", "tab": "="},
    )

    result = json.loads(result_text)
    assert result["status"] == "FAILED"
    assert secret not in caplog.text
    assert secret not in result_text
    assert "kv_body_regex_validation_failed" in caplog.text
    assert result["error"] == "kv_body_regex_validation_failed"


def test_header_logtype_regex_validation_failure_does_not_expose_header(
    monkeypatch, caplog
):
    import agent.tools.pipeline.log_header_processor as header_processor

    secret = "header-field-secret-91ac"

    def fake_llm(prompt, *_args, **_kwargs):
        if "分隔符" in prompt:
            return r"r'^.*?\S+/\d+/\S+:\s*(.*)$'"
        if "日志头样例" in prompt:
            return r"r'(NO_MATCH)'"
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr(header_processor, "_call_llm_direct", fake_llm)
    logs = (
        f"<189>2026-09-15 {secret} %%10VFW:1 TYPE/6/EVENT: "
        "Type=Auth; payload=safe;"
    )

    result_text = header_processor.classify_header_features(
        logs,
        format_type="KV",
        format_detail="日志头+KV",
        format_info={"delimit": ";", "tab": "="},
    )

    result = json.loads(result_text)
    assert result["status"] == "FAILED"
    assert secret not in caplog.text
    assert secret not in result_text
    assert "header_logtype_regex_validation_failed" in caplog.text
    assert result["error"] == "header_logtype_regex_validation_failed"


def test_header_success_logs_body_length_without_body_preview(monkeypatch, caplog):
    import agent.tools.pipeline.log_classifier as classifier
    import agent.tools.pipeline.log_header_processor as header_processor

    secret = "header-body-secret-c43e"

    def fake_llm(prompt, *_args, **_kwargs):
        if "分隔符" in prompt:
            return r"r'^.*?\S+/\d+/\S+:\s*(.*)$'"
        if "日志头样例" in prompt:
            return r"r'(TYPE/\d+/EVENT)'"
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr(header_processor, "_call_llm_direct", fake_llm)
    monkeypatch.setattr(
        classifier,
        "_meaning_fill_batches",
        lambda *_args, **_kwargs: {
            "status": "SUCCESS",
            "feature_count": 1,
            "classification_details": [
                {"logtype": "TYPE/6/EVENT", "meaning": "safe"}
            ],
        },
    )
    logs = (
        "<189>2026-09-15 safe-host %%10VFW:1 TYPE/6/EVENT: "
        f"Type=Auth; payload={secret};"
    )

    result_text = header_processor.classify_header_features(
        logs,
        format_type="KV",
        format_detail="日志头+KV",
        format_info={"delimit": ";", "tab": "="},
    )

    result = json.loads(result_text)
    assert result["status"] == "SUCCESS"
    assert secret not in caplog.text
    assert secret not in result_text
    assert "body_length=" in caplog.text
    assert "body 提取:" not in caplog.text


def test_header_semantic_exception_is_reported_without_exception_text(
    monkeypatch, caplog
):
    import agent.tools.pipeline.log_classifier as classifier
    import agent.tools.pipeline.log_header_processor as header_processor

    secret = "header-exception-secret-b810"

    def fake_llm(prompt, *_args, **_kwargs):
        if "分隔符" in prompt:
            return r"r'^.*?\S+/\d+/\S+:\s*(.*)$'"
        if "日志头样例" in prompt:
            return r"r'(TYPE/\d+/EVENT)'"
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr(header_processor, "_call_llm_direct", fake_llm)
    monkeypatch.setattr(
        classifier,
        "_meaning_fill_batches",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    logs = (
        "<189>2026-09-15 safe-host %%10VFW:1 TYPE/6/EVENT: "
        "Type=Auth; payload=safe;"
    )

    result_text = header_processor.classify_header_features(
        logs,
        format_type="KV",
        format_detail="日志头+KV",
        format_info={"delimit": ";", "tab": "="},
    )

    result = json.loads(result_text)
    assert result["status"] == "FAILED"
    assert secret not in caplog.text
    assert secret not in result_text
    assert result["error"] == "semantic_classification_failed"
    assert "exception_type=RuntimeError" in caplog.text
