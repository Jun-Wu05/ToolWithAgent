# V2 #270 Run 诊断验收记录

## 自动验证

- 根仓全量 `pytest -q`：通过；生产 Python 源码快照已重新生成并通过一致性检查。
- V2 后端全量 `pytest -q`：224 passed；末次未执行原因投影的诊断定向 7 passed。
- V2 前端单 worker 全量 Vitest：207 passed；末次新增未执行原因展示后诊断定向 6 passed。
- 前端 `npm run lint`：0 error，1 条既有 `FieldChangesWorkspace.tsx` ref 清理警告。
- 前端 `npm run build`：通过。

## 人工浏览器验收

当前工作树：`C:\Users\v-wujun\.codex\worktrees\issue-270-run-diagnostics\toolswithagent`，分支 `codex/issue-270-run-diagnostics`。启动前运行 `git rev-parse HEAD` 和 `git status --short` 核对提交；不要复用旧服务或旧会话。2026-10-27 检查时 8100 和 5173 端口无监听进程。API、Worker 使用同一 `V2_DATA_DIR`，在各自终端从此工作树执行：

```powershell
Set-Location -LiteralPath 'C:\Users\v-wujun\.codex\worktrees\issue-270-run-diagnostics\toolswithagent'
$env:V2_DATA_DIR = (Join-Path (Get-Location) 'tmp/v2-data-270')
$env:V2_MODE = 'development'
$env:V2_WORKER_CONCURRENCY = '1'
$env:PYTHONPATH = "$PWD;$PWD\v2\backend"
Get-NetTCPConnection -LocalPort 8100,5173 -State Listen -ErrorAction SilentlyContinue
```

API 终端：`./.venv/Scripts/python.exe -m uvicorn toolwithagent_v2.main:app --host 127.0.0.1 --port 8100`。
Worker 终端：`./.venv/Scripts/python.exe -m toolwithagent_v2.runtime.worker`。
前端终端：`Set-Location v2/frontend; npm run dev`。确认 API 和 Worker 日志目录属于本工作树，再用全新浏览器会话访问 `http://127.0.0.1:5173`。

1. 以 `dev-user` 建立一个成功 Run、一个失败 Run。切到 `dev-other`，从左侧“Run 诊断”进入独立页面；两条 Run 均应在列表出现，五个 Tab 可切换。成功 Run 显示执行摘要；失败 Run 优先选失败节点和失败调用，概览按钮可定位调用及时间线。
2. 检查输入与输出的请求 ID、版本、参数、耗时、重试序号；Run 详情先返回调用元数据，选中调用后按需读取完整模型请求与响应，长内容不静默截断。日志按实际时间顺序分页，可按级别、步骤、模块和关键字筛选，保留业务消息与异常上下文。
3. 下载 JSON 诊断包；核对只含该 Run 的摘要、时间线、完整模型调用内容、业务日志与产物元数据，不另附上传文件二进制或其他 Run 内容；API Key、Authorization、Cookie、密码等秘密值被遮盖，其余业务内容保留。
4. 用旧 Run 验证未采集的业务日志和模型内容明确显示“未采集”。`dev-user` 可从本人轨迹进入同一详细诊断，猜测他人 Run ID 不能读取；直接访问 `/api/v2/developer/runs` 应为 403。Developer 尝试用户重试、取消等写入应为 403；Admin 的左侧“Run 诊断”复用相同只读内容。

## 当前证据边界

> 2026-11-05 更新：User 可读本人 Run、Developer/Admin 可读授权 Run 的完整业务日志和完整模型请求/响应；终端同样可读。仅 API Key、Authorization、Cookie、密码等秘密值遮盖。日志按时间顺序分页，旧 Run 缺失证据显示「未采集」。

- 新采集的计划开始事件含匿名 Step 清单与依赖；时间线据此标明未执行节点，旧 Run 仍显示“未采集”。执行操作类型可关联到 Step。后续补充的身份采集只记录真实注册的字段 Skill（如 `skills/regex-extract-field`）和真实直连模型工具入口（`agent.tools.pipeline.llm_client._call_llm_direct`）；`model_calls.id` 是单次调用 ID。未经过 Skill/Tool 接缝的模型调用以及旧 Run 仍显示“未采集”，不把 Step 或操作名伪装成 Skill/Tool ID。
- 模型调用记录真实步骤恢复次数；同一次步骤尝试中的不同调用使用相同次数。对显式引用且能在 Run 冻结输入中定位的产物，显示该产物版本；其他输入产物版本显示“未采集”。
- 诊断页按需读取完整请求、响应脱敏文本，诊断包保留同一 Run 实际采集的模型与业务日志内容，不另附上传文件二进制。上一轮浏览器人工验收已由用户确认通过；本次新增字段另待复查。

## 2026-10-28 身份采集续作

- 本轮验收工作树：`D:\Agent\agent_design\toolswithagent\tmp\issue-270-identity-evidence`，分支 `codex/issue-270-identity-evidence`。上文的 `issue-270-run-diagnostics` 启动示例属于上一轮；本轮先核对工作树 HEAD 和端口，再从本目录按 `v2/README.md` 分终端启动 API、Worker 与前端，三者使用新的相同 `V2_DATA_DIR`。
- 用户已确认上一轮 #270 浏览器联合验收通过。本次新增的 Skill/Tool 身份字段仍需用新 Run 复查；旧 Run 不回填。
- 根仓全量 pytest 通过；V2 后端 227 passed；前端 Vitest 214 passed。lint 0 错误、1 条既有 React Hooks 警告；生产构建通过。
- 建议复查正则提取自动生成模式的新 Run：该模型调用应同时显示 `skills/regex-extract-field` 与 `agent.tools.pipeline.llm_client._call_llm_direct`；一般 Agno 模型调用若未经过真实 Skill/Tool 接缝，应继续显示“未采集”。诊断包中的对应 ID 应与页面一致。
