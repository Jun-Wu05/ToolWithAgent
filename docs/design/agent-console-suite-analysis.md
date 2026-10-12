# agent-console-suite（Lovable 原型）对比分析

> 分析对象：`D:\Agent\agent_design\agent-console-suite-ref`（[Jun-Wu05/agent-console-suite](https://github.com/Jun-Wu05/agent-console-suite) 本地克隆）
> 快照 commit：`a35bdb1`（Add project README）
> 分析日期：2026-10-10
> 状态：**已定稿**（2026-10-10 人工逐项确认 §8.4 全部 11 项。总定位（人工原话归纳）：agent-console-suite 是最终期望的**视觉展示效果**；实现方式沿用 V2 既定方案（React + TypeScript + 零依赖手写 CSS）以主流方式处理，不引入新框架。DESIGN.md 仍为唯一真源，本文作为其视觉增量的决策依据）
> 关联：DESIGN.md 头部 #263 记录的原型 URL：<https://agent-console-suite.lovable.app/>

## 1. 项目概况与技术栈

该项目是 Lovable 生成的 Agent 工作台原型（README 自述 "Agent Workbench"，Live app 为 agent-console-suite.lovable.app）。README 正文保留了当初给 Lovable 的完整设计提示词：参考 Collect UI 的 Dashboard / Admin Panel / Bot Interface 等类型，目标风格 "Cursor + Linear + ChatGPT + LangSmith"，要求简洁、专业、偏开发者工具、信息密度适中、少渐变、少装饰、不把所有内容做成圆角卡片——与 DESIGN.md「可信的运维台」的宜忌方向高度一致。值得注意：其 `src/styles.css` 头部注释直接写着 `ToolWithAgent — 「可信的运维台」设计系统`，即原型本身就是按 ToolWithAgent V2 设计语言（含 2026-09-20 主题决策）生成的，Token 值与 DESIGN.md 基本同源。

技术栈（`package.json`、`vite.config.ts`、`.lovable/project.json`）：

| 维度 | 选型 | 备注 |
|---|---|---|
| 框架 | React 19.2 + TypeScript 5.8 | TanStack Start 全栈模板 `tanstack_start_ts_current` |
| 构建 | Vite 8.1.5 + `@lovable.dev/vite-tanstack-config` 聚合插件 + nitro（SSR/构建目标） | 包管理用 bun（bun.lock、bunfig.toml） |
| 路由 | TanStack Router 1.170.18，文件路由（`src/routes/` + 自动生成 `routeTree.gen.ts`） | 非 react-router |
| 数据 | TanStack React Query 5.101 | 页面实际不发请求，全部读 `src/lib/mock-data.ts` |
| 样式 | Tailwind CSS 4.2.1（CSS-first `@theme`，无 tailwind.config）+ `tw-animate-css` | 深色用 `@custom-variant dark` |
| UI 库 | shadcn/ui（new-york 风格、slate 基色，`components.json`）全量 46 组件 scaffold | **未被任何页面引用**（见 §3） |
| 图标 | lucide-react 0.575（ISC） | 页面实际使用的唯一第三方 UI 运行时 |
| 表单 | react-hook-form + zod + @hookform/resolvers（scaffold，未使用） | |
| 其他 scaffold | recharts、embla-carousel、react-day-picker、input-otp、vaul、cmdk、react-resizable-panels、date-fns | 均未被页面使用 |

Lovable 生成痕迹：`.lovable/project.json`（模板版本）、`AGENTS.md` 中的 LOVABLE 标记块、`src/lib/lovable-error-reporting.ts`、vite.config.ts 注释。

## 2. 设计 Token 全量记录

来源：`src/styles.css`（Tailwind v4 CSS-first 配置，`@theme inline` 把语义色映射到 CSS 变量）。色值以 OKLCH 原样记录；浅色 HEX 为源文件自带注释，深色 HEX 为换算近似值（标 ≈）。

### 2.1 基础项

| 项 | 值 |
|---|---|
| 字体（正文） | `--font-sans: system-ui, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`（比 DESIGN.md 多 PingFang SC） |
| 字体（等宽） | `--font-mono: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace` |
| 正文规格 | 14px / line-height 1.5；`-webkit-font-smoothing: antialiased` |
| 圆角 | `--radius: 0.375rem`（6px）；sm=radius-2px、md=radius、lg=radius+2px、xl=radius+4px（单轨派生） |
| 选区 | `::selection` = `color-mix(in oklab, var(--primary) 22%, transparent)` |
| 滚动条 | `scrollbar-width: thin; scrollbar-color: var(--border) transparent` |
| 阴影 | 仅 `--shadow-modal`：浅色 `0 12px 32px rgb(15 23 42 / 0.16)`，深色 `0 12px 32px rgb(0 0 0 / 0.5)`；普通卡片无阴影 |

### 2.2 浅色主题（`:root`，默认）

| Token | OKLCH（原样） | HEX（源注释） | 用途 |
|---|---|---|---|
| `--surface-base` | oklch(0.984 0.003 248) | #F8FAFC | 页面底层 |
| `--surface-card` | oklch(1 0 0) | #FFFFFF | 一级内容 / 侧栏 |
| `--surface-inset` | oklch(0.968 0.007 248) | #F1F5F9 | 日志 / 代码 / 次级底 |
| `--surface-modal` | oklch(1 0 0) | #FFFFFF | 浮层 |
| `--foreground` | oklch(0.208 0.042 266) | #0F172A | 主文字（中性 900） |
| `--muted-foreground` | oklch(0.446 0.03 256) | #475569 | 次文字（中性 700） |
| `--faint` | oklch(0.704 0.04 256) | #94A3B8 | 三级文字（时间戳等，中性 400） |
| `--border` | oklch(0.869 0.022 253) | #CBD5E1 | 控件描边（中性 300） |
| `--border-subtle` | oklch(0.929 0.013 256) | #E2E8F0 | 分隔线（中性 200） |
| `--primary` | oklch(0.623 0.214 259) | #3B82F6 | 操作蓝 |
| `--primary-foreground` | oklch(1 0 0) | #FFFFFF | 主按钮文字 |
| `--success` | oklch(0.627 0.17 149) | #16A34A | |
| `--warning` | oklch(0.646 0.153 61) | #D97706 | |
| `--danger` | oklch(0.577 0.245 27) | #DC2626 | |
| `--info` | oklch(0.588 0.158 242) | #0284C7 | |
| `--tint-primary` | oklch(0.972 0.012 251) | #EFF5FE | 选中 / 悬停底 |
| `--tint-success` | oklch(0.963 0.021 155) | #E8F6ED | |
| `--tint-warning` | oklch(0.96 0.021 75) | #FBF1E6 | |
| `--tint-danger` | oklch(0.945 0.021 22) | #FCE9E9 | |
| `--tint-info` | oklch(0.954 0.017 232) | #E6F3F9 | |

另有一组 shadcn 兼容别名（`--color-background`→surface-card、`--color-muted`→surface-inset、`--color-accent`→tint-primary、`--color-sidebar`→surface-base、`--color-ring`→primary、`--color-running`→info 等），仅服务于 46 个 scaffold 组件的类名。

### 2.3 深色主题（`.dark`）

同组变量整体重定义，非机械反色：表面提亮、主色与语义色提亮并降饱和、tint 变为低明度带彩底、`primary-foreground` 反转为深色文字（落实 DESIGN「反色按钮」策略）。

| Token | OKLCH（原样） | HEX（换算近似） |
|---|---|---|
| `--surface-base` | oklch(0.176 0.011 266) | ≈#0E1116 |
| `--surface-card` | oklch(0.216 0.013 266) | ≈#171A20 |
| `--surface-inset` | oklch(0.256 0.014 266) | ≈#20232A |
| `--surface-modal` | oklch(0.256 0.014 266) | ≈#20232A |
| `--foreground` | oklch(0.955 0.008 256) | ≈#EDF0F6 |
| `--muted-foreground` | oklch(0.72 0.02 256) | ≈#9DA5B1 |
| `--faint` | oklch(0.56 0.022 256) | ≈#6C7582 |
| `--border` | oklch(0.34 0.016 266) | ≈#343840 |
| `--border-subtle` | oklch(0.29 0.014 266) | ≈#282B33 |
| `--primary` | oklch(0.71 0.15 255) | ≈#5CA3FD |
| `--primary-foreground` | oklch(0.16 0.03 266) | ≈#070D1A |
| `--success` | oklch(0.73 0.16 152) | ≈#46C473 |
| `--warning` | oklch(0.79 0.14 78) | ≈#EBAE42 |
| `--danger` | oklch(0.68 0.19 25) | ≈#F75D59 |
| `--info` | oklch(0.72 0.13 238) | ≈#46AFEC |
| `--tint-primary` | oklch(0.3 0.03 262) | ≈#262E3D |
| `--tint-success` | oklch(0.31 0.05 155) | ≈#193825 |
| `--tint-warning` | oklch(0.32 0.05 75) | ≈#422F13 |
| `--tint-danger` | oklch(0.31 0.06 22) | ≈#4A2322 |
| `--tint-info` | oklch(0.31 0.04 235) | ≈#1B3442 |

### 2.4 动效与工具类（`@utility`）

- `focus-ring`：focus-visible 时 2px 主色 45% 外描边 + 主色边框（输入、按钮、列表行共用）。
- `row-hover`：120ms ease 背景过渡，hover 变 `--tint-primary`。
- `num`：等宽字体 + `font-variant-numeric: tabular-nums`（数字 / 标识符对齐）。
- `shadow-float`：引用 `--shadow-modal`。
- `pulse-dot`：运行中状态点的 1.6s `ping-ring` 扩散环（唯一动效）。

许可说明：色值、Token 命名与数值关系本身不构成受版权保护的表达，直接借值无许可风险；若逐字复制 `styles.css` 代码文本，则受仓库许可约束（见 §6）。

## 3. 组件清单（标准件 vs 自定义件）

### 3.1 shadcn 标准件（`src/components/ui/`，46 个，均为脚手架死代码）

accordion、alert-dialog、alert、aspect-ratio、avatar、badge、breadcrumb、button、calendar、card、carousel、chart、checkbox、collapsible、command、context-menu、dialog、drawer、dropdown-menu、form、hover-card、input-otp、input、label、menubar、navigation-menu、pagination、popover、progress、radio-group、resizable、scroll-area、select、separator、sheet、sidebar、skeleton、slider、sonner、switch、table、tabs、textarea、toggle-group、toggle、tooltip。

经 findstr 全量检索，`src/routes/`、`src/components/workspace/`、`src/lib/` 无任何文件 import `@/components/ui`；抽查 `button.tsx` 为未修改的 shadcn new-york 原版。这 46 个组件连同 recharts、carousel、date-picker 等依赖只随模板进来，页面完全不用。

### 3.2 自定义业务组件（`src/components/workspace/`，实际 UI 全部在此）

| 文件 | 要点 |
|---|---|
| `Shell.tsx` | 左侧 240px 侧栏（品牌块、「新对话」按钮、5 项主导航、「最近」4 条带状态点）+ 48px 顶栏（仅主题切换）+ 主区；`row-hover`/`tint-primary` 选中态 |
| `ui.tsx` | 轻量原语全集：StatusDot/StatusText（状态→色映射 + 中文状态字）、Tag/Badge/Kbd/EmptyState/Spinner、Button（cva：primary/secondary/outline/ghost/text/danger × sm/md/icon）、PanelHeader、Metric、Field（220px 标签列+hint 的设置行）、Input/Select/Switch（原生控件换肤）、SectionTitle、CodeBlock |
| `Composer.tsx` | 卡片式输入区：附件 chips 区 + 3 行 textarea（Enter 发送 / Shift+Enter 换行）+ 底栏（左「上传文件」ghost 按钮 + 文件类型提示，右主色发送）；`focus-within` 主色描边 |
| `TaskHintBar.tsx` | Composer 上方三态提示条：running→tint-info、waiting→tint-warning、failed→tint-danger，右动作链接（查看执行详情/去确认） |
| `ContextPanel.tsx` | 384px 右侧上下文抽屉，标题+关闭+内容；`PanelState = null | {type:"execution"|"artifact", id}` 保证单实例 |
| `theme.tsx` | ThemeToggle + 防闪白初始化脚本（见 §5） |

`src/routes/runs.$runId.tsx` 内还有两个页面级复合块：ExecutionDetail（步骤元信息 + ToolCallBlock 列表 + 可折叠「执行计划原文」JSON）与 ToolCallBlock（chevron + 状态点 + mono 工具名 + 耗时/Token 右对齐，展开输入/输出 CodeBlock）。

## 4. 页面清单与布局

路由：TanStack 文件路由，`src/routes/__root.tsx` 为唯一壳（Sidebar + 顶栏 + Outlet + 404/错误组件 + QueryClientProvider）。

| 路由 | 文件 | 布局概括 |
|---|---|---|
| `/` 对话工作台 | `index.tsx` | 居中 max-w-3xl 单列。空态=标题+副标题+4 个建议 chips+「最近运行」3 条列表；有消息=用户气泡（muted 底、右对齐、80% 宽）+ Agent 纯文本流。底部 TaskHintBar + Composer |
| `/runs` 运行记录 | `runs.index.tsx` | max-w-5xl；状态过滤 chips（全部/运行中/等待确认/失败）；卡片内表格：任务（标题+intent 标签）/状态/耗时（tabular 数字）/开始时间；行 hover |
| `/runs/$runId` 运行详情 | `runs.$runId.tsx` | 三栏：左 256px 步骤时间线（状态点+名称+状态字）；中 max-w-3xl 对话列（头部=标题+状态+暂停/重新运行/执行详情，消息流含产物文件 chips，底部 TaskHintBar+Composer）；右 384px ContextPanel 按需二选一（执行详情 / 文件详情 dl+下载） |
| `/agents` | `agents.tsx` | 左 256px Agent 列表（状态点+名称+24h 运行数，次行成功率/p50）+ 右表单：启用 Switch、3 格指标条（gap-px 分隔）、Field 行（模型/Provider/Temperature/Prompt 路径/可用工具标签/最大重试）、保存/重置 |
| `/artifacts` | `artifacts.tsx` | 头部（标题+搜索框+批量导出）+ 类型过滤 chips + 全宽表格（图标+mono 名称/类型标签/状态/来源 Run 链接/大小/生成时间） |
| `/settings` | `settings.tsx` | 左 208px 分区锚点导航 + 右五分区（模型通道/Embedding/向量库/执行/追踪与日志）Field 行式表单 + 保存/恢复默认 |

数据全部来自 `src/lib/mock-data.ts`：runs（7 条）、steps（6 步，含 6 个 toolCall）、artifacts（8 条）、agents（3 个）、activity；领域词汇与 ToolWithAgent 对齐（PlannerAgent / FieldMappingAgent / ThreatAgent、run_* ID、字段映射/威胁类型/枚举/日志解析意图、SiliconFlow/DeepSeek、Qwen3-Embedding-8B、ChromaDB 集合名）。

### 4.1 与 PRD §14 八页清单的映射

| PRD page-id | 原型对应 | 差异 |
|---|---|---|
| `workbench` | `/` | 近似；但建议 chips 点击即发送（PRD/DESIGN 要求预填不自动执行） |
| `runs` | `/runs` | 近似；缺失败摘要、取消/重跑入口 |
| `developer-run-detail` | `/runs/$runId` | 形态接近（时间线+ToolCall+计划原文），但无角色分层，普通用户也看到全部技术细节 |
| `tasks` / `mapping-editor` / `field-changes` | 无 | 原型没有任务页、映射结果编辑器、字段变更预览 |
| `app-shell`（角色分层） | `__root.tsx` + Shell | 原型无角色概念，5 项导航对所有人可见 |
| （原型独有） | `/agents`、`/artifacts`、`/settings` | V2 页面清单之外：Agent 配置、系统设置归 Admin/Developer 域；独立 Artifacts 页与「产物留在消息流+右侧抽屉」决策冲突（frontend-reference-analysis.md §8.5） |

## 5. 深色模式机制

- **class 切换 + 本机记忆，无 next-themes**：`ThemeToggle`（`theme.tsx`）切换 `<html>` 的 `.dark` class 并写 `localStorage["twa-theme"]`；默认浅色。
- **防 FOUC**：`__root.tsx` 的 `shellComponent` 在 `<head>` 内联 `THEME_INIT_SCRIPT`（读 localStorage、首帧前加 class），SSR 下不闪白。
- **Tailwind v4 挂接**：`@custom-variant dark (&:where(.dark, .dark *))`，使 `dark:` 变体跟随 class 而非媒体查询。
- **原生控件联动**：`html`/`html.dark` 切换 `color-scheme: light/dark`。
- 机制与 DESIGN.md「V2 主题决策（2026-09-20）」逐条吻合（默认浅色、本机记忆、两套主题共享语义 Token、非机械反色）。

## 6. 许可证与第三方风险

| 对象 | 许可 | 风险判断 |
|---|---|---|
| 仓库自身 | **无 LICENSE 文件**（根目录仅 .gitignore/.prettierignore/.prettierrc/bunfig.toml/components.json 等） | 默认「保留所有权利」。仓库属 Jun-Wu05（与 ToolWithAgent 同一所有者，README 自述 Lovable 生成、"Full ownership"），自用无障碍；若要把代码并入将来开源的 ToolWithAgent，需先给该仓库补 LICENSE |
| shadcn/ui 组件源码 | MIT | 复制组件文件时需在分发物保留上游版权声明；本分析未复制 |
| @radix-ui/react-*（24 个包） | MIT | 宽松，无传染 |
| lucide-react | ISC | 页面实际使用的唯一第三方 UI 库；分发需附带 ISC 声明 |
| tailwindcss / @tailwindcss/vite / tw-animate-css | MIT | |
| class-variance-authority / clsx / tailwind-merge | MIT | |
| cmdk / sonner / vaul / embla-carousel-react / react-day-picker / input-otp / react-resizable-panels / recharts / react-hook-form / @hookform/resolvers / zod / date-fns / @tanstack/* / react / react-dom / vite / nitro | 均为 MIT | 全部宽松许可，无 GPL/AGPL 类传染 |

结论：依赖面无传染性许可；真正的风险点只有两个——仓库自身缺 LICENSE（同所有者，补一个即可消除），以及若逐字复制 scaffold 组件需保留 MIT 声明。页面实际用到的自写 `workspace/` 组件几乎不含第三方代码。参考方式建议延续 frontend-reference-analysis.md 的口径：本调研只形成设计决策，不引入第三方代码；后续任何代码级复用单独记录来源、许可证、修改范围。

## 7. 与 DESIGN.md 的 Token 对照表

对照三方：参考仓库 `styles.css` ↔ DESIGN.md（定稿基线）↔ `v2/frontend/src/styles.css`（现实现 8 变量：--base/--panel/--inset/--text/--muted/--line/--blue/--select，data-theme=dark 覆盖）。

| 参考 Token | light / dark HEX | DESIGN.md 对应 | v2 现实现对应 | 关系 |
|---|---|---|---|---|
| `--surface-base` | #F8FAFC / ≈#0E1116 | surface-base #F8FAFC（深色延后） | --base #f8fafc / dark #0f172a | 同义（light 同值；dark 取向略异：参考蓝黑 #0E1116 vs #0f172a） |
| `--surface-card` | #FFFFFF / ≈#171A20 | surface-card #FFFFFF | --panel #fff / #192437 | 同义 |
| `--surface-inset` | #F1F5F9 / ≈#20232A | surface-inset #F1F5F9 | --inset #f1f5f9 / #243248 | 同义 |
| `--surface-modal` | #FFFFFF / ≈#20232A | surface-modal #FFFFFF | 无（浮层直接 --panel+阴影） | DESIGN 已定义、参考已落地、v2 未单列 |
| `--foreground` | #0F172A / ≈#EDF0F6 | 色板中性 900 | --text #1e293b（中性 800）/ #e9eef6 | 近似：正文主色取 900 还是 800 需定 |
| `--muted-foreground` | #475569 / ≈#9DA5B1 | 色板中性 700 | --muted #64748b（中性 500）/ #a7b5c9 | 近似：参考深一档 |
| `--faint` | #94A3B8 / ≈#6C7582 | 无对应文字 Token | 无 | **参考独有**（第三级文字） |
| `--border` | #CBD5E1 / ≈#343840 | 无（数据密集线用 neutral-200） | --line #e2e8f0 / #334155 | 近似：参考把控件描边定在 300 |
| `--border-subtle` | #E2E8F0 / ≈#282B33 | neutral-200 细分隔线 | --line（同值） | 同义异名 |
| `--primary` | #3B82F6 / ≈#5CA3FD | primary-500 #3B82F6（深色延后） | --blue #2563eb（600）/ #93c5fd | 近似：v2 交互蓝定 600，参考与 DESIGN 定 500 |
| `--primary-foreground` | #FFFFFF / ≈#070D1A | 主按钮白字；深色「反色按钮」 | 白字硬编码 | 同义（dark 反转值是参考落地） |
| `--success/-warning/-danger/-info` | #16A34A/#D97706/#DC2626/#0284C7 | semantic-* 四色同值 | 硬编码同值 | 同义 |
| `--tint-primary` | #EFF5FE / ≈#262E3D | primary-tint-8 #EFF5FE | --select #eff5fe / #233c61 | 同义（dark tint 明度策略不同） |
| `--tint-success/-warning/-danger/-info` | #E8F6ED/#FBF1E6/#FCE9E9/#E6F3F9 | 叠色对照表 4 项同值 | 仅 feedback.error #fce9e9、feedback.notice #e6f3f9 两处硬编码 | 同义；v2 覆盖不全 |
| `--shadow-modal` | 0 12px 32px rgba(15,23,42,.16) | 环境阴影同值 | .drawer 硬编码同值 | 同义 |
| `--radius` 0.375rem | 6px 单轨 | 主按钮 6px、卡片 8px 双轨 | 6px/8px 硬编码 | 近似 |
| `--font-sans` / `--font-mono` | 见 §2.1 | §3 字体栈 | :root font-family | 同义微差（参考多 PingFang SC、SF Mono） |
| `focus-ring` / `row-hover` / `num` / `pulse-dot` | §2.4 | 无对应 Token（散见各组件规格） | 散落硬编码（outline #3b82f6、.pulse 等） | **参考独有**（统一工具类表达） |
| `--color-sidebar*` / `--color-ring` / `--color-running` | §2.2 末 | 侧栏用表面差区分；running 归 info | .sidebar 用 --panel | 同义异构（shadcn 兼容别名层） |
| （DESIGN 独有）辅色 #6366F1、第三色 #06B6D4 及各自 10 阶 | 参考完全未用 | §2 色板 | v2 用 #6366f1 做图标点缀 | **DESIGN 独有**；参考的事实是「全站零辅色也成立」 |
| （DESIGN 独有）中性完整 10 阶、24/16 字号阶梯、列表行 64px+3px 指示条 | 参考仅取部分点位 | §2/§3/§5 | 部分实现 | DESIGN 独有规格 |

## 8. 吸收候选 / 不吸收候选 / 存疑待讨论（草案）

立场：DESIGN.md 为真源，只挑亮点融入；以下均为候选，非结论。每项标注来源、理由与影响面（Token 层 / 组件层 / 工程层）。

### 8.1 吸收候选（按价值排序）

1. **深色主题具体色值整套**（§2.3；来源 `styles.css:100-128`）。DESIGN.md 明确「深色 HEX 在深色视觉稿定稿时固化」，这是当前基线唯一悬空项；参考提供了一整套非反转、提亮降饱和、tint 带彩底的深色值，且 dark `primary-foreground` 反转正是「反色按钮」条款的落地。影响面：Token 层（直接填 DESIGN §2/§4 的深色列）。
2. **`--faint` 第三级文字 Token**（`styles.css:77,108`；用法见 `runs.index.tsx` 时间列、`Shell.tsx`「最近」标题）。时间戳、次要元数据与正文二级 muted 拉开层次，信息密度高的运维台受益。影响面：Token 层（补一个变量 + DESIGN §3 信息层级加一行）。
3. **`--border` / `--border-subtle` 两档分隔线**（`styles.css:79-80,110-111`）。正好落实 DESIGN「数据密集边界规则」里「结构分区靠表面色阶、精确阅读控件才用细线」的意图，比现在单档 --line 更可表达。影响面：Token 层。
4. **状态→色映射表 + StatusDot/StatusText 形态**（`ui.tsx:10-62`：running/generating→info、done/succeeded→success、waiting/stale→warning、queued/pending→faint、failed→danger，且「颜色之外必须同时显示状态文字」）。与 DESIGN 宜忌第二条逐字吻合，是 §7 验收清单「状态均有可观察反馈」的最小实现；`pulse-dot` 让 running 不靠文字也能感知。影响面：Token 层（映射表）+ 组件层（两个小组件）。
5. **`@utility` 组合类：focus-ring / row-hover / num / shadow-float**（`styles.css:159-184`）。焦点环、行悬停、tabular 数字在 DESIGN §5 分散规定，收拢成具名工具类可保证全站一致（v2 现在是各处硬编码 outline/hover）。影响面：Token 层（CSS 工具类，v2 单文件 styles.css 可直接加）。`num` 的 tabular-nums 尤其适合耗时/Token 数值列。
6. **TaskHintBar 三态任务提示条**（`TaskHintBar.tsx`；`index.tsx:94-98` 无进行中事项时不渲染）。running/waiting/failed 三色 tint 底 + 右侧动作链接（查看详情/去确认），不遮挡消息流、不占位——DESIGN §5「Composer 上方紧凑任务提示」的直接实现。影响面：组件层。
7. **单实例 ContextPanel + `PanelState` 判别联合**（`ContextPanel.tsx` + `runs.$runId.tsx:34`）。execution 与 artifact 二选一、关闭即恢复宽度，用类型系统而非注释保证「同一时刻只展示一种上下文」（DESIGN app-shell 条款、frontend-reference-analysis §5.2）。影响面：组件层。
8. **ToolCallBlock 折叠工具调用块**（`runs.$runId.tsx:182-219`）。收起时只占一行（chevron+状态点+mono 工具名+耗时/Token 右对齐），展开才见输入/输出 CodeBlock——按需排查、不常驻占空间，契合 Developer 视角执行详情。影响面：组件层。
9. **Composer 结构细节**（`Composer.tsx`）：附件 chips 可移除、focus-within 主色描边、Enter 发送/Shift+Enter 换行、左下上传+类型提示+右下发送的底栏。与 DESIGN「Composer 与首页任务快捷入口」条款几乎逐条对应，v2 现实现已接近，可补 focus-within 描边与附件 chips 形态。影响面：组件层。
10. **fmtMs / fmtTokens 格式化约定**（`mock-data.ts:359-372`：「—」占零值、ms/s/m s、k 缩写）。全站耗时与 Token 展示统一，避免各页各写一套。影响面：组件层（工具函数）。
11. **::selection 主色 22% 选区色 + thin scrollbar + color-scheme 联动**（`styles.css:131-155`）。低成本提升「证据阅读」质感的细节；color-scheme 让深色下原生控件（select/scrollbar）跟上。影响面：Token 层。
12. **首页建议 chips 的按钮形态**（`index.tsx:46-56`）。「已交付能力对应的任务快捷入口」的视觉形态可借鉴；但须把「点击即发送」改为 DESIGN 要求的「预填不自动执行」（见 8.2 第 6 条）。影响面：组件层。

### 8.2 不吸收候选

1. **`/agents` 全局 Agent 配置页**（`agents.tsx`）。把 PlannerAgent/FieldMappingAgent/ThreatAgent、模型、Temperature、Prompt 路径暴露给所有用户，且无角色概念；DESIGN §5 与 PRD §14 明确普通用户不见 Agent 配置，Developer 不得执行业务写操作。影响面：不进入页面清单。
2. **`/settings` 系统配置页内容**（`settings.tsx`：Provider/API Key/并发/Embedding/ChromaDB 路径/保留天数）。属 Admin 域，V2 已定「唯一管理入口 admin 页」；且 API Key 明文输入框等形态需按 V2 安全规格重做。影响面：不进入页面清单。**备注（2026-10-10 人工确认记录）**：其"左锚点分区导航 + Field 行式设置表单"的布局模式不随本次吸收，但留作 #271 Admin 页实施时的布局参考。
3. **`/artifacts` 独立产物页 + 批量导出**（`artifacts.tsx`）。与已定决策冲突：产物在消息流可见、点击后复用右侧抽屉（frontend-reference-analysis §8.5「不新增常驻 Artifact 列」）；批量导出属 DESIGN 禁止的「与业务无关的批量操作」。影响面：不进入页面清单。
4. **shadcn/Radix 46 组件全家桶及其附带依赖**（recharts/carousel/date-picker/drawer/cmdk 等）。在参考仓库本身就是死代码；DESIGN 要求「组件保持浏览器原生行为」，v2 零依赖单文件 CSS 的路线不引入构建链与组件库。影响面：工程层（不引入）。
5. **TanStack Start / React 19 / Tailwind v4 / bun / SSR 技术栈**。V2 已定 React + FastAPI 独立入口与现有实现方式；原型价值在视觉与交互模式，不在工程选型。影响面：工程层（不引入）。
6. **「点击即发送」的快捷入口行为**（`index.tsx:51` onClick 直接触发 send）。违反 DESIGN「快捷入口不自动执行、不覆盖未发送草稿」。影响面：行为层（形态可吸收、行为须改造，见 8.1 第 12 条）。
7. **mock 领域文案直接照搬**（`mock-data.ts` 中 SiliconFlow/DeepSeek/Qwen3/ChromaDB 等真实产品名与 `agentic` 措辞）。真实 UI 文案以 V2 产品规格与状态策略为准，原型 mock 仅是占位。影响面：文案层。

### 8.3 存疑待讨论

1. **深色 `--primary` 取值**：参考 ≈#5CA3FD（较饱和）vs v2 现值 #93C5FD（blue-300，较浅）。饱和蓝在深底上对比更强，浅蓝更接近现有实现观感。Token 层。
2. **深色 tint 明度策略**：参考 tint L≈0.30–0.32（≈#262E3D，低明度带彩底）vs v2 --select dark #233C61（更深更蓝）。两种取向都成立，需并排看效果。Token 层。
3. **正文主色取中性 900 还是 800**：参考 #0F172A vs v2 #1E293B（DESIGN 色板两者皆有）。Token 层。
4. **圆角单轨 6px 还是 6/8 双轨**：参考统一 6px（含卡片），DESIGN 规定卡片 8px、内嵌 6px。Token 层。
5. **`pulse-dot` 是否属于被延后的「动画微交互」**：DESIGN §7 将动画微交互延后，宜忌只禁「弹跳动画」；1.6s 扩散环是否放行需讨论。Token/组件层。
6. **侧栏 240px、顶栏 48px** vs DESIGN 侧栏 320px、顶栏 56px：参考更紧凑（信息密度取向），DESIGN 更宽敞（阅读取向）。Token 层（尺寸规格）。
7. **辅色 #6366F1 / 第三色 #06B6D4 的去留**：参考仓库全站零辅色也成立，v2 现实现仅用 #6366f1 做文件图标点缀。是降级为「按需点缀」还是维持 DESIGN 色板地位，需讨论。Token 层。
8. **表格行高**：参考 runs 表 56px（h-14）/artifacts 40px（h-10）vs DESIGN 列表行最小 64px。运维台密度取向需定。组件层。
9. **顶栏职责**：参考顶栏 48px 只放主题切换，页面标题在内容区；v2 顶栏 79px 承载标题+副标题。两种信息架构。组件层。
10. **Tailwind v4 `@theme inline` 的 Token 组织方式**：语义命名与别名层（shadcn 兼容）设计得好，但若 v2 维持零依赖单文件 CSS，只能借鉴命名法不能借鉴机制。工程层。

### 8.4 待决表（建议值，待人工逐项确认）

以下为 2026-10-10 对话中提出的建议值；在人工确认前仅作为原型制作与后续 PRD 草稿的工作假设，任何一项都可推翻。编号 D-VA-n 供讨论引用。

| 编号 | 议题 | 选项 | 建议值 | 状态 |
|---|---|---|---|---|
| D-VA-1 | 吸收范围 | A. 仅 Token 层五项（§8.1 1-5）；B. +组件层三项（§8.1 6-8）；C. +细节包（§8.1 9-12） | B（Token 五项 + 组件三项全收；细节包待原型看效果再定） | **已确认 → C**（三档全收，2026-10-10） |
| D-VA-2 | 深色 `--primary` | ≈#5CA3FD（参考值，饱和）/ #93C5FD（v2 现值，浅） / #3B82F6 不变 | ≈#5CA3FD（深底对比约 7:1，与浅色连续性最好） | **已确认 → ≈#5CA3FD**（2026-10-10） |
| D-VA-3 | 辅色 #6366F1 / 第三色 #06B6D4 去留 | 保留 DESIGN 色板 / 移除只留主色 / 降级为装饰色注记 | 保留在色板（v2 已用辅色做图标点缀；参考未用 ≠ 不能用） | **已确认 → 保留在色板**（2026-10-10） |
| D-VA-4 | 壳层尺寸 | DESIGN 320px/56px / 参考紧凑 240px/48px | 保持 DESIGN 现值（#263 已确认壳层规则，只改视觉参数不动布局尺寸） | **已确认 → 保持 320/56**（2026-10-10） |
| D-VA-5 | 深色 tint 明度策略 | 参考系 ≈#262E3D 起（低明度带彩底） / v2 现值 #233C61 系（更深更蓝） | 参考系（与 §8.1-1 深色整套同源，避免拼凑两套取向） | 默认生效（见确认记录） |
| D-VA-6 | 正文主色 | 中性 900 #0F172A（参考） / 中性 800 #1E293B（v2 现值） | 900（DESIGN 未明文规定档位时对齐参考；信息密度台下更深一档可读性更好） | 默认生效（见确认记录） |
| D-VA-7 | 圆角 | 单轨 6px（参考） / 6/8 双轨（DESIGN：卡片 8、内嵌 6） | 单轨 6px（更简；若人工偏爱卡片 8px 层次感则保留双轨） | 默认生效（见确认记录） |
| D-VA-8 | `pulse-dot` 扩散环 | 放行（参考唯一动效） / 归入延后的动画微交互 | 归入延后（维持 §7 延后决议；原型中不做） | 默认生效（见确认记录） |
| D-VA-9 | 表格行高 | DESIGN 列表行最小 64px / 参考 56px（runs）/40px（artifacts） | 64px 不动（PRD 现规格；参考为密度取向的另一选择） | 默认生效（见确认记录） |
| D-VA-10 | 顶栏职责 | PRD §14 现状（页面标题在内容区，顶栏仅主题切换） / 参考同现状 | 按 PRD 不动 | 默认生效（见确认记录） |
| D-VA-11 | Tailwind `@theme` Token 组织法 | 借鉴命名法不引机制 / 引入 Tailwind v4 | 延后至阶段 2「前端栈决策」一并定（与是否引入 UI 框架同一议题） | **已确认 → 暂不引入**（2026-10-10，见确认记录） |

确认记录（2026-10-10，对话逐项批复）：

- **总定位**（人工确认）：agent-console-suite 是**最终期望的视觉展示效果**；实现方式沿用 V2 既定方案（React + TypeScript + 零依赖手写 CSS）以主流方式处理，不引入新框架。

- **D-VA-1 → C**：三档全收——Token 层五项 + 组件层三项 + 细节包（§8.1 9-12）。其中第 12 项「快捷入口 chips」仅吸收视觉形态，行为按 §8.2-6 改造为"预填不自动执行"。
- **D-VA-2 → ≈#5CA3FD**：人工确认（深底对比约 7:1）。
- **D-VA-3 → 保留在 DESIGN.md 色板**：人工确认；v2 现有辅色图标点缀用法不变。
- **D-VA-4 → 保持 320px / 56px**：人工确认；#263 已定壳层规则不变，本次只改视觉参数。
- **D-VA-5 ～ D-VA-10 → 按建议默认值生效**：2026-10-10 对话中已公布默认值并请人工过目（可推翻），人工对四项主决策作答且未对默认值提出异议；具体取值见上表"建议值"列。后续 PRD 定稿前如需推翻仍可修改。
- **D-VA-11 → 暂不引入框架**：人工确认（2026-10-10 对话，含可维护性对比与市面案例讨论）。v2/frontend 维持零依赖手写 CSS + TypeScript 现栈；本次吸收时将 Token 命名对齐 Tailwind 语义习惯（`--surface-*`/`--tint-*` 分层）并补具名工具类（focus-ring/row-hover/num），为未来引入预留平滑迁移路。不引入则不新增 ADR；若后续推翻本决定引入 Tailwind v4，需新增 ADR 并接受样式层全量重写。

## 9. 来源

- 本地快照：`D:\Agent\agent_design\agent-console-suite-ref` @ `a35bdb1`
- `package.json`、`README.md`、`components.json`、`vite.config.ts`、`.lovable/project.json`、`AGENTS.md`
- `src/styles.css`、`src/router.tsx`、`src/routes/__root.tsx` 及 6 个页面路由、`src/components/workspace/`（Shell/ui/Composer/TaskHintBar/ContextPanel/theme）、`src/lib/mock-data.ts`、`src/components/ui/`（46 个 scaffold）
- 对照基线：`docs/design/DESIGN.md`（含头部 #263 原型 URL）、`v2/frontend/src/styles.css`、`docs/prd/toolwithagent-v2-product-experience.md` §14、`docs/design/frontend-reference-analysis.md`（行文参照）
- 原型在线地址：<https://agent-console-suite.lovable.app/>
