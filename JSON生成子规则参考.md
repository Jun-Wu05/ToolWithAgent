纯json/syslog+json的子规则生成
1、name和description的格式为遍历classification_details里面的logtype和feature_field的值，生成logtype_feature_field_格式_子规则，
举例logtype为威胁感知事件，feature_field为categoryName，格式为json时，name为威胁感知事件_categoryName_json_子规则；
2、parser部分的name恒为json

syslog+json的子规则里单独处理：filter里加name为addFields，fields的key值恒为日志类型，value值，遍历logtype取值。
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
            "fields": {
                "日志类型": "威胁感知事件"
            },
            "name": "addFields",
            "id": ""
        }
    ],
    "subResolver": 1
}
3、normalize为重点设计部分：
1）syslog+json的子规则里单独处理添加index为日志类型的json，field恒为log_type
{
    "mappings": [],
    "field": "log_type",
    "sim": true,
    "result": [
        "威胁感知事件"
    ],
    "info": null,
    "entity": "日志",
    "required": false,
    "core": false,
    "value": "",
    "index": "日志类型"
}
待处理：
2）
real_samples的纯json部分，通过代码的形式，将json解析为key：value的形式后，index为key，result里为value，结构字段为：
{
    "mappings": [],
    "field": null,
    "sim": null,
    "result": [
        "TCP端口扫描"
    ],
    "info": null,
    "entity": null,
    "required": false,
    "core": null,
    "value": null,
    "index": "typeName"
}
可能出现的问题：
2.1 嵌套多层json如何处理，代码能否往下继续提取，
建议处理方式：
最多提取到第二层a.b；
2.2 json的值为数组形式，能否正常处理


1、syslog+json输出结果：
{
    "status": "SUCCESS",
    "log_format": "JSON",
    "log_format_detail": "日志头+JSON",
    "feature_field": "categoryName",
    "feature_identifier": "(\\{[\\S\\s]*\\})",
    "feature_count": 2,
    "total_valid_lines": 208,
    "covered_lines": 208,
    "classification_details": [
        {
            "logtype": "威胁感知事件",
            "sample": "<14>1 2024-07-08T09:22:13.288Z ecm-974c-0013 - - - - {\"accessCode\":\"all\",\"action\":{\"text\":\"10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描\"},\"agentInputTime\":\"1720430531595\",\"aggKey\":\"A-l4RB6KZI0SgILf\",\"alarmMsg\":\"攻击者正在对您的服务器 10.249.210.29 进行端口扫描，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"威胁感知事件\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明服务器的TCP端口正在被扫描。建议将进行端口扫描的IP加入到云中心的黑名单。\",\"description\":\"利用TCP扫描工具检测服务器TCP端口的分配及提供的服务和它们的软件版本。\",\"eventGrade\":1,\"eventId\":1114112,\"eventInputTime\":\"2024-07-08 17:22:11\",\"eventType\":0,\"eventUuid\":\"00110000\",\"groupName\":\"TCP端口扫描\",\"hour\":17,\"ifFort\":1,\"innerIp\":\"10.249.210.29\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184144413,\"ip\":\"10.249.210.17\",\"ipAddress\":\"(局域网)\",\"ipLong\":184144401,\"judgeStatus\":\"未研判\",\"levelDesc\":\"低危\",\"localTimestamp\":1720430530000,\"logType\":1,\"logUuid\":\"0524251c18e249f8928c89fc871c2ce7\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.249.210.29\",\"intranetIp\":\"10.249.210.29\",\"machineName\":\"jtshxtgztw007\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2012 R2 Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\"},\"machineUuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\",\"markName\":\"undefined\",\"minute\":1042,\"object\":{\"other\":\"80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902\"},\"operation\":\"\",\"operationDesc\":\"\",\"phase\":1,\"phaseDesc\":\"探测\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":1,\"saveEsTime\":\"2024-07-08 17:22:11\",\"score\":0,\"source\":1,\"sourceDesc\":\"内置规则\",\"sourceIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.17\",\"region\":\"\",\"type\":\"局域网\"},\"standardTimestamp\":1720430530000,\"status\":0,\"subject\":{\"procHash\":\"-1\",\"process\":\"10.249.210.17\",\"type\":\"kernel_event\",\"user\":\"unknow\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.29\",\"region\":\"\",\"type\":\"局域网\"},\"typeName\":\"TCP端口扫描\",\"ucrc\":1100636110,\"unitCode\":\"97c9bbda9d8e4cee8774b5bd3141c2f6\",\"userUuids\":[\"2c9b6f6673e4429e8bc1a7a949a7c993\"]}",
            "real_samples": "{\"accessCode\":\"all\",\"action\":{\"text\":\"10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描\"},\"agentInputTime\":\"1720430531595\",\"aggKey\":\"A-l4RB6KZI0SgILf\",\"alarmMsg\":\"攻击者正在对您的服务器 10.249.210.29 进行端口扫描，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"威胁感知事件\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明服务器的TCP端口正在被扫描。建议将进行端口扫描的IP加入到云中心的黑名单。\",\"description\":\"利用TCP扫描工具检测服务器TCP端口的分配及提供的服务和它们的软件版本。\",\"eventGrade\":1,\"eventId\":1114112,\"eventInputTime\":\"2024-07-08 17:22:11\",\"eventType\":0,\"eventUuid\":\"00110000\",\"groupName\":\"TCP端口扫描\",\"hour\":17,\"ifFort\":1,\"innerIp\":\"10.249.210.29\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184144413,\"ip\":\"10.249.210.17\",\"ipAddress\":\"(局域网)\",\"ipLong\":184144401,\"judgeStatus\":\"未研判\",\"levelDesc\":\"低危\",\"localTimestamp\":1720430530000,\"logType\":1,\"logUuid\":\"0524251c18e249f8928c89fc871c2ce7\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.249.210.29\",\"intranetIp\":\"10.249.210.29\",\"machineName\":\"jtshxtgztw007\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2012 R2 Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\"},\"machineUuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\",\"markName\":\"undefined\",\"minute\":1042,\"object\":{\"other\":\"80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902\"},\"operation\":\"\",\"operationDesc\":\"\",\"phase\":1,\"phaseDesc\":\"探测\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":1,\"saveEsTime\":\"2024-07-08 17:22:11\",\"score\":0,\"source\":1,\"sourceDesc\":\"内置规则\",\"sourceIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.17\",\"region\":\"\",\"type\":\"局域网\"},\"standardTimestamp\":1720430530000,\"status\":0,\"subject\":{\"procHash\":\"-1\",\"process\":\"10.249.210.17\",\"type\":\"kernel_event\",\"user\":\"unknow\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.29\",\"region\":\"\",\"type\":\"局域网\"},\"typeName\":\"TCP端口扫描\",\"ucrc\":1100636110,\"unitCode\":\"97c9bbda9d8e4cee8774b5bd3141c2f6\",\"userUuids\":[\"2c9b6f6673e4429e8bc1a7a949a7c993\"]}"
        },
        {
            "logtype": "系统加固日志",
            "sample": "<14>1 2024-07-08T08:54:56.792Z ecm-974c-0013 - - - - {\"accessCode\":\"all\",\"action\":{\"text\":\"对外服务进程 C:\\\\Program Files (x86)\\\\Alibaba\\\\aegis\\\\aegis_client\\\\aegis_10_94\\\\aliyundun.exe 创建可执行文件 c:\\\\program files (x86)\\\\alibaba\\\\aegis\\\\aegis_update\\\\aliyundunupdate.exe。来源：操作系统加固\"},\"agentInputTime\":\"1720428883652\",\"aggKey\":\"B0IFvJ0MJ_AgwBMi\",\"alarmMsg\":\"您的服务器 10.252.96.224 有对外服务进程创建二进制文件，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"系统加固日志\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明网站服务器正在被对外服务进程创建可执行文件。通过云中心PC端开启强制访问控制，并通过事件管理分析事件详情及日志，查找被上传可疑文件的漏洞，对其进行修补。\",\"description\":\"对外服务进程创建可执行文件\",\"eventGrade\":0,\"eventId\":327681,\"eventInputTime\":\"2024-07-08 16:54:43\",\"eventType\":0,\"eventUuid\":\"00050001\",\"groupName\":\"可疑二进制文件\",\"hour\":16,\"ifFort\":1,\"innerIp\":\"10.252.96.224\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184312032,\"judgeStatus\":\"未研判\",\"levelDesc\":\"高危\",\"localTimestamp\":1720428882000,\"logType\":1,\"logUuid\":\"3f7f8f088a9d4cf7b0529038b6e7e0d5\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.252.96.224\",\"intranetIp\":\"10.252.96.224\",\"machineName\":\"izz143itflcktlz\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2016 Technical Preview Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"a0931f794cb8f06d7456c282b4568eb5\"},\"machineUuid\":\"a0931f794cb8f06d7456c282b4568eb5\",\"markName\":\"undefined\",\"minute\":1014,\"object\":{\"file\":\"c:/program files (x86)/alibaba/aegis/aegis_update/aliyundunupdate.exe\",\"fileHash\":\"ee69b4dc72bd0d0cd1fa3cb6cbadd2c8662f3824ebd3f3f720097667a7ba3270\"},\"operation\":\"create_bin\",\"operationDesc\":\"创建二进制文件\",\"phase\":3,\"phaseDesc\":\"控制\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":0,\"saveEsTime\":\"2024-07-08 16:54:43\",\"score\":20,\"serviceId\":\"\",\"source\":1,\"sourceDesc\":\"内置规则\",\"standardTimestamp\":1720428882000,\"status\":0,\"subject\":{\"bVerify\":\"yes\",\"company\":\"Alibaba Cloud Computing Ltd\",\"pid\":\"27812\",\"procHash\":\"799a60888891c38ffb040e7c2c70c5e2\",\"procUuid\":\"bb9fb2776f4b68208a554da56edb4783\",\"process\":\"C:/Program Files (x86)/Alibaba/aegis/aegis_client/aegis_10_94/aliyundun.exe\",\"type\":\"kernel\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.252.96.224\",\"region\":\"\",\"type\":\"局域网\"},\"treePath\":\"wininit.exe(NT AUTHORITY\\\\SYSTEM)(480)|services.exe(NT AUTHORITY\\\\SYSTEM)(592)|AliYunDun.exe(NT AUTHORITY\\\\SYSTEM)(27812)\",\"typeName\":\"对外服务进程创建可执行文件\",\"ucrc\":1980191992,\"unitCode\":\"d3d4aa2cb9ab443eb2a3be96dcd2ae3e\",\"userUuids\":[\"0e682938d83d44e98dba57199d55bee2\"]}",
            "real_samples": "{\"accessCode\":\"all\",\"action\":{\"text\":\"对外服务进程 C:\\\\Program Files (x86)\\\\Alibaba\\\\aegis\\\\aegis_client\\\\aegis_10_94\\\\aliyundun.exe 创建可执行文件 c:\\\\program files (x86)\\\\alibaba\\\\aegis\\\\aegis_update\\\\aliyundunupdate.exe。来源：操作系统加固\"},\"agentInputTime\":\"1720428883652\",\"aggKey\":\"B0IFvJ0MJ_AgwBMi\",\"alarmMsg\":\"您的服务器 10.252.96.224 有对外服务进程创建二进制文件，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"系统加固日志\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明网站服务器正在被对外服务进程创建可执行文件。通过云中心PC端开启强制访问控制，并通过事件管理分析事件详情及日志，查找被上传可疑文件的漏洞，对其进行修补。\",\"description\":\"对外服务进程创建可执行文件\",\"eventGrade\":0,\"eventId\":327681,\"eventInputTime\":\"2024-07-08 16:54:43\",\"eventType\":0,\"eventUuid\":\"00050001\",\"groupName\":\"可疑二进制文件\",\"hour\":16,\"ifFort\":1,\"innerIp\":\"10.252.96.224\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184312032,\"judgeStatus\":\"未研判\",\"levelDesc\":\"高危\",\"localTimestamp\":1720428882000,\"logType\":1,\"logUuid\":\"3f7f8f088a9d4cf7b0529038b6e7e0d5\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.252.96.224\",\"intranetIp\":\"10.252.96.224\",\"machineName\":\"izz143itflcktlz\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2016 Technical Preview Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"a0931f794cb8f06d7456c282b4568eb5\"},\"machineUuid\":\"a0931f794cb8f06d7456c282b4568eb5\",\"markName\":\"undefined\",\"minute\":1014,\"object\":{\"file\":\"c:/program files (x86)/alibaba/aegis/aegis_update/aliyundunupdate.exe\",\"fileHash\":\"ee69b4dc72bd0d0cd1fa3cb6cbadd2c8662f3824ebd3f3f720097667a7ba3270\"},\"operation\":\"create_bin\",\"operationDesc\":\"创建二进制文件\",\"phase\":3,\"phaseDesc\":\"控制\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":0,\"saveEsTime\":\"2024-07-08 16:54:43\",\"score\":20,\"serviceId\":\"\",\"source\":1,\"sourceDesc\":\"内置规则\",\"standardTimestamp\":1720428882000,\"status\":0,\"subject\":{\"bVerify\":\"yes\",\"company\":\"Alibaba Cloud Computing Ltd\",\"pid\":\"27812\",\"procHash\":\"799a60888891c38ffb040e7c2c70c5e2\",\"procUuid\":\"bb9fb2776f4b68208a554da56edb4783\",\"process\":\"C:/Program Files (x86)/Alibaba/aegis/aegis_client/aegis_10_94/aliyundun.exe\",\"type\":\"kernel\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.252.96.224\",\"region\":\"\",\"type\":\"局域网\"},\"treePath\":\"wininit.exe(NT AUTHORITY\\\\SYSTEM)(480)|services.exe(NT AUTHORITY\\\\SYSTEM)(592)|AliYunDun.exe(NT AUTHORITY\\\\SYSTEM)(27812)\",\"typeName\":\"对外服务进程创建可执行文件\",\"ucrc\":1980191992,\"unitCode\":\"d3d4aa2cb9ab443eb2a3be96dcd2ae3e\",\"userUuids\":[\"0e682938d83d44e98dba57199d55bee2\"]}"
        }
    ]
}

2、纯json输出结果

{
    "status": "SUCCESS",
    "log_format": "JSON",
    "log_format_detail": "纯JSON",
    "feature_field": "type",
    "feature_identifier": "(\\{[\\S\\s]*\\})",
    "feature_count": 3,
    "total_valid_lines": 84,
    "covered_lines": 84,
    "classification_details": [
        {
            "logtype": "T_INTRANET_DETECTION",
            "sample": "{\"rectime\":1618541709000,\"ds\":\"20210416\",\"hh\":\"10\",\"app\":\"明御主机安全及管理系统\",\"app_version\":\"2.0.16.4\",\"uid\":\"TX1383f7\",\"username\":\"test\",\"uuid\":\"619c4d322b0d9c7f1f91ee245830c6331c1d4cd608f44b21f4d31a1 1a72fc1 10\",\"machine_ip\":\"10.50.38.161\",\"type\":\"T_INTRANET_DETECTION\",\"event_id\":6001,\"event_str\":\"内网探测\",\"desc\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe 的运行已放行(禁止PSExec的工具运行)\",\"suggest\":[\"* 查看渗透工具的上传时间，并查看在这个时间段有哪些服务器对本地服务器进行了访问，这些服务器中可能存在已经被攻击者控制的机器，对可疑的服务器进行访问限制\",\"* 保存样本并及时删除渗透工具\",\"* 对本机进行访问限制，防止对内网中的其他服务器进行攻击\",\"* 找出渗透工具指定攻击的服务器，并进行访问限制，提早控制传染源\"],\"risk\":\"已失陷\",\"ip\":\"10.11.36.202\",\"ip_location\":\"局域网\",\"process\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe\",\"process_md5\":\"27304b246c7d5b4e149124d5f93c5b01\",\"process_id\":3888,\"process_user\":\"Administrator\",\"process_command_line\":\"\\\\\\\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe\\\\\\\" \",\"pprocess\":\"C:\\\\\\\\Windows\\\\\\\\explorer.exe\",\"pprocess_md5\":\"ac4c51eb24aa95b77f705ab159189e24\",\"pprocess_id\":4640,\"pprocess_user\":\"Administrator\",\"pprocess_command_line\":\"C:\\\\\\\\Windows\\\\\\\\Explorer.EXE\",\"process_tree\":\"explorer.exe(4640) -\\\\u003e PsExec.exe(3888)\",\"operation\":\"创建进程\",\"file_path\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe\",\"result\":\"已放行\"}",
            "real_samples": "{\"rectime\":1618541709000,\"ds\":\"20210416\",\"hh\":\"10\",\"app\":\"明御主机安全及管理系统\",\"app_version\":\"2.0.16.4\",\"uid\":\"TX1383f7\",\"username\":\"test\",\"uuid\":\"619c4d322b0d9c7f1f91ee245830c6331c1d4cd608f44b21f4d31a1 1a72fc1 10\",\"machine_ip\":\"10.50.38.161\",\"type\":\"T_INTRANET_DETECTION\",\"event_id\":6001,\"event_str\":\"内网探测\",\"desc\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe 的运行已放行(禁止PSExec的工具运行)\",\"suggest\":[\"* 查看渗透工具的上传时间，并查看在这个时间段有哪些服务器对本地服务器进行了访问，这些服务器中可能存在已经被攻击者控制的机器，对可疑的服务器进行访问限制\",\"* 保存样本并及时删除渗透工具\",\"* 对本机进行访问限制，防止对内网中的其他服务器进行攻击\",\"* 找出渗透工具指定攻击的服务器，并进行访问限制，提早控制传染源\"],\"risk\":\"已失陷\",\"ip\":\"10.11.36.202\",\"ip_location\":\"局域网\",\"process\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe\",\"process_md5\":\"27304b246c7d5b4e149124d5f93c5b01\",\"process_id\":3888,\"process_user\":\"Administrator\",\"process_command_line\":\"\\\\\\\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe\\\\\\\" \",\"pprocess\":\"C:\\\\\\\\Windows\\\\\\\\explorer.exe\",\"pprocess_md5\":\"ac4c51eb24aa95b77f705ab159189e24\",\"pprocess_id\":4640,\"pprocess_user\":\"Administrator\",\"pprocess_command_line\":\"C:\\\\\\\\Windows\\\\\\\\Explorer.EXE\",\"process_tree\":\"explorer.exe(4640) -\\\\u003e PsExec.exe(3888)\",\"operation\":\"创建进程\",\"file_path\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\内网探测\\\\\\\\PsExec.exe\",\"result\":\"已放行\"}"
        },
        {
            "logtype": "T_STANDALONE_EXPANSION",
            "sample": "{\"rectime\":1618489628000,\"ds\":\"20210415\",\"hh\":\"20\",\"app\":\"明御主机安全及管理系统\",\"app_version\":\"2.0.16.4\",\"uid\":\"TX1383f7\",\"username\":\"test\",\"uuid\":\"aeab9d8bce39429d531bbfe4b31b769f555babba3ea6433ca52f5f5fb0757a8b\",\"machine_ip\":\"10.50.38.46\",\"type\":\"T_STANDALONE_EXPANSION\",\"event_id\":6002,\"event_str\":\"单机扩展\",\"desc\":\"/usr/bin/python 的运行已放行(514b86a378ddc73a94a4aafbc3aad4df)\",\"suggest\":[\"* 查看渗透工具的上传时间，并查看在这个时间段有哪些服务器对本地服务器进行了访问，这些服务器中可能存在已经被攻击者控制的机器， 对可疑的服务器进行访问限制\",\"* 保存样本并及时删除渗透工具\",\"* 对本机进行访问限制， 防止对内网中的其他服务器进行攻击\",\"* 找出渗透工具指定攻击的服务器， 并进行访问限制， 提早控制传染源\"],\"risk\":\"已失陷\",\"ip\":\"\",\"ip_location\":\"\",\"process\":\"/usr/bin/python\",\"process_md5\":\"363ec7cfccb1604140779b51a394f264\",\"process_id\":2356,\"process_user\":\"root\",\"process_command_line\":\"\",\"pprocess\":\"/lib64/libnss_files-2.14.1.so\",\"pprocess_md5\":\"dcc8f971edc9e39837d2b30a904343d6\",\"pprocess_id\":1,\"pprocess_user\":\"root\",\"pprocess_command_line\":\"\",\"process_tree\":\"/usr/bin/python\",\"operation\":null,\"file_path\":\"/root/mvhwnew\",\"result\":\"仅记录\"}",
            "real_samples": "{\"rectime\":1618489628000,\"ds\":\"20210415\",\"hh\":\"20\",\"app\":\"明御主机安全及管理系统\",\"app_version\":\"2.0.16.4\",\"uid\":\"TX1383f7\",\"username\":\"test\",\"uuid\":\"aeab9d8bce39429d531bbfe4b31b769f555babba3ea6433ca52f5f5fb0757a8b\",\"machine_ip\":\"10.50.38.46\",\"type\":\"T_STANDALONE_EXPANSION\",\"event_id\":6002,\"event_str\":\"单机扩展\",\"desc\":\"/usr/bin/python 的运行已放行(514b86a378ddc73a94a4aafbc3aad4df)\",\"suggest\":[\"* 查看渗透工具的上传时间，并查看在这个时间段有哪些服务器对本地服务器进行了访问，这些服务器中可能存在已经被攻击者控制的机器， 对可疑的服务器进行访问限制\",\"* 保存样本并及时删除渗透工具\",\"* 对本机进行访问限制， 防止对内网中的其他服务器进行攻击\",\"* 找出渗透工具指定攻击的服务器， 并进行访问限制， 提早控制传染源\"],\"risk\":\"已失陷\",\"ip\":\"\",\"ip_location\":\"\",\"process\":\"/usr/bin/python\",\"process_md5\":\"363ec7cfccb1604140779b51a394f264\",\"process_id\":2356,\"process_user\":\"root\",\"process_command_line\":\"\",\"pprocess\":\"/lib64/libnss_files-2.14.1.so\",\"pprocess_md5\":\"dcc8f971edc9e39837d2b30a904343d6\",\"pprocess_id\":1,\"pprocess_user\":\"root\",\"pprocess_command_line\":\"\",\"process_tree\":\"/usr/bin/python\",\"operation\":null,\"file_path\":\"/root/mvhwnew\",\"result\":\"仅记录\"}"
        },
        {
            "logtype": "T_TUNEL_CONSTRUCTION",
            "sample": "{\"rectime\":1618541847000,\"ds\":\"20210416\",\"hh\":\"10\",\"app\":\"明御主机安全及管理系统\",\"app_version\":\"2.0.16.4\",\"uid\":\"TX1383f7\",\"username\":\"test\",\"uuid\":\"619c4d322b0d9c7f1f91ee245830c6331c1d4cd608f44b21f4d31a1 1a72fc1 10\",\"machine_ip\":\"10.50.38.161\",\"type\":\"T_TUNEL_CONSTRUCTION\",\"event_id\":6003,\"event_str\":\"隧道搭建\",\"desc\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe 的运行已放行 (禁止隧道代理转发类工具运行(TE))\",\"suggest\":[\"* 查看渗透工具的上传时间， 并查看在这个时间段有哪些服务器对本地服务器进行了访问， 这些服务器中可能存在已经被攻击者控制的机器， 对可疑的服务器进行访问限制\",\"* 保存样本并及时删除渗透工具\",\"* 对本机进行访问限制， 防止对内网中的其他服务器进行攻击\",\"* 找出渗透工具指定攻击的服务器， 并进行访问限制， 提早控制传染源\"],\"risk\":\"低风险\",\"ip\":\"10.11.36.202\",\"ip_location\":\"局域网\",\"process\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe\",\"process_md5\":\"738e878f5ecdf60e0d8cb96dfb5396c6\",\"process_id\":4508,\"process_user\":\"Administrator\",\"process_command_line\":\"\\\\\\\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe\\\\\\\" \",\"pprocess\":\"C:\\\\\\\\Windows\\\\\\\\explorer.exe\",\"pprocess_md5\":\"ac4c51eb24aa95b77f705ab159189e24\",\"pprocess_id\":4640,\"pprocess_user\":\"Administrator\",\"pprocess_command_line\":\"C:\\\\\\\\Windows\\\\\\\\Explorer.EXE\",\"process_tree\":\"explorer.exe(4640) -\\\\u003eagent_win32.exe(4508)\",\"operation\":\"创建进程\",\"file_path\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe\",\"result\":\"已放行\"}",
            "real_samples": "{\"rectime\":1618541847000,\"ds\":\"20210416\",\"hh\":\"10\",\"app\":\"明御主机安全及管理系统\",\"app_version\":\"2.0.16.4\",\"uid\":\"TX1383f7\",\"username\":\"test\",\"uuid\":\"619c4d322b0d9c7f1f91ee245830c6331c1d4cd608f44b21f4d31a1 1a72fc1 10\",\"machine_ip\":\"10.50.38.161\",\"type\":\"T_TUNEL_CONSTRUCTION\",\"event_id\":6003,\"event_str\":\"隧道搭建\",\"desc\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe 的运行已放行 (禁止隧道代理转发类工具运行(TE))\",\"suggest\":[\"* 查看渗透工具的上传时间， 并查看在这个时间段有哪些服务器对本地服务器进行了访问， 这些服务器中可能存在已经被攻击者控制的机器， 对可疑的服务器进行访问限制\",\"* 保存样本并及时删除渗透工具\",\"* 对本机进行访问限制， 防止对内网中的其他服务器进行攻击\",\"* 找出渗透工具指定攻击的服务器， 并进行访问限制， 提早控制传染源\"],\"risk\":\"低风险\",\"ip\":\"10.11.36.202\",\"ip_location\":\"局域网\",\"process\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe\",\"process_md5\":\"738e878f5ecdf60e0d8cb96dfb5396c6\",\"process_id\":4508,\"process_user\":\"Administrator\",\"process_command_line\":\"\\\\\\\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe\\\\\\\" \",\"pprocess\":\"C:\\\\\\\\Windows\\\\\\\\explorer.exe\",\"pprocess_md5\":\"ac4c51eb24aa95b77f705ab159189e24\",\"pprocess_id\":4640,\"pprocess_user\":\"Administrator\",\"pprocess_command_line\":\"C:\\\\\\\\Windows\\\\\\\\Explorer.EXE\",\"process_tree\":\"explorer.exe(4640) -\\\\u003eagent_win32.exe(4508)\",\"operation\":\"创建进程\",\"file_path\":\"C:\\\\\\\\Users\\\\\\\\Administrator\\\\\\\\Desktop\\\\\\\\隧道搭建\\\\\\\\agent_win32.exe\",\"result\":\"已放行\"}"
        }
    ]
}

3、参考子规则的normalize部分示例
[
    {
        "name": "威胁感知事件_categoryName_子规则",
        "sysType": 0,
        "createtime": 1780280197000,
        "source": 0,
        "entities": [
            "日志"
        ],
        "description": "威胁感知事件_categoryName_子规则",
        "normalize": [
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "all"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "accessCode"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "{\"text\":\"10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描\"}"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "action"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "action.text"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1720430531595"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "agentInputTime"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "A-l4RB6KZI0SgILf"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "aggKey"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "攻击者正在对您的服务器 10.249.210.29 进行端口扫描，请及时处理。详情请登录云中心查看。"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "alarmMsg"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "威胁感知事件"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "categoryName"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "2024-07-08"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "day"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "该类事件的报警，说明服务器的TCP端口正在被扫描。建议将进行端口扫描的IP加入到云中心的黑名单。"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "dealSuggestion"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "利用TCP扫描工具检测服务器TCP端口的分配及提供的服务和它们的软件版本。"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "description"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "eventGrade"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1114112"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "eventId"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "2024-07-08 17:22:11"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "eventInputTime"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "0"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "eventType"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "00110000"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "eventUuid"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "TCP端口扫描"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "groupName"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "17"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "hour"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "ifFort"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.29"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "innerIp"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "(局域网)"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "innerIpAddress"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "184144413"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "innerIpLong"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.17"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "ip"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "(局域网)"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "ipAddress"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "184144401"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "ipLong"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "未研判"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "judgeStatus"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "低危"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "levelDesc"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1720430530000"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "localTimestamp"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "logType"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "0524251c18e249f8928c89fc871c2ce7"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "logUuid"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "g01"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "logo"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "{\"extranetIp\":\"10.249.210.29\",\"maxResults\":10,\"onlineStatus\":1,\"osType\":0,\"currentPage\":1,\"operatingSystem\":\"Microsoft Windows Server 2012 R2 Standard Edition 64-bit\",\"uuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\",\"machineName\":\"jtshxtgztw007\",\"intranetIp\":\"10.249.210.29\"}"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.currentPage"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.29"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.extranetIp"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.29"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.intranetIp"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "jtshxtgztw007"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.machineName"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.maxResults"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.onlineStatus"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "Microsoft Windows Server 2012 R2 Standard Edition 64-bit"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.operatingSystem"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "0"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.osType"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "2fbc0442627a9871cb01c4e55b5ca2fb"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machine.uuid"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "2fbc0442627a9871cb01c4e55b5ca2fb"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "machineUuid"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "undefined"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "markName"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1042"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "minute"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "{\"other\":\"80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902\"}"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "object"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "object.other"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    ""
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "operation"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    ""
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "operationDesc"
            },
            {
                "mappings": [],
                "field": "original_log",
                "sim": true,
                "result": [
                    "{\"accessCode\":\"all\",\"action\":{\"text\":\"10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描\"},\"agentInputTime\":\"1720430531595\",\"aggKey\":\"A-l4RB6KZI0SgILf\",\"alarmMsg\":\"攻击者正在对您的服务器 10.249.210.29 进行端口扫描，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"威胁感知事件\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明服务器的TCP端口正在被扫描。建议将进行端口扫描的IP加入到云中心的黑名单。\",\"description\":\"利用TCP扫描工具检测服务器TCP端口的分配及提供的服务和它们的软件版本。\",\"eventGrade\":1,\"eventId\":1114112,\"eventInputTime\":\"2024-07-08 17:22:11\",\"eventType\":0,\"eventUuid\":\"00110000\",\"groupName\":\"TCP端口扫描\",\"hour\":17,\"ifFort\":1,\"innerIp\":\"10.249.210.29\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184144413,\"ip\":\"10.249.210.17\",\"ipAddress\":\"(局域网)\",\"ipLong\":184144401,\"judgeStatus\":\"未研判\",\"levelDesc\":\"低危\",\"localTimestamp\":1720430530000,\"logType\":1,\"logUuid\":\"0524251c18e249f8928c89fc871c2ce7\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.249.210.29\",\"intranetIp\":\"10.249.210.29\",\"machineName\":\"jtshxtgztw007\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2012 R2 Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\"},\"machineUuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\",\"markName\":\"undefined\",\"minute\":1042,\"object\":{\"other\":\"80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902\"},\"operation\":\"\",\"operationDesc\":\"\",\"phase\":1,\"phaseDesc\":\"探测\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":1,\"saveEsTime\":\"2024-07-08 17:22:11\",\"score\":0,\"source\":1,\"sourceDesc\":\"内置规则\",\"sourceIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.17\",\"region\":\"\",\"type\":\"局域网\"},\"standardTimestamp\":1720430530000,\"status\":0,\"subject\":{\"procHash\":\"-1\",\"process\":\"10.249.210.17\",\"type\":\"kernel_event\",\"user\":\"unknow\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.29\",\"region\":\"\",\"type\":\"局域网\"},\"typeName\":\"TCP端口扫描\",\"ucrc\":1100636110,\"unitCode\":\"97c9bbda9d8e4cee8774b5bd3141c2f6\",\"userUuids\":[\"2c9b6f6673e4429e8bc1a7a949a7c993\"]}"
                ],
                "info": null,
                "entity": "日志",
                "required": false,
                "core": false,
                "value": null,
                "index": "original_log"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "phase"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "探测"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "phaseDesc"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "9ec0e44cdbee4bc2a0006b8cad87bf67"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "plateCode"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "zhucema"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "registerCode"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "result"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "2024-07-08 17:22:11"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "saveEsTime"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "0"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "score"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "source"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "内置规则"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceDesc"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "{\"country\":\"局域网\",\"city\":\"\",\"ip\":\"10.249.210.17\",\"region\":\"\",\"type\":\"局域网\"}"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceIpAddress"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    ""
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceIpAddress.city"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "局域网"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceIpAddress.country"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.17"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceIpAddress.ip"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    ""
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceIpAddress.region"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "局域网"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "sourceIpAddress.type"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1720430530000"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "standardTimestamp"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "0"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "status"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "{\"process\":\"10.249.210.17\",\"type\":\"kernel_event\",\"procHash\":\"-1\",\"user\":\"unknow\"}"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "subject"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "-1"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "subject.procHash"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.17"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "subject.process"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "kernel_event"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "subject.type"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "unknow"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "subject.user"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "{\"country\":\"局域网\",\"city\":\"\",\"ip\":\"10.249.210.29\",\"region\":\"\",\"type\":\"局域网\"}"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "targetIpAddress"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    ""
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "targetIpAddress.city"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "局域网"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "targetIpAddress.country"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "10.249.210.29"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "targetIpAddress.ip"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    ""
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "targetIpAddress.region"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "局域网"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "targetIpAddress.type"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "TCP端口扫描"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "typeName"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "1100636110"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "ucrc"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "97c9bbda9d8e4cee8774b5bd3141c2f6"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "unitCode"
            },
            {
                "mappings": [],
                "field": null,
                "sim": null,
                "result": [
                    "[\"2c9b6f6673e4429e8bc1a7a949a7c993\"]"
                ],
                "info": null,
                "entity": null,
                "required": false,
                "core": null,
                "value": null,
                "index": "userUuids"
            },
            {
                "mappings": [],
                "field": "log_type",
                "sim": true,
                "result": [
                    "威胁感知事件"
                ],
                "info": null,
                "entity": "日志",
                "required": false,
                "core": false,
                "value": "",
                "index": "日志类型"
            }
        ],
        "lasttime": 1780280197000,
        "parser": {
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
                    "fields": {
                        "日志类型": "威胁感知事件"
                    },
                    "name": "addFields",
                    "id": ""
                }
            ],
            "subResolver": 1
        },
        "resolverType": "event",
        "deviceType": {
            "id": "1",
            "name": "设备分类",
            "parentId": ""
        },
        "simEntities": [
            "日志"
        ],
        "version": "v1",
        "change": 0,
        "id": "ff17c6f6-5535-4721-bce2-94dec106f7c9",
        "properties": [
            {
                "format": null,
                "name": "日志类型",
                "sim": true,
                "info": null,
                "key": "log_type",
                "entity": "日志",
                "sample": [
                    "威胁感知事件"
                ],
                "type": "object",
                "required": null,
                "core": null
            },
            {
                "format": null,
                "name": "原始日志",
                "sim": true,
                "info": null,
                "key": "original_log",
                "entity": "日志",
                "sample": [
                    "{\"accessCode\":\"all\",\"action\":{\"text\":\"10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描\"},\"agentInputTime\":\"1720430531595\",\"aggKey\":\"A-l4RB6KZI0SgILf\",\"alarmMsg\":\"攻击者正在对您的服务器 10.249.210.29 进行端口扫描，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"威胁感知事件\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明服务器的TCP端口正在被扫描。建议将进行端口扫描的IP加入到云中心的黑名单。\",\"description\":\"利用TCP扫描工具检测服务器TCP端口的分配及提供的服务和它们的软件版本。\",\"eventGrade\":1,\"eventId\":1114112,\"eventInputTime\":\"2024-07-08 17:22:11\",\"eventType\":0,\"eventUuid\":\"00110000\",\"groupName\":\"TCP端口扫描\",\"hour\":17,\"ifFort\":1,\"innerIp\":\"10.249.210.29\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184144413,\"ip\":\"10.249.210.17\",\"ipAddress\":\"(局域网)\",\"ipLong\":184144401,\"judgeStatus\":\"未研判\",\"levelDesc\":\"低危\",\"localTimestamp\":1720430530000,\"logType\":1,\"logUuid\":\"0524251c18e249f8928c89fc871c2ce7\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.249.210.29\",\"intranetIp\":\"10.249.210.29\",\"machineName\":\"jtshxtgztw007\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2012 R2 Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\"},\"machineUuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\",\"markName\":\"undefined\",\"minute\":1042,\"object\":{\"other\":\"80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902\"},\"operation\":\"\",\"operationDesc\":\"\",\"phase\":1,\"phaseDesc\":\"探测\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":1,\"saveEsTime\":\"2024-07-08 17:22:11\",\"score\":0,\"source\":1,\"sourceDesc\":\"内置规则\",\"sourceIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.17\",\"region\":\"\",\"type\":\"局域网\"},\"standardTimestamp\":1720430530000,\"status\":0,\"subject\":{\"procHash\":\"-1\",\"process\":\"10.249.210.17\",\"type\":\"kernel_event\",\"user\":\"unknow\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.29\",\"region\":\"\",\"type\":\"局域网\"},\"typeName\":\"TCP端口扫描\",\"ucrc\":1100636110,\"unitCode\":\"97c9bbda9d8e4cee8774b5bd3141c2f6\",\"userUuids\":[\"2c9b6f6673e4429e8bc1a7a949a7c993\"]}"
                ],
                "type": "object",
                "required": null,
                "core": null
            },
            {
                "format": null,
                "name": "解析规则链",
                "sim": null,
                "info": null,
                "key": "rule_name_list",
                "entity": null,
                "sample": [
                    "[威胁感知事件_categoryName_子规则]"
                ],
                "type": "object",
                "required": null,
                "core": null
            }
        ],
        "parserV2": null,
        "sample": "{\"accessCode\":\"all\",\"action\":{\"text\":\"10.249.210.17(局域网) 对服务器10.249.210.29 进行TCP端口扫描。被扫端口为：80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902。来源：防端口扫描\"},\"agentInputTime\":\"1720430531595\",\"aggKey\":\"A-l4RB6KZI0SgILf\",\"alarmMsg\":\"攻击者正在对您的服务器 10.249.210.29 进行端口扫描，请及时处理。详情请登录云中心查看。\",\"categoryName\":\"威胁感知事件\",\"day\":\"2024-07-08\",\"dealSuggestion\":\"该类事件的报警，说明服务器的TCP端口正在被扫描。建议将进行端口扫描的IP加入到云中心的黑名单。\",\"description\":\"利用TCP扫描工具检测服务器TCP端口的分配及提供的服务和它们的软件版本。\",\"eventGrade\":1,\"eventId\":1114112,\"eventInputTime\":\"2024-07-08 17:22:11\",\"eventType\":0,\"eventUuid\":\"00110000\",\"groupName\":\"TCP端口扫描\",\"hour\":17,\"ifFort\":1,\"innerIp\":\"10.249.210.29\",\"innerIpAddress\":\"(局域网)\",\"innerIpLong\":184144413,\"ip\":\"10.249.210.17\",\"ipAddress\":\"(局域网)\",\"ipLong\":184144401,\"judgeStatus\":\"未研判\",\"levelDesc\":\"低危\",\"localTimestamp\":1720430530000,\"logType\":1,\"logUuid\":\"0524251c18e249f8928c89fc871c2ce7\",\"logo\":\"g01\",\"machine\":{\"currentPage\":1,\"extranetIp\":\"10.249.210.29\",\"intranetIp\":\"10.249.210.29\",\"machineName\":\"jtshxtgztw007\",\"maxResults\":10,\"onlineStatus\":1,\"operatingSystem\":\"Microsoft Windows Server 2012 R2 Standard Edition 64-bit\",\"osType\":0,\"uuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\"},\"machineUuid\":\"2fbc0442627a9871cb01c4e55b5ca2fb\",\"markName\":\"undefined\",\"minute\":1042,\"object\":{\"other\":\"80,23,443,21,22,25,3389,110,445,139,143,53,135,3306,8080,1723,111,995,993,5900,1025,587,8888,199,1720,113,554,256,5910,2022,1310,524,8652,1718,3404,8443,3003,9929,500,2323,82,24444,1719,32775,54328,16000,30951,32782,15742,1900,10621,13722,1062,5222,1165,55056,1151,3476,1862,1201,5802,2492,1068,2967,8082,2601,7911,1037,301,1058,1091,5200,8994,32773,1247,2021,1065,749,1000,27715,5989,8193,32774,2035,7937,3801,50000,2135,981,3269,1461,5190,3323,9009,2004,3914,1110,1700,60020,1057,4444,5903,6009,5988,1234,9102,5902\"},\"operation\":\"\",\"operationDesc\":\"\",\"phase\":1,\"phaseDesc\":\"探测\",\"plateCode\":\"9ec0e44cdbee4bc2a0006b8cad87bf67\",\"registerCode\":\"zhucema\",\"result\":1,\"saveEsTime\":\"2024-07-08 17:22:11\",\"score\":0,\"source\":1,\"sourceDesc\":\"内置规则\",\"sourceIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.17\",\"region\":\"\",\"type\":\"局域网\"},\"standardTimestamp\":1720430530000,\"status\":0,\"subject\":{\"procHash\":\"-1\",\"process\":\"10.249.210.17\",\"type\":\"kernel_event\",\"user\":\"unknow\"},\"targetIpAddress\":{\"city\":\"\",\"country\":\"局域网\",\"ip\":\"10.249.210.29\",\"region\":\"\",\"type\":\"局域网\"},\"typeName\":\"TCP端口扫描\",\"ucrc\":1100636110,\"unitCode\":\"97c9bbda9d8e4cee8774b5bd3141c2f6\",\"userUuids\":[\"2c9b6f6673e4429e8bc1a7a949a7c993\"]}",
        "subResolver": 1,
        "deleted": 0
    }
]