"""模型与检索边界不得记录敏感原值。"""

import json
import logging


def test字段检索诊断完整记录字段名与相似度(caplog):
    """字段名、候选标准字段名与相似度分数必须进入 DEBUG trace，供字段映射优化分析。"""
    import numpy as np

    from agent.core.field_retriever import _log_retrieve_trace

    caplog.set_level(logging.DEBUG)
    records = [
        {"系统属性名称": "源IP"},
        {"系统属性名称": "事件类型"},
        {"系统属性名称": "目的IP"},
    ]
    similarity_matrix = np.array([[0.90, 0.40, 0.82]])
    candidates_tmp = [("源IP(0.90, src_ip)", "src_ip", 0.90)]
    candidates = ["源IP(0.90, src_ip)"]

    _log_retrieve_trace(
        field_name="src_ip",
        i=0,
        similarity_matrix=similarity_matrix,
        candidates_tmp=candidates_tmp,
        candidates=candidates,
        records=records,
        elapsed_seconds=0.125,
    )

    log_text = caplog.text
    # 真实字段名、候选标准字段名、相似度分数与耗时都必须可见
    assert "src_ip" in log_text
    assert "源IP" in log_text
    assert "0.90" in log_text
    assert "elapsed_seconds=" in log_text


def test字段映射解析日志不记录完整模型输出(caplog):
    """结构化模型结果只记录类型和数量，不记录字段原值或部分 JSON。"""
    from application.parsing import parse_json_mapping_result

    caplog.set_level(logging.INFO)
    secret_value = "secret-token-10.0.0.1"
    content = (
        '[{"原始字段名":"' + secret_value
        + '","系统属性名称":"标准字段","匹配状态":"匹配成功"}]'
    )

    rows = parse_json_mapping_result(content)

    assert len(rows) == 1
    assert secret_value not in caplog.text
    assert "content_length=" in caplog.text


def test用户明文消息保持结构化jsonl兼容():
    """含中文和换行的完整用户消息仍由既有 formatter 编码为单条合法 JSON。"""
    from agent.shared.logger import _StructuredTraceFormatter

    user_text = "第一行中文\n第二行原文"
    record = logging.LogRecord(
        name="user_message_handlers",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[USER_INPUT] 收到用户指令: user_text=%s character_count=%s",
        args=(user_text, len(user_text)),
        exc_info=None,
    )

    encoded = _StructuredTraceFormatter().format(record)
    decoded = json.loads(encoded)

    assert user_text in decoded["message"]
    assert "character_count=" in decoded["message"]
    assert len(encoded.splitlines()) == 1
    assert "\\n" in encoded
