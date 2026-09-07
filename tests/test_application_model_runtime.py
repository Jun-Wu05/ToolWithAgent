"""Application-owned model session lifecycle."""

from types import SimpleNamespace


def _session(**overrides):
    """构造带模型覆盖字段的会话假件。"""
    fields = dict(current_provider=None, model_name=None, api_key=None, team=None)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_apply_model_settings_updates_session_and_rebuilds_team():
    """应用设置原子更新会话字段并重建该会话的 Team。"""
    import application.model_runtime as runtime

    session = _session()

    team = runtime.apply_model_settings(session, "deepseek", "deepseek-chat", "key")

    assert session.current_provider == "deepseek"
    assert session.model_name == "deepseek-chat"
    assert session.api_key == "key"
    assert session.team is team
    assert team is not None


def test_reset_and_lazy_team_lifecycle():
    """重置只清会话字段与 Team；ensure_team 按会话配置懒重建。"""
    import application.model_runtime as runtime

    session = _session(
        current_provider="deepseek",
        model_name="deepseek-chat",
        api_key="key",
        team=object(),
    )

    runtime.reset_model_settings(session)
    assert (
        session.current_provider,
        session.model_name,
        session.api_key,
        session.team,
    ) == (None, None, None, None)

    rebuilt = runtime.ensure_team(session)
    assert session.team is rebuilt
