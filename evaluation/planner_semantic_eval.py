"""真实 Planner 语义稳定性评测，不在默认 pytest 中发起网络请求。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from agent.core.planner import PlannerService, create_planner_agent
from web.planner_models import PlanDecision
from web.session_facts import SessionFacts


@dataclass(frozen=True)
class SemanticCase:
    """描述一条语料、会话事实和可观察的计划断言。"""

    name: str
    user_text: str
    facts: SessionFacts
    validate: Callable[[PlanDecision], bool]


def _step_types(decision: PlanDecision) -> tuple[str, ...]:
    """返回计划步骤类型，非执行决策返回空元组。"""
    return tuple(step.type for step in decision.steps)


def _single_step(expected_type: str) -> Callable[[PlanDecision], bool]:
    """构造七类单意图的共同断言。"""
    return lambda decision: decision.decision == "execute" and _step_types(decision) == (
        expected_type,
    )


MAPPED_FACTS = SessionFacts(
    has_decoded_config=True,
    has_mapped_sub_rules=True,
    available_config_refs=("session.decoded_config", "session.mapped_sub_rules"),
    available_fields=("事件级别", "event_type3"),
    enum_mapping_target_fields=("事件级别",),
    enum_mapping_row_count=2,
    mapped_sub_rule_count=1,
)

CASES = (
    SemanticCase("log_parse", "日志类型提取", SessionFacts(has_logs=True), _single_step("log_parse")),
    SemanticCase(
        "field_mapping",
        "执行标准字段映射",
        SessionFacts(available_fields=("源地址", "目的地址")),
        _single_step("field_mapping"),
    ),
    SemanticCase(
        "enum_extract",
        "提取事件级别的枚举值",
        SessionFacts(has_logs=True, available_fields=("事件级别",)),
        lambda d: _step_types(d) == ("enum_extract",)
        and getattr(d.steps[0], "target_field", None) == "事件级别",
    ),
    SemanticCase(
        "threat_mapping",
        "把 SQL注入 和 暴力破解 做威胁类型映射",
        SessionFacts(),
        _single_step("threat_mapping"),
    ),
    SemanticCase("fill", "把枚举映射表填充回事件级别", MAPPED_FACTS, _single_step("fill")),
    SemanticCase(
        "remove_mapping",
        "取消事件级别的值映射",
        MAPPED_FACTS,
        _single_step("remove_mapping"),
    ),
    SemanticCase("export", "导出映射后的配置", MAPPED_FACTS, _single_step("export")),
    SemanticCase(
        "compound",
        "提取 event_type3 的枚举值，再做威胁映射并填充回 event_type3",
        MAPPED_FACTS.model_copy(update={"has_logs": True}),
        lambda d: _step_types(d) == ("enum_extract", "threat_mapping", "fill"),
    ),
    SemanticCase(
        "compound_enum_threat",
        "把alarm_name的枚举值提取出来，并且进行威胁类型映射",
        SessionFacts(has_logs=True, available_fields=("alarm_name",)),
        lambda d: _step_types(d) == ("enum_extract", "threat_mapping"),
    ),
    SemanticCase(
        "conflict",
        "日志类型提取，但按事件级别字段做枚举提取，只执行一步",
        SessionFacts(has_logs=True, available_fields=("事件级别",)),
        lambda d: d.decision == "clarification" and not d.steps,
    ),
)


async def run_evaluation(runs: int, selected_case: str | None = None) -> list[dict[str, object]]:
    """通过生产 PlannerService 接缝运行语料并收集 schema、延迟与 token。"""
    agent = create_planner_agent()
    observations: list[dict[str, object]] = []
    cases = [case for case in CASES if selected_case in (None, case.name)]
    if not cases:
        raise ValueError(f"未知语料: {selected_case}")

    for case in cases:
        for run_number in range(1, runs + 1):
            usage: dict[str, int] = {}

            async def runner(planner_input: str):
                """包装真实 Agent，仅旁路采集本次 response metrics。"""
                response = await agent.arun(planner_input)
                metrics = getattr(response, "metrics", None)
                if metrics is not None:
                    usage.update(
                        input_tokens=int(getattr(metrics, "input_tokens", 0) or 0),
                        output_tokens=int(getattr(metrics, "output_tokens", 0) or 0),
                        total_tokens=int(getattr(metrics, "total_tokens", 0) or 0),
                    )
                return response

            started_at = time.monotonic()
            decision = await PlannerService(runner=runner, timeout_seconds=90).plan(
                user_text=case.user_text,
                conversation_history=[],
                session_facts=case.facts,
                progress_plan_id=f"eval-{case.name}-{run_number}",
            )
            observation = {
                "case": case.name,
                "run": run_number,
                "passed": case.validate(decision),
                "decision": decision.decision,
                "step_types": list(_step_types(decision)),
                "schema": decision.model_dump(mode="json"),
                "latency_seconds": round(time.monotonic() - started_at, 3),
                "tokens": usage,
            }
            observations.append(observation)
            print(json.dumps(observation, ensure_ascii=False, separators=(",", ":")), flush=True)
    return observations


def main() -> int:
    """解析命令行并以退出码表达真实语义门禁结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", choices=[case.name for case in CASES])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    observations = asyncio.run(run_evaluation(args.runs, args.case))
    if args.output:
        args.output.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in observations) + "\n",
            encoding="utf-8",
        )
    failures = [item for item in observations if not item["passed"]]
    print(json.dumps({"total": len(observations), "failures": len(failures)}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
