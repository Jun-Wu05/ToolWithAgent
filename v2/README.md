# ToolWithAgent V2 独立入口

V2 API、Worker、前端与原 Chainlit 入口并行运行。默认端口为 API `8100`、React `5173`；SQLite、上传文件和 Python 环境只放在当前 worktree 的 `tmp/` 中。当前基础切片执行确定性的 `file_ingest` 校验；#265 增加持久化 Run 恢复、取消、重跑及用于故障测试的 Fake Application。真实模型与字段映射业务尚未接入。

## 本地启动（PowerShell）

以下命令均从本 worktree 根目录执行：

```powershell
python -m venv tmp/venv
tmp/venv/Scripts/python.exe -m pip install -e './v2/backend[test]'
$env:V2_DATA_DIR = (Join-Path (Get-Location) 'tmp/v2-data')
$env:V2_MODE = 'development'
$env:V2_WORKER_CONCURRENCY = '1'
$env:PYTHONPATH = 'v2/backend'
```

分别在独立终端（设置相同的 `V2_DATA_DIR` 与 `PYTHONPATH`）启动：

```powershell
tmp/venv/Scripts/python.exe -m uvicorn toolwithagent_v2.main:app --host 127.0.0.1 --port 8100
```

```powershell
tmp/venv/Scripts/python.exe -m toolwithagent_v2.runtime.worker
```

前端从 `v2/frontend` 运行 `npm install`、`npm run dev`。前端开发代理指向 `http://127.0.0.1:8100`。

首次启动 API/Worker 自动执行 Alembic migration。开发模式默认 `dev-user`，可通过 `GET /api/v2/dev/identities` 和 `POST /api/v2/dev/session` 切换测试身份。生产模式不注册这些开发路由，也不会自动选择模拟身份；生产身份接入属于后续切片。

## 当前 API

- `GET /health/live`、`GET /api/v2/me`
- `GET/POST /api/v2/conversations`、`GET /api/v2/conversations/{id}`
- `POST /api/v2/conversations/{id}/messages`（文本投影，不执行自然语言业务）
- `POST /api/v2/conversations/{id}/files`（multipart `file`，返回 file/task/run）
- `GET /api/v2/runs/{id}`、`GET /api/v2/conversations/{id}/events?after=N`（SSE）
- `POST /api/v2/runs/{id}/retry`（可带 `Idempotency-Key`，复制原 Run 的冻结快照）
- `POST /api/v2/runs/{id}/cancel-token` → `POST /api/v2/runs/{id}/cancel`（body 包含一次性 `token`）
- `POST /api/v2/runs/{id}/confirmation-token` → `POST /api/v2/runs/{id}/confirm`（body 包含 `token`、`checkpoint_revision`；重新领 token 可跨刷新恢复）
- `POST /api/v2/admin/runs/{id}/force-stop`（仅 Admin，body 包含非空 `reason`）
- 开发模式专用：`POST /api/v2/dev/conversations/{id}/fake-runs`（`scenario` 为 `success`、`confirm` 或 `fail`；仅用于持久化故障演示）

上传和消息命令接受 `Idempotency-Key`；相同身份、会话、key 和输入返回同一结果，换输入复用 key 返回 `idempotency_key_reused`。上传支持 `.csv`、`.txt`、`.log`、`.json`、`.jsonl`、`.xlsx`、`.b64`，默认上限 20 MiB。文件内容由 Worker 校验类型和哈希，状态从数据库事件表推送；刷新或重启后 REST 查询可恢复。所有 API 文件响应只包含安全元数据，不返回存储路径。

重跑保留历史 Run；当前 Run 的取消或强停立即撤销发布资格，旧 Worker 的迟到结果不能写入 Artifact。等待确认时，checkpoint、确认事项和 SSE 事件在同一事务内保存；确认后由 Worker 从下一动作续跑。Blob 先写 staging 并 fsync、校验哈希、改名为内容寻址文件，再与 Run 状态和事件一起提交数据库。启动对账仅清理超过一小时且无引用的 staging／孤儿文件，避免与正在发布的 Worker 竞争。

## 后端验证

每次运行 pytest 前固定临时目录，避免 Windows 的默认 TEMP 权限和路径问题：

```powershell
New-Item -ItemType Directory -Force 'tmp/system' | Out-Null
$env:TEMP = (Resolve-Path 'tmp/system').Path
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PYTHONPATH = 'v2/backend'
tmp/venv/Scripts/python.exe -c "import os,tempfile; assert tempfile.gettempdir()==os.environ['TEMP']"
tmp/venv/Scripts/python.exe -m pytest -q v2/backend/tests --basetemp=tmp/pytest-v2 -o cache_dir=tmp/pytest-cache
```
