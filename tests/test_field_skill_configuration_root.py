"""Field Skill preserves uploaded configuration roots for both UI entries."""
import asyncio
import copy
import pytest
from application.request_runtime import run_deterministic_plan
from application.session_state import SessionState
from application.progress import NullProgressSink
from contracts.planner_models import DeterministicPlan, StepStatus


@pytest.mark.parametrize('operation', [
    {'type':'add_fields','field_name':'new','field_value':'fixed'},
    {'type':'delete_fields','fields':['source']},
    {'type':'decode_fields','fields':['source']},
    {'type':'merge_fields','source_fields':['source','other'],'target_field':'joined'},
    {'type':'regex_extract','source_field':'source','new_field':'part','description':'提取值','pattern':'(value)'},
])
def test_field_skill_keeps_dict_root_metadata_and_does_not_mutate_input(operation):
    root={'meta':'中文', 'rules':[{'name':'rule','normalize':[{'index':'source','result':['value']},{'index':'other','result':['second']}]}]}
    original=copy.deepcopy(root)
    session=SessionState(decoded_data=root)
    plan=DeterministicPlan.model_validate({'plan_id':'root','steps':[{'step_id':'change','config_ref':'session.decoded_config',**operation}]})
    result=asyncio.run(run_deterministic_plan(session=session,team=None,plan=plan,progress_sink=NullProgressSink()))
    assert result.status == StepStatus.SUCCESS, result
    assert session.decoded_data['meta']=='中文' and isinstance(session.decoded_data['rules'],list)
    assert root == original and session.mapped_sub_rules is None
