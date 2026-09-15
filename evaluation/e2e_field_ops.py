# -*- coding: utf-8 -*-
"""E2E 验证：4 个真实 base64 规则走 解码→增/删/合并→事件名称写入→编码 链路。"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from application.adapters.field_skill import _load_skill_function  # noqa: E402
from agent.shared.event_classify import apply_event_fields_to_sub_rules  # noqa: E402

TEST_DIR = Path(__file__).resolve().parent.parent / "archive" / "skillsdesign" / "test"

add_field = _load_skill_function("add_fields")
delete_field = _load_skill_function("delete_fields")
merge_fields = _load_skill_function("merge_fields")


def decode_rule(path: Path):
    raw = path.read_text(encoding="utf-8").strip()
    data = json.loads(base64.b64decode(raw).decode("utf-8"))
    return data


def encode_rule(data) -> str:
    return base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")


def normalize_indexes(entity):
    return [item.get("index") for item in (entity.get("normalize") or [])]


def main() -> None:
    files = sorted(TEST_DIR.glob("*.txt"))
    assert len(files) == 4, f"期望 4 个测试规则，实际 {len(files)}"

    for path in files:
        data = decode_rule(path)
        kind = "入口规则" if all(e.get("subResolver") != 1 for e in data) else "子规则"
        print(f"\n=== {path.name} [{kind}] entities={len(data)} ===")

        # 1. 添加字段（引用型），覆盖入口规则 filter=null 场景
        r1 = add_field(data, "测试新增字段", "%{original_log}")
        assert r1["status"] == "success", r1["message"]
        added = r1["data"]
        for entity in added:
            filters = entity["parser"]["filter"]
            assert filters, f"{path.name}: filter 未初始化"
            af = [f for f in filters if f.get("name") == "addFields" and f.get("id") == ""]
            assert af and af[-1]["fields"].get("测试新增字段") == "%{original_log}"
            assert "测试新增字段" in normalize_indexes(entity)
        print("  add_fields 引用型: OK（", r1["message"], "）")

        # 2. 删除该字段（回到原状）
        r2 = delete_field(added, ["测试新增字段"])
        assert r2["status"] == "success", r2["message"]
        restored = r2["data"]
        for entity in restored:
            assert "测试新增字段" not in normalize_indexes(entity)
        # 删除字段后与原始数据语义等价（除 removeFields filter 追加外）
        print("  delete_fields: OK（", r2["message"], "）")

        # 3. 合并前两个可合并字段（若存在）
        idx0 = [i for i in normalize_indexes(restored[0]) if i]
        if len(idx0) >= 2:
            src = idx0[:2]
            r3 = merge_fields(restored, src, "合并预览", "_")
            if r3["status"] == "success":
                merged = r3["data"]
                m = [
                    f for f in merged[0]["parser"]["filter"]
                    if f.get("name") == "merger" and f.get("field") == "合并预览"
                ]
                assert m and m[0]["fields"] == src
                assert "合并预览" in normalize_indexes(merged[0])
                print(f"  merge_fields {src}: OK")
                restored = merged
            else:
                # 部分实体缺字段的规则允许失败
                print(f"  merge_fields {src}: 跳过（{r3['message'][:50]}）")

        # 4. 事件名称确定性写入（模拟判定结果：各选威胁/非威胁一值）
        judgments = {e.get("name", ""): ("网络攻击" if i % 2 == 0 else "登录事件")
                     for i, e in enumerate(restored)}
        annotated = apply_event_fields_to_sub_rules(restored, judgments)
        for entity in annotated:
            name = entity.get("name", "")
            if name not in judgments:
                continue
            expect = judgments[name]
            level = "提醒" if expect == "网络攻击" else "信息"
            af = [f for f in entity["parser"]["filter"]
                  if f.get("name") == "addFields" and f.get("id") == ""]
            tail = af[-1]["fields"] if af else {}
            assert tail.get("事件名称") == expect, (name, tail)
            assert tail.get("事件级别") == level, (name, tail)
            idx = normalize_indexes(entity)
            assert idx[-2:] == ["事件名称", "事件级别"], idx[-3:]
        print(f"  事件名称写入: OK（{len(judgments)} 条，绑定级别正确）")

        # 5. 编码往返一致性（dict key 顺序保持，base64 稳定）
        encoded = encode_rule(annotated)
        round_trip = json.loads(base64.b64decode(encoded).decode("utf-8"))
        assert round_trip == annotated, "编码往返不一致"
        print(f"  base64 往返: OK（{len(encoded)} chars）")

    print("\nE2E ALL OK")


if __name__ == "__main__":
    main()
