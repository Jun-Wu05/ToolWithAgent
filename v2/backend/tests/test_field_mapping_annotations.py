"""字段映射成功后的事件标注和链路警告必须完整持久并隔离敏感文案。"""
import asyncio
import json
from types import SimpleNamespace

from test_field_mapping_slice import setup, enqueue, mappings


def bridge_result(tmp_path, classifier, monkeypatch=None):
    """保持真实映射Adapter和执行后hook，只注入可控专业模型与失败Adapter。"""
    from application.adapters import create_default_adapters
    from application.adapters.field_mapping import FieldMappingAdapter
    from toolwithagent_v2.runtime.business_application import BusinessApplication
    from contracts.planner_models import StepResult, StepStatus

    class Member:
        name = 'FieldMappingAgent'
        async def arun(self, prompt, **kwargs):
            yield SimpleNamespace(event='RunCompleted', content=[
                {'原始字段名': 'src', '系统属性名称': '未匹配', '匹配状态': '未匹配'},
                {'原始字段名': 'kind', '系统属性名称': '未匹配', '匹配状态': '未匹配'}])

    def adapters(team):
        result = create_default_adapters(team)
        result['field_mapping'] = FieldMappingAdapter(team, candidate_retriever=lambda _: {}, event_classifier=classifier)
        if monkeypatch is not None:
            result["add_fields"] = FailedAdd()
        return result

    if monkeypatch is not None:
        import application.threat_chain as chain
        class FailedAdd:
            async def execute(self, step, context, dependencies=None):
                context.session.mapped_sub_rules[0]['normalize'].append({'index': 'PARTIAL-PRIVATE', 'field': 'threat_type'})
                return StepResult(step_id=step.step_id, operation_type=step.type, status=StepStatus.FAILED,
                                  error_code='test_chain_failed', message='controlled chain failure')
        monkeypatch.setattr(chain, 'batch_retrieve_candidates_table', lambda *args, **kwargs: {})

    source = tmp_path/'input.txt'
    source.write_text('kind=a src=one\nkind=a src=two\nkind=a src=three\n', encoding='utf-8')
    classification = {'classification': {'status': 'SUCCESS', 'log_format': 'KV', 'feature_field': 'kind',
        'analysis': {'has_key_value_pairs': True, 'delimit': ' ', 'tab': '='},
        'classification_details': [{'logtype': 'a', 'count': 3, 'real_samples': 'kind=a src=one'}]}}
    bridge = BusinessApplication(tmp_path/'knowledge.db', team_factory=lambda: SimpleNamespace(members=(Member(),)), adapters_factory=adapters)
    return asyncio.run(bridge.field_mapping(source, {'media_type': 'text/plain', 'source_fields': {'product': 'p', 'log_vendor': 'v'}}, classification))


def test_real_uncertain_annotation_keeps_mapping_success_and_application_warning(tmp_path):
    """真实标注两次仍未知时，成功映射不得吞掉hook的待确认警告。"""
    async def uncertain_classifier(prompt):
        return json.dumps({'results': []})
    result = bridge_result(tmp_path, uncertain_classifier)
    assert 'error' not in result
    assert result['config'] and result['download_content']
    assert len(result['event_annotations']) == 1
    row = result['event_annotations'][0]
    assert row['status'] == 'uncertain'
    assert row['threat_types'] == ('⚠️ 未生成',)
    warnings = result.get('warnings', [])
    assert len(warnings) == 1
    assert warnings[0]['code'] == 'threat_chain_warning'
    assert '⚠️' in warnings[0]['message'] and '待人工确认' in warnings[0]['message']


def test_real_failed_chain_keeps_mapping_success_warning_and_no_partial_commit(tmp_path, monkeypatch):
    """真实执行后hook链路失败，仍发布完整映射并保留未生成标注而不提交链路副本。"""
    async def threat_classifier(prompt):
        signals = json.loads(prompt.split('## 待判定子规则\n```json\n')[1].split('\n```')[0])
        return json.dumps({'results': [{'rule_name': row['rule_name'], 'event_name': '网络攻击', 'group': 'threat'} for row in signals]}, ensure_ascii=False)
    result = bridge_result(tmp_path, threat_classifier, monkeypatch)
    assert 'error' not in result
    assert result['config'] and result['download_content']
    assert 'PARTIAL-PRIVATE' not in json.dumps(result['config'], ensure_ascii=False)
    assert result['event_annotations'][0]['status'] == 'judged'
    assert result['event_annotations'][0]['threat_types'] == ('⚠️ 未生成',)
    warnings = result.get('warnings', [])
    assert len(warnings) == 1
    assert warnings[0]['code'] == 'threat_chain_warning'
    assert '⚠️' in warnings[0]['message'] and '未完全成功' in warnings[0]['message']
    assert '字段映射结果不受影响' in warnings[0]['message']


def test_public_mapping_view_retains_annotations_warnings_but_summary_and_events_are_safe(tmp_path):
    """只有本人主动查看完整结果才可见业务文案，默认摘要仅有计数和稳定码。"""
    client, store, conversation, worker, business, file_id = setup(tmp_path)
    annotation = {'rule_name': 'rule', 'event_name': '', 'event_level': '', 'threat_source_field': '',
                  'threat_types': ['⚠️ 未生成'], 'status': 'uncertain'}
    warning = {'code': 'threat_chain_warning', 'message': '⚠️ 待人工确认 PRIVATE-WARNING'}
    original = business.field_mapping
    async def annotated(path, snapshot, classification=None):
        result = await original(path, snapshot, classification)
        return {**result, 'event_annotations': [annotation], 'warnings': [warning]}
    business.field_mapping = annotated
    queued = enqueue(client, conversation, file_id)
    assert queued.status_code == 201
    assert worker.once()
    artifact = mappings(store, conversation)[0]
    assert artifact['current']
    view = client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").json()
    assert view.get('event_annotations') == [{**annotation, 'type_source': '', 'type_values': ['⚠️ 未生成']}]
    assert view.get('warnings') == [warning]
    assert artifact['summary'].get('uncertain_annotation_count') == 1
    assert artifact['summary'].get('warning_codes') == ['threat_chain_warning']
    public = [store.get_conversation('dev-user', conversation), store.events('dev-user', conversation, 0),
              client.get(f"/api/v2/runs/{queued.json()['run']['id']}").json()]
    assert 'PRIVATE-WARNING' not in json.dumps(public, ensure_ascii=False)
    client.post('/api/v2/dev/session', json={'user_id': 'dev-other'})
    assert client.get(f"/api/v2/artifacts/{artifact['id']}/mapping-view").status_code == 404
