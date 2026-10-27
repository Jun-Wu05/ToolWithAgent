"""Model-call evidence keeps stable categories and strips credentials."""

import asyncio
from types import SimpleNamespace

import httpx

from contracts.model_call_diagnostics import bind_recorder, instrument_model, redact_text, reset_recorder


class FakeModel:
    id = "model-a"

    async def ainvoke(self, messages, assistant_message, **kwargs):
        if messages[0].content == "timeout":
            raise httpx.ConnectError("Authorization: Bearer top-secret")
        assistant_message.content = "api_key=top-secret finished"
        return assistant_message


class Message:
    def __init__(self, content):
        self.content = content


def test_agno_call_records_success_and_typed_connection_failure_without_secrets():
    events = []
    token = bind_recorder(events.append)
    model = instrument_model(FakeModel(), "deepseek", "model-a")
    try:
        asyncio.run(model.ainvoke([Message("api_key=top-secret input")], Message("")))
        try:
            asyncio.run(model.ainvoke([Message("timeout")], Message("")))
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("original exception must propagate")
    finally:
        reset_recorder(token)
    assert [event["status"] for event in events] == ["succeeded", "failed"]
    assert events[1]["error_code"] == "model_connection"
    assert all(event["provider"] == "deepseek" and event["model"] == "model-a" for event in events)
    assert all(event["request_id"] and event["duration_ms"] >= 0 for event in events)
    assert "top-secret" not in str(events)


def test_no_v2_scope_does_not_capture_model_content():
    model = instrument_model(FakeModel(), "deepseek", "model-a")
    result = asyncio.run(model.ainvoke([Message("input")], Message("")))
    assert result.content == "api_key=top-secret finished"


def test_json_credentials_and_large_content_are_redacted_and_bounded():
    value = '{"api_key":"secret-one", "cookie": "session=secret-two; other=secret-three", "note": "safe"}'
    projected = redact_text(value)
    assert all(secret not in projected for secret in ("secret-one", "secret-two", "secret-three"))
    assert '"note": "safe"' in projected
    assert "secret-four" not in redact_text("Cookie: session=secret-four; other=secret-five")
    assert "secret-five" not in redact_text("Cookie: session=secret-four; other=secret-five")
    assert "dGVzdA==" not in redact_text("prefix Authorization: Basic dGVzdA== suffix")
    assert "secret-seven" not in redact_text("prefix Cookie: session=secret-six; other=secret-seven")
    assert len(redact_text("a" * 5000)) == 4096


def test_direct_log_model_call_records_sanitized_request_and_response(monkeypatch):
    from agent.tools.pipeline import llm_client

    monkeypatch.setattr(llm_client.ModelConfig, "get_provider", lambda: "deepseek")
    monkeypatch.setattr(llm_client.ModelConfig, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(llm_client.ModelConfig, "get_model_id", lambda: "model-a")
    monkeypatch.setattr(llm_client.model_config, "get_provider_spec", lambda _: SimpleNamespace(name="deepseek", supports_json_response_format=False))
    monkeypatch.setattr(llm_client.model_config, "get_chat_completions_url", lambda _: "https://example.invalid/chat")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "api_key=test-key result"}}], "usage": {}}

    monkeypatch.setattr(llm_client.httpx, "post", lambda *args, **kwargs: Response())
    events = []
    token = bind_recorder(events.append)
    try:
        assert llm_client._call_llm_direct("Authorization: Bearer test-key") == "api_key=test-key result"
    finally:
        reset_recorder(token)
    assert len(events) == 1
    assert events[0]["status"] == "succeeded"
    assert events[0]["provider"] == "deepseek"
    assert "test-key" not in str(events)
