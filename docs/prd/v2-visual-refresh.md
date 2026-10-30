# ToolWithAgent V2 视觉基线刷新（agent-console-suite 融入）

> 历史规格（2026-10-30 标注）：本文记录 2026-10-10 的视觉刷新决策及其实施背景。普通用户新工作台的信息架构、色彩方向与验收以 [前端体验重设计 PRD（Issue #427）](https://github.com/Jun-Wu05/ToolWithAgent/issues/427) 和 `docs/design/v2-visual-baseline.md` §0 为准；本文的旧布局与数值不作为新方向的验收目标。

> 状态：已定稿（2026-10-10 人工逐节确认；布局维持 #263 壳层规则、仅改视觉参数为确认项之一）
> 日期：2026-10-10
> 范围：V2 前端视觉 Token 体系增补、深色主题定稿、组件原语增补；不改变布局结构、交互、角色分层、页面清单与业务流程
> 视觉真源：`docs/design/DESIGN.md`（地位不变）；本 PRD 的决策依据为 `docs/design/agent-console-suite-analysis.md`（已定稿，含 §8.4 确认记录）
> 关联：#263（全局设计基线，刻意未冻结最终视觉）；原型 `docs/design/prototypes/toolwithagent-v2-visual-refresh-workbench.html`、`toolwithagent-v2-visual-refresh-mapping.html` 及明暗截图

## 1. 背景与目标

#263 定稿了 App Shell、状态原语与设计 QA 基线，同时明确"不把现有原型视觉冻结为最终品牌风格"。人工确认的外部原型 agent-console-suite（快照 `a35bdb1`）即期望的最终视觉展示效果；调研证实其 Token 体系与 DESIGN.md 同源（见分析文档 §1）。

本 PRD 定义从当前 V2 视觉现状到该效果的基线刷新范围：

1. 补齐 DESIGN.md 唯一悬空项——**深色主题具体色值定稿**；
2. 吸收 Token 层增强（第三级文字、两档分隔线、状态色映射、具名工具类）；
3. 吸收三个组件原语（任务提示条、单实例上下文抽屉、折叠工具调用块）与状态原语形态；
4. 实现方式沿用 V2 既定方案：React + TypeScript + 零依赖手写 CSS，不引入新框架（D-VA-11）。

## 2. 非目标

- 不改 #263 已确认的布局与壳层规则（左侧导航 / 中间工作区 / 固定 Composer / 单实例右侧抽屉，侧栏 320px、顶栏 56px 保持，D-VA-4）；
- 不改产品体验 PRD 中的角色、页面清单（§14）与状态策略（§15）；
- 不引入 Tailwind、组件库或任何新构建依赖；Token 命名对齐 Tailwind 语义习惯仅为未来迁移预留，不构成引入承诺；
- 本 PRD 只定规格，不修改 `v2/frontend` 代码；实施另立 issue（见 §7）；
- 动画微交互（含 `pulse-dot` 扩散环）维持 DESIGN.md §7 的延后决议（D-VA-8）。

## 3. 决策引用

全部视觉取舍已在分析文档 §8.4 逐项确认（2026-10-10），本 PRD 直接引用其结论，不再重复论证：

| 决策 | 结论 |
|---|---|
| D-VA-1 吸收范围 | 三档全收：Token 层五项 + 组件层三项 + 细节包（快捷入口 chips 仅吸收形态，行为保持"预填不自动执行"） |
| D-VA-2 深色主色 | ≈#5CA3FD |
| D-VA-3 品牌辅色 | #6366F1 / #06B6D4 保留在 DESIGN.md 色板，v2 现有图标点缀用法不变 |
| D-VA-4 壳层尺寸 | 保持 320px / 56px |
| D-VA-5 深色 tint | 参考系（低明度带彩底） |
| D-VA-6 正文主色 | 中性 900 #0F172A |
| D-VA-7 圆角 | 单轨 6px |
| D-VA-8～10 | pulse-dot 延后；列表行高 64px 不动；顶栏职责按产品体验 PRD §14 |
| D-VA-11 前端栈 | 暂不引入框架，零依赖手写 CSS + 具名工具类，留迁移路；无需 ADR |

## 4. Token 层规格变更

规格的完整落点（明暗两版全表、组件原语规格）由配套新设计文档承载（本 PRD 合并后交付）；本节记录决策级变更。

### 4.1 新增 Token（吸收）

| Token | 浅色值 | 用途 |
|---|---|---|
| `--faint` | #94A3B8（中性 400） | 第三级文字：时间戳、次要元数据，与正文/次文字拉开层次 |
| `--border` | #CBD5E1（中性 300） | 控件描边（输入、按钮、选择器） |
| `--border-subtle` | #E2E8F0（中性 200） | 结构分隔线（现有单档 `--line` 拆为两档） |

### 4.2 深色主题定稿（清偿 DESIGN.md"深色过渡值"欠账）

采用分析文档 §2.3 整套（非机械反色：表面三档提亮、主色与语义色提亮降饱和、tint 低明度带彩底、`primary-foreground` 反转为深色文字，落实"反色按钮"策略）。关键值：表面 `≈#0E1116 / ≈#171A20 / ≈#20232A`、主色 `≈#5CA3FD`、tint-primary `≈#262E3D`。完整值表见分析文档 §2.3，将誊入新设计文档。

深色 HEX 为 OKLCH 换算近似值（标 ≈），实现以分析文档记录的 OKLCH 原值为准；`color-scheme` 随主题联动，原生控件（select/滚动条）同步换肤。

### 4.3 调整项

- 正文主色由中性 800 收敛为中性 900（D-VA-6）；次文字对齐参考深一档（#475569）；
- 圆角收敛为单轨 6px（卡片/内嵌/控件统一，D-VA-7）；
- 交互蓝维持 primary-500 #3B82F6（v2 现实现误用 600，回归 DESIGN.md 规格）；
- 新增具名工具类：`focus-ring`（focus-visible 主色描边）、`row-hover`（120ms 过渡至 tint-primary）、`num`（等宽 + tabular-nums，用于耗时/Token 数值列）、`shadow-modal`（引用环境阴影）；`::selection` 主色 22% 选区色、thin 滚动条。

### 4.4 状态 → 色映射（吸收，配合状态策略）

`running/generating → info`、`done/succeeded → success`、`waiting/需确认 → warning`、`queued/pending → faint`、`failed → danger`。**颜色之外必须同时显示状态文字**（状态点 + 状态字并存），满足"不只依赖颜色表达状态"的验收要求；映射键与产品体验 PRD §15 状态策略对齐，不新增状态。

## 5. 组件原语增补

| 原语 | 形态 | 落点（page-id） |
|---|---|---|
| StatusDot / StatusText | 状态点 + 状态字，按 §4.4 映射着色 | 全部页面（工作台最近会话、任务、运行记录、映射编辑器状态列） |
| TaskHintBar | Composer 上方三态提示条（running→tint-info / waiting→tint-warning / failed→tint-danger + 右侧动作链接）；无进行中事项不渲染 | `workbench`、`developer-run-detail` |
| ContextPanel + PanelState | 右侧上下文抽屉单实例：`null \| {type:"execution"|"artifact", id}` 判别联合，执行详情与产物详情二选一，关闭恢复工作区宽度 | `workbench`、`developer-run-detail`、`mapping-editor`（抽屉复用） |
| ToolCallBlock | 折叠工具调用块：收起一行（chevron + 状态点 + mono 工具名 + 耗时/Token 右对齐），展开见输入/输出 | `developer-run-detail`（执行详情抽屉） |
| Composer 细节 | 附件 chips 可移除、`focus-within` 主色描边、Enter 发送 / Shift+Enter 换行、底栏左"上传+类型提示"右发送 | `workbench`、`mapping-editor` |
| 快捷入口 chips | 首页任务快捷入口按钮形态（仅形态；点击预填 Composer，不自动执行、不覆盖未发送草稿） | `workbench` 空态 |
| 格式化约定 | `fmtMs`（"—"占零值、ms/s/m s）、`fmtTokens`（k 缩写）全站统一 | 全部页面数值列 |

## 6. 验收标准

1. DESIGN.md §7 人工验收清单全项通过（明暗两版各验一遍）；
2. Token 一致性：`v2/frontend/src/styles.css` 实现值与新设计文档规格表逐项一致，无硬编码色值绕过 Token（既有硬编码在实施时收编）；
3. 状态表达：每个状态呈现均为"颜色 + 文字"并存；深色下主色、语义色对比度不低于参考值实测水平（主色约 7:1）；
4. 布局回归：壳层尺寸、单实例抽屉行为、Composer 行为与 #263 基线一致，仅视觉参数变化；
5. 行为红线：快捷入口不自动执行；执行详情/产物抽屉不常驻挤压主对话区。

## 7. 实施顺序与在途协调

- **硬门槛**：`#266`（字段映射主路径）与 `#275`（PR #300）合并前，不得修改 `v2/frontend`；本 PRD 及配套设计文档为纯文档交付，与在途开发零冲突。
- 实施拆分建议（视觉冻结后另立 issue，走 issue SOP）：
  1. Token 层：styles.css 变量重构（新增/拆档/深色定稿/工具类）；
  2. 组件原语：StatusDot/StatusText、TaskHintBar、ContextPanel、ToolCallBlock 落地；
  3. 页面应用：按 page-id 逐页应用新原语与深色回归；
  4. 明暗双版人工验收（§6）。
- 配套交付：本 PRD 合并后，另起新设计文档（`docs/design/` 下，承载明暗两版全量规格与组件原语规格，DESIGN.md 原文不动并在新文档开头声明权威关系）。

## 8. 风险与边界

- **视觉冻结**：本 PRD 与配套设计文档人工验收前，不开任何 UI 实施 issue、不碰 `v2/frontend`；
- **许可**：参考仓库自身无 LICENSE 文件（同一所有者，建议补一个消除隐患）；本次只吸收 Token 值、命名与交互模式，不逐字复制其代码文本；若后续代码级复用，须单独记录来源、许可证与修改范围（沿用 frontend-reference-analysis.md 口径）；
- **精度**：深色 HEX 为 OKLCH 换算近似，实现与验收以 OKLCH 原值为准，避免二次换算漂移；
- **快照**：参考仓库持续推送中，本 PRD 依据快照 `a35bdb1`（2026-10-10）；若后续原型有重大视觉更新，需人工决定是否重新走一轮增量分析。
