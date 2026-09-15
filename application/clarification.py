"""基于安全会话事实生成升级追问说明。"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent.shared.logger import get_logger
from contracts.session_facts import SessionFacts


ClarificationRunner = Callable[[str], Awaitable[Any] | Any]
recovery_logger = get_logger("recovery")
_MAX_TEXT_LENGTH = 240
_QUOTED_TOKEN_RE = re.compile(r"(?:`([^`]+)`|「([^」]+)」|“([^”]+)”)")
_ASCII_IDENTIFIER_RE = re.compile(r"(?<![\w])([A-Za-z_][A-Za-z0-9_.:-]*)(?![\w])")
_MARKDOWN_OPTION_RE = re.compile(r"(?m)^\s*[-*+]\s+")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RECOVERY_SUMMARY_RE = re.compile(
    r"^(?:(?:retry_as_is|restructure|rederive_system_param|escalate)=\d+"
    r"(?:,(?:retry_as_is|restructure|rederive_system_param|escalate)=\d+)*)?$"
)


def _create_clarification_agent():
    """延迟创建无工具、低随机性的生产追问生成器。"""
    from agno.agent import Agent

    from agent.core.model_config import ModelConfig
    from agent.prompts import load_clarification_prompt

    model = ModelConfig.get_main_model()
    model.temperature = 0
    return Agent(
        name="ClarificationComposer",
        role="升级追问文案生成器",
        model=model,
        instructions=load_clarification_prompt(),
        tools=[],
        markdown=False,
        debug_mode=False,
    )


def _allowed_output_tokens(facts: SessionFacts, choices: Sequence[str]) -> set[str]:
    """收集 Composer 可以逐字引用的安全字段名与确定性选项。"""
    values = [
        *choices,
        *facts.available_fields,
        *facts.mappable_fields,
        *facts.enum_mapping_target_fields,
        *facts.threat_source_fields,
        *facts.available_config_refs,
        *facts.mapped_sub_rule_names,
    ]
    allowed = {value for value in values if value}
    for value in tuple(allowed):
        allowed.update(_ASCII_IDENTIFIER_RE.findall(value))
    return allowed


def _is_safe_output(text: str, facts: SessionFacts, choices: Sequence[str]) -> bool:
    """保守过滤生成内容；识别不了的标识符直接回退模板。"""
    if not text or len(text) > _MAX_TEXT_LENGTH or _MARKDOWN_OPTION_RE.search(text):
        return False
    # ponytail: 朴素 token 白名单足够；仅在出现可复现漏报时升级结构化输出。
    allowed = _allowed_output_tokens(facts, choices)
    quoted = {
        next(part for part in match if part)
        for match in _QUOTED_TOKEN_RE.findall(text)
    }
    if not quoted.issubset(allowed):
        return False
    return set(_ASCII_IDENTIFIER_RE.findall(text)).issubset(allowed)


async def compose_clarification(
    kind: str,
    facts: SessionFacts,
    error_code: str | None,
    choices: Sequence[str],
    recovery_summary: str,
    *,
    runner: ClarificationRunner | None = None,
    timeout_seconds: float = 12.0,
) -> str | None:
    """生成追问说明；任何生成失败都返回 ``None`` 交给模板兜底。"""
    started_at = time.monotonic()
    safe_error_code = (
        error_code
        if error_code is None or _ERROR_CODE_RE.fullmatch(error_code)
        else None
    )
    safe_recovery_summary = (
        recovery_summary if _RECOVERY_SUMMARY_RE.fullmatch(recovery_summary) else ""
    )

    def finish(
        outcome: str,
        text: str | None = None,
        response: Any = None,
    ) -> str | None:
        """只记录可审计元数据；prompt 与生成文案都不得进入日志。"""
        metrics = getattr(response, "metrics", None)
        recovery_logger.info(
            "[CLARIFICATION] kind=%s error_code=%s choice_count=%s "
            "recovery_summary=%s outcome=%s elapsed_seconds=%.3f "
            "input_tokens=%s output_tokens=%s total_tokens=%s",
            kind,
            safe_error_code,
            len(choices),
            safe_recovery_summary,
            outcome,
            time.monotonic() - started_at,
            getattr(metrics, "input_tokens", 0),
            getattr(metrics, "output_tokens", 0),
            getattr(metrics, "total_tokens", 0),
        )
        return text

    if error_code is not None and safe_error_code is None:
        return finish("invalid_error_code")
    if not _RECOVERY_SUMMARY_RE.fullmatch(recovery_summary):
        return finish("invalid_recovery_summary")
    if runner is None:
        try:
            runner = _create_clarification_agent().arun
        except Exception:
            return finish("generator_unavailable")

    prompt = json.dumps(
        {
            "kind": kind,
            "facts": facts.model_dump(mode="json"),
            "error_code": error_code,
            "choices": list(choices),
            "recovery_summary": recovery_summary,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    async def invoke() -> Any:
        response = runner(prompt)
        return await response if inspect.isawaitable(response) else response

    try:
        response = await asyncio.wait_for(invoke(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return finish("timeout")
    except Exception:
        return finish("runner_failed")
    content = getattr(response, "content", response)
    text = content.strip() if isinstance(content, str) else ""
    if not _is_safe_output(text, facts, choices):
        return finish("unsafe_output", response=response)
    return finish("success", text, response)
