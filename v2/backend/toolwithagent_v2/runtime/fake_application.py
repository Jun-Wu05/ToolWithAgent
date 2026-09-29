"""Deterministic headless Application stand-in for durable Run testing."""
import hashlib
import json

from application.execution_continuation import ExecutionContinuation


class FakeApplication:
    def __init__(self, calls=None, facts=None):
        self.calls = calls if calls is not None else {}
        self.facts = facts

    def _called(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    @staticmethod
    def digest(facts):
        return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def execute(self, snapshot, continuation=None):
        facts = self.facts if self.facts is not None else snapshot.get("session_facts", {})
        digest = self.digest(facts)
        if continuation is not None:
            if continuation.session_facts_digest != digest:
                return {"error": "continuation_stale"}
            if continuation.next_action != "finish":
                return {"error": "invalid_continuation"}
            self._called("step_two")
            return {"artifact": json.dumps({"result": "resumed", "facts": facts}, sort_keys=True).encode()}
        self._called("planner")
        self._called("step_one")
        if snapshot["scenario"] == "fail":
            return {"error": "fake_failure"}
        if snapshot["scenario"] == "confirm":
            return {"continuation": ExecutionContinuation(
                next_action="finish",
                completed_step_refs=("step_one",),
                recovery_budget={"total": 2, "rederive": 1, "step_retry": 1},
                session_facts_digest=digest,
            ), "confirmation": {"message": "Continue fake task?"}}
        self._called("step_two")
        return {"artifact": json.dumps({"result": "complete", "facts": facts}, sort_keys=True).encode()}
