"""字段调整适配器：调用 skills/ 目录脚本对解析规则做字段增删合并（PRD #124）。

接线方式（ADR-0008）：
- skills/<name>/scripts/<op>.py 是字段操作的**单一事实源**（纯函数）；
- 本模块用 importlib 按声明式注册表加载脚本函数，不在适配器内复制逻辑；
- 新增/删除一个字段操作技能 = 脚本 + 契约类 + 注册表一行 + planner.md 一条语义。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from typing import Any

from agent.shared.event_classify import (
    EVENT_LEVEL_FIELD,
    EVENT_NAME_FIELD,
    EVENT_NAME_LEVEL_BINDING,
)
from agent.shared.logger import get_logger

from web.plan_executor import ExecutionContext
from contracts.planner_models import (
    AddFieldsStep,
    DecodeFieldsStep,
    DeleteFieldsStep,
    MergeFieldsStep,
    RegexExtractStep,
    StepResult,
    StepSpec,
)
from web.adapters.shared import (
    REPO_ROOT,
    _build_config_artifact,
    _failed,
    _read_config,
    _success,
    _write_config,
)


logger = get_logger("execution_adapters")

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
    _skill_function_cache[step_type] = function
    return function


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

    def _walk(node: Any) -> str | None:
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for entry in normalize:
                    if (
                        isinstance(entry, dict)
                        and entry.get("index") == field_name
                        and isinstance(entry.get("result"), list)
                        and entry["result"]
                        and str(entry["result"][0]).strip()
                    ):
                        return str(entry["result"][0])
            for value in node.values():
                found = _walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found is not None:
                    return found
        return None

    return _walk(config)


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
    """递归收集配置中全部 entity 名单（去重保序）。"""
    names: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(config)
    return names


def _iter_target_entities(config: Any, targets: list[str] | None):
    """递归产出目标 entity dict；targets 为 None 时产出全部 entity。

    entity 判定：含 parser 或 normalize 的 dict（入口规则与子规则都算）。
    """
    target_set = set(targets) if targets else None

    def _walk(node: Any):
        if isinstance(node, dict):
            name = node.get("name")
            looks_like_entity = isinstance(node.get("parser"), dict) or isinstance(
                node.get("normalize"), list)
            if looks_like_entity:
                if target_set is None:
                    yield node
                elif isinstance(name, str) and name in target_set:
                    yield node
            for value in node.values():
                yield from _walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from _walk(item)

    yield from _walk(config)


def _entity_event_name(entity: dict) -> str | None:
    """读取单条 entity 已标注的事件名称（addFields 固定值优先，normalize 兜底）。"""
    parser = entity.get("parser") or {}
    for filter_item in parser.get("filter") or []:
        if (
            isinstance(filter_item, dict)
            and filter_item.get("name") == "addFields"
            and filter_item.get("id") == ""
            and isinstance(filter_item.get("fields"), dict)
            and EVENT_NAME_FIELD in filter_item["fields"]
        ):
            value = filter_item["fields"][EVENT_NAME_FIELD]
            if value in EVENT_NAME_LEVEL_BINDING:
                return str(value)
    for entry in entity.get("normalize") or []:
        if isinstance(entry, dict) and entry.get("index") == EVENT_NAME_FIELD:
            result = entry.get("result") or [""]
            value = str(result[0]) if result else ""
            if value in EVENT_NAME_LEVEL_BINDING:
                return value
    return None


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
    step: Any, config: Any, targets: list[str] | None
) -> StepResult | None:
    """delete 前检查目标 entity 内对被删字段的悬空引用（#126）。

    命中两类引用即拒绝：merger 的源字段、addFields 值中的 %{字段} 占位。
    """
    deleted = set(step.fields)
    issues: list[str] = []
    for entity in _iter_target_entities(config, targets):
        name = entity.get("name") or "<未命名>"
        parser = entity.get("parser") or {}
        for filter_item in parser.get("filter") or []:
            if not isinstance(filter_item, dict):
                continue
            if filter_item.get("name") == "merger":
                overlap = deleted & set(filter_item.get("fields") or [])
                if overlap:
                    issues.append(f"{name}: merger 源字段引用 {sorted(overlap)}")
            fields = filter_item.get("fields")
            if isinstance(fields, dict):
                for value in fields.values():
                    if isinstance(value, str):
                        refs = deleted & {
                            ref for ref in deleted if f"%{{{ref}}}" in value
                        }
                        if refs:
                            issues.append(f"{name}: %{{{sorted(refs)[0]}}} 引用")
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

    # ---- 三类步骤的参数翻译与后处理 ----

    def _execute_add(self, step: AddFieldsStep, context: ExecutionContext) -> StepResult:
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        if step.field_name == EVENT_NAME_FIELD:
            guard = self._guard_event_name(
                step, context, config, targets, check_level_conflict=not step.skip_existing
            )
            if guard is not None:
                return guard

        result = self._skill_runner("add_fields")(
            config,
            step.field_name,
            step.field_value,
            target_names=targets,
            skip_existing=step.skip_existing,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        updated = result["data"]
        message = str(result.get("message", ""))

        # 事件名称绑定守卫：自动联动写入绑定的事件级别（同目标范围）
        if step.field_name == EVENT_NAME_FIELD:
            level = EVENT_NAME_LEVEL_BINDING[step.field_value]
            level_result = self._skill_runner("add_fields")(
                updated,
                EVENT_LEVEL_FIELD,
                level,
                target_names=targets,
                skip_existing=step.skip_existing,
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

        dangling = _check_dangling_references(step, config, targets)
        if dangling is not None:
            return dangling

        result = self._skill_runner("delete_fields")(
            config, list(step.fields), target_names=targets
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = str(result.get("message", ""))
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

        result = self._skill_runner("merge_fields")(
            config, list(step.source_fields), step.target_field, step.sep,
            target_names=targets,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        return self._finish(step, context, result["data"], str(result.get("message", "")))

    def _execute_decode(self, step: DecodeFieldsStep, context: ExecutionContext) -> StepResult:
        """base64 解码：filter 写入运行时 OGNL 原地覆盖，不双写 normalize。"""
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        targets, scope_error = _resolve_field_scope(step, config)
        if scope_error is not None:
            return scope_error

        result = self._skill_runner("decode_fields")(
            config, list(step.fields), target_names=targets
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        return self._finish(step, context, result["data"], str(result.get("message", "")))

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

        pattern = step.pattern
        if not pattern:
            sample = _first_field_sample(config, step.source_field)
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
                    step.source_field,
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
            step.source_field,
            pattern,
            keyword=_description_keyword(step.description),
            target_names=targets,
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = str(result.get("message", "")) + f"；正则: {pattern}"
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
