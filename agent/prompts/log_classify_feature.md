<task>
分析日志样本及 JSON 内部字段的聚合统计信息，为每种分类值生成业务含义描述。
特征提取的正则匹配由上游确定性代码完成，本任务仅负责语义分类。
</task>

<role>安全日志分析专家</role>

<context>
<format_info>
<format_type>{format_type}</format_type>
<format_detail>{format_detail}</format_detail>
<feature_field>{feature_field}</feature_field>
</format_info>

<aggregation_statistics>
{aggregation_text}
</aggregation_statistics>

<raw_samples count="5">
{sampled_logs}
</raw_samples>
</context>

<requirements>
<requirement index="1">对 aggregation_statistics 中出现的每种业务分类值，逐条生成 classification_details；不得遗漏任何分类值，也**不得新增 aggregation_statistics 中未出现的值**</requirement>
<rule>分类的 logtype 必须严格等于 aggregation_statistics 中的值，禁止使用 raw_samples 中出现的其他字段值（如 username、IP、geoCity 等）替代 {feature_field} 的分类值</rule>
<rule>如果 aggregation_statistics 中仅有 1 个唯一值，classification_details 数组必须也只有 1 个元素</rule>

<requirement index="2">为每个分类值补充简短的业务含义描述（meaning 字段），说明该日志类型代表什么业务场景</requirement>
</requirements>

<output>
严格输出 JSON 格式，必须符合以下 Schema：

```json
{{
  "type": "object",
  "properties": {{
    "status": {{"type": "string", "enum": ["SUCCESS", "FAILED", "PARTIAL"]}},
    "categorical_features": {{"type": "string"}},
    "Diversion_method": {{"type": "string"}},
    "log_format": {{"type": "string"}},
    "feature_field": {{"type": "string"}},
    "feature_count": {{"type": "number"}},
    "classification_details": {{
      "type": "array",
      "items": {{
        "type": "object",
        "properties": {{
          "logtype": {{"type": "string"}},
          "meaning": {{"type": "string"}}
        }},
        "required": ["logtype", "meaning"]
      }}
    }}
  }},
  "required": ["status", "categorical_features", "Diversion_method", "log_format", "feature_field", "feature_count", "classification_details"]
}}
```

**输出要求**：
1. 确保输出**完整的 JSON**（包含闭合的 `}}` 和 `]`）
2. 所有字段名使用**双引号**
3. **不要**使用 markdown 围栏（```json ... ```）
4. **不要**添加任何额外文字或注释
5. **不要**截断任何字段，确保 JSON 结构完整
6. `feature_count` 必须严格等于 `classification_details` 数组的长度

示例输出：
{{"status":"SUCCESS","categorical_features":"告警类型","Diversion_method":"告警类型","log_format":"JSON","feature_field":"categoryName","feature_count":4,"classification_details":[{{"logtype":"WEAK_PASSWD","meaning":"弱密码告警"}},{{"logtype":"MALWARE","meaning":"恶意软件告警"}},{{"logtype":"PHISHING","meaning":"钓鱼网站告警"}},{{"logtype":"DDOS","meaning":"DDoS攻击告警"}}]}}
</output>
