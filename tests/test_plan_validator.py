"""
计划校验层测试（#17）。

验证 ADR-0004 定义的三层校验：
- validate_plan_structure：JSON schema 合法性（结构校验）
- validate_plan_semantics：params 对照 session 状态（语义校验）
- verify_step_result：执行后结果非空（执行后验证）

测试接缝：web/plan_validator.py（纯 Python，零 LLM 调用）
"""
import pytest

from web.plan_validator import (
    validate_plan_structure,
    validate_plan_semantics,
    verify_step_result,
)


# ============================================================================
# ① 结构校验
# ============================================================================

class TestValidatePlanStructure:
    """validate_plan_structure — JSON 计划的格式合法性。"""

    def test_valid_plan_passes(self):
        """合法的带参数 JSON 计划通过校验。"""
        steps = [
            {"type": "enum", "params": {"field": "漏洞名称"}},
            {"type": "threat", "data_deps": ["enum"]},
            {"type": "fill", "params": {"field": "漏洞名称", "source": "threat"}, "data_deps": ["threat"]},
        ]
        result = validate_plan_structure(steps)
        assert result.valid is True
        assert result.errors == []

    def test_valid_minimal_plan_passes(self):
        """每步只有 type 的最小计划通过校验。"""
        steps = [{"type": "threat"}, {"type": "fill"}]
        result = validate_plan_structure(steps)
        assert result.valid is True

    def test_empty_steps_fails(self):
        """空 steps 列表 → 校验失败。"""
        result = validate_plan_structure([])
        assert result.valid is False
        assert any("空" in e or "empty" in e.lower() or "步骤" in e for e in result.errors)

    def test_invalid_step_type_fails(self):
        """非法步骤类型 → 校验失败。"""
        steps = [{"type": "invalid_type"}]
        result = validate_plan_structure(steps)
        assert result.valid is False
        assert any("invalid_type" in e or "类型" in e for e in result.errors)

    def test_missing_type_field_fails(self):
        """步骤缺少 type 字段 → 校验失败。"""
        steps = [{"params": {"field": "x"}}]
        result = validate_plan_structure(steps)
        assert result.valid is False

    def test_data_deps_referencing_nonexistent_step_fails(self):
        """data_deps 引用不存在的步骤 → 校验失败。"""
        steps = [{"type": "fill", "data_deps": ["nonexistent"]}]
        result = validate_plan_structure(steps)
        assert result.valid is False
        assert any("nonexistent" in e or "data_deps" in e.lower() or "依赖" in e for e in result.errors)

    def test_data_deps_referencing_future_step_fails(self):
        """data_deps 引用后序步骤（位置在后）→ 校验失败（依赖必须在前）。"""
        steps = [
            {"type": "fill", "data_deps": ["threat"]},
            {"type": "threat"},
        ]
        result = validate_plan_structure(steps)
        assert result.valid is False

    def test_data_deps_referencing_previous_step_passes(self):
        """data_deps 引用前序步骤（位置在前）→ 通过。"""
        steps = [
            {"type": "enum"},
            {"type": "threat", "data_deps": ["enum"]},
        ]
        result = validate_plan_structure(steps)
        assert result.valid is True


# ============================================================================
# ② 语义校验
# ============================================================================

class TestValidatePlanSemantics:
    """validate_plan_semantics — params 对照 session 状态。"""

    def _make_session(self, fields=None, sub_rules=None, has_enum_result=False, has_threat_data=False):
        """构造测试用 session。

        fields 参数会被转成 KV 格式的 raw_log_lines，让 extract_log_fields_for_mapping
        能正确提取字段（复用 field_source 的真实逻辑，而非 mock）。
        """
        session = {}
        if fields is not None:
            # 构造 KV 格式日志行，让 field_source 能提取出指定字段名
            session["raw_log_lines"] = [" ".join(f"{f}=value_{j}" for f in fields) for j in range(3)]
        if sub_rules is not None:
            session["mapped_sub_rules"] = sub_rules
        if has_enum_result:
            session["last_enum_extract_result"] = {"field": "漏洞名称", "value": ["v1"]}
        if has_threat_data:
            session["last_threat_data"] = [{"mappingValue": "漏洞利用"}]
        return session

    def test_enum_field_exists_passes(self):
        """enum 步骤的 field 在字段列表中 → 通过。"""
        steps = [{"type": "enum", "params": {"field": "vul_name"}}]
        session = self._make_session(fields=["vul_name", "src_ip", "dst_ip"])
        result = validate_plan_semantics(steps, session)
        assert result.valid is True

    def test_enum_field_not_in_list_fails(self):
        """enum 步骤的 field 不在字段列表中 → 失败。"""
        steps = [{"type": "enum", "params": {"field": "ghost_field"}}]
        session = self._make_session(fields=["src_ip", "dst_ip"])
        result = validate_plan_semantics(steps, session)
        assert result.valid is False
        assert any("ghost_field" in e or "field" in e.lower() or "字段" in e for e in result.errors)

    def test_fill_field_in_sub_rules_passes(self):
        """fill 步骤的 field 在 mapped_sub_rules 的 normalize 项中 → 通过。"""
        steps = [{"type": "fill", "params": {"field": "漏洞名称", "source": "threat"}}]
        session = self._make_session(
            sub_rules=[{"normalize": [{"index": "漏洞名称", "field": "漏洞名称"}]}]
        )
        result = validate_plan_semantics(steps, session)
        assert result.valid is True

    def test_fill_field_not_in_sub_rules_fails(self):
        """fill 步骤的 field 不在 mapped_sub_rules → 失败。"""
        steps = [{"type": "fill", "params": {"field": "ghost_field", "source": "threat"}}]
        session = self._make_session(
            sub_rules=[{"normalize": [{"index": "源IP", "field": "源地址"}]}]
        )
        result = validate_plan_semantics(steps, session)
        assert result.valid is False

    def test_threat_with_enum_data_dep_passes(self):
        """threat 步骤声明 data_deps=[enum] → 语义校验通过（data_deps 合法性由结构校验负责）。

        注：语义校验不检查 last_enum_extract_result 是否已产生——那是运行时状态。
        逐步执行时 enum 步骤执行完才写入 session，threat 的语义校验发生在其后。
        """
        steps = [
            {"type": "enum", "params": {"field": "vul_name"}},
            {"type": "threat", "data_deps": ["enum"]},
        ]
        session = self._make_session(fields=["vul_name"])  # 故意不设 has_enum_result
        result = validate_plan_semantics(steps, session)
        assert result.valid is True

    def test_fill_no_sub_rules_fails(self):
        """fill 步骤但 session 无 mapped_sub_rules → 失败（无处可填）。"""
        steps = [{"type": "fill", "params": {"field": "x", "source": "threat"}}]
        session = self._make_session(has_threat_data=True)
        result = validate_plan_semantics(steps, session)
        assert result.valid is False

    def test_steps_without_params_skip_semantics(self):
        """无 params 的步骤（如 mapping/log_parser）跳过语义校验 → 不报错。"""
        steps = [{"type": "mapping"}, {"type": "log_parser"}]
        session = self._make_session(fields=[])
        result = validate_plan_semantics(steps, session)
        assert result.valid is True


# ============================================================================
# ③ 执行后验证
# ============================================================================

class TestVerifyStepResult:
    """verify_step_result — handler 执行后检查结果是否真的变了。"""

    def test_fill_with_modified_sub_rules_passes(self):
        """fill 执行后 mapped_sub_rules 的 mappings 非空 → 通过。"""
        session = {
            "mapped_sub_rules": [
                {"normalize": [{"index": "漏洞名称", "field": "漏洞名称", "mappings": [{"mappingValue": "漏洞利用"}]}]}
            ]
        }
        assert verify_step_result("fill", session) is True

    def test_fill_with_empty_mappings_fails(self):
        """fill 执行后 mapped_sub_rules 的 mappings 仍为空 → 失败（静默成功问题）。"""
        session = {
            "mapped_sub_rules": [
                {"normalize": [{"index": "漏洞名称", "field": "漏洞名称", "mappings": []}]}
            ]
        }
        assert verify_step_result("fill", session) is False

    def test_threat_with_data_passes(self):
        """threat 执行后 last_threat_data 非空 → 通过。"""
        session = {"last_threat_data": [{"mappingValue": "漏洞利用"}]}
        assert verify_step_result("threat", session) is True

    def test_threat_with_empty_data_fails(self):
        """threat 执行后 last_threat_data 为空 → 失败。"""
        session = {"last_threat_data": []}
        assert verify_step_result("threat", session) is False

    def test_threat_without_data_fails(self):
        """threat 执行后 session 无 last_threat_data → 失败。"""
        session = {}
        assert verify_step_result("threat", session) is False

    def test_enum_with_result_passes(self):
        """enum 执行后有 last_enum_extract_result → 通过。"""
        session = {"last_enum_extract_result": {"field": "漏洞名称", "value": ["v1", "v2"]}}
        assert verify_step_result("enum", session) is True

    def test_enum_with_empty_values_fails(self):
        """enum 执行后提取结果为空 → 失败。"""
        session = {"last_enum_extract_result": {"field": "x", "value": []}}
        assert verify_step_result("enum", session) is False

    def test_mapping_always_passes(self):
        """mapping 步骤无明确的单点验证条件 → 默认通过（结果在上层处理）。"""
        session = {}
        assert verify_step_result("mapping", session) is True

    def test_log_parser_always_passes(self):
        """log_parser 步骤无单点验证条件 → 默认通过。"""
        session = {}
        assert verify_step_result("log_parser", session) is True
