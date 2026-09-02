"""Issue #175：数据源模态表单可见性、交互恢复与步骤续跑。"""

import asyncio
from types import SimpleNamespace

import pytest


def _fake_chainlit(sent: list, session: object):
    class Message:
        def __init__(self, content="", elements=None, **kwargs):
            self.content = content
            self.elements = elements or []

        async def send(self):
            sent.append(("message", self))

    class CustomElement:
        def __init__(self, **kwargs):
            self.name = kwargs["name"]
            self.display = kwargs["display"]
            self.props = kwargs["props"]

    class AskElementMessage:
        def __init__(self, **kwargs):
            raise AssertionError("Action 回调不得使用会遗留 loading 状态的 Ask API")

    return SimpleNamespace(
        AskElementMessage=AskElementMessage,
        CustomElement=CustomElement,
        Message=Message,
        user_session=SimpleNamespace(get=lambda key: session),
    )


def _payload(*, product="产品A", vendor="厂商B", data_source="") -> dict:
    return {
        "rule_source_product": product,
        "rule_source_log_vendor": vendor,
        "rule_source_data_source": data_source,
    }


def test_prompt_sends_non_blocking_modal_and_remembers_exact_step(monkeypatch) -> None:
    import web.rule_source_form as source_form
    from contracts.planner_models import ExportStep

    sent = []
    step = ExportStep(
        step_id="entry",
        type="export",
        source_ref="session.log_classification.entry_rules",
    )
    session = {}
    monkeypatch.setattr(source_form, "cl", _fake_chainlit(sent, session))

    asyncio.run(source_form.prompt_rule_source_fields(session, pending_step=step))

    assert session["pending_rule_source_step"] is step
    message = sent[0][1]
    assert message.elements[0].name == "RuleSourceDialog"
    assert message.elements[0].props["timeout_seconds"] == 300
    assert not hasattr(message, "wait_for_answer")


def test_submission_stores_fields_and_resumes_exact_step(monkeypatch) -> None:
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
    session = {"team": object(), "pending_rule_source_step": step}
    monkeypatch.setattr(source_form, "cl", _fake_chainlit(sent, session))

    async def fake_execute(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fake_execute)

    completed = asyncio.run(
        source_form.handle_rule_source_submission(
            _payload(product=" 产品A ", vendor=" 厂商B "), session
        )
    )

    assert completed is True
    assert session["rule_source_fields"].data_source == "产品A(厂商B)"
    assert session["pending_rule_source_step"] is None
    assert calls[0]["steps"] == (step,)
    assert calls[0]["user_session"] is session


def test_invalid_submission_reopens_modal_with_preserved_values(monkeypatch) -> None:
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
        raise AssertionError("校验失败时不得执行计划")

    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fail_execute)

    completed = asyncio.run(
        source_form.handle_rule_source_submission(
            _payload(product="", vendor=" 厂商B ", data_source=" 自定义来源 "),
            session,
        )
    )

    assert completed is False
    assert session["pending_rule_source_step"] is step
    assert "数据源产品" in sent[0][1].content
    reopened = sent[1][1].elements[0]
    assert reopened.props["rule_source_log_vendor"] == "厂商B"
    assert reopened.props["rule_source_data_source"] == "自定义来源"


@pytest.mark.parametrize(
    ("reason", "expected_text"),
    [("cancel", "已取消"), ("timeout", "已超时")],
)
def test_cancel_or_timeout_clears_pending_step(
    monkeypatch, reason, expected_text
) -> None:
    import web.rule_source_form as source_form
    from contracts.planner_models import ExportStep

    sent = []
    session = {
        "pending_rule_source_step": ExportStep(
            step_id="entry",
            type="export",
            source_ref="session.log_classification.entry_rules",
        )
    }
    monkeypatch.setattr(source_form, "cl", _fake_chainlit(sent, session))

    asyncio.run(source_form.handle_rule_source_cancel({"reason": reason}, session))

    assert session["pending_rule_source_step"] is None
    assert expected_text in sent[0][1].content


def test_submit_and_cancel_actions_route_custom_element_payload(monkeypatch) -> None:
    import web.action_callbacks as action_callbacks
    import web.rule_source_form as source_form

    session = {}
    routed = []
    monkeypatch.setattr(action_callbacks, "cl", _fake_chainlit([], session))

    async def fake_submit(payload, user_session):
        routed.append(("submit", payload, user_session))

    async def fake_cancel(payload, user_session):
        routed.append(("cancel", payload, user_session))

    monkeypatch.setattr(source_form, "handle_rule_source_submission", fake_submit)
    monkeypatch.setattr(source_form, "handle_rule_source_cancel", fake_cancel)

    asyncio.run(
        action_callbacks.on_submit_rule_source_fields(
            SimpleNamespace(payload={"rule_source_product": "产品A"})
        )
    )
    asyncio.run(
        action_callbacks.on_cancel_rule_source_fields(
            SimpleNamespace(payload={"reason": "cancel"})
        )
    )

    assert routed == [
        ("submit", {"rule_source_product": "产品A"}, session),
        ("cancel", {"reason": "cancel"}, session),
    ]


@pytest.mark.parametrize(
    ("callback_name", "source_ref"),
    [
        ("on_export_rules", "session.log_classification.entry_rules"),
        ("on_export_sub_rules", "session.log_classification.sub_rules"),
        ("on_apply_field_mapping", "session.fields"),
    ],
)
def test_three_rule_buttons_open_modal_before_execution_when_fields_missing(
    monkeypatch, callback_name, source_ref
) -> None:
    import application.session_projection as session_projection
    import web.action_callbacks as action_callbacks
    import web.deterministic_plan as deterministic_plan
    import web.rule_source_form as source_form

    session = {"log_classification": {"classification_details": []}}
    prompted = []
    monkeypatch.setattr(action_callbacks, "cl", _fake_chainlit([], session))
    monkeypatch.setattr(
        session_projection,
        "build_session_facts",
        lambda user_session: SimpleNamespace(available_fields=("field_a",)),
    )

    async def fake_prompt(user_session, *, pending_step=None, **kwargs):
        prompted.append((user_session, pending_step))

    async def fail_execute(**kwargs):
        raise AssertionError("缺少数据源字段时按钮不应先执行计划")

    monkeypatch.setattr(source_form, "prompt_rule_source_fields", fake_prompt)
    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fail_execute)

    asyncio.run(getattr(action_callbacks, callback_name)(SimpleNamespace()))

    assert prompted[0][0] is session
    assert prompted[0][1].source_ref == source_ref


@pytest.mark.parametrize(
    "callback_name",
    ["on_export_rules", "on_export_sub_rules", "on_apply_field_mapping"],
)
def test_three_rule_buttons_execute_directly_when_session_fields_exist(
    monkeypatch, callback_name
) -> None:
    import application.session_projection as session_projection
    import web.action_callbacks as action_callbacks
    import web.deterministic_plan as deterministic_plan
    import web.rule_source_form as source_form
    from contracts.rule_source import RuleSourceFields

    session = {
        "log_classification": {"classification_details": []},
        "rule_source_fields": RuleSourceFields.create(
            product="产品A", log_vendor="厂商B"
        ),
    }
    calls = []
    monkeypatch.setattr(action_callbacks, "cl", _fake_chainlit([], session))
    monkeypatch.setattr(
        session_projection,
        "build_session_facts",
        lambda user_session: SimpleNamespace(available_fields=("field_a",)),
    )

    async def fail_prompt(*args, **kwargs):
        raise AssertionError("已有会话字段时不应重复弹窗")

    async def fake_execute(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(source_form, "prompt_rule_source_fields", fail_prompt)
    monkeypatch.setattr(deterministic_plan, "execute_deterministic_plan", fake_execute)

    asyncio.run(getattr(action_callbacks, callback_name)(SimpleNamespace()))

    assert len(calls) == 1


def test_natural_language_needs_input_report_opens_same_modal(monkeypatch) -> None:
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


def test_source_dialog_is_isolated_from_model_settings_callback() -> None:
    import inspect
    import web.settings_handler as settings_handler

    source = inspect.getsource(settings_handler.on_settings_update)

    assert "rule_source" not in source
    assert "handle_rule_source_settings" not in source


def test_custom_element_contract_is_non_blocking_and_supports_actions() -> None:
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "public" / "elements" / "RuleSourceDialog.jsx"
    ).read_text(encoding="utf-8")

    assert "<Dialog open" in source
    assert 'finish("submit_rule_source_fields"' in source
    assert 'finish("cancel_rule_source_fields"' in source
    assert "callAction" in source
    assert "deleteElement" in source
    assert "submitElement" not in source
    assert "cancelElement" not in source
    assert 'id="rule-source-product"' in source
    assert 'id="rule-source-vendor"' in source
    assert 'id="rule-source-name"' in source
