# V2 #412 / #413 / #416 浏览器人工验收

本清单用于本地联合验收；不代表已合入开发线或通过人工验收。

自动验证：根 pytest 1003、V2 后端 216、前端 202 全通过；lint 0 错误（FieldChangesWorkspace.tsx 有一条既有 ref warning）、build 通过。根与后端 JUnit 证据位于本 worktree 的 tmp/acceptance-root.xml 和 tmp/acceptance-backend.xml。

Standards Review：初审发现不完整模型项计数回填异常，红测试复现后修复；复查无实质问题。降级文案判定存在非阻断重复建议。

Spec Review：初审发现纯审计实际入口遗漏及自动改选后降级状态遗漏，均补实际路径红绿测试并修复；复查无剩余需求缺口。

## 版本与启动

- 目录：`D:\Agent\agent_design\twa-412`（复用已准备环境的目录作为联合验收 checkout）。
- 分支：`codex/acceptance-412-413-416`。
- 基线：`c07867c895bfb8805f7d48027e96f74b8278de34`。
- 修复来源：#412 `743d042c773a317292793ddf0daa721c11291839`；#413 `300dda5fd2b2c149142be83a77d83ae2834d6018`；#416 `beac8e3dd224fab728d87c9e285b141dc7404085`。联合分支仅供本地验收，按这些已验证提交组合文件，最终完整 HEAD 随交付消息提供。
- 数据目录：本目录 `tmp\manual-review-412-413-416`，首次启动为空，不复制旧验收数据库。
- 日志目录：本目录 `agent\logs`；确认新日志文件落在该目录，并核对启动终端输出的 Worktree 与 HEAD。
- API：8100；前端：5173；API 与 Worker 必须同时运行。

启动前在 PowerShell 核对：

```powershell
Set-Location -LiteralPath 'D:\Agent\agent_design\twa-412'
git branch --show-current
git rev-parse HEAD
git status --short
Get-NetTCPConnection -LocalPort 8100,5173 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalPort,OwningProcess
```

如已有旧服务监听，先确认并停止旧服务，避免测试错版本。不要直接杀未知 PID。

在两个独立 PowerShell 终端分别执行（脚本只设置本终端环境并以前台方式启动）：

```powershell
& 'D:\Agent\agent_design\twa-412\tmp\start-api-412-413-416.ps1'
```

```powershell
& 'D:\Agent\agent_design\twa-412\tmp\start-worker-412-413-416.ps1'
```

第三个终端启动前端：

```powershell
Set-Location -LiteralPath 'D:\Agent\agent_design\twa-412\v2\frontend'
npm run dev -- --port 5173 --strictPort
```

浏览器打开 `http://127.0.0.1:5173`，使用 `dev-user` 和全新会话。首次运行真实任务前确认 Provider 已配置；不要把密钥贴进验收记录。打开 Developer 工具 Network 观察本机 API 请求即可，不需要切换到尚未交付的 Developer 诊断页。

## #412：日志类型真实计数

分别上传 `tmp\acceptance-samples` 下的 JSON、KV、Header 三个脱敏样例，每个样例使用新会话：

| 样例 | 预期类型计数 | 总有效行 |
|---|---|---|
| counts-json.jsonl | AUDIT=3、IPS=2、RUN_INFO=1 | 6 |
| counts-kv.log | AUDIT=3、IPS=2、RUN_INFO=1 | 6 |
| counts-header.log | AUDIT/6/AUDIT_LOG=3、IPS/4/IPS_LOG=2、RUN_INFO/6/RUN_INFO_LOG=1 | 6 |

1. 文件校验完成后运行“日志类型提取”。JSON/KV 可显式指定 `event_type`；Header 使用自动探测。
2. 检查助手回复与日志解析结果卡：每类数量与上述真实频次一致，不是全部 0；三类计数之和为 6，coverage 为 6/6。
3. 打开分类产物并下载，核对每个 `classification_details[].count` 与回复/卡片一致。
4. 刷新页面后计数不变；切换会话再返回不串数据。
5. 可再用原 KvHeadQiming.xlsx 重跑，按该文件的实际频次核对，不能套用上表的 6 行数字。

若真实 Provider 的格式识别/规则生成先失败，该项记“阻塞”，记录安全错误码与 Run ID；失败运行不算计数验收通过。

## #413：字段映射成功与威胁链异常分开表达

使用原问题的 KvHeadQiming.xlsx，执行标准字段映射，提交本人映射参数。观察自动枚举→威胁类型映射链路：

1. 数字代码来源触发 `threat_mapping_source_context_required` 时，链路明确显示失败/需要补充，不显示整链全部完成。
2. 字段映射结果本身仍成功、可查看和下载；自动威胁链失败不把已完成映射清掉，也不发布链路的部分配置。
3. 对照回复、受保护结果警告和展开的执行轨迹：失败原因和阶段一致，不出现链路失败却在业务说明中宣称成功。
4. 刷新、切换会话再返回，原失败记录和关联输入保留；用户重跑产生新 Run，旧 Run 不被覆盖。
5. 若实际运行落入“其他”降级（包括自动改选后仍全为“其他”），报告应明确说明降级，不能表示已得到确定的具体威胁判断。
6. 有真实语义来源且链路完整成功时，正常完成状态、配置与下载不受影响。

内部 `business_state.current_execution.steps` 的 failed / needs_input / warning / degraded / success 已由自动快照往返测试覆盖，普通用户页面不额外开放内部 Blob。浏览器验收后保留 Run ID，可由 Agent 对本次新数据做只读复核；不要为查看快照放宽权限。旧 Run 的历史快照不迁移，请验证新运行。

## #416：审计事件与威胁判定适用范围

打开包含审计/登录/其他信息级事件和威胁事件的映射结果，展开“事件名称标注”：

1. 表头为“威胁判定来源（仅威胁事件）”“威胁判定结果（仅威胁事件）”。
2. 已判定的审计/信息级行显示“操作/审计事件”，两项威胁判定均为“不适用”；不出现“未确定/未生成”暗示审计事件缺威胁判断。
3. 真正的威胁行保留来源字段和最终威胁类型；真实失败时保留未生成提示，不能被标成“不适用”。
4. 待人工确认的行仍显示未知/待确认，不得被当成已确定的普通事件。
5. 用仅含操作/审计事件的输入单独运行一次：映射成功，不出现“威胁子规则状态异常”或要求重试不适用链路的警告。
6. 验证一个旧信息级产物：页面也能正确标明“不适用”；历史存储内容保持不变。
7. 切换浅色/深色与窄屏，表头可读、表格局部滚动、展开/返回和键盘焦点正常。

## 隐私与记录

- 本人提交的产品/厂商/数据源参数只在本人操作输入记录回看；消息、进度事件不展示日志样例、警告原文、服务器路径或凭据。
- 更换用户后不能读取原用户的结果、样例或下载。
- 每项记录：通过/失败/阻塞、Run ID、版本 HEAD、预期与实际、必要截图；无需重新发送原始业务日志。
- 反馈格式示例：`#412 JSON 通过；#413 Run <id> 刷新后状态不一致；#416 审计行通过，深色窄屏表头需调整`。

PR 正文草稿随代码准备，发布前仍需用户审阅；本轮不启动服务、不操作浏览器、不合并或关闭待验收 issue。
