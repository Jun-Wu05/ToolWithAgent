# -*- coding: utf-8 -*-
"""planner 语义遵循度评测：走 PlannerService.plan 全链路（真实 LLM + 守卫层）。

用法:
    python -X utf8 outputs\\planner_eval\\run_eval.py [--out results_before.json]

宽松匹配规则:
- decision 必须一致
- execute: 步骤类型序列一致；期望步骤中声明的参数逐一比对
  （列表参数集合相等，标量相等；config_ref 未声明则不比对）
- clarification: 只比对 decision（reason_code 不作硬性要求）
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.core.planner import PlannerService  # noqa: E402
from contracts.planner_models import ConversationTurn  # noqa: E402
from contracts.session_facts import SessionFacts  # noqa: E402

_CONFIG_REFS = {
    "session.decoded_config",
    "session.mapped_sub_rules",
}


def _param_matches(expected: object, actual: object) -> bool:
    """参数宽松匹配：列表比集合，标量比相等。"""
    if isinstance(expected, list):
        return isinstance(actual, (list, tuple)) and set(expected) == set(actual)
    return expected == actual


def _step_matches(expected: dict, actual) -> bool:
    """单个步骤匹配：type 相等 + 期望声明的参数全部命中。"""
    if getattr(actual, "type", None) != expected.get("type"):
        return False
    for key, expected_value in expected.items():
        if key == "type":
            continue
        actual_value = getattr(actual, key, None)
        if key == "config_ref":
            if expected_value == "*any*" and actual_value in _CONFIG_REFS:
                continue
        if not _param_matches(expected_value, actual_value):
            return False
    return True


def _decision_matches(expected: dict, decision) -> tuple[bool, str]:
    """整体匹配，返回 (是否通过, 失败原因)。"""
    if decision.decision != expected["decision"]:
        return False, f"decision={decision.decision}"
    if decision.decision != "execute":
        return True, ""
    expected_steps = expected.get("steps", [])
    actual_steps = list(decision.steps)
    if len(expected_steps) != len(actual_steps):
        types = [getattr(s, "type", "?") for s in actual_steps]
        return False, f"步骤数 {len(actual_steps)}（{types}）"
    for expected_step, actual_step in zip(expected_steps, actual_steps):
        if not _step_matches(expected_step, actual_step):
            return False, f"步骤不匹配: 期望 {expected_step}"
    return True, ""


async def run(out_path: str) -> None:
    """逐条执行评测并输出明细与遵循率。"""
    cases_path = Path(__file__).resolve().parent / "cases.json"
    cases = json.loads(io.open(cases_path, encoding="utf-8").read())["cases"]
    service = PlannerService()
    results = []
    passed = 0
    started = time.time()

    for index, case in enumerate(cases, 1):
        facts = SessionFacts.model_validate(case.get("facts", {}))
        history = [
            ConversationTurn(role=item["role"], content=item["content"])
            for item in case.get("history", [])
        ]
        try:
            decision = await service.plan(
                user_text=case["user_text"],
                conversation_history=history,
                session_facts=facts,
            )
            ok, reason = _decision_matches(case["expect"], decision)
            actual = {
                "decision": decision.decision,
                "steps": [
                    {key: value for key, value in step.model_dump().items()
                     if key in ("type", "feature_field", "target_field", "field_name",
                                "field_value", "value_type", "fields", "source_fields",
                                "target_field", "sep", "source_field", "config_ref",
                                "fill_kind", "target_fields", "source_ref", "values")}
                    for step in decision.steps
                ],
            }
        except Exception as error:  # noqa: BLE001 - 评测记录一切异常为失败
            ok, reason = False, f"异常: {type(error).__name__}: {error}"
            actual = {"decision": "error"}

        passed += int(ok)
        results.append({
            "id": case["id"],
            "category": case.get("category", ""),
            "user_text": case["user_text"],
            "ok": ok,
            "reason": reason,
            "actual": actual,
        })
        mark = "PASS" if ok else "FAIL"
        print(f"[{index:>2}/{len(cases)}] {mark} {case['id']}" + (f"  -- {reason}" if not ok else ""))

    rate = passed / len(cases) * 100
    summary = {
        "total": len(cases),
        "passed": passed,
        "rate_percent": round(rate, 1),
        "elapsed_seconds": round(time.time() - started, 1),
        "failed_ids": [r["id"] for r in results if not r["ok"]],
        "results": results,
    }
    Path(out_path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n=== 遵循率: {passed}/{len(cases)} = {rate:.1f}%  （{summary['elapsed_seconds']}s）===")
    print(f"结果已写入 {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "results.json"))
    args = parser.parse_args()
    asyncio.run(run(args.out))
