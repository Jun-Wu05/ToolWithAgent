---
name: regex-extract-field
description: 正则提取字段技能 - 在解析规则上用正则从已有字段（如原始日志、请求头）提取出一个新字段。当用户说"把原始日志里的 X 提取出来、把请求头里的 X 提取出来、正则提取"时使用；正则由系统按样本生成并强制全匹配校验。
license: MIT
metadata:
  version: "1.0.0"
  tags: ["regex", "extract", "parser"]
---

# 正则提取字段技能

## 何时使用
- 用户说"帮我把原始日志里的 client 提取出来"、"把 req_header 的 Referer 提取出来"时
- 用户需要从长文本字段（原始日志 / 解码后的请求头）中提取子内容为新字段

## 语义映射（Planner 消歧已固化）
- 「原始日志里的 X」→ 被提取字段 = `original_log`
- 「请求头里的 X」→ 被提取字段 = `req_header`
- 被提取字段必须取自配置 normalize 里的 index

## 前置条件
- 会话中存在可调整的解析规则（session.decoded_config 或 session.mapped_sub_rules）
- 被提取字段有样本值（正则生成的依据）；无样本时用户需直接提供正则

## 调用链路（ADR-0008 类型化接线）

```
用户指令 → PlannerAgent 生成 regex_extract 类型化步骤
  （source_field / description / 可选 new_field 与 pattern / config_ref）
→ FieldSkillAdapter（application/adapters/field_skill.py）：pattern 缺省时调 agent/shared/regex_extract.py
  按样本 LLM 生成（re.compile + fullmatch 硬校验，失败带反馈重试一次）
→ scripts/extract_field.py 的 extract_field() 纯函数（单一事实源）
→ 结果写回 session，产物消息附正则原文
```

Planner **不得自行编造正则**；只有用户直接给出正则时才携带 pattern。

## 数据操作（scripts/extract_field.py）

双写：

1. parser.filter 追加（或合并进）customFunction 过滤器：
   ```json
   {
     "custom_name": "extractRegexField",
     "fields": [{
       "functionName": "extractRegexField",
       "ognl": "<%@com.hansight.dataviewer.utils.ognl.OgnlUtils@regexExtraction(arg2,\"arg3\")%>",
       "functionViewName": "正则提取",
       "fieldName": "",
       "args": [
         {"name": "新增字段", "args": "arg1", "detail": "新增字段名称", "type": "field", "value": "newclient"},
         {"name": "被提取字段", "args": "arg2", "detail": "字符格式字段", "type": "args", "value": "original_log"},
         {"name": "正则表达式", "args": "arg3", "detail": "只提取第一个匹配项", "type": "args", "value": "[\\S\\s]*client=\"(.*?)\"[\\S\\s]*"}
       ]
     }],
     "name": "customFunction",
     "id": ""
   }
   ```
2. normalize 末尾追加新字段条目，result 为样本验证时第一个捕获组的**预览值**。

## 硬性校验
- **正则必须全匹配整条样本**（设计约束：非全匹配在解析器中不生效）——脚本用 re.fullmatch 验证，失败返回 `pattern_mismatch`
- 正则语法非法返回 `invalid_pattern`
- 被提取字段不存在返回 `field_not_found`；新字段名冲突返回 `field_conflict`
- 新字段名缺省时自动推导：关键词可用则用原名，已存在则加 `new` 前缀（如 client 已存在 → newclient）

## 已知边界
- 正则按**第一个有样本的 entity** 生成并验证；多条子规则形态各异时一份正则不一定适配全部
- **子规则寻址（#126）**：`target_names` 按 entity name 精确过滤（None=全部），名单外原样透传
