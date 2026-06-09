<task>
判断"日志头+JSON"或"日志头+KV"格式日志的分类特征值位于日志头还是body中。
输入：header_analysis（日志头脱敏聚合）、body_analysis（候选字段）、sample_logs（原始日志）
输出：JSON格式的特征位置和字段名
</task>

<role>安全日志分析专家</role>

<rules>
<rule index="1" priority="high">日志头类型标识优先判断：
特征：位置固定（syslog头后body前）、语义明确（设备内置类型）、数量有限（1~50）、有分隔符
判断：header_analysis存在符合上述特征的值→header路径，否则考虑body</rule>

<rule index="2">强类型字段（字段名含type/event_type/log_type/category/class）：
唯一值1~50→有效（常数字段、数字值、>20种都有效）
弱类型字段：唯一值2~20→有效，否则无效
唯一值>50→可能是ID类字段，需进一步判断</rule>

<rule index="3">黑名单（不能作为分类特征）：
绝对黑名单：时间戳、IP地址、端口号、MAC地址、UUID、session_id、request_id、主机名
条件黑名单：数值类字段（如count、priority），但字段名含type时除外</rule>

<rule index="4">判断优先级：
a)日志头有类型标识→header
b)body有强类型字段→body
c)两者都有→选择语义更匹配"日志类型"的
d)仅body有→body，仅header有→header
e)都没有→unknown</rule>

<rule index="5">feature_field格式：
body→字段名，header→__header__，unknown→空字符串</rule>

<rule index="6">禁止：body路径时feature_field为空；header路径时feature_field不为__header__</rule>
</rules>

<examples>
<example input="header有38个类型标识，body有event_type1=4个唯一值" output="header:日志头存在类型标识（2~50个唯一值），优先选择header"/>
<example input="header无类型标识，body有type=22个唯一值（数字值）" output="body:type字段名含type，唯一值22（1~50范围），数字值有效"/>
<example input="header无类型标识，body有logtype=1个唯一值（常数字段）" output="body:logtype字段名含type，唯一值1（1~50范围），常数字段有效"/>
<example input="header无类型标识，body有threat_level=1个唯一值" output="unknown:threat_level字段名不含type，唯一值1，无效"/>
</examples>

<output>
严格输出JSON格式：{{"feature_location":"body"|"header"|"unknown","feature_field":"字段名"|"__header__"|"","reason":"判断理由"}}
确保输出完整JSON，双引号，不用markdown围栏，不截断。
</output>

<context>
<header_analysis>{header_analysis}</header_analysis>
<body_analysis>{body_analysis}</body_analysis>
<sample_logs count="{sample_count}">{sampled_logs}</sample_logs>
</context>