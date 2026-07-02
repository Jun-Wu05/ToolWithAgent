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

<rule index="2">黑名单（严禁作为特征字段）：时间、IP/端口/MAC/URL/域名、用户名/归属地/UUID/手机号、日志级别(如<31>)、脱敏标记"1"、纯数字、空值</rule>

<rule index="3">基数校验：有效特征值的数量必须为 2~20 种。少于2种或多于20种均为分类失败</rule>

<rule index="4">feature_identifier 设置：JSON body 固定为 `(\{{[\S\s]*\}})`，KV body 保持为空字符串 `""`，均无需自行生成</rule>

<rule index="5">matched_regex 为该特征值的专属匹配字符串（如 weak_passwd），用于从原始日志中匹配样例；feature_count 必须严格等于 classification_details 数组长度</rule>

<rule index="6">analysis 字段：delimit = 键值对之间的分隔符（space/comma/pipe/||等），tab = 键值连接符（= 或 :），无法判断时输出"判断失败"</rule>

<rule index="7">日志类型标识（logtype）的提取规则：

1. **优先从日志头提取类型标识**：位于 syslog 头之后、KV body 之前，具有业务语义的设备内置类型

2. **必须提取完整类型路径，不得截取或简化**：
   - 当类型标识含 `/`、`:` 等层级分隔符时，必须保留**完整路径**作为 logtype
   - ❌ 错误（截取首段）：`FILTER`、`UFLT`
   - ✅ 正确（完整路径）：`FILTER/6/FILTER_ZONE_IPV4_EXECUTION`、`UFLT/6/UFLT_MATCH_IPV6_LOG`
   - matched_regex 也必须能匹配完整路径（如 `FILTER/6/FILTER_ZONE_IPV4_EXECUTION`）

3. **同前缀不同后缀视为不同类型**：如 `UFLT/6/UFLT_MATCH_IPV4_LOG` 与 `UFLT/6/UFLT_MATCH_IPV6_LOG` 是两个独立的 logtype

4. 如果日志头没有类型标识或仅有固定前缀（唯一值=1），则检查 body 中是否有分类字段（字段名含 type/category/class 等）

5. Diversion_method：logtype 来自日志头设为"在日志头中"，来自 body 设为字段名（如"Content字段"）
</rule>
</rules>

<output>
严格输出 JSON 格式（不要 markdown 围栏，不要额外文字），必须符合以下 Schema：

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

示例输出（注意 logtype 为完整路径）：
{{"status":"SUCCESS","categorical_features":"在日志头中","Diversion_method":"在日志头中","log_format":"日志头+KV","feature_identifier":"","feature_count":2,"classification_details":[{{"logtype":"FILTER/6/FILTER_ZONE_IPV4_EXECUTION","matched_regex":"FILTER/6/FILTER_ZONE_IPV4_EXECUTION","meaning":"IPv4区域过滤执行日志","sample":""}},{{"logtype":"IPS/4/IPS_IPV4_INTERZONE","matched_regex":"IPS/4/IPS_IPV4_INTERZONE","meaning":"IPv4区域间入侵防护日志","sample":""}}],"analysis":{{"delimit":";","tab":"="}}}}
</output>