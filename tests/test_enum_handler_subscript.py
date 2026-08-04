"""
enum_handler 架构变更测试 — 使用 _call_llm_direct 而非 team.run。

背景（2026-07-30）：enum_handler 原先用 team.run（经过 RouterAgent），
RouterAgent 输出路由解释（Markdown）而非纯 JSON，导致正则提取失败。
改为 _call_llm_direct 直接调 LLM API（强制 JSON、返回字符串）。

本测试验证：enum_handler 不再调用 team.run（避免 RouterAgent 干扰）。
"""
import asyncio
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _chainlit_stub(monkeypatch):
    """handle_enum_extract_flow 依赖 cl.Message，提供最小桩。"""
    if "chainlit" not in sys.modules:
        stub = types.ModuleType("chainlit")

        class _Msg:
            def __init__(self, *a, **kw):
                self.content = kw.get("content", "")

            async def send(self):
                return self

            async def remove(self):
                return self

            async def update(self):
                return self

            async def stream_token(self, tok):
                self.content += tok

        stub.Message = _Msg
        stub.Action = lambda **kw: None
        monkeypatch.setitem(sys.modules, "chainlit", stub)


class TestEnumHandlerNoTeamRun:
    """enum_handler 不应调用 team.run（改用 _call_llm_direct）。"""

    def test_team_run_not_called(self):
        """enum_handler 执行时 team.run 不应被调用。"""
        session = {
            "raw_log_lines": ['攻击类型:web 漏洞攻击,'],
        }

        class SpyTeam:
            """记录 team.run 是否被调用的间谍。"""
            run_called = False

            def run(self, *a, **kw):
                SpyTeam.run_called = True
                # 即使被调用也返回字符串（模拟旧 _call_llm_direct 行为）
                return types.SimpleNamespace(
                    content='{"field":"攻击类型","regex":"攻击类型:([^,]+)"}'
                )

        spy = SpyTeam()
        from web.enum_handler import handle_enum_extract_flow
        try:
            asyncio.get_event_loop().run_until_complete(
                handle_enum_extract_flow(session, spy, "提取攻击类型的枚举值")
            )
        except Exception:
            pass  # _call_llm_direct 可能因无 API key 失败，但 team.run 不应被调用

        assert not SpyTeam.run_called, (
            "enum_handler 不应调用 team.run（会触发 RouterAgent 输出非 JSON）。"
            "应使用 _call_llm_direct 直接调 LLM API。"
        )
