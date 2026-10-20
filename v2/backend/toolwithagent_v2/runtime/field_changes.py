"""Prepare typed field operations once; apply frozen commands without model calls."""
from __future__ import annotations

import copy

from application.execution import ExecutionContext
from application.session_projection import build_session_facts
from application.adapters.field_skill import FieldSkillAdapter
from application.progress import NullProgressSink
from contracts.planner_models import DeterministicPlan, StepStatus
from .postprocessing import freeze_session, restore_session, config_payload

FIELD_TYPES = frozenset({'add_fields', 'delete_fields', 'merge_fields', 'decode_fields', 'regex_extract'})


class FieldPlanCaptured(Exception):
    def __init__(self, plan):
        self.plan = plan


def capture_field_plan(decision):
    if decision.decision in {'execute', 'proposal'} and any(step.type in FIELD_TYPES for step in decision.steps):
        raise FieldPlanCaptured(decision)


def operation_fields(step):
    """Dependency footprint, including read fields and the event binding pair."""
    fields = set(getattr(step, 'fields', ())) | set(getattr(step, 'source_fields', ()))
    for key in ('field_name', 'source_field', 'target_field', 'new_field'):
        if value := getattr(step, key, None):
            fields.add(value)
    if getattr(step, 'value_type', None) == 'reference':
        fields.add(step.field_value[2:-1])
    if fields & {'事件名称', '事件级别'}:
        fields.update(('事件名称', '事件级别'))
    return fields


def atomic_groups(steps, footprints=None):
    """Same-field and declared dependencies are indivisible, in original order."""
    components = []
    for step in steps:
        fields = {(step.config_ref, name) for name in (footprints or {}).get(step.step_id, operation_fields(step))}
        merged = {'steps': [step], 'fields': fields, 'ids': {step.step_id}}
        remaining = list(components)
        while True:
            matches = [group for group in remaining if merged['fields'] & group['fields']
                or any(set(item.depends_on) & merged['ids'] for item in group['steps'])
                or any(set(item.depends_on) & group['ids'] for item in merged['steps'])]
            if not matches:
                break
            for group in matches:
                merged['steps'] += group['steps']
                merged['fields'] |= group['fields']
                merged['ids'] |= group['ids']
                remaining.remove(group)
        components = remaining + [merged]
    positions = {step.step_id: i for i, step in enumerate(steps)}
    for group in components:
        group['steps'].sort(key=lambda step: positions[step.step_id])
    return sorted(components, key=lambda group: positions[group['steps'][0].step_id])


def _rule_changes(before, after, source, fields):
    """Owner-only business projection; never sent through public progress events."""
    from agent.shared.mapping_utils import iter_config_entities
    old = list(iter_config_entities(before)) if before else []
    new = list(iter_config_entities(after)) if after else []
    changes = []
    for position, (left, right) in enumerate(zip(old, new)):
        if left == right:
            continue
        before_fields = {str(item.get('index')): item for item in left.get('normalize', []) if item.get('index')}
        after_fields = {str(item.get('index')): item for item in right.get('normalize', []) if item.get('index')}
        names = list(dict.fromkeys([*before_fields, *after_fields]))
        for name in names:
            if before_fields.get(name) == after_fields.get(name):
                continue
            changes.append({'sub_rule_id': f'{source}:{position}', 'sub_rule_name': right.get('name') or str(position + 1),
                'field': name, 'kind': 'add' if name not in before_fields else 'delete' if name not in after_fields else 'modify',
                'before': before_fields.get(name), 'after': after_fields.get(name)})
        # Runtime filters are part of the change even when normalize also changed.
        if left.get('parser') != right.get('parser'):
            changes.append({'sub_rule_id': f'{source}:{position}', 'sub_rule_name': right.get('name') or str(position + 1),
                'field': '、'.join(sorted(fields)) + '（运行时处理）', 'kind': 'modify', 'before': (left.get('parser') or {}).get('filter'), 'after': (right.get('parser') or {}).get('filter')})
    return changes


async def execute_fields(session, steps, *, adapter=None, capture=False):
    """Invoke the existing Application adapter; no V2 copy of field semantics."""
    adapter = adapter or FieldSkillAdapter()
    frozen = []
    original_runner = adapter._skill_runner
    patterns = {}
    def runner(kind):
        function = original_runner(kind)
        if kind != 'regex_extract':
            return function
        def regex(*args, **kwargs):
            patterns['pattern'] = args[3]
            return function(*args, **kwargs)
        return regex
    if capture:
        adapter._skill_runner = runner
    try:
        for step in steps:
            if not capture and step.type == 'regex_extract' and not step.pattern:
                raise ValueError('field_preparation_incomplete')
            context = ExecutionContext(session=session, session_facts=build_session_facts(session), progress_sink=NullProgressSink())
            result = await adapter.execute(step, context, {})
            if result.status != StepStatus.SUCCESS:
                raise ValueError(result.error_code or 'field_change_failed')
            frozen.append(step.model_copy(update={'pattern': patterns['pattern']}) if step.type == 'regex_extract' and capture else step)
    finally:
        adapter._skill_runner = original_runner
    return frozen


async def prepare_fields(session, decision, *, adapter=None, base=None):
    field_steps = [step for step in decision.steps if step.type in FIELD_TYPES]
    pending_steps = [step for step in decision.steps if step.type not in FIELD_TYPES]
    # A prerequisite that produces the configuration must complete in its own run.
    if any(set(step.depends_on) & {item.step_id for item in pending_steps} for step in field_steps):
        raise ValueError('field_prerequisite_required')
    initial = freeze_session(session)
    staged = restore_session(initial)
    expanded = []
    for step in field_steps:
        if step.type in {'delete_fields', 'decode_fields'} and len(step.fields) > 1:
            fields = list(step.fields)
            binding = {'事件名称', '事件级别'}
            if step.type == 'delete_fields' and binding <= set(fields):
                expanded.append(step.model_copy(update={'fields': ('事件名称', '事件级别')}))
                fields = [name for name in fields if name not in binding]
            expanded.extend(step.model_copy(update={'step_id': f'{step.step_id}:{index}', 'fields': (name,)})
                for index, name in enumerate(fields))
        else:
            expanded.append(step)
    # Dependencies targeting a split command bind all its fields.
    aliases = {step.step_id: [item.step_id for item in expanded if item.step_id == step.step_id or item.step_id.startswith(step.step_id + ':')]
        for step in field_steps}
    expanded = [step.model_copy(update={'depends_on': tuple(part for ref in step.depends_on for part in aliases.get(ref, [ref]))}) for step in expanded]
    steps = await execute_fields(staged, expanded, adapter=adapter, capture=True)
    # Resolve aliases through actual changed fields as well as declared parameters.
    from application.adapters.shared import resolve_field_names
    footprints = {}
    inferred = False
    for step in steps:
        key = 'decoded_data' if step.config_ref == 'session.decoded_config' else 'mapped_sub_rules'
        names = operation_fields(step)
        resolved, _ = resolve_field_names(initial.get(key), list(names), list(step.target_rule_names) or None)
        inferred |= any(name != value for name, value in resolved.items())
        footprints[step.step_id] = names | set(resolved.values())
    groups = atomic_groups(steps, footprints)
    prepared = []
    for position, group in enumerate(groups):
        isolated = restore_session(initial)
        await execute_fields(isolated, group['steps'])
        changes = []
        for source in dict.fromkeys(step.config_ref for step in group['steps']):
            key = 'decoded_data' if source == 'session.decoded_config' else 'mapped_sub_rules'
            changes.extend(_rule_changes(initial.get(key), getattr(isolated, key), source, {name for ref, name in group['fields'] if ref == source}))
        prepared.append({'id': f'group-{position + 1}', 'steps': [step.model_dump(mode='json') for step in group['steps']],
            'fields': sorted({name for _, name in group['fields']}), 'changes': changes,
            'deletes': sorted({name for step in group['steps'] if step.type == 'delete_fields' for name in operation_fields(step)})})
    rules = {item['sub_rule_id'] for group in prepared for item in group['changes']}
    direct = (decision.decision == 'execute' and len(prepared) == 1 and len(rules) == 1
        and len({change['field'] for change in prepared[0]['changes'] if not change['field'].endswith('（运行时处理）')}) <= 1 and not prepared[0]['deletes']
        and len(steps) == 1 and steps[0].type in {'add_fields', 'decode_fields', 'regex_extract'}
        and not inferred and all(step.type != 'regex_extract' or bool(step.new_field) for step in steps))
    return {'initial_state': initial, 'base_payload': copy.deepcopy(base), 'groups': prepared, 'plan_id': decision.plan_id, 'direct': direct,
        'step_order': [step.step_id for step in steps], 'pending_steps': [step.model_dump(mode='json') for step in pending_steps]}


async def apply_fields(prepared, selected):
    groups = prepared['groups']
    known = {group['id'] for group in groups}
    if len(selected) != len(set(selected)) or not set(selected) <= known:
        raise ValueError('field_selection_invalid')
    # Reconstitute original order after groups have been coalesced.
    raw = [step for group in groups if group['id'] in selected for step in group['steps']]
    order = {name: position for position, name in enumerate(prepared.get('step_order', []))}
    raw.sort(key=lambda step: order.get(step['step_id'], 0))
    session = restore_session(prepared['initial_state'])
    if raw:
        plan = DeterministicPlan.model_validate({'plan_id': prepared['plan_id'], 'steps': [{**step, 'depends_on': []} for step in raw]})
        await execute_fields(session, plan.steps)
    source = raw[-1]['config_ref'] if raw else groups[0]['steps'][0]['config_ref']
    return session, config_payload(session, source, prepared.get('base_payload'))
