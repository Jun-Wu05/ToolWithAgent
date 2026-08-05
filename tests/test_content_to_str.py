"""
content_to_str 测试 — Pydantic 对象/字符串统一序列化。

回归背景（issue #9）：
  output_schema 返回的 Pydantic 对象（如 ThreatMappingList）在字符串操作
  （'xxx' in content）上抛 TypeError。master 三处分散转换且不一致，
  user_message_handlers:240 完全无防御。
  提取为 content_to_str 统一处理 v1/v2 + 纯字符串。
"""
import json

import pytest

from web.utils import content_to_str


class TestContentToStr:
    """content_to_str 覆盖四种输入类型。"""

    def test_plain_string_returns_as_is(self):
        """纯字符串原样返回（不做 json.dumps 包成 JSON 字符串）。"""
        assert content_to_str("hello 世界") == "hello 世界"
        assert content_to_str("") == ""

    def test_pydantic_v2_object(self):
        """Pydantic v2 对象（有 model_dump）→ json.dumps(model_dump())。"""
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            value: int

        obj = Item(name="测试", value=42)
        result = content_to_str(obj)
        # 应是合法 JSON，含中文（ensure_ascii=False）
        parsed = json.loads(result)
        assert parsed == {"name": "测试", "value": 42}
        assert "测试" in result  # ensure_ascii=False 保留中文

    def test_pydantic_v1_style_object(self):
        """模拟 Pydantic v1 对象（有 dict 无 model_dump）→ json.dumps(dict())。"""
        class V1Style:
            def dict(self):
                return {"threat": "隧道攻击"}

        result = content_to_str(V1Style())
        assert json.loads(result) == {"threat": "隧道攻击"}

    def test_other_object_falls_back_to_str(self):
        """非 Pydantic 对象走 str() 兜底。"""
        result = content_to_str(12345)
        assert result == "12345"
        result = content_to_str([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_none_falls_back_to_str(self):
        """None 走 str() 兜底（不抛异常）。"""
        assert content_to_str(None) == "None"
