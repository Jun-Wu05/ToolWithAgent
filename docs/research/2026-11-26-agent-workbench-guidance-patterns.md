# Agent 工作台引导模式调研：空白态、下一步引导与信息密度（V2 对照）

> 日期：2026-11-26
> 状态：研究稿（主流产品一手来源对照 + V2 缺口映射），待评审
> 关联文档：[自主性差距报告](./agent-autonomy-gap-review.md)（本文回答的是它未覆盖的「引导与界面密度」一层）
> 调研方法：只采一手来源（官方帮助文档、产品页、官方博客/changelog、NN/g 原文），逐条附 URL；所有引文为英文原文直引。调研环境无法访问 web.archive.org，个别已下线的官方条目标注「存档引文，未直接核实」；Genspark 官方站点对抓取返回 403，未纳入对照。浏览器截图不可用，产品行为以官方文档文案引述代替。

## TL;DR

1. **空白态**：成熟产品给的是**可直接发送的完整示例话术**（ChatGPT "prompt examples"、Manus 官方示例、bolt 教程可粘贴 prompt），外加**零成本试用通路**（Dify 模板 "Trials use none of your AI credits"、v0/bolt 可复制的真实项目）。没有一家要求用户先改写带占位符的模板——这与 NN/g「空状态要给 direct pathway」的结论一致。
2. **下一步引导**：业界收敛到四种机制的组合——**计划外化为可审任务列表**（Manus todo.md / Replit 任务列表 / Cursor Plan Mode / bolt Plan Mode）、**澄清问题用交互 UI 承接**（Cursor 2.1）、**基于对话事实生成 follow-up**（Dify）、**执行过程流式逐步叙事**（LangGraph Studio / v0 / n8n）。固定阶段链式的「下一步建议」在对照产品中没有先例。
3. **信息密度**：有一条被反复独立实现的规则——**大块、自包含、可独立复用的产物移出对话流**（Claude artifacts 给出了可操作的判据「typically over 15 lines / stands on its own without chat context」；ChatGPT canvas、v0 实时预览、n8n 画布、Cursor diffs 视图全是旁窗/画布形态）。对话流内只留叙事与摘要。
4. **对 V2 的六个缺口**：a/b/f 三个缺口都有业界直解（可直发示例、每卡一个主操作、产物迁右侧工作区）；c 有 NN/g 同领域（日志分析工具 Loggly）的空状态双通路先例；d 的解是把执行叙事 append-only 地投进对话流（Manus KV-cache 纪律证明这与稳定性不冲突）；e 的解是让下一步建议由会话事实驱动而非固定阶段表。

---

## 1. 问题一：空白状态与新用户引导——首次进入时产品展示什么

### 1.1 产品 × 做法总览

| 产品 | 空白态给什么 | 一手来源 |
|---|---|---|
| ChatGPT | 新会话展示可点击的示例话术（"prompt examples"），即发即用 | [ChatGPT release notes（存档引文）](https://help.openai.com/en/articles/6825453-chatgpt-release-notes) |
| Claude.ai | 从模板新建产物（Docs/Slides/Design/Data/Sheets/Whiteboards/Motion）；Projects 引导先传知识再对话 | [Artifacts 帮助文档](https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them)、[Projects 帮助文档](https://support.claude.com/en/articles/9517075-what-are-projects) |
| Manus | 官方文档直接给一条完整示例话术 + 写需求的四要素指引 | [Quickstart](https://manus.im/docs/introduction/quickstart) |
| Cursor | 官方文档未描述新会话空白态（未核实，不作论据） | — |
| v0 | 模板画廊：「Explore what our community is building」，真实项目可复制 | [v0 docs](https://v0.app/docs/)、[v0 templates](https://v0.app/templates) |
| bolt.new | 两条通路：自带想法直接开工，或从模板市场复制「真实项目」 | [帮助中心首页](https://support.bolt.new/home) |
| Dify | 应用级「开场白 + 建议问题」是一等公民配置；Agent 支持「先试用模板再创建」 | [App Toolkit](https://docs.dify.ai/en/self-host/use-dify/build/additional-features)、[Build an Agent](https://docs.dify.ai/en/cloud/use-dify/build/new-agent/build) |
| LangGraph Studio | 开发者工具：打开项目即见图结构，无面向终端用户的空白态 | [LangSmith Studio docs](https://docs.langchain.com/oss/python/langgraph/studio) |
| Replit Agent | 官方 overview 未记载首屏文案（仅行为描述，见 §2.2） | [Agent overview](https://docs.replit.com/features/agent/overview) |
| n8n | 空画布用第一问结构化引导：「How should this workflow start?」＋触发器选择/模板/助手三通路 | [Build your first workflow](https://docs.n8n.io/build-your-first-workflow) |

### 1.2 关键做法与引文

**ChatGPT：可直发的示例话术。** 官方发布说明（2023-07 条目，现行页面已裁剪为仅保留近期条目，以下为存档引文，未在现行页面直接核实）："Prompt examples: A blank page can be intimidating. At the beginning of a new chat, you'll now see examples to help you get started." 同期还有 suggested replies："ChatGPT now suggests relevant ways to continue your conversation."（[来源](https://help.openai.com/en/articles/6825453-chatgpt-release-notes)）。示例话术至今仍在迭代：OpenAI 官方论坛 2026-08 的用户帖描述新会话中出现 suggested prompts——"a feature that began popping up around 8/20"（[官方论坛帖子](https://community.openai.com/t/suggested-prompts-are-an-unwanted-interruption-please-make-them-optional/1392548)，用户内容，佐证「chips 仍在生产环境投放」但不可作为产品文案依据）。

**Manus：文档直接给完整示例。** Quickstart 原文："Write what you want as the result. Include the topic, the scope, and the output format." 并给出一条可直接照抄的任务："Research the top 5 AI trends in healthcare and create a summary report."（[Quickstart](https://manus.im/docs/introduction/quickstart)）。这是「话术即文档」的典型——帮助文档本身就在示范一条好的开场请求。

**bolt.new：两条通路 + 可粘贴话术。** 帮助中心首页："start building in Bolt to bring your own idea to life"，或从模板市场复制——"Each example below is a real project that you can copy for free."（[帮助中心](https://support.bolt.new/home)）。官方 QuickStart 教程则直接给一段可粘贴的完整 prompt（宠物取名应用），用户贴进输入框即可跑通全流程，"Wait approximately five minutes while Bolt creates your app"（[QuickStart](https://support.bolt.new/get-started/quickstart)）。

**Dify：空白态是平台级配置，模板可先试用。** 开场白是产品功能而非话术技巧："Set an opening message that greets users at the start of each conversation, with optional suggested questions to guide them toward what the app does well"（[App Toolkit](https://docs.dify.ai/en/self-host/use-dify/build/additional-features)）。模板通路带零成本试用："For a ready-made starting point, choose **Create from Template** instead. You can try a template before using it: open its **Details** > **Try it**." "Trials use none of your AI credits or API keys."（[Build an Agent](https://docs.dify.ai/en/cloud/use-dify/build/new-agent/build)）。

**n8n：把开放输入变成结构化第一问。** 空画布的第一个问题不是「请描述你想做什么」，而是："How should this workflow start?"——用户从触发器类型（定时/表单/应用事件）开始选择："Select **Add first step**, then select **On a schedule**"；同时保留从模板或用 Assistant 对话生成两条通路（[Build your first workflow](https://docs.n8n.io/build-your-first-workflow)）。

**NN/g 设计学基础（空白态）。** Kate Kaplan《Designing Empty States in Complex Applications》（NN/g，2021-09-19）给出三条指南：① 传达系统状态（空面板"creates confusion and decreases user confidence"）；② 提供学习线索——空态是"pull revelation"式情境帮助，比前置教程有效；③ 给关键任务**直达通路**："Don't just say what a user *could* do — show how or link directly to it." 文中恰有同领域案例：日志分析工具 Loggly 的空状态提供 "2 direct pathways for getting started: adding log sources or exploring with demo data."（[nngroup.com/articles/empty-state-interface-design](https://www.nngroup.com/articles/empty-state-interface-design)）。结论句："Don't let empty-state design be an afterthought within your application." 2022 年视频版重申同一框架："Empty states provide opportunities for designers to communicate system status, increase learnability of the system, and deliver direct pathways for key tasks."（[视频页](https://www.nngroup.com/videos/empty-states-in-application-design-guidelines)）。

**值得学**：可直发的完整示例（ChatGPT/Manus/bolt）、零成本试用（Dify/v0/bolt）、结构化第一问（n8n）、空态=知识/模板前置（Claude Projects、Dify 开场白）。
**反模式（对照 V2 a）**：给用户一段需要先替换【字段名】占位符才能用的话术模板——所有对照产品的示例话术都「原文可用」，无一要求改写。

---

## 2. 问题二：下一步引导——如何让"下一步做什么"永远明确

### 2.1 产品 × 机制总览

| 产品 | 计划外化 | 澄清承接 | follow-up 生成 | 单主操作卡 | 过程叙事 |
|---|---|---|---|---|---|
| ChatGPT | —（canvas 快捷菜单场景化） | Tasks 走对话式创建+确认 | suggested replies（存档引文） | canvas 快捷菜单按场景聚焦 | canvas 内协作 |
| Claude.ai | — | —（未见官方记载） | —（未核实） | "Try fixing with Claude" | 产物内编辑叙事 |
| Manus | **todo.md 逐步更新** | — | follow-up message in the same task | — | 计划复诵进上下文 |
| Cursor | **Plan Mode（Markdown 文件）** | **交互 UI 答澄清问题** | Bugbot→"Fix in Cursor" | **Fix in Cursor（预填 prompt）** | 浏览器工具自测叙事 |
| Replit | **ordered task list + 审批** | plan 审批对话框 | checkpoints 回滚 | "Accept tasks"/"Revise plan" | 定期自测 |
| bolt | Plan Mode→"Implement this plan" | 计划在聊天中精修 | "Implement this plan" 一键切换 Build | **Implement this plan** | — |
| v0 | 规划内置于 mantra（"Plan your project"） | "make v0 clarify" | 最多 10 条排队 prompt | — | **visual progress indicators** |
| Dify | — | — | **Follow-up 生成式 + 可配** | "More Like This" 每卡一钮 | — |
| LangGraph Studio | 图结构可视化 | 每步暂停模式 | — | — | **每步流式展示** |
| n8n | 画布节点图 | 逐步审批（Allow once） | — | — | **进度上画布** |

### 2.2 关键做法与引文

**Manus：计划是持续重写的 todo，复诵目标。** 官方博客："when handling complex tasks, it tends to create a todo.md file—and update it step-by-step as the task progresses." 以及点题句："By constantly rewriting the todo list, Manus is reciting its objectives into the end of the context."（[Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)）。任务交付后下一步动作被明确为："To change the result, send a follow-up message in the same task."（[Quickstart](https://manus.im/docs/introduction/quickstart)）。

**Replit：任务列表先审后建 + checkpoints 兜底。** 官方文档："creates an ordered task list you can review and refine" "When you're happy with the plan, approve it and Replit starts building."；界面对话框给出 "Accept tasks" 与 "Revise plan" 两个选项；执行中 "creates checkpoints as it works, so you can roll back to any previous state"，且 "tests its own work on a regular basis"（[Agent overview](https://docs.replit.com/features/agent/overview)）。

**Cursor：澄清问题用交互 UI 承接，计划可编辑可检索。** Plan Mode 发布文：计划落成 "a Markdown file with file paths and code references"，带 "an interactive editor to modify plans inline"；用户可 "edit the plan directly, including adding or removing to-dos"，然后 "build directly from your plan when ready"；Cursor 还会 "suggest plan mode automatically when you describe complex tasks"（[Introducing Plan Mode](https://cursor.com/blog/plan-mode)）。2.1 版本把「问」做成了 UI："Cursor responds with clarifying questions to improve the plan quality." "shows an interactive UI to easily answer questions." "You can also ⌘+F to search inside generated plans."（[changelog 2.1](https://cursor.com/changelog/2-1)）。

**Cursor：每张结果卡一个主操作。** Bugbot 的审查发现以单按钮直连修复动作："You can click 'Fix in Cursor' to move back to the editor with a pre-filled prompt to fix the issue."（[changelog 1.0](https://cursor.com/changelog/1-0)）。这就是「发现→修复」的 direct pathway：一个主操作 + 预填上下文，而非在卡片上堆并列按钮。

**bolt：计划确认后一个按钮切模式。** Plan Mode 页描述：确认计划后提供快速操作按钮 "Implement this plan"，点击后 "auto-switches to Build Mode to apply changes"；从首页以 Plan Mode 启动时 "first builds your app's base structure, then presents the plan in chat for review and refinement"（[Plan Mode](https://support.bolt.new/prompting/plan-mode)）。

**Dify：follow-up 是可配置的生成能力，不是固定表。** "When enabled, follow-up questions are generated after each response to help users continue the conversation." 且方向可控：可 "pick the model that generates the questions, or write a custom prompt (up to 1,000 characters)"，用来 "adjust the number, wording, or length of the questions"（[App Toolkit](https://docs.dify.ai/en/self-host/use-dify/build/additional-features)）。另有每卡单钮的 "More Like This"："each generated result includes a button to produce a variation"（同一来源）。

**v0：过程反馈是一等公民。** 官方文档列出的能力包括："Real-time Feedback: Real-time preview of your app, with visual progress indicators and rich UI feedback for all agent actions"（[v0 docs](https://v0.app/docs/)）。引导用户拆步骤并让 v0 追问的方法论："Start simple. Plan your project. Provide context. Specify and make v0 clarify. Iterate."（[text-prompting](https://v0.app/docs/text-prompting)）。

**LangGraph Studio：把「下一步在干嘛」做成产品。** 官方文档："connects to your locally running agent to show you each step your agent takes"，包括 "the prompts sent to the model, tool calls and their results, and the final output"（[LangSmith Studio docs](https://docs.langchain.com/oss/python/langgraph/studio)）。首发博客："a stream of real-time information about what steps are happening"、支持 "it pauses after each step of the graph" 的步进模式，且 "At any point, you can interact with the state of the agent"（[首发博客](https://www.langchain.com/blog/langgraph-studio-the-first-agent-ide)）。

**n8n：审批即下一步。** Assistant 构建："You describe what you want, approve each step, and end up with a workflow you can open, edit, and publish." 权限请求 "Allow once"，进度可视化："you'll see the progress on the canvas to the right of the chat"（[Build your first workflow](https://docs.n8n.io/build-your-first-workflow)）。

**ChatGPT Tasks：任务创建本身走对话 + 确认 + 面板管理。** "To create a task, ask ChatGPT to complete an action, such as 'Let me know when my package is delivered.'" 创建后有确认："After a task is created, ChatGPT displays the following confirmation"；管理统一入口 "Go to Scheduled to view and manage tasks"（[Scheduled tasks](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)）。

**值得学**：计划外化为「可审、可改、可检索」的实体（Cursor/Replit/Manus）；澄清问题配交互 UI 而非自由文本追问（Cursor 2.1）；follow-up 基于对话生成且方向可配置（Dify）；结果卡单主操作 + 预填上下文（Cursor Bugbot/bolt/Dify More Like This）。
**反模式（对照 V2 e）**：对照产品中没有任何一家在任务完成后推荐**固定阶段链**的下一步——所有下一步建议要么由模型基于当前事实生成（Dify/ChatGPT suggested replies），要么由计划实体承接（todo/task list），要么把「改变结果」明确为同任务内追加消息（Manus）。

---

## 3. 问题三：信息密度控制——完整产物放哪，对话流留什么

### 3.1 产品 × 布局总览

| 产品 | 大块产物的归宿 | 对话流里留什么 | 一手来源 |
|---|---|---|---|
| ChatGPT | canvas 旁窗（写作/代码），自动+手动打开，版本历史 | 交互叙事与快捷菜单 | [Introducing canvas](https://openai.com/index/introducing-canvas/) |
| Claude.ai | artifacts 独立窗口 + 侧栏 Artifacts tab | 触发生成/修改的对话 | [Artifacts 帮助](https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them) |
| Manus | 沙箱交付物（报告/幻灯/网站）在任务内交付 | todo 复诵、追加消息 | [Quickstart](https://manus.im/docs/introduction/quickstart) |
| Cursor | 编辑器/diffs 视图承载变更；agent 视图围绕结果 | 计划文件、澄清问答 | [Cursor 3](https://cursor.com/blog/cursor-3)、[Cursor 2.0](https://cursor.com/blog/2-0) |
| v0 | 实时预览即界面主体 | agent 动作反馈 | [v0 docs](https://v0.app/docs/) |
| bolt | Preview 窗口（"Try it out in the Preview window"） | 计划精修、模式切换 | [QuickStart](https://support.bolt.new/get-started/quickstart) |
| Dify | 右侧面板 Build/Preview 切换承载产物 | 构建聊天即操作流 | [Build an Agent](https://docs.dify.ai/en/cloud/use-dify/build/new-agent/build) |
| LangGraph Studio | 图可视化 + 逐步状态 | 与 agent 交互的输入框 | [Studio docs](https://docs.langchain.com/oss/python/langgraph/studio) |
| n8n | 画布（聊天右侧） | 对话式指令 + 审批 | [Build your first workflow](https://docs.n8n.io/build-your-first-workflow) |

### 3.2 关键做法与引文

**Claude artifacts：给出了「什么时候搬出对话流」的可操作判据。** 帮助文档：产物应 "open in its own window beside your conversation"，并被收集到 "the Artifacts tab in your Claude sidebar"；触发判据是内容 "is significant and self-contained, typically over 15 lines"、会被 "edit, iterate on, or reuse outside the conversation"、"stands on its own without chat context"、且会被 "refer back to or use later"（[Artifacts 帮助](https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them)）。产物侧的编辑保持轻叙事："Claude's edits are outlined as they land"（[claude.com/features/artifacts](https://claude.com/features/artifacts)）。**这条判据几乎可直接套用 V2 的枚举预览表**（内嵌表含页签/搜索/排序/分页，满足全部四条）。

**ChatGPT canvas：旁窗 + 自动打开 + 场景化快捷菜单。** "opens in a separate window, allowing you and ChatGPT to collaborate on a project" "Canvas opens automatically when ChatGPT detects a scenario in which it could be helpful." 用户也可在 prompt 中写 "use canvas" 手动打开；窗口内是按场景聚焦的快捷菜单（写作：Suggest edits / 调整长度 / 调整阅读级别 / final polish / 加 emoji；代码：Review code / 加日志 / 加注释 / 修 bug / 移植语言），支持直接编辑、选中局部聚焦、"restore previous versions of your work" 的版本历史（[Introducing canvas](https://openai.com/index/introducing-canvas/)）。

**Cursor：变更审查独立成视图，界面围绕 agent 而非文件。** 2.0："designed from the ground up to be centered around agents rather than files"；官方把「审查变更」识别为 agent 时代新瓶颈并给出解法："we've seen two new bottlenecks emerge: reviewing code and testing the changes" "We've made it much easier to quickly review the changes an agent has made and dive deeper into the code"（[Cursor 2.0](https://cursor.com/blog/2-0)）。Cursor 3 进一步："The new diffs view allows you to edit and review changes faster with a simpler UI."（[Cursor 3](https://cursor.com/blog/cursor-3)）。对话流内的密度管理见 1.0："Mermaid diagrams and Markdown tables can now be generated and viewed in the same place!" 加上可折叠工具调用（[changelog 1.0](https://cursor.com/changelog/1-0)）——大结构进对话可折叠，完整产物仍出流。

**v0：预览即画布。** "Real-time preview of your app, with visual progress indicators and rich UI feedback for all agent actions"（[v0 docs](https://v0.app/docs/)）——产物不是对话里的文本块，是持续存在的可视界面。

**Dify：右侧面板承载 Build/Preview 两种视图。** "Switch the right panel from **Build** to **Preview** to try the agent as end users will experience it once published"（[Build an Agent](https://docs.dify.ai/en/cloud/use-dify/build/new-agent/build)）——与 V2 的「右侧资源工作区」同构，可佐证右侧工作区放产物预览是业界主流布局。

**NN/g 设计学基础（渐进披露）。** Jakob Nielsen《Progressive Disclosure》（2006-12-03）："Initially, show users only a few of the most important options." 次要特性只在用户要求时出现；该策略 "improves 3 of usability's 5 components: learnability, efficiency of use, and error rate"。两条硬性要求：切分要正确（首层只放高频项）+ 层级要明显（"labeled with strong information scent"）；且 "**3+ levels typically have low usability because users often get lost when moving between the levels**"（[nngroup.com/articles/progressive-disclosure](https://www.nngroup.com/articles/progressive-disclosure/)）。**对 V2 的直接含义：把表格移到右侧工作区可行，但不要在对话流里再留三层嵌套的折叠入口。**

**值得学**：产物旁窗/画布 + 自动打开判据（Claude/ChatGPT canvas）；变更审查独立视图（Cursor 3）；聊天+画布分栏（n8n）；对话流内可折叠结构（Cursor 1.0）；**append-only 叙事纪律**——Manus 的上下文工程把进度叙事与稳定性统一："Make your context append-only." "Keep your prompt prefix stable."（[Manus 博客](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)），说明「执行中持续往对话流追加进度」不牺牲性能与稳定性。
**反模式（对照 V2 f）**：对照产品无一在对话流内嵌需要页签/搜索/排序/分页的完整表格——满足 Claude 判据（>15 行、自包含、脱离对话可用）的内容一律搬出。

---

## 4. 模式与反模式清单

### 4.1 值得学的模式

| # | 模式 | 一手例证（产品） | 对应 V2 缺口 |
|---|---|---|---|
| 1 | 可直发的完整示例话术 | ChatGPT prompt examples（存档引文）、Manus Quickstart 示例、bolt 可粘贴 prompt | a |
| 2 | 空态模板 + 零成本试用 | Dify "Try it ... none of your AI credits"、v0/bolt 真实项目可复制 | a/c |
| 3 | 空态给两条以上直达通路（含 demo data） | NN/g Loggly："adding log sources or exploring with demo data"、n8n 触发器/模板/助手三通路 | c |
| 4 | 开放输入变结构化第一问 | n8n "How should this workflow start?" | a |
| 5 | 开场白+建议问题为平台配置 | Dify Conversation Opener | a |
| 6 | 计划外化为可审、可改、可检索实体 | Manus todo.md、Replit task list（Accept/Revise）、Cursor plan 文件、bolt plan-in-chat | d |
| 7 | 澄清问题用交互 UI 承接 | Cursor 2.1 interactive UI | （追问生成化，见关联报告卡片 3） |
| 8 | follow-up 由事实生成、方向可配置 | Dify Follow-up（可选模型/自定义 prompt） | e |
| 9 | 结果卡单主操作 + 预填上下文 | Cursor Bugbot "Fix in Cursor"、bolt "Implement this plan"、Dify "More Like This" | b |
| 10 | 执行过程流式逐步叙事（append-only） | LangGraph Studio 每步流、v0 progress indicators、n8n 进度上画布、Manus append-only 纪律 | d |
| 11 | 大块产物判据化搬出对话流 | Claude artifacts（>15 行/自包含/可复用/无对话上下文可用）、ChatGPT canvas 自动开窗 | f |
| 12 | 产物侧持续存在的工作区（预览/审查/版本） | v0 实时预览、Cursor 3 diffs、ChatGPT canvas 版本历史、Replit checkpoints | f |

### 4.2 反模式（业界证据 + V2 同型）

| # | 反模式 | 一手证据 | V2 同型 |
|---|---|---|---|
| 1 | 空白态留给用户「要先改写才能用」的模板 | NN/g：空态要求 "show how or link directly to it"，Don't "just say what a user *could* do"（[empty-state](https://www.nngroup.com/articles/empty-state-interface-design)） | a |
| 2 | 结果卡上堆并列操作 | NN/g 渐进披露首层原则："show users only a few of the most important options"（[progressive-disclosure](https://www.nngroup.com/articles/progressive-disclosure/)）；对照业界每卡单钮惯例 | b |
| 3 | 缺资源时功能路径完全不可见 | NN/g Loggly 反面推论：空状态必须同时给「补数据」和「用示例数据」两条通路（[empty-state](https://www.nngroup.com/articles/empty-state-interface-design)） | c |
| 4 | 长任务静默 | 对照业界全部采用流式/逐步/画布叙事（§2.2） | d |
| 5 | 下一步建议与当前事实无关 | 对照产品无固定阶段链建议先例（§2.2） | e |
| 6 | 对话流内嵌重型交互件 | Claude artifacts 判据 + ChatGPT canvas / Cursor / v0 的旁窗惯例（§3.2） | f |
| 7 | 建议流不可关闭/干扰 | OpenAI 官方论坛用户投诉（2026-08）："very distracting"、请求 "should definitely be optional"（[论坛帖](https://community.openai.com/t/suggested-prompts-are-an-unwanted-interruption-please-make-them-optional/1392548)，用户内容）——chips 类机制应可停用 |
| 8 | 渐进披露层级过深 | NN/g："3+ levels typically have low usability because users often get lost"（[progressive-disclosure](https://www.nngroup.com/articles/progressive-disclosure/)）——V2 若把产物迁右侧，注意入口层级 ≤2 |

---

## 5. 对 V2 的启示（逐条对应已知缺口）

> V2 现状基线：空状态 6 个场景模板（含【字段名】占位符）；结果卡片 3-6 按钮；每阶段后端生成建议 chips；任务提示条在输入框上方；产物在右侧资源工作区。

**a) 空状态模板含占位符，用户需懂行话才能替换。**
业界惯例是**示例话术原文可用**：ChatGPT 的 prompt examples、Manus 文档里的完整示例请求、bolt 教程里可整段粘贴的 prompt，都假设用户「不改一个字也能跑通」。NN/g 空态指南要求 "direct pathways"——用户点/贴即用，而不是先理解再改写。**建议**：① 空态 chips 从「话术模板」改为「完整示例请求」，点击直接发送（话术内不出现任何需替换的占位符）；② 配套内置一份小体量示例日志文件，让示例话术即点即真跑；③ 学 Dify 把「开场白 + 建议问题」做成数据驱动配置而非硬编码文案，便于后续按用户角色（分析师/开发）分版本。

**b) 分类结果卡带 5-6 个按钮，与 chips 内容重复（违反"每卡一个主操作"）。**
业界对照里「发现→行动」全部是单主操作 + 预填：Cursor Bugbot 的 "Fix in Cursor"（一钮进编辑器、prompt 已预填）、bolt 的 "Implement this plan"（一钮切模式）、Dify 的 "More Like This"（每卡仅一个 variation 钮）。NN/g 渐进披露同样要求首层只放最重要选项。**建议**：① 每张结果卡收敛为 1 个主操作（该阶段语义上的默认下一步），其余操作进「···」次级菜单或右侧工作区按钮组；② 结果卡按钮与对话流 chips 严格二选一承载「下一步」职责，另一方只做「查看产物」入口，消除双份重复。

**c) 填充功能需先上传枚举映射附件，无附件时路径完全不可见、无引导。**
NN/g 的 Loggly 案例是**同领域**答案：日志工具空状态必须给两条通路——"adding log sources or exploring with demo data"（补数据源 / 用演示数据探索）。n8n 空画布同样给「触发器 / 模板 / 助手」三选一。**建议**：① 填充能力入口处做前置检查：会话无枚举附件时，把空状态/建议 chips 改写为两条通路——「上传映射文件」与「使用内置示例枚举数据先试跑」；② 内置 1-2 份标准枚举映射模板（如常见 SIEM 字典），作为产物在管理台可下载/可一键载入，使该功能在零准备度下也有完整可体验路径。

**d) 长任务运行中对话流静止，进度只在输入框上方提示条与轨迹页签。**
业界解法高度一致：**把计划外化并持续叙事**。Manus 用 todo.md "update it step-by-step as the task progresses"，并证明进度叙事可以 append-only（"Make your context append-only."）而不破坏 KV-cache 稳定性；LangGraph Studio "show you each step your agent takes"；v0 "visual progress indicators and rich UI feedback for all agent actions"；n8n "you'll see the progress on the canvas to the right of the chat"。**建议**：① 执行中把 PlanDecision 的类型化步骤以「步骤卡」形式 append 到对话流（每完成一步更新一次：步骤名/状态/关键计数），对话流由静止变为线性叙事，轨迹页签保留全量细节（渐进披露：主层叙事、次层轨迹）；② 步骤卡复用现有 ExecutionReport 数据，无需新增执行语义（与本仓「执行账本回喂」方向衔接，见 [自主性差距报告](./agent-autonomy-gap-review.md) 卡片 2）。

**e) 导出完成后建议的下一步是"继续标准字段映射"，多数场景无关。**
对照产品没有固定阶段链建议：Dify 的 follow-up "are generated after each response" 且方向可通过自定义 prompt 控制；Manus 把完成后的动作定义为 "send a follow-up message in the same task"（同任务内精修），而不是推荐一个泛化新任务；Cursor 让下一步从「研究代码库 + 澄清」中长出来。**建议**：① 下一步建议不再取自固定阶段顺序表，改由会话事实驱动（本仓 SessionFacts 已有结构：上一阶段产物状态 → 生成建议），导出完成后建议应收敛为与新事实相干的分支（新文件解析 / 修正后重导出 / 复用到其他会话）；② 允许后端为建议 chips 配置「生成规则/模板 + 关停开关」（Dify 式配置能力 + 业界反模式 7 的教训：建议可停）。

**f) 对话流内嵌完整表格/表单（枚举预览含页签/搜索/排序/分页），考虑迁右侧工作区。**
业界已收敛出判据：Claude artifacts 明确四条——"significant and self-contained, typically over 15 lines"、"edit, iterate on, or reuse outside the conversation"、"stands on its own without chat context"、"refer back to or use later"；满足即开旁窗（"open in its own window beside your conversation"）。ChatGPT canvas、v0 预览、n8n 画布、Cursor diffs 全部是「聊天 + 旁侧产物面」的双栏形态；Dify 的右面板 Build/Preview 切换与 V2 右侧资源工作区同构。**建议**：① 枚举预览（含页签/搜索/排序/分页）整体迁右侧资源工作区，满足 Claude 四条判据的产物不应留在对话流；② 对话流内留「摘要卡」（行数/字段数/覆盖率 + 一个「在工作区打开」主操作，与缺口 b 的收敛合并考虑）；③ 右侧工作区已有字段映射/结果产物页签，枚举预览作为同级页签挂入即可，但入口层级控制在 ≤2（NN/g 反模式 8）；④ 保留对话流内轻量 Markdown 表格 + 可折叠（Cursor 1.0 "Mermaid diagrams and Markdown tables ... in the same place" + collapsible tool calls 的形态）用于小规模预览。

---

## 6. 来源

### 产品官方（一手）

- OpenAI — [Introducing canvas](https://openai.com/index/introducing-canvas/) · [Scheduled tasks in ChatGPT（帮助中心）](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt) · [ChatGPT release notes（帮助中心；2023-07「prompt examples / suggested replies」条目为存档引文，现行页面已裁剪）](https://help.openai.com/en/articles/6825453-chatgpt-release-notes) · [OpenAI 官方论坛：suggested prompts 投诉帖（用户内容，佐证用）](https://community.openai.com/t/suggested-prompts-are-an-unwanted-interruption-please-make-them-optional/1392548)
- Anthropic / Claude — [What are artifacts and how do I use them?（帮助中心）](https://support.claude.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them) · [What are projects?（帮助中心）](https://support.claude.com/en/articles/9517075-what-are-projects) · [Claude Artifacts 产品页](https://claude.com/features/artifacts)
- Manus — [Context Engineering for AI Agents: Lessons from Building Manus（官方博客）](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) · [Get started with Manus（官方文档）](https://manus.im/docs/introduction/quickstart) · [Features overview（官方文档）](https://manus.im/docs/features/overview)
- Cursor — [Introducing Plan Mode](https://cursor.com/blog/plan-mode) · [Introducing Cursor 2.0](https://cursor.com/blog/2-0) · [Meet the new Cursor（Cursor 3）](https://cursor.com/blog/cursor-3) · [Changelog 1.0](https://cursor.com/changelog/1-0) · [Changelog 2.1](https://cursor.com/changelog/2-1)
- v0（Vercel）— [v0 docs 总览](https://v0.app/docs/) · [Prompt Engineering（text-prompting）](https://v0.app/docs/text-prompting) · [v0 templates](https://v0.app/templates)
- bolt.new（StackBlitz）— [帮助中心首页](https://support.bolt.new/home) · [QuickStart](https://support.bolt.new/get-started/quickstart) · [Intro to Bolt](https://support.bolt.new/get-started/intro-bolt) · [Plan Mode](https://support.bolt.new/prompting/plan-mode)
- Dify — [App Toolkit / Additional Features](https://docs.dify.ai/en/self-host/use-dify/build/additional-features) · [30-Minute Quick Start](https://docs.dify.ai/en/quick-start) · [Build an Agent](https://docs.dify.ai/en/cloud/use-dify/build/new-agent/build)
- LangChain — [LangSmith Studio（原 LangGraph Studio）文档](https://docs.langchain.com/oss/python/langgraph/studio) · [LangGraph Studio: The First Agent IDE（首发博客）](https://www.langchain.com/blog/langgraph-studio-the-first-agent-ide)
- Replit — [Agent overview（官方文档）](https://docs.replit.com/features/agent/overview)
- n8n — [Build your first workflow（官方文档）](https://docs.n8n.io/build-your-first-workflow)

### 设计学基础（NN/g 原文）

- Kate Kaplan — [Designing Empty States in Complex Applications: 3 Guidelines（2021-09-19）](https://www.nngroup.com/articles/empty-state-interface-design)
- Jakob Nielsen — [Progressive Disclosure（2006-12-03）](https://www.nngroup.com/articles/progressive-disclosure/)
- Kate Kaplan — [Empty States in Application Design: 3 Guidelines（视频，2022-10-14）](https://www.nngroup.com/videos/empty-states-in-application-design-guidelines)

### 未核实与缺口声明

- ChatGPT 2023-07「prompt examples / suggested replies」原文无法在现行帮助页直接核实（页面已裁剪旧条目；web.archive.org 在调研环境不可达），全文标注为存档引文；其当前行为另有官方论坛用户帖（2026-08）佐证。
- Claude.ai、Cursor 的新会话空白态首屏文案无官方文档记载，未纳入论据。
- Genspark 官方站点对自动抓取返回 403，未能取得一手来源，未纳入对照。
- 本调研未采信任何二手评测/测评文章；各产品均以上表官方来源为唯一依据。
