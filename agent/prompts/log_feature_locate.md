<task>
判断"日志头+JSON"格式日志的分类特征值位于日志头还是JSON body中。

你将收到：
1. header_analysis: 日志头脱敏聚合统计（脱敏后的模式及各自出现次数）
2. body_analysis: JSON body 中候选字段及其唯一值数量和样本值
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
<rule index="4">判断优先级：
  a) body 和 header 都有有效分类特征 → 选择语义更匹配"日志类型"的那个
  b) 仅 body 有有效候选 → body
  c) 仅 header 有有效候选 → header
  d) 都没有 → unknown</rule>
<rule index="5">feature_field 仅在 feature_location="body" 时填写具体字段名，header 时为空字符串</rule>
</rules>

<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"feature_location":"body|header|unknown","feature_field":"字段名（header时为空字符串）","header_distinct_count":N,"body_best_candidate":"最佳body字段名 (N种唯一值)","reason":"判断依据的简明说明"}}
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