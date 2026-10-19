"""Serializable boundary between a paused Application plan and its next action."""
from dataclasses import dataclass, field
import json


@dataclass(frozen=True)
class ExecutionContinuation:
    next_action: str
    completed_step_refs: tuple[str, ...]
    recovery_budget: dict[str, int]
    session_facts_digest: str
    frozen_plan: dict | None = None
    completed_results: tuple[dict, ...] = ()
    staging_state: dict = field(default_factory=dict)
    recovery_count: int = 0
    step_recovery_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.next_action or not self.session_facts_digest:
            raise ValueError("invalid_continuation")
        if any(not item for item in self.completed_step_refs):
            raise ValueError("invalid_continuation")
        if self.recovery_count < 0 or any(value < 0 for value in self.step_recovery_counts.values()):
            raise ValueError("invalid_continuation")
        if any(not isinstance(value, int) or value < 0 for value in self.recovery_budget.values()):
            raise ValueError("invalid_continuation")

    def to_json(self) -> str:
        return json.dumps({
            "next_action": self.next_action,
            "completed_step_refs": list(self.completed_step_refs),
            "recovery_budget": self.recovery_budget,
            "session_facts_digest": self.session_facts_digest,
            "frozen_plan": self.frozen_plan,
            "completed_results": list(self.completed_results),
            "staging_state": self.staging_state,
            "recovery_count": self.recovery_count,
            "step_recovery_counts": self.step_recovery_counts,
        }, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "ExecutionContinuation":
        value = json.loads(raw)
        return cls(
            next_action=value["next_action"],
            completed_step_refs=tuple(value["completed_step_refs"]),
            recovery_budget=dict(value["recovery_budget"]),
            session_facts_digest=value["session_facts_digest"],
            frozen_plan=value.get("frozen_plan"),
            completed_results=tuple(value.get("completed_results", ())),
            staging_state=value.get("staging_state", {}),
            recovery_count=value.get("recovery_count", 0),
            step_recovery_counts=value.get("step_recovery_counts", {}),
        )
