"""Serializable boundary between a paused Application plan and its next action."""
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ExecutionContinuation:
    next_action: str
    completed_step_refs: tuple[str, ...]
    recovery_budget: dict[str, int]
    session_facts_digest: str

    def __post_init__(self):
        if not self.next_action or not self.session_facts_digest:
            raise ValueError("invalid_continuation")
        if any(not item for item in self.completed_step_refs):
            raise ValueError("invalid_continuation")
        if any(not isinstance(value, int) or value < 0 for value in self.recovery_budget.values()):
            raise ValueError("invalid_continuation")

    def to_json(self) -> str:
        return json.dumps({
            "next_action": self.next_action,
            "completed_step_refs": list(self.completed_step_refs),
            "recovery_budget": self.recovery_budget,
            "session_facts_digest": self.session_facts_digest,
        }, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "ExecutionContinuation":
        value = json.loads(raw)
        return cls(
            next_action=value["next_action"],
            completed_step_refs=tuple(value["completed_step_refs"]),
            recovery_budget=dict(value["recovery_budget"]),
            session_facts_digest=value["session_facts_digest"],
        )
