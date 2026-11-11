# 工作台设计集成验证记录

> 任务 A 接手基线与「预览→生产」对应表。任务 B–E 的对照截图、回归与结论追加在本文件下方。

**人工视觉验收：2026-11-11 用户在本地打开真实工作台逐项查看，确认目前改动全部合格。**

## A1 接手基线（2026-11-11）

- 实施目录：`C:/Users/v-wujun/.codex/worktrees/v2-workbench-redesign/toolswithagent`（设计 worktree）；主目录 master 的 `AGENTS.md` 修改与 `tmp_issue430_body.txt` 未触碰。
- 分支：`codex/v2-workbench-redesign`；HEAD `4870e3a86fbbc1c6ba19b4b16d24380b151733bc`。该 HEAD 等于 `codex/v2-development` 当前 tip（`4870e3a8`，PR #442）：**分支自身尚无提交，全部重设计成果都在未提交改动中**，严禁 reset/clean/整文件回退。
- `git status --short`：修改 7 个文件（`docs/design/v2-visual-baseline.md`、`v2/frontend/src/App.test.tsx`、`App.tsx`、`ConversationTimeline.test.tsx`、`ConversationTimeline.tsx`、`styles.css`、`workbench.css`）；未跟踪：本目录、`TrajectoryLedger.tsx`、`TrajectoryLedger.test.tsx`、`trajectory-preview.tsx`、`trajectory-preview.css`、`trajectory-preview.html`。
- `git diff --stat`：7 files，+79/−33；`git diff --check` 干净。
- 批准基线 `15-chat-running-1440.png` 与预览页 `trajectory-preview.html?chat` 已做像素比对：0/1296000 像素差异（1440×900、无头 Chrome、与 render_implementation.py 同参数），预览未漂移。

## A2 未提交改动内容（全部为本任务输入）

- `styles.css`：`:root` 字号 14→15px；浅/深 Token 换为批准色板（#F5F7F9 / #FFFFFF / #202A33 / #61717D / #315E7A；深色 #18232B / #23313B / #91B4C8 等）。
- `workbench.css`：`.app` 15px；追加轨迹账本样式块（`.trajectory*`）与批准对话样式块（`.timeline` / `.chat-row` / `.message` / `.conversation-content` / `.composer-region`，现行 112–140 行）。
- `App.tsx`：轨迹视图 `ExecutionTrace`→`TrajectoryLedger`；composer-region 由 `is-compact` 类切换改为 `hidden` 属性（轨迹页整块隐藏，不占高度）。
- `ConversationTimeline.tsx`：删除 `chat-avatar` 身份列；actor=user 的全部消息（含文件、操作记录）右对齐。
- `v2-visual-baseline.md`：加指向本目录 README 的注记。
- `App.test.tsx` / `ConversationTimeline.test.tsx` 已随上述行为更新。

## A3 预览→生产元素对应表

| 预览元素（trajectory-preview.html?chat） | 生产元素（App.tsx） | 样式共用 | 差异与处置 |
| --- | --- | --- | --- |
| `.preview-shell` 220px+main 网格 | `.app` + `.sidebar` + `main.workspace` | 否 | 侧栏 224→220px（任务 B） |
| `.preview-sidebar` 品牌/导航/最近会话 | `.sidebar`（brand / new-conversation / nav / recent-list / identity） | 否（预览专属外壳 CSS） | 生产多身份切换、会话状态、移动抽屉——真实功能保留 |
| `.preview-top` 57px 标题行 | `.workspace-header`（含重命名/结果与产物/清空业务数据/主题按钮） | 否 | 高度 56→57px、底色 base→card（任务 B）；真实按钮全保留 |
| `.workspace-tabs`（复用生产类） | `.workspace-tabs` + `.workspace-task-status` | 是 | 生产右侧多任务状态角标（保留） |
| `.conversation-content`>ConversationTimeline | `.conversation-content`>`.conversation-pane`>ConversationTimeline | 是 | 生产多空状态模板/加载态/未应用草稿区（保留） |
| `.preview-body`>TrajectoryLedger | `.workbench-pane`（trace）>TrajectoryLedger | 组件共用 | 容器 padding 20px 27px vs 38px 44px 28px（任务 B 统一） |
| `.composer-region`（TaskHintBar+composer） | `.composer-region`（TaskHintBar+BusinessConfirmation+草稿提示+composer） | 是 | 生产多确认卡/草稿提示（保留，均在对话视图内） |
| 预览 stop/send（内存演示） | stopRun/send（真实 API） | — | 见 A4，演示行为不得带入 |

## A4 预览专属、禁止进入生产

- `trajectory-preview.tsx` 内对 `api.run` / `api.userDiagnosticRun` / `api.userDiagnosticCall` 的模块级替换，及 `run-fixture.json` 导入。
- `previewRun` 合成运行、演示停止按钮（`setStopped`）、演示 `send()`（只改本地内存）。
- 示例文案（「设计预览 · 示例文案」、脱敏会话消息、fixture 字段）。
- `.preview-shell` / `.preview-sidebar` / `.preview-top` / `.preview-tabs` / `.preview-body` 外壳 CSS（仅描述预览框架）。

## A5 已识别待对齐差异（任务 B 工作项）

1. 侧栏 224→220px（桌面主验收尺寸）。
2. 主列底色 base→card：预览 `main` 为白，生产 `.workspace` 现透出 base 底色。
3. `.workspace-header`：min-height 56px / padding 10px 28px / 底色 base → 57px / padding 0 28px / card，内容起点与预览对齐（57+44=101px）；≤750px 窄屏行为保持现状。
4. 轨迹视图容器 padding：`.conversation-content` 在 trace 视图应为 20px 27px（对话视图保持批准的 38px 44px 28px）。
5. 死规则清理：`.composer-region.is-compact*`（App 已改 hidden）、`.chat-avatar`（已删渲染）、`.unlinked-inputs`（无渲染调用；buildTurns 的 unlinked 数据层保留且有测试）。
6. 有意保留的差异：预览 ≤1100px 折叠为 68px 图标栏，生产保留完整侧栏与移动抽屉（真实功能入口不删）；生产头部按钮组、任务状态角标、反馈条为真实功能。

## B 任务 B：真实外壳落实（2026-11-11）

改动（全部在设计 worktree，未提交）：

- `workbench.css`：侧栏 224→220px；`.workspace` 增加 `background:var(--surface-card)`（主列白底，同预览 main）；`.workspace-header` min-height 56→57px、padding 10px 28px→0 28px、底色 base→card；删除死规则 `.composer-region.is-compact*`（4 条）、`.chat-avatar`、`.unlinked-inputs*`；新增 `.composer-region[hidden]{display:none}` 防御规则；新增 `.conversation-content.trace-view{padding:20px 27px}`（窄屏 12px），与预览 `.preview-body` 一致。
- `App.tsx`：`conversation-content` 在 `workspaceTab === 'trace'` 时附加 `trace-view` 类（仅类切换，滚动容器/状态挂载机制不变）。
- 未动：消息关联、Run 关联、产物版本、权限计算、确认流程、映射编辑；`ExecutionTrace`（WorkspaceViews 旧组件）与其测试保留未删（无生产调用，另行处置）。

死选择器复核（生产 TSX/TS 全检索）：`is-compact` 无调用；`chat-avatar` 仅测试文件提及（渲染已删）；`unlinked-inputs` 无渲染调用（`buildTurns` 数据层 `unlinked` 保留，测试覆盖）。

## C 任务 C：同条件对照与真实会话证据（2026-11-11）

**方法**：CDP（Chrome DevTools Protocol）驱动无头 Chrome，`Emulation.setDeviceMetricsOverride` 精确 1440×900 CSS 视口、deviceScaleFactor 1；预览与真实 App 用同一管线截图，公平对照。（仓库脚本 `render_implementation.py` 的 `--virtual-time-budget` 与真实 App 的 SSE 长连接互斥，会无限停摆，故换 CDP。）

**固定数据视觉对照**（真实 App 入口 `/` + 本地 fixture API（8100）注入与批准图同源数据；fixture 仅存在于临时目录与独立进程，不进生产代码、不替换全局 API）：

- `integration-preview-chat-cdp-1440.png` / `integration-chat-running-1440.png`（对照 `15-chat-running-1440.png`）
- `integration-preview-trace-cdp-1440.png` / `integration-trace-no-composer-1440.png`
- 像素结论（同一 CDP 管线互比）：对话区上部与中部 **0/649040 像素差异（0.0%）**——批准的气泡、正文、间距在生产 App 完全一致；差异仅侧栏 4.1%（真实身份区/会话状态 vs 预览简化侧栏）、标题行 4.0%（真实按钮组 vs 预览极简标题）、输入区 0.5%（SSE 真实进度文案「标准字段映射：业务分析 进行中 第 2/2 批」vs 预览硬编码文案）。
- 批准图 vs CDP 管线 sanity 差异 2.78%（两条截图管线的抗锯齿/亚像素差；此前已用与批准图相同管线验证预览 0/1296000 像素差异，基线未漂移）。
- 视觉模型核验对话页 7 项全部符合（气泡右对齐/正文左对齐/无身份列/导航保留/标题页签/完整输入区/无溢出）。

**轨迹页隐藏合同（真实 App，CDP 断言）**：

- `composer-region`：`hidden=true`、`display:none`、高度/宽度 0——不占布局高度。
- 隐藏区域内可见可聚焦控件 0 个；焦点不在隐藏区内。
- 轨迹容器实测 `padding: 20px 27px`（与预览 `.preview-body` 一致）。
- 轨迹页底部带（y830-900）与预览 **0 像素差异**。
- 对话→轨迹→对话往返后草稿逐字保留（React 原生 setter 注入验证）；返回后 composer-region 恢复显示（高 206px）。

**真实测试会话截图**（真实后端 uvicorn+worker，dev 模式，`fake-runs` 与真实文件上传；存为 `integration-real-*.png`）：

| 文件 | 场景与断言 |
| --- | --- |
| `integration-real-confirm-1440.png` | 上传 sample-security.log（file_ingest 成功）+ fake confirm：等待确认提示条、确认卡在对话流程内、文件卡靠用户侧；视觉核验 5/5 符合。fake payload 只有 `message` 字段无 `question`，确认卡文案显示加载占位——dev 演示数据形态限制，非 UI 缺陷（令牌 API 200，按钮可用，真实 proposal 形态由 App 40 项测试覆盖） |
| `integration-real-fail-1440.png` | fake fail（失败 Run 为最新）：`.hint-failed` 提示条 + 「查看失败原因」按钮 |
| `integration-real-success-1440.png` | fake success：完成态对话 |
| `integration-real-artifacts-1440.png` | 头部「结果与产物」打开右侧资源工作区；fake 场景不发布产物，如实显示空态（产物查看/版本/下载语义由 App.test.tsx 既有 mock 测试覆盖） |
| `integration-real-trace-1440.png` | 真实会话轨迹页：2 Run / 6 事件、composer 不存在、内容填满视口（bottom≥895） |
| `integration-real-developer-1440.png` | 经真实 UI 身份下拉切换 developer：清空业务数据/提取日志类型/标准字段映射/确认卡全部消失（只读语义） |

**可用性检查**：1024×900、390×844（窄屏）、1440 深色均截图入档（`integration-chat-1024.png`、`integration-chat-narrow-390.png`、`integration-chat-dark-1440.png`、`integration-trace-1024.png`），`scrollWidth ≤ innerWidth` 断言全部通过（无横向溢出）。

## D 任务 D：回归与全量结果（2026-11-11）

- 定向测试：`ConversationTimeline(8) + App(40) + TrajectoryLedger(2)` = **50 项全过**。
- 构建：`npm run build` 通过（tsc -b + vite build，61.22 kB CSS / 329.58 kB JS）。
- Lint：`eslint .` 仅 1 条警告——`FieldChangesWorkspace.tsx:34` `react-hooks/exhaustive-deps`。来源复核：`request` 是 number 型请求版本计数器（非 DOM ref），cleanup 中 `++request.current` 为「在途响应失效」惯用法，属规则对非 DOM ref 的误报；不修改（修改属行为变更，超出本任务范围）。
- 前端全量（`npm test`，227 项）：第 1 次 3 失败 / 第 2 次 1 失败 / 第 3 次 **17 文件 227 项全过（87.1s）**。失败均为 `MappingDraftIndependent.test.tsx` 的 5000ms 测试超时（并行负载下 5.1s 触线；同文件单独运行 7/7 过、8.4s；失败用例与本轮改动面 CSS+className 无交集），判定为并行资源争用型抖动，非功能回归；按计划未以单文件重跑宣称全量通过，完整套件第 3 次全绿后采信并如实记录方差。
- 根全量 pytest（SOP 命令 `python -X utf8 -m pytest -q --basetemp=.pytest-tmp-workbench-integration`，103 文件 / 1030 用例）：**1030 项全部通过，退出码 0**（进度区 1030 个通过点、无任何失败/错误标记；仅既有 DeprecationWarning）。
- v2/backend 套件：本轮未改任何 Python；真实后端已在实机启动并通过健康检查与会话/上传/确认令牌链路。v2/backend 全套件未重跑（合入前如需可按 README 命令补跑）。
- 生产 Python 未改动，未重生成快照。

