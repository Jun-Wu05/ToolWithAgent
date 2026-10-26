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

## 对话表格摘要（2026-10-22 追加）

字段映射的对话卡从"仅按钮的结果卡"升级为紧凑表格摘要（`v2/frontend/src/ConversationMappingSummary.tsx`）：

- 映射表默认显示当前子规则首页前 8 行（原始字段 / 标准字段 / 状态），可展开至首页 50 行，超过提示"查看完整结果"；有草稿时按草稿叠加展示。
- 修改明细按需展开：修改前取值逐条从正式产物视图按路径查询，不编造旧值；取值失败时对应单元格显示"—"并提示。
- 草稿状态行直接消费会话响应中的草稿摘要（已保存未应用 / 正在应用 / 已应用），普通查看不产生额外请求。
- 行内调整需显式进入：点击后才读取或创建同一草稿并复用既有选择器、占用替换确认、联动范围、保存失败保留与 revision 冲突锁；历史结果卡只读。
- 底部保留查看完整结果、后续处理与下载配置；不新增常驻右栏，不修改后端、数据库或接口结构。

自动验证：前端全量 12 文件 167 项通过；lint 0 errors（仅 FieldChangesWorkspace.tsx:33 既有 warning）；生产构建通过。App 既有隐私断言按新语义更新（对话摘要挂载即拉本人行视图；事件名称标注与警告文本仍不进入普通摘要）。

浏览器复查（前端 5175 / API 8112，合成夹具会话）：浅色与深色 1440px 截图 `summary-light-1440.png`、`summary-dark-1440.png`；修改明细展示 `dst_port 未映射 → 目的端口` 真实前后值；390px 窄屏无文档级横向溢出、表格在卡内滚动；行内调整激活 8 个选择器并打开真实标准字段目录。窄屏与选择器截图因内嵌浏览器截图超时未留存，以 DOM 级检查记录，人工视觉终验仍归 #310。

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

## #409 统一视觉对齐（2026-10-26）

实施分支：`codex/issue-409-visual-alignment`；独立工作树：`D:/Agent/agent_design/twa-409`。原始 V2 基线 `8bb3a66fa5cb2126105e52a4534ad9b9af5522f0`，吸收 master `ff6775d18865e1a23b7a10a09cd2063ada971137` 的同步提交为 `d1df43ce`。master 同步、快照修正与视觉实现分别记录。

### 实现与数据边界

- 任务上下文默认关闭，与执行/产物详情共用唯一 PanelState；桌面 1400px 起并列，任务面板 300px；窄屏覆盖，任务面板最多 320px，提供遮罩、Esc、焦点循环与关闭后焦点返回。
- 上下文和概览复用 TaskFacts，展示当前会话真实输入、产物计数、未应用草稿与最近更新时间。产物与草稿入口定位真实对象，不创建替代数据或执行任务。宽屏打开上下文后隐藏概览重复事实栏。
- 对话、输入和提示区域最大 1000px 居中；概览、结果、轨迹与 Admin 数据区最大 1440px；表格、长代码在容器内滚动。
- 概览下一步按待确认、草稿、失败详情、当前映射、执行进展、无任务返回对话选择，草稿绑定其真实 ID/来源版本，失败绑定其 Run。
- 轨迹维持按需加载，输入引用、输出产物引用与执行 JSON 分区折叠。复制提供成功/失败文字反馈，数据改变或组件卸载后丢弃旧异步反馈。普通用户不新增原始模型/Tool I/O 内容读取。
- 用户与 Admin 身份选择器独立底栏；Admin 补齐窄屏导航入口，选择分区后关闭导航，六区沿用现有 API、授权、审核与强停确认。
- 沿用已有明暗 Token，不修改后端 API、数据库、业务 Prompt 或依赖声明。

### 自动验证记录

原始 V2 根目录基线发现既有源码快照遗漏（log_pattern_store.py 1114→1178 行），补报后通过生成脚本修复。master 同步后的根目录全量、后端 198 项、前端 183 项、lint 与构建通过。新增交互测试先确认缺失行为会失败，再实施；最终结果见本节后续记录。

### 人工明暗验收清单（尚未执行）

使用 CSS 视口 1920、1440、1024、390px，分别检查浅色与深色；使用全新会话，输入真实测试文件后验证，不把空库或历史会话当作当前业务状态。

1. 四 Tab、当前输入和草稿状态切换正常；1000/1440px 内容居中，输入框和提示条对齐，没有页面级横向溢出；长表格/JSON 在局部滚动。
2. 上下文初始关闭。宽屏打开占 300px 并列，关闭后内容恢复；1024/390px 覆盖，面板不超过屏宽，遮罩/Esc 可关闭，Tab/Shift+Tab 不进入背景，焦点返回触发按钮。
3. 上下文和概览展示相同的文件、产物、草稿事实。打开执行/产物详情会替换任务面板；切换会话/身份不残留旧面板或内容。
4. 有待确认、未应用草稿、失败 Run、当前映射、仅执行记录、无执行这六种状态时，“下一步”依次进入对应真实位置；过期来源草稿只允许既有恢复/丢弃规则，不自动换成当前产物。
5. 展开轨迹才读取详情；输入、输出、JSON 默认折叠。分别复制输入引用、输出引用、执行记录，核对内容和成功反馈；剪贴板拒绝时明确提示手动复制。
6. 用户与 Admin 身份底栏在长名称和窄屏下不遮挡选择器。Admin 导航能展开并进入六区；所有表格、弹窗、代码和危险动作确认在明暗两版可读，权限行为不变。

### 本工作树精确启动方式

以下命令仅为人工交接，本次 Agent 未启动服务、Worker 或浏览器。启动前确认 8112/5175 未被旧进程占用；占用时先由用户停止旧服务，不在其他工作树复用已运行服务。

```powershell
Set-Location -LiteralPath 'D:/Agent/agent_design/twa-409'
git branch --show-current
git rev-parse HEAD
git status --short
Get-NetTCPConnection -LocalPort 8112,5175 -State Listen -ErrorAction SilentlyContinue
$env:PYTHONPATH='.;v2/backend'
$env:V2_MODE='development'
$env:V2_DATA_DIR=Join-Path (Get-Location) 'tmp/manual-review-data'
tmp/venv/Scripts/python.exe -m uvicorn toolwithagent_v2.main:app --host 127.0.0.1 --port 8112
```

第二个终端：

```powershell
Set-Location -LiteralPath 'D:/Agent/agent_design/twa-409/v2/frontend'
npm run dev -- --config tmp/vite.review.config.ts
```

本地忽略的 `tmp/vite.review.config.ts` 固定前端 5175、strictPort 与 API 8112 代理。业务任务需要用户在第三个终端从同一工作树、同样的 PYTHONPATH/V2_MODE/V2_DATA_DIR 启动 `tmp/venv/Scripts/python.exe -m toolwithagent_v2.runtime.worker`；真实 Provider 调用由用户控制。预期日志在 `D:/Agent/agent_design/twa-409/agent/logs`，启动后核对新日志路径，不使用旧会话或旧日志作为本次证据。

本次自动测试不能替代 #310 主观明暗终验、真实 Provider 业务验收、双入口与平台导入门禁。PR 合入 V2 不代表发布或切换默认入口。

### 审查与收尾记录

Standards 轴发现 1 项 P2、Spec 轴发现 2 项 P2（焦点问题重合），共 2 个独立问题，均已修复并经两路只读审查复核关闭：

- 窄屏面板排除负 tabIndex、隐藏页及闭合 details 中的焦点候选；包含 summary/链接；覆盖模式切换重新建立焦点边界。新增“两 Tab + 默认页纯文字”正反向循环用例。
- 进入指定映射目标时，在既有未保存编辑保护通过后清除旧字段变更选择。新增“字段变更→概览→草稿/当前映射”参数化回归。

根目录最终全量 988 项通过，V2 独立环境后端全量 198 项通过。前端首轮全量 190 项通过；审查修复后全部 App/面板 58 项通过，lint 零错误（仅 FieldChangesWorkspace.tsx 既有 1 条 warning）、生产构建和 42 项明暗 Token 自检通过。最终前端全量结果另记如下。

如需在其他 checkout 重建本地验收代理，在 v2/frontend/tmp/vite.review.config.ts 写入：

```typescript
import { mergeConfig } from 'vitest/config'
import base from '../vite.config'
export default mergeConfig(base, { server: { host: '127.0.0.1', port: 5175, strictPort: true, proxy: { '/api/v2': 'http://127.0.0.1:8112' } } })
```

最终前端全量：13 个测试文件、192 项全部通过（含审查修复），机器可读结果保存在本工作树 `v2/frontend/tmp/issue-409-final-tests.json`。根目录最终结果为 `tmp/pytest-root-final.xml`（988 项，零失败/错误/跳过）。人工启动配置已通过 Vite loadConfigFromFile 只读解析，确认 host=127.0.0.1、5175 strictPort、API 代理 8112；未启动服务。交付前重新 fetch，确认 master ff6775d1 是本分支祖先，远端 V2 仍为 8bb3a66f；主工作树保持干净。

### 人工验收阻塞修复：字段候选检索缺少 requests（2026-10-26）

用户在本工作树实际运行字段映射，Run 6c1c9aa2-233a-4109-9b87-72ebb6402c26 于 10:48:47 以 field_retrieval_failed 失败。单字段、禁止联网的同环境复现定位到共享 agent/core/embedding_client.py 中 import requests 抛 ModuleNotFoundError；V2 独立环境与包声明均缺该依赖。本次在 V2 运行依赖补充 requests>=2.32，共享客户端和业务规则不变。

新增 test_embedding_runtime.py：在 V2 环境导入真实 requests，仅替换 requests.post 的 HTTP 响应，经过真实共享客户端并断言 4096 维结果与调用模型。原环境红测为 ModuleNotFoundError，按修正声明重装 V2 包后转绿，pip check 通过；不会发出网络模型请求。两路只读审查均通过。

当前本工作树 tmp/venv 已更新（requests 2.34.2）。运行中的 Worker 建议在原终端 Ctrl+C 后，按上文相同工作树和 V2_DATA_DIR 重启；在原会话对失败映射选择“重新执行”，不必重新上传或清空主数据。Agent 未重启服务、未自动调用真实模型。真实在线 Embedding/字段映射仍需用户重试确认，离线测试不声明在线任务已经成功。
`requests` 修复最终验证：根目录 988 项、V2 后端 199 项全量通过，pip check 通过；两轴独立审查无发现。前端源码未改动，沿用本 PR 已通过的 192 项前端回归及构建结果。
