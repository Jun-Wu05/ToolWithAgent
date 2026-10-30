"""Application 字段调整适配器：调用 Skills 脚本执行类型化字段操作。

接线方式（ADR-0008）：
- skills/<name>/scripts/<op>.py 是字段操作的**单一事实源**（纯函数）；
- 本模块用 importlib 按声明式注册表加载脚本函数，不在适配器内复制逻辑；
- 新增/删除一个字段操作技能 = 脚本 + 契约类 + 注册表一行 + planner.md 一条语义。
"""

from __future__ import annotations

import importlib.util
import copy
from functools import wraps
from collections.abc import Mapping
from typing import Any

from agent.shared.event_classify import (
    EVENT_LEVEL_FIELD,
    EVENT_NAME_FIELD,
    EVENT_NAME_LEVEL_BINDING,
    make_event_level_normalize_entry,
    make_event_name_normalize_entry,
    read_entity_event_name,
)
from agent.shared.logger import get_logger
from contracts.model_call_diagnostics import reset_skill, set_skill

from application.execution import ExecutionContext
from contracts.planner_models import (
    AddFieldsStep,
    DecodeFieldsStep,
    DeleteFieldsStep,
    MergeFieldsStep,
    RegexExtractStep,
    StepResult,
    StepSpec,
    THREAT_TYPE_FIELD,
)
from application.adapters.shared import (
    REPO_ROOT,
    _build_config_artifact,
    _failed,
    _read_config,
    _success,
    _write_config,
    field_vocabulary,
    format_field_vocabulary,
    resolve_field_names,
)
from agent.shared.mapping_utils import (
    collect_config_names,
    iter_config_entities,
    iter_normalize_entries,
)
from application.adapters.field_skill_policy import find_dangling_references


logger = get_logger("execution_adapters")


def _event_normalize_metadata(entry: Mapping[str, Any]) -> dict[str, Any]:
    """提取通用 add_fields 支持的事件标准字段元数据。

    mappings/value 一并携带（#392）：导出平台按 mappings/value 取值，事件
    两字段需要恒等/码值映射与默认值；威胁类型路径不传这两个键，不受影响。
    """
    return {
        key: entry[key]
        for key in ("field", "entity", "sim", "core", "mappings", "value")
    }

# ---------------------------------------------------------------------------
# 声明式注册表：步骤类型 → (skill 脚本相对路径, 函数名)
# ---------------------------------------------------------------------------

FIELD_SKILL_REGISTRY: dict[str, tuple[str, str]] = {
    "add_fields": (r"skills\add-fields\scripts\add_fields.py", "add_field"),
    "delete_fields": (r"skills\delete-fields\scripts\delete_fields.py", "delete_field"),
    "merge_fields": (r"skills\merge-fields\scripts\merge_fields.py", "merge_fields"),
    "decode_fields": (
        r"skills\base64-decode-fields\scripts\decode_fields.py",
        "decode_fields",
    ),
    "regex_extract": (
        r"skills\regex-extract-field\scripts\extract_field.py",
        "extract_field",
    ),
}

_skill_function_cache: dict[str, Any] = {}


def _load_skill_function(step_type: str) -> Any:
    """按注册表加载 skill 脚本函数（模块级缓存；skills 脚本是单一事实源）。"""
    cached = _skill_function_cache.get(step_type)
    if cached is not None:
        return cached
    try:
        script_rel, function_name = FIELD_SKILL_REGISTRY[step_type]
    except KeyError:
        raise ValueError(f"未注册的字段操作技能: {step_type}") from None
    script_path = REPO_ROOT / script_rel
    if not script_path.is_file():
        raise FileNotFoundError(f"skill 脚本不存在: {script_path}")
    spec = importlib.util.spec_from_file_location(
        f"field_skill_{step_type}", script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, function_name)

    @wraps(function)
    def run(config, *args, **kwargs):
        # Skill scripts consume entity lists; keep an uploaded dict root intact.
        if isinstance(config, list) and all(
            isinstance(item, dict) and ("normalize" in item or "parser" in item)
            for item in config
        ):
            return function(config, *args, **kwargs)
        root = copy.deepcopy(config)
        entities, paths = [], []
        def collect(node, path=()):
            if isinstance(node, dict):
                if isinstance(node.get("normalize"), list) or isinstance(node.get("parser"), dict):
                    paths.append(path)
                    entities.append(node)
                for key, value in node.items():
                    collect(value, (*path, key))
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    collect(value, (*path, index))
        collect(root)
        outcome = function(entities, *args, **kwargs)
        if outcome.get("status") != "success":
            return outcome
        for path, replacement in zip(paths, outcome["data"]):
            if not path:
                root = replacement
            else:
                parent = root
                for part in path[:-1]:
                    parent = parent[part]
                parent[path[-1]] = replacement
        return {**outcome, "data": root}

    _skill_function_cache[step_type] = run
    return run


def _map_skill_error(message: str) -> str:
    """把 skill 脚本返回的中文错误消息映射为稳定错误码。"""
    if "输入数据为空" in message:
        return "config_required"
    if "保留字段" in message:
        return "reserved_field_rejected"
    if "已存在" in message:
        return "field_conflict"
    if "无法全匹配" in message:
        return "pattern_mismatch"
    if "不合法" in message and "正则" in message:
        return "invalid_pattern"
    if "不存在" in message:
        return "field_not_found"
    if "至少需要" in message:
        return "insufficient_source_fields"
    return "field_adjust_failed"


def _first_field_sample(config: Any, field_name: str) -> str | None:
    """递归查找字段的第一条样本值（normalize result[0]），供正则生成。"""
    for _path, _position, _owner, entry in iter_normalize_entries(config):
        if (
            entry.get("index") == field_name
            and isinstance(entry.get("result"), list)
            and entry["result"]
            and str(entry["result"][0]).strip()
        ):
            return str(entry["result"][0])
    return None


def _description_keyword(description: str) -> str:
    """从提取目标描述提取关键词，供缺省字段命名。

    「请求头里的 Referer」→ Referer；「client」→ client。
    取最后一个按空白与常见连接词切分的片段，保留字母数字下划线连字符。
    """
    import re

    tokens = re.split(r"[\s里中的:：,，/、]+", description.strip())
    for token in reversed(tokens):
        cleaned = re.sub(r"[^0-9A-Za-z_-]", "", token)
        if cleaned:
            return cleaned
    return ""


def _collect_entity_names(config: Any) -> list[str]:
    """递归收集配置中全部 entity 名单（已收口 mapping_utils.collect_config_names，#313）。"""
    return collect_config_names(config)


def _iter_target_entities(config: Any, targets: list[str] | None):
    """递归产出目标 entity dict（已委托 shared.iter_config_entities，#146）。"""
    return iter_config_entities(config, targets)


# 删除操作的保留字段（与 skills/delete-fields/scripts/delete_fields.py 的
# RESERVED_FIELDS 同源；适配器在词汇解析前先拦，给出比 field_not_found 更
# 具体的错误）。脚本层仍保留同款守卫兜底。
_DELETE_RESERVED_FIELDS = frozenset({"original_log", "rule_name_list", "日志类型"})


def _resolve_step_field_names(
    step: StepSpec,
    config: Any,
    targets: list[str] | None,
    names: list[str],
    *,
    reference: bool = False,
) -> tuple[dict[str, str], StepResult | None]:
    """把步骤字段名解析为原始 index（#146）；歧义/未命中转稳定错误。

    reference=True 用于 %{X} 引用目标校验：未命中错误码为
    reference_target_not_found（与普通字段引用区分）；歧义统一
    field_name_ambiguous 并列出候选原始名。
    """
    resolved, problems = resolve_field_names(config, names, targets)
    if not problems:
        return resolved, None
    problem = problems[0]
    if problem["kind"] == "ambiguous":
        return resolved, _failed(
            step,
            "field_name_ambiguous",
            (
                f"字段「{problem['name']}」是标准字段名，对应多个原始字段："
                f"{'、'.join(problem['candidates'])}；请改用其中的原始字段名"
            ),
        )
    error_code = "reference_target_not_found" if reference else "field_not_found"
    message = (
        f"未找到字段「{problem['name']}」。"
        f"可用字段（原始名(标准名)）：{format_field_vocabulary(config, targets)}"
    )
    # 近邻提示（#147）：字段并集上做确定性近似，只提示不自动改
    import difflib

    vocabulary_terms = [index for index, _ in field_vocabulary(config, targets)]
    close_matches = difflib.get_close_matches(
        problem["name"], vocabulary_terms, n=2, cutoff=0.8
    )
    if close_matches:
        message += f"；您是不是要找：{'、'.join(close_matches)}？"
    return resolved, _failed(step, error_code, message)


def _resolution_note(resolved: dict[str, str]) -> str:
    """构造「已解析 标准名→原始名」的消息注记（无解析时为空串）。"""
    changes = [f"{name}→{index}" for name, index in resolved.items() if name != index]
    if not changes:
        return ""
    return f"；字段解析：{'、'.join(changes)}"


def _entity_event_name(entity: dict) -> str | None:
    """读取单条 entity 已标注的事件名称；读取逻辑 SSOT 在 event_classify。"""
    return read_entity_event_name(entity)


def _resolve_field_scope(
    step: StepSpec, config: Any
) -> tuple[list[str] | None, StepResult | None]:
    """把 target_rule_names / rule_group 解析为目标名单（#126）。

    - target_rule_names 非空：逐名校验存在性，未知名返回 rule_name_not_found；
    - rule_group 非 all：按已标注事件名称 + 绑定表确定性分组；
      无任何标注时返回 event_annotation_required；
    - 其余：None 表示全部 entity。
    """
    from agent.shared.event_classify import THREAT_EVENT_NAMES

    if step.target_rule_names:
        available = _collect_entity_names(config)
        available_set = set(available)
        unknown = [name for name in step.target_rule_names if name not in available_set]
        if unknown:
            preview = "、".join(available[:20]) + ("等" if len(available) > 20 else "")
            return None, _failed(
                step,
                "rule_name_not_found",
                f"未找到子规则: {'、'.join(unknown)}。可用子规则: {preview}",
            )
        return list(step.target_rule_names), None

    if step.rule_group != "all":
        wanted_threat = step.rule_group == "threat"
        targets = []
        annotated = False
        for entity in _iter_target_entities(config, None):
            event_name = _entity_event_name(entity)
            if event_name is None:
                continue
            annotated = True
            is_threat = event_name in THREAT_EVENT_NAMES
            if is_threat == wanted_threat:
                name = entity.get("name")
                if isinstance(name, str) and name:
                    targets.append(name)
        if not annotated:
            return None, _failed(
                step,
                "event_annotation_required",
                "按威胁/非威胁组批需要先完成字段映射（自动标注事件名称）后再试",
            )
        if not targets:
            return None, _failed(
                step,
                "rule_name_not_found",
                f"没有属于{'威胁' if wanted_threat else '非威胁'}组的子规则",
            )
        return targets, None

    return None, None


def _check_dangling_references(
    step: Any,
    config: Any,
    targets: list[str] | None,
    deleted_names: list[str] | None = None,
) -> StepResult | None:
    """delete 前检查目标 entity 内对被删字段的悬空引用（#126）。

    命中两类引用即拒绝：merger 的源字段、addFields 值中的 %{字段} 占位。
    deleted_names 传入解析后的原始字段名（#146）。
    """
    deleted = deleted_names or step.fields
    issues: list[str] = []
    conflicts = find_dangling_references(_iter_target_entities(config, targets), deleted)
    for conflict in conflicts:
        if conflict.kind == "merger":
            issues.append(
                f"{conflict.entity_name}: merger 源字段引用 {list(conflict.fields)}"
            )
        else:
            issues.append(
                f"{conflict.entity_name}: %{{{conflict.fields[0]}}} 引用"
            )
    if issues:
        return _failed(
            step,
            "field_reference_conflict",
            "以下引用了被删字段，请先解除引用再删除：" + "；".join(issues[:5]),
        )
    return None


class FieldSkillAdapter:
    """字段调整适配器：读配置 → 调 skill 函数 → 写回 session → 产出下载产物。"""

    def __init__(self, skill_runner: Any = None, regex_llm: Any = None):
        """skill_runner / regex_llm 注入接缝：默认走注册表加载与真实
        正则生成，测试传构造假件。"""
        self._skill_runner = skill_runner or _load_skill_function
        self._regex_llm = regex_llm

    async def execute(
        self,
        step: StepSpec,
        context: ExecutionContext,
        dependencies: Mapping[str, StepResult],
    ) -> StepResult:
        """执行一个字段调整步骤；各步骤类型共用本适配器，按类型取参。"""
        registered = FIELD_SKILL_REGISTRY.get(step.type)
        if registered is None:
            raise TypeError("FieldSkillAdapter 只接受字段调整类步骤")
        skill_id = "/".join(registered[0].replace("\\", "/").split("/")[:2])
        token = set_skill(skill_id)
        try:
            if isinstance(step, AddFieldsStep):
                return self._execute_add(step, context)
            if isinstance(step, DeleteFieldsStep):
                return self._execute_delete(step, context)
            if isinstance(step, MergeFieldsStep):
                return self._execute_merge(step, context)
            if isinstance(step, DecodeFieldsStep):
                return self._execute_decode(step, context)
            if isinstance(step, RegexExtractStep):
                return await self._execute_regex_extract(step, context)
            raise TypeError("FieldSkillAdapter 只接受字段调整类步骤")
        finally:
            reset_skill(token)

    # ---- 三类步骤的参数翻译与后处理 ----

    def _execute_add(self, step: AddFieldsStep, context: ExecutionContext) -> StepResult:
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        # %{X} 引用目标校验与标准名解析（#146）：不可解析的引用拒绝写入
        field_value = step.field_value
        ref_resolution: dict[str, str] = {}
        if step.value_type == "reference":
            inner = step.field_value[2:-1]
            ref_resolution, ref_error = _resolve_step_field_names(
                step, config, targets, [inner], reference=True
            )
            if ref_error is not None:
                return ref_error
            if ref_resolution[inner] != inner:
                field_value = f"%{{{ref_resolution[inner]}}}"

        if step.field_name == EVENT_NAME_FIELD:
            guard = self._guard_event_name(
                step, context, config, targets, check_level_conflict=not step.skip_existing
            )
            if guard is not None:
                return guard

        add_kwargs = {
            "target_names": targets,
            "skip_existing": step.skip_existing,
        }
        if step.field_name == THREAT_TYPE_FIELD:
            add_kwargs["normalize_metadata"] = {
                "field": "threat_type",
                "entity": "威胁",
                "sim": True,
                "core": False,
            }
        elif step.field_name == EVENT_NAME_FIELD:
            add_kwargs["normalize_metadata"] = _event_normalize_metadata(
                make_event_name_normalize_entry(step.field_value)
            )
        result = self._skill_runner("add_fields")(
            config,
            step.field_name,
            field_value,
            **add_kwargs,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        updated = result["data"]
        message = str(result.get("message", "")) + _resolution_note(ref_resolution)

        # 事件名称绑定守卫：自动联动写入绑定的事件级别（同目标范围）
        if step.field_name == EVENT_NAME_FIELD:
            level = EVENT_NAME_LEVEL_BINDING[step.field_value]
            level_result = self._skill_runner("add_fields")(
                updated,
                EVENT_LEVEL_FIELD,
                level,
                target_names=targets,
                skip_existing=step.skip_existing,
                normalize_metadata=_event_normalize_metadata(
                    make_event_level_normalize_entry(level)
                ),
            )
            if level_result.get("status") != "success":
                return self._skill_error(step, level_result)
            updated = level_result["data"]
            message = f"{message}，已按绑定关系联动写入{EVENT_LEVEL_FIELD}={level}"

        return self._finish(step, context, updated, message)

    def _execute_delete(self, step: DeleteFieldsStep, context: ExecutionContext) -> StepResult:
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        # 保留字段先于词汇解析拦截（#146：给出比 not_found 更具体的错误）
        reserved_hit = [name for name in step.fields if name in _DELETE_RESERVED_FIELDS]
        if reserved_hit:
            return _failed(
                step,
                "reserved_field_rejected",
                f"字段 {reserved_hit} 为系统保留字段，不允许删除",
            )

        # 绑定对联动删除（#147）：删 事件名称 或 事件级别 任一时自动扩展为两者，
        # 避免留下"名称在、级别没"的绑定残缺；重新标注流程仍是删+加。
        effective_fields = list(step.fields)
        pair_note = ""
        if any(name in (EVENT_NAME_FIELD, EVENT_LEVEL_FIELD) for name in effective_fields):
            for pair_name in (EVENT_NAME_FIELD, EVENT_LEVEL_FIELD):
                if pair_name not in effective_fields:
                    effective_fields.append(pair_name)
            pair_note = "；已联动删除绑定对（事件名称+事件级别）"

        # 字段名解析（#146）：标准名唯一映射到原始 index 后再做悬空检查与删除
        resolved_fields, resolve_error = _resolve_step_field_names(
            step, config, targets, effective_fields
        )
        if resolve_error is not None:
            return resolve_error
        fields_resolved = [resolved_fields[name] for name in effective_fields]

        dangling = _check_dangling_references(step, config, targets, fields_resolved)
        if dangling is not None:
            return dangling

        result = self._skill_runner("delete_fields")(
            config, fields_resolved, target_names=targets
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = (
            str(result.get("message", ""))
            + _resolution_note(resolved_fields)
            + pair_note
        )
        not_found = result.get("not_found")
        if not_found:
            message = f"{message}；未找到字段: {', '.join(not_found)}"
        return self._finish(step, context, result["data"], message)

    def _execute_merge(self, step: MergeFieldsStep, context: ExecutionContext) -> StepResult:
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        # 源字段名解析（#146）：标准名唯一映射到原始 index 后再合并
        resolved_sources, resolve_error = _resolve_step_field_names(
            step, config, targets, list(step.source_fields)
        )
        if resolve_error is not None:
            return resolve_error
        source_list = [resolved_sources[name] for name in step.source_fields]

        result = self._skill_runner("merge_fields")(
            config, source_list, step.target_field, step.sep,
            target_names=targets,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = str(result.get("message", "")) + _resolution_note(resolved_sources)
        return self._finish(step, context, result["data"], message)

    def _execute_decode(self, step: DecodeFieldsStep, context: ExecutionContext) -> StepResult:
        """base64 解码：filter 写入运行时 OGNL 原地覆盖，不双写 normalize。"""
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        resolved_decode, resolve_error = _resolve_step_field_names(
            step, config, targets, list(step.fields)
        )
        if resolve_error is not None:
            return resolve_error

        result = self._skill_runner("decode_fields")(
            config,
            [resolved_decode[name] for name in step.fields],
            target_names=targets,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = str(result.get("message", "")) + _resolution_note(resolved_decode)
        return self._finish(step, context, result["data"], message)

    async def _execute_regex_extract(
        self, step: RegexExtractStep, context: ExecutionContext
    ) -> StepResult:
        """正则提取：用户未提供正则时按样本生成并校验，再执行双写。"""
        from agent.shared.regex_extract import generate_extraction_pattern

        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        resolved_source, resolve_error = _resolve_step_field_names(
            step, config, targets, [step.source_field]
        )
        if resolve_error is not None:
            return resolve_error
        source_field = resolved_source[step.source_field]

        pattern = step.pattern
        if not pattern:
            sample = _first_field_sample(config, source_field)
            if sample is None:
                return _failed(
                    step,
                    "sample_required",
                    f"被提取字段「{step.source_field}」没有样本值，无法生成正则；"
                    "请直接提供正则表达式或换一个有样本的字段",
                )
            try:
                pattern = await generate_extraction_pattern(
                    sample,
                    source_field,
                    step.description,
                    llm_client=self._regex_llm,
                )
            except Exception as error:  # noqa: BLE001 - 生成失败统一转为稳定错误码
                logger.warning(
                    "[REGEX_EXTRACT] 生成失败: step_id=%s error=%s", step.step_id, error
                )
                return _failed(step, "regex_generation_failed", f"正则生成失败：{error}")

        result = self._skill_runner("regex_extract")(
            config,
            step.new_field or None,
            source_field,
            pattern,
            keyword=_description_keyword(step.description),
            target_names=targets,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = (
            str(result.get("message", ""))
            + _resolution_note(resolved_source)
            + f"；正则: {pattern}"
        )
        return self._finish(step, context, result["data"], message)

    # ---- 守卫与收尾 ----

    def _guard_event_name(
        self,
        step: AddFieldsStep,
        context: ExecutionContext,
        config: Any,
        targets: list[str] | None,
        check_level_conflict: bool = True,
    ) -> StepResult | None:
        """【事件名称】绑定守卫：白名单校验恒开；联动前置检查限目标范围。

        skip_existing 模式下已有字段的 entity 由跳过语义接管，
        级别存在性冲突检查关闭（check_level_conflict=False）。
        """
        if step.value_type == "reference":
            return _failed(
                step,
                "invalid_event_name",
                f"{EVENT_NAME_FIELD}必须是固定分类名，不支持引用型值",
            )
        if step.field_value not in EVENT_NAME_LEVEL_BINDING:
            legal = "、".join(EVENT_NAME_LEVEL_BINDING)
            return _failed(
                step,
                "invalid_event_name",
                f"{EVENT_NAME_FIELD}必须是以下分类名之一: {legal}",
            )
        if not check_level_conflict:
            return None
        for entity in _iter_target_entities(config, targets):
            for entry in entity.get("normalize") or []:
                if isinstance(entry, dict) and entry.get("index") == EVENT_LEVEL_FIELD:
                    return _failed(
                        step,
                        "event_level_conflict",
                        f"{EVENT_LEVEL_FIELD}已存在；修改{EVENT_NAME_FIELD}请先删除"
                        f"{EVENT_NAME_FIELD}和{EVENT_LEVEL_FIELD}再重新添加"
                        f"（或要求跳过已有字段的子规则）",
                    )
        return None

    def _skill_error(self, step: StepSpec, result: Mapping[str, Any]) -> StepResult:
        message = str(result.get("message", "字段调整失败"))
        error_code = _map_skill_error(message)
        logger.info(
            "[FIELD_SKILL] 字段调整被拒绝: step_id=%s type=%s error_code=%s",
            step.step_id,
            step.type,
            error_code,
        )
        return _failed(step, error_code, message)

    def _finish(
        self,
        step: StepSpec,
        context: ExecutionContext,
        updated: Any,
        message: str,
    ) -> StepResult:
        """写回 session 原配置来源，并产出可下载的调整后配置。"""
        item_count = len(updated) if isinstance(updated, list) else 1
        _write_config(context.session, step.config_ref, updated)
        logger.info(
            "[FIELD_SKILL] 字段调整完成: step_id=%s type=%s config_ref=%s item_count=%s",
            step.step_id,
            step.type,
            step.config_ref,
            item_count,
        )
        return _success(
            step,
            _build_config_artifact(updated, item_count, "field_adjusted_config"),
            message,
        )
