"""ClarificationComposer 的安全生成与失败回退测试。"""

import asyncio
import json
from types import SimpleNamespace

import pytest


def test安全生成文案通过公共接口返回():
    """生成器只基于安全事实解释卡点，并保留确定性建议字段。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    async def runner(_prompt: str):
        return SimpleNamespace(content="当前缺少可用字段，请选择「event_type」。")

    text = asyncio.run(
        compose_clarification(
            "needs_input",
            SessionFacts(available_fields=("event_type",)),
            "enum_target_field_not_found",
            ("event_type",),
            "retry_as_is=1",
            runner=runner,
        )
    )

    assert text == "当前缺少可用字段，请选择「event_type」。"


def test生成器输入只序列化安全事实和确定性选项():
    """原始业务样本不属于 Composer 输入，runner 只能看到安全目录。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    captured = {}
    sensitive_sample = "token=never-send-this-value"

    def runner(prompt: str):
        captured["payload"] = json.loads(prompt)
        return SimpleNamespace(content="请选择「event_type」。")

    asyncio.run(
        compose_clarification(
            "needs_input",
            SessionFacts(available_fields=("event_type",)),
            "enum_target_field_not_found",
            ("event_type",),
            "retry_as_is=1",
            runner=runner,
        )
    )

    serialized = json.dumps(captured["payload"], ensure_ascii=False)
    assert sensitive_sample not in serialized
    assert captured["payload"]["facts"]["available_fields"] == ["event_type"]
    assert captured["payload"]["choices"] == ["event_type"]


def test生成器异常时返回空值交给模板兜底():
    """模型异常不能阻断原有确定性追问。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    def runner(_prompt: str):
        raise RuntimeError("provider unavailable")

    text = asyncio.run(
        compose_clarification(
            "clarification",
            SessionFacts(),
            "missing_context",
            (),
            "",
            runner=runner,
        )
    )

    assert text is None


@pytest.mark.parametrize(
    "content",
    (
        "",
        "说明" * 121,
        "请回复：\n- 新增选项",
        "请改用「unknown_field」。",
    ),
)
def test空白过长新增选项或未知标识符均被拒绝(content):
    """朴素渲染守卫宁可回退模板，也不展示不可验证的生成内容。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    text = asyncio.run(
        compose_clarification(
            "needs_input",
            SessionFacts(available_fields=("event_type",)),
            "enum_target_field_not_found",
            ("event_type",),
            "",
            runner=lambda _prompt: SimpleNamespace(content=content),
        )
    )

    assert text is None


def test生成超时时返回空值交给模板兜底():
    """短超时确保追问生成不会拖住原有渲染。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    async def runner(_prompt: str):
        await asyncio.sleep(0.02)
        return SimpleNamespace(content="不会展示")

    text = asyncio.run(
        compose_clarification(
            "clarification",
            SessionFacts(),
            "missing_context",
            (),
            "",
            runner=runner,
            timeout_seconds=0.001,
        )
    )

    assert text is None


def test追问生成指令由统一Prompt加载器提供():
    """Composer prompt 归属 agent/prompts，禁止散落在应用代码。"""
    from agent.prompts import load_clarification_prompt

    prompt = load_clarification_prompt()

    assert "不得新增、删除或改写 choices" in prompt
    assert "不得输出业务值" in prompt


def test未注入runner时延迟使用生产生成器(monkeypatch):
    """生产路径在调用时才创建模型，导入模块不会要求密钥。"""
    import application.clarification as clarification
    from contracts.session_facts import SessionFacts

    class FakeAgent:
        async def arun(self, _prompt: str):
            return SimpleNamespace(content="请选择「event_type」。")

    monkeypatch.setattr(
        clarification,
        "_create_clarification_agent",
        lambda: FakeAgent(),
        raising=False,
    )

    text = asyncio.run(
        clarification.compose_clarification(
            "needs_input",
            SessionFacts(available_fields=("event_type",)),
            "enum_target_field_not_found",
            ("event_type",),
            "",
        )
    )

    assert text == "请选择「event_type」。"


def test生产生成器初始化失败时也回退(monkeypatch):
    """缺少模型配置等初始化错误不能越过模板兜底边界。"""
    import application.clarification as clarification
    from contracts.session_facts import SessionFacts

    def fail_to_create():
        raise RuntimeError("missing model config")

    monkeypatch.setattr(clarification, "_create_clarification_agent", fail_to_create)

    text = asyncio.run(
        clarification.compose_clarification(
            "clarification",
            SessionFacts(),
            "missing_context",
            (),
            "",
        )
    )

    assert text is None


def test恢复摘要拒绝类型和计数以外的内容():
    """恢复摘要不能成为业务值绕过 SessionFacts 边界的旁路。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    calls = []
    text = asyncio.run(
        compose_clarification(
            "needs_input",
            SessionFacts(available_fields=("event_type",)),
            "enum_target_field_not_found",
            ("event_type",),
            "retry_as_is=1;raw_value=secret",
            runner=lambda prompt: calls.append(prompt)
            or SimpleNamespace(content="请选择「event_type」。"),
        )
    )

    assert text is None
    assert calls == []


def test错误码拒绝稳定标识符以外的内容():
    """error_code 只能是可审计代码，不能成为业务值旁路。"""
    from application.clarification import compose_clarification
    from contracts.session_facts import SessionFacts

    calls = []
    text = asyncio.run(
        compose_clarification(
            "needs_input",
            SessionFacts(),
            "missing_context;raw_value=secret",
            (),
            "",
            runner=lambda prompt: calls.append(prompt)
            or SimpleNamespace(content="请补充信息。"),
        )
    )

    assert text is None
    assert calls == []


def test生成结果写入恢复审计且不记录模型文案(monkeypatch):
    """升级追问只审计安全元数据，模型输出与完整 prompt 不进入日志。"""
    import application.clarification as clarification
    from contracts.session_facts import SessionFacts

    records = []
    monkeypatch.setattr(
        clarification,
        "recovery_logger",
        SimpleNamespace(info=lambda message, *args: records.append((message, args))),
        raising=False,
    )

    generated = "请选择「event_type」。"
    text = asyncio.run(
        clarification.compose_clarification(
            "needs_input",
            SessionFacts(available_fields=("event_type",)),
            "enum_target_field_not_found",
            ("event_type",),
            "retry_as_is=1",
            runner=lambda _prompt: SimpleNamespace(content=generated),
        )
    )

    assert text == generated
    assert len(records) == 1
    message, args = records[0]
    assert "[CLARIFICATION]" in message
    assert "success" in args
    assert generated not in repr(records)
