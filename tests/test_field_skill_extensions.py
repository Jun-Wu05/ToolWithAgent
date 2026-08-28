"""base64 解码与正则提取两个新 skill 的测试（skills 扩展）。

覆盖：脚本纯函数、契约、适配器路径（含正则生成的 LLM 注入假件与
全匹配校验）、错误码映射。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from contracts.planner_models import (
    DecodeFieldsStep,
    PlanDecision,
    RegexExtractStep,
    StepStatus,
)
from application.session_projection import build_session_facts
from web.plan_executor import ExecutionContext
from web.adapters.skill_ops import (
    FIELD_SKILL_REGISTRY,
    FieldSkillAdapter,
    _load_skill_function,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script(rel_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, _REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def decode_module():
    """加载 base64 解码脚本。"""
    return _load_script(
        r"skills\base64-decode-fields\scripts\decode_fields.py", "t_decode_fields"
    )


@pytest.fixture(scope="module")
def extract_module():
    """加载正则提取脚本。"""
    return _load_script(
        r"skills\regex-extract-field\scripts\extract_field.py", "t_extract_field"
    )


def _config():
    """含 original_log / req_header 样本的规则。"""
    return [
        {
            "name": "rule-1",
            "normalize": [
                {"index": "original_log", "result": ['client="pc-01" server="nginx"']},
                {"index": "req_header", "result": ["GET /a HTTP/1.1\r\nReferer: http://x\r\n"]},
                {"index": "client", "result": ["pc-01"]},
            ],
            "parser": {"filter": []},
        }
    ]


def _context(session):
    return ExecutionContext(
        session=session,
        session_facts=build_session_facts(session),
        progress_sink=None,
    )


def _run(adapter, step, session):
    return asyncio.run(adapter.execute(step, _context(session), {}))


# ---------------------------------------------------------------------------
# base64 解码脚本与适配器
# ---------------------------------------------------------------------------


def test解码写入ognl并保持幂等合并(decode_module):
    """解码条目写入解码过滤器，重复调用合并不重复追加。"""
    # req_body_x 不存在于任何 entity → 全缺报错（#147 per-entity）
    once = decode_module.decode_fields(_config(), ["req_body_x"])
    assert once["status"] == "error"

    result = decode_module.decode_fields(_config(), ["req_header"])
    assert result["status"] == "success"
    filters = result["data"][0]["parser"]["filter"]
    decode_filters = [
        f for f in filters
        if f.get("name") == "addFields" and f.get("id") == "" and f.get("fields")
    ]
    assert len(decode_filters) == 1
    assert decode_filters[0]["fields"] == {
        "req_header": "<%@com.hansight.dataviewer.utils.Base64@Base64Decode(req_header)%>"
    }
    # normalize 不双写
    indexes = [e["index"] for e in result["data"][0]["normalize"]]
    assert indexes == ["original_log", "req_header", "client"]

    # 幂等：再次解码同字段不新增过滤器
    twice = decode_module.decode_fields(result["data"], ["req_header", "client"])
    assert twice["status"] == "success"
    filters2 = [
        f for f in twice["data"][0]["parser"]["filter"]
        if f.get("name") == "addFields" and f.get("id") == "" and f.get("fields")
    ]
    assert len(filters2) == 1
    assert set(filters2[0]["fields"]) == {"req_header", "client"}


def test解码适配器写回并产出下载产物():
    """decode_fields 步骤成功写回 session。"""
    session = {"decoded_data": _config()}
    step = DecodeFieldsStep(
        step_id="d1", type="decode_fields", fields=("req_header",), config_ref="session.decoded_config"
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.SUCCESS
    decode_filters = [
        f for f in session["decoded_data"][0]["parser"]["filter"]
        if f.get("name") == "addFields" and "Base64Decode" in str(f.get("fields"))
    ]
    assert decode_filters


def test解码字段缺失映射field_not_found():
    """不存在的字段返回稳定错误码并列出可用字段。"""
    step = DecodeFieldsStep(
        step_id="d1", type="decode_fields", fields=("ghost",), config_ref="session.decoded_config"
    )
    result = _run(FieldSkillAdapter(), step, {"decoded_data": _config()})
    assert result.status == StepStatus.FAILED
    assert result.error_code == "field_not_found"


# ---------------------------------------------------------------------------
# 正则提取脚本
# ---------------------------------------------------------------------------


def test正则提取双写customFunction与normalize(extract_module):
    """customFunction 结构与设计文档一致；normalize 预览值为第一捕获组。"""
    pattern = r'[\S\s]*client="(.*?)"[\S\s]*'
    result = extract_module.extract_field(_config(), "newclient", "original_log", pattern)
    assert result["status"] == "success", result["message"]

    rule = result["data"][0]
    custom = [f for f in rule["parser"]["filter"] if f.get("name") == "customFunction"]
    assert len(custom) == 1
    assert custom[0]["custom_name"] == "extractRegexField"
    func = custom[0]["fields"][0]
    assert func["functionName"] == "extractRegexField"
    assert func["ognl"] == (
        '<%@com.hansight.dataviewer.utils.ognl.OgnlUtils@regexExtraction(arg2,"arg3")%>'
    )
    args = {arg["args"]: arg for arg in func["args"]}
    assert args["arg1"]["value"] == "newclient"
    assert args["arg1"]["type"] == "field"
    assert args["arg2"]["value"] == "original_log"
    assert args["arg3"]["value"] == pattern
    # normalize 预览 = 捕获组
    preview = [e for e in rule["normalize"] if e["index"] == "newclient"]
    assert preview[0]["result"] == ["pc-01"]


def test正则非全匹配被拒绝(extract_module):
    """锚定起点不同、无法全匹配样本的正则被硬校验拒绝（设计约束）。"""
    result = extract_module.extract_field(
        _config(), "x", "original_log", r'server="(.*?)"'
    )
    assert result["status"] == "error"
    assert "无法全匹配" in result["message"]


def test正则语法非法被拒绝(extract_module):
    """非法正则返回错误。"""
    result = extract_module.extract_field(_config(), "x", "original_log", "([unclosed")
    assert result["status"] == "error"
    assert "不合法" in result["message"]


def test新字段名缺省推导与冲突(extract_module):
    """未指定新字段名时按提取关键词命名：已存在 → new 前缀；不存在 → 原名。"""
    result = extract_module.extract_field(
        _config(), None, "original_log", r'[\S\s]*client="(.*?)"[\S\s]*', keyword="client"
    )
    assert result["status"] == "success"
    indexes = [e["index"] for e in result["data"][0]["normalize"]]
    assert "newclient" in indexes  # client 已存在 → newclient

    result2 = extract_module.extract_field(
        _config(), None, "original_log", r'[\S\s]*server="(.*?)"[\S\s]*', keyword="server"
    )
    indexes2 = [e["index"] for e in result2["data"][0]["normalize"]]
    assert "server" in indexes2  # server 不存在 → 原名


# ---------------------------------------------------------------------------
# 正则生成（注入假 LLM）与适配器
# ---------------------------------------------------------------------------


def _fake_pattern_llm(pattern: str):
    """返回固定 pattern 的假 LLM。"""

    def _call(prompt: str) -> str:
        return json.dumps({"pattern": pattern}, ensure_ascii=False)

    return _call


def test正则生成成功经全匹配校验():
    """生成的正则通过 compile + fullmatch 校验后返回。"""
    from agent.shared.regex_extract import generate_extraction_pattern

    pattern = asyncio.run(
        generate_extraction_pattern(
            'client="pc-01" server="nginx"',
            "original_log",
            "client",
            llm_client=_fake_pattern_llm(r'[\S\s]*client="(.*?)"[\S\s]*'),
        )
    )
    assert pattern == r'[\S\s]*client="(.*?)"[\S\s]*'


def test正则生成非法输出重试后失败():
    """非法输出带反馈重试一次，仍失败抛 RegexGenerationError。"""
    from agent.shared.regex_extract import RegexGenerationError, generate_extraction_pattern

    calls = []

    def bad(prompt: str) -> str:
        calls.append(prompt)
        return "not json"

    with pytest.raises(RegexGenerationError):
        asyncio.run(
            generate_extraction_pattern(
                'client="pc-01"', "original_log", "client", llm_client=bad
            )
        )
    assert len(calls) == 2


def test正则生成无法全匹配重试修正():
    """第一次不匹配、第二次修正后通过。"""
    from agent.shared.regex_extract import generate_extraction_pattern

    state = {"count": 0}

    def flaky(prompt: str) -> str:
        state["count"] += 1
        pattern = r'client="(.*?)"' if state["count"] == 1 else r'[\S\s]*client="(.*?)"[\S\s]*'
        return json.dumps({"pattern": pattern}, ensure_ascii=False)

    pattern = asyncio.run(
        generate_extraction_pattern(
            'src=1 client="pc-01"', "original_log", "client", llm_client=flaky
        )
    )
    assert "[\\S\\s]*" in pattern


def test正则提取适配器用户直接提供正则():
    """pattern 显式携带时不调 LLM，直接执行脚本。"""
    session = {"decoded_data": _config()}
    step = RegexExtractStep(
        step_id="r1",
        type="regex_extract",
        source_field="original_log",
        description="client",
        new_field="newclient",
        pattern=r'[\S\s]*client="(.*?)"[\S\s]*',
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, session)
    assert result.status == StepStatus.SUCCESS
    assert "newclient" in result.message
    indexes = [e["index"] for e in session["decoded_data"][0]["normalize"]]
    assert "newclient" in indexes


def test正则提取适配器注入假LLM生成():
    """pattern 缺省时经注入假 LLM 生成并执行。"""
    session = {"decoded_data": _config()}
    step = RegexExtractStep(
        step_id="r1",
        type="regex_extract",
        source_field="req_header",
        description="请求头里的 Referer",
        config_ref="session.decoded_config",
    )
    adapter = FieldSkillAdapter(
        regex_llm=_fake_pattern_llm(r"[\S\s]*Referer: (.*?)\r\n[\S\s]*")
    )
    result = _run(adapter, step, session)
    assert result.status == StepStatus.SUCCESS
    indexes = [e["index"] for e in session["decoded_data"][0]["normalize"]]
    assert "Referer" in indexes  # Referer 不存在 → 原名


def test正则提取无样本且无正则时失败():
    """被提取字段无样本且用户未提供正则 → sample_required。"""
    empty_sample = [
        {
            "name": "r",
            "normalize": [{"index": "original_log", "result": []}],
            "parser": {"filter": []},
        }
    ]
    step = RegexExtractStep(
        step_id="r1",
        type="regex_extract",
        source_field="original_log",
        description="client",
        config_ref="session.decoded_config",
    )
    result = _run(FieldSkillAdapter(), step, {"decoded_data": empty_sample})
    assert result.status == StepStatus.FAILED
    assert result.error_code == "sample_required"


# ---------------------------------------------------------------------------
# 契约与注册表
# ---------------------------------------------------------------------------


def test新步骤进入判别联合与注册表():
    """契约可用；注册表两个新条目指向真实脚本并可加载。"""
    decision = PlanDecision(
        decision="execute",
        plan_id="p",
        steps=(
            DecodeFieldsStep(
                step_id="d1", type="decode_fields", fields=("a",), config_ref="session.decoded_config"
            ),
            RegexExtractStep(
                step_id="r1",
                type="regex_extract",
                source_field="original_log",
                description="x",
                config_ref="session.mapped_sub_rules",
                depends_on=("d1",),
            ),
        ),
    )
    assert [s.type for s in decision.steps] == ["decode_fields", "regex_extract"]

    for step_type in ("decode_fields", "regex_extract"):
        script_rel, function_name = FIELD_SKILL_REGISTRY[step_type]
        assert (_REPO_ROOT / script_rel).is_file(), script_rel
        assert _load_skill_function(step_type).__name__ == function_name
