---
name: merge-fields
description: 合并字段技能 - 当用户需要把多个字段合并成一个新字段时使用。触发词：合并字段、字段合并、把XX和XX合并成XX、merge fields、将XX合并为XX。用户在 Base64 配置数据上执行字段合并操作时必须调用此技能。
license: MIT
metadata:
  version: "1.0.0"
  tags: ["merge", "fields", "parser"]
---

# 合并字段技能

## 何时使用
- 用户说"合并字段"、"字段合并"、"把XX和XX合并成XX"、"将XX和XX合并为XX"时
- 用户需要将多个已有字段合并为一个新字段时
- 用户在 Base64 配置数据上执行合并操作时

## 前置条件
- 用户已提供 Base64 编码的配置数据（或 session 中已有解码后的数据）
- 用户指定了：源字段列表、目标字段名、分隔符（可为空字符串）

## 操作步骤

### Step 1: 获取 Base64 数据
从用户输入或 session 中获取 Base64 编码的配置数据。使用 `base64_decode_tool` 解码，得到 JSON 数组。

### Step 2: 解析用户合并指令
从用户输入中提取：
- `source_fields`: 源字段名列表（如 `["a", "b"]`）
- `target_field`: 目标字段名（如 `"d"`）
- `sep`: 分隔符（如 `""`、`"-"`、`":"`）

### Step 3: 执行合并
调用 `scripts/merge_fields.py` 中的 `merge_fields()` 函数，对每个 entity 执行：

1. **验证源字段存在**：检查 normalize 中是否包含所有源字段的 index
2. **检查目标字段冲突**：目标字段名不能已存在于 normalize 中
3. **添加 merger filter**：在 parser.filter 中新增：
   ```json
   {"name": "merger", "field": "<target_field>", "sep": "<sep>", "id": "", "fields": ["<source1>", "<source2>"]}
   ```
4. **添加 normalize 条目**：在 normalize 数组末尾新增：
   ```json
   {"mappings": [], "field": null, "sim": null, "result": ["<合并后的值>"], "info": null, "entity": null, "required": false, "core": null, "value": null, "index": "<target_field>"}
   ```
   其中 result 的值 = 各源字段 `result[0]` 用 `sep` 拼接

### Step 4: 编码输出
使用 `base64_encode_tool` 将修改后的 JSON 数组重新编码为 Base64。

### Step 5: 返回结果
- 输出 Base64 编码的完整配置数据
- 简要告知用户合并了哪些字段到哪个新字段

## 输出格式示例

合并后的 normalize 新增条目：
```json
{
  "mappings": [],
  "field": null,
  "sim": null,
  "result": ["12"],
  "info": null,
  "entity": null,
  "required": false,
  "core": null,
  "value": null,
  "index": "d"
}
```

合并后的 parser.filter 新增条目：
```json
{
  "name": "merger",
  "field": "d",
  "sep": "",
  "id": "",
  "fields": ["a", "b"]
}
```

## 约束与边界
- 源字段不存在时：告知用户哪些字段不存在，列出 normalize 中可用的字段 index
- 目标字段已存在时：告知用户冲突，建议更换名称或先删除原有字段
- 分隔符为空字符串时：直接拼接，不插入任何字符
- 源字段数量为 1 个时：提示合并操作至少需要 2 个源字段
- 所有 entity 共享同一份 normalize 结构，合并操作应用到每一个 entity

## 完整示例

### 输入
用户指令："把字段 a 和字段 b 合并成字段 d"
Base64 解码后第一部分的 normalize：
```json
[
  {"index": "a", "result": ["1"], ...},
  {"index": "b", "result": ["2"], ...},
  {"index": "c", "result": ["3"], ...}
]
```

### 处理
- source_fields = ["a", "b"]
- target_field = "d"
- sep = ""
- merged_result = "1" + "" + "2" = "12"

### 输出
normalize 新增：
```json
{"index": "d", "result": ["12"], ...}
```
filter 新增：
```json
{"name": "merger", "field": "d", "sep": "", "id": "", "fields": ["a", "b"]}
```
