<task>
判断"日志头+JSON"或"日志头+KV"格式日志的分类特征值位于日志头还是body中。

你将收到：
1. header_analysis: 日志头脱敏聚合统计（脱敏后的模式及各自出现次数）
2. body_analysis: JSON/KV body 中候选字段及其唯一值数量和样本值
3. sample_logs: 原始采样日志

请根据以下规则判断特征位置：
</task>

<role>安全日志分析专家</role>

<rules>
<rule index="1">分类特征 = 能够区分不同日志类型的字段值（如事件类型、功能模块、攻击类型）</rule>
<rule index="2">有效分类特征必须满足：唯一值数量 2~20 个（过少无区分度，过多属于ID类字段）</rule>
<rule index="3">黑名单（不能作为分类特征）：
- 时间类：时间戳、日期、ISO格式时间
- 网络类：IP地址、端口号、MAC地址、URL
- 标识类：UUID、流水号、长随机字符串
- 元信息：日志级别(priority)、主机名(hostname)
- 数值类：纯数字计数器</rule>
<rule index="4">KV 格式特殊判断：
  - 优先检查 body 中的明确分类字段：logtype、event_type、log_type、event_name 等
  - 如果 body 中存在这些字段，**必须**选择 `feature_location="body"` 并返回字段名
  - 不得因为 header 中有类似模式而选择 header</rule>
<rule index="5">判断优先级：
  a) KV 格式且 body 有明确分类字段（logtype、event_type 等）→ body（强制）
  b) body 和 header 都有有效分类特征 → 选择语义更匹配"日志类型"的那个
  c) 仅 body 有有效候选 → body
  d) 仅 header 有有效候选 → header
  e) 都没有 → unknown</rule>
<rule index="6">feature_field 必须：
  - feature_location="body" → 返回实际字段名（如 logtype、event_type）
  - feature_location="header" → 返回 __header__
  - feature_location="unknown" → 返回空字符串 ""</rule>
<rule index="7">禁止：
  - feature_location="body" 时 feature_field 为空
  - feature_location="header" 时 feature_field 不为 __header__
  - body 有候选字段但选择 header</rule>
</rules>

<output>
严格输出 JSON 格式，必须符合以下 Schema：

```json
{{
  "type": "object",
  "properties": {{
    "feature_location": {{"type": "string", "enum": ["body", "header", "unknown"]}},
    "feature_field": {{"type": "string"}},
    "header_distinct_count": {{"type": "number"}},
    "body_best_candidate": {{"type": "string"}},
    "reason": {{"type": "string"}}
  }},
  "required": ["feature_location", "feature_field", "reason"]
}}
```

**输出要求**：
1. 确保输出**完整的 JSON**（包含闭合的 `}}` 和 `]`）
2. 所有字段名使用**双引号**
3. **不要**使用 markdown 围栏（```json ... ```）
4. **不要**添加任何额外文字或注释
5. **不要**截断任何字段，确保 JSON 结构完整
6. `feature_location="body"` 时 `feature_field` 必须填写实际字段名（如 logtype）
7. `feature_location="header"` 时 `feature_field` 必须为 `__header__`
8. `feature_location="unknown"` 时 `feature_field` 为空字符串 `""`

示例输出（body 路径）：
{{"feature_location":"body","feature_field":"logtype","header_distinct_count":38,"body_best_candidate":"logtype","reason":"KV body 中存在 logtype 字段，唯一值在 2~20 范围，是明确的分类特征"}}

示例输出（header 路径）：
{{"feature_location":"header","feature_field":"__header__","header_distinct_count":38,"body_best_candidate":"","reason":"header 中存在 log_type=1/2 等分类特征，body 无明确分类字段"}}
</output>

<context>
<header_analysis>
{header_analysis}
</header_analysis>

<body_analysis>
{body_analysis}
</body_analysis>

<sample_logs count="{sample_count}">
{sampled_logs}
</sample_logs>
</context>