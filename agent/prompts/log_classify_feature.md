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
提取业务特征的唯一标识符（feature_identifier），即一个**双捕获组正则表达式**：
<group index="1">去掉日志系统前缀（时间戳、主机名、PID 等）后的日志主体内容（若为纯 JSON 则为完整 JSON 对象，若为 KV 则为 key=value 主体）</group>
<group index="2">{feature_field} 对应的字段值（必须用通配符如 ([^"]+) 或 (\S+) 提取所有可能的字段值，禁止写死具体的值如 "grantblock"、"API SERVER" 等）</group>

<rule>正则只需做到：能在日志行中定位到特征字段，正确提取 Group 1（日志主体）和 Group 2（特征值）。</rule>
<rule>正则不需精确匹配日志系统前缀（时间戳、主机名、PID 等），可以跳过或使用 .*? 通配。</rule>
<rule>正则应对所有同类日志行通用，不应依赖具体 IP、时间戳、数字值等可变内容。</rule>

<examples>
<example>
<log>{{"ssl_protocol":"TLSv1.3","state_id":1792943,"tag_":"waf_access2","timestamp":"2026-05-12T17:17:35+08:00","topic_":"waf_access2_2026-05-12","upstream_addr":"218.69.98.180:8443"}}</log>
<regex>(\{{.*"tag_":"(.*?)".*\}})</regex>
<note>Group1=JSON主体, Group2=tag_值</note>
</example>
<example>
<log><190>Sep 29 2024 16:44:32 changrong-2.49 %%01VBST/6/RCVDTC(l)[51289]:VBST received BPDU with TC, VBST VLAN 28, port name is GE0/0/28.</log>
<regex>(?:%%|)(\S+\/\d+\/\w+)(?:\(\w+\)\[\d+\]|\[\d+\]|\(\w+\)|):(.*)</regex>
<note>Group1=VBST/6/RCVDTC, Group2=日志消息体</note>
</example>
<example>
<log><150>May 14 16:24:17 sfos logs[3003]: 日志类型:API SERVER, [proxy] getAllAppcontrolsMid: getEdrStatus is not 0</log>
<regex>日志类型:([^,]+),\s*(.*)</regex>
<note>Group1=API SERVER, Group2=日志主体</note>
</example>
</examples>
</requirement>

<requirement index="3">对 aggregation_statistics 中出现的每种业务分类值，逐条生成 classification_details；不得遗漏任何分类值，也**不得新增 aggregation_statistics 中未出现的值**</requirement>
<rule>分类的 logtype 必须严格等于 aggregation_statistics 中的值，禁止使用 raw_samples 中出现的其他字段值（如 username、IP、geoCity 等）替代 {feature_field} 的分类值</rule>
<rule>如果 aggregation_statistics 中仅有 1 个唯一值，classification_details 数组必须也只有 1 个元素</rule>
</requirements>

<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"status":"SUCCESS","categorical_features":"分类特征名称","Diversion_method":"日志分流方法","log_format":"固定枚举值：JSON / KV / CEF / SEPARATOR / UNKNOWN（必须取其一，不能自由填写）","feature_field":"{feature_field}","feature_identifier":"双捕获组正则","feature_count":N,"classification_details":[{{"logtype":"值","matched_regex":"匹配正则","meaning":"业务含义","sample":"完整原始日志行"}}],"expert_summary":"综合摘要(100字内)","fail_reason":""}}
</output>