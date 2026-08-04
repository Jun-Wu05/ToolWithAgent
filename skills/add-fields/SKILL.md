---
name: add-fields
description: 添加字段技能 - 当用户需要在配置数据中新增一个字段时使用。触发词：添加字段、新增字段、增加字段、add field、插入字段、加入字段。用户在 Base64 配置数据上执行字段添加操作时必须调用此技能。
license: MIT
metadata:
  version: "1.0.0"
  tags: ["add", "fields", "parser"]
---

# 添加字段技能

## 何时使用
- 用户说"添加字段"、"新增字段"、"增加字段"、"插入字段"时
- 用户需要在配置数据中新增一个字段时
- 用户指定了新字段的名称和值的来源（固定值或引用已有字段）时

## 前置条件
- 用户已提供 Base64 编码的配置数据（或 session 中已有解码后的数据）
- 用户指定了新字段的名称
- 用户指定了新字段的值来源：固定值（如 "1.1.1.1"）或引用已有字段（如 `%{reqheader}`）

## 操作步骤

### Step 1: 获取数据
输入中已包含解码后的 JSON 数据（mapping entity 数组），直接使用。

### Step 2: 解析用户添加指令
从用户输入中提取：
- `field_name`: 新字段名（如 `"主机ip"`）
- `field_value`: 字段值（如 `"1.1.1.1"`）
- `value_type`: 值类型 — `"fixed"`（固定值）或 `"reference"`（引用已有字段，格式为 `%{index}`）

### Step 3: 执行添加
调用 `scripts/add_fields.py` 中的 `add_field()` 函数，对每个 entity 执行：

1. **验证字段不存在**：检查 normalize 中是否已存在该字段名
2. **处理值引用**：如果值是 `%{index}` 格式，保留原字符串（运行时由解析器替换）
3. **添加 addFields filter**：在 parser.filter 中新增：
   ```json
   {"name": "addFields", "id": "", "fields": {"<field_name>": "<field_value>"}}
   ```
4. **添加 normalize 条目**：在 normalize 数组末尾新增：
   ```json
   {"mappings": [], "field": null, "sim": null, "result": ["<field_value>"], "info": null, "entity": null, "required": false, "core": null, "value": null, "index": "<field_name>"}
   ```
   注意：如果用户未提供值，result 为空数组 `[]`

### Step 4: 返回结果
输出修改后的完整 JSON 数组。

## 输出格式示例

添加后的 normalize 新增条目：
```json
{
  "mappings": [],
  "field": null,
  "sim": null,
  "result": ["1.1.1.1"],
  "info": null,
  "entity": null,
  "required": false,
  "core": null,
  "value": null,
  "index": "主机ip"
}
```

添加后的 parser.filter 新增条目：
```json
{
  "name": "addFields",
  "id": "",
  "fields": {
    "主机ip": "1.1.1.1"
  }
}
```

## 引用已有字段的示例

用户说："新增字段请求头，引用 reqheader 的值"

filter 新增：
```json
{
  "name": "addFields",
  "id": "",
  "fields": {
    "请求头": "%{reqheader}"
  }
}
```

normalize 新增：
```json
{
  "index": "请求头",
  "result": ["%{reqheader}"],
  ...
}
```

## 约束与边界
- 字段名已存在时：告知用户冲突，建议更换名称或先删除原有字段
- 值为空时：result 设为空数组 `[]`，filter 中 value 设为空字符串 `""`
- 引用格式 `%{index}` 中的 index 指向已有字段的 normalize index
- 所有 entity 共享同一份 normalize 结构，添加操作应用到每一个 entity

## 完整示例

### 输入
用户指令："添加字段 主机ip，值为 1.1.1.1"
Base64 解码后第一部分的 normalize：
```json
[
  {"index": "a", "result": ["1"], ...},
  {"index": "b", "result": ["2"], ...}
]
```

### 处理
- field_name = "主机ip"
- field_value = "1.1.1.1"
- value_type = "fixed"

### 输出
normalize 新增：
```json
{"index": "主机ip", "result": ["1.1.1.1"], ...}
```
filter 新增：
```json
{"name": "addFields", "id": "", "fields": {"主机ip": "1.1.1.1"}}
```
