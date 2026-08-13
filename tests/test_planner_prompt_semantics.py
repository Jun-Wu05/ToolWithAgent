"""Planner 提示词的离线语义目录与消歧契约测试。"""

from pathlib import Path


PROMPT = (
    Path(__file__).resolve().parent.parent / "agent" / "prompts" / "planner.md"
).read_text(encoding="utf-8")


def test提示词定义七类操作及各自必需参数():
    """防止统一路由再次只依靠模型从操作名猜任务边界。"""
    for operation in (
        "log_parse",
        "field_mapping",
        "enum_extract",
        "threat_mapping",
        "fill",
        "remove_mapping",
        "export",
    ):
        assert f"`{operation}`" in PROMPT
    assert "没有 `target_field`，不要求选择字段" in PROMPT
    assert "必须有 `target_field`" in PROMPT


def test提示词包含日志类型与枚举提取的正反例():
    """“日志类型提取”必须稳定落到无目标字段的 LogParseStep。"""
    assert "“日志类型提取”是 `log_parse`，不是 `enum_extract`" in PROMPT
    assert '{"step_id":"log-1","type":"log_parse"}' in PROMPT
    assert '"type":"enum_extract","target_field":"事件级别"' in PROMPT
    assert "不得生成 `enum_extract` 或询问字段" in PROMPT


def test提示词包含三步复合计划与冲突澄清():
    """代表性 few-shot 同时固定依赖链与失败关闭行为。"""
    assert '"type":"enum_extract"' in PROMPT
    assert '"type":"threat_mapping","source_ref":"step:enum-1"' in PROMPT
    assert '"type":"fill","fill_kind":"threat"' in PROMPT
    assert '"reason_code":"conflicting_intent"' in PROMPT
    assert "## 静默自检" in PROMPT
