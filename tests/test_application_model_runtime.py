"""Application-owned model session lifecycle."""

from types import SimpleNamespace


def test_apply_model_settings_updates_session_and_rebuilds_team(monkeypatch) -> None:
    import application.model_runtime as runtime

    session = SimpleNamespace(current_provider=None, model_name=None, api_key=None, team=None)
    team = object()
    calls = []
    monkeypatch.setattr(
        runtime.ModelConfig,
        "set_runtime_config",
        lambda **kwargs: calls.append(("config", kwargs)),
    )
    monkeypatch.setattr(runtime, "reset_team_instance", lambda: calls.append(("reset",)))
    monkeypatch.setattr(runtime, "get_team_instance", lambda: team)

    assert runtime.apply_model_settings(session, "deepseek", "deepseek-chat", "key") is team
    assert session.current_provider == "deepseek"
    assert session.model_name == "deepseek-chat"
    assert session.api_key == "key"
    assert session.team is team
    assert calls == [
        ("config", {"provider": "deepseek", "api_key": "key", "model": "deepseek-chat"}),
        ("reset",),
    ]


def test_reset_and_lazy_team_lifecycle(monkeypatch) -> None:
    import application.model_runtime as runtime

    old_team = object()
    new_team = object()
    session = SimpleNamespace(
        current_provider="deepseek", model_name="deepseek-chat", api_key="key", team=old_team
    )
    calls = []
    monkeypatch.setattr(runtime.ModelConfig, "clear_runtime_config", lambda: calls.append("clear"))
    monkeypatch.setattr(runtime, "reset_team_instance", lambda: calls.append("reset"))
    monkeypatch.setattr(runtime, "get_team_instance", lambda: new_team)

    runtime.reset_model_settings(session)
    assert (session.current_provider, session.model_name, session.api_key, session.team) == (
        None,
        None,
        None,
        None,
    )
    assert calls == ["clear", "reset"]
    assert runtime.ensure_team(session) is new_team
    assert session.team is new_team
