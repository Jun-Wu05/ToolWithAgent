"""Issue #167：冻结历史 Base64 Tool 的公开兼容行为。"""

from __future__ import annotations

import base64
import json

from agent.tools.base64_tool import base64_decode_tool, base64_encode_tool


def _encode_text(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def test_base64_decode公开入口解码json并提取字段与原始日志() -> None:
    payload = {
        "rules": [
            {
                "normalize": [
                    {"index": "src_ip"},
                    {"index": "original_log", "result": ["log-a", "log-b"]},
                ]
            }
        ]
    }

    result = json.loads(
        base64_decode_tool.entrypoint(
            _encode_text(json.dumps(payload, ensure_ascii=False))
        )
    )

    assert result == {
        "status": "success",
        "decoded_json": payload,
        "decoded_text": json.dumps(payload, ensure_ascii=False),
        "fields": ["src_ip", "original_log"],
        "original_log": ["log-a", "log-b"],
        "field_count": 2,
        "message": "成功解码，提取到 2 个字段",
    }


def test_base64_decode公开入口以raw_text结构返回普通文本() -> None:
    result = json.loads(base64_decode_tool.entrypoint(_encode_text("hello 世界")))

    assert result == {
        "status": "success",
        "decoded_json": {"raw_text": "hello 世界"},
        "decoded_text": "hello 世界",
        "fields": [],
        "original_log": None,
        "field_count": 0,
        "message": "成功解码，提取到 0 个字段",
    }


def test_base64_decode公开入口为空输入和非法输入返回错误json() -> None:
    empty = json.loads(base64_decode_tool.entrypoint(" \n\t "))
    invalid = json.loads(base64_decode_tool.entrypoint("%%%not-base64%%%"))

    assert empty == {"status": "error", "error_message": "输入为空"}
    assert invalid["status"] == "error"
    assert invalid["error_message"].startswith("Base64 解码失败: ")


def test_base64_encode公开入口保持json对象_json字符串和文本语义() -> None:
    encoded_object = base64_encode_tool.entrypoint({"中文": "值"})
    encoded_json_text = base64_encode_tool.entrypoint('{"a":1}')
    encoded_plain_text = base64_encode_tool.entrypoint("hello")

    assert base64.b64decode(encoded_object).decode("utf-8") == '{"中文": "值"}'
    assert base64.b64decode(encoded_json_text).decode("utf-8") == '{"a": 1}'
    assert base64.b64decode(encoded_plain_text).decode("utf-8") == '"hello"'
    assert base64_encode_tool.entrypoint({1, 2}).startswith("编码失败: ")


def test_base64_tool公开名称与可调用入口保持兼容() -> None:
    assert base64_decode_tool.name == "base64_decode"
    assert base64_encode_tool.name == "base64_encode"
    assert callable(base64_decode_tool.entrypoint)
    assert callable(base64_encode_tool.entrypoint)
    assert base64_decode_tool.parameters["required"] == ["b64_text"]
    assert base64_encode_tool.parameters["required"] == ["json_data"]

