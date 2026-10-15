# -*- coding: utf-8 -*-
"""Step 2a 分隔符交叉的回归测试（#344）。

修复前 log_classifier 与 locate_feature 对 delimit/tab 同名参数语义相反
（前者 delimit=字段分隔符，后者 delimit=键值分隔符），Step 2a 调用点
两值交叉后 extract_value 取不到任何值。以下用例修复前红、修复后绿。
"""

import json

from agent.tools.pipeline import log_feature_locator
from agent.tools.pipeline.common.format_context import FormatContext

# 领域规则源的真实形态（如 EDR 子规则 parser.delimit="\s"、parser.tab="="）：
# syslog 头 + 空白分字段 + 等号连键值。
LOGS = "<134>Aug 24 10:00:00 host app: user=admin action=block"


def test_step2a_分隔符不得交叉(monkeypatch):
    """日志头+KV 走 Step 2a 时，特征值必须按 format_info 语义提取。

    format_info 语义：delimit=字段分隔符（空白）、tab=键值分隔符（"="）。
    修复前 locate_feature 按相反语义消费这对值（字段分隔符落到键值位、
    键值分隔符落到字段位），extract_value("user") 取不到值，
    body_analysis 的 sample_values 为空列表。
    """
    prompts = []

    def _fake_llm(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps(
            {"feature_location": "body", "feature_field": "user", "reason": "stub"}
        )

    monkeypatch.setattr(log_feature_locator, "_call_llm_direct", _fake_llm)

    result = log_feature_locator.locate_feature(
        LOGS,
        "user",
        "kv",
        "日志头+KV",
        fmt=FormatContext(field_delimit=" ", kv_delimit="="),
    )

    assert result["feature_location"] == "body"
    # 原始日志行会整体进 prompt（sampled_logs），因此断言 JSON 化的提取结果，
    # 而非裸值：交叉时 sample_values 为空列表。
    assert '"sample_values": ["admin"]' in prompts[0]


def test_format_info键名到上下文的映射():
    """delimit→field_delimit、tab→kv_delimit；缺键与空值回落默认。"""
    assert FormatContext.from_format_info({"delimit": "||", "tab": ":"}) == (
        FormatContext(field_delimit="||", kv_delimit=":")
    )
    assert FormatContext.from_format_info(None) == FormatContext()
    assert FormatContext.from_format_info({"delimit": "", "tab": ""}) == FormatContext()
    assert FormatContext(field_delimit=" ", kv_delimit="=") == FormatContext()


def test_format_info往返一致():
    ctx = FormatContext(field_delimit="||", kv_delimit=":")
    assert FormatContext.from_format_info(ctx.as_format_info()) == ctx


def test_交叉分隔符提取不到特征值():
    """两值互换后 user 提取必空——钉住交叉的可见后果，防止回归被静默吞掉。"""
    from agent.tools.pipeline.extractors.kv_extractor import KvExtractor

    correct = KvExtractor(field_delimit=" ", kv_delimit="=")
    crossed = KvExtractor(field_delimit="=", kv_delimit=" ")
    assert correct.extract_value(LOGS, "user") == "admin"
    assert crossed.extract_value(LOGS, "user") is None
