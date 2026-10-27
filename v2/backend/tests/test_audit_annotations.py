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
