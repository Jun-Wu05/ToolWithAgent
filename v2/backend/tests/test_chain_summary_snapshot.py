"""Non-blocking chain outcomes survive protected business_state round trips."""
import pytest

from application.session_projection import build_session_facts, summarize_report
from contracts.planner_models import ExecutionReport, StepResult, StepStatus
from toolwithagent_v2.runtime.postprocessing import BusinessSession, freeze_session, restore_session


@pytest.mark.parametrize("outcome", ["failed", "needs_input", "warning", "degraded", "success"])
def test_business_state_round_trip_keeps_chain_outcome(outcome):
    report = ExecutionReport(plan_id="mapping", results=(StepResult(
        step_id="threat-chain", operation_type="threat_chain", status=StepStatus.SUCCESS,
        summary_status=outcome, error_code="threat_mapping_source_context_required",
        message="PRIVATE_SAMPLE PRIVATE_PATH PRIVATE_WARNING",
    ),))
    session = BusinessSession(current_execution=summarize_report(report))
    state = freeze_session(session)
    assert state["current_execution"]["steps"][0]["status"] == outcome
    facts = build_session_facts(restore_session(state))
    assert facts.recent_execution[0].steps[0].status == outcome
    assert "PRIVATE_" not in facts.model_dump_json()
    assert report.status == StepStatus.SUCCESS
