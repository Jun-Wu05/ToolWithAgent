"""检查标准字段表列对齐"""
with open("config/标准字段.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()

header = lines[0].strip().split("\t")
header[0] = header[0].lstrip("\ufeff")
print(f"Header ({len(header)} cols): {header}")
print()

for idx in [391, 392, 393, 394, 395]:
    line = lines[idx].strip()
    cols = line.split("\t")
    print(f"Line {idx} ({len(cols)} cols):")
    for j, c in enumerate(cols):
        print(f"  col[{j}] = [{c}]")
    print()