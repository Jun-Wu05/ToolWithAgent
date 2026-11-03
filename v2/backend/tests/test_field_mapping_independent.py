"""独立验证映射接口的输入、公开桥接、样例与隐私边界。"""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from test_field_mapping_slice import setup, enqueue, mappings


def test_mapping_input_exclusive_validated_and_same_conversation(tmp_path):
    """当前文件与分类只能显式择一，不能把同一用户其他会话输入带入。"""
    client, store, conversation, worker, business, file_id = setup(tmp_path)
    endpoint = f'/api/v2/conversations/{conversation}/field-mapping'
    fields = {'product': 'p', 'log_vendor': 'v'}
    for extra in ({}, {'file_id': file_id, 'classification_artifact_id': 'unused'}):
        response = client.post(endpoint, json={**fields, **extra})
        assert response.status_code == 400
        assert response.json()['error']['code'] == 'mapping_input_required'
    for invalid in ({'product': ' '}, {'log_vendor': ''}):
        response = client.post(endpoint, json={**fields, 'file_id': file_id, **invalid})
        assert response.status_code == 400
    uploaded = client.post(f'/api/v2/conversations/{conversation}/files', files={'file': ('queued.txt', b'kind=b')}).json()['file']['id']
    response = client.post(endpoint, json={**fields, 'file_id': uploaded})
    assert response.json()['error']['code'] == 'file_not_validated'
    assert worker.once()
    other = client.post('/api/v2/conversations', json={}).json()['id']
    response = client.post(f'/api/v2/conversations/{other}/field-mapping', json={**fields, 'file_id': uploaded})
    assert response.status_code == 404
    client.post(f'/api/v2/conversations/{conversation}/log-parse', json={'file_id': uploaded})
    assert worker.once()
    classified = store.get_conversation('dev-user', conversation)['artifacts'][0]['id']
    response = client.post(f'/api/v2/conversations/{other}/field-mapping', json={**fields, 'classification_artifact_id': classified})
    assert response.status_code == 404


def test_source_fields_frozen_and_events_and_diagnostics_safe(tmp_path):
    """执行只消费冻结来源信息，摘要及SSE事件源均不泄漏原值。"""
    client, store, conversation, worker, business, file_id = setup(tmp_path)
    response = enqueue(client, conversation, file_id, product='  PRODUCT-PRIVATE  ', log_vendor=' VENDOR-PRIVATE ')
    assert response.status_code == 201
    claim = store.claim('worker-a')
    assert claim['input']['source_fields'] == {'product': 'PRODUCT-PRIVATE', 'log_vendor': 'VENDOR-PRIVATE', 'data_source': 'PRODUCT-PRIVATE(VENDOR-PRIVATE)'}
    observed = []
    original = business.field_mapping
    async def capture(path, snapshot, classification=None):
        observed.append(snapshot['source_fields'].copy())
        return await original(path, snapshot, classification)
    business.field_mapping = capture
    assert worker._run_field_mapping(claim)
    assert observed == [claim['input']['source_fields']]
    artifact = mappings(store, conversation)[0]
    run_id = response.json()['run']['id']
    diagnostics = client.get(f'/api/v2/runs/{run_id}').json()
    events = store.events('dev-user', conversation, 0)
    for secret in ('SECRET', 'VALUE', 'PRODUCT-PRIVATE', 'VENDOR-PRIVATE'):
        assert secret not in json.dumps(diagnostics, ensure_ascii=False)
        assert secret not in json.dumps(events, ensure_ascii=False)
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").json()['items'][0]['samples'] == ['SECRET']


@pytest.mark.parametrize('outcome', ('unmatched', 'xlsx_unmatched', 'model_failure', 'deterministic_failure'))
def test_real_business_adapter_success_or_failure_publish_boundary(tmp_path, outcome):
    """注入专业Agent而保持真实Application及默认Adapter，验证成功和失败发布边界。"""
    from application.adapters import create_default_adapters
    from application.adapters.field_mapping import FieldMappingAdapter
    from toolwithagent_v2.runtime.business_application import BusinessApplication
    from agent.tools.rule_generator import rules_to_base64_text
    client, store, conversation, worker, old_business, file_id = setup(tmp_path)
    if outcome == 'xlsx_unmatched':
        from io import BytesIO
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['原始日志'])
        for value in ('first', 'second', 'third'):
            sheet.append([f'kind=a src={value}'])
        content = BytesIO()
        workbook.save(content)
        workbook.close()
        upload = client.post(f'/api/v2/conversations/{conversation}/files', files={
            'file': ('logs.xlsx', content.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        assert upload.status_code == 201
        file_id = upload.json()['file']['id']
        assert worker.once()
    assert enqueue(client, conversation, file_id).status_code == 201
    assert worker.once()
    previous = mappings(store, conversation)[0]
    calls = []
    class Member:
        name = 'FieldMappingAgent'
        async def arun(self, prompt, **kwargs):
            calls.append(prompt)
            if outcome == 'model_failure':
                raise RuntimeError('provider failure PRIVATE')
            yield SimpleNamespace(event='RunCompleted', content=[
                {'原始字段名': 'src', '系统属性名称': '未匹配', '匹配状态': '未匹配'},
                {'原始字段名': 'kind', '系统属性名称': '未匹配', '匹配状态': '未匹配'}])
    async def classifier(prompt):
        signals = json.loads(prompt.split('## 待判定子规则\n```json\n')[1].split('\n```')[0])
        return json.dumps({'results': [{'rule_name': signal['rule_name'], 'event_name': '登录事件', 'group': 'non_threat'} for signal in signals]}, ensure_ascii=False)
    def adapters(team):
        result = create_default_adapters(team)
        result['field_mapping'] = FieldMappingAdapter(team, candidate_retriever=lambda _: {}, event_classifier=classifier)
        return result
    bridge = BusinessApplication(tmp_path/'knowledge.db', team_factory=lambda: SimpleNamespace(members=(Member(),)), adapters_factory=adapters)
    classification = {'classification': {'status': 'SUCCESS', 'log_format': 'KV', 'feature_field': 'kind',
        'analysis': {'has_key_value_pairs': True, 'delimit': ' ', 'tab': '='},
        'classification_details': [{'logtype': 'a', 'count': 1, 'real_samples': 'kind=a src=SECRET'}]}}
    observed = []
    async def field_mapping(path, snapshot, unused=None):
        if outcome == 'deterministic_failure':
            snapshot = {**snapshot, 'source_fields': {'product': '', 'log_vendor': ''}}
        try:
            result = await bridge.field_mapping(path, snapshot, classification)
        except Exception as error:
            observed.append({'exception_type': type(error).__name__, 'message': str(error)})
            raise
        observed.append(result)
        return result
    old_business.field_mapping = field_mapping
    response = enqueue(client, conversation, file_id, key='independent-real-adapter')
    assert response.status_code == 201
    assert worker.once()
    results = mappings(store, conversation)
    if outcome in ('unmatched', 'xlsx_unmatched'):
        assert calls, observed
        assert 'error' not in observed[0]
        assert len(results) == 2
        assert [item['current'] for item in results] == [False, True]
        assert results[-1]['summary']['unmatched_count'] == 2
        download = client.get(f"/api/v2/artifacts/{results[-1]['id']}/download")
        assert download.content == rules_to_base64_text(observed[0]['config']).encode('utf-8')
        assert json.loads(base64.b64decode(download.content)) == observed[0]['config']
        if outcome == 'xlsx_unmatched':
            assert [(item['value'], item['line_number']) for item in observed[0]['samples']['0']['src']] == [
                ('first', 1), ('second', 2), ('third', 3)]
    else:
        assert observed[0]['error']
        assert len(results) == 1
        assert results[0]['id'] == previous['id']
        assert results[0]['current']
        assert client.get(f"/api/v2/runs/{response.json()['run']['id']}").json()['status'] == 'failed'


def test_field_mapping_skips_reparse_plan_when_classification_reused(tmp_path, monkeypatch):
    """复用分类产物时只执行 v2-field-mapping 计划；无分类才允许重解析（#432）。"""
    import toolwithagent_v2.runtime.business_application as bridge_module
    from contracts.planner_models import StepStatus
    plans = []
    class Row:
        def __init__(self, data): self._data = data
        def model_dump(self, by_alias=False, **kwargs): return self._data
    class MappedArtifact:
        artifact_type = 'field_mapping'
        download_kind = 'mapped_sub_rules'
        def __init__(self):
            self.mappings = [Row({'原始字段名': 'src', '系统属性名称': '源地址', '匹配状态': '匹配成功'})]
            self.event_annotations = []
    class Result:
        def __init__(self, step_id, operation_type, artifact=None):
            self.step_id = step_id
            self.operation_type = operation_type
            self.status = StepStatus.SUCCESS
            self.artifact = artifact
            self.message = None
    class Report:
        status = StepStatus.SUCCESS
        def __init__(self, results): self.results = results
    async def fake_plan(session, team, plan, progress_sink, adapters=None):
        plans.append(plan.plan_id)
        if plan.plan_id == 'v2-mapping-log-parse':
            session.log_classification = {'status': 'SUCCESS', 'log_format': 'KV'}
            return Report([Result('log-parse', 'log_parse')])
        session.mapped_sub_rules = [{'name': 'rule', 'normalize': [{'index': 'src', 'field': '源地址', 'result': ['SECRET']}]}]
        return Report([Result('field-mapping', 'field_mapping', MappedArtifact())])
    monkeypatch.setattr(bridge_module, 'run_deterministic_plan', fake_plan)
    business = bridge_module.BusinessApplication(tmp_path/'knowledge.db', team_factory=lambda: object(), adapters_factory=lambda team: {})
    source = tmp_path/'logs.txt'
    source.write_text('kind=a src=SECRET\n', encoding='utf-8')
    snapshot = {'media_type': 'text/plain', 'source_fields': {'product': 'P', 'log_vendor': 'V', 'data_source': 'P(V)'}}
    classification = {'classification': {'status': 'SUCCESS', 'log_format': 'KV', 'feature_field': 'kind',
        'analysis': {'has_key_value_pairs': True, 'delimit': ' ', 'tab': '='},
        'classification_details': [{'logtype': 'a', 'count': 1, 'real_samples': 'kind=a src=SECRET'}]}}
    reused = asyncio.run(business.field_mapping(source, snapshot, classification))
    assert plans == ['v2-field-mapping']
    assert 'error' not in reused
    plans.clear()
    reparsed = asyncio.run(business.field_mapping(source, snapshot, None))
    assert plans == ['v2-mapping-log-parse', 'v2-field-mapping']
    assert 'error' not in reparsed


def test_sample_reader_order_dedup_rule_membership_and_config_null_numbers():
    """样例有序去重且限制20，JSON不跨类型，配置样例行号明确为空。"""
    from toolwithagent_v2.runtime.mapping_projection import collect_samples
    config = [{'name': 'a', 'parser': {'name': 'json'}, 'normalize': [{'index': 'value', 'result': ['fallback']}]}]
    classification = {'feature_identifier': r'(\{"type":"(a|b)".*\})', 'feature_body_group': 1, 'feature_value_group': 2,
                      'classification_details': [{'logtype': 'a'}]}
    lines = ['', '{"type":"b","value":"foreign"}', '{"type":"a","value":"first"}', '{"type":"a","value":"first"}', '{"type":"a","value":null}', '{"type":"a","value":"second"}']
    samples = collect_samples(config, lines, classification)['0']['value']
    assert [(x['value'], x['line_number']) for x in samples] == [('first', 3), ('second', 6)]
    fallback = collect_samples(config, [], classification)['0']['value']
    assert fallback == [{'value': 'fallback', 'line_number': None, 'source': 'config-sample'}]


def test_public_view_filters_entire_selected_subrule_before_page(tmp_path):
    """当前Tab第51行之后的搜索与过滤结果仍可出现在第一页。"""
    client, store, conversation, worker, business, file_id = setup(tmp_path)
    async def many(path, snapshot, classification=None):
        indexes = [f'field_{n}' for n in range(70)]
        return {'config': [{'name': 'many', 'normalize': [{'index': name, 'field': None} for name in indexes]}, {'name': 'other', 'normalize': [{'index': 'elsewhere', 'field': None}]}],
                'mapping_rows': [{'原始字段名': name, '系统属性名称': '未匹配', '匹配状态': '未匹配'} for name in [*indexes, 'elsewhere']],
                'download_kind': 'mapped_sub_rules', 'download_content': 'bytes'}
    business.field_mapping = many
    assert enqueue(client, conversation, file_id).status_code == 201
    assert worker.once()
    artifact = mappings(store, conversation)[0]
    endpoint = f"/api/v2/artifacts/{artifact['id']}/mapping-view"
    first = client.get(endpoint).json()
    assert first['page_size'] == 50 and len(first['items']) == 50 and first['total'] == 70
    assert len(client.get(endpoint, params={'page': 2}).json()['items']) == 20
    found = client.get(endpoint, params={'q': 'field_69', 'status': 'unmatched'}).json()
    assert found['total'] == 1 and found['items'][0]['source_path'] == 'field_69'
    other = client.get(endpoint, params={'sub_rule': '1'}).json()
    assert other['items'][0]['source_path'] == 'elsewhere'
