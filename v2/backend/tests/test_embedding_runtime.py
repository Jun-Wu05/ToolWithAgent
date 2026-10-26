"""V2 isolated install must support the shared embedding HTTP client."""
from types import SimpleNamespace


def test_shared_embedding_client_runs_in_v2_environment(monkeypatch):
    import requests
    from agent.core import embedding_client

    vector = [0.0] * embedding_client.EMBEDDING_DIM
    vector[0] = 1.0
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]["model"]))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"index": 0, "embedding": vector}]},
        )

    monkeypatch.setenv("SILICONFLOW_API_KEY", "offline-test-key")
    monkeypatch.setattr(requests, "post", post)
    result = embedding_client.call_embedding_api(["src_ip"])

    assert result is not None
    assert result.shape == (1, embedding_client.EMBEDDING_DIM)
    assert result[0, 0] == 1.0
    assert calls == [(embedding_client.EMBEDDING_API_URL, embedding_client.EMBEDDING_MODEL)]
