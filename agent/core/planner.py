"""独立 PlannerAgent：只理解指令并产出严格计划，不持有业务工具。"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agno.agent import Agent
from pydantic import ValidationError

from agent.core.model_config import ModelConfig
from agent.prompts import load_planner_prompt
from agent.shared.logger import get_logger
from contracts.planner_models import (
    ConversationTurn,
    FillStep,
    LogParseStep,
    PendingPlan,
    PlanDecision,
)
from application.progress import NullProgressSink
from contracts.progress import (
    ProgressEvent,
    ProgressPhase,
    ProgressSink,
    ProgressStatus,
)
from contracts.session_facts import SessionFacts

logger = get_logger("planner")

PlannerRunner = Callable[[str], Awaitable[Any] | Any]


def create_planner_agent() -> Agent:
    """创建确定性 PlannerAgent，并由 Agno 强制校验输出结构。"""
    model = ModelConfig.get_main_model()
    # 相同事实与指令必须产生稳定计划；禁止用失败后重调破坏“一次 Planner”不变量。
    model.temperature = 0
    return Agent(
        name="PlannerAgent",
        role="用户指令规划器",
        model=model,
        instructions=load_planner_prompt(),
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
    pending_plan: PendingPlan | None = None,
) -> str:
    """构建仅含用户原文、有限历史和安全事实的 Planner 输入。"""
    payload = {
        "user_text": user_text,
        "conversation_history": _limited_history(conversation_history),
        "session_facts": session_facts.model_dump(mode="json"),
        "pending_plan": (
            {
                "plan_id": pending_plan.plan_id,
                "operations": [step.type for step in pending_plan.steps],
            }
            if pending_plan
            else None
        ),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FILL_TARGET_VERBS = (
    "填充到",
    "填充至",
    "填入",
    "填到",
    "写入",
    "写到",
    "回填到",
    "回填至",
    "填回到",
    "填回至",
)
_GENERIC_FILL_TARGET_RE = re.compile(
    r"(?:填充到|填充至|填入|填到|写入|写到|回填到|回填至|填回到|填回至|填回(?!去))"
    r"\s*(?:字段\s*)?[`'\"“”‘’「」『』]*"
    r"(?P<target>[A-Za-z_][A-Za-z0-9_.-]*|"
    r"[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9_.-]*?)"
    r"(?=[`'\"“”‘’「」『』，。！？；,\s]|并|然后|$)"
)
_NON_FIELD_FILL_TARGETS = frozenset(
    {
        "配置",
        "当前配置",
        "解析规则",
        "规则",
        "目标字段",
        "对应字段",
        "绑定字段",
        "标准字段",
        "原字段",
        "原来的字段",
        "回去",
        "进去",
    }
)

# PlanDecision 顶层合法字段。模型常自添 explanation/rationale 等多余键，剥离这些键
# 仅作兜底；步骤级 extra=forbid 与判别联合校验不受影响，结构安全性不降级。
_PLAN_DECISION_KEYS = frozenset(
    {
        "decision",
        "plan_id",
        "steps",
        "pending_plan_id",
        "reason_code",
        "question",
        "choices",
        "guidance_code",
        "answer",
        "parameters",
    }
)


def _extract_json_object(text: str) -> str:
    """从可能含 markdown 围栏或解释性前后缀的文本中取出首个 JSON 对象片段。"""
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _coerce_plan_decision(content: Any) -> PlanDecision:
    """把模型/Agno 返回内容规整为 PlanDecision。

    Agno 在自身结构化解析失败时会保留 content 为原始字符串，直接交给
    ``PlanDecision.model_validate`` 会抛 "Input should be a valid dictionary"；
    这里先抽 JSON 再解析。顶层多余字段（如 explanation）兜底剥离，步骤结构仍走
    严格判别联合校验，整体返回值始终经过 PlanDecision 的全部语义校验。
    """
    if isinstance(content, PlanDecision):
        return content

    payload: Any = content
    if isinstance(content, str):
        try:
            payload = json.loads(_extract_json_object(content))
        except json.JSONDecodeError as error:
            raise ValueError(f"模型输出不是合法 JSON: {error.msg}") from error

    if isinstance(payload, dict):
        try:
            return PlanDecision.model_validate(payload)
        except ValidationError:
            unknown_keys = set(payload) - _PLAN_DECISION_KEYS
            # 只有存在顶层多余键时才剥离重试；否则原样抛出，保留错误可观测性。
            if not unknown_keys:
                raise
            cleaned = {key: value for key, value in payload.items() if key in _PLAN_DECISION_KEYS}
            return PlanDecision.model_validate(cleaned)

    raise TypeError(f"不支持的 Planner 输出类型: {type(content).__name__}")


def _explicit_fill_target_mentions(
    user_text: str,
    available_fields: Sequence[str],
) -> tuple[str, ...]:
    """识别当前文本在填充动词后明确点名的已知字段，不把“填充回去”当作显式目标。"""
    verb_pattern = "|".join(re.escape(item) for item in _FILL_TARGET_VERBS)
    mentions: list[str] = []
    for field in sorted(set(available_fields), key=len, reverse=True):
        if not field:
            continue
        pattern = re.compile(
            rf"(?:{verb_pattern})\s*(?:字段\s*)?[`'\"“”‘’「」『』]*{re.escape(field)}"
        )
        if pattern.search(user_text):
            mentions.append(field)
    if mentions:
        return tuple(mentions)
    generic_mentions = [
        match.group("target")
        for match in _GENERIC_FILL_TARGET_RE.finditer(user_text)
        if match.group("target") not in _NON_FIELD_FILL_TARGETS
    ]
    return tuple(dict.fromkeys(generic_mentions))


# 用户显式指定分类特征字段的规范短语族（与 CONTEXT.md「分类特征字段」消歧边界同步）。
# 结构 = 介词（把/将/拿/按/用/对）+ 字段片段 + 连接词+日志类型：既能命中
# 「把A字段作为日志类型」「按A做日志类型分类」「用A区分日志类型」，又不会
# 误伤不含字段点名的纯操作指令（如「日志类型提取」「帮我做日志类型分类」）。
_EXPLICIT_FEATURE_FIELD_PHRASE_RE = re.compile(
    r"(?:把|将|拿|按|用|对)[^，。;；]{0,40}?"
    r"(?:(?:作为|当作|设为|当成|当|做)日志类型|区分日志类型|给日志分类)"
)


def _guard_explicit_feature_field(user_text: str, decision: PlanDecision) -> PlanDecision:
    """用户显式要求把某字段作为日志类型而计划缺该参数时，追问而非静默自动探测。

    只判短语族存在与参数缺席的矛盾组合，不从中文文本抽取字段名；
    字段识别始终是 Planner 模型的职责（PRD #110「显式意图确定性守卫」）。
    """
    if decision.decision not in {"execute", "proposal"}:
        return decision
    if not _EXPLICIT_FEATURE_FIELD_PHRASE_RE.search(user_text):
        return decision
    has_explicit_log_parse = any(
        isinstance(step, LogParseStep) and step.feature_field
        for step in decision.steps
    )
    if has_explicit_log_parse:
        return decision
    return PlanDecision(
        decision="clarification",
        plan_id=decision.plan_id,
        reason_code="explicit_feature_field_ignored",
        question=(
            "您要求把指定字段作为日志类型，但计划中没有携带该字段。"
            "请确认要作为日志类型的字段名（日志体键，如 category），"
            "或直接说“日志类型提取”由系统自动探测。"
        ),
    )


def _guard_cross_turn_threat_target(
    user_text: str,
    decision: PlanDecision,
    session_facts: SessionFacts,
) -> PlanDecision:
    """阻止 Planner 把用户点名的冲突字段静默改写为产物绑定字段。"""
    if decision.decision not in {"execute", "proposal"}:
        return decision
    threat_fact = next(
        (
            item
            for item in session_facts.referenceable_artifacts
            if item.source_ref == "session.artifacts.threat_mapping"
            and item.artifact_type == "threat_mapping"
        ),
        None,
    )
    if threat_fact is None or not threat_fact.source_field:
        return decision
    explicit_targets = _explicit_fill_target_mentions(
        user_text,
        session_facts.available_fields,
    )
    if not explicit_targets:
        return decision

    for step in decision.steps:
        if not (
            isinstance(step, FillStep)
            and step.fill_kind == "threat"
            and step.source_ref == "session.artifacts.threat_mapping"
        ):
            continue
        binding = next(
            (
                item
                for item in threat_fact.target_bindings
                if item.config_ref == step.config_ref
            ),
            None,
        )
        if binding is None:
            continue
        allowed_names = {threat_fact.source_field, binding.target_field}
        conflict = next(
            (item for item in explicit_targets if item not in allowed_names),
            None,
        )
        if conflict is None:
            continue
        return PlanDecision(
            decision="clarification",
            plan_id=decision.plan_id,
            reason_code="artifact_target_mismatch",
            question=(
                f"最近威胁映射来自 {threat_fact.source_field}，只能填回标准字段"
                f"“{binding.target_field}”，不能填入“{conflict}”。"
                f"如需处理“{conflict}”，请先为该字段重新生成威胁映射。"
            ),
        )
    return decision


_AUTO_THREAT_SOURCE_RE = re.compile(
    r"(?:选择|挑选|推荐)[^，。;；]{0,20}(?:合适|最佳|适合)[^，。;；]{0,20}字段"
)


def _normalize_threat_source_clarification(
    user_text: str, decision: PlanDecision, session_facts: SessionFacts
) -> PlanDecision:
    """统一威胁来源提示，禁止把完整字段池作为推荐列表展示。"""
    if decision.decision != "clarification":
        return decision
    auto_requested = decision.reason_code == "threat_source_auto_requested" or (
        decision.reason_code == "threat_source_required"
        and _AUTO_THREAT_SOURCE_RE.search(user_text)
    )
    if auto_requested:
        return decision.model_copy(
            update={
                "reason_code": "threat_source_auto_requested",
                "question": "正在从真实字段中自动选择威胁类型来源。",
                "choices": (),
            }
        )
    if decision.reason_code == "threat_source_not_found":
        requested = decision.parameters.get("requested_field", "").replace("`", "").strip()
        question = (
            f"字段 `{requested}` 不存在于当前威胁子规则，未执行。"
            if requested
            else "指定字段不存在于当前威胁子规则，未执行。"
        )
        return decision.model_copy(update={"question": question, "choices": ()})
    if decision.reason_code != "threat_source_required":
        return decision
    question = (
        "请明确用于威胁类型映射的来源字段。"
        if session_facts.threat_source_fields
        else "当前威胁子规则没有共同可用的来源字段，请先检查字段映射结果。"
    )
    return decision.model_copy(update={"question": question, "choices": ()})


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
        pending_plan: PendingPlan | None = None,
        progress_sink: ProgressSink | None = None,
        progress_plan_id: str = "planning",
    ) -> PlanDecision:
        """调用 Planner 一次；服务或结构失败时拒绝执行并返回明确追问。"""
        planner_input = build_planner_input(
            user_text,
            conversation_history,
            session_facts,
            pending_plan,
        )
        runner = self._get_runner()
        sink = progress_sink or NullProgressSink()
        started_at = time.monotonic()
        model_id = ModelConfig.get_model_id()
        provider = ModelConfig.get_provider()
        call_phase = "runner_start"
        response_received = False
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
            "[MODEL_CALL_START] Planner 模型调用开始: plan_id=%s provider=%s model=%s "
            "timeout_seconds=%s input_length=%s phase=%s",
            progress_plan_id,
            provider,
            model_id,
            self._timeout_seconds,
            len(planner_input),
            call_phase,
        )

        async def invoke_runner() -> Any:
            """调用 Planner，并按返回值是否可 await 决定是否等待。

            注意：Agno 的 Agent.arun 是「返回协程的普通方法」而非 coroutine function
            （inspect.iscoroutinefunction(Agent.arun) 为 False）。若用 iscoroutinefunction
            判定分支，arun 会被当作同步函数在 to_thread 里调用，返回一个未被 await 的协程，
            表现为 response/content 是 coroutine、模型实际从未被调用。这里改为对调用结果
            用 inspect.isawaitable 判定，兼容真协程函数、arun 这类返回协程的普通函数，
            以及同步测试替身。
            """
            nonlocal call_phase
            call_phase = "runner_wait"
            raw = runner(planner_input)
            if inspect.isawaitable(raw):
                response = await raw
                call_phase = "response_received"
                return response
            call_phase = "response_received"
            return raw

        content: Any = None
        try:
            response = await asyncio.wait_for(invoke_runner(), timeout=self._timeout_seconds)
            response_received = True
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
            decision = _coerce_plan_decision(content)
            if decision.plan_id == "pending":
                decision = decision.model_copy(update={"plan_id": f"plan-{uuid.uuid4().hex[:12]}"})
            decision = _guard_cross_turn_threat_target(
                user_text,
                decision,
                session_facts,
            )
            decision = _guard_explicit_feature_field(user_text, decision)
            decision = _normalize_threat_source_clarification(
                user_text, decision, session_facts
            )
            elapsed_seconds = time.monotonic() - started_at
            logger.info(
                "[MODEL_CALL_END] Planner 模型调用完成: plan_id=%s provider=%s model=%s "
                "elapsed_seconds=%.3f decision=%s phase=%s response_received=%s",
                decision.plan_id,
                provider,
                model_id,
                elapsed_seconds,
                decision.decision,
                call_phase,
                response_received,
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
                "[MODEL_CALL_TIMEOUT] Planner 模型调用超时: plan_id=%s provider=%s model=%s "
                "timeout_seconds=%s elapsed_seconds=%.3f phase=%s response_received=%s",
                progress_plan_id,
                provider,
                model_id,
                self._timeout_seconds,
                elapsed_seconds,
                call_phase,
                response_received,
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
            # 仅记录结构形状与校验失败位置，绝不输出模型原文/字段值，满足脱敏要求。
            shape_hint = ""
            if isinstance(content, dict):
                shape_hint = f" keys={sorted(content.keys())}"
            elif isinstance(content, str):
                shape_hint = f" len={len(content)}"
            error_locs = ""
            if isinstance(error, ValidationError):
                error_locs = " locs=" + json.dumps(
                    [{"loc": list(item["loc"]), "type": item["type"]} for item in error.errors()],
                    ensure_ascii=False,
                )
            logger.error(
                "[PLANNER] 输出非法，拒绝执行: error_category=invalid_plan error_type=%s "
                "provider=%s model=%s elapsed_seconds=%.3f phase=%s response_received=%s "
                "content_kind=%s%s%s",
                type(error).__name__,
                provider,
                model_id,
                time.monotonic() - started_at,
                call_phase,
                response_received,
                type(content).__name__,
                shape_hint,
                error_locs,
            )
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
            logger.error(
                "[PLANNER] 服务不可用，拒绝执行: error_category=planner_unavailable error_type=%s "
                "provider=%s model=%s elapsed_seconds=%.3f phase=%s response_received=%s",
                type(error).__name__,
                provider,
                model_id,
                time.monotonic() - started_at,
                call_phase,
                response_received,
            )
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
