"""
SessionState 契约测试 — 防止「写入未定义的 session 字段」类 bug。

背景：会话写入散落在 web/ 与 application/ 多个文件，风格有两类：旧式
``session["key"] = value`` 直写，与 application 层的
``_session_set(session, "key", value)`` 垫片调用。每次新增功能写 session 时，
容易忘记在 SessionState 里加字段，导致运行期崩溃。

本测试扫描 web/ 与 application/ 下两类字面量键写入，断言每个 key 都已定义，
把运行期错误提前到测试期。#367 退役 dict 兼容层后，SessionState 只余属性
形态；直写形态在类型上已不可能，扫描保留作为防御。

已知边界：变量键写入（如 ``_session_set(session, session_key, ...)`` 或
``session[key] = value``）无法静态判定，不在守卫视野内。
"""
import os
import re

import pytest

import application.session_state as ss_module

# 会话垫片的允许唯一实现位置（#351 收口：其余拷贝全部改为导入）
_SHIM_SINGLE_HOME = "application/adapters/shared.py"


def _collect_shim_definitions(root_dir: str) -> dict[str, set[str]]:
    """扫描目录下 .py 文件中的会话垫片 def 定义（posix 路径 → 函数名集合）。

    覆盖三个历史拷贝名：``_session_get``/``_session_set``（3 文件 6 份 def）
    与 ``_read_session_value``（session_projection 的同体只读变体）。
    """
    shim_def_re = re.compile(r"def (_session_get|_session_set|_read_session_value)\(")
    found: dict[str, set[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fname)
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    m = shim_def_re.search(line)
                    if m:
                        found.setdefault(fpath.replace(os.sep, "/"), set()).add(
                            m.group(1)
                        )
    return found


def _collect_written_session_keys(root_dir: str) -> set:
    """扫描目录下所有 .py 文件，收集两类字面量键写入的 key 名。

    匹配 ``user_session["key"] =`` / ``session["key"] =`` 直写，与
    ``_session_set(session, "key", ...)``（允许参数间空白/换行前的同行形态）。
    """
    written = set()
    session_write_re = re.compile(r'(?:user_)?session\[[\'"](\w+)[\'"]\]\s*=')
    session_set_re = re.compile(
        r'_session_set\(\s*(?:user_)?session\s*,\s*[\'"](\w+)[\'"]'
    )
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
                    for m in session_set_re.finditer(line):
                        written.add(m.group(1))
    return written


def _collect_defined_session_fields() -> set:
    """从 SessionState dataclass 提取已定义的字段名集合。"""
    from dataclasses import fields
    return {f.name for f in fields(ss_module.SessionState)}


class TestSessionStateContract:
    """所有被写入的 session key 必须在 SessionState 中定义。"""

    def test_all_written_keys_are_defined(self):
        """扫描 web/ 与 application/ 下两类字面量键写入，断言 key 已定义。

        失败时列出未定义的 key 及修复指引（在 SessionState 加字段）。
        """
        written = _collect_written_session_keys("web") | _collect_written_session_keys(
            "application"
        )
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
                f"修复：在 application/session_state.py 的 SessionState dataclass 中添加这些字段。"
            )

    def test_guard_scan_covers_application_writes(self):
        """自证守卫未空转：application/ 扫描必须实际命中 _session_set 字面量键。

        写入风格整体迁移后旧守卫曾扫描空集而永远绿（issue #329）；
        本用例钉住「扫描集合非空」，再次漂移时立即变红。
        """
        written = _collect_written_session_keys("application")
        assert written, (
            "application/ 扫描结果为空——守卫再次空转，"
            "检查写入风格与正则是否漂移"
        )
        assert "pending_plan" in written

    def test_guard_detects_session_set_style_writes(self, tmp_path):
        """自证识别能力：对临时样本同时识别直写与 _session_set 两类形态。"""
        sample = tmp_path / "sample_writer.py"
        sample.write_text(
            "_session_set(session, \"not_a_real_field_xyz\", 1)\n"
            "session[\"also_not_real_abc\"] = 2\n",
            encoding="utf-8",
        )
        written = _collect_written_session_keys(str(tmp_path))

        assert "not_a_real_field_xyz" in written
        assert "also_not_real_abc" in written
        assert "not_a_real_field_xyz" not in _collect_defined_session_fields()

    def test_defined_fields_are_writable(self):
        """SessionState 每个已定义字段都能正常读写（回归基本契约）。"""
        from application.session_state import SessionState
        s = SessionState()
        # 抽查几个关键字段
        s.mapped_sub_rules = [{"normalize": []}]
        assert s.mapped_sub_rules == [{"normalize": []}]
        s.last_threat_data = [{"a": 1}]
        assert s.last_threat_data == [{"a": 1}]

    def test_session_state_dict_compat_layer_is_removed(self):
        """SessionState 不再提供 dict 形态方法（#367 退役契约）。

        get/__getitem__/__setitem__/__contains__/pop 曾是 dict 迁移期的兼容层；
        重新引入任何一种都会让「session 是不是 dict」的歧义回到类型上。
        """
        defined = vars(ss_module.SessionState)
        for name in (
            "get",
            "__getitem__",
            "__setitem__",
            "__contains__",
            "pop",
        ):
            assert name not in defined

    def test_log_classification_commit_clears_only_mapped_rule_derivatives(self):
        """生产 SessionState 与字典测试接缝共享同一派生状态失效语义。"""
        from application.session_state import SessionState, commit_log_classification
        from contracts.planner_models import ExportStep, PendingPlan
        from contracts.rule_source import RuleSourceFields

        mapped_ref = "session.mapped_sub_rules"
        decoded_ref = "session.decoded_config"
        session = SessionState(
            decoded_data={"normalize": []},
            mapped_sub_rules=[{"name": "old"}],
            sub_rule_mapping_results=[{"rule_name": "old"}],
            last_mapping_data=[{"原始字段名": "kind"}],
            enum_fill_contributions={
                mapped_ref: {"kind": [{"orgValue": "old"}]},
                decoded_ref: {"severity": [{"orgValue": "high"}]},
            },
            stale_enum_config_refs={mapped_ref, decoded_ref},
            enum_pending_refills={
                mapped_ref: {"kind"},
                decoded_ref: {"severity"},
            },
            rule_source_fields=RuleSourceFields.create(
                product="旧产品", log_vendor="旧厂商"
            ),
            pending_rule_source_step=ExportStep(
                step_id="old-export",
                type="export",
                source_ref="session.log_classification.entry_rules",
            ),
            pending_plan=PendingPlan(
                plan_id="old-proposal",
                steps=(
                    ExportStep(
                        step_id="old-config-export",
                        type="export",
                        source_ref="session.decoded_config",
                    ),
                ),
                session_facts_digest="a" * 64,
            ),
        )

        cleared = commit_log_classification(session, {"types": ["new"]})

        assert cleared is True
        assert session.log_classification == {"types": ["new"]}
        assert session.mapped_sub_rules is None
        assert session.sub_rule_mapping_results is None
        assert session.last_mapping_data is None
        assert session.decoded_data == {"normalize": []}
        assert session.enum_fill_contributions == {
            decoded_ref: {"severity": [{"orgValue": "high"}]}
        }
        assert session.stale_enum_config_refs == {decoded_ref}
        assert session.enum_pending_refills == {
            decoded_ref: {"severity"},
        }
        assert session.rule_source_fields is None
        assert session.pending_rule_source_step is None
        assert session.pending_plan is None

    def test_会话垫片单一实现(self):
        """垫片 def 全仓唯一：application/web 扫描只允许 adapters/shared 一处。

        #351 收口前的形态是 3 文件 6 份 def + session_projection 的
        ``_read_session_value`` 同体只读变体；任何新拷贝（包括改名前的
        旧名）在此立即变红。
        """
        definitions: dict[str, set[str]] = {}
        for root in ("application", "web"):
            for path, names in _collect_shim_definitions(root).items():
                definitions.setdefault(path, set()).update(names)

        assert definitions == {
            _SHIM_SINGLE_HOME: {"_session_get", "_session_set"},
        }
