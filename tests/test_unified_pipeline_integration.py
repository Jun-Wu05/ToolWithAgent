"""
统一管道集成测试（#19）。

验证 ADR-0004 统一管道的完整接通链路：
  parse_plan_marker（JSON）→ validate_plan_structure → validate_plan_semantics
  → execute_pending_steps（逐步语义校验 + execute_step 传 params + 执行后验证）

不调用真实 LLM——execute_step 用 mock 替换，只验证数据流和参数传递。
"""
import asyncio
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _chainlit_stub(monkeypatch):
    """handler 依赖 cl.Message，强制提供桩。"""
    class _Msg:
        def __init__(self, *a, **kw):
            self.content = kw.get("content", "")
        async def send(self): return self
        async def remove(self): return self
        async def update(self): return self
        async def stream_token(self, tok): self.content += tok

    class _File:
        def __init__(self, *a, **kw): pass

    stub = types.ModuleType("chainlit")
    stub.Message = _Msg
    stub.File = _File
    stub.Action = lambda **kw: None
    monkeypatch.setitem(sys.modules, "chainlit", stub)
    import web.fill_dispatcher as _fd
    import web.enum_handler as _eh
    monkeypatch.setattr(_fd, "cl", stub)
    monkeypatch.setattr(_eh, "cl", stub)
    yield


# 三步复合计划（enum → threat → fill），#15 的核心场景
PLAN_CONTENT = (
    '我将分三步：先提取枚举值，再威胁映射，最后填充。\n\n'
    '[PLAN:{"steps":['
    '{"type":"enum","params":{"field":"vul_name"}},'
    '{"type":"threat","data_deps":["enum"]},'
    '{"type":"fill","params":{"field":"vul_name","source":"threat"},"data_deps":["threat"]}'
    ']}]'
)


class TestParseAndStructureValidation:
    """JSON 计划解析 + 结构校验接通。"""

    def test_json_plan_parses_to_structured_steps(self):
        from web.step_planner import parse_plan_marker
        from web.plan_validator import validate_plan_structure

        steps = parse_plan_marker(PLAN_CONTENT)
        assert len(steps) == 3
        assert steps[0]["type"] == "enum"
        assert steps[0]["params"]["field"] == "vul_name"

        result = validate_plan_structure(steps)
        assert result.valid is True


class TestSemanticValidation:
    """语义校验接通（字段对照 session）。"""

    def test_valid_fields_pass(self):
        from web.step_planner import parse_plan_marker
        from web.plan_validator import validate_plan_semantics

        steps = parse_plan_marker(PLAN_CONTENT)
        session = {
            "raw_log_lines": ["vul_name=CVE-001 src_ip=1.1.1.1"] * 3,
            "mapped_sub_rules": [{"normalize": [{"index": "vul_name", "field": "vul_name"}]}],
        }
        result = validate_plan_semantics(steps, session)
        assert result.valid is True

    def test_missing_field_blocked(self):
        """字段不存在时语义校验拦截。"""
        from web.step_planner import parse_plan_marker
        from web.plan_validator import validate_plan_semantics

        steps = parse_plan_marker(PLAN_CONTENT)
        session = {
            "raw_log_lines": ["src_ip=1.1.1.1 dst_ip=2.2.2.2"] * 3,
            "mapped_sub_rules": [{"normalize": [{"index": "src_ip", "field": "src_address"}]}],
        }
        result = validate_plan_semantics(steps, session)
        assert result.valid is False
        assert any("vul_name" in e for e in result.errors)


class TestExecutePendingStepsParamPassing:
    """execute_pending_steps → execute_step 参数传递（mock execute_step）。"""

    def test_params_correctly_passed(self, monkeypatch):
        from web.step_planner import parse_plan_marker, execute_pending_steps
        import web.step_planner as sp

        steps = parse_plan_marker(PLAN_CONTENT)
        session = {
            "raw_log_lines": ["vul_name=CVE-001 src_ip=1.1.1.1"] * 3,
            "mapped_sub_rules": [{"normalize": [{"index": "vul_name", "field": "vul_name", "mappings": []}]}],
            "last_threat_data": [{"mappingValue": "漏洞利用"}],
            "pending_steps": steps,
        }

        received = []

        async def mock_execute_step(step_type, user_session, team, original_text, step_params=None):
            received.append((step_type, step_params))
            # 模拟每步产出
            if step_type == "fill":
                user_session["mapped_sub_rules"] = [
                    {"normalize": [{"index": "vul_name", "field": "vul_name", "mappings": [{"mappingValue": "x"}]}]}
                ]
            elif step_type == "enum":
                user_session["last_enum_extract_result"] = {"field": "vul_name", "value": ["v1"]}
            elif step_type == "threat":
                user_session["last_threat_data"] = [{"mappingValue": "漏洞利用"}]
            return True

        monkeypatch.setattr(sp, "execute_step", mock_execute_step)

        asyncio.get_event_loop().run_until_complete(
            execute_pending_steps(session, team=None, original_text="提取vul_name枚举值然后威胁映射填回去")
        )

        assert len(received) == 3
        assert received[0] == ("enum", {"field": "vul_name"})
        assert received[1] == ("threat", None)
        assert received[2] == ("fill", {"field": "vul_name", "source": "threat"})

    def test_semantic_failure_stops_execution(self, monkeypatch):
        """语义校验失败时停止执行，不调用 execute_step。"""
        from web.step_planner import execute_pending_steps
        import web.step_planner as sp

        # enum 的 field 不在字段列表中
        session = {
            "raw_log_lines": ["src_ip=1.1.1.1 dst_ip=2.2.2.2"] * 3,
            "pending_steps": [{"type": "enum", "params": {"field": "ghost_field"}}],
        }

        called = []
        async def mock_execute_step(step_type, *a, **kw):
            called.append(step_type)
            return True

        monkeypatch.setattr(sp, "execute_step", mock_execute_step)

        asyncio.get_event_loop().run_until_complete(
            execute_pending_steps(session, team=None, original_text="test")
        )

        assert len(called) == 0, "语义校验失败时不应调用 execute_step"
