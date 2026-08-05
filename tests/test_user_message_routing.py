"""
handle_user_message 路由一致性测试 — 防止快路径绕过 detect_intent。

测试接缝：web/user_message_handlers.handle_user_message
捕获点：用 monkeypatch 替换下游 handler，断言"被调用的 handler"与
       detect_intent 的路由决策一致。

回归背景（2026-07-27 日志 app_20260727_091154.log 行 159-163）：
  用户输入「把这些枚举值进行威胁类型的映射」
  - detect_intent 正确判定 general（多关键词冲突，交 RouterAgent）
  - 但 handle_user_message 残留的「野生 is_enum_extract」绕过路由，
    直接调用 handle_enum_extract_flow
  - 最终 enum_handler 因收到 ThreatMappingList 对象而崩溃

注：不依赖 pytest-asyncio，用 asyncio.run 直接驱动协程，保持测试自包含。
"""
import asyncio
import sys
import types

import pytest


# ============================================================
# 测试桩：构造一个最小的 chainlit 占位（handle_user_message 依赖 cl）
# ============================================================
@pytest.fixture(autouse=True)
def _ensure_chainlit_stub(monkeypatch):
    """总是强制注入 chainlit 桩，避免真实 chainlit 已被其它测试导入时失效。"""
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
    # 注意：web.enum_handler 等模块顶层已 `import chainlit as cl`，持有真实引用。
    # 替换 sys.modules 后，需让被测模块的 cl 也指向桩——通过 monkeypatch 直接覆盖。
    monkeypatch.setitem(sys.modules, "chainlit", stub)
    import web.user_message_handlers as h
    monkeypatch.setattr(h, "cl", stub, raising=False)


# ============================================================
# 辅助：捕获 handle_user_message 究竟把请求交给了哪个下游 handler
# ============================================================
def _which_handler_called(user_text, session, monkeypatch):
    """同步入口：用 asyncio.run 驱动 handle_user_message，返回被调用的下游 handler 名。"""
    """运行 handle_user_message，返回被调用的下游 handler 名（或 'team_run'/'none'）。

    通过 monkeypatch 给所有下游 handler 打桩，记录首次被 await 的那个。
    """
    import web.user_message_handlers as h

    called = {"name": "none"}

    def make_stub(name):
        async def _stub(*a, **kw):
            called["name"] = name
        return _stub

    # 打桩所有分流出口
    monkeypatch.setattr(h, "handle_threat_fill_flow", make_stub("threat_fill"), raising=False)
    monkeypatch.setattr(h, "handle_enum_fill_flow", make_stub("enum_fill"), raising=False)
    monkeypatch.setattr(h, "handle_enum_extract_flow", make_stub("enum_extract"), raising=False)
    monkeypatch.setattr(h, "handle_log_parser", make_stub("log_parser"), raising=False)

    # fill_dispatcher 延迟导入，打模块桩
    import web.fill_dispatcher as fd
    monkeypatch.setattr(fd, "handle_fill", make_stub("fill"), raising=False)
    monkeypatch.setattr(fd, "handle_remove_fill", make_stub("remove_fill"), raising=False)

    # team.run / call_team：general/_mapping 的最终出口
    async def _call_team_stub(team, inp, loading_msg, intent=None):
        called["name"] = f"team_run:{intent}"
        # 返回一个带 content 的假结果，让 handler 正常退出
        class _R:
            content = "已处理"
        return _R()
    monkeypatch.setattr(h, "call_team", _call_team_stub, raising=False)

    # 清空快捷键不触发
    asyncio.get_event_loop().run_until_complete(
        h.handle_user_message(session, team=object(), user_text=user_text)
    )
    return called["name"]


# ============================================================
# 回归：快路径不得绕过 detect_intent 的消歧判定
# ============================================================

class TestRouteConsistency:
    """detect_intent 判定为 general 的输入，handle_user_message 不得走快路径。"""

    def test_enum_threat_mapping_conflict_goes_to_router(self, monkeypatch):
        """「把这些枚举值进行威胁类型的映射」→ general，不得走 enum_extract。

        回归日志：app_20260727_091154.log 行 159-163。
        修复前：野生 is_enum_extract 命中「枚举值」→ 直调 enum_extract → 崩溃。
        修复后：detected_intent=general → 交 RouterAgent（team_run:general）。
        """
        session = {}  # 空 session，无填充模式
        called = _which_handler_called(
            "把这些枚举值进行威胁类型的映射", session, monkeypatch
        )
        # 不得进入任何快路径（enum_extract/enum_fill/threat_fill/log_parser/fill）
        assert called != "enum_extract", (
            "BUG：含「枚举值」但语义是威胁映射，却被野生快路径抢路由到 enum_extract"
        )
        assert called == "team_run:general", (
            f"多关键词冲突应交 RouterAgent，实际走了：{called}"
        )

    def test_pure_enum_extract_still_fast_path(self, monkeypatch):
        """纯枚举提取（无冲突）→ 仍走 enum_extract 快路径（保证不误伤）。"""
        session = {"raw_log_lines": ["x"]}
        called = _which_handler_called("提取src_ip的枚举值", session, monkeypatch)
        assert called == "enum_extract", (
            "纯枚举提取应保留快路径，实际走了：" + str(called)
        )

    def test_log_parser_with_enum_conflict_goes_to_router(self, monkeypatch):
        """「日志类型字段有哪些枚举值」→ 多域冲突 → general（不得被 log_parser 抢）。"""
        session = {}
        called = _which_handler_called("日志类型字段有哪些枚举值", session, monkeypatch)
        # 修复前：野生 is_log_parser 命中「日志类型」→ 直调 log_parser
        assert called != "log_parser", (
            "BUG：含「日志类型」但多域冲突，却被野生快路径抢路由到 log_parser"
        )
        assert called == "team_run:general", (
            f"多关键词冲突应交 RouterAgent，实际走了：{called}"
        )

    def test_pure_log_parser_still_fast_path(self, monkeypatch):
        """纯日志解析（无冲突）→ 仍走 log_parser 快路径。"""
        session = {}
        called = _which_handler_called("识别日志格式", session, monkeypatch)
        assert called == "log_parser"

    def test_clear_keyword_shortcut_unchanged(self, monkeypatch):
        """清空快捷键不受影响（不走任何业务 handler）。"""
        session = {}
        called = _which_handler_called("清空数据", session, monkeypatch)
        # 清空走 _clear_session_data 内部 cl.Message，不触发任何打桩 handler
        assert called == "none"
