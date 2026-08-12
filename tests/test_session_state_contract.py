"""
SessionState 契约测试 — 防止「写入未定义的 session 字段」类 bug。

背景：SessionState.__setitem__ 严格要求字段必须预先定义，否则抛
'SessionState 没有字段: xxx'。但全代码库有 20+ 处 session[key]=value
写入散落在多个文件。每次新增功能写 session 时，容易忘记在 SessionState
里加字段，导致运行期崩溃。

本测试扫描 web/ 下所有 session[...]= 写入，断言每个 key 都已定义，
把「运行期 KeyError」提前到「测试期 AssertionError」。
"""
import os
import re

import pytest

import web.session_state as ss_module


def _collect_written_session_keys(root_dir: str) -> set:
    """扫描目录下所有 .py 文件，收集 session[key]= 写入的 key 名。

    匹配 user_session["key"] = 和 session["key"] = 两种风格。
    """
    written = set()
    session_write_re = re.compile(r'(?:user_)?session\[[\'"](\w+)[\'"]\]\s*=')
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # 跳过缓存目录
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fname)
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    # 跳过注释行
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    for m in session_write_re.finditer(line):
                        written.add(m.group(1))
    return written


def _collect_defined_session_fields() -> set:
    """从 SessionState dataclass 提取已定义的字段名集合。"""
    from dataclasses import fields
    return {f.name for f in fields(ss_module.SessionState)}


class TestSessionStateContract:
    """所有被写入的 session key 必须在 SessionState 中定义。"""

    def test_all_written_keys_are_defined(self):
        """扫描 web/ 下所有 session[key]= 写入，断言 key 已定义。

        失败时列出未定义的 key 及修复指引（在 SessionState 加字段）。
        """
        written = _collect_written_session_keys("web")
        defined = _collect_defined_session_fields()

        missing = written - defined

        if missing:
            # 给出清晰的修复指引
            detail = "\n".join(
                f"  - {k}" for k in sorted(missing)
            )
            pytest.fail(
                f"以下 session key 被写入但 SessionState 未定义，"
                f"会导致运行期 'SessionState 没有字段' 崩溃：\n{detail}\n\n"
                f"修复：在 web/session_state.py 的 SessionState dataclass 中添加这些字段。"
            )

    def test_session_state_setitem_rejects_unknown_key(self):
        """SessionState.__setitem__ 对未定义字段抛 KeyError（这是防护的根基）。

        确保这个严格行为不会被意外放宽（若放宽，上面的扫描测试就失效了）。
        """
        from web.session_state import SessionState
        s = SessionState()
        with pytest.raises(KeyError, match="没有字段"):
            s["nonexistent_field_xyz"] = "value"

    def test_defined_fields_are_writable(self):
        """SessionState 每个已定义字段都能正常读写（回归基本契约）。"""
        from web.session_state import SessionState
        s = SessionState()
        # 抽查几个关键字段
        s["mapped_sub_rules"] = [{"normalize": []}]
        assert s.mapped_sub_rules == [{"normalize": []}]
        s["last_threat_data"] = [{"a": 1}]
        assert s.last_threat_data == [{"a": 1}]
