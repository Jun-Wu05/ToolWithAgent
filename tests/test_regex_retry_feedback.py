# -*- coding: utf-8 -*-
"""正则生成重试反馈的崩溃回归测试（#352）。

2026-10-15 外部 API 降级实锤：LLM 调用失败后 last_regex=""，attempt 2
仍构造「上次正则有误」反馈块，空/无捕获组 pattern 进入判定函数后
match.group(1) 崩溃，吞掉「重试 + 失败抛 ValueError」既有契约。
修复前以下用例红（IndexError），修复后绿。
"""

import httpx

import pytest

from agent.tools.pipeline import log_header_processor as lhp

LOGS = [
    "<134>Aug 24 10:00:00 host app: type=attack src=1.1.1.1",
    "<134>Aug 24 10:00:01 host app: type=scan src=2.2.2.2",
]


def test_kv正则生成_首次调用超时后重试成功(monkeypatch):
    """API 降级场景：attempt 1 超时（无正则产出）→ attempt 2 正常重试而非崩溃。"""
    calls = {"n": 0}

    def _flaky_llm(prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("simulated timeout")
        return "r'type=(\\w+)'"

    monkeypatch.setattr(lhp, "_call_llm_direct", _flaky_llm)

    regex = lhp._generate_kv_feature_identifier("\n".join(LOGS), kv_delimit="=")

    assert calls["n"] == 2
    assert regex == "type=(\\w+)"


def test_header正则生成_首次调用超时后重试成功(monkeypatch):
    """同构路径：header 类型正则生成的重试同样不得因空反馈崩溃。"""
    calls = {"n": 0}

    def _flaky_llm(prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("simulated timeout")
        return "r'host (\\w+):'"

    monkeypatch.setattr(lhp, "_call_llm_direct", _flaky_llm)

    regex = lhp._generate_header_logtype_regex(
        LOGS, format_type="kv", kv_delimit="="
    )

    assert calls["n"] == 2
    assert regex.pattern == "host (\\w+):"


def test_kv正则生成_全部调用失败抛ValueError而非崩溃(monkeypatch):
    """全败路径必须保持既有契约：ValueError，而非 IndexError/AttributeError。"""

    def _dead_llm(prompt, **kwargs):
        raise httpx.ReadTimeout("simulated timeout")

    monkeypatch.setattr(lhp, "_call_llm_direct", _dead_llm)

    with pytest.raises(ValueError, match="kv_body_regex_generation_failed"):
        lhp._generate_kv_feature_identifier("\n".join(LOGS), kv_delimit="=")


def test_failing_sample_block_无捕获组pattern返回空():
    """空 regex / 无捕获组 regex 无法展示「上次捕获」，返回空块不崩溃。"""
    assert lhp._failing_sample_block("", ["any line here"]) == ""
    assert lhp._failing_sample_block("an", ["any line here"]) == ""
    # 对照：单捕获组但未命中的正则仍产出展示块
    block = lhp._failing_sample_block(r"(zz)y", ["any line here"])
    assert "any line here" in block
