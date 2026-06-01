"""阶段1：候选召回率测试 — 使用统一的 query_field_candidates()

验证 _split_compound_field + synonyms + _calculate_similarity 的联合效果。

指标：
- Recall@1（top-1 候选即正确）
- Recall@3（top-3 候选中包含正确答案）
- MRR（Mean Reciprocal Rank）
- 按分类维度的分组召回率

用法：
    pytest eval/test_candidate_recall.py -v -s
"""

import os
import sys
import json
from datetime import datetime

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agent.tools.standard_mapper import query_field_candidates, _load_standard_fields_list


class TestCandidateRecall:
    """候选召回率测试"""

    @pytest.fixture(autouse=True, scope="class")
    def setup_table(self, request):
        """加载标准字段表（class 级别共享）"""
        cls = request.cls
        cls.fields_table = _load_standard_fields_list()
        assert cls.fields_table, "标准字段表为空"

    def test_positive_recall_at_1(self, positive_cases):
        """正例 Recall@1：top-1 候选即正确"""
        hits = 0
        misses = []

        for case in positive_cases:
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=1)

            if candidates and candidates[0][1] == expected:
                hits += 1
            else:
                misses.append({
                    "raw": raw,
                    "expected": expected,
                    "got": candidates[0][1] if candidates else "(无候选)",
                    "score": candidates[0][0] if candidates else 0,
                })

        total = len(positive_cases)
        recall_at_1 = hits / total if total else 0
        print(f"\n[Recall@1] {hits}/{total} = {recall_at_1:.1%}")
        if misses:
            print(f"  未命中 ({len(misses)}):")
            for m in misses[:15]:
                print(f"    {m['raw']} -> 期望={m['expected']}, 实际={m['got']} (score={m['score']:.3f})")

        assert recall_at_1 >= 0.50, f"Recall@1 = {recall_at_1:.1%}，低于基线 50%"

    def test_positive_recall_at_3(self, positive_cases):
        """正例 Recall@3：top-3 候选中包含正确答案"""
        hits = 0
        misses = []

        for case in positive_cases:
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=3)
            candidate_names = [name for _, name in candidates]

            if expected in candidate_names:
                hits += 1
            else:
                misses.append({
                    "raw": raw,
                    "expected": expected,
                    "top3": candidate_names,
                })

        total = len(positive_cases)
        recall_at_3 = hits / total if total else 0
        print(f"\n[Recall@3] {hits}/{total} = {recall_at_3:.1%}")
        if misses:
            print(f"  未命中 ({len(misses)}):")
            for m in misses[:15]:
                print(f"    {m['raw']} -> 期望={m['expected']}, top3={m['top3']}")

        assert recall_at_3 >= 0.80, f"Recall@3 = {recall_at_3:.1%}，低于基线 80%"

    def test_positive_recall_at_5(self, positive_cases):
        """正例 Recall@5：top-5 候选中包含正确答案（生产环境使用 top_k=5 + LLM 二次筛选）"""
        hits = 0
        misses = []

        for case in positive_cases:
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=5)
            candidate_names = [name for _, name in candidates]

            if expected in candidate_names:
                hits += 1
            else:
                misses.append({
                    "raw": raw,
                    "expected": expected,
                    "top5": candidate_names,
                })

        total = len(positive_cases)
        recall_at_5 = hits / total if total else 0
        print(f"\n[Recall@5] {hits}/{total} = {recall_at_5:.1%}")
        if misses:
            print(f"  未命中 ({len(misses)}):")
            for m in misses[:15]:
                print(f"    {m['raw']} -> 期望={m['expected']}, top5={m['top5']}")

        # 基线 85%：剩余 hard case（src_ip/ip/mac_address 等）是本质歧义，
        # 需要 LLM 二次筛选才能解决（这正是两阶段架构的设计意图）
        assert recall_at_5 >= 0.85, f"Recall@5 = {recall_at_5:.1%}，低于基线 85%"

    def test_mrr(self, positive_cases):
        """MRR（Mean Reciprocal Rank）"""
        rr_sum = 0.0

        for case in positive_cases:
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=10)
            candidate_names = [name for _, name in candidates]

            if expected in candidate_names:
                rank = candidate_names.index(expected) + 1
                rr_sum += 1.0 / rank

        total = len(positive_cases)
        mrr = rr_sum / total if total else 0
        print(f"\n[MRR] {mrr:.3f}")

        assert mrr >= 0.50, f"MRR = {mrr:.3f}，低于基线 0.50"

    def test_negative_no_match(self, negative_cases):
        """负例：记录误匹配基线"""
        false_matches = 0

        for case in negative_cases:
            raw = case["raw_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=1)
            if candidates and candidates[0][0] > 0.5:
                false_matches += 1

        total = len(negative_cases)
        print(f"\n[负例误匹配] {false_matches}/{total} 个负例有高分候选(>0.5)")

    def test_category_breakdown(self, positive_cases):
        """按分类维度统计 Recall@3"""
        from collections import defaultdict
        cat_hits = defaultdict(int)
        cat_total = defaultdict(int)

        for case in positive_cases:
            cat = case.get("category", "未知")
            cat_total[cat] += 1
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=3)
            candidate_names = [name for _, name in candidates]
            if expected in candidate_names:
                cat_hits[cat] += 1

        print(f"\n[分类 Recall@3]")
        for cat in sorted(cat_total.keys()):
            hits = cat_hits[cat]
            total = cat_total[cat]
            print(f"  {cat}: {hits}/{total} = {hits/total:.0%}" if total else f"  {cat}: 0/0")

    def test_nested_field_recall(self):
        """嵌套字段 (a.b 格式) 召回率测试"""
        nested_cases = [
            {"raw_field": "detail.srcIp", "expected": "源地址"},
            {"raw_field": "detail.dstPort", "expected": "目的端口"},
            {"raw_field": "connection.protocol", "expected": "协议"},
            {"raw_field": "machine.extranetIp", "expected": "源地址"},
            {"raw_field": "threat.riskLevel", "expected": "威胁等级"},
        ]

        hits = 0
        misses = []

        for case in nested_cases:
            raw = case["raw_field"]
            expected = case["expected"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=3)
            candidate_names = [name for _, name in candidates]
            if expected in candidate_names:
                hits += 1
            else:
                misses.append({"raw": raw, "expected": expected, "top3": candidate_names})

        total = len(nested_cases)
        rate = hits / total if total else 0
        print(f"\n[嵌套字段 Recall@3] {hits}/{total} = {rate:.0%}")
        if misses:
            for m in misses:
                print(f"  未命中: {m['raw']} -> 期望={m['expected']}, top3={m['top3']}")

        assert rate >= 0.60, f"嵌套字段 Recall@3 = {rate:.0%}，低于基线 60%"

    def test_generate_report(self, golden_cases, tmp_path):
        """生成评估报告 JSON"""
        positive = [c for c in golden_cases if c["expected_standard_field"] != "UNMATCHED"]

        results = []
        for case in positive:
            raw = case["raw_field"]
            expected = case["expected_standard_field"]
            candidates = query_field_candidates(raw, self.fields_table, top_k=3)
            candidate_names = [name for _, name in candidates]
            hit = expected in candidate_names
            results.append({
                "id": case["id"],
                "raw_field": raw,
                "expected": expected,
                "top3_candidates": [(round(s, 3), n) for s, n in candidates],
                "recall@3": hit,
                "category": case.get("category", ""),
            })

        total = len(positive)
        r1 = sum(1 for r in results if r["top3_candidates"] and r["top3_candidates"][0][1] == r["expected"])
        r3 = sum(1 for r in results if r["recall@3"])

        report = {
            "timestamp": datetime.now().isoformat(),
            "metrics": {
                "recall@1": r1 / total if total else 0,
                "recall@3": r3 / total if total else 0,
            },
            "details": results,
        }

        report_path = tmp_path / "candidate_recall_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[报告] Recall@1={report['metrics']['recall@1']:.1%}, Recall@3={report['metrics']['recall@3']:.1%}")
        assert report_path.exists()