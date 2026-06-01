<task>
从脱敏后的日志头聚合结果中，提取业务分类特征字段。日志类型值位于日志头中（JSON body 之外）。
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

<rule index="4">feature_identifier 固定为 (\{{[\S\s]*\}})，用于匹配 JSON body，无需自行生成</rule>

<rule index="5">每个 classification_detail 中的 matched_regex 为该特征值的专属匹配字符串（如 weak_passwd），用于从原始日志中匹配样例</rule>

<rule index="6">feature_count 必须严格等于 classification_details 数组的长度</rule>
</rules>

<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"status":"SUCCESS|FAIL","categorical_features":"在日志头中","Diversion_method":"特征字段的中文业务名称（如 告警类型、事件类型）","log_format":"日志头+JSON","feature_identifier":"(\{{[\S\s]*\}})","feature_count":N,"classification_details":[{{"logtype":"特征值","matched_regex":"该特征值的专属匹配字符串","meaning":"该特征值的业务含义","sample":"AAA"}}],"fail_reason":"仅在 FAIL 时填写"}}
</output>