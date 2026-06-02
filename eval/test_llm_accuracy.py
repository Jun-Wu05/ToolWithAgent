"""阶段2：LLM 选择准确率测试 — 需要 LLM 调用

评估 LLM 从 top-K 候选中选择正确标准字段的能力。
使用生产环境的 field_weak.md prompt，确保测试结果反映真实表现。

指标：
- Precision@1（LLM 首选正确率）
- 负例判断准确率（应标"未匹配"时正确标了）

用法：
    pytest eval/test_llm_accuracy.py -v -s
    pytest eval/test_llm_accuracy.py -v -k "test_llm_precision"

注意：需要配置 LLM API key
"""

import os
import sys
import json
import re
from typing import Any

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agent.tools.standard_mapper import query_field_candidates, _load_standard_fields_list
from agent.tools.pipeline.llm_client import _call_llm_direct
from agent.prompts import load_field_weak_prompt


def _build_llm_prompt(cases: list[dict], fields_table: list[dict]) -> str:
    """构建 LLM 映射 prompt（使用生产环境 field_weak.md + 候选列表）"""
    # 加载生产 prompt
    system_prompt = load_field_weak_prompt()

    # 构建字段候选列表（用户输入）
    field_entries: list[str] = []
    for case in cases:
        raw = case["raw_field"]
        log_ctx = case.get("log_context", "")
        candidates = query_field_candidates(raw, fields_table, top_k=3)

        entry = {"原始字段": raw}
        if log_ctx:
            entry["日志上下文"] = log_ctx
        if candidates:
            cand_list = []
            for score, name in candidates:
                # 查找英文字段名
                eng_name = ""
                for f in fields_table:
                    if f.get("系统属性名称") == name:
                        eng_name = f.get("字段名称", "")
                        break
                cand_list.append(f"{name}({score:.2f}, {eng_name})" if eng_name else f"{name}({score:.2f})")
            entry["标准字段候选"] = cand_list
        else:
            entry["标准字段候选"] = ["无候选"]
        field_entries.append(json.dumps(entry, ensure_ascii=False))

    user_input = (
        "请为以下字段映射到标准字段：\n\n"
        + "\n".join(field_entries)
        + "\n\n请严格按 JSON 数组格式返回结果。"
    )

    # 拼接 system + user（_call_llm_direct 只支持单条消息）
    return system_prompt + "\n\n" + user_input


def _parse_llm_mapping_result(llm_output: str) -> list[dict] | None:
    """3 层健壮解析 LLM 输出"""
    if not llm_output or not llm_output.strip():
        return None
    text = llm_output.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


@pytest.mark.llm
class TestLLMAccuracy:
    """LLM 选择准确率测试（需要 API key，标记 @pytest.mark.llm）"""

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, request):
        """加载标准字段表"""
        cls = request.cls
        cls.fields_table = _load_standard_fields_list()
        assert cls.fields_table, "标准字段表为空"

    def test_llm_precision_positive(self, positive_cases):
        """正例：LLM 选择准确率"""
        prompt = _build_llm_prompt(positive_cases, self.fields_table)

        try:
            llm_output = _call_llm_direct(prompt, max_tokens=4000)
        except Exception as e:
            pytest.skip(f"LLM 调用失败: {e}")

        mappings = _parse_llm_mapping_result(llm_output)
        if not mappings:
            pytest.fail(f"LLM 输出解析失败: {llm_output[:200]}")

        llm_map: dict[str, str] = {}
        for item in mappings:
            raw = item.get("原始字段名", "")
            std = item.get("系统属性名称", "")
            if std == "未匹配":
                std = "UNMATCHED"
            llm_map[raw] = std

        hits = 0
        misses: list[dict] = []
        for case in positive_cases:
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            actual = llm_map.get(raw, "(未返回)")

            if actual == expected:
                hits += 1
            else:
                misses.append({"raw": raw, "expected": expected, "actual": actual})

        total = len(positive_cases)
        precision = hits / total if total else 0
        print(f"\n[LLM Precision@1] {hits}/{total} = {precision:.1%}")
        if misses:
            print(f"  错误 ({len(misses)}):")
            for m in misses[:15]:
                print(f"    {m['raw']} → 期望={m['expected']}, 实际={m['actual']}")

        assert precision >= 0.50, f"LLM Precision@1 = {precision:.1%}，低于基线 50%"

    def test_llm_negative_accuracy(self, negative_cases):
        """负例：LLM 正确标为"未匹配"的比例"""
        prompt = _build_llm_prompt(negative_cases, self.fields_table)

        try:
            llm_output = _call_llm_direct(prompt, max_tokens=2000)
        except Exception as e:
            pytest.skip(f"LLM 调用失败: {e}")

        mappings = _parse_llm_mapping_result(llm_output)
        if not mappings:
            pytest.fail(f"LLM 输出解析失败: {llm_output[:200]}")

        llm_map: dict[str, str] = {}
        for item in mappings:
            raw = item.get("原始字段名", "")
            std = item.get("系统属性名称", "")
            llm_map[raw] = std

        correct_rejects = 0
        false_accepts: list[dict] = []
        for case in negative_cases:
            raw = case["raw_field"]
            actual = llm_map.get(raw, "(未返回)")

            if actual == "未匹配":
                correct_rejects += 1
            else:
                false_accepts.append({"raw": raw, "actual": actual})

        total = len(negative_cases)
        reject_rate = correct_rejects / total if total else 0
        print(f"\n[负例拒绝率] {correct_rejects}/{total} = {reject_rate:.1%}")
        if false_accepts:
            print(f"  误匹配 ({len(false_accepts)}):")
            for f in false_accepts:
                print(f"    {f['raw']} → {f['actual']}")

        assert reject_rate >= 0.40, f"负例拒绝率 = {reject_rate:.1%}，低于基线 40%"