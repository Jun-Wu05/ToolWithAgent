# V2 #270 Run 诊断验收记录

## 自动验证

- 根仓全量 `pytest -q`：通过；生产 Python 源码快照已重新生成并通过一致性检查。
- V2 后端全量 `pytest -q`：221 passed。
- V2 前端单 worker 全量 Vitest：207 passed。
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
2. 检查输入与输出的请求 ID、版本、参数、耗时、重试序号和脱敏内容；Run 详情请求只返回调用元数据，选中调用后才请求其文本，超过 4096 字符的内容应标注“已截断”。日志可按级别、范围、来源、关键字筛选，点击记录可返回相应证据。
3. 下载 JSON 诊断包；核对只含该 Run 的摘要、时间线、调用、日志与产物元数据，没有上传文件正文或其他 Run 内容，且 API Key、Authorization、Cookie 值已脱敏。
4. 用旧 Run 验证无模型调用时显示“未采集”。以 `dev-user` 直接访问 `/api/v2/developer/runs` 应为 403；以 Developer 尝试用户重试、取消等写入应为 403。Admin 的左侧“Run 诊断”应复用相同只读页面。

## 当前证据边界

- 现有类型化进度事件有 Run、Task 与匿名 Step scope，但没有独立 Skill ID、Tool ID 或下游未执行节点清单；页面明确标“未采集”，不从时间邻近关系推断。
- 现有模型调用入口无法稳定给出每次调用的输入产物版本；此字段显示“未采集”。
- 诊断页对每次调用保存最多 4096 字符的请求、响应脱敏文本；诊断包不包含完整上传文件。浏览器人工验收仍待用户执行。
