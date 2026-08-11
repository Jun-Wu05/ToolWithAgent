"""
计划校验层（ADR-0004）。

在理解层（RouterAgent 产出计划）和执行层（handler）之间的纯 Python 校验闸。
零 LLM 调用，延迟 < 1ms。

三层校验：
1. validate_plan_structure — JSON schema 合法性（结构校验）
2. validate_plan_semantics — params 对照 session 状态（语义校验）
3. verify_step_result — handler 执行后结果非空（执行后验证）

设计原则：
- 确定性执行器不会质疑指令，校验层是理解层与执行层之间的安全闸
- 校验失败时返回结构化错误，由调用方（step_planner）决策降级/追问
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from agent.shared.logger import get_logger

logger = get_logger("plan_validator")

# 合法的步骤类型（与 step_planner._VALID_STEPS 对齐）
_VALID_STEP_TYPES = {"log_parser", "mapping", "enum", "threat", "fill"}


@dataclass
class ValidationResult:
    """校验结果。

    Attributes:
        valid: 是否通过校验。
        errors: 校验失败时的错误描述列表（供调用方决策降级/追问）。
    """
    valid: bool
    errors: List[str] = field(default_factory=list)

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True)

    @classmethod
    def fail(cls, *errors: str) -> "ValidationResult":
        return cls(valid=False, errors=list(errors))


# ============================================================================
# ① 结构校验
# ============================================================================

def validate_plan_structure(steps: List[Dict[str, Any]]) -> ValidationResult:
    """校验 JSON 计划的结构合法性。

    检查内容：
    - steps 非空
    - 每步有 type 且为合法值
    - data_deps 引用的步骤在序列中存在且位置在前（无循环/前向引用）

    Args:
        steps: parse_plan_marker 返回的结构化步骤列表

    Returns:
        ValidationResult（valid=True 通过，False 时 errors 含具体问题）
    """
    if not steps:
        return ValidationResult.fail("计划步骤列表为空，无可执行的步骤")

    errors: List[str] = []
    seen_types = set()

    for i, step in enumerate(steps):
        # 检查 type 字段存在
        step_type = step.get("type")
        if not step_type:
            errors.append(f"步骤 {i + 1}: 缺少 type 字段")
            continue

        # 检查 type 合法性
        if step_type not in _VALID_STEP_TYPES:
            errors.append(
                f"步骤 {i + 1}: 非法步骤类型 '{step_type}'，"
                f"合法值为 {sorted(_VALID_STEP_TYPES)}"
            )

        # 检查 data_deps 引用的步骤存在且在前
        data_deps = step.get("data_deps", [])
        for dep in data_deps:
            if dep not in seen_types:
                errors.append(
                    f"步骤 {i + 1} ({step_type}): data_deps 引用了未出现的前序步骤 '{dep}'"
                )

        seen_types.add(step_type)

    if errors:
        return ValidationResult.fail(*errors)
    return ValidationResult.ok()


# ============================================================================
# ② 语义校验
# ============================================================================

def validate_plan_semantics(steps: List[Dict[str, Any]], user_session) -> ValidationResult:
    """校验 params 对照当前 session 状态。

    检查内容（按步骤类型）：
    - enum: params.field 在字段列表中存在
    - fill: params.field 在 mapped_sub_rules 的 normalize 项中存在
    - threat: 若有 data_deps=[enum]，session 应有 last_enum_extract_result
    - mapping/log_parser: 无 params，跳过

    Args:
        steps: 结构化步骤列表
        user_session: 会话状态（含字段列表、mapped_sub_rules 等）

    Returns:
        ValidationResult
    """
    errors: List[str] = []

    # 获取当前可用字段列表（复用 field_source 的统一逻辑）
    available_fields = _get_available_fields(user_session)

    # 获取 mapped_sub_rules 中的已知字段（index + field）
    sub_rule_fields = _get_sub_rule_fields(user_session)

    for i, step in enumerate(steps):
        step_type = step.get("type", "")
        params = step.get("params", {})

        if step_type == "enum":
            field_name = params.get("field")
            if field_name and available_fields and field_name not in available_fields:
                errors.append(
                    f"步骤 {i + 1} (enum): 字段 '{field_name}' 不在当前可用字段列表中"
                )

        elif step_type == "fill":
            target_field = params.get("field")
            if not target_field:
                errors.append(f"步骤 {i + 1} (fill): 缺少目标字段 params.field")
            else:
                sub_rules = _get_sub_rules(user_session)
                if not sub_rules:
                    errors.append(
                        f"步骤 {i + 1} (fill): 无 mapped_sub_rules，没有可填充的目标"
                    )
                elif sub_rule_fields and target_field not in sub_rule_fields:
                    errors.append(
                        f"步骤 {i + 1} (fill): 目标字段 '{target_field}' "
                        f"不在 mapped_sub_rules 的 normalize 项中"
                    )

        elif step_type == "threat":
            # threat 步骤的 data_deps 引用合法性由结构校验负责（检查前序步骤存在）。
            # 这里不检查 last_enum_extract_result 是否已产生——那是运行时状态：
            # 逐步执行时，enum 步骤执行完才写入 session，threat 的语义校验发生在其后。
            # 若在执行前对全计划做静态校验，data_deps 的结果还未产生，会误报。
            pass

    if errors:
        return ValidationResult.fail(*errors)
    return ValidationResult.ok()


# ============================================================================
# ③ 执行后验证
# ============================================================================

def verify_step_result(step_type: str, user_session) -> bool:
    """handler 执行后验证结果是否真的产生变化。

    确定性执行器不会报告自己的失败，这层检查确保「步骤完成」不谎报。

    Args:
        step_type: 刚执行的步骤类型
        user_session: 执行后的会话状态

    Returns:
        True 表示确实产生了有效结果，False 表示结果为空（应视为失败）
    """
    if step_type == "fill":
        sub_rules = _get_sub_rules(user_session)
        if not sub_rules:
            return False
        # 检查是否有任何 normalize 项的 mappings 非空
        for rule in sub_rules:
            for norm_item in rule.get("normalize", []):
                if norm_item.get("mappings"):
                    return True
        return False

    if step_type == "threat":
        threat_data = _session_get(user_session, "last_threat_data")
        return bool(threat_data)

    if step_type == "enum":
        enum_result = _session_get(user_session, "last_enum_extract_result")
        if not enum_result or not isinstance(enum_result, dict):
            return False
        values = enum_result.get("value", [])
        return bool(values)

    # mapping / log_parser: 无明确的单点验证条件，默认通过
    # （它们的结果在上层 process_team_response / batch_mapping_helper 处理）
    return True


# ============================================================================
# 内部工具函数
# ============================================================================

def _session_get(user_session, key: str, default=None):
    """兼容 dict / SessionState 的安全取值。"""
    if user_session is None:
        return default
    if hasattr(user_session, "get"):
        return user_session.get(key, default)
    if isinstance(user_session, dict):
        return user_session.get(key, default)
    return default


def _get_available_fields(user_session) -> List[str]:
    """从 session 获取当前可用字段列表。

    优先复用 field_source.extract_log_fields_for_mapping 的统一逻辑。
    失败时返回空列表（校验时空列表 = 不校验字段存在性）。
    """
    # 语义校验主要面向 enum/fill，它们的字段来自日志解析结果
    # 复用 field_source 的统一提取逻辑（与 input_builder / enum_handler 一致）
    try:
        from web.field_source import extract_log_fields_for_mapping
        classification = _session_get(user_session, "log_classification")
        raw_log_lines = _session_get(user_session, "raw_log_lines")
        fields = extract_log_fields_for_mapping(classification, raw_log_lines)
        return fields if fields else []
    except Exception as e:
        logger.debug(f"[VALIDATOR] 获取字段列表失败，跳过字段存在性校验: {e}")
        return []


def _get_sub_rules(user_session) -> List[Dict]:
    """从 session 获取 mapped_sub_rules。"""
    sub_rules = _session_get(user_session, "mapped_sub_rules")
    return sub_rules if sub_rules else []


def _get_sub_rule_fields(user_session) -> List[str]:
    """从 mapped_sub_rules 提取所有 normalize 项的 index + field 字段名。"""
    sub_rules = _get_sub_rules(user_session)
    fields = []
    for rule in sub_rules:
        for norm_item in rule.get("normalize", []):
            # normalize 项的 index 是原始字段名，field 是标准字段名
            # fill 的 target_field 可能匹配其中任一个
            if norm_item.get("index"):
                fields.append(norm_item["index"])
            if norm_item.get("field"):
                fields.append(norm_item["field"])
    return fields
