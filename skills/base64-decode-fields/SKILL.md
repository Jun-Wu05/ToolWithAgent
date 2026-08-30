---
name: base64-decode-fields
description: base64 解码字段技能 - 对解析规则（Base64 配置或映射生成的子规则）中指定字段启用运行时 base64 解码。当用户说"base64 解码、解码字段、解码 req_header/req_body"并指明已有字段名时使用；解码原地覆盖字段值，不新增字段。
license: MIT
metadata:
  version: "1.0.0"
  tags: ["base64", "decode", "parser"]
---

# base64 解码字段技能

## 何时使用
- 用户说"base64 解码 req_header"、"解码字段 X / Y"时
- 用户上传的规则中有 base64 编码的字段（如 HTTP 请求头/响应体），需要在解析时还原明文

## 前置条件
- 会话中存在可调整的解析规则（session.decoded_config 或 session.mapped_sub_rules）
- 要解码的字段名存在于配置的 normalize（被解码的是**已有字段**）

## 调用链路（ADR-0008 类型化接线）

```
用户指令 → PlannerAgent 生成 decode_fields 类型化步骤（fields / config_ref）
→ FieldSkillAdapter（application/adapters/field_skill.py 注册表）
→ scripts/decode_fields.py 的 decode_fields() 纯函数（单一事实源）
→ 结果写回 session，产出 field_adjusted_config 下载产物
```

## 数据操作（scripts/decode_fields.py）

对每个 entity：在（或新建的）解码 addFields 过滤器中写入

```json
{
  "fields": {
    "req_header": "<%@com.hansight.dataviewer.utils.Base64@Base64Decode(req_header)%>",
    "req_body": "<%@com.hansight.dataviewer.utils.Base64@Base64Decode(req_body)%>"
  },
  "name": "addFields",
  "id": ""
}
```

要点：
- **原地覆盖**：key = 原字段名，值 = 固定 OGNL 解码语句，运行时由解析器替换字段值
- **不双写 normalize**（与添加字段的双写语义不同）
- 重复调用幂等：合并进已有解码过滤器，不重复追加

## 约束与边界
- 字段不存在时返回 `field_not_found` 并列出可用字段
- 操作应用到每一个 entity；无 normalize 的 entity 跳过且计数如实
- **子规则寻址（#126）**：`target_names` 按 entity name 精确过滤（None=全部），名单外原样透传

## 完整示例

用户指令："解码 req_header 和 req_body"

filter 追加（在 additional_fields_filter 之后）：
```json
{"fields": {"req_header": "<%@com.hansight.dataviewer.utils.Base64@Base64Decode(req_header)%>", "req_body": "<%@com.hansight.dataviewer.utils.Base64@Base64Decode(req_body)%>"}, "name": "addFields", "id": ""}
```
