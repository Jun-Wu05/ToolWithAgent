import json
import pytest
from fastapi.testclient import TestClient
from toolwithagent_v2.api.app import create_app
from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.runtime.worker import Worker
from toolwithagent_v2.settings import Settings

class MappingBusiness:
    fail = False
    async def parse(self, path, snapshot):
        return {'classification': {'status':'SUCCESS','classification_details':[]}, 'total_lines':3, 'submission_eligible':False}
    async def field_mapping(self, path, snapshot, classification=None):
        if self.fail:
            return {'error':'field_mapping_incomplete'}
        return {'config':[{'name':'rule','normalize':[{'index':'src','field':'源地址','result':['SECRET']},{'index':'unknown','field':None,'result':['VALUE']}]}], 'mapping_rows':[{'原始字段名':'src','系统属性名称':'源地址','匹配状态':'匹配成功'},{'原始字段名':'unknown','系统属性名称':'未匹配','匹配状态':'未匹配'}], 'samples': {'0': {'src':[{'value':'SECRET','line_number':1}], 'unknown':[{'value':'VALUE','line_number':1}]}}, 'download_kind':'mapped_sub_rules','download_content':'COMPATIBLE-BYTES'}

def setup(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path/'data')))
    store = client.app.state.store
    conversation = client.post('/api/v2/conversations',json={}).json()['id']
    business = MappingBusiness()
    worker = Worker(store,'worker-a',business_application=business)
    response=client.post(f'/api/v2/conversations/{conversation}/files',files={'file':('logs.txt',b'kind=a src=SECRET\n')})
    assert worker.once()
    # 分叉②（#435）：映射统一要求当前分类产物，脚手架先完成一次日志类型提取。
    client.post(f'/api/v2/conversations/{conversation}/log-parse',json={'file_id':response.json()['file']['id']})
    assert worker.once()
    return client,store,conversation,worker,business,response.json()['file']['id']

def enqueue(client, conversation, file_id, **extra):
    return client.post(f'/api/v2/conversations/{conversation}/field-mapping', json={'file_id':file_id,'product':'PRODUCT-PRIVATE','log_vendor':'VENDOR-PRIVATE',**extra},headers={'Idempotency-Key':extra.get('key','mapping-one')})

def mappings(store,conversation):
    return [a for a in store.get_conversation('dev-user',conversation)['artifacts'] if a['kind']=='field_mapping']

def test_mapping_publish_safe_summary_view_download_and_restart(tmp_path):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    response=enqueue(client,conversation,file_id)
    assert response.status_code==201,response.text
    assert enqueue(client,conversation,file_id).json()==response.json()
    assert worker.once()
    artifact=mappings(store,conversation)[0]
    assert artifact['summary']['matched_count']==1
    assert artifact['summary']['unmatched_count']==1
    assert artifact['current']
    safe=store.get_conversation('dev-user',conversation)
    assert all(secret not in str(safe) for secret in ('SECRET','VALUE'))
    # owner 亲填的表单参数只允许出现在自己的 operation 输入记录里，不进产物或事件。
    records=[m for m in safe['messages'] if m.get('kind')=='operation']
    assert all(secret not in json.dumps([m for m in safe['messages'] if m.get('kind')!='operation'],ensure_ascii=False) for secret in ('PRODUCT-PRIVATE','VENDOR-PRIVATE'))
    assert any('PRODUCT-PRIVATE' in json.dumps(m,ensure_ascii=False) for m in records)
    view=client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").json()
    assert view['items'][0]['samples']==['SECRET']
    assert view['page_size']==50
    assert not any('confidence' in item for item in view['items'])
    download=client.get(f"/api/v2/artifacts/{artifact['id']}/download")
    assert download.content==b'COMPATIBLE-BYTES'
    assert 'fieldmapped_subrules_' in download.headers['content-disposition']
    assert mappings(Store(Settings(data_dir=store.root)),conversation)[0]['id']==artifact['id']
    changed=enqueue(client,conversation,file_id,product='OTHER')
    assert changed.status_code==409

@pytest.mark.parametrize('change',['cancel','new_file','classification'])
def test_late_mapping_cannot_publish_after_input_or_claim_change(tmp_path,change):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    response=enqueue(client,conversation,file_id)
    assert response.status_code==201,response.text
    claim=store.claim('worker-a')
    if change=='cancel':
        token=store.issue_cancel_token('dev-user',claim['id'])['token']; store.cancel('dev-user',claim['id'],token)
    elif change=='new_file':
        client.post(f'/api/v2/conversations/{conversation}/files',files={'file':('new.txt',b'kind=b\n')})
        with __import__('toolwithagent_v2.infrastructure.db',fromlist=['connect']).connect(store.path) as db:
            db.execute("UPDATE files SET parse_status='succeeded' WHERE id<>?",(file_id,))
    else:
        with __import__('toolwithagent_v2.infrastructure.db',fromlist=['connect']).connect(store.path) as db:
            run_id=store._enqueue_task(db,'dev-user',conversation,'log_parse',claim['input'])['run']['id']
            db.execute("UPDATE runs SET status='cancelled' WHERE id=?",(run_id,))
            db.execute("INSERT INTO artifacts(id,conversation_id,task_id,run_id,kind,version,status,storage_key,sha256,metadata_json,created_at,size) VALUES('changed',?,(SELECT task_id FROM runs WHERE id=?),?,'log_classification',1,'published','artifacts/x','x','{}','2999',0)",(conversation,run_id,run_id))
    worker._run_field_mapping(claim)
    assert mappings(store,conversation)==[]

def test_file_entry_mapping_reuses_current_classification_artifact(tmp_path):
    """文件入口映射：无分类产物被拒绝并引导先提取；有分类则与其同源锚定（#432/#435 分叉②）。"""
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    with __import__('toolwithagent_v2.infrastructure.db',fromlist=['connect']).connect(store.path) as db:
        db.execute("UPDATE artifacts SET status='stale' WHERE kind='log_classification'")
    seen=[]
    original=business.field_mapping
    async def capture(path,snapshot,classification=None):
        seen.append(classification is not None)
        return await original(path,snapshot,classification)
    business.field_mapping=capture
    rejected=enqueue(client,conversation,file_id,key='no-classification')
    assert rejected.status_code==400
    assert rejected.json()['error']['code']=='classification_required'
    client.post(f'/api/v2/conversations/{conversation}/log-parse',json={'file_id':file_id})
    assert worker.once()
    classified=[a for a in store.get_conversation('dev-user',conversation)['artifacts'] if a['kind']=='log_classification' and a['status']=='published'][0]
    assert enqueue(client,conversation,file_id,key='with-classification').status_code==201
    claim=store.claim('worker-a')
    assert claim['input']['source_artifact_id']==classified['id']
    assert 'source_sha256' in claim['input'] and 'source_storage_key' in claim['input']
    assert claim['input']['classification_anchor']==classified['id']
    assert worker._run_field_mapping(claim)
    assert seen==[True]
    assert len(mappings(store,conversation))==1

def test_failure_keeps_old_result_and_invalid_upload_does_not_stale_it(tmp_path):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    assert enqueue(client,conversation,file_id).status_code==201
    assert worker.once()
    first=mappings(store,conversation)[0]
    bad=client.post(f'/api/v2/conversations/{conversation}/files',files={'file':('bad.json',b'{broken')})
    assert worker.once()
    assert mappings(store,conversation)[0]['current']
    business.fail=True
    assert enqueue(client,conversation,file_id,key='retry').status_code==201
    assert worker.once()
    assert mappings(store,conversation)[0]['id']==first['id']

@pytest.mark.parametrize('role',['dev-other','dev-admin'])
def test_role_and_resource_guards(tmp_path,role):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    assert enqueue(client,conversation,file_id).status_code==201; assert worker.once()
    artifact=mappings(store,conversation)[0]
    client.post('/api/v2/dev/session',json={'user_id':role})
    assert enqueue(client,conversation,file_id).status_code==403
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").status_code==404
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/download").status_code==404


def test_view_filters_before_paging_and_validates_queries():
    from toolwithagent_v2.runtime.mapping_projection import mapping_view
    payload={'config':[{'name':'many','normalize':[{'index':f'field_{i}','field':None} for i in range(65)]}],
             'mapping_rows':[{'原始字段名':f'field_{i}','系统属性名称':'未匹配','匹配状态':'未匹配'} for i in range(65)]}
    assert len(mapping_view(payload)['items'])==50
    assert len(mapping_view(payload,page=2)['items'])==15
    assert mapping_view(payload,q='field_64')['items'][0]['source_path']=='field_64'
    assert mapping_view(payload,status='matched')['total']==0
    with pytest.raises(ValueError): mapping_view(payload,page=0)
    with pytest.raises(ValueError): mapping_view(payload,sub_rule='missing')


def test_new_valid_file_stales_old_result_but_retains_owner_view(tmp_path):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    assert enqueue(client,conversation,file_id).status_code==201; assert worker.once()
    artifact=mappings(store,conversation)[0]
    client.post(f'/api/v2/conversations/{conversation}/files',files={'file':('new.txt',b'kind=b\n')})
    assert worker.once()
    assert not mappings(store,conversation)[0]['current']
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").status_code==200
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/download").status_code==200
    assert enqueue(client,conversation,file_id,key='old').json()['error']['code']=='mapping_input_stale'


def test_classification_input_is_frozen_and_foreign_user_rejected(tmp_path):
    from toolwithagent_v2.infrastructure.db import connect
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    client.post(f'/api/v2/conversations/{conversation}/log-parse',json={'file_id':file_id}); assert worker.once()
    artifact=[a for a in store.get_conversation('dev-user',conversation)['artifacts'] if a['kind']=='log_classification'][-1]
    assert artifact['mapping_eligible']
    response=client.post(f'/api/v2/conversations/{conversation}/field-mapping',json={'classification_artifact_id':artifact['id'],'product':'p','log_vendor':'v'})
    assert response.status_code==201,response.text; assert worker.once()
    mapped=mappings(store,conversation)[0]
    assert mapped['source_artifact_id']==artifact['id']
    with connect(store.path) as db:
        assert db.execute('SELECT 1 FROM artifact_edges WHERE source_artifact_id=? AND derived_artifact_id=?',(artifact['id'],mapped['id'])).fetchone()
        db.execute("INSERT INTO users(id,display_name,role,is_active,created_at) VALUES('other','other','user',1,'now')")
    client.post('/api/v2/dev/session',json={'user_id':'other'})
    assert client.get(f"/api/v2/artifacts/{mapped['id']}/mapping-view").status_code==404
    assert client.get(f"/api/v2/artifacts/{mapped['id']}/download").status_code==404


def test_corrupt_blob_refuses_view_and_download(tmp_path):
    from toolwithagent_v2.infrastructure.db import connect
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    assert enqueue(client,conversation,file_id).status_code==201; assert worker.once()
    artifact=mappings(store,conversation)[0]
    with connect(store.path) as db:
        key=db.execute('SELECT storage_key FROM artifacts WHERE id=?',(artifact['id'],)).fetchone()[0]
    (store.root/key).write_bytes(b'corrupt')
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").json()['error']['code']=='artifact_corrupt'
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/download").json()['error']['code']=='artifact_corrupt'


def test_public_bridge_runs_real_mapping_adapter_and_compat_export(tmp_path):
    import asyncio, base64
    from types import SimpleNamespace
    from application.adapters import create_default_adapters
    from application.adapters.field_mapping import FieldMappingAdapter
    from toolwithagent_v2.runtime.business_application import BusinessApplication
    calls=[]
    class Member:
        name='FieldMappingAgent'
        async def arun(self, prompt, **kwargs):
            calls.append(prompt)
            yield SimpleNamespace(event='RunCompleted',content=[{'原始字段名':'src','系统属性名称':'源地址','匹配状态':'匹配成功'},{'原始字段名':'kind','系统属性名称':'未匹配','匹配状态':'未匹配'}])
    async def event_classifier(prompt):
        signals=json.loads(prompt.split('## 待判定子规则\n```json\n')[1].split('\n```')[0])
        return json.dumps({'results':[{'rule_name':signal['rule_name'],'event_name':'登录事件','group':'non_threat'} for signal in signals]},ensure_ascii=False)
    def adapters(team):
        result=create_default_adapters(team)
        result['field_mapping']=FieldMappingAdapter(team,candidate_retriever=lambda _: {},event_classifier=event_classifier)
        return result
    source=tmp_path/'log.txt'; source.write_text('kind=a src=1\nkind=a src=2\nkind=a src=3\n',encoding='utf-8')
    classification={'classification':{'status':'SUCCESS','log_format':'KV','feature_field':'kind',
        'analysis':{'has_key_value_pairs':True,'delimit':' ','tab':'='},
        'classification_details':[{'logtype':'a','count':3,'real_samples':'kind=a src=1'}]}}
    bridge=BusinessApplication(tmp_path/'knowledge.sqlite3',team_factory=lambda:SimpleNamespace(members=(Member(),)),adapters_factory=adapters)
    result=asyncio.run(bridge.field_mapping(source,{'media_type':'text/plain','source_fields':{'product':'p','log_vendor':'v'}},classification))
    assert 'error' not in result,result
    assert calls
    assert json.loads(base64.b64decode(result['download_content']))==result['config']
    src=next(entry for entry in result['config'][0]['normalize'] if entry['index']=='src')
    assert src['field']=='源地址'
    assert [item['value'] for item in result['samples']['0']['src']]==['1','2','3']
    assert [item['line_number'] for item in result['samples']['0']['src']]==[1,2,3]


def test_sample_reader_twenty_values_does_not_change_enum_rejection():
    from application.standard_enum_mapping import build_value_profiles_from_logs
    from toolwithagent_v2.runtime.mapping_projection import collect_samples
    config=[{'name':'kv','parser':{'name':'delimitWithKeyMap','tab':'=','delimit':' '},'normalize':[{'index':'src','result':[]}]}]
    lines=['', *[f'src={i}' for i in range(30)]]
    samples=collect_samples(config,lines,{})['0']['src']
    assert len(samples)==20
    assert samples[0]['line_number']==2
    profile=build_value_profiles_from_logs(config,lines,{})[('0','src')]
    assert profile.status=='rejected'
    assert profile.scanned_lines==30
    assert len(profile.values)==11


def test_frozen_old_claim_cannot_publish_after_retry(tmp_path):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    response=enqueue(client,conversation,file_id); assert response.status_code==201
    claim=store.claim('worker-a')
    token=store.issue_cancel_token('dev-user',claim['id'])['token']; store.cancel('dev-user',claim['id'],token)
    store.retry('dev-user',claim['id'])
    assert not store.publish('worker-a',claim,b'old',kind='field_mapping')
    assert mappings(store,conversation)==[]
    assert worker.once()
    assert len(mappings(store,conversation))==1


def test_same_input_remapping_supersedes_only_current_pointer(tmp_path):
    client,store,conversation,worker,business,file_id=setup(tmp_path)
    assert enqueue(client,conversation,file_id).status_code==201; assert worker.once()
    first=mappings(store,conversation)[0]
    assert enqueue(client,conversation,file_id,key='second').status_code==201; assert worker.once()
    results=mappings(store,conversation)
    assert len(results)==2
    assert [item['current'] for item in results]==[False,True]
    assert client.get(f"/api/v2/artifacts/{first['id']}/download").content==b'COMPATIBLE-BYTES'
