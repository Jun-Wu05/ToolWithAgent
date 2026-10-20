"""Field change grouping and preparation exercise real Application adapters offline."""
import asyncio
import pytest
from contracts.planner_models import PlanDecision
from toolwithagent_v2.runtime.field_changes import atomic_groups, prepare_fields, apply_fields
from toolwithagent_v2.runtime.postprocessing import BusinessSession, freeze_session


def decision(steps):
    return PlanDecision.model_validate({'decision': 'execute', 'plan_id': 'field-test', 'steps': steps})


def add(name, id=None, **extra):
    return {'type': 'add_fields', 'step_id': id or name, 'field_name': name, 'field_value': 'fixed', 'config_ref': 'session.mapped_sub_rules', **extra}


def session():
    return BusinessSession(mapped_sub_rules=[{'name': 'rule', 'normalize': [{'index': 'source', 'result': ['value']}]}])


def test_groups_join_same_field_and_declared_cross_field_dependency():
    steps = decision([add('a'), add('b'), {'type': 'decode_fields', 'step_id': 'decode', 'fields': ['a'], 'config_ref': 'session.mapped_sub_rules', 'depends_on': ['b']}]).steps
    groups = atomic_groups(steps)
    assert [[step.step_id for step in group['steps']] for group in groups] == [['a', 'b', 'decode']]


def test_prepare_does_not_mutate_session_and_selection_replays_shared_skills():
    original = session(); before = freeze_session(original)
    prepared = asyncio.run(prepare_fields(original, decision([add('a'), add('b')])))
    assert freeze_session(original) == before and len(prepared['groups']) == 2 and not prepared['direct']
    applied, payload = asyncio.run(apply_fields(prepared, ['group-2']))
    assert [item['index'] for item in applied.mapped_sub_rules[0]['normalize']] == ['source', 'b']
    assert payload['download_content'] and freeze_session(original) == before
    with pytest.raises(ValueError, match='field_selection_invalid'):
        asyncio.run(apply_fields(prepared, ['unknown']))


def test_single_explicit_non_delete_is_direct_but_multiple_rules_are_not():
    assert asyncio.run(prepare_fields(session(), decision([add('a')])) )['direct']
    original = session(); original.mapped_sub_rules *= 2
    assert not asyncio.run(prepare_fields(original, decision([add('a')])) )['direct']


def test_failed_preparation_rolls_back_whole_version():
    original = session(); before = freeze_session(original)
    with pytest.raises(ValueError):
        asyncio.run(prepare_fields(original, decision([add('a'), add('source')])))
    assert freeze_session(original) == before

class FieldPlanner:
    def __init__(self, steps):
        self.steps = steps; self.calls = 0
    async def plan(self, **kwargs):
        self.calls += 1
        return decision(self.steps)


def test_api_selection_restart_apply_new_run_and_whole_version_undo(tmp_path):
    from test_postprocessing import setup, rules, current
    from toolwithagent_v2.infrastructure.store import Store
    from toolwithagent_v2.runtime.worker import Worker
    from toolwithagent_v2.settings import Settings
    steps = [{**add('a'), 'config_ref': 'session.decoded_config'}, {**add('b'), 'config_ref': 'session.decoded_config'}]
    planner = FieldPlanner(steps)
    client, store, conversation, worker = setup(tmp_path, planner)
    rules(client, conversation, worker)
    original = client.post(f'/api/v2/conversations/{conversation}/messages', json={'content': '添加a和b'}).json()['run']['id']
    assert worker.once()
    assert store.get_run('dev-user', original)['status'] == 'waiting_confirmation'
    preview = client.get(f'/api/v2/runs/{original}/field-change-preview').json()
    assert len(preview['groups']) == 2 and preview['current']
    selected = client.post(f'/api/v2/runs/{original}/field-change-selection', json={'selected_group_ids': ['group-2']}, headers={'If-Match': str(preview['revision']), 'Idempotency-Key': 'selection'})
    assert selected.status_code == 200, selected.text
    preview = selected.json()
    headers = {'If-Match': str(preview['revision']), 'Idempotency-Key': 'apply'}
    applied = client.post(f'/api/v2/runs/{original}/field-change-apply', json={}, headers=headers)
    assert applied.status_code == 201, applied.text
    assert client.post(f'/api/v2/runs/{original}/field-change-apply', json={}, headers=headers).json() == applied.json()
    new_run = applied.json()['run']['id']; assert new_run != original
    restarted = Store(Settings(data_dir=store.root))
    assert Worker(restarted, 'worker', business_application=worker.business_application).once()
    assert restarted.get_run('dev-user', new_run)['status'] == 'succeeded'
    artifact = current(restarted, conversation, 'field_mapping')
    payload = client.get(f"/api/v2/artifacts/{artifact['id']}/content").json()
    assert [item['index'] for item in payload['config'][0]['normalize']][-1] == 'b'
    assert all(item['index'] != 'a' for item in payload['config'][0]['normalize'])
    final = client.get(f'/api/v2/runs/{original}/field-change-preview').json()
    assert [group['status'] for group in final['groups']] == ['not_applied_by_user', 'applied']
    undo = client.post(f"/api/v2/artifacts/{artifact['id']}/undo", headers={'Idempotency-Key': 'undo'})
    assert undo.status_code == 201, undo.text
    assert worker.once()
    assert store.get_run('dev-user', undo.json()['run']['id'])['status'] == 'succeeded'
    restored = current(store, conversation, 'field_mapping')
    assert restored['id'] != artifact['id']
    root = client.get(f"/api/v2/artifacts/{restored['id']}/content").json()
    assert all(item['index'] not in {'a', 'b'} for item in root['config'][0]['normalize'])
    assert planner.calls == 1

def make_preview(tmp_path, steps=None):
    from test_postprocessing import setup, rules
    steps = steps or [{**add('a'), 'config_ref': 'session.decoded_config'}, {**add('b'), 'config_ref': 'session.decoded_config'}]
    client, store, conversation, worker = setup(tmp_path, FieldPlanner(steps))
    rules(client, conversation, worker)
    run = client.post(f'/api/v2/conversations/{conversation}/messages', json={'content': '调整字段'}).json()['run']['id']
    assert worker.once()
    response = client.get(f'/api/v2/runs/{run}/field-change-preview')
    assert response.status_code == 200, response.text
    return client, store, conversation, worker, response.json()


def test_multi_field_delete_groups_can_be_selected_independently_and_confirmed_once(tmp_path):
    client, store, conversation, worker, preview = make_preview(tmp_path, [{'type':'delete_fields', 'step_id':'delete', 'fields':['alarm','status'], 'config_ref':'session.decoded_config'}])
    assert len(preview['groups']) == 2
    url = f"/api/v2/runs/{preview['run_id']}/field-change-apply"
    headers = {'If-Match':'1','Idempotency-Key':'apply-missing-token'}
    assert client.post(url,json={},headers=headers).status_code == 409
    confirmation_url = f"/api/v2/tasks/{preview['task_id']}/confirmations"
    confirmation_headers = {'If-Match':'1','Idempotency-Key':'delete-token'}
    approval = client.post(confirmation_url,headers=confirmation_headers).json()
    assert approval['payload']['deletes'] == ['alarm','status']
    assert client.post(confirmation_url,headers=confirmation_headers).json() == approval
    # Selection changes invalidate a token even when subsequently selecting the same groups.
    selected = client.post(f"/api/v2/runs/{preview['run_id']}/field-change-selection",json={'selected_group_ids':['group-1']},headers={'If-Match':'1','Idempotency-Key':'select-one'}).json()
    assert selected['revision'] == 2
    assert client.post(url,json={'token':approval['token']},headers={'If-Match':'2','Idempotency-Key':'stale-token'}).status_code == 409
    approval = client.post(confirmation_url,headers={'If-Match':'2','Idempotency-Key':'new-token'}).json()
    assert approval['payload']['deletes'] == ['alarm']
    result = client.post(url,json={'token':approval['token']},headers={'If-Match':'2','Idempotency-Key':'valid-token'})
    assert result.status_code == 201, result.text
    assert worker.once()
    assert store.get_run('dev-user',result.json()['run']['id'])['status'] == 'succeeded'
    assert client.post(f"/api/v2/runs/{preview['run_id']}/confirm",json={'token':approval['token'],'checkpoint_revision':2}).status_code == 409


def test_selection_permissions_revision_and_idempotency(tmp_path):
    client, store, conversation, worker, preview = make_preview(tmp_path)
    path = f"/api/v2/runs/{preview['run_id']}/field-change-selection"
    assert client.post(path,json={'selected_group_ids':[]},headers={'Idempotency-Key':'missing-revision'}).status_code == 428
    assert client.post(path,json={'selected_group_ids':['invented']},headers={'If-Match':'1','Idempotency-Key':'unknown'}).status_code == 400
    headers={'If-Match':'1','Idempotency-Key':'saved'}
    response=client.post(path,json={'selected_group_ids':['group-1']},headers=headers)
    assert response.status_code == 200
    assert client.post(path,json={'selected_group_ids':['group-1']},headers=headers).json() == response.json()
    assert client.post(path,json={'selected_group_ids':[]},headers=headers).status_code == 409
    assert client.post(path,json={'selected_group_ids':[]},headers={'If-Match':'1','Idempotency-Key':'old-revision'}).status_code == 409
    client.cookies.set('v2_dev_user','dev-other')
    assert client.get(f"/api/v2/runs/{preview['run_id']}/field-change-preview").status_code == 404
    assert client.post(path,json={'selected_group_ids':[]},headers={'If-Match':'2','Idempotency-Key':'other'}).status_code == 403


def test_cancelled_preview_cannot_apply_or_resume(tmp_path):
    client, store, conversation, worker, preview = make_preview(tmp_path)
    run=preview['run_id']
    token=client.post(f'/api/v2/runs/{run}/cancel-token').json()['token']
    assert client.post(f'/api/v2/runs/{run}/cancel',json={'token':token}).status_code == 200
    assert client.get(f'/api/v2/runs/{run}/field-change-preview').json()['status'] == 'cancelled'
    assert client.post(f'/api/v2/runs/{run}/field-change-apply',json={},headers={'If-Match':'1','Idempotency-Key':'late'}).status_code == 409
    assert not worker.once()


def test_direct_change_automatically_creates_new_deterministic_run(tmp_path):
    from test_postprocessing import current
    client, store, conversation, worker, preview = make_preview(tmp_path,[{**add('one'),'config_ref':'session.decoded_config'}])
    assert preview['status'] == 'applying' and preview['apply_run_id'] != preview['run_id']
    assert store.get_run('dev-user',preview['run_id'])['status'] == 'succeeded'
    assert worker.once()
    assert current(store,conversation,'field_mapping')['run_id'] == preview['apply_run_id']


def test_apply_failure_preserves_preview_and_publishes_no_partial_results(tmp_path,monkeypatch):
    from toolwithagent_v2.infrastructure.db import connect
    from toolwithagent_v2.runtime import field_changes
    client, store, conversation, worker, preview = make_preview(tmp_path)
    with connect(store.path) as db:
        before=[tuple(row) for row in db.execute('SELECT id,status FROM artifacts ORDER BY id')]
    run=client.post(f"/api/v2/runs/{preview['run_id']}/field-change-apply",json={},headers={'If-Match':'1','Idempotency-Key':'apply'}).json()['run']['id']
    async def fail(*args,**kwargs):
        raise ValueError('field_conflict')
    monkeypatch.setattr(field_changes,'apply_fields',fail)
    assert worker.once()
    assert store.get_run('dev-user',run)['status'] == 'failed'
    with connect(store.path) as db:
        assert [tuple(row) for row in db.execute('SELECT id,status FROM artifacts ORDER BY id')] == before
    assert client.get(f"/api/v2/runs/{preview['run_id']}/field-change-preview").json()['status'] == 'ready'


def test_all_unselected_groups_settle_as_not_applied(tmp_path):
    client, store, conversation, worker, preview = make_preview(tmp_path)
    updated=client.post(f"/api/v2/runs/{preview['run_id']}/field-change-selection",json={'selected_group_ids':[]},headers={'If-Match':'1','Idempotency-Key':'none'}).json()
    result=client.post(f"/api/v2/runs/{preview['run_id']}/field-change-apply",json={},headers={'If-Match':str(updated['revision']),'Idempotency-Key':'settle'})
    assert result.status_code == 201,result.text
    assert worker.once()
    assert store.get_run('dev-user',result.json()['run']['id'])['status'] == 'succeeded'
    assert all(group['status']=='not_applied_by_user' for group in client.get(f"/api/v2/runs/{preview['run_id']}/field-change-preview").json()['groups'])

def test_remaining_business_work_is_replanned_after_final_selection(tmp_path):
    from test_postprocessing import setup, rules
    class CompoundPlanner:
        calls=[]
        async def plan(self, **kwargs):
            self.calls.append(kwargs['user_text'])
            if len(self.calls)==1:
                return decision([{**add('a'),'config_ref':'session.decoded_config'}, {**add('b'),'config_ref':'session.decoded_config'}, {'step_id':'export','type':'export','source_ref':'session.decoded_config'}])
            assert '用户未应用' in kwargs['user_text'] and '"b"' in kwargs['user_text']
            return decision([{'step_id':'export-final','type':'export','source_ref':'session.decoded_config'}])
    planner=CompoundPlanner()
    client,store,conversation,worker=setup(tmp_path,planner); rules(client,conversation,worker)
    source=client.post(f'/api/v2/conversations/{conversation}/messages',json={'content':'添加a和b然后导出'}).json()['run']['id'];assert worker.once()
    assert client.post(f'/api/v2/runs/{source}/field-change-selection',json={'selected_group_ids':['group-1']},headers={'If-Match':'1','Idempotency-Key':'one'}).status_code==200
    run=client.post(f'/api/v2/runs/{source}/field-change-apply',json={},headers={'If-Match':'2','Idempotency-Key':'apply'}).json()['run']['id']
    assert worker.once() and store.get_run('dev-user',run)['status']=='succeeded'
    assert worker.once() and len(planner.calls)==2
    assert store.get_conversation('dev-user',conversation)['runs'][-1]['status']=='succeeded'


def test_worker_loss_releases_apply_and_invalidates_old_confirmation(tmp_path):
    from toolwithagent_v2.infrastructure.db import connect
    client,store,conversation,worker,preview=make_preview(tmp_path)
    applied=client.post(f"/api/v2/runs/{preview['run_id']}/field-change-apply",json={},headers={'If-Match':'1','Idempotency-Key':'apply'}).json()['run']['id']
    claim=store.claim('worker');assert claim['id']==applied
    with connect(store.path) as db:
        db.execute("UPDATE runs SET lease_expires_at='2000' WHERE id=?",(applied,))
    assert store.claim('worker') is None
    row=client.get(f"/api/v2/runs/{preview['run_id']}/field-change-preview").json()
    assert row['status']=='ready' and row['revision']==2
    assert store.publish_business('worker',claim,[]) is False
    cancelled=client.post(f"/api/v2/runs/{preview['run_id']}/field-change-cancel",headers={'If-Match':'2','Idempotency-Key':'cancel'})
    assert cancelled.status_code==200,cancelled.text


def test_undo_stales_transitive_downstream_without_deleting_history(tmp_path):
    from toolwithagent_v2.infrastructure.db import connect
    client,store,conversation,worker,preview=make_preview(tmp_path,[{**add('single'),'config_ref':'session.decoded_config'}])
    assert worker.once()
    row=client.get(f"/api/v2/runs/{preview['run_id']}/field-change-preview").json();artifact=row['applied_artifact_id']
    with connect(store.path) as db:
        original=db.execute('SELECT * FROM artifacts WHERE id=?',(artifact,)).fetchone()
        for id in ('descendant','grandchild','independent'):
            db.execute('INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,metadata_json,created_at) VALUES(?,?,?,?,?,1,?,?,?)',(id,conversation,original['task_id'],original['run_id'],'test_lineage','published','{}',original['created_at']))
        db.execute('INSERT INTO artifact_edges VALUES(?,?,?)',(artifact,'descendant','test'))
        db.execute('INSERT INTO artifact_edges VALUES(?,?,?)',('descendant','grandchild','test'))
    result=client.post(f'/api/v2/artifacts/{artifact}/undo',headers={'Idempotency-Key':'undo'})
    assert result.status_code==201,result.text
    assert worker.once()
    with connect(store.path) as db:
        statuses={item['id']:item['status'] for item in db.execute("SELECT id,status FROM artifacts WHERE id IN (?,?,?,?)",(artifact,'descendant','grandchild','independent'))}
    assert statuses=={artifact:'stale','descendant':'stale','grandchild':'stale','independent':'published'}
    assert client.post(f'/api/v2/artifacts/{artifact}/undo',headers={'Idempotency-Key':'undo'}).json()==result.json()
    assert client.post(f'/api/v2/artifacts/{artifact}/undo',headers={'Idempotency-Key':'different'}).status_code==409

def test_regex_is_generated_once_and_frozen_for_apply(monkeypatch):
    from agent.shared import regex_extract
    calls=[]
    async def generate(*args,**kwargs):
        calls.append(args)
        return '(value)'
    monkeypatch.setattr(regex_extract,'generate_extraction_pattern',generate)
    plan=decision([{'step_id':'extract','type':'regex_extract','source_field':'source','new_field':'part','description':'提取值','config_ref':'session.mapped_sub_rules'}])
    prepared=asyncio.run(prepare_fields(session(),plan))
    assert len(calls)==1 and prepared['groups'][0]['steps'][0]['pattern']=='(value)'
    applied,payload=asyncio.run(apply_fields(prepared,['group-1']))
    assert len(calls)==1 and any(item['index']=='part' for item in payload['config'][0]['normalize'])


def test_same_field_standard_alias_is_not_separately_selectable():
    original=session();original.mapped_sub_rules[0]['normalize'][0]['field']='源地址'
    prepared=asyncio.run(prepare_fields(original,decision([
        {'step_id':'decode','type':'decode_fields','fields':['源地址'],'config_ref':'session.mapped_sub_rules'},
        {'step_id':'delete','type':'delete_fields','fields':['source'],'config_ref':'session.mapped_sub_rules'}])))
    assert len(prepared['groups'])==1


def test_atomic_dependency_merge_closes_transitively():
    plan=decision([add('first'),add('second'),{'step_id':'bridge','type':'merge_fields','source_fields':['first','second'],'target_field':'joined','config_ref':'session.mapped_sub_rules'}])
    assert len(atomic_groups(plan.steps))==1

def test_event_binding_pair_is_deleted_once_as_one_group():
    original=session()
    original.mapped_sub_rules[0]['normalize'].extend([{'index':'事件名称','result':['其他告警']},{'index':'事件级别','result':['提醒']}])
    prepared=asyncio.run(prepare_fields(original,decision([{'step_id':'delete','type':'delete_fields','fields':['事件名称','事件级别'],'config_ref':'session.mapped_sub_rules'}])))
    assert len(prepared['groups'])==1 and len(prepared['groups'][0]['steps'])==1
    restored,payload=asyncio.run(apply_fields(prepared,['group-1']))
    assert all(item['index'] not in {'事件名称','事件级别'} for item in payload['config'][0]['normalize'])


def test_combined_add_and_decode_preview_contains_runtime_filter_changes():
    prepared=asyncio.run(prepare_fields(session(),decision([add('a'),{'step_id':'decode','type':'decode_fields','fields':['a'],'config_ref':'session.mapped_sub_rules'}])))
    assert len(prepared['groups'])==1
    runtime=[item for item in prepared['groups'][0]['changes'] if item['field'].endswith('（运行时处理）')]
    assert runtime and runtime[0]['after'] and runtime[0]['before'] != runtime[0]['after']

def test_field_adjustment_preserves_mapping_samples_annotations_and_warnings():
    base={'mapping_rows':[{'原始字段名':'source','系统属性名称':'源地址','匹配状态':'成功'}], 'samples':{'rule':{'source':['value']}}, 'event_annotations':[{'rule_name':'rule','status':'uncertain'}], 'warnings':[{'code':'threat_chain_warning','message':'既有提醒'}]}
    prepared=asyncio.run(prepare_fields(session(),decision([add('a')]),base=base))
    _,payload=asyncio.run(apply_fields(prepared,['group-1']))
    assert all(payload[key]==value for key,value in base.items())
    assert prepared['base_payload']==base
