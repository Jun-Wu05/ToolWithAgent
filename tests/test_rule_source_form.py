"""Issue #129：Chainlit 数据源共用表单与待执行步骤续跑。"""

import asyncio
from types import SimpleNamespace


def _fake_chainlit(sent: list, session: object):
    class Message:
        def __init__(self, content="", **kwargs):
            self.content = content

        async def send(self):
            sent.append(("message", self.content))

    class ChatSettings:
        def __init__(self, widgets):
            self.widgets = widgets

        async def send(self):
            sent.append(("settings", self.widgets))

    return SimpleNamespace(
        Message=Message,
        ChatSettings=ChatSettings,
        user_session=SimpleNamespace(get=lambda key: session),
    )


def test_rule_source_form_uses_collision_safe_shared_widget_ids() -> None:
    from web.rule_source_form import build_rule_source_widgets

    widgets = build_rule_source_widgets()

    assert [widget.id for widget in widgets] == [
        "rule_source_product",
        "rule_source_log_vendor",
        "rule_source_data_source",
    ]
    assert [widget.label for widget in widgets] == [
        "数据源产品（必填）",
        "数据源厂商（必填）",
        "数据源（可选）",
    ]


def test_prompt_rule_source_form_remembers_exact_pending_step(monkeypatch) -> None:
    import web.rule_source_form as source_form
    from contracts.planner_models import ExportStep

    sent = []
    session = {}
    monkeypatch.setattr(source_form, "cl", _fake_chainlit(sent, session))
    step = ExportStep(
        step_id="entry",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )

    asyncio.run(source_form.prompt_rule_source_fields(session, pending_step=step))

    assert session["pending_rule_source_step"] is step
    assert sent[0][0] == "settings"


def test_valid_source_form_submission_stores_fields_and_resumes_step(monkeypatch) -> None:
    import web.deterministic_plan as deterministic_plan
    import web.rule_source_form as source_form
    from contracts.planner_models import ExportStep

    sent = []
    calls = []
    step = ExportStep(
        step_id="entry",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )
    session = {"pending_rule_source_step": step, "team": object()}
    monkeypatch.setattr(source_form, "cl", _fake_chainlit(sent, session))

    async def fake_execute(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fake_execute)

    handled = asyncio.run(
        source_form.handle_rule_source_settings(
            {
                "rule_source_product": " 产品A ",
                "rule_source_log_vendor": " 厂商B ",
                "rule_source_data_source": "",
            },
            session,
        )
    )

    assert handled is True
    assert session["rule_source_fields"].data_source == "产品A(厂商B)"
    assert session["pending_rule_source_step"] is None
    assert calls[0]["steps"] == (step,)
    assert calls[0]["user_session"] is session


def test_invalid_source_form_submission_reports_error_and_reopens(monkeypatch) -> None:
    import web.deterministic_plan as deterministic_plan
    import web.rule_source_form as source_form
    from contracts.planner_models import FieldMappingStep

    sent = []
    step = FieldMappingStep(
        step_id="mapping", type="field_mapping", source_ref="session.fields"
    )
    session = {"pending_rule_source_step": step}
    monkeypatch.setattr(source_form, "cl", _fake_chainlit(sent, session))

    async def fail_execute(**kwargs):
        raise AssertionError("校验失败时不得续跑")

    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fail_execute)

    handled = asyncio.run(
        source_form.handle_rule_source_settings(
            {
                "rule_source_product": "",
                "rule_source_log_vendor": "厂商B",
                "rule_source_data_source": "",
            },
            session,
        )
    )

    assert handled is True
    assert session["pending_rule_source_step"] is step
    assert [kind for kind, _ in sent] == ["message", "settings"]
    assert "数据源产品" in sent[0][1]


def test_unrelated_settings_payload_is_not_consumed() -> None:
    from web.rule_source_form import is_rule_source_settings

    assert is_rule_source_settings({"provider": "deepseek"}) is False
    assert is_rule_source_settings({"rule_source_product": "产品A"}) is True


def test_global_settings_callback_routes_source_form_before_model_settings(monkeypatch) -> None:
    import web.rule_source_form as source_form
    import web.settings_handler as settings_handler

    session = {}
    routed = []
    monkeypatch.setattr(settings_handler, "cl", _fake_chainlit([], session))

    async def fake_handle(settings, user_session):
        routed.append((settings, user_session))
        return True

    monkeypatch.setattr(source_form, "handle_rule_source_settings", fake_handle)

    payload = {"rule_source_product": "产品A"}
    asyncio.run(settings_handler.on_settings_update(payload))

    assert routed == [(payload, session)]


def test_entry_export_button_prompts_before_execution_when_fields_missing(monkeypatch) -> None:
    import web.action_callbacks as action_callbacks
    import web.deterministic_plan as deterministic_plan
    import web.rule_source_form as source_form

    session = {"log_classification": {"classification_details": []}}
    prompted = []
    monkeypatch.setattr(action_callbacks, "cl", _fake_chainlit([], session))

    async def fake_prompt(user_session, *, pending_step=None, **kwargs):
        prompted.append((user_session, pending_step))

    async def fail_execute(**kwargs):
        raise AssertionError("缺少数据源字段时按钮不应先执行计划")

    monkeypatch.setattr(source_form, "prompt_rule_source_fields", fake_prompt)
    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fail_execute)

    asyncio.run(action_callbacks.on_export_rules(SimpleNamespace()))

    assert prompted[0][0] is session
    assert prompted[0][1].source_ref == "session.log_classification.entry_rules"


def test_natural_language_needs_input_report_opens_same_form(monkeypatch) -> None:
    import web.plan_renderer as plan_renderer
    import web.rule_source_form as source_form
    from contracts.planner_models import ExecutionReport, StepResult, StepStatus

    sent = []
    prompted = []
    monkeypatch.setattr(plan_renderer, "cl", _fake_chainlit(sent, {}))

    async def fake_prompt(*args, **kwargs):
        prompted.append(True)

    monkeypatch.setattr(source_form, "prompt_rule_source_fields", fake_prompt)
    report = ExecutionReport(
        plan_id="natural-source-gate",
        results=(
            StepResult(
                step_id="export",
                operation_type="export",
                status=StepStatus.NEEDS_INPUT,
                error_code="data_source_fields_required",
                message="请填写数据源字段",
            ),
        ),
    )

    asyncio.run(plan_renderer.render_execution_report(report))

    assert prompted == [True]
