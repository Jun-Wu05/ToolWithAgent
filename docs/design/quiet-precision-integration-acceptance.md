# Quiet Precision 正式接入验证

## 范围与数据边界

分支 `codex/v2-quiet-precision`，基于 `codex/v2-development` 同步 master 后的 `7e4fd71ef54808422dda6f76dc97853c38c8fbba`。master 为 `5c6f017f13e013797c673c6b9b64aa1421712991`。本轮不修改后端业务实现、API、数据库或默认入口。

正式代码复用既有 Conversation / Artifact / Run、SSE、草稿 revision 和服务端占用校验。四 Tab、双主题、224px 导航和表内映射接入真实前端；没有带入原型合成统计、假版本、内存草稿或演示开关。

## 分阶段变更

| 阶段 | 实际变更 | 验证 |
|---|---|---|
| 结构盘点 | 保留 App 真实命令、身份与异步隔离，独立工作树固定基线 | 实施计划、基线全量回归 |
| 基础系统 | styles.css 双主题语义 Token、workbench.css 字体/按钮/输入/表格/布局 | 42 色 Token 检查、build、lint |
| 字段映射 | StandardFieldPicker 搜索/占用/禁用原因/键盘/Esc/上下定位；保留当前筛选编辑行 | 草稿/冲突/保存失败/连续替换/筛选刷新回归与真实 API |
| 工作区 | 四 Tab、双栏概览、真实版本差异、折叠执行记录与复制；跨 Tab 保留编辑器 | App/WorkspaceViews、身份/会话隔离回归 |
| 浏览器 | 1440/1920/1024/390 CSS px × 浅深色 × 4 页 | 32 组尺寸与截图，无页面溢出或输入遮挡 |

## 自动验证

- 前端全量：11 文件、156 项通过。最终差异编码优化后再次运行相关 6 项，窄屏修正后 App 27 项与生产构建通过。
- 根目录全量 pytest：通过。
- 后端隔离全量：179 passed，1 条第三方 Starlette/httpx 弃用警告。
- lint：0 errors，FieldChangesWorkspace.tsx:33 原有 react-hooks/exhaustive-deps warning。
- 两个独立 Review 发现并修复：重叠草稿操作后写覆盖、跨页面入口保护保存失败选择；复核通过。

## master 同步兼容

master `a38f6056`（#394/#396）已将非空威胁模型终态失败改为成功降级到“其他”。两项 V2 旧测试据此更新：模型异常验证新持久化产物与降级值；原子回滚改为在前置枚举成功后注入真正 FAILED StepResult，仍验证旧产物不替换、失败执行不发布产物和异常不泄漏。独立审查确认测试未弱化。

## 浏览器证据与限制

验收端口：前端 `http://127.0.0.1:5175/`，API `http://127.0.0.1:8112/`，数据在工作树 `tmp/ui-review-data`。会话明确标记“本地验收 · 合成输入与真实 API”。输入与初次映射模型输出为本地合成夹具；持久化、查询、候选字段目录、草稿写入、apply Worker、版本内容及 diff 走真实代码。未启动模型 Worker 或调用付费模型。

真实 API 交互验证：占用者提示、Esc 关闭、DOM 方向键/Enter 提交、自动保存、当前筛选行保留和主动刷新移除均通过。窄屏导航与标题间距、发送单行亦复查通过。

本地证据目录：`D:/Agent/agent_design/toolswithagent/tmp/v2-quiet-precision/`，包括 `real-metrics.json`、32 张 `real-<width>-<view>-<theme>.png`、选择器/编辑/版本比较截图与 `real-interactions.json`。对照已批准原型证据：`D:/Agent/agent_design/toolswithagent/tmp/quiet-precision/review.md`。

键盘自动验证使用 DOM KeyboardEvent，未声称物理按键验收。真实模型端到端、平台导入、人工主观视觉验收仍为独立发布门禁；本次没有将 V2 切为默认入口。

## 精确启动命令

```powershell
Set-Location -LiteralPath 'C:/Users/v-wujun/.codex/worktrees/v2-quiet-precision/toolswithagent'
git branch --show-current
git rev-parse HEAD
git status --short
Get-NetTCPConnection -LocalPort 8112,5175 -State Listen -ErrorAction SilentlyContinue
$env:PYTHONPATH='.;v2/backend'
$env:V2_DATA_DIR=Join-Path (Get-Location) 'tmp/ui-review-data'
tmp/venv/Scripts/python.exe -m uvicorn toolwithagent_v2.main:app --host 127.0.0.1 --port 8112
# 第二个终端，同一工作树
Set-Location v2/frontend
npm run dev -- --host 127.0.0.1 --port 5175 --strictPort --config tmp/vite.review.config.ts
```

上述服务已在对应目录启动；勿重复启动同端口。API PID 29336 启动日志已确认，合成夹具执行日志位于该工作树 `agent/logs/app_20261022_151117.log`。本地 tmp 配置与验收数据不会提交。
