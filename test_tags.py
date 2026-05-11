"""临时测试：验证标签生成和缓存重建后的检索效果"""
import sys
sys.path.insert(0, ".")
from agent.core.field_retriever import (
    init_field_cache,
    _debug_lookup,
    _load_cache,
    _generate_field_tags,
    _build_query_text_for_embedding,
)

print("=" * 60)
print("1. 标签生成测试")
print("=" * 60)
test_cases = [
    "destAddress",
    "srcAddress",
    "sendTime",
    "processId",
    "dst_ip_list",
    "srcPort",
    "destPort",
    "protocolType",
    "eventCount",
    "macAddress",
    "deviceName",
]
for tc in test_cases:
    tags = _generate_field_tags(tc)
    qtext = _build_query_text_for_embedding(tc)
    print(f"  {tc:20s} tags={tags}")
    print(f"  {'':20s} query_text={qtext}")
    print()

print("=" * 60)
print("2. 重建 Embedding 缓存")
print("=" * 60)
ok = init_field_cache(force_refresh=True)
print(f"  缓存重建: {'成功' if ok else '失败'}")

print()
print("=" * 60)
print("3. 验证目标字段的标签")
print("=" * 60)
emb, recs = _load_cache()
if recs:
    interesting = [r for r in recs if "address" in r.get("字段名称", "").lower()]
    for r in interesting[:8]:
        name = r.get("字段名称", "")
        sys_name = r.get("系统属性名称", "")
        tags = r.get("_tags", [])
        comp = r.get("_composite_text", "")[:120]
        print(f"  {sys_name:30s} ({name:15s}) tags={tags}")
        print(f"    composite: {comp}...")
        print()

print()
print("=" * 60)
print("4. destAddress 检索结果 (top-6)")
print("=" * 60)
result = _debug_lookup("destAddress", top_k=6)
print(result)
print()

print("=" * 60)
print("5. srcAddress 检索结果 (top-6)")
print("=" * 60)
result2 = _debug_lookup("srcAddress", top_k=6)
print(result2)