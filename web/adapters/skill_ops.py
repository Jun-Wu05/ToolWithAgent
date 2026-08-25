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


def _field_exists_in_config(config: Any, field_name: str) -> bool:
    """递归检查配置中是否已有该字段（normalize index 粒度）。"""

    def _walk(node: Any) -> bool:
        if isinstance(node, dict):
            normalize = node.get("normalize")
            if isinstance(normalize, list):
                for entry in normalize:
                    if isinstance(entry, dict) and entry.get("index") == field_name:
                        return True
            for value in node.values():
                if _walk(value):
                    return True
        elif isinstance(node, list):
            for item in node:
                if _walk(item):
                    return True
        return False

    return _walk(config)


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
        if step.field_name == EVENT_NAME_FIELD:
            guard = self._guard_event_name(step, context)
            if guard is not None:
                return guard

        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        result = self._skill_runner("add_fields")(config, step.field_name, step.field_value)
        if result.get("status") != "success":
            return self._skill_error(step, result)

        updated = result["data"]
        message = str(result.get("message", ""))

        # 事件名称绑定守卫：自动联动写入绑定的事件级别
        if step.field_name == EVENT_NAME_FIELD:
            level = EVENT_NAME_LEVEL_BINDING[step.field_value]
            level_result = self._skill_runner("add_fields")(
                updated, EVENT_LEVEL_FIELD, level
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

        result = self._skill_runner("delete_fields")(config, list(step.fields))
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

        result = self._skill_runner("merge_fields")(
            config, list(step.source_fields), step.target_field, step.sep
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        return self._finish(step, context, result["data"], str(result.get("message", "")))

    def _execute_decode(self, step: DecodeFieldsStep, context: ExecutionContext) -> StepResult:
        """base64 解码：filter 写入运行时 OGNL 原地覆盖，不双写 normalize。"""
        config = _read_config(context.session, step.config_ref)
        if not config:
            return _failed(step, "config_required", "当前没有可调整的解析规则")

        result = self._skill_runner("decode_fields")(config, list(step.fields))
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
        )
        if result.get("status") != "success":
            return self._skill_error(step, result)

        message = str(result.get("message", "")) + f"；正则: {pattern}"
        return self._finish(step, context, result["data"], message)

    # ---- 守卫与收尾 ----

    def _guard_event_name(
        self, step: AddFieldsStep, context: ExecutionContext
    ) -> StepResult | None:
        """【事件名称】绑定守卫：白名单校验 + 联动前置检查。"""
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
        config = _read_config(context.session, step.config_ref)
        if config and _field_exists_in_config(config, EVENT_LEVEL_FIELD):
            return _failed(
                step,
                "event_level_conflict",
                f"{EVENT_LEVEL_FIELD}已存在；修改{EVENT_NAME_FIELD}请先删除"
                f"{EVENT_NAME_FIELD}和{EVENT_LEVEL_FIELD}再重新添加",
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
