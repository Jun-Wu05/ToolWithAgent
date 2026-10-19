# -*- coding: utf-8 -*-
"""共享 LLM 响应解析原语的契约测试（#345）。

钉住收口前各调用点的既有行为：围栏剥离、尾随逗号修复、``{...}`` 块提取、
None 兜底，以及抛错风格调用方（json.loads 异常上抛）只消费围栏原语。
"""

import json

import pytest

from agent.shared.llm_response import parse_json_object, strip_code_fences


class TestStripCodeFences:
    def test_无围栏原样返回(self):
        assert strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_剥掉json围栏(self):
        assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_剥掉裸围栏(self):
        assert strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_围栏行整体过滤(self):
        assert strip_code_fences('```json\n{"a": 1}\n```\n尾注') == '{"a": 1}\n尾注'


class TestParseJsonObject:
    def test_纯文本直解(self):
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_围栏文本直解(self):
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_空文本与空白返回None(self):
        assert parse_json_object("") is None
        assert parse_json_object("   ") is None

    def test_非法文本默认None(self):
        assert parse_json_object("invalid") is None

    def test_尾随逗号修复开关(self):
        text = '{"a": 1,}'
        assert parse_json_object(text) is None
        assert parse_json_object(text, repair_trailing_comma=True) == {"a": 1}

    def test_块提取开关(self):
        text = '前缀 {"a": 1} 后缀'
        assert parse_json_object(text) is None
        assert parse_json_object(text, extract_block=True) == {"a": 1}

    def test_块提取失败仍None(self):
        assert parse_json_object("前缀 {a} 后缀", extract_block=True) is None


class TestCallersKeepSemantics:
    def test_parse_json_safe_委托行为不变(self):
        from application.parsing import parse_json_safe

        assert parse_json_safe('```json\n{"key": "值"}\n```') == {"key": "值"}
        assert parse_json_safe('前缀 {"key": 1} 后缀') == {"key": 1}
        assert parse_json_safe("invalid") is None

    def test_抛错风格只剥围栏_异常上抛(self):
        from agent.shared.event_classify import _extract_results
        from agent.shared.regex_extract import _extract_pattern

        with pytest.raises(json.JSONDecodeError):
            _extract_results("invalid")
        with pytest.raises(json.JSONDecodeError):
            _extract_pattern("invalid")
        assert _extract_results('```json\n{"results": [{"rule_name": "r"}]}\n```') == [
            {"rule_name": "r"}
        ]
        assert _extract_pattern('```\n{"pattern": "a+"}\n```') == "a+"
