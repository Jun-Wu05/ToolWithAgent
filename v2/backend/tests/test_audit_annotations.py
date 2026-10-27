"""Pure audit mapping takes no threat chain but still records applicability."""
import json
from test_field_mapping_annotations import bridge_result


def test_pure_audit_mapping_artifact_marks_threat_determination_not_applicable(tmp_path):
    async def audit_classifier(prompt):
        signals = json.loads(prompt.split('## 待判定子规则\n```json\n')[1].split('\n```')[0])
        return json.dumps({'results': [
            {'rule_name': row['rule_name'], 'event_name': '审计事件', 'group': 'non_threat', 'operation_type': '数据库审计'}
            for row in signals
        ]}, ensure_ascii=False)
    result = bridge_result(tmp_path, audit_classifier)
    assert 'error' not in result
    assert result['event_annotations']
    for row in result['event_annotations']:
        assert row['event_name'] == '审计事件'
        assert row['threat_source_field'] == '不适用'
        assert row['threat_types'] == ('不适用',)
    assert result.get('warnings', []) == []


def test_old_audit_artifact_projects_actual_type_without_rewriting_or_leaking(tmp_path):
    from test_field_mapping_slice import setup, enqueue, mappings
    client, store, conversation, worker, business, file_id = setup(tmp_path)
    original = business.field_mapping
    async def old_payload(*args, **kwargs):
        payload = await original(*args, **kwargs)
        payload['config'][0]['parser'] = {'filter': [{'name': 'addFields', 'fields': {'操作类型': '数据库审计'}}]}
        payload['event_annotations'] = [{'rule_name': 'rule', 'event_name': '审计事件', 'event_level': '信息',
            'threat_source_field': '不适用', 'threat_types': ['不适用'], 'status': 'judged', 'reason': 'PRIVATE-SAVED-REASON'}]
        return payload
    business.field_mapping = old_payload
    assert enqueue(client, conversation, file_id).status_code == 201
    assert worker.once()
    artifact = mappings(store, conversation)[0]
    path = f"/api/v2/artifacts/{artifact['id']}"
    content = client.get(path + '/content')
    assert content.status_code == 200
    before = content.json()
    row = client.get(path + '/mapping-view').json()['event_annotations'][0]
    assert row['type_source'] == '—（固定值）'
    assert row['type_values'] == ['数据库审计']
    assert row['event_name'] == '审计事件'
    assert client.get(path + '/content').json() == before
    assert '数据库审计' not in json.dumps(store.get_conversation('dev-user', conversation), ensure_ascii=False)
    assert '数据库审计' not in json.dumps(store.events('dev-user', conversation, 0), ensure_ascii=False)
    client.post('/api/v2/dev/session', json={'user_id': 'dev-other'})
    assert client.get(path + '/mapping-view').status_code == 404
