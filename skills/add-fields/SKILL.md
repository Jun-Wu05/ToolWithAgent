---
name: add-fields
description: 添加字段技能 - 在解析规则（Base64 配置或映射生成的子规则）的每个 entity 上新增一个字段。当用户说"添加字段、新增字段、增加字段、插入字段、加入字段、add field"并给出字段名与值来源（固定值或 %{index} 引用）时使用。
license: MIT
metadata:
  version: "1.1.0"
  tags: ["add", "fields", "parser"]
---

# 添加字段技能

## 何时使用
- 用户说"添加字段"、"新增字段"、"增加字段"、"插入字段"时
- 用户指定了新字段的名称和值的来源：固定值（如 "1.1.1.1"）或引用已有字段（如 `%{reqheader}`）
- 用户要求修改某子规则的【事件名称】时（先删除事件名称与事件级别，再用本技能添加新值）

## 前置条件
- 会话中存在可调整的解析规则：用户上传的 Base64 配置（session.decoded_config）或标准字段映射生成的子规则（session.mapped_sub_rules），两者并存时优先后者
- 用户指定了新字段的名称
- 用户指定了新字段的值来源：固定值或 `%{index}` 引用

## 调用链路（ADR-0008 类型化接线）

```
用户指令 → PlannerAgent 生成 add_fields 类型化步骤
  （field_name / field_value / value_type=fixed|reference / config_ref）
→ FieldSkillAdapter（web/adapters/skill_ops.py，按声明式注册表分发）
→ 本目录 scripts/add_fields.py 的 add_field() 纯函数（单一事实源）
→ 结果写回 session 原配置来源，产出 field_adjusted_config 下载产物
```

适配器不重复脚本逻辑；修改本技能的数据操作行为只需改 scripts/add_fields.py。

## 数据操作（scripts/add_fields.py）

对每个 entity 执行：

1. **验证字段不存在**：检查 normalize 中是否已存在该字段名（index）
2. **处理值引用**：`%{index}` 格式保留原字符串，运行时由解析器替换
3. **添加 addFields filter**：在 parser.filter 末尾追加（filter 为 null 的入口规则会先初始化为空数组）：
   ```json
   {"name": "addFields", "id": "", "fields": {"<field_name>": "<field_value>"}}
   ```
4. **添加 normalize 条目**：在 normalize 数组末尾新增：
   ```json
   {"mappings": [], "field": null, "sim": null, "result": ["<field_value>"], "info": null, "entity": null, "required": false, "core": null, "value": null, "index": "<field_name>"}
   ```

操作应用到每一个 entity（入口规则与子规则混合数据同样处理）；无 normalize 的 entity 被跳过且计数如实报告。

## 【事件名称】绑定规则

手动添加【事件名称】时适配器执行确定性守卫：

- 值必须是 21 个合法分类名之一——威胁组（事件级别=提醒）：网络攻击、病毒检测、邮件告警、终端告警、蜜罐告警、其他告警；非威胁组（事件级别=信息）：登录事件、审计事件、会话操作、进程操作、用户操作、资源监控、邮件操作、dns查询、dns响应、数据库操作、ssh连接、认证事件、telnet连接、网络连接、web访问
- 不支持引用型值；非法值返回 `invalid_event_name`
- 添加【事件名称】后自动联动写入绑定的【事件级别】，无需（也不应）单独添加事件级别
- 【事件级别】已存在时返回 `event_level_conflict`，需先删除两个字段再重新添加

## 约束与边界
- 字段名已存在时：返回 `field_conflict`，建议更换名称或先删除原有字段
- 值为空时：result 为空数组 `[]`，filter 中 value 为空字符串 `""`
- 引用格式 `%{index}` 中的 index 指向已有字段的 normalize index
- 无可用配置时返回 `config_required`

## 完整示例

用户指令："添加字段 主机ip，值为 1.1.1.1"（config_ref=session.decoded_config）

normalize 新增：
```json
{"index": "主机ip", "result": ["1.1.1.1"], ...}
```
filter 新增：
```json
{"name": "addFields", "id": "", "fields": {"主机ip": "1.1.1.1"}}
```

用户指令："把事件名称改成终端告警"（Planner 分解为 delete_fields + add_fields 两步）：
```json
{"fields": {"事件名称": "终端告警", "事件级别": "提醒"}, "name": "addFields", "id": ""}
```
