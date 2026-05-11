"""全面扫描标准字段表列对齐问题"""
with open("config/标准字段.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()

header = lines[0].strip().split("\t")
header[0] = header[0].lstrip("\ufeff")
print(f"Header ({len(header)} cols): {header}")

# 合法属性分类值（含中文字符）
valid_categories = set()
all_categories = set()

issues = []
for i, line in enumerate(lines):
    line = line.strip()
    if not line or i == 0:
        continue
    cols = line.split("\t")
    
    if len(cols) < 4:
        issues.append((i, "COL_COUNT", len(cols), cols))
        continue
    
    cat = cols[1]  # 属性分类
    field_name = cols[2]  # 字段名称
    attr_type = cols[3]  # 属性类型
    sys_name = cols[0]  # 系统属性名称
    
    all_categories.add(cat)
    
    has_cn = any('\u4e00' <= c <= '\u9fff' for c in cat)
    
    if not has_cn and cat:
        # col[1] 不含中文，可能是列错位
        # 检查 col[2] 是否含中文 (字段名称位不应含中文)
        has_cn_in_field = any('\u4e00' <= c <= '\u9fff' for c in field_name)
        # 检查 col[3] 是否含中文 (属性类型位不应含中文)
        has_cn_in_type = any('\u4e00' <= c <= '\u9fff' for c in attr_type)
        
        if has_cn_in_field or has_cn_in_type:
            issues.append((i, "MISALIGNED", cols, 
                          f"col[1]={cat}(no_CN), col[2]={field_name}({'CN' if has_cn_in_field else 'no_CN'}), col[3]={attr_type}({'CN' if has_cn_in_type else 'no_CN'})"))

print(f"\n=== 所有属性分类值 ({len(all_categories)}) ===")
for c in sorted(all_categories):
    print(f"  [{c}]")

print(f"\n=== 发现 {len(issues)} 个问题 ===")
for idx, typ, cols, detail in issues:
    print(f"\nLine {idx} [{typ}]: [{lines[idx].strip()}]")
    print(f"  系统属性名称: [{cols[0]}]")
    print(f"  Detail: {detail}")