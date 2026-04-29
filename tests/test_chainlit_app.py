r"""
单元测试：route_config 关键词加载 + input_builder 输入构建

覆盖场景：
- route_config 关键词加载（JSON 文件或默认值回退）
- input_builder.build_llm_input 有数据 / 无数据拼接

运行方式：
    cd d:\Agent\agent_design\toolswithagent
    python -m pytest tests/test_chainlit_app.py -v
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ========== route_config 测试 ==========

class TestRouteConfig:
    """路由关键词配置加载"""

    def test_keywords_are_lists(self):
        """所有关键词常量应为非空列表"""
        from web.route_config import (
            MAPPING_KEYWORDS, THREAT_KEYWORDS,
            ENUM_KEYWORDS, ENUM_EXTRACT_KEYWORDS,
        )
        assert isinstance(MAPPING_KEYWORDS, list) and len(MAPPING_KEYWORDS) > 0
        assert isinstance(THREAT_KEYWORDS, list) and len(THREAT_KEYWORDS) > 0
        assert isinstance(ENUM_KEYWORDS, list) and len(ENUM_KEYWORDS) > 0
        assert isinstance(ENUM_EXTRACT_KEYWORDS, list) and len(ENUM_EXTRACT_KEYWORDS) > 0

    def test_default_mapping_keywords_contain_expected(self):
        """默认映射关键词应包含「映射」"""
        from web.route_config import MAPPING_KEYWORDS
        assert any("映射" in kw for kw in MAPPING_KEYWORDS)

    def test_default_threat_keywords_contain_expected(self):
        """默认威胁关键词应包含「威胁类型」"""
        from web.route_config import THREAT_KEYWORDS
        assert any("威胁" in kw for kw in THREAT_KEYWORDS)

    def test_enum_keywords_contain_expected(self):
        """默认枚举关键词应包含「枚举」"""
        from web.route_config import ENUM_KEYWORDS
        assert any("枚举" in kw for kw in ENUM_KEYWORDS)

    def test_enum_extract_keywords_contain_expected(self):
        """默认枚举提取关键词应包含「提取」"""
        from web.route_config import ENUM_EXTRACT_KEYWORDS
        assert any("提取" in kw or "枚举值" in kw for kw in ENUM_EXTRACT_KEYWORDS)

    def test_reload_preserves_type(self):
        """重新导入加载仍为列表（幂等）"""
        import web.route_config
        import importlib
        importlib.reload(web.route_config)
        assert isinstance(web.route_config.MAPPING_KEYWORDS, list)
        assert isinstance(web.route_config.THREAT_KEYWORDS, list)


# ========== input_builder 测试 ==========

class TestBuildLlmInput:
    """build_llm_input 输入构建"""

    def test_with_data_includes_fields(self):
        """有 decoded_data 且有 simplified_data.fields 时拼接字段列表"""
        from web.input_builder import build_llm_input
        user_session = {
            "decoded_data": {"key": "value"},
            "decoded_fields": ["field1", "field2"],
            "simplified_data": {
                "fields": ["src_ip", "dst_ip", "event_time"],
                "original_log_sample": '{"src_ip": "1.1.1.1"}',
            },
        }
        result = build_llm_input("映射", user_session)
        assert "src_ip" in result
        assert "dst_ip" in result
        assert "event_time" in result
        assert "用户请求" in result
        assert '{"src_ip": "1.1.1.1"}' in result

    def test_with_data_no_log_sample(self):
        """有数据但无日志样本：不拼接「原始日志样本」标记"""
        from web.input_builder import build_llm_input
        user_session = {
            "decoded_data": {"key": "value"},
            "simplified_data": {
                "fields": ["src_ip"],
                "original_log_sample": "",
            },
        }
        result = build_llm_input("字段映射", user_session)
        assert "src_ip" in result
        assert "原始日志样本" not in result

    def test_without_data_returns_raw_text(self):
        """无 decoded_data 也无 decoded_fields：原样返回用户文本"""
        from web.input_builder import build_llm_input
        user_session = {}
        result = build_llm_input("随便聊聊", user_session)
        assert result == "随便聊聊"

    def test_long_log_sample_truncated(self):
        """日志样本超过 2000 字符应截断"""
        from web.input_builder import build_llm_input
        long_sample = "A" * 2500
        user_session = {
            "decoded_data": {"key": "value"},
            "simplified_data": {
                "fields": ["src_ip"],
                "original_log_sample": long_sample,
            },
        }
        result = build_llm_input("映射", user_session)
        assert "...(已截断)" in result
        assert long_sample not in result
        assert "A" * 2000 in result