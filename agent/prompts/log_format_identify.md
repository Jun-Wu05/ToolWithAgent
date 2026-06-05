<task>
分析以下采样日志，识别日志格式类型和基本结构。
本任务只负责格式识别，不需要判断分类字段（分类字段由后续步骤自动发现）。
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

<important_rules>
- 对于"日志头 + JSON body"的格式，必须识别为 format="json"，NOT "syslog" NOT "mixed"
- 所有可解析的 JSON body 日志（包括有 syslog 前缀的）都属于 json 类型
- 如果识别到 feature_field，请务必填写具体字段名，不要留空
  - JSON 格式：填写 JSON 字段名（如 "event.action"、"type"、"tag_name"）
  - KV 格式：填写 key 名（如 "type"、"log_type"、"category"、"event"）
- 实在找不到分类字段时 feature_field 才留空
</important_rules>

<header_detection>
判断日志是否有"日志头"——即日志行前半部分为固定格式的时间戳、主机名、进程名等系统前缀。
在 format_detail 中描述完整格式，例如"日志头+KV"、"日志头+JSON"、"纯KV"、"纯JSON"等。
如果存在日志头，还需识别日志头与 body 之间的分界标记（header_end_marker），即紧接在系统前缀之后、body 开始之前的一个固定字符串。
例如 syslog 格式 `<14>1 2026-04-14T05:57:55Z host app 1 type - body_content` 中，` - ` 就是分界标记。
如果无日志头（纯 JSON / 纯 KV），header_end_marker 为空字符串。
</header_detection>


<output>
严格输出一行 JSON，不要额外文字，不要 markdown 代码块包裹：
{{"format":"json|kv|space|semicolon|comma|unknown","format_detail":"日志头+JSON|JSON|KV|日志头+KV|等","delimiter":"分隔符字符","confidence":0.0~1.0,"kv_connector":"=或:","kv_separator":"分隔符代码格式（空格填space，分号填semicolon，英文逗号填comma，中文逗号填chinese_comma，管道填pipe，tab填tab）","has_header":true|false,"header_end_marker":"日志头与body的分界标记字符串（仅RFC5424 syslog格式有值如' - '，BSD syslog和纯格式为空字符串）","has_header_feature":true|false,"feature_field":"日志分类特征字段名（JSON格式填字段名如event_type，KV格式填key名如type、log_type；找不到时为空字符串）","feature_location":"body|header|unknown（特征值在header中则填header，在body内则填body，无法判断填unknown）","reason":"判断理由"}}

注意：
- format_detail 必须准确描述结构，如"日志头+KV"表示 syslog 头部后跟 KV body
- has_header 为 true 时，header_end_marker 仅对 RFC5424 格式有值（如 ` - `），BSD syslog 格式（如 `<221>May 21 14:09:05 ips IPS: body`）的 header_end_marker 为空字符串
- has_header_feature 判断规则：当 has_header=true 时，检查日志头中是否包含可作为日志类型分类的特征关键词（如攻击类型名、功能模块名、日志类别等），不包含 IP/时间/UUID/数字/日志级别等非分类信息。如果 has_header=false，则 has_header_feature 必须为 false
- feature_field: 
  - JSON 格式：识别 JSON body 中哪个字段是日志分类的主要特征字段（如 tag_、event_type、msg_type、type、action 等）
  - KV 格式：识别 KV body 中哪个 key 是日志分类的主要特征字段（如 type、log_type、category、event 等）
  - 如果 has_header_feature=true 且特征在头部，则 feature_field 可留空
- feature_location: 分类特征所在位置。"body"=分类字段在body内部值中，"header"=分类特征在日志头部分（{{之前的文本}}），"unknown"=无法判断
</output>

<input>
{sampled_logs}
</input>