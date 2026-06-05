syslog+kv时遇到的问题：
1、real_samples的值如何生成，为什么没有正确通过feature_identifier提取到捕获组里面的日志主体部分？
2、categorical_features的值时怎么生成的？能不能在日志类型在body里时，取值为字段名？
3、feature_field的值时怎么生成的？feature_field判断不准确，日志类型的特征值明明在body里，为什么会输出__header__？
{
  "status": "SUCCESS",
  "categorical_features": "在日志头中",
  "Diversion_method": "日志类型",
  "log_format": "KV",
  "feature_identifier": "<\\d+>\\S+:\\s*(.*)",
  "feature_count": 1,
  "classification_details": [
    {
      "logtype": "包过滤日志",
      "sample": "<5>kernel: devid=2 date=\"2026/06/01 18:04:17\" dname=themis logtype=1 pri=5 ver=0.3.0 rule_name=pf67 mod=pf sa=10.32.37.72 sport=32758 type=NULL da=192.168.28.130 dport=6999 code=NULL proto=IPPROTO_TCP policy=允许 duration=0 rcvd=60 sent=60 fwlog=0 dsp_msg=\"包过滤日志\"",
      "real_samples": "devid=2 date=\"2026/06/01 18:04:17\" dname=themis logtype=1 pri=5 ver=0.3.0 rule_name=pf67 mod=pf sa=10.32.37.72 sport=32758 type=NULL da=192.168.28.130 dport=6999 code=NULL proto=IPPROTO_TCP policy=允许 duration=0 rcvd=60 sent=60 fwlog=0 dsp_msg=\"包过滤日志\""
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
  "total_valid_lines": 10000,
  "covered_lines": 8390,
  "header_end_marker": ""
}


待处理：
1）入口规则生成
3）解析规则生成文档待补充
4）纯KV/KV+日志头子规则生成


1、纯KV格式的日志入口规则的生成
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

3.1外层的name和description，动态取值json输出结果里面的classification_details里面的logtype，后面固定为_kv_子规则，举例如果logtype里面是cloudwalker-brute-force，则为cloudwalker-brute-force_kv_子规则；
3.2filter里增加name为addFields的json，fields的key为日志类型，value动态取值logtype的值。
       {
            "fields": {
                "日志类型": "cloudwalker-brute-force"
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
                "日志类型": "cloudwalker-brute-force"
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
        "cloudwalker-brute-force"
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
    "Diversion_method": "事件类型",
    "log_format": "KV",
    "feature_identifier": "<\\d+>\\d+\\s+\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z\\s+\\S+\\s+\\S+\\s+\\d+\\s+\\S+\\s+-\\s+([\\S\\s]*)",
    "feature_count": 2,
    "classification_details": [
        {
            "logtype": "cloudwalker-suspicious-command",
            "sample": "<14>1 2026-04-14T05:57:55Z 070853be68d7 cloudwalker 1 cloudwalker-suspicious-command - \ufeffmsg_type=\"cloudwalker-suspicious-command\" host_name=\"wp-comp-app-j01\" host_ip=\"10.30.52.48\" business_group_id=1 business_group_name=\"根分组\" host_id=631 event_id=4831559 event_name=\"可疑命令\" rule_name=\"内置规则_Linux 网络应用执行 ps 命令\" signature=\"ps\" event_level=\"critical\" event_state=\"risky\" event_create_time=\"2026-04-14 13:58:05\" event_update_time=\"2026-04-14 13:57:55\" process_tree=[{\"pname\":\"init\",\"pid\":1,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":0,\"cmdline\":\"/sbin/init\"},{\"pname\":\"httpd\",\"pid\":9052,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":1,\"cmdline\":\"/opt/gitlab-7.10.1-0/apache2/bin/httpd -f /opt/gitlab-7.10.1-0/apache2/conf/httpd.conf\"},{\"pname\":\"PassengerWatchdog\",\"pid\":9058,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":9052,\"cmdline\":\"PassengerWatchdog\"},{\"pname\":\"PassengerHelperAgent\",\"pid\":9061,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":9058,\"cmdline\":\"PassengerHelperAgent\"},{\"pname\":\"ps\",\"pid\":8392,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":9061,\"cmdline\":\"ps -opid,ppid,%cpu,rss,vsize,pgid,uid,command -p7629,9250\"}] file_path=\"/bin/ps\" process_command_line=\"ps -opid,ppid,%cpu,rss,vsize,pgid,uid,command -p7629,9250\" event_start_time=\"2026-04-14 13:58:05\" user_id=0 user_name=\"root\" user_gid=0 user_gname=\"root\" env=[\"LDAPCONF=/opt/gitlab-7.10.1-0/common/etc/openldap/ldap.conf\",\"MAGICK_CONFIGURE_PATH=/opt/gitlab-7.10.1-0/common/lib/ImageMagick-6.7.5/config:/opt/gitlab-7.10.1-0/common/\",\"OPENSSL_CONF=/opt/gitlab-7.10.1-0/common/openssl/openssl.cnf\",\"GEM_PATH=/opt/gitlab-7.10.1-0/ruby/lib/ruby/gems/2.0.0\",\"GS_LIB=/opt/gitlab-7.10.1-0/common/share/ghostscript/fonts\",\"HOME=/root\",\"PWD=/root\",\"RUBY_HOME=/opt/gitlab-7.10.1-0/ruby\",\"SASL_PATH=/opt/gitlab-7.10.1-0/common/lib/sasl2\",\"CXXFLAGS=-I/opt/gitlab-7.10.1-0/common/include \",\"GITPERLLIB=/opt/gitlab-7.10.1-0/git/lib/site_perl/5.16.3\",\"MAGICK_CODER_MODULE_PATH=/opt/gitlab-7.10.1-0/common/lib/ImageMagick-6.7.5/modules-Q16/coders\",\"PERL5LIB=/opt/gitlab-7.10.1-0/git/lib/site_perl/5.16.3:/opt/gitlab-7.10.1-0/perl/lib/5.16.3:/opt/gitlab-7.10.1-0/perl/lib/site_perl/5.16.3:/opt/gitlab-7.10.1-0/perl/lib/5.16.3/x86_64-linux-thread-multi:/opt/gitlab-7.10.1-0/perl/lib/site_perl/5.16.3/x86_64-linux-thread-multi\",\"TERMINFO=/opt/gitlab-7.10.1-0/common/share/terminfo\",\"_=/opt/gitlab-7.10.1-0/apache2/bin/httpd\",\"GIT_TEMPLATE_DIR=/opt/gitlab-7.10.1-0/git/share/git-core/templates\",\"LOGNAME=root\",\"MAGICK_HOME=/opt/gitlab-7.10.1-0/common\",\"OPENSSL_ENGINES=/opt/gitlab-7.10.1-0/common/lib/engines\",\"PATH=/opt/gitlab-7.10.1-0/nodejs/bin:/opt/gitlab-7.10.1-0/apps/gitlabci/gitlabci-runner/bin:/opt/gitlab-7.10.1-0/apps/gitlab/gitlab-shell/bin:/opt/gitlab-7.10.1-0/redis/bin:/opt/gitlab-7.10.1-0/sqlite/bin:/opt/gitlab-7.10.1-0/python/bin:/opt/gitlab-7.10.1-0/perl/bin:/opt/gitlab-7.10.1-0/git/bin:/opt/gitlab-7.10.1-0/ruby/bin:/opt/gitlab-7.10.1-0/postgresql/bin:/opt/gitlab-7.10.1-0/mysql/bin:/opt/gitlab-7.10.1-0/apache2/bin:/opt/gitlab-7.10.1-0/common/bin:/usr/bin:/bin\",\"SASL_CONF_PATH=/opt/gitlab-7.10.1-0/common/etc\",\"SHELL=/bin/sh\",\"CFLAGS=-I/opt/gitlab-7.10.1-0/common/include/ImageMagick -I/opt/gitlab-7.10.1-0/common/include \",\"LDFLAGS=-L/opt/gitlab-7.10.1-0/common/lib \",\"NODE_PATH=/opt/gitlab-7.10.1-0/nodejs/lib/node_modules\",\"RUBYLIB=/opt/gitlab-7.10.1-0/ruby/lib/ruby/site_ruby/2.0.0:/opt/gitlab-7.10.1-0/ruby/lib/ruby/site_ruby/2.0.0/x86_64-linux:/opt/gitlab-7.10.1-0/ruby/lib/ruby/site_ruby/:/opt/gitlab-7.10.1-0/ruby/lib/ruby/vendor_ruby/2.0.0:/opt/gitlab-7.10.1-0/ruby/lib/ruby/vendor_ruby/2.0.0/x86_64-linux:/opt/gitlab-7.10.1-0/ruby/lib/ruby/vendor_ruby/:/opt/gitlab-7.10.1-0/ruby/lib/ruby/2.0.0:/opt/gitlab-7.10.1-0/ruby/lib/ruby/2.0.0/x86_64-linux:/opt/gitlab-7.10.1-0/ruby/lib/ruby/:/opt/gitlab-7.10.1-0/ruby/lib\",\"SSL_CERT_FILE=/opt/gitlab-7.10.1-0/common/openssl/certs/curl-ca-bundle.crt\",\"PYTHONHOME=/opt/gitlab-7.10.1-0/python\",\"BUNDLE_CONFIG=/opt/gitlab-7.10.1-0/ruby/.bundler/config\",\"CURL_CA_BUNDLE=/opt/gitlab-7.10.1-0/common/openssl/certs/curl-ca-bundle.crt\",\"LD_LIBRARY_PATH=/opt/gitlab-7.10.1-0/sqlite/lib:/opt/gitlab-7.10.1-0/python/lib:/opt/gitlab-7.10.1-0/mysql/lib:/opt/gitlab-7.10.1-0/apache2/lib:/opt/gitlab-7.10.1-0/common/lib:/opt/gitlab-7.10.1-0/ruby/lib/ruby/gems/2.0.0/gems/passenger-4.0.57/lib:/opt/gitlab-7.10.1-0/redis/lib:/opt/gitlab-7.10.1-0/sqlite/lib:/opt/gitlab-7.10.1-0/python/lib:/opt/gitlab-7.10.1-0/perl/lib:/opt/gitlab-7.10.1-0/perl/lib/5.16.3/x86_64-linux-thread-multi/CORE:/opt/gitlab-7.10.1-0/git/lib:/opt/gitlab-7.10.1-0/ruby/lib:/opt/gitlab-7.10.1-0/postgresql/lib:/opt/gitlab-7.10.1-0/mysql/lib:/opt/gitlab-7.10.1-0/apache2/lib:/opt/gitlab-7.10.1-0/common/lib:\",\"LANG=zh_CN.UTF-8\",\"PKG_CONFIG_PATH=/opt/gitlab-7.10.1-0/common/lib/pkgconfig\",\"SHLVL=3\",\"USER=root\",\"GEM_HOME=/opt/gitlab-7.10.1-0/ruby/lib/ruby/gems/2.0.0\",\"GIT_EXEC_PATH=/opt/gitlab-7.10.1-0/git/libexec/git-core/\",\"GIT_SSL_CAINFO=/opt/gitlab-7.10.1-0/common/openssl/certs/curl-ca-bundle.crt\"] process_all_command_line=[{\"ID\":4831559,\"CreatedAt\":\"2026-04-14T05:57:55.97929063Z\",\"UpdatedAt\":\"2026-04-14T05:57:55.97929063Z\",\"seq\":1,\"cmdline\":\"ps -opid,ppid,%cpu,rss,vsize,pgid,uid,command -p7629,9250\",\"cwd\":\"/\",\"start_time\":\"2026-04-14T05:58:05.99Z\",\"finish_time\":\"2026-04-14T05:58:05.99Z\",\"exit_code\":0,\"label\":\"suspicious\"}] process_name=\"ps\" event_end_time=\"2026-04-14 13:58:05\" event_description=\"检测到网络应用执行了 ps 命令。网络应用通常不会执行此类命令，可能是入侵者在利用远程命令执行漏洞。\" event_solution=\"\" org_id=1 org_name=\"默认机构\" host_attribute=[{\"attr_name\":\"固定资产编号\",\"attr_value\":[]},{\"attr_name\":\"资产等级\",\"attr_value\":[]},{\"attr_name\":\"负责人\",\"attr_value\":[]},{\"attr_name\":\"负责人邮箱\",\"attr_value\":[]},{\"attr_name\":\"机房位置\",\"attr_value\":[]}] level_1_biz_grp_name=\"根分组\" level_2_biz_grp_name=\"\" level_3_biz_grp_name=\"\" level_4_biz_grp_name=\"\" level_other_biz_grp_name=\"\"",
            "real_samples": "\ufeffmsg_type=\"cloudwalker-suspicious-command\" host_name=\"wp-comp-app-j01\" host_ip=\"10.30.52.48\" business_group_id=1 business_group_name=\"根分组\" host_id=631 event_id=4831559 event_name=\"可疑命令\" rule_name=\"内置规则_Linux 网络应用执行 ps 命令\" signature=\"ps\" event_level=\"critical\" event_state=\"risky\" event_create_time=\"2026-04-14 13:58:05\" event_update_time=\"2026-04-14 13:57:55\" process_tree=[{\"pname\":\"init\",\"pid\":1,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":0,\"cmdline\":\"/sbin/init\"},{\"pname\":\"httpd\",\"pid\":9052,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":1,\"cmdline\":\"/opt/gitlab-7.10.1-0/apache2/bin/httpd -f /opt/gitlab-7.10.1-0/apache2/conf/httpd.conf\"},{\"pname\":\"PassengerWatchdog\",\"pid\":9058,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":9052,\"cmdline\":\"PassengerWatchdog\"},{\"pname\":\"PassengerHelperAgent\",\"pid\":9061,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":9058,\"cmdline\":\"PassengerHelperAgent\"},{\"pname\":\"ps\",\"pid\":8392,\"uname\":\"root\",\"uid\":0,\"sid\":\"\",\"euname\":\"root\",\"euid\":0,\"ppid\":9061,\"cmdline\":\"ps -opid,ppid,%cpu,rss,vsize,pgid,uid,command -p7629,9250\"}] file_path=\"/bin/ps\" process_command_line=\"ps -opid,ppid,%cpu,rss,vsize,pgid,uid,command -p7629,9250\" event_start_time=\"2026-04-14 13:58:05\" user_id=0 user_name=\"root\" user_gid=0 user_gname=\"root\" env=[\"LDAPCONF=/opt/gitlab-7.10.1-0/common/etc/openldap/ldap.conf\",\"MAGICK_CONFIGURE_PATH=/opt/gitlab-7.10.1-0/common/lib/ImageMagick-6.7.5/config:/opt/gitlab-7.10.1-0/common/\",\"OPENSSL_CONF=/opt/gitlab-7.10.1-0/common/openssl/openssl.cnf\",\"GEM_PATH=/opt/gitlab-7.10.1-0/ruby/lib/ruby/gems/2.0.0\",\"GS_LIB=/opt/gitlab-7.10.1-0/common/share/ghostscript/fonts\",\"HOME=/root\",\"PWD=/root\",\"RUBY_HOME=/opt/gitlab-7.10.1-0/ruby\",\"SASL_PATH=/opt/gitlab-7.10.1-0/common/lib/sasl2\",\"CXXFLAGS=-I/opt/gitlab-7.10.1-0/common/include \",\"GITPERLLIB=/opt/gitlab-7.10.1-0/git/lib/site_perl/5.16.3\",\"MAGICK_CODER_MODULE_PATH=/opt/gitlab-7.10.1-0/common/lib/ImageMagick-6.7.5/modules-Q16/coders\",\"PERL5LIB=/opt/gitlab-7.10.1-0/git/lib/site_perl/5.16.3:/opt/gitlab-7.10.1-0/perl/lib/5.16.3:/opt/gitlab-7.10.1-0/perl/lib/site_perl/5.16.3:/opt/gitlab-7.10.1-0/perl/lib/5.16.3/x86_64-linux-thread-multi:/opt/gitlab-7.10.1-0/perl/lib/site_perl/5.16.3/x86_64-linux-thread-multi\",\"TERMINFO=/opt/gitlab-7.10.1-0/common/share/terminfo\",\"_=/opt/gitlab-7.10.1-0/apache2/bin/httpd\",\"GIT_TEMPLATE_DIR=/opt/gitlab-7.10.1-0/git/share/git-core/templates\",\"LOGNAME=root\",\"MAGICK_HOME=/opt/gitlab-7.10.1-0/common\",\"OPENSSL_ENGINES=/opt/gitlab-7.10.1-0/common/lib/engines\",\"PATH=/opt/gitlab-7.10.1-0/nodejs/bin:/opt/gitlab-7.10.1-0/apps/gitlabci/gitlabci-runner/bin:/opt/gitlab-7.10.1-0/apps/gitlab/gitlab-shell/bin:/opt/gitlab-7.10.1-0/redis/bin:/opt/gitlab-7.10.1-0/sqlite/bin:/opt/gitlab-7.10.1-0/python/bin:/opt/gitlab-7.10.1-0/perl/bin:/opt/gitlab-7.10.1-0/git/bin:/opt/gitlab-7.10.1-0/ruby/bin:/opt/gitlab-7.10.1-0/postgresql/bin:/opt/gitlab-7.10.1-0/mysql/bin:/opt/gitlab-7.10.1-0/apache2/bin:/opt/gitlab-7.10.1-0/common/bin:/usr/bin:/bin\",\"SASL_CONF_PATH=/opt/gitlab-7.10.1-0/common/etc\",\"SHELL=/bin/sh\",\"CFLAGS=-I/opt/gitlab-7.10.1-0/common/include/ImageMagick -I/opt/gitlab-7.10.1-0/common/include \",\"LDFLAGS=-L/opt/gitlab-7.10.1-0/common/lib \",\"NODE_PATH=/opt/gitlab-7.10.1-0/nodejs/lib/node_modules\",\"RUBYLIB=/opt/gitlab-7.10.1-0/ruby/lib/ruby/site_ruby/2.0.0:/opt/gitlab-7.10.1-0/ruby/lib/ruby/site_ruby/2.0.0/x86_64-linux:/opt/gitlab-7.10.1-0/ruby/lib/ruby/site_ruby/:/opt/gitlab-7.10.1-0/ruby/lib/ruby/vendor_ruby/2.0.0:/opt/gitlab-7.10.1-0/ruby/lib/ruby/vendor_ruby/2.0.0/x86_64-linux:/opt/gitlab-7.10.1-0/ruby/lib/ruby/vendor_ruby/:/opt/gitlab-7.10.1-0/ruby/lib/ruby/2.0.0:/opt/gitlab-7.10.1-0/ruby/lib/ruby/2.0.0/x86_64-linux:/opt/gitlab-7.10.1-0/ruby/lib/ruby/:/opt/gitlab-7.10.1-0/ruby/lib\",\"SSL_CERT_FILE=/opt/gitlab-7.10.1-0/common/openssl/certs/curl-ca-bundle.crt\",\"PYTHONHOME=/opt/gitlab-7.10.1-0/python\",\"BUNDLE_CONFIG=/opt/gitlab-7.10.1-0/ruby/.bundler/config\",\"CURL_CA_BUNDLE=/opt/gitlab-7.10.1-0/common/openssl/certs/curl-ca-bundle.crt\",\"LD_LIBRARY_PATH=/opt/gitlab-7.10.1-0/sqlite/lib:/opt/gitlab-7.10.1-0/python/lib:/opt/gitlab-7.10.1-0/mysql/lib:/opt/gitlab-7.10.1-0/apache2/lib:/opt/gitlab-7.10.1-0/common/lib:/opt/gitlab-7.10.1-0/ruby/lib/ruby/gems/2.0.0/gems/passenger-4.0.57/lib:/opt/gitlab-7.10.1-0/redis/lib:/opt/gitlab-7.10.1-0/sqlite/lib:/opt/gitlab-7.10.1-0/python/lib:/opt/gitlab-7.10.1-0/perl/lib:/opt/gitlab-7.10.1-0/perl/lib/5.16.3/x86_64-linux-thread-multi/CORE:/opt/gitlab-7.10.1-0/git/lib:/opt/gitlab-7.10.1-0/ruby/lib:/opt/gitlab-7.10.1-0/postgresql/lib:/opt/gitlab-7.10.1-0/mysql/lib:/opt/gitlab-7.10.1-0/apache2/lib:/opt/gitlab-7.10.1-0/common/lib:\",\"LANG=zh_CN.UTF-8\",\"PKG_CONFIG_PATH=/opt/gitlab-7.10.1-0/common/lib/pkgconfig\",\"SHLVL=3\",\"USER=root\",\"GEM_HOME=/opt/gitlab-7.10.1-0/ruby/lib/ruby/gems/2.0.0\",\"GIT_EXEC_PATH=/opt/gitlab-7.10.1-0/git/libexec/git-core/\",\"GIT_SSL_CAINFO=/opt/gitlab-7.10.1-0/common/openssl/certs/curl-ca-bundle.crt\"] process_all_command_line=[{\"ID\":4831559,\"CreatedAt\":\"2026-04-14T05:57:55.97929063Z\",\"UpdatedAt\":\"2026-04-14T05:57:55.97929063Z\",\"seq\":1,\"cmdline\":\"ps -opid,ppid,%cpu,rss,vsize,pgid,uid,command -p7629,9250\",\"cwd\":\"/\",\"start_time\":\"2026-04-14T05:58:05.99Z\",\"finish_time\":\"2026-04-14T05:58:05.99Z\",\"exit_code\":0,\"label\":\"suspicious\"}] process_name=\"ps\" event_end_time=\"2026-04-14 13:58:05\" event_description=\"检测到网络应用执行了 ps 命令。网络应用通常不会执行此类命令，可能是入侵者在利用远程命令执行漏洞。\" event_solution=\"\" org_id=1 org_name=\"默认机构\" host_attribute=[{\"attr_name\":\"固定资产编号\",\"attr_value\":[]},{\"attr_name\":\"资产等级\",\"attr_value\":[]},{\"attr_name\":\"负责人\",\"attr_value\":[]},{\"attr_name\":\"负责人邮箱\",\"attr_value\":[]},{\"attr_name\":\"机房位置\",\"attr_value\":[]}] level_1_biz_grp_name=\"根分组\" level_2_biz_grp_name=\"\" level_3_biz_grp_name=\"\" level_4_biz_grp_name=\"\" level_other_biz_grp_name=\"\""
        },
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
        "delimit": "space",
        "tab": "="
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