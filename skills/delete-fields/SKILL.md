---
name: delete-fields
description: 删除字段技能 - 当用户需要从配置数据中移除一个或多个字段时使用。触发词：删除字段、移除字段、去掉字段、删掉字段、delete field、remove field、清除字段。用户在 Base64 配置数据上执行字段删除操作时必须调用此技能。
license: MIT
metadata:
  version: "1.0.0"
  tags: ["delete", "fields", "parser"]
---

# 删除字段技能

## 何时使用
- 用户说"删除字段"、"移除字段"、"去掉字段"、"删掉字段"时
- 用户需要从配置数据中移除一个或多个字段时
- 用户指定了要删除的字段名时

## 前置条件
- 用户已提供 Base64 编码的配置数据（或 session 中已有解码后的数据）
- 用户指定了要删除的字段名列表

## 操作步骤

### Step 1: 获取 Base64 数据
从用户输入或 session 中获取 Base64 编码的配置数据。使用 `base64_decode_tool` 解码，得到 JSON 数组。

### Step 2: 解析用户删除指令
从用户输入中提取：
- `fields_to_delete`: 要删除的字段名列表（如 `["a"]` 或 `["a", "b"]`）

### Step 3: 执行删除
调用 `scripts/delete_fields.py` 中的 `delete_field()` 函数，对每个 entity 执行：

1. **验证字段存在**：检查 normalize 中是否包含要删除的字段的 index
2. **添加 removeFields filter**：在 parser.filter 中新增：
   ```json
   {"name": "removeFields", "id": "", "fields": ["<field1>", "<field2>"]}
   ```
3. **移除 normalize 条目**：从 normalize 数组中移除 index 匹配的条目

### Step 4: 编码输出
使用 `base64_encode_tool` 将修改后的 JSON 数组重新编码为 Base64。

### Step 5: 返回结果
- 输出 Base64 编码的完整配置数据
- 简要告知用户删除了哪些字段

## 输出格式示例

删除后的 normalize（字段 "a" 的条目被移除）：
```json
[
  {"index": "b", "result": ["2"], ...},
  {"index": "c", "result": ["3"], ...},
  {"index": "original_log", ...}
]
```

filter 新增：
```json
{
  "name": "removeFields",
  "id": "",
  "fields": ["a"]
}
```

删除多个字段的 filter：
```json
{
  "name": "removeFields",
  "id": "",
  "fields": ["a", "b"]
}
```

## 约束与边界
- 字段不存在时：告知用户哪些字段不存在，列出 normalize 中可用的字段 index
- 多字段删除：所有要删除的字段放在同一个 removeFields filter 的 fields 数组中
- 不删除系统保留字段（如 original_log、rule_name_list），如遇用户要求删除需提醒
- 所有 entity 共享同一份 normalize 结构，删除操作应用到每一个 entity

## 完整示例

### 输入
用户指令："删除字段 a"
Base64 解码后第一部分的 normalize：
```json
[
  {"index": "a", "result": ["1"], ...},
  {"index": "b", "result": ["2"], ...},
  {"index": "c", "result": ["3"], ...},
  {"index": "original_log", "result": ["{\"a\":1,\"b\":\"2\",\"c\":\"3\"}"], ...}
]
```

### 处理
- fields_to_delete = ["a"]

### 输出
normalize 移除了 index="a" 的条目：
```json
[
  {"index": "b", "result": ["2"], ...},
  {"index": "c", "result": ["3"], ...},
  {"index": "original_log", ...}
]
```
filter 新增：
```json
{"name": "removeFields", "id": "", "fields": ["a"]}
```

## 多字段删除示例

用户指令："删除字段 a 和 b"

输出 filter：
```json
{"name": "removeFields", "id": "", "fields": ["a", "b"]}
```
