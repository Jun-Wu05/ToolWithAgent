"""共享执行器恢复账本、预算和请求日志隐私的兼容回归。"""
import asyncio
from dataclasses import asdict
import logging
from io import StringIO
from application.execution import ExecutionContext, PlanExecutor
from application.execution_continuation import ExecutionContinuation
from application.recovery import RecoveryBudget
from application.log_privacy import private_business_logging
from contracts.planner_models import DeterministicPlan, EnumExtractStep, ThreatMappingStep, EnumValuesArtifact, StepResult, StepStatus
from contracts.session_facts import SessionFacts
import pytest
from factories import make_session_state


def test_resume_keeps_success_dependency_and_exhausted_recovery_budget():
    plan = DeterministicPlan(plan_id="resume", steps=(EnumExtractStep(step_id="enum",type="enum_extract",target_field="alarm"),
        ThreatMappingStep(step_id="threat",type="threat_mapping",source_ref="step:enum",depends_on=("enum",))))
    completed = StepResult(step_id="enum",operation_type="enum_extract",status=StepStatus.SUCCESS,
        artifact=EnumValuesArtifact(item_count=1,values=("SQL注入",),field="alarm"))
    calls=[]
    class Adapter:
        async def execute(self,step,context,dependencies):
            calls.append(step.step_id)
            assert dependencies["enum"].artifact.values == ("SQL注入",)
            return StepResult(step_id=step.step_id,operation_type=step.type,status=StepStatus.SUCCESS)
    continuation = ExecutionContinuation("execute_plan",("enum",),asdict(RecoveryBudget()),"digest",
        frozen_plan=plan.model_dump(mode="json"),completed_results=(completed.model_dump(mode="json"),),recovery_count=2,step_recovery_counts={"enum":1})
    checkpoint={}
    result=asyncio.run(PlanExecutor({"enum_extract":Adapter(),"threat_mapping":Adapter()}).execute(plan,
        ExecutionContext(make_session_state(),SessionFacts(has_logs=True),checkpoint=checkpoint),continuation=continuation))
    assert result.status == StepStatus.SUCCESS and calls == ["threat"]
    assert len(result.results)==2 and checkpoint["recovery_count"]==2 and checkpoint["step_recovery_counts"]=={"enum":1}


def test_resume_rejects_changed_frozen_plan_and_wrong_ledger():
    plan=DeterministicPlan(plan_id="resume",steps=(EnumExtractStep(step_id="enum",type="enum_extract",target_field="alarm"),))
    continuation=ExecutionContinuation("execute_plan",(),asdict(RecoveryBudget()),"digest",frozen_plan={})
    with pytest.raises(ValueError,match="continuation_plan_mismatch"):
        asyncio.run(PlanExecutor({}).execute(plan,ExecutionContext(make_session_state(),SessionFacts()),continuation=continuation))
    bad=ExecutionContinuation("execute_plan",("wrong",),asdict(RecoveryBudget()),"digest",frozen_plan=plan.model_dump(mode="json"))
    with pytest.raises(ValueError,match="continuation_ledger_invalid"):
        asyncio.run(PlanExecutor({}).execute(plan,ExecutionContext(make_session_state(),SessionFacts()),continuation=bad))


def test_resume_does_not_reset_retry_budget():
    plan=DeterministicPlan(plan_id="resume",steps=(EnumExtractStep(step_id="enum",type="enum_extract",target_field="alarm"),))
    calls=[]
    class Failing:
        async def execute(self,*args):
            calls.append(1); raise TimeoutError("SECRET")
    continuation=ExecutionContinuation("execute_plan",(),asdict(RecoveryBudget()),"digest",frozen_plan=plan.model_dump(mode="json"),recovery_count=2)
    with private_business_logging():
        result=asyncio.run(PlanExecutor({"enum_extract":Failing()}).execute(plan,ExecutionContext(make_session_state(),SessionFacts(has_logs=True)),continuation=continuation))
    assert result.status == StepStatus.FAILED and len(calls)==1


def test_private_logs_sanitize_args_exception_extra_to_thread_and_restore():
    output=StringIO(); logger=logging.getLogger("privacy-test"); logger.setLevel(logging.INFO)
    class AllFields(logging.Formatter):
        def format(self,record):
            return str(record.__dict__)
    handler=logging.StreamHandler(output); handler.setFormatter(AllFields()); logger.addHandler(handler)
    def emit():
        try: raise ValueError("SECRET-EXCEPTION")
        except ValueError: logger.exception("SECRET-MESSAGE %s","SECRET-ARGS",extra={"payload":"SECRET-EXTRA"})
    async def scoped():
        with private_business_logging():
            emit(); await asyncio.to_thread(emit)
    asyncio.run(scoped())
    assert "SECRET" not in output.getvalue()
    logger.info("CHAINLIT-UNCHANGED %s","VISIBLE",extra={"payload":"VISIBLE-EXTRA"})
    assert "CHAINLIT-UNCHANGED" in output.getvalue() and "VISIBLE-EXTRA" in output.getvalue()
    logger.removeHandler(handler)


def test_private_scope_isolated_between_async_requests():
    output=StringIO(); logger=logging.getLogger("privacy-parallel"); logger.setLevel(logging.INFO)
    handler=logging.StreamHandler(output); logger.addHandler(handler)
    async def private():
        with private_business_logging():
            await asyncio.sleep(0); logger.info("SECRET-PRIVATE")
    async def public():
        await asyncio.sleep(0); logger.info("PUBLIC-CHAINLIT")
    async def together(): await asyncio.gather(private(),public())
    asyncio.run(together())
    assert "SECRET" not in output.getvalue() and "PUBLIC-CHAINLIT" in output.getvalue()
    logger.removeHandler(handler)


def test_clear_removes_attachment_contributions_and_pending_refills():
    """业务清空必须同时移除跨轮附件、填充贡献及重填状态。"""
    from application.request_runtime import clear_session_data, is_explicit_clear_command
    keys = ("decoded_data", "raw_log_lines", "latest_enum_artifact", "latest_threat_artifact",
        "enum_mapping_sheets", "enum_fill_contributions", "stale_enum_config_refs", "enum_pending_refills")
    session = make_session_state(**{key: "PRIVATE" for key in keys}, current_provider="kept")
    assert is_explicit_clear_command("清空数据！")
    clear_session_data(session)
    assert all(not getattr(session, key) for key in keys)
    assert session.current_provider == "kept"
