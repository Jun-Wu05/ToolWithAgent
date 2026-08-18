# 合并字段 - 数据结构参考

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

关键字段：
- `index`：字段标识名（如 "a"、"b"、"主机ip"）
- `result`：字段值数组，合并时取 `result[0]` 进行拼接

## parser.filter 条目结构

### merger - 合并过滤器（本技能新增）
```json
{
  "name": "merger",
  "field": "目标字段名",
  "sep": "分隔符",
  "id": "",
  "fields": ["源字段1", "源字段2"]
}
```

- `field`：合并后的新字段名
- `sep`：拼接分隔符（可为空字符串 ""）
- `fields`：参与合并的源字段列表（2个及以上）

### addFields - 添加字段过滤器
```json
{
  "name": "addFields",
  "id": "",
  "fields": {
    "字段名": "字段值或%{引用}"
  }
}
```

### removeFields - 删除字段过滤器
```json
{
  "name": "removeFields",
  "id": "",
  "fields": ["字段名1", "字段名2"]
}
```

## 合并示例 - 完整输入输出

### 输入数据
normalize:
```json
[
  {"index": "a", "result": ["1"], "mappings": [], "field": null, "sim": null, "info": null, "entity": null, "required": false, "core": null, "value": null},
  {"index": "b", "result": ["2"], "mappings": [], "field": null, "sim": null, "info": null, "entity": null, "required": false, "core": null, "value": null}
]
```

### 合并指令
"把 a 和 b 合并成 d，分隔符为空"

### 输出数据
normalize 新增：
```json
{"index": "d", "result": ["12"], "mappings": [], "field": null, "sim": null, "info": null, "entity": null, "required": false, "core": null, "value": null}
```

filter 新增：
```json
{"name": "merger", "field": "d", "sep": "", "id": "", "fields": ["a", "b"]}
```

## 多字段合并

当用户说"把 a、b、c 合并成 d，分隔符用 -"时：
- source_fields = ["a", "b", "c"]
- sep = "-"
- result = "1" + "-" + "2" + "-" + "3" = "1-2-3"

输出 merger filter：
```json
{"name": "merger", "field": "d", "sep": "-", "id": "", "fields": ["a", "b", "c"]}
```

## 引用说明

如果用户说"把 a 和 b 合并成 d，但 b 用已有字段的值"，合并逻辑不变——
它从 normalize 中取各源字段的 `result[0]` 进行拼接，不涉及 parser 层的 %{引用} 语法。
