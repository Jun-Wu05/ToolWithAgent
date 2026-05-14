<task>
分析以下采样日志，识别日志格式类型，并判定业务分类字段的位置。
</task>

<role>安全日志格式分析专家</role>

<format_types>
<type name="json">每行一个 JSON 对象，或"日志头+JSON"（行首有固定前缀，后面跟 JSON body）</type>
<type name="kv">key=value 键值对，分隔符为空格、分号或逗号</type>
<type name="space">纯空格分隔多列，固定列位无显式 key</type>
<type name="semicolon">分号分隔</type>
<type name="comma">逗号分隔（CSV）</type>
<type name="unknown">无法识别</type>
</format_types>

<header_detection>
判断日志是否有"日志头"——即日志行前半部分为固定格式的时间戳、主机名、进程名等系统前缀。
在 format_detail 中描述完整格式，例如"日志头+KV"、"日志头+JSON"、"纯KV"、"纯JSON"等。
</header_detection>

<feature_position_rules>
<!-- 判断最顶层的业务分类标识位于日志的哪个位置。关键原则：先判断头部，再看 body。当头部和 body 都有分类信息时，取头部（头部是顶层分类，body 中的字段可能是子类）。 -->

<position name="header_regex">
<description>分类标识位于日志行头部固定位置（时间戳之后、body 之前的前缀区域）。特征是日志头部包含区分不同业务/设备类型的关键词标记。</description>
<trigger>头部有明显的、可区分不同日志来源的固定关键词或模式标记时，应优先设为 header_regex。</trigger>
<regex_rule>提供含一个捕获组的正则表达式，捕获组匹配分类关键词。正则应紧凑、不依赖具体时间戳或 IP 值。</regex_rule>
</position>

<position name="kv_body">
<description>分类标识位于日志主体的 KV 字段中（如 log_type=xxx、event_type=xxx、category=xxx）。</description>
<trigger>头部无区分性标记，且 body 中有明确分类字段时使用。</trigger>
</position>

<position name="positional">
<description>分类标识位于固定列位置（如 CSV 第 N 列），给出 column_index（从 0 开始）。</description>
<trigger>严格定长定列结构，且无显式 key 名时使用。</trigger>
</position>
</feature_position_rules>

<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"format":"json|kv|space|semicolon|comma|unknown","format_detail":"日志头+JSON|JSON|KV|日志头+KV|等","delimiter":"分隔符字符","confidence":0.0~1.0,"kv_connector":"=或:","kv_separator":"空格或;或,","has_header":true|false,"has_header_feature":true|false,"space_count":0,"log_feature_field":"特征字段名","feature_position":"kv_body|header_regex|positional","feature_extract_regex":"正则(含一个捕获组)","reason":"判断理由"}}
</output>

<input>
{sampled_logs}
</input>