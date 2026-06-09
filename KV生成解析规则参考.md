
待处理：
1）入口规则生成
3）解析规则生成文档待补充
4）纯KV/KV+日志头子规则生成


1、纯KV格式的日志入口规则的生成
1）parser的name恒为delimitWithKeyMap，
2）tab取json输出结果里面的tab,delimit取json输出结果里面的delimit，
3）filter里面增加case，value值格式固定为feature_field like ' '，like前面的字段动态取feature_field里面的值，引号里面的值遍历classification_details的logtype，其余结构不变。
name为addFields的json里"fields": {
                "日志类型": "%{type}"
            }，key值恒为日志类型，后面格式%{}固定，里面的值动态取值feature_field
{
    "name": "delimitWithKeyMap",
    "tab": "=",
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
            "fields": {
                "日志类型": "%{type}"
            },
            "name": "addFields",
            "id": ""
        },
        {
            "cases": [
                {
                    "value": "type like 'ac'",
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
    "delimit": "\\s",
    "subResolver": 0
}
4）normalize添加json结构固定为：
{
    "mappings": [],
    "field": "log_type",
    "sim": true,
    "result": [
        "ac"
    ],
    "info": null,
    "entity": "日志",
    "required": false,
    "core": false,
    "value": "",
    "index": "日志类型"
}

参考json：

{
  "status": "SUCCESS",
  "log_format": "KV",
  "log_format_detail": "纯KV",
  "feature_field": "type",
  "feature_identifier": "",
  "feature_count": 3,
  "total_valid_lines": 2000,
  "covered_lines": 2000,
  "classification_details": [
    {
      "logtype": "ac",
      "sample": "id=tos time=\"2026-06-01 10:04:20\" fw=TopsecOS  pri=6 type=ac  recorder=FW-NAT src=10.32.12.200 dst=172.26.18.66 sport=42218 dport=80 smac=00:25:9e:92:6e:89 dmac=94:a6:d8:cc:72:78 proto=tcp indev=eth14 outdev=eth15 user= rule=���� connid=138383122 parentid=0 dpiid=0 natid=0 policyid=8121 msg=\"null\"",
      "real_samples": "id=tos time=\"2026-06-01 10:04:20\" fw=TopsecOS  pri=6 type=ac  recorder=FW-NAT src=10.32.12.200 dst=172.26.18.66 sport=42218 dport=80 smac=00:25:9e:92:6e:89 dmac=94:a6:d8:cc:72:78 proto=tcp indev=eth14 outdev=eth15 user= rule=���� connid=138383122 parentid=0 dpiid=0 natid=0 policyid=8121 msg=\"null\""
    },
    {
      "logtype": "conn",
      "sample": "id=tos time=\"2026-06-01 10:04:07\" fw=TopsecOS  pri=6 type=conn  recorder=session src=10.32.9.166 dst=172.26.18.66 proto=tcp sport=36794 dport=80 inpkt=6 outpkt=4 sent=376 rcvd=372 duration=20 connid=196924573 parent=0 op=ɾ�� msg=\"null\"",
      "real_samples": "id=tos time=\"2026-06-01 10:04:07\" fw=TopsecOS  pri=6 type=conn  recorder=session src=10.32.9.166 dst=172.26.18.66 proto=tcp sport=36794 dport=80 inpkt=6 outpkt=4 sent=376 rcvd=372 duration=20 connid=196924573 parent=0 op=ɾ�� msg=\"null\""
    },
    {
      "logtype": "vpn",
      "sample": "id=tos time=\"2026-06-01 10:04:19\" fw=TopsecOS  pri=7 type=vpn recorder=vpn msg=\"Line 0 registeration mutex is locked.\"",
      "real_samples": "id=tos time=\"2026-06-01 10:04:19\" fw=TopsecOS  pri=7 type=vpn recorder=vpn msg=\"Line 0 registeration mutex is locked.\""
    }
  ],
  "analysis": {
    "has_json_structure": false,
    "has_cef_prefix": false,
    "has_key_value_pairs": true,
    "has_delimited_structure": false,
    "delimit": "=",
    "tab": "space"
  },
  "categorical_features": "type",
  "Diversion_method": "日志类型",
  "fail_reason": "",
  "feature_body_group": 0,
  "feature_value_group": 0
}

2、syslog头+KV的入口规则生成：
log_format_detail为日志头+KV时，
parser里面的name恒为orgRegex，value为feature_identifier里的值
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
                    "value": "original_log like 'cloudwalker-brute-force'",
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
    "value": "<\\d+>\\d+\\s+\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z\\s+\\S+\\s+\\S+\\s+\\d+\\s+\\S+\\s+-\\s+([\\S\\s]*)",
    "subResolver": 0
}

输出json结果：
{
    "status": "SUCCESS",
    "categorical_features": "在日志头中",
    "Diversion_method": "事件类型",
    "log_format": "KV",
    "feature_identifier": "<\\d+>\\d+\\s+\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z\\s+\\S+\\s+\\S+\\s+\\d+\\s+\\S+\\s+-\\s+([\\S\\s]*)",
    "feature_count": 2,
    "classification_details": [
        {
            "logtype": "cloudwalker-brute-force",
            "sample": "<14>1 2026-04-14T05:57:49Z 070853be68d7 cloudwalker 1 cloudwalker-brute-force - \ufeffmsg_type=\"cloudwalker-brute-force\" host_name=\"rk-2dyw3-qz2\" host_ip=\"10.32.26.77\" business_group_id=1 business_group_name=\"根分组\" host_id=158 event_id=24340 event_name=\"暴力破解\" event_level=\"medium\" event_state=\"risky\" event_create_time=\"2026-04-14 13:55:42\" event_update_time=\"2026-04-14 13:57:49\" event_start_time=\"2026-04-14 13:15:05\" event_end_time=\"2026-04-14 13:22:05\" service_name=\"ssh\" source_ip=\"10.32.26.76\" org_id=1 org_name=\"默认机构\" host_attribute=[{\"attr_name\":\"负责人\",\"attr_value\":[]},{\"attr_name\":\"负责人邮箱\",\"attr_value\":[]},{\"attr_name\":\"机房位置\",\"attr_value\":[]},{\"attr_name\":\"固定资产编号\",\"attr_value\":[]},{\"attr_name\":\"资产等级\",\"attr_value\":[]}] level_1_biz_grp_name=\"根分组\" level_2_biz_grp_name=\"\" level_3_biz_grp_name=\"\" level_4_biz_grp_name=\"\" level_other_biz_grp_name=\"\"",
            "real_samples": "\ufeffmsg_type=\"cloudwalker-brute-force\" host_name=\"rk-2dyw3-qz2\" host_ip=\"10.32.26.77\" business_group_id=1 business_group_name=\"根分组\" host_id=158 event_id=24340 event_name=\"暴力破解\" event_level=\"medium\" event_state=\"risky\" event_create_time=\"2026-04-14 13:55:42\" event_update_time=\"2026-04-14 13:57:49\" event_start_time=\"2026-04-14 13:15:05\" event_end_time=\"2026-04-14 13:22:05\" service_name=\"ssh\" source_ip=\"10.32.26.76\" org_id=1 org_name=\"默认机构\" host_attribute=[{\"attr_name\":\"负责人\",\"attr_value\":[]},{\"attr_name\":\"负责人邮箱\",\"attr_value\":[]},{\"attr_name\":\"机房位置\",\"attr_value\":[]},{\"attr_name\":\"固定资产编号\",\"attr_value\":[]},{\"attr_name\":\"资产等级\",\"attr_value\":[]}] level_1_biz_grp_name=\"根分组\" level_2_biz_grp_name=\"\" level_3_biz_grp_name=\"\" level_4_biz_grp_name=\"\" level_other_biz_grp_name=\"\""
        }
    ],
    "analysis": {
        "has_json_structure": false,
        "has_cef_prefix": false,
        "has_key_value_pairs": true,
        "has_delimited_structure": false,
        "delimit": "=",
        "tab": "space"
    },
    "fail_reason": "",
    "log_format_detail": "日志头+KV",
    "feature_field": "__header__",
    "feature_body_group": 1,
    "feature_value_group": 0,
    "total_valid_lines": 500,
    "covered_lines": 92,
    "header_end_marker": " - "
}

3、纯KV/日志头+KV的子规则生成

3.1外层的name和description，动态取值json输出结果里面的classification_details里面的logtype，后面固定为_kv_子规则，举例如果logtype里面是AUTH_FAILURE，则为AUTH_FAILURE_kv_子规则；
3.2filter里增加name为addFields的json，fields的key为日志类型，value动态取值logtype的值。
       {
            "fields": {
                "日志类型": "AUTH_FAILURE"
            },
            "name": "addFields",
            "id": ""
        }
3.3 parser.name恒为delimitWithKeyMap，tab取tab的值，delimit取delimit里面值.但是子规则里面的delimit的值为符号，需进行转义，空格为\\s，以此类推。
{
    "name": "delimitWithKeyMap",
    "tab": "=",
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
            "fields": {
                "日志类型": "AUTH_FAILURE"
            },
            "name": "addFields",
            "id": ""
        }
    ],
    "delimit": "\\s",
    "subResolver": 1
}

3.4 normalize末尾追加 `日志类型` 条目
{
    "mappings": [],
    "field": "log_type",
    "sim": true,
    "result": [
        "AUTH_FAILURE"
    ],
    "info": null,
    "entity": "日志",
    "required": false,
    "core": false,
    "value": "",
    "index": "日志类型"
}

参考输出json
{
  "status": "SUCCESS",
  "categorical_features": "在日志头中",
  "Diversion_method": "在日志头中",
  "log_format": "KV",
  "feature_identifier": "<\\d+>\\w+\\s+\\d+\\s+\\d{2}:\\d{2}:\\d{2}\\s+\\S+\\s+\\S+：\\s*(.*)",
  "feature_count": 10,
  "classification_details": [
    {
      "logtype": "AUTH_FAILURE",
      "sample": "<134>Jun 8 08:15:22 host-server AUTH_FAILURE： user=admin method=ssh status=invalid_key src_ip=10.0.0.55 failure_count=3",
      "real_samples": "user=admin method=ssh status=invalid_key src_ip=10.0.0.55 failure_count=3"
    },
    {
      "logtype": "FILE_PERM_CHANGE",
      "sample": "<134>Jun 8 09:42:10 host-server FILE_PERM_CHANGE： process=rsyslogd target=/var/log/secure old_perm=600 new_perm=644 uid=0 gid=0",
      "real_samples": "process=rsyslogd target=/var/log/secure old_perm=600 new_perm=644 uid=0 gid=0"
    },
    {
      "logtype": "PROCESS_ABNORMAL_EXIT",
      "sample": "<134>Jun 8 10:18:33 host-server PROCESS_ABNORMAL_EXIT： process=nginx pid=1234 signal=SIGSEGV exit_code=139 core_dumped=true user=www-data",
      "real_samples": "process=nginx pid=1234 signal=SIGSEGV exit_code=139 core_dumped=true user=www-data"
    },
    {
      "logtype": "FIREWALL_RULE_CHANGE",
      "sample": "<134>Jun 8 11:05:47 host-server FIREWALL_RULE_CHANGE： action=add chain=INPUT rule=\"DROP tcp -- 203.0.113.0/24 0.0.0.0/0 dport:22\" operator=admin",
      "real_samples": "action=add chain=INPUT rule=\"DROP tcp -- 203.0.113.0/24 0.0.0.0/0 dport:22\" operator=admin"
    },
    {
      "logtype": "USER_ROLE_CHANGE",
      "sample": "<134>Jun 8 12:30:12 host-server USER_ROLE_CHANGE： operator=security_admin target=john_doe role=auditor action=assign reason=\"job rotation\"",
      "real_samples": "operator=security_admin target=john_doe role=auditor action=assign reason=\"job rotation\""
    },
    {
      "logtype": "SUSPICIOUS_CONNECTION",
      "sample": "<134>Jun 8 13:55:01 host-server SUSPICIOUS_CONNECTION： protocol=tcp src_port=54321 dst_ip=185.130.5.253 dst_port=4444 conn_state=established bytes=1048576",
      "real_samples": "protocol=tcp src_port=54321 dst_ip=185.130.5.253 dst_port=4444 conn_state=established bytes=1048576"
    },
    {
      "logtype": "QUOTA_EXCEEDED",
      "sample": "<134>Jun 8 14:40:23 host-server QUOTA_EXCEEDED： type=disk user=app_svc path=/home/app_svc used=98% limit=50GB inodes_used=250k",
      "real_samples": "type=disk user=app_svc path=/home/app_svc used=98% limit=50GB inodes_used=250k"
    },
    {
      "logtype": "SERVICE_FAILURE",
      "sample": "<134>Jun 8 15:20:17 host-server SERVICE_FAILURE： service=docker daemon error=\"failed to start containerd: exit status 1\" restart_count=5",
      "real_samples": "service=docker daemon error=\"failed to start containerd: exit status 1\" restart_count=5"
    },
    {
      "logtype": "SENSITIVE_FILE_ACCESS",
      "sample": "<134>Jun 8 16:10:05 host-server SENSITIVE_FILE_ACCESS： process=cat pid=8901 user=www-data file=/etc/shadow result=denied capabilities=\"no_dac_override\"",
      "real_samples": "process=cat pid=8901 user=www-data file=/etc/shadow result=denied capabilities=\"no_dac_override\""
    },
    {
      "logtype": "CRON_MODIFICATION",
      "sample": "<134>Jun 8 17:45:30 host-server CRON_MODIFICATION： user=operator crontab=/var/spool/cron/operator command=\"/bin/sh /tmp/backdoor.sh\" hash_change=true previous_hash=\"a1b2c3\" new_hash=\"d4e5f6\"",
      "real_samples": "user=operator crontab=/var/spool/cron/operator command=\"/bin/sh /tmp/backdoor.sh\" hash_change=true previous_hash=\"a1b2c3\" new_hash=\"d4e5f6\""
    }
  ],
  "analysis": {
    "has_json_structure": false,
    "has_cef_prefix": false,
    "has_key_value_pairs": true,
    "has_delimited_structure": false,
    "delimit": "space",
    "tab": "="
  },
  "log_format_detail": "日志头+KV",
  "feature_field": "__header__",
  "feature_body_group": 1,
  "feature_value_group": 0,
  "total_valid_lines": 1063,
  "covered_lines": 1063,
  "header_end_marker": "： "
}

{
  "status": "SUCCESS",
  "log_format": "KV",
  "log_format_detail": "纯KV",
  "feature_field": "type",
  "feature_identifier": "",
  "feature_count": 3,
  "total_valid_lines": 2000,
  "covered_lines": 2000,
  "classification_details": [
    {
      "logtype": "ac",
      "sample": "id=tos time=\"2026-06-01 10:04:20\" fw=TopsecOS  pri=6 type=ac  recorder=FW-NAT src=10.32.12.200 dst=172.26.18.66 sport=42218 dport=80 smac=00:25:9e:92:6e:89 dmac=94:a6:d8:cc:72:78 proto=tcp indev=eth14 outdev=eth15 user= rule=���� connid=138383122 parentid=0 dpiid=0 natid=0 policyid=8121 msg=\"null\"",
      "real_samples": "id=tos time=\"2026-06-01 10:04:20\" fw=TopsecOS  pri=6 type=ac  recorder=FW-NAT src=10.32.12.200 dst=172.26.18.66 sport=42218 dport=80 smac=00:25:9e:92:6e:89 dmac=94:a6:d8:cc:72:78 proto=tcp indev=eth14 outdev=eth15 user= rule=���� connid=138383122 parentid=0 dpiid=0 natid=0 policyid=8121 msg=\"null\""
    },
    {
      "logtype": "conn",
      "sample": "id=tos time=\"2026-06-01 10:04:07\" fw=TopsecOS  pri=6 type=conn  recorder=session src=10.32.9.166 dst=172.26.18.66 proto=tcp sport=36794 dport=80 inpkt=6 outpkt=4 sent=376 rcvd=372 duration=20 connid=196924573 parent=0 op=ɾ�� msg=\"null\"",
      "real_samples": "id=tos time=\"2026-06-01 10:04:07\" fw=TopsecOS  pri=6 type=conn  recorder=session src=10.32.9.166 dst=172.26.18.66 proto=tcp sport=36794 dport=80 inpkt=6 outpkt=4 sent=376 rcvd=372 duration=20 connid=196924573 parent=0 op=ɾ�� msg=\"null\""
    },
    {
      "logtype": "vpn",
      "sample": "id=tos time=\"2026-06-01 10:04:19\" fw=TopsecOS  pri=7 type=vpn recorder=vpn msg=\"Line 0 registeration mutex is locked.\"",
      "real_samples": "id=tos time=\"2026-06-01 10:04:19\" fw=TopsecOS  pri=7 type=vpn recorder=vpn msg=\"Line 0 registeration mutex is locked.\""
    }
  ],
  "analysis": {
    "has_json_structure": false,
    "has_cef_prefix": false,
    "has_key_value_pairs": true,
    "has_delimited_structure": false,
    "delimit": "space",
    "tab": "="
  },
  "categorical_features": "type",
  "Diversion_method": "日志类型",
  "fail_reason": "",
  "feature_body_group": 0,
  "feature_value_group": 0
}