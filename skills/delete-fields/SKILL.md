---
name: delete-fields
description: 删除字段技能 - 从解析规则（Base64 配置或映射生成的子规则）中移除一个或多个字段。当用户说"删除字段、移除字段、去掉字段、删掉字段、清除字段、delete field、remove field"并指明字段名时使用；注意"取消/删除某字段的映射"是取消映射操作，不属于本技能。
license: MIT
metadata:
  version: "1.1.0"
  tags: ["delete", "fields", "parser"]
---

# 删除字段技能

## 何时使用
- 用户说"删除字段"、"移除字段"、"去掉字段"、"删掉字段"并指明字段名时
- 用户要求修改【事件名称】时的第一步（事件名称与事件级别需一起删除再重新添加）

## 消歧边界
- "删除字段 X"（移除整个字段及其 normalize 条目）→ 本技能
- "取消/删除 X 的映射"、"清空 X 的值映射"（只清 mappings，字段保留）→ remove_mapping 操作，不是本技能

## 前置条件
- 会话中存在可调整的解析规则（session.decoded_config 或 session.mapped_sub_rules）
- 用户指定了要删除的字段名列表

## 调用链路（ADR-0008 类型化接线）

```
用户指令 → PlannerAgent 生成 delete_fields 类型化步骤（fields / config_ref）
→ FieldSkillAdapter（application/adapters/field_skill.py）
→ scripts/delete_fields.py 的 delete_field() 纯函数（单一事实源）
→ 结果写回 session，产出 field_adjusted_config 下载产物
```

## 数据操作（scripts/delete_fields.py）

对每个 entity 执行：

1. **验证保留字段**：要删除字段命中保留字段集合时整体拒绝
2. **添加 removeFields filter**：已有 removeFields 则合并字段名，否则在 parser.filter 追加（filter 为 null 的入口规则先初始化为空数组）：
   ```json
   {"name": "removeFields", "id": "", "fields": ["<field1>", "<field2>"]}
   ```
3. **移除 normalize 条目**：从 normalize 数组中移除 index 匹配的条目

操作应用到每一个 entity；无 normalize 的 entity 被跳过且计数如实报告；不存在的字段在结果消息中列明。

## 系统保留字段（不可删除）

| 字段 | 原因 |
|---|---|
| `original_log` | 原始日志载体，字段引用与回溯依赖 |
| `rule_name_list` | 规则名列表系统字段 |
| `日志类型` | 子规则分流核心字段，删除破坏规则结构 |

命中保留字段返回 `reserved_field_rejected`。【事件名称】【事件级别】可删（用于重新标注流程）。

**子规则寻址（#126）**：`target_names` 按 entity name 精确过滤（None=全部）；适配器另有悬空引用守卫——被删字段被 merger 源字段或 `%{字段}` 占位引用时返回 `field_reference_conflict`，需先解除引用。

## 完整示例

用户指令："删除字段 a 和 b"（config_ref=session.mapped_sub_rules）

filter 新增：
```json
{"name": "removeFields", "id": "", "fields": ["a", "b"]}
```
normalize 中 index 为 a、b 的条目被移除，其余条目（含 original_log、日志类型）保持不变。
