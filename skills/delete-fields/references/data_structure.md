# 删除字段 - 数据结构参考

## 整体结构

Base64 解码后是一个 JSON 数组，每个元素是一个 mapping entity：

```json
[
  {
    "name": "规则名称",
    "normalize": [...],
    "parser": {
      "name": "json",
      "filter": [...]
    }
  }
]
```

## normalize 条目结构

```json
{
  "mappings": [],
  "field": null,
  "sim": null,
  "result": ["字段值"],
  "info": null,
  "entity": null,
  "required": false,
  "core": null,
  "value": null,
  "index": "字段名"
}
```

## removeFields 过滤器结构

### 删除单个字段
```json
{
  "name": "removeFields",
  "id": "",
  "fields": ["a"]
}
```

### 删除多个字段
```json
{
  "name": "removeFields",
  "id": "",
  "fields": ["a", "b"]
}
```

## 删除示例 - 完整输入输出

### 输入数据
normalize:
```json
[
  {"index": "a", "result": ["1"], "mappings": [], "field": null, "sim": null, "info": null, "entity": null, "required": false, "core": null, "value": null},
  {"index": "b", "result": ["2"], "mappings": [], "field": null, "sim": null, "info": null, "entity": null, "required": false, "core": null, "value": null},
  {"index": "c", "result": ["3"], "mappings": [], "field": null, "sim": null, "info": null, "entity": null, "required": false, "core": null, "value": null},
  {"index": "original_log", "result": ["{\"a\":1,\"b\":\"2\",\"c\":\"3\"}"], "field": "original_log", "sim": true, "entity": "日志", "required": false, "core": false, "mappings": [], "info": null, "value": null}
]
```

filter:
```json
[
  {"name": "addFields", "id": "additional_fields_filter", "fields": {"product": "", "event_name": "", "event_level": "", "log_vendor": ""}}
]
```

### 删除指令
"删除字段 a"

### 输出数据
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

### 用户指令
"删除字段 a 和 b"

### 输出
filter 新增：
```json
{"name": "removeFields", "id": "", "fields": ["a", "b"]}
```

normalize 移除了 index="a" 和 index="b" 的条目。

## 合并 removeFields

如果 filter 中已存在 removeFields 条目，新删除的字段会合并到已有的 fields 数组中：

### 已有 filter
```json
{"name": "removeFields", "id": "", "fields": ["a"]}
```

### 再次删除 "b"
```json
{"name": "removeFields", "id": "", "fields": ["a", "b"]}
```

## 系统保留字段

以下字段不允许删除：
- `original_log` — 原始日志字段
- `rule_name_list` — 解析规则链

尝试删除这些字段时会返回错误提示。
