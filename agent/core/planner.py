"""独立 PlannerAgent：只理解指令并产出严格计划，不持有业务工具。"""

from __future__ import annotations

import asyncio
import json
import uuid
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from agno.agent import Agent
from pydantic import ValidationError

from agent.core.model_config import ModelConfig
from agent.shared.logger import get_logger
from web.planner_models import ConversationTurn, PlanDecision
from web.progress import (
    NullProgressSink,
    ProgressEvent,
    ProgressPhase,
    ProgressSink,
    ProgressStatus,
)
from web.session_facts import SessionFacts

logger = get_logger("planner")

PlannerRunner = Callable[[str], Awaitable[Any] | Any]
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "planner.md"


def create_planner_agent() -> Agent:
    """创建无业务工具的 PlannerAgent，并由 Agno 强制校验输出结构。"""
    return Agent(
        name="PlannerAgent",
        role="用户指令规划器",
        model=ModelConfig.get_main_model(),
        instructions=_PROMPT_PATH.read_text(encoding="utf-8"),
        tools=[],
        output_schema=PlanDecision,
        markdown=False,
        debug_mode=False,
    )


def _limited_history(conversation_history: Sequence[ConversationTurn]) -> list[dict[str, str]]:
    """只保留最近六条文本历史，控制 token 并避免无关对象进入规划输入。"""
    return [
        {"role": item.role, "content": item.content}
        for item in conversation_history[-6:]
    ]

def build_planner_input(
    user_text: str,
    conversation_history: Sequence[ConversationTurn],
    session_facts: SessionFacts,
) -> str:
    """构建仅含用户原文、有限历史和安全事实的 Planner 输入。"""
    payload = {
        "user_text": user_text,
        "conversation_history": _limited_history(conversation_history),
        "session_facts": session_facts.model_dump(mode="json"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class PlannerService:
    """封装 Planner 调用与失败关闭策略，任何异常都只返回安全追问。"""

    def __init__(
        self,
        runner: PlannerRunner | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        """接收可替换 runner 和超时边界；生产环境延迟创建 Agent。"""
        self._runner = runner
        self._agent: Agent | None = None
        self._timeout_seconds = timeout_seconds

    def _get_runner(self) -> PlannerRunner:
        """延迟获取真实模型调用，避免导入模块时要求 API key。"""
        if self._runner is not None:
            return self._runner
        if self._agent is None:
            self._agent = create_planner_agent()
        return self._agent.arun

    async def plan(
        self,
        user_text: str,
        conversation_history: Sequence[ConversationTurn],
        session_facts: SessionFacts,
        progress_sink: ProgressSink | None = None,
        progress_plan_id: str = "planning",
    ) -> PlanDecision:
        """调用 Planner 一次；服务或结构失败时拒绝执行并返回明确追问。"""
        planner_input = build_planner_input(user_text, conversation_history, session_facts)
        runner = self._get_runner()
        sink = progress_sink or NullProgressSink()
        started_at = time.monotonic()
        await sink.publish(
            ProgressEvent(
                plan_id=progress_plan_id,
                step_id="planner",
                phase=ProgressPhase.PLANNING,
                status=ProgressStatus.RUNNING,
                message_code="planner_understanding",
            )
        )
        logger.info(
            "[MODEL_CALL_START] Planner 模型调用开始: plan_id=%s timeout_seconds=%s input_length=%s",
            progress_plan_id,
            self._timeout_seconds,
            len(planner_input),
        )

        async def invoke_runner() -> Any:
            """在异步边界调用 Planner；同步测试替身放入工作线程。"""
            if asyncio.iscoroutinefunction(runner):
                return await runner(planner_input)
            return await asyncio.to_thread(runner, planner_input)

        try:
            response = await asyncio.wait_for(invoke_runner(), timeout=self._timeout_seconds)
            metrics = getattr(response, "metrics", None)
            if metrics is not None:
                logger.info(
                    "[MODEL_USAGE] Planner token 统计: plan_id=%s input_tokens=%s "
                    "output_tokens=%s total_tokens=%s",
                    progress_plan_id,
                    getattr(metrics, "input_tokens", 0),
                    getattr(metrics, "output_tokens", 0),
                    getattr(metrics, "total_tokens", 0),
                )
            content = getattr(response, "content", response)
            if isinstance(content, PlanDecision):
                decision = content
            else:
                decision = PlanDecision.model_validate(content)
            if decision.plan_id == "pending":
                decision = decision.model_copy(update={"plan_id": f"plan-{uuid.uuid4().hex[:12]}"})
            elapsed_seconds = time.monotonic() - started_at
            logger.info(
                "[MODEL_CALL_END] Planner 模型调用完成: plan_id=%s elapsed_seconds=%.3f decision=%s",
                decision.plan_id,
                elapsed_seconds,
                decision.decision,
            )
            await sink.publish(
                ProgressEvent(
                    plan_id=decision.plan_id,
                    step_id="planner",
                    phase=ProgressPhase.PLANNING,
                    status=ProgressStatus.SUCCESS,
                    message_code="planner_completed",
                    elapsed_seconds=elapsed_seconds,
                )
            )
            return decision
        except asyncio.TimeoutError:
            elapsed_seconds = time.monotonic() - started_at
            logger.error(
                "[MODEL_CALL_TIMEOUT] Planner 模型调用超时: plan_id=%s timeout_seconds=%s",
                progress_plan_id,
                self._timeout_seconds,
            )
            await sink.publish(
                ProgressEvent(
                    plan_id=progress_plan_id,
                    step_id="planner",
                    phase=ProgressPhase.PLANNING,
                    status=ProgressStatus.FAILED,
                    message_code="planner_timeout",
                    elapsed_seconds=elapsed_seconds,
                )
            )
            return PlanDecision(
                decision="clarification",
                plan_id=progress_plan_id,
                reason_code="planner_timeout",
                question="指令理解服务响应超时，本次未执行任何操作。请稍后重试。",
            )
        except (ValidationError, TypeError, ValueError) as error:
            logger.error("[PLANNER] 输出非法，拒绝执行: error_category=invalid_plan error_type=%s", type(error).__name__)
            await sink.publish(
                ProgressEvent(
                    plan_id=progress_plan_id,
                    step_id="planner",
                    phase=ProgressPhase.PLANNING,
                    status=ProgressStatus.FAILED,
                    message_code="invalid_plan",
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return PlanDecision(
                decision="clarification",
                plan_id=progress_plan_id,
                reason_code="invalid_plan",
                question="我没有生成可安全执行的计划。请补充目标操作、字段和数据来源后重试。",
            )
        except Exception as error:
            logger.error("[PLANNER] 服务不可用，拒绝执行: error_category=planner_unavailable error_type=%s", type(error).__name__)
            await sink.publish(
                ProgressEvent(
                    plan_id=progress_plan_id,
                    step_id="planner",
                    phase=ProgressPhase.PLANNING,
                    status=ProgressStatus.FAILED,
                    message_code="planner_unavailable",
                    elapsed_seconds=time.monotonic() - started_at,
                )
            )
            return PlanDecision(
                decision="clarification",
                plan_id=progress_plan_id,
                reason_code="planner_unavailable",
                question="指令理解服务暂时不可用，本次未执行任何操作。请稍后重试。",
            )