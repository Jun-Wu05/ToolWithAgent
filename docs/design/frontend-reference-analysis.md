# ToolWithAgent V2 前端参考项目对比分析

> 调研日期：2026-09-18
> 调研对象：[Hermes UI](https://github.com/pyrate-llama/hermes-ui)、[LangGraph React Agent Studio](https://github.com/Ylang-Labs/langgraph-react-agent-studio)、[AI Platform Frontend](https://github.com/mikefelder/ai-platform-frontend)

## 1. 调研目的

本次调研不是选择一套界面直接复制，而是验证 ToolWithAgent V2 的页面结构是否符合 Agent 产品的成熟交互，并寻找可以低风险借鉴的模式。比较重点是普通用户如何完成“上传文件 → Agent 执行任务 → 人工确认 → 获得规则产物”，不是比较模型能力或 Agent 框架性能。

判断标准：

1. 对话是否仍是主入口，而不是普通聊天机器人外壳。
2. 长时间执行是否让用户知道正在做什么、是否需要处理。
3. Tool Call、输入输出和错误是否能按需排查，而不是常驻占用空间。
4. 文件与 Artifact 是否能被发现、预览和追溯。
5. 普通用户与 Developer/Admin 的信息密度是否分开。
6. 实现方式是否适配 V2 的 React + FastAPI 独立入口及现有 Chainlit 共存策略。

## 2. 快速结论

三者适合承担不同参考角色：

| 项目 | 最适合参考的部分 | 对 V2 的参考权重 | 不应照搬的部分 |
|---|---|---:|---|
| Hermes UI | 普通用户工作台、Composer、任务提示、主题、Artifact 面板 | 高 | 单文件前端、功能入口过多、Workspace/Terminal 等非首版能力 |
| LangGraph React Agent Studio | 实时执行时间线、Tool 执行状态、多 Agent 活动反馈 | 中高 | LangGraph 基础设施绑定、直接展示“思考过程”的措辞、多 Agent 先于业务任务 |
| AI Platform Frontend | Chat 与 Agent Flow 分页、节点检查器、Run 分析 | 中 | 普通用户常驻 DAG、云厂商标签、只靠 sessionStorage 持久化 |

推荐组合：普通用户工作台以 Hermes UI 的交互成熟度为主要参考，右侧执行详情吸收 LangGraph Studio 的时间线结构，Developer/Admin 的运行分析页面再选择性吸收 AI Platform Frontend 的 DAG 与节点检查器。

## 3. 产品定位差异

### 3.1 Hermes UI：Agent 日常工作中心

Hermes UI 将聊天、任务、文件、Artifact、日志、技能、定时任务和终端统一到同一应用。官方说明包含可折叠左右栏、可调整栏宽、主题切换、Tool Call 展开、Composer 文件上传、执行中停止/引导、任务看板和动态 Artifact 面板。它最接近“用户每天持续使用的 Agent 工作台”。

对 V2 的意义：普通用户主页面应首先保证对话、输入文件、当前任务和结果产物之间的连续性；系统监控不应反过来主导页面。

### 3.2 LangGraph React Agent Studio：Agent 执行观察台

该项目是 Gemini Fullstack LangGraph Quickstart 的增强分支，前端采用 React、TypeScript、Tailwind CSS 与 Radix UI，强调实时 Streaming、活动时间线、Tool 结果和多个专业 Agent。后端同时依赖 FastAPI、WebSocket、Redis、PostgreSQL 和 LangGraph 运行模型。

对 V2 的意义：其时间线与工具状态适合右侧“执行详情”；其框架绑定和多 Agent 选择不适合成为普通用户理解业务的前置条件。

### 3.3 AI Platform Frontend：多 Agent 编排分析台

该项目明确分成 Chat Page 与 Agent Flow Page。Chat 负责用户输入和结果，Agent Flow 使用 React Flow 展示 Supervisor、专业 Agent 与 Synthesizer 的 DAG；点击节点后在侧栏查看输出和 JSON Payload。

对 V2 的意义：DAG 对 Developer/Admin 排查跨 Agent 问题有价值，但普通用户只需要知道任务步骤、当前状态、失败原因和下一步操作。

## 4. 六个前端维度对比

| 维度 | Hermes UI | LangGraph Studio | AI Platform Frontend | V2 结论 |
|---|---|---|---|---|
| 导航 | 一个工作台承载大量工具，支持折叠侧栏 | Agent 选择与对话为主 | Chat 与 Flow 明确分开 | 普通用户保留工作台、任务、运行记录；管理能力另页 |
| 对话框 | 文件、模型、命令、停止、引导能力完整 | 面向 Streaming Agent 对话 | Chat 页面结构简单 | Composer 固定底部，上传、范围、附件、发送/停止都在此处 |
| 执行详情 | Tool Call 可展开，活动与任务贴近对话 | 实时时间线和 Tool 结果最强 | 通过 Flow 页和节点检查器查看 | 默认关闭右栏；点击“执行详情”后展开时间线 |
| 文件/产物 | 动态 Artifact 面板，可按内容加宽 | 更关注工具过程 | 节点输出和 JSON 较强 | 结果文件在对话内可见；点击后在同一右栏打开产物详情 |
| 主题与密度 | 多主题、左右栏可折叠和调宽 | Tailwind/Radix 现代组件 | 深色导航 + 浅色内容的企业面板 | 浅色默认、支持深浅切换；不增加常驻信息栏 |
| 角色分层 | 同一工具内包含大量高级功能 | 偏开发者/Agent 构建者 | 偏平台运维与编排观察 | 普通用户看摘要；Developer 看 Tool I/O；Admin 看全局运行和配置 |

## 5. 建议直接吸收的交互模式

### 5.1 Composer 上方的当前任务提示

长任务执行中或等待人工确认时，在聊天框上方保留一条窄提示，显示“正在执行什么”或“需要你处理什么”。提示可打开任务或执行详情，但不能遮挡消息，也不另建大型状态卡。

### 5.2 单一上下文右侧栏

右侧栏默认关闭，由用户点击以下入口打开：

- 执行详情：步骤、Tool Call、耗时、输入输出、错误；
- 产物详情：预览、下载、版本、来源；
- Developer 信息：模型、重试、原始 Tool I/O。

同一时间只展示一种上下文，避免执行栏、Artifact 栏和依赖关系栏同时常驻。

### 5.3 结果与证据分离

主对话区只展示用户需要理解和确认的结果；技术证据进入右侧栏。普通用户不需要阅读模型内部原始推理，界面应使用“执行详情”“判断依据”“输入与输出”，不使用“原始思维链”。

### 5.4 Chat 与运行分析分层

普通用户继续在会话中完成业务；Developer/Admin 可从 Run 进入独立分析页，必要时显示 Agent DAG。DAG 是故障分析工具，不是业务流程导航。

## 6. 明确不吸收的内容

- 不在 V2 首版引入 Workspace/Space 概念。
- 不加入 Terminal、Cron、MCP Browser、Skills Browser 等通用 Agent 平台入口。
- 不把 Token、Provider、模型名和全局统计常驻在普通用户页面。
- 不要求普通用户先选择 FieldMappingAgent、ThreatAgent 等内部角色。
- 不用动态图、光效和玻璃拟态制造“AI 感”。
- 不将浏览器 sessionStorage 作为会话和待处理事项的唯一持久化来源。

## 7. 实现与许可证风险

| 项目 | 前端实现特征 | 许可证判断 | 复用建议 |
|---|---|---|---|
| Hermes UI | React 18、Babel Standalone、CDN 依赖，核心前端集中于单个 HTML | MIT | 可研究交互和小型模式；不要复制其单文件工程结构 |
| LangGraph Studio | React + TypeScript + Tailwind + Radix，前后端与 LangGraph 体系结合 | Apache-2.0 | 可参考组件组织；复制代码时保留许可证和修改声明 |
| AI Platform Frontend | React 19 + TypeScript + Vite + React Flow | 仓库根目录未发现明确 LICENSE 文件 | 只参考思想和布局，许可证明确前不复制代码 |

任何代码级复用都必须单独记录来源、许可证、修改范围和保留声明；本调研本身只形成设计决策，不引入第三方代码。

## 8. 对当前 V2 图稿的调整清单

1. 保留浅色默认与右上角深浅切换。
2. 保留固定 Composer 和左下角用户信息。
3. 在 Composer 上方增加一条紧凑的当前任务/待处理提示。
4. “执行详情”继续默认关闭，点击后展开右侧时间线。
5. 点击结果文件时复用同一右侧栏显示产物，不新增常驻 Artifact 列。
6. DAG、JSON Payload、Provider 状态留到 Developer/Admin 图稿。
7. 不增加 Workspace、终端或全局仪表盘入口。

## 9. 来源

- [Hermes UI 仓库与 README](https://github.com/pyrate-llama/hermes-ui#readme)
- [Hermes UI 截图目录](https://github.com/pyrate-llama/hermes-ui/tree/main/screenshots)
- [Hermes UI MIT License](https://github.com/pyrate-llama/hermes-ui/blob/main/LICENSE)
- [LangGraph React Agent Studio 仓库与 README](https://github.com/Ylang-Labs/langgraph-react-agent-studio#readme)
- [LangGraph React Agent Studio 前端目录](https://github.com/Ylang-Labs/langgraph-react-agent-studio/tree/main/frontend)
- [LangGraph React Agent Studio Apache-2.0 License](https://github.com/Ylang-Labs/langgraph-react-agent-studio/blob/main/LICENSE)
- [AI Platform Frontend 仓库与 README](https://github.com/mikefelder/ai-platform-frontend#readme)
