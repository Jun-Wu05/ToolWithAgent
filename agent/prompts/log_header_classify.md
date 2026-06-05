<task>
从脱敏后的日志头聚合结果中，提取业务分类特征字段。日志类型值位于日志头中（body 内容之外）。
</task>

<role>资深网络安全运营专家</role>

<context>
<aggregated_headers>
{aggregated_headers}
</aggregated_headers>

<raw_samples count="{sample_count}">
{sampled_logs}
</raw_samples>
</context>

<rules>
<rule index="1">特征字段必须具备业务定性能力，仅限于：事件类型、日志类别、功能模块、威胁/行为标识类字段</rule>

<rule index="2">黑名单（严禁作为特征字段）：
- 时间类：时间、ISO格式时间、Syslog格式时间
- 网络类：IP地址（IPv4/IPv6）、端口号、MAC地址、URL、域名
- 标识类：用户名、归属地、唯一ID（UUID/SN/GUID）、长字母数字混合ID、手机号
- 元信息类：日志级别（如 <31>, <182> 等）、脱敏标记"1"
- 数值类：纯数字、空值
</rule>

<rule index="3">基数校验：有效特征值的数量必须为 2~20 种。少于2种或多于20种均为分类失败</rule>

<rule index="4">feature_identifier 的设置：
- 如果 body 是 JSON 格式：固定为 (\{{[\S\s]*\}})，无需自行生成
- 如果 body 是 KV（键值对）格式：保持为空字符串 ""，无需自行生成
</rule>

<rule index="5">每个 classification_detail 中的 matched_regex 为该特征值的专属匹配字符串（如 weak_passwd），用于从原始日志中匹配样例</rule>

<rule index="6">feature_count 必须严格等于 classification_details 数组的长度</rule>

<rule index="7">analysis 字段用于描述日志 body 的结构特征：
- tab：键值连接符（如 = 或 :），无法判断时输出"判断失败"
- delimit：键值对之间的分隔符（如 space、comma、pipe），无法判断时输出"判断失败"
</rule>
</rules>

<output>
严格输出 JSON 格式，必须符合以下 Schema：

```json
{{
  "type": "object",
  "properties": {{
    "status": {{"type": "string", "enum": ["SUCCESS", "FAILED"]}},
    "categorical_features": {{"type": "string", "const": "在日志头中"}},
    "Diversion_method": {{"type": "string"}},
    "log_format": {{"type": "string"}},
    "feature_identifier": {{"type": "string"}},
    "feature_count": {{"type": "number"}},
    "classification_details": {{
      "type": "array",
      "items": {{
        "type": "object",
        "properties": {{
          "logtype": {{"type": "string"}},
          "matched_regex": {{"type": "string"}},
          "meaning": {{"type": "string"}},
          "sample": {{"type": "string"}}
        }},
        "required": ["logtype", "matched_regex", "meaning"]
      }}
    }},
    "analysis": {{
      "type": "object",
      "properties": {{
        "delimit": {{"type": "string"}},
        "tab": {{"type": "string"}}
      }}
    }},
    "fail_reason": {{"type": "string"}}
  }},
  "required": ["status", "categorical_features", "Diversion_method", "log_format", "feature_identifier", "feature_count", "classification_details", "analysis"]
}}
```

**输出要求**：
1. 确保输出**完整的 JSON**（包含闭合的 `}}` 和 `]`）
2. 所有字段名使用**双引号**
3. **不要**使用 markdown 围栏（```json ... ```）
4. **不要**添加任何额外文字或注释
5. **不要**截断任何字段，确保 JSON 结构完整

示例输出：
{{"status":"SUCCESS","categorical_features":"在日志头中","Diversion_method":"告警类型","log_format":"日志头+KV","feature_identifier":"","feature_count":3,"classification_details":[{{"logtype":"AUDIT","matched_regex":"AUDIT","meaning":"审计日志","sample":""}}],"analysis":{{"delimit":":","tab":" "}}}}
</output>
