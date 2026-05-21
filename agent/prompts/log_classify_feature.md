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
提取业务特征的唯一标识符（feature_identifier），即一个**双捕获组正则表达式**，两个捕获组分别提取"日志主体"和"特征值"。
必须输出 feature_body_group 和 feature_value_group 两个字段，声明哪个捕获组是日志主体、哪个是特征值：

<group index="body">日志主体 = 去掉日志系统前缀（时间戳、主机名、PID 等）后的内容（若为纯 JSON 则为完整 JSON 对象，若为 KV 则为 key=value 主体。特征位于头部 keyword 时，keyword 和 body 可以分布在任意组，取决于正则写法）</group>
<group index="value">{feature_field} 对应的字段值（必须用通配符如 ([^"]+) 或 (\S+) 提取所有可能的字段值，禁止写死具体的值如 "grantblock"、"API SERVER" 等）</group>

<critical>feature_identifier 正则中必须包含外层捕获组，缺少外层捕获组的单捕获组正则会直接导致匹配失败。例如：日志 `{"topic":"waf_access","msg":"..."}` 的正则必须为 `(\{{.*"topic":"([^"]+)".*\}})` 而非 `"topic":"([^"]+)"`。</critical>

<rule>正则只需做到：能在日志行中定位到特征字段，正确提取 2 个捕获组。</rule>
<rule>正则不需精确匹配日志系统前缀（时间戳、主机名、PID 等），可以跳过或使用 .*? 通配。</rule>
<rule>正则应对所有同类日志行通用，不应依赖具体 IP、时间戳、数字值等可变内容。</rule>
<rule>禁止正则中出现具体字段名/关键字（如 "protocol"、"src_ip"、"tag_"、"logType"），始终使用通配符 (\S+ 或 [\S\s]* 或 ([^"]+)) 匹配。</rule>

<examples>
<example>
<log>{{"ssl_protocol":"TLSv1.3","state_id":1792943,"tag_":"waf_access2","timestamp":"2026-05-12T17:17:35+08:00","topic_":"waf_access2_2026-05-12","upstream_addr":"218.69.98.180:8443"}}</log>
<regex>(\{{.*"tag_":"([^"]+)".*\}})</regex>
<note>特征位于 JSON 内部字段：Group1(外括号)=完整JSON主体=body, Group2(内括号)=tag_特征值=value。feature_body_group=1, feature_value_group=2</note>
</example>
<example>
<log><14>MAY 21 11:30:47 localhost.localdomain dns_result: {"protocol":"dns","sport":3950,"dport":53,"sip":"::ffff:192.168.20.61","qname":"www.baidu.com"}</log>
<regex>(\S+):\s+(\{[\S\s]*\})</regex>
<note>特征位于头部 keyword（header+JSON 结构）：Group1=keyword(dns_result)=value, Group2=完整JSON主体=body。feature_body_group=2, feature_value_group=1。正则不依赖 JSON 内部字段名</note>
</example>
<example>
<log><221>May 21 14:09:05 ips IPS: src_ip="106.75.167.104" dst_ip="124.117.209.141" protocol="DNS" alarm_name="DNS_BIND版本探测" action=0</log>
<regex>(\S+):\s+([\S\s]*)</regex>
<note>特征位于头部 keyword（header+KV 结构）：Group1=keyword(IPS)=value, Group2=KV主体=body。feature_body_group=2, feature_value_group=1。正则不依赖 KV 内部字段名</note>
</example>
</examples>
</requirement>

<requirement index="3">对 aggregation_statistics 中出现的每种业务分类值，逐条生成 classification_details；不得遗漏任何分类值，也**不得新增 aggregation_statistics 中未出现的值**</requirement>
<rule>分类的 logtype 必须严格等于 aggregation_statistics 中的值，禁止使用 raw_samples 中出现的其他字段值（如 username、IP、geoCity 等）替代 {feature_field} 的分类值</rule>
<rule>如果 aggregation_statistics 中仅有 1 个唯一值，classification_details 数组必须也只有 1 个元素</rule>
</requirements>

<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"status":"SUCCESS","categorical_features":"分类特征名称","Diversion_method":"日志分流方法","log_format":"固定枚举值：JSON / KV / CEF / SEPARATOR / UNKNOWN（必须取其一，不能自由填写）","feature_field":"{feature_field}","feature_identifier":"双捕获组正则（禁止正则中出现具体字段名/关键字，始终使用通配符匹配）","feature_body_group":1|2,"feature_value_group":1|2,"feature_count":N,"classification_details":[{{"logtype":"值","sample":"完整原始日志行"}}]}}
</output>