"""Owner-only mapping table projection; no business decisions or editing."""
from application.standard_enum_mapping import iter_rule_field_values
from agent.tools.rule_generator.utils import value_to_str

STATUSES = ('matched', 'unmatched', 'parse_error')


def collect_samples(config, lines, classification):
    samples = {}
    for position, rule in enumerate(config):
        fields = {}
        for entry in rule.get('normalize', []):
            index = str(entry.get('index') or '')
            if not index:
                continue
            source, values = iter_rule_field_values(rule, index, lines, classification, position, entry.get("result") or [])
            seen, rows = set(), []
            for number, present, raw in values:
                if not present or raw is None or raw == '':
                    continue
                value = value_to_str(raw)
                if value and value not in seen:
                    seen.add(value)
                    rows.append({'value': value, 'line_number': number, 'source': source})
                    if len(rows) == 20:
                        break
            fields[index] = rows
        samples[str(position)] = fields
    return samples


def mapping_rows(payload):
    original = {item['原始字段名']: item for item in payload['mapping_rows']}
    result = []
    for position, rule in enumerate(payload['config']):
        rows = []
        for entry in rule.get('normalize', []):
            source = str(entry.get('index') or '')
            if source not in original:
                continue  # Generated platform fields are not editable source fields.
            mapped = original[source]
            standard = str(entry.get('field') or '')
            status = 'matched' if standard else 'unmatched'
            if '解析异常' in mapped.get('匹配状态', ''):
                status = 'parse_error'
            evidence = mapped.get('匹配状态', '')
            values = payload.get('samples', {}).get(str(position), {}).get(source, [])[:20]
            rows.append({'source_path': source, 'samples': [item['value'] for item in values[:3]],
                'expanded_samples': values, 'standard_field': standard, 'evidence': evidence,
                'status': status, 'warning': '未匹配' if status == 'unmatched' else ('解析异常' if status == 'parse_error' else ''),
                'user_modified': False})
        rows.sort(key=lambda row: STATUSES.index(row['status']))
        result.append({'id': str(position), 'name': str(rule.get('name') or f'子规则 {position+1}'), 'rows': rows})
    return result


def mapping_summary(payload):
    rules = mapping_rows(payload)
    rows = [row for rule in rules for row in rule['rows']]
    return {'rule_count': len(rules), 'field_count': len(rows),
        'matched_count': sum(row['status']=='matched' for row in rows),
        'unmatched_count': sum(row['status']=='unmatched' for row in rows),
        'parse_error_count': sum(row['status']=='parse_error' for row in rows),
        'uncertain_annotation_count': sum(row.get('status') == 'uncertain'
            for row in payload.get('event_annotations', [])),
        'warning_codes': ['threat_chain_warning'] if any(
            warning.get('code') == 'threat_chain_warning' for warning in payload.get('warnings', [])) else []}


def mapping_view(payload, sub_rule=None, page=1, q='', status=None):
    if page < 1 or len(q) > 200 or status not in (None, '', *STATUSES):
        raise ValueError('invalid_mapping_query')
    rules = mapping_rows(payload)
    selected = str(sub_rule) if sub_rule is not None else (rules[0]['id'] if rules else '')
    rule = next((rule for rule in rules if rule['id'] == selected), None)
    if rule is None:
        raise ValueError('mapping_sub_rule_not_found')
    query = q.casefold().strip()
    rows = [row for row in rule['rows'] if (not status or row['status']==status) and
        (not query or query in str([row['source_path'], row['standard_field'], row['expanded_samples']]).casefold())]
    return {'sub_rules': [{'id': rule['id'], 'name': rule['name'], 'field_count':len(rule['rows'])} for rule in rules],
        'sub_rule_id': selected, 'items': rows[(page-1)*50:page*50], 'total': len(rows), 'page': page, 'page_size': 50, 'sample_line_reference': 'log_entry',
        'event_annotations': payload.get('event_annotations', []), 'warnings': payload.get('warnings', [])}
