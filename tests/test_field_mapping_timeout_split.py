"""字段映射超时拆批、来源观测与原子性的回归测试。"""

import asyncio
import json
import re
from types import SimpleNamespace

from web.execution_adapters import FieldMappingExecutionPolicy, ProfessionalAgentAdapter
from web.plan_executor import ExecutionContext
from contracts.planner_models import FieldMappingStep, StepStatus
from contracts.session_facts import build_session_facts


class _Team:
    """提供单个字段映射成员。"""

    def __init__(self, member):
        self.members = [member]


class APITimeoutError(Exception):
    """模拟 Provider SDK 主动超时。"""


class _RateLimitError(Exception):
    """模拟携带 Retry-After 的 HTTP 429。"""

    status_code = 429
    response = SimpleNamespace(headers={"Retry-After": "0"})


class _MappingMember:
    """按测试模式令父批超时、子批失败或首次限流。"""

    name = "FieldMappingAgent"

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = []
        self.cancel_count = 0

    async def arun(self, model_input, *, stream, stream_events):
        """记录字段集合并生成 Agno 风格完成事件。"""
        match = re.search(r"字段列表（.*?）：\n(\[.*?\])", model_input, re.S)
        fields = list(json.loads(match.group(1)))
        self.calls.append(tuple(fields))
        if self.mode in {"watchdog", "child_failure"} and len(fields) == 25:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancel_count += 1
                raise
        if self.mode == "provider" and len(fields) == 25:
            raise APITimeoutError("provider deadline")
        if self.mode == "child_failure" and "child_00" in fields:
            raise ValueError("child invalid response")
        if self.mode == "rate_limit" and len(self.calls) == 1:
            raise _RateLimitError("rate limited")
        mappings = [
            {"原始字段名": field, "系统属性名称": f"标准_{field}", "匹配状态": "匹配成功"}
            for field in reversed(fields)
        ]
        if self.mode == "watchdog" and mappings:
            mappings.append(dict(mappings[0]))
        yield SimpleNamespace(event="RunCompleted", content=json.dumps(mappings, ensure_ascii=False))


def _run_mapping(fields, member, policy, session=None):
    """通过真实 Adapter 接缝执行一步字段映射。"""
    session = session or {"decoded_fields": fields}
    return asyncio.run(
        ProfessionalAgentAdapter(_Team(member), mapping_policy=policy).execute(
            FieldMappingStep(step_id="mapping", type="field_mapping", source_ref="session.fields"),
            ExecutionContext(session=session, session_facts=build_session_facts(session)),
            {},
        )
    )


def test字段映射25字段watchdog超时后拆成13和12并原子合并(monkeypatch):
    """超时大批不原样重试；子批结果去重并恢复原字段顺序。"""
    import web.execution_adapters as execution_adapters
    import web.input_builder as input_builder

    monkeypatch.setattr(input_builder, "_pre_query_field_candidates", lambda fields: "")
    messages = []
    monkeypatch.setattr(
        execution_adapters.logger,
        "warning",
        lambda message, *args: messages.append(message % args),
    )
    fields = [f"split_{index:02d}" for index in range(25)]
    member = _MappingMember("watchdog")
    result = _run_mapping(
        fields,
        member,
        FieldMappingExecutionPolicy(
            watchdog_timeout_seconds=0.02,
            max_retries=1,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
            timeout_split_size=13,
            max_timeout_split_depth=1,
        ),
    )

    assert result.status == StepStatus.SUCCESS
    assert [len(call) for call in member.calls] == [25, 13, 12]
    assert member.calls.count(tuple(fields)) == 1
    assert member.cancel_count == 1
    assert [row.original_field for row in result.artifact.mappings] == fields
    assert len({row.original_field for row in result.artifact.mappings}) == 25
    assert any("timeout_origin=adapter_watchdog" in message for message in messages)
    assert any("child_sizes=[13, 12]" in message for message in messages)


def test字段映射provider超时来源可观测且不原样重试(monkeypatch):
    """SDK timeout 使用 provider_sdk 标签并走同一层受限拆分。"""
    import web.execution_adapters as execution_adapters
    import web.input_builder as input_builder

    monkeypatch.setattr(input_builder, "_pre_query_field_candidates", lambda fields: "")
    messages = []
    monkeypatch.setattr(
        execution_adapters.logger,
        "warning",
        lambda message, *args: messages.append(message % args),
    )
    fields = [f"provider_{index:02d}" for index in range(25)]
    member = _MappingMember("provider")
    result = _run_mapping(
        fields,
        member,
        FieldMappingExecutionPolicy(
            watchdog_timeout_seconds=1,
            max_retries=1,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
        ),
    )

    assert result.status == StepStatus.SUCCESS
    assert [len(call) for call in member.calls] == [25, 13, 12]
    assert member.calls.count(tuple(fields)) == 1
    assert any("timeout_origin=provider_sdk" in message for message in messages)


def test字段映射子批失败时session保持原子不变(monkeypatch):
    """任一子批失败都不得提交其他子批的成功结果。"""
    import web.input_builder as input_builder

    monkeypatch.setattr(input_builder, "_pre_query_field_candidates", lambda fields: "")
    fields = [f"child_{index:02d}" for index in range(25)]
    session = {
        "decoded_fields": fields,
        "mapped_sub_rules": [
            {"name": "rule", "normalize": [{"index": field, "field": ""} for field in fields]}
        ],
    }
    original_sub_rules = json.loads(json.dumps(session["mapped_sub_rules"]))
    member = _MappingMember("child_failure")
    result = _run_mapping(
        fields,
        member,
        FieldMappingExecutionPolicy(
            watchdog_timeout_seconds=0.02,
            max_retries=0,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
        ),
        session,
    )

    assert result.status == StepStatus.FAILED
    assert result.error_code == "field_mapping_model_failed"
    assert member.calls.count(tuple(fields)) == 1
    assert "last_mapping_data" not in session
    assert "sub_rule_mapping_results" not in session
    assert session["mapped_sub_rules"] == original_sub_rules


def test字段映射429仍按RetryAfter有限原样重试(monkeypatch):
    """非超时瞬时错误保留一次有限重试，不触发拆批。"""
    import web.input_builder as input_builder

    monkeypatch.setattr(input_builder, "_pre_query_field_candidates", lambda fields: "")
    fields = [f"rate_{index:02d}" for index in range(25)]
    member = _MappingMember("rate_limit")
    result = _run_mapping(
        fields,
        member,
        FieldMappingExecutionPolicy(
            watchdog_timeout_seconds=1,
            max_retries=1,
            retry_delay_seconds=0,
            backfill_max_attempts=0,
        ),
    )

    assert result.status == StepStatus.SUCCESS
    assert member.calls == [tuple(fields), tuple(fields)]
