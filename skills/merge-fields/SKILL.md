---
name: merge-fields
description: 合并字段技能 - 把解析规则（Base64 配置或映射生成的子规则）中多个已有字段的值合并成一个新字段。当用户说"合并字段、字段合并、把XX和XX合并成XX、将XX合并为XX、merge fields"并给出源字段、目标字段名（分隔符可选）时使用。
license: MIT
metadata:
  version: "1.1.0"
  tags: ["merge", "fields", "parser"]
---

# 合并字段技能

## 何时使用
- 用户说"合并字段"、"字段合并"、"把XX和XX合并成XX"、"将XX和XX合并为XX"时
- 用户提供了：源字段列表（≥2 个）、目标字段名、分隔符（可为空字符串）

## 前置条件
- 会话中存在可调整的解析规则（session.decoded_config 或 session.mapped_sub_rules）
- 所有源字段在每个 entity 的 normalize 中都存在

## 调用链路（ADR-0008 类型化接线）

```
用户指令 → PlannerAgent 生成 merge_fields 类型化步骤
  （source_fields≥2 / target_field / sep / config_ref）
→ FieldSkillAdapter（application/adapters/field_skill.py）
→ scripts/merge_fields.py 的 merge_fields() 纯函数（单一事实源）
→ 结果写回 session，产出 field_adjusted_config 下载产物
```

## 数据操作（scripts/merge_fields.py）

对每个 entity 执行：

1. **验证源字段存在**：任一源字段缺失即返回 `field_not_found` 并列出可用字段
2. **检查目标字段冲突**：目标字段名已存在返回 `field_conflict`
3. **添加 merger filter**（filter 为 null 的入口规则先初始化为空数组）：
   ```json
   {"name": "merger", "field": "<target_field>", "sep": "<sep>", "id": "", "fields": ["<source1>", "<source2>"]}
   ```
4. **添加 normalize 条目**：result 为各源字段 `result[0]` 用 sep 拼接的**预览值**

操作应用到每一个 entity；无 normalize 的 entity 被跳过且计数如实报告。

## 约束与边界
- normalize 的 `result` 只是预览值：源字段为 `%{index}` 引用型时预览为 `%{a}%{b}` 形式的占位拼接，实际拼接由运行时 merger filter 在值替换后执行
- 源字段数量少于 2 个返回 `insufficient_source_fields`
- 已存在相同目标字段的 merger 时更新（不重复追加）
- **子规则寻址（#126）**：`target_names` 按 entity name 精确过滤（None=全部），名单外原样透传

## 完整示例

用户指令："把字段 a 和字段 b 合并成字段 d，分隔符 -"

filter 新增：
```json
{"name": "merger", "field": "d", "sep": "-", "id": "", "fields": ["a", "b"]}
```
normalize 新增（a=1、b=2 时）：
```json
{"index": "d", "result": ["1-2"], ...}
```
