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
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"status":"SUCCESS","categorical_features":"分类特征名称","Diversion_method":"日志分流方法","log_format":"JSON","feature_field":"{feature_field}","feature_count":N,"classification_details":[{{"logtype":"值","meaning":"业务含义描述"}}]}}
</output>
