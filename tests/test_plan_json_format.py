"""
PLAN 标记 JSON 格式解析测试（#16）。

验证 ADR-0004 定义的结构化 JSON 计划格式：
- 新格式 [PLAN:{"steps":[...]}] 携带 params + data_deps
- 旧格式 [PLAN:enum|threat] 向后兼容（转为无参数 dict 列表）
- 标记清理（clean_plan_marker）对新旧格式都无残留

测试接缝：web/step_planner.py
"""
from web.step_planner import parse_plan_marker, clean_plan_marker


class TestParsePlanJsonFormat:
    """JSON 嵌套标记的解析（ADR-0004 新格式）。"""

    def test_parse_json_with_params(self):
        """JSON 标记解析出带 params 的步骤列表。"""
        content = (
            '我将分三步。\n\n'
            '[PLAN:{"steps":['
            '{"type":"enum","params":{"field":"漏洞名称"}},'
            '{"type":"threat","data_deps":["enum"]},'
            '{"type":"fill","params":{"field":"threat_type","source":"threat"}}'
            ']}]\n\n完成。'
        )
        result = parse_plan_marker(content)
        assert result is not None
        assert len(result) == 3
        assert result[0]["type"] == "enum"
        assert result[0]["params"] == {"field": "漏洞名称"}
        assert result[1]["type"] == "threat"
        assert result[1]["data_deps"] == ["enum"]
        assert result[2]["type"] == "fill"
        assert result[2]["params"]["field"] == "threat_type"
        assert result[2]["params"]["source"] == "threat"

    def test_parse_json_minimal_steps(self):
        """JSON 标记每步只有 type（无 params/data_deps）。"""
        content = '[PLAN:{"steps":[{"type":"threat"},{"type":"fill"}]}]'
        result = parse_plan_marker(content)
        assert result is not None
        assert len(result) == 2
        assert result[0] == {"type": "threat"}
        assert result[1] == {"type": "fill"}

    def test_parse_json_preserves_data_deps(self):
        """data_deps 字段保留（供 #17 校验层验证步骤间依赖）。"""
        content = (
            '[PLAN:{"steps":['
            '{"type":"mapping"},'
            '{"type":"enum","params":{"field":"severity"},"data_deps":["mapping"]},'
            '{"type":"threat","data_deps":["enum"]},'
            '{"type":"fill","params":{"field":"threat_type"},"data_deps":["threat"]}'
            ']}]'
        )
        result = parse_plan_marker(content)
        assert result[1]["data_deps"] == ["mapping"]
        assert result[2]["data_deps"] == ["enum"]
        assert result[3]["data_deps"] == ["threat"]

    def test_json_empty_steps_returns_none(self):
        """JSON 但 steps 为空数组 → 返回 None（无有效步骤）。"""
        content = '[PLAN:{"steps":[]}]'
        assert parse_plan_marker(content) is None


class TestParsePlanLegacyFormat:
    """旧式无参数标记的向后兼容。"""

    def test_legacy_pipe_format(self):
        """[PLAN:enum|threat] 仍能解析，转为无参数 dict 列表。"""
        result = parse_plan_marker("我将分两步。\n[PLAN:enum|threat]\n完成。")
        assert result is not None
        assert len(result) == 2
        assert result[0] == {"type": "enum"}
        assert result[1] == {"type": "threat"}

    def test_legacy_single_step(self):
        """[PLAN:threat] 单步旧式标记。"""
        result = parse_plan_marker("[PLAN:threat]")
        assert result == [{"type": "threat"}]

    def test_legacy_three_steps(self):
        """[PLAN:mapping|enum|threat] 三步旧式标记。"""
        result = parse_plan_marker("[PLAN:mapping|enum|threat]")
        assert result == [
            {"type": "mapping"},
            {"type": "enum"},
            {"type": "threat"},
        ]


class TestParsePlanEdgeCases:
    """边界情况。"""

    def test_no_marker_returns_none(self):
        """无标记返回 None。"""
        assert parse_plan_marker("普通回复，无计划标记") is None

    def test_plain_text_with_braces_not_mistaken_as_plan(self):
        """用户正文含花括号 {格式} 不被误匹配为 PLAN 标记。"""
        content = "请用 {格式} 处理这些数据"
        assert parse_plan_marker(content) is None

    def test_json_malformed_falls_back_to_none(self):
        """JSON 格式错误（解析失败）→ 返回 None（不 crash）。"""
        content = '[PLAN:{"steps":[{"type":"enum",}]]'  # 尾逗号非法 JSON
        assert parse_plan_marker(content) is None

    def test_marker_with_surrounding_text(self):
        """标记前后有大量文本仍能提取 JSON。"""
        content = (
            "根据您的请求，我将先提取枚举值，再做威胁映射。\n\n"
            '[PLAN:{"steps":[{"type":"enum","params":{"field":"漏洞名称"}},{"type":"threat","data_deps":["enum"]}]}]\n\n'
            "系统将自动按序执行。"
        )
        result = parse_plan_marker(content)
        assert result is not None
        assert len(result) == 2
        assert result[0]["params"]["field"] == "漏洞名称"


class TestCleanPlanMarker:
    """标记清理函数（供 user_message_handlers 展示文本用）。"""

    def test_clean_json_marker_no_residual(self):
        """JSON 标记清理后无 [PLAN: 残留。"""
        content = (
            "我将分两步。\n\n"
            '[PLAN:{"steps":[{"type":"enum"},{"type":"threat"}]}]\n\n'
            "完成。"
        )
        cleaned = clean_plan_marker(content)
        assert "[PLAN:" not in cleaned
        assert "完成。" in cleaned
        assert "我将分两步" in cleaned

    def test_clean_legacy_marker_no_residual(self):
        """旧式标记清理后无残留。"""
        content = "说明文字\n[PLAN:enum|threat]\n后续"
        cleaned = clean_plan_marker(content)
        assert "[PLAN:" not in cleaned
        assert "说明文字" in cleaned
        assert "后续" in cleaned

    def test_clean_no_marker_unchanged(self):
        """无标记时文本不变。"""
        content = "普通回复文本"
        assert clean_plan_marker(content) == content

    def test_clean_preserves_braces_in_text(self):
        """正文中的花括号不被误清理。"""
        content = "请用 {格式} 处理\n[PLAN:enum|threat]\n完成"
        cleaned = clean_plan_marker(content)
        assert "{格式}" in cleaned
        assert "[PLAN:" not in cleaned
