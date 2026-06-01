✅已完成 待处理：1、纯json入口规则的日志类型映射处理，需要在normalize里新增index恒为日志类型的json数组，field恒为log_type，result里置空，其他结构不变。（2026-06-01 实现）
[
    {
        "mappings": [],
        "field": "log_type",
        "sim": true,
        "result": [
        ],
        "info": null,
        "entity": "日志",
        "required": false,
        "core": false,
        "value": "",
        "index": "日志类型"
    }
]

✅已完成 2、syslog+json的入口规则重新生成（2026-06-01 实现）
✅已完成 3、生成解析规则的文件rule_generator.py不拆分（482行规模适中），已重构：提取_fill_rule_common()合并公共逻辑，_resolve_sub_parser_name()重命名，添加🔮扩展点注释

优化部分：
✅已完成 1、syslog+json的日志类型放在子规则添加字段处理（2026-06-01 实现）
  - 子规则 name：`{logtype}_{feature_field}_json_子规则`
  - 子规则 parser.name 恒为 `"json"`
  - syslog+JSON 子规则 filter 追加 `addFields(日志类型=logtype)`
  - syslog+JSON 子规则 normalize 追加 `{index:"日志类型", field:"log_type", result:[logtype]}`
  - 纯 JSON 子规则不需要 normalize 日志类型条目
✅已完成 2、生成规则的函数相同部分合并为_fill_rule_common()（2026-06-01 实现）
✅已完成 3、预留扩展KV/分隔符/等格式 — 在else分支和_resolve_sub_parser_name()添加🔮注释标记（2026-06-01）


1、纯json格式的日志入口规则的生成
name恒为json，
filter里面增加case，
name为conditionMatch的json数组，value值格式固定为original_log like ' '，引号里面的值遍历classification_details的logtype，其余结构不变
name为addFields的json里"fields": {
                "日志类型": "%{payload_index}"
            }，key值恒为日志类型，后面格式%{}固定，里面的值动态取值feature_field
{
    "name": "json",
    "resolverType": "event",
    "unmappingKeep": false,
    "deviceType": "1",
    "filter": [
        {
            "fields": {
                "product": "",
                "event_name": "",
                "event_level": "",
                "log_vendor": ""
            },
            "name": "addFields",
            "id": "additional_fields_filter"
        },
        {
            "cases": [
                {
                    "value": "original_log like 'detect_webshell'",
                    "rule": {
                        "fields": {
                            "1": "1"
                        },
                        "name": "addFields",
                        "id": ""
                    },
                    "name": "case",
                    "id": ""
                },
                {
                    "value": "original_log like 'vul_patch_business_impact'",
                    "rule": {
                        "fields": {
                            "1": "1"
                        },
                        "name": "addFields",
                        "id": ""
                    },
                    "name": "case",
                    "id": ""
                }
            ],
            "default": {
                "name": "none"
            },
            "name": "conditionMatch",
            "id": ""
        },
        {
            "fields": {
                "日志类型": "%{payload_index}"
            },
            "name": "addFields",
            "id": ""
        }
    ],
    "subResolver": 0
}

输出json数据
{
  "status": "SUCCESS",
  "log_format": "JSON",
  "log_format_detail": "纯JSON",
  "feature_field": "payload_index",
  "feature_identifier": "(\\{[\\S\\s]*\\})",
  "feature_count": 32,
  "total_valid_lines": 328,
  "covered_lines": 328,
  "classification_details": [
    {
      "logtype": "detect_webshell",
      "sample": "{\"payload_id\":\"65a968125d7bd44c9a0d84d3\",\"payload_index\":\"detect_webshell\",\"operation\":\"insert\",\"payload\":{\"file_path\":\"/opt/www/joywok/library/stomp-activemq/activemq_mipush.php\",\"sha256\":\"da55311fb385b429d50af5687381b3c01c031cf811b3f003cd973d65a8898581\",\"agent_id\":\"6585462de1452da2\",\"c_time\":1705575893,\"remark\":null,\"type\":\"web后门\",\"file_create_time\":null,\"platform\":\"CentOS Linux release 7.9.2009 (Core)\",\"internal_ip\":\"172.20.4.37\",\"charge_name\":null,\"detail_info\":[{\"detail\":[{\"function_name\":\"userinput\",\"arguments\":[\"\"]}],\"type_desc\":\"该Web后门文件经自研引擎分析，反混淆回归推导运算后，确定为恶意后门文件\",\"type\":\"自研引擎\"}],\"host_location\":null,\"webshell_desc\":\"该Web后门文件经自研引擎分析，反混淆回归推导运算后，确定为恶意后门文件\",\"file_type\":\"php\",\"white_rule_effect\":false,\"group_relate_name\":\"未分组主机\",\"store_time\":1705601128,\"a_time\":1704269592,\"external_ip\":null,\"group\":\"root\",\"severity\":\"高危\",\"host_ip\":\"172.20.4.37\",\"asset_number\":null,\"create_time\":1705601042,\"charge_email\":null,\"com_id\":\"f06b56e4c917477429a8\",\"permission\":\"rwxrwxrwx\",\"hard_id\":\"faef488c-d421-48aa-bb1d-f774bca713f1\",\"ips\":[\"172.20.4.37\"],\"m_time\":1702525022,\"webshell_type\":\"自研引擎\",\"size\":6441,\"group_id\":1,\"host_tag_map\":{},\"domain\":\"localhost\",\"os_type\":\"linux\",\"detail\":\"主机 172.20.4.37 发现Web后门：/opt/www/joywok/library/stomp-activemq/activemq_mipush.php\",\"source_id\":\"65a968125d7bd44c9a0d84d3\",\"user\":\"root\",\"host_name\":\"newcentosimage\",\"status\":\"\",\"hit_rule_count\":1,\"md5\":\"7290163b39153cb3c35658d73fcc258d\"}}",
      "real_samples": "{\"payload_id\":\"65a968125d7bd44c9a0d84d3\",\"payload_index\":\"detect_webshell\",\"operation\":\"insert\",\"payload\":{\"file_path\":\"/opt/www/joywok/library/stomp-activemq/activemq_mipush.php\",\"sha256\":\"da55311fb385b429d50af5687381b3c01c031cf811b3f003cd973d65a8898581\",\"agent_id\":\"6585462de1452da2\",\"c_time\":1705575893,\"remark\":null,\"type\":\"web后门\",\"file_create_time\":null,\"platform\":\"CentOS Linux release 7.9.2009 (Core)\",\"internal_ip\":\"172.20.4.37\",\"charge_name\":null,\"detail_info\":[{\"detail\":[{\"function_name\":\"userinput\",\"arguments\":[\"\"]}],\"type_desc\":\"该Web后门文件经自研引擎分析，反混淆回归推导运算后，确定为恶意后门文件\",\"type\":\"自研引擎\"}],\"host_location\":null,\"webshell_desc\":\"该Web后门文件经自研引擎分析，反混淆回归推导运算后，确定为恶意后门文件\",\"file_type\":\"php\",\"white_rule_effect\":false,\"group_relate_name\":\"未分组主机\",\"store_time\":1705601128,\"a_time\":1704269592,\"external_ip\":null,\"group\":\"root\",\"severity\":\"高危\",\"host_ip\":\"172.20.4.37\",\"asset_number\":null,\"create_time\":1705601042,\"charge_email\":null,\"com_id\":\"f06b56e4c917477429a8\",\"permission\":\"rwxrwxrwx\",\"hard_id\":\"faef488c-d421-48aa-bb1d-f774bca713f1\",\"ips\":[\"172.20.4.37\"],\"m_time\":1702525022,\"webshell_type\":\"自研引擎\",\"size\":6441,\"group_id\":1,\"host_tag_map\":{},\"domain\":\"localhost\",\"os_type\":\"linux\",\"detail\":\"主机 172.20.4.37 发现Web后门：/opt/www/joywok/library/stomp-activemq/activemq_mipush.php\",\"source_id\":\"65a968125d7bd44c9a0d84d3\",\"user\":\"root\",\"host_name\":\"newcentosimage\",\"status\":\"\",\"hit_rule_count\":1,\"md5\":\"7290163b39153cb3c35658d73fcc258d\"}}"
    },
    {
      "logtype": "vul_patch_business_impact",
      "sample": "{\"payload\":{\"agent_id\":\"65dc2ff5c6ef8ec2\",\"port_proto\":null,\"pid\":855,\"remark\":null,\"platform\":\"Ubuntu 18.04.5 LTS (Bionic Beaver)\",\"internal_ip\":\"10.132.41.1\",\"charge_name\":null,\"host_location\":null,\"process_name\":\"accounts-daemon\",\"white_rule_effect\":false,\"group_relate_name\":\"RVM\",\"store_time\":1710110027,\"external_ip\":null,\"host_ip\":\"10.132.41.1\",\"asset_number\":null,\"charge_email\":null,\"bind_ip\":null,\"com_id\":\"4870564f756e646a7464\",\"pkg_version\":\"0.6.45-1ubuntu1.3\",\"hard_id\":\"6F0D99E1-4938-41AE-AD1B-B4F286F5CE07\",\"ips\":[\"10.132.41.1\",\"fe80::eda:41ff:fe1d:76da\"],\"pkg_name\":\"accountsservice\",\"vul_id\":\"QT012023007555\",\"group_id\":6,\"host_tag_map\":{},\"os_type\":\"linux\",\"cmd\":\"/usr/lib/accountsservice/accounts-daemon\",\"source_id\":\"65ee18b52694b647164fa824\",\"host_name\":\"ub18-cyc00\"},\"payload_id\":\"65ee354bb1af0e46d7012dbc\",\"payload_index\":\"vul_patch_business_impact\"}",
      "real_samples": "{\"payload\":{\"agent_id\":\"65dc2ff5c6ef8ec2\",\"port_proto\":null,\"pid\":855,\"remark\":null,\"platform\":\"Ubuntu 18.04.5 LTS (Bionic Beaver)\",\"internal_ip\":\"10.132.41.1\",\"charge_name\":null,\"host_location\":null,\"process_name\":\"accounts-daemon\",\"white_rule_effect\":false,\"group_relate_name\":\"RVM\",\"store_time\":1710110027,\"external_ip\":null,\"host_ip\":\"10.132.41.1\",\"asset_number\":null,\"charge_email\":null,\"bind_ip\":null,\"com_id\":\"4870564f756e646a7464\",\"pkg_version\":\"0.6.45-1ubuntu1.3\",\"hard_id\":\"6F0D99E1-4938-41AE-AD1B-B4F286F5CE07\",\"ips\":[\"10.132.41.1\",\"fe80::eda:41ff:fe1d:76da\"],\"pkg_name\":\"accountsservice\",\"vul_id\":\"QT012023007555\",\"group_id\":6,\"host_tag_map\":{},\"os_type\":\"linux\",\"cmd\":\"/usr/lib/accountsservice/accounts-daemon\",\"source_id\":\"65ee18b52694b647164fa824\",\"host_name\":\"ub18-cyc00\"},\"payload_id\":\"65ee354bb1af0e46d7012dbc\",\"payload_index\":\"vul_patch_business_impact\"}"
    }
  ]
}


2、syslog头+json的日志入口规则的生成
log_format_detail为日志头+JSON时，
parser里面的name恒为orgRegex，value恒为(\{[\S\s]*\})
parser里面的filter里面增加case，
name为conditionMatch的json数组，value值格式固定为original_log like ' '，引号里面的值遍历classification_details的logtype，其余结构不变
{
    "name": "orgRegex",
    "resolverType": "event",
    "unmappingKeep": false,
    "deviceType": "1",
    "filter": [
        {
            "fields": {
                "product": "",
                "event_name": "",
                "event_level": "",
                "log_vendor": ""
            },
            "name": "addFields",
            "id": "additional_fields_filter"
        },
        {
            "cases": [
                {
                    "value": "original_log like 'weak_passwd'",
                    "rule": {
                        "fields": {
                            "1": "1"
                        },
                        "name": "addFields",
                        "id": ""
                    },
                    "name": "case",
                    "id": ""
                },
                {
                    "value": "original_log like 'clear_password'",
                    "rule": {
                        "fields": {
                            "1": "1"
                        },
                        "name": "addFields",
                        "id": ""
                    },
                    "name": "case",
                    "id": ""
                }
            ],
            "default": {
                "name": "none"
            },
            "name": "conditionMatch",
            "id": ""
        }
    ],
    "value": "(\\{[\\S\\s]*\\})",
    "subResolver": 0
}

输出json结果：
{
    "status": "SUCCESS",
    "categorical_features": "在日志头中",
    "Diversion_method": "威胁行为标识",
    "log_format": "JSON",
    "feature_identifier": "(\\{[\\S\\s]*\\})",
    "feature_count": 4,
    "classification_details": [
        {
            "logtype": "clear_password",
            "sample": "<158>Aug 02 14:00:07 skyeye SyslogClient[1]: 2024-08-02 14:00:07|!172.16.254.61|!clear_password|!{\"branch_id\": \"QnMLEQg+O\", \"account\": \"scan\", \"group\": \"未分配资产组\", \"check_type\": \"规则匹配\", \"proto\": \"smtp\", \"passwd\": \"\\\"scan123\\\"\", \"access_time\": \"2024-08-02 12:20:44\", \"ret\": \"535 5.7.8 Error: authentication failed: authentication failure\", \"id\": \"2024-08-02-20b40c87739c88dfce6f1058066fecb1\", \"is_show\": 1, \"asset_ip\": \"172.16.128.1\", \"login_ret\": \"失败\", \"group_id\": 1, \"dip\": \"172.16.128.1\", \"port\": \"25\"}",
            "real_samples": "{\"branch_id\": \"QnMLEQg+O\", \"account\": \"scan\", \"group\": \"未分配资产组\", \"check_type\": \"规则匹配\", \"proto\": \"smtp\", \"passwd\": \"\\\"scan123\\\"\", \"access_time\": \"2024-08-02 12:20:44\", \"ret\": \"535 5.7.8 Error: authentication failed: authentication failure\", \"id\": \"2024-08-02-20b40c87739c88dfce6f1058066fecb1\", \"is_show\": 1, \"asset_ip\": \"172.16.128.1\", \"login_ret\": \"失败\", \"group_id\": 1, \"dip\": \"172.16.128.1\", \"port\": \"25\"}"
        },
        {
            "logtype": "weak_passwd",
            "sample": "<158>Aug 02 14:00:17 skyeye SyslogClient[1]: 2024-08-02 14:00:17|!172.16.254.61|!weak_passwd|!{\"branch_id\": \"QnMLEQg+O\", \"account\": \"admin\", \"sip\": \"80.94.92.124\", \"group\": \"未分配资产组\", \"check_type\": \"规则匹配\", \"proto\": \"smtp\", \"passwd\": \"\\\"admin123\\\"\", \"access_time\": \"2024-08-02 12:20:51\", \"host_state\": \"失败\", \"uri\": \"\", \"is_show\": 1, \"asset_ip\": \"172.16.128.1\", \"key\": \"2024-08-02-cfe077f796786699b430b59fd3078352\", \"label\": \"中间键型\", \"dip\": \"172.16.128.1\", \"port\": \"25\"}",
            "real_samples": "{\"branch_id\": \"QnMLEQg+O\", \"account\": \"admin\", \"sip\": \"80.94.92.124\", \"group\": \"未分配资产组\", \"check_type\": \"规则匹配\", \"proto\": \"smtp\", \"passwd\": \"\\\"admin123\\\"\", \"access_time\": \"2024-08-02 12:20:51\", \"host_state\": \"失败\", \"uri\": \"\", \"is_show\": 1, \"asset_ip\": \"172.16.128.1\", \"key\": \"2024-08-02-cfe077f796786699b430b59fd3078352\", \"label\": \"中间键型\", \"dip\": \"172.16.128.1\", \"port\": \"25\"}"
        }
    ],
    "fail_reason": "",
    "log_format_detail": "日志头+JSON",
    "feature_field": "__header__",
    "total_valid_lines": 3162,
    "covered_lines": 3162,
    "analysis": {
        "has_json_structure": true,
        "has_cef_prefix": false,
        "has_key_value_pairs": false,
        "has_delimited_structure": false,
        "delimit": ":",
        "tab": "space"
    },
    "header_end_marker": "",
    "feature_body_group": 0,
    "feature_value_group": 0
}