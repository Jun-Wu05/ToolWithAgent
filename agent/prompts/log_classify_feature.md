<task>
分析日志样本及业务分类字段的聚合统计信息，识别各类日志的业务含义、攻击特征、分类和危害等级。
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
<requirement index="1">分析日志结构，给出完整格式描述（如"日志头+JSON"、"纯JSON"、"KV"、"日志头+KV"等）</requirement>

<requirement index="2">
提取业务特征的唯一标识符（feature_identifier），即一个双捕获组正则表达式：
<group index="1">去掉日志头后的日志主体部分（若为纯 JSON 则为完整 JSON，若为 KV 则为 key=value 主体）</group>
<group index="2">{feature_field} 对应的字段值</group>
<rule>Group 1 和 Group 2 的捕获范围必须互不重叠，正则应对所有同类日志行通用，不应依赖具体时间戳或 IP。</rule>
</requirement>

<requirement index="3">对每种业务分类值，分析其意义、匹配正则（matched_regex）、危害等级</requirement>
</requirements>

<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"status":"SUCCESS","categorical_features":"分类特征名称","Diversion_method":"日志分流方法","log_format":"日志头+JSON 或 JSON 或 KV","feature_field":"{feature_field}","feature_identifier":"双捕获组正则","feature_count":N,"classification_details":[{{"value":"值","matched_regex":"匹配正则","meaning":"业务含义","sample":"完整原始日志行"}}],"expert_summary":"综合摘要(100字内)","fail_reason":""}}
</output>