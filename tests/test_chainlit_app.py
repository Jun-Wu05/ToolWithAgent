"""
单元测试：_route_request() 和 _build_llm_input()

覆盖场景：
- 路由：威胁类型关键词 > 枚举关键词 > 字段映射关键词 > 无匹配
- 输入构建：is_mapping=True 有数据 / 无数据、is_mapping=False

运行方式：
    cd d:\Agent\agent_design\toolswithagent
    python -m pytest tests/test_chainlit_app.py -v
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# 直接导入被测函数
from web.chainlit_app import _route_request, _build_llm_input


# ========== _route_request 测试 ==========

class TestRouteRequest:
    """_route_request 路由测试"""

    def test_threat_keyword_priority_over_mapping(self):
        """威胁类型关键词「威胁类型映射」应优先于字段映射关键词「映射」"""
        user_lower = "威胁类型映射"
        user_text = "威胁类型映射"
        _, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)
        assert is_threat is True
        assert is_mapping is False
        assert is_enum is False

    def test_threat_keyword_simple(self):
        """单纯威胁类型关键词命中"""
        user_lower = "威胁类型"
        user_text = "威胁类型"
        text_out, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)
        assert is_threat is True
        assert is_mapping is False
        assert is_enum is False
        assert text_out.startswith("[威胁类型]")

    def test_mapping_keyword(self):
        """字段映射关键词命中"""
        user_lower = "帮我映射"
        user_text = "帮我映射"
        text_out, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)
        assert is_mapping is True
        assert is_threat is False
        assert is_enum is False
        assert text_out.startswith("[字段映射]")

    def test_enum_keyword(self):
        """枚举关键词命中"""
        user_lower = "枚举字段"
        user_text = "枚举字段"
        text_out, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)
        assert is_enum is True
        assert is_mapping is False
        assert is_threat is False
        assert text_out.startswith("[枚举处理]")

    def test_no_keyword_match(self):
        """无关键词命中"""
        user_lower = "今天天气怎么样"
        user_text = "今天天气怎么样"
        text_out, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)
        assert is_mapping is False
        assert is_threat is False
        assert is_enum is False
        assert text_out == "今天天气怎么样"

    def test_threat_keyword_english(self):
        """英文威胁类型关键词命中"""
        user_lower = "threat_type"
        user_text = "threat_type"
        _, is_mapping, is_threat, is_enum = _route_request(user_lower, user_text)
        assert is_threat is True
        assert is_mapping is False


# ========== _build_llm_input 测试 ==========

class TestBuildLlmInput:
    """_build_llm_input 输入构建测试"""

    def test_mapping_with_data(self):
        """is_mapping=True 且有数据：拼接字段列表"""
        user_session = {
            "decoded_data": {"key": "value"},
            "decoded_fields": ["field1", "field2"],
            "simplified_data": {
                "fields": ["src_ip", "dst_ip", "event_time"],
                "original_log_sample": '{"src_ip": "1.1.1.1"}',
            },
        }
        result = _build_llm_input("映射", user_session, is_mapping=True)
        assert "src_ip" in result
        assert "dst_ip" in result
        assert "event_time" in result
        assert "用户请求" in result
        assert '{"src_ip": "1.1.1.1"}' in result

    def test_mapping_with_data_no_log_sample(self):
        """is_mapping=True 有数据但无日志样本"""
        user_session = {
            "decoded_data": {"key": "value"},
            "simplified_data": {
                "fields": ["src_ip"],
                "original_log_sample": "",
            },
        }
        result = _build_llm_input("字段映射", user_session, is_mapping=True)
        assert "src_ip" in result
        assert "📋 原始日志样本" not in result

    def test_mapping_without_data(self):
        """is_mapping=True 但无数据：仅传用户原始文本"""
        user_session = {}
        result = _build_llm_input("字段映射", user_session, is_mapping=True)
        assert result == "字段映射"
        assert "字段列表" not in result

    def test_threat_request(self):
        """威胁类型请求：仅传用户原始文本（即使有数据）"""
        user_session = {
            "decoded_data": {"key": "value"},
            "simplified_data": {"fields": ["src_ip"]},
        }
        result = _build_llm_input("威胁类型", user_session, is_mapping=False)
        assert result == "威胁类型"
        assert "src_ip" not in result

    def test_no_data_no_mapping(self):
        """无数据且非映射请求：仅传用户原始文本"""
        user_session = {}
        result = _build_llm_input("随便聊聊", user_session, is_mapping=False)
        assert result == "随便聊聊"