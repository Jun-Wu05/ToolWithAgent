"""模型与检索边界不得记录敏感原值。"""

import logging


def test字段检索诊断只记录哈希与数量(caplog):
    """字段名、候选名和日志样本不得进入 DEBUG trace。"""
    from agent.core.field_retriever import _log_retrieve_trace

    caplog.set_level(logging.DEBUG)
    _log_retrieve_trace(
        field_name="token=secret-token;src_ip=10.0.0.1",
        candidate_count=8,
        final_candidate_count=6,
        elapsed_seconds=0.125,
    )

    log_text = caplog.text
    assert "field_hash=" in log_text
    assert "candidate_count=8" in log_text
    assert "elapsed_seconds=0.125" in log_text
    assert "secret-token" not in log_text
    assert "10.0.0.1" not in log_text


def test字段映射解析日志不记录完整模型输出(caplog):
    """结构化模型结果只记录类型和数量，不记录字段原值或部分 JSON。"""
    from web.parsers import parse_json_mapping_result

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