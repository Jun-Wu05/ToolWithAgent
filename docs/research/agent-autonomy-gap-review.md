# ToolWithAgent 自主性差距报告：从固定流水线到渐进式半自主 Agent

> 日期：2026-09-09
> 状态：研究稿（调研 + 代码证据 + 业界对照），待拷问收口
> 配套文档：[PRD 草案：agent-autonomy-evolution](../prd/agent-autonomy-evolution.md) · [可视化版报告](./agent-autonomy-gap-review.html)
> 调研方法：代码库全量探索（file:line 证据）+ 主流框架与生产级 agent 公开资料调研（来源见 §8）

## TL;DR

1. **现状定位**：按 Anthropic《Building Effective Agents》的分类，ToolWithAgent 是**教科书级的 workflow（固定编排的 prompt chain），不是 agent**——LLM 只在一次规划调用里产出静态 `PlanDecision`，之后所有控制流由 Python for 循环和 12 项适配器注册表决定。这是**有意识的工程立场**（ADR-0005 失败关闭、PRD 策略冻结），不是落后。
2. **「不智能」的两个根因**（对应用户感知「失败的点很奇怪、回答很机械」）：
   - **失败点奇怪**：大量正则守卫在中文表层模式上开火（填充动词表、短语正则、字段白名单），命中位置看似随机；且 Planner 失败即转追问、零重试（设计不变量）。
   - **回答机械**：追问文案是 `message_code` 模板渲染；Planner 只见 SessionFacts **目录**不见**值**，无法生成有上下文的自然回复。
3. **能否变成自主 agent**：能，且**不必推翻现有架构**。演进缝已经存在——ADR-0010 威胁链已经验证了「执行结果 → 构造新计划 → 再走 PlanExecutor」这条缝。推荐**渐进式半自主**（L1 → L2 → 选择性 L3），每阶段用评估门禁决定是否继续放开。
4. **首选切片**（本轮已确认）：**失败自恢复层（RecoveryOrchestrator）+ 执行反馈回喂 + 追问生成化**——把「失败即停问人」变成「有界自恢复（≤N 次），穷尽预算或不可逆操作才问人，且问得有人话味」。

---

## 1. 现状架构画像

### 1.1 端到端控制流（实际调用树）

```text
用户在 Chainlit 输入
└─ web/message_router.py:on_message            [每会话 asyncio.Lock 串行]
   └─ web/user_message_handlers.py:handle_user_message
      ├─ is_explicit_clear_command              [9 个清空关键词硬匹配 request_runtime.py:20-30]
      └─ application/request_runtime.py:run_user_request
         ├─ typed_conversation_history / append_history   [单条截 1500 字符，窗口 6000]
         ├─ build_session_facts                 [SessionState → 冻结 Pydantic 投影，只含目录]
         ├─ ★ PlannerService.plan               [agent/core/planner.py:318]
         │    ├─ Agno Agent: tools=[]、temperature=0、output_schema=PlanDecision
         │    ├─ 输入 = {user_text, 最近 6 条历史, session_facts} 的 JSON
         │    ├─ JSON 围栏剥离 + Pydantic 校验 + 未知键兜底剥离
         │    ├─ _guard_cross_turn_threat_target   [Python 正则守卫]
         │    └─ _guard_explicit_feature_field     [Python 正则守卫]
         │    失败/超时/非法 → clarification，不重试   ← 「一次 Planner 不变量」
         ├─ decision ≠ execute → 模板追问，结束
         ├─ PlanExecutor.execute                [application/execution.py:105]
         │    ├─ policy.validate_plan           [计划级预校验，任何步骤前拦截整份计划]
         │    └─ for step in plan.steps         [★ 严格顺序 for 循环 execution.py:162]
         │         ├─ _validate_step            [语义/依赖校验 → needs_input 即停]
         │         ├─ DefaultExecutionPolicy.validate_step  [字段白名单守卫 → 追问可用字段]
         │         ├─ adapter = adapters[step.type]  [dict 按 12 个字符串键硬分派]
         │         └─ adapter.execute(...)        [非 SUCCESS 立即 break，无恢复]
         └─ run_threat_chain_after_mapping      [application/threat_chain.py:204，ADR-0010]
              纯 Python 判触发 → 构造固定 4 步计划 → 再走一遍 PlanExecutor
```

### 1.2 关键判断与代码证据

| 判断 | 证据 |
|---|---|
| 决策时零工具调用 | `agent/core/planner.py:45` `tools=[]`；能力面 = 12 个冻结 StepSpec 类型（`contracts/planner_models.py`） |
| 「一次 Planner」不变量 | `agent/core/planner.py:38-39`「禁止用失败后重调破坏一次 Planner 不变量」；ADR-0005 |
| 执行是顺序循环，无观察反馈 | `application/execution.py:162` `for step in plan.steps`；`depends_on` 只用于校验不用于调度；非 SUCCESS 立即 break |
| 失败关闭，无自恢复 | Planner 失败→追问；执行失败→break→渲染错误；唯一例外是威胁链（纯 Python 续跑，ADR-0010） |
| 正则守卫与 prompt 规则双份维护同一语义 | `planner.py:86-108`（10 个填充动词 + 非字段词表）、`planner.py:200-203`（中文短语正则）vs `agent/prompts/planner.md`（169 行，约 40 条消歧规则） |
| 追问是模板不是生成 | `web/plan_renderer.py:100-103`（clarification → 💡 模板 + choices 列表）；`execution_policy.py:127-158`（needs_input 消息列可用字段） |
| Planner 只见目录不见值 | `contracts/session_facts.py:18-42`；ADR-0006 仅 2 个产物槽位；历史仅 6 条×2000 字符（`planner.py:52-57`） |
| 知识在 prompt 不在数据 | `agent/prompts/threat_type.md:26`（约 130 个威胁类清单内嵌）；`agent/shared/event_classify.py:30-66`（21 个事件名硬编码绑定） |
| 防御性解析 | `application/parsing.py`：Pydantic → json.loads → 括号切片 → 围栏提取 → 中文标点修复（:274-292）→ 逐项正则（:294-308）；拒绝响应检测（:14-20） |
| 无跨会话记忆 | `agent/memory/` 已清空（commit 437a895）；ADR-0001「暂不需跨进程持久化」 |
| 知识库只写不读 | `agent/tools/log_pattern_store.py` + `config/log_patterns.db`（shared-log-knowledge-review PRD 自述） |

### 1.3 演进史注记：你们已经历过一轮「自主化」并主动收敛

`docs/prd/autonomous-agent-routing.md`（RouterAgent 时代）→ ADR-0002（快/慢路径）→ ADR-0005（统一 Planner、废除关键词路由回退）。这条历史说明：**自主性曾在「路由」这个位置被尝试过，并因正确性门禁被主动收敛为确定性设计**。本轮演进必须尊重这个教训——不是回到多 Agent 自主路由，而是在保持统一 Planner 的前提下，把自主性加在**已被验证值得的位置：执行反馈后的自恢复**。

### 1.4 遗骸清单（名为 agent 的层大半是遗骸）

| 遗骸 | 现状 |
|---|---|
| EnumAgent / LogParserAgent（`agent/core/team.py:156-214`） | 构造后从未被生产代码调用（生产路径直连 httpx headless 函数） |
| `agent/core/resilience.py`（CircuitBreaker/ModelFallback/RetryPolicy） | 生产代码零引用，仅特征测试在测；README:158 宣称「含熔断」与实际不符 |
| `agent/tools/confirmation_tool.py`（4 个 HITL 工具） | 从未挂载到任何 Agent |
| `create_data_mapping_team`（`team.py:227-243`） | 返回的只是 ProfessionalAgentRegistry，注释自认「不提供自主路由能力」 |
| `skills/multi-step-plan/` | RouterAgent 时代遗物 |

---

## 2. 「不智能」的根因解剖

### 2.1 失败点为什么奇怪

失败发生在**表层模式匹配**上，而不是语义理解上：

1. **填充动词表**：`planner.py:86-108` 硬编码 10 个「填充到/填入/写入/回填到…」动词 + 非字段词集合。用户换个说法（如「设置到」「放在」）就绕过或误触发守卫。
2. **字段白名单守卫**：`execution_policy.py:127-158`——枚举目标字段不在（日志体键 ∪ available_fields）时 needs_input。守卫本身是对的（issue #196 的修复），但它**只有两个出口：硬跑失败或问人**，没有第三个出口「agent 先自查再决定」。
3. **计划级预拦截**：`execution.py:142`（#148）在任何步骤执行前拦截整份计划。用户看到的是「计划被拒」，而不是「哪一步可以修」。
4. **Planner 零重试**：超时/非法输出一律转 clarification——把「重试」从系统能力中除名，网络抖动也会变成一次追问。

**本质**：这些守卫每一条都对应一个曾经的线上 bug（#122/#126/#148/#149/#173/#196…），它们是**用确定性补 LLM 不可靠性的创可贴**，逐条累积后形成了「失败点奇怪」的体感——失败位置由正则表覆盖面决定，与用户语义无关。

### 2.2 回答为什么机械

1. **追问是模板**：clarification/needs_input 渲染走 `message_code` 模板（`web/plan_renderer.py:100-103`），文案固定，不携带会话上下文。
2. **Planner 无米下锅**：SessionFacts 刻意贫乏——只有计数和目录、无值（`contracts/session_facts.py:18-42`）；信息型问题也只能逐字引用 facts（planner.md:56）。它不是不会说人话，是**看不到可以说的人话素材**。
3. **上下文窗口极小**：最近 6 条历史 × 2000 字符（`planner.py:52-57`），多轮对话的来龙去脉被截断。

---

## 3. 业界对照：自主性阶梯与主流设计

### 3.1 自主性阶梯（L0-L4）与现状定位

```text
L0 单次调用        LLM + 检索 + few-shot，无编排
L1 Workflow        代码预定义路径，LLM 只做节点内工作     ← ★ ToolWithAgent 现状
L2 半动态 Workflow  orchestrator-workers / evaluator-optimizer
                   （LLM 动态拆解子任务、迭代打磨，骨架仍由代码持有）
L3 自主 Agent      LLM 在循环中自掌方向：感知→规划→行动→验证→重复
L4 多 Agent 组织   role-based 团队 + SOP（CrewAI/MetaGPT/AutoGen）
```

现状并非纯 L1——已有 L2 的局部元素：威胁链是「确定性的执行后续跑」（evaluator 触发的延伸执行）；FieldMappingBatchRunner 是 parallelization；Planner 的 clarification 判定是 routing。**缺的是把这些局部元素连成循环并交给 LLM 掌控。**

### 3.2 Anthropic 六模式对照

| 模式 | 业界定义 | ToolWithAgent 对应物 | 差距 |
|---|---|---|---|
| Prompt chaining | 串行步骤 + 程序化门禁 | 主执行链 | 已具备 |
| Routing | 先分类再分发 | Planner 的 decision 判别联合 | 已具备 |
| Parallelization | 并发 + 程序聚合 | FieldMappingBatchRunner（批 25/并发 3） | 已具备 |
| Orchestrator-workers | LLM 动态拆解子任务 | 无（子任务=固定 12 类步骤） | **缺** |
| Evaluator-optimizer | 生成→评估→反馈循环 | 仅 2 处带反馈重试 1 次（event_classify.py:219-239、regex_extract.py:104-126） | **局部具备，未成体系** |
| Autonomous agent | LLM 在循环中用工具、按环境反馈自掌方向 | 无（tools=[]、失败关闭） | **缺** |

### 3.3 生产级自主 agent 的机制清单（可借鉴做法 → 本仓落点）

| 机制 | 案例做法 | 本仓落点 |
|---|---|---|
| 执行循环 | Anthropic：LLM 在循环中基于环境反馈用工具；Claude Code「收集上下文→行动→验证→重复」 | 有界循环包裹 PlanExecutor（保留确定性骨架） |
| 任务分解外化 | Claude Code TodoWrite / Manus todo.md「复诵」 | PlanDecision 已是类型化 todo，补「可展示+可更新」 |
| 错误即反馈 | Manus：「错误纠正机制本身是 agent 区别于 workflow 的本质」，失败调用保留在上下文 | ExecutionReport 回喂恢复决策器（而非丢弃） |
| 自我验证 | Devin：跑测试→读报错→自改，72% 通过案例耗时 >10min | 步骤失败后先自查会话事实/可用字段/知识库再决定 |
| 工具接口设计（ACI） | SWE-agent：文件窗口 100 行最优、搜索只回文件名、edit 内置 linter、空输出显式反馈；「工具接口质量与 prompt 同量级」 | 知识数据化后按 ACI 原则设计查询工具 |
| 上下文管理 | Claude Code compaction（保决策/丢冗余）；Manus KV-cache 纪律（前缀稳定、append-only） | SessionFacts 受控扩容（目录+受控值+执行账本摘要） |
| HITL 门控 | Claude Code 权限分级（default→acceptEdits→plan→bypass），harness 强制执行 | 「只读自恢复自动、写库/导出需确认」分级 |
| 终止条件 | Anthropic 迭代上限；Devin 45 分钟硬上限 | 恢复预算 ≤N + 最大步数 + 验证通过即正常终止 |
| 主动求澄清 | Anthropic 实证：agent 主动澄清是最重要的监督形式之一（方案选择 35%/诊断信息 21%/模糊需求 13%） | 追问生成化：LLM 基于 facts 生成，带建议选项 |

### 3.4 两条重要警示

1. **多 agent 慎用**（Cognition《Don't Build Multi-Agents》）：「动作携带隐式决策，冲突的决策导致坏结果」；需要一致性的流水线用**单线程线性 agent**。本仓的规则抽取正是需要一致性的流水线——**不应走向多 agent**，单 Planner + 恢复循环即可。
2. **「less structure, more intelligence」有前提**（Manus）：结构性管道是弥补模型能力不足的拐杖，**仅在前沿模型上**可整体删除结构换智能。本仓接的是 deepseek/siliconflow 等多提供商，保留确定性骨架 + 局部自主是更稳的路线。Anthropic 原则同向：「只在复杂度能可度量改善产出时才增加」。

### 3.5 自主性的实证结论（Anthropic 2026-02 数百万交互研究）

- 自主性是「模型 × 用户 × 产品」共同构建的涌现属性，存在 deployment overhang（模型能承受的自主性超过实践赋予它的）。
- 有经验用户自动批准更多（20%→40% 会话）但打断也更频繁（5%→9% 轮次）——监督形态从「逐步审批」迁移到「监控+必要时干预」。
- 产品启示：**有效监督不需要批准每个动作，而是处于能干预的位置**——这正是「有界自恢复 + 人类兜底」的设计依据。

---

## 4. 差距清单（12 条摩擦点 × 6 轴）

| # | 轴 | 摩擦点 | 证据 |
|---|---|---|---|
| 1 | 控制流归属 | 单发规划无循环：LLM 任意时刻不拥有下一步决策权 | execution.py:162 |
| 2 | 控制流归属 | 执行结果永不反馈回规划（威胁链除外） | execution.py 无回喂通道 |
| 3 | 失败处理 | Planner 失败即弃、零重试（不变量） | planner.py:38-39 |
| 4 | 失败处理 | 执行非 SUCCESS 立即 break，无恢复路径 | execution.py:162-189 |
| 5 | 工具/知识面 | 决策时零工具；候选由系统预注入而非检索调用 | planner.py:45、team.py:47-49 |
| 6 | 工具/知识面 | 知识内嵌 prompt（130 威胁类/21 事件名），无法检索/更新/审计 | threat_type.md:26、event_classify.py:30-66 |
| 7 | 工具/知识面 | 新操作 = 4-6 处显式改动（prompt+StepSpec+Adapter+注册表+守卫） | ADR-0008 |
| 8 | 记忆/上下文 | 无跨会话记忆；知识库只写不读 | agent/memory/ 清空、log_pattern_store |
| 9 | 记忆/上下文 | SessionFacts 只有目录无值；历史 6 条×2000 字符 | session_facts.py:18-42 |
| 10 | 回答生成 | 追问/引导是 message_code 模板，无上下文无建议 | plan_renderer.py:100-103 |
| 11 | 回答生成 | prompt 规则与 Python 正则守卫双份维护，持续通胀 | planner.md 169 行 vs planner.py:86-108 |
| 12 | 遗骸代码 | 未接线 Agent/熔断/HITL 工具，README 与实际不符 | §1.4 清单 |

---

## 5. 候选改造卡片

### 卡片 1：失败自恢复层 RecoveryOrchestrator —— 强烈推荐

- **涉及文件**：`application/execution.py`、新增 `application/recovery.py`、`application/request_runtime.py`
- **问题**：needs_input/failed 一律立即交还人类（摩擦点 #3/#4）。事实上大多数失败原因（字段名不在白名单、参数缺一个、步骤依赖顺序错）在会话事实里就有答案——只是没人去看。
- **方案**（2026-09-10 拷问定稿，ADR-0011）：failed/needs_input 发生时，先进入有界自恢复（每计划 ≤2 次）：恢复决策器只见【类型化失败步骤 + error_code + SessionFacts】，**不见用户原文**；输出是受限修订枚举 retry_as_is / restructure / rederive_system_param / escalate，而非自由 PlanDecision。合法动作仅三类：①瞬时失败重试、②计划结构修正、③系统推导参数重推导（唯一需要 LLM 的一类，每计划 ≤1 次）。**用户显式点名的参数一律不碰**（含大小写差异）；会覆盖用户手动产物的动作视为不可逆，直接升级追问。修订后计划照走 policy 校验 + PlanExecutor。
- **收益**：把「机械追问」变成「先自救后求救」；杠杆——一个接缝覆盖全部 12 类步骤的失败恢复；局部性——恢复逻辑集中在一个模块，policy 校验资产全复用。**追问率应显著下降**（Phase 1 门禁指标）。
- **ADR 关系**：不违反 ADR-0005——初始规划仍一次成型；恢复决策器不重调 Planner。已定稿为 [ADR-0011 有界自恢复循环](../adr/0011-bounded-self-recovery.md)。

```diff
  for step in plan.steps:
      result = adapter.execute(step, ctx, deps)
-     if result.status != SUCCESS: break          # 失败即停 → 模板追问
+     if result.status != SUCCESS:
+         revision = orchestrator.decide(          # 不见用户原文；①② 确定性，③ 才调 LLM
+             failed_step, result.error_code, facts, budget)
+         if revision is ESCALATE: break           # 超出动作集/不可逆/预算尽 → 生成化追问
+         plan = apply(plan, revision)             # 仍是类型化计划，照过 policy 校验
+         continue outer_loop
```

### 卡片 2：ExecutionReport 回喂通道 —— 强烈推荐（卡片 1 的使能器）

- **涉及文件**：`contracts/session_facts.py`、`application/session_state.py`、`application/execution.py`
- **问题**：执行账本（ExecutionReport）生成后只用于渲染，规划侧永远看不到「刚才发生了什么」（摩擦点 #2/#9）。
- **方案**：账本受控摘要（每步 status/error_code/关键产出计数）扩入 SessionFacts 新字段 `recent_execution`；守卫保持「值不外泄」原则，只暴露目录与状态。
- **收益**：恢复决策器和后续 Planner 调用都能基于事实而非猜测；威胁链（ADR-0010）从特例变成通用机制的第一个用户。
- **ADR 关系**：延伸 ADR-0006（可引用会话产物）——从 2 个静态槽位扩展为受控执行摘要。

### 卡片 3：追问生成化 —— 强烈推荐

- **涉及文件**：`web/plan_renderer.py`、`application/request_runtime.py`、`agent/prompts/`（新增 clarification 生成 prompt）
- **问题**：追问是 message_code 模板（摩擦点 #10），用户体感「回答很机械」的直接来源。
- **方案**：clarification/needs_input 的**文案**改为 LLM 基于 SessionFacts（含最近执行摘要）+ 失败原因生成：说清楚「卡在哪、我试了什么、我建议选哪个、为什么」；与 Planner 同视野——**不见任何业务值**（拷问定稿）；choices 选项仍由确定性代码提供（结构不变，只是话术生成）。Anthropic 实证支持：agent 主动求澄清是最重要的监督形式，且呈现方案选择占比最高（35%）。
- **收益**：不动任何执行语义，纯 UX 杠杆；与卡片 1 组合后，剩下的追问都是「有上下文、带建议」的追问。
- **风险控制**：生成文案过现有渲染校验；choices 保持确定性来源，防止幻觉选项。

### 卡片 4：遗骸清理 —— 强烈推荐（零风险，建议最先做）

- **涉及文件**：`agent/core/team.py`、`agent/core/resilience.py`、`agent/tools/confirmation_tool.py`、`skills/multi-step-plan/`、`README.md`
- **问题**：§1.4 清单——遗骸误导维护者与 AI 导航，README 宣称与实际不符（熔断未接线、Team 无路由能力）。
- **方案**：逐项做**删除测试**——删除后复杂性若集中（而非移出到 N 个调用者），即删：EnumAgent/LogParserAgent、resilience.py（或接线，二选一，默认删）、confirmation_tool.py、multi-step-plan 遗物；README 修正宣称。82 个离线测试保障。
- **收益**：立刻降低认知成本与误导；「名为 agent 的层」与真实架构对齐，后续演进的接缝更干净。

### 卡片 5：威胁/事件知识数据化出 prompt —— 值得探索

- **涉及文件**：`agent/prompts/threat_type.md`、`agent/shared/event_classify.py`、`config/`
- **问题**：约 130 个威胁类内嵌 prompt 长列表（摩擦点 #6）——每次调用全量注入 token，无法单独更新/审计/检索。
- **方案**：威胁分类表迁为 config 数据（对齐 `threat_type_config.json` 既有方向）；prompt 只留判定规则 + 按需注入候选（如按日志特征预筛 top-N 类）。21 事件名白名单已是代码常量，可同步数据化。
- **收益**：token 下降、知识可治理（与 shared-log-knowledge 管理台同构）、为卡片 6 检索工具铺路。

### 卡片 6：标准字段候选「预注入 → 检索工具」 —— 值得探索（先评估再动）

- **涉及文件**：`agent/core/field_retriever.py`、`agent/core/team.py:47-49`
- **问题**：候选由系统预检索注入 prompt（摩擦点 #5），模型被禁止调查询工具——换字段/换策略都要再走一轮。
- **方案（谨慎）**：Phase 2 先做离线评估：对比「预注入 vs 检索工具」在 planner_eval 基线上的准确率/调用次数/成本。**批处理经济学可能证明现状更优**——batch runner 的批 25/并发 3 是精心调过的，检索工具化会改变调用形态。评估达标才动。
- **ADR 关系**：与 application-runtime-extraction PRD 的调用冻结不冲突（该冻结范围仅限该重构）。

### 卡片 7：日志知识库读回路 —— 值得探索（依赖 #190/#191）

- **涉及文件**：`agent/tools/log_pattern_store.py`、`application/adapters/log_parse.py`
- **问题**：知识库只写不读（摩擦点 #8），同类日志每次从零解析，无跨会话学习。
- **方案**：按已提交的 shared-log-knowledge-review PRD 实施读回路（结构 hash + Jaccard 候选检索，刻意不用 embedding——与其决策一致）；命中且确定性回放校验通过 → 跳过 LLM 直出结果。
- **收益**：这是「记忆」轴的第一个闭环；与该 PRD 的治理台（HITL）天然衔接。

### 卡片 8：全面 agent loop（L3） —— 待验证/暂缓

- **方案**：Planner 变成持续 function-calling 循环，LLM 逐步决定调哪个工具、何时结束。
- **暂缓理由**：(1) 需 Phase 1-3 的 evals 先证明可度量收益（Anthropic：复杂度只在 demonstrably 改善产出时增加）；(2) Cognition 单线程建议——本仓需要一致性，多决策点自由循环的错误复合风险高；(3) Manus「less structure」前提是前沿模型，本仓多提供商接入不满足。Phase 4 评估门禁后再议。

---

## 6. 演进路线图（摘要，详见 PRD）

```text
Phase 0  遗骸清理 + README 修正            零风险，立刻做
   ↓
Phase 1  失败自恢复 MVP（卡片1+2+3）        门禁：追问率↓ 完成率↑ 自恢复错误率≤阈值 成本无失控
   ↓
Phase 2  知识数据化（卡片5；卡片6 评估后定）  门禁：token/准确率评估
   ↓
Phase 3  日志知识库读回路（卡片7）           依赖 #190/#191；门禁：命中率+回放校验
   ↓
Phase 4  评估门禁 → 决定是否进一步放开       达标才议 L3（卡片8）
```

## 7. 首选推荐

**先做 Phase 0（清理，零风险）+ Phase 1（失败自恢复 + 回喂 + 追问生成化）**。理由：

1. 直击用户已确认的最痛体感（失败点奇怪 + 回答机械）；
2. 是全部候选中「杠杆/风险比」最高的一张：一个接缝（RecoveryOrchestrator）覆盖 12 类步骤的失败处理，且复用全部现有确定性资产（policy 校验、类型化计划、原子写回、审计账本）；
3. ADR-0010 威胁链已验证这条缝的技术可行性——Phase 1 是把特例泛化为机制；
4. 不动初始规划不变量（ADR-0005 保持成立），演进可逆（预算设 0 即回到现状行为）。

## 8. 回溯验证：Phase 1 能吸收多少历史上的「奇怪失败」（2026-09-10 补）

拆解 issue 后，用全部 53 个已关闭 bug（`gh issue list --state closed --label bug`）与 #60 验收轮 1 的实测发现做回溯分类，检验 Phase 1 三个机制的真实覆盖面：

| 类别 | 历史事故 | Phase 1 对应 | 数量 |
|---|---|---|---|
| ① 瞬时/基础设施失败 | #52 字段映射 90 秒双重 deadline 随机长尾整步失败；#48 batch 漏字段整步硬失败不重试 | #224（已在 FieldMappingBatchRunner 内修过，① 把同类保护推广到其余适配器） | **2** |
| ③ 系统推导参数错 | 无。#209 是用户换源后的清理 bug（会话级来源覆盖），不是自动判定错；#60 验收 1.8 把「判不出 → 降级其他」视为符合设计 | #225 | **0** |
| ② 计划结构错 | 无（`dependency_missing` 基线/产物/测试均 0） | 已砍 | **0** |
| 用户点名参数不存在 → 追问 | #196「用 abc 作为威胁类型来源」；#91 枚举填充缺目标字段 | #226 只改文案，行为按拷问结论保持追问 | **2** |
| Planner 意图理解/消歧 | #76 误判枚举提取为填充；#79 两步复合计划；#26 复合意图被快路径截断；#8 快路径误路由；#15 复合意图找不到目标字段；#146 合并意图单操作化；#46 Planner ValidationError 全部回退追问 | **Phase 1 不覆盖**（planner.md 规则 + planner_eval 遵循率是它的既有闭环；#46 属 Planner 自身失败，ADR-0005 明确排除重试） | **7** |
| 执行语义 / 数据 / 渲染 / 基础设施 | 其余（写回、覆盖、渲染截断、日志保留、KV 解析等） | 与自主性无关 | **≈42** |

**诚实结论：**

1. Phase 1 直接命中的历史事故只有 2 个，且都已在批处理层修过；③ 和 ② 都是 **0 事故**。#225 的价值是「设计上存在的降级路径」而非「发生过的痛」——建议排在 #226 之后实施，或等 #227 门禁数据再决定。
2. 历史上「失败点奇怪」的最大来源是 **Planner 意图理解（7 例）**，而这恰恰是 Phase 1 有意不碰的层（拷问 Q1/Q2 结论：自恢复不重新理解意图）。这层已有自己的闭环（planner.md 规则 + `outputs/planner_eval` 遵循率），代价是 prompt 持续通胀（摩擦点 #11）。
3. 因此 Phase 1 解决的是「回答机械」（#226）与「基础设施级失败」（#224），**不是**历史意义上的「奇怪失败」。若后者仍是首要痛点，#227 门禁后值得评估一张新卡片：**Planner 计划复核**（evaluator-optimizer 模式用在规划层——生成计划后用一次独立校验调用对照用户原文核对参数逐字性与操作类型，不通过则追问），它会触碰 ADR-0005 的一次调用不变量，需要单独拷问。

## 9. 来源

- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-agents-overview)（[直达](https://www.anthropic.com/engineering/building-effective-agents)）
- [Anthropic — Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic — Measuring AI agent autonomy in practice](https://www.anthropic.com/research/measuring-agent-autonomy)
- [OpenAI Agents SDK — Running agents / Handoffs / Sessions](https://openai.github.io/openai-agents-python/)
- [LangGraph — Overview / Graph API / Interrupts / Persistence](https://docs.langchain.com/oss/python/langgraph/overview)
- [HuggingFace — Introducing smolagents](https://huggingface.co/blog/smolagents)
- [CrewAI / AutoGen / MetaGPT 文档](https://microsoft.github.io/autogen/stable/)
- [Claude Code — Sub-agents / Permissions / Best Practices](https://code.claude.com/docs/en/best-practices)
- [OpenHands 论文 arXiv:2407.16741](https://arxiv.org/abs/2407.16741) · [Condenser 架构](https://docs.openhands.dev/sdk/arch/condenser)
- [SWE-agent 论文 arXiv:2405.15793](https://arxiv.org/abs/2405.15793) · [ACI 文档](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md)
- [Manus — Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Cognition — Introducing Devin](https://cognition.com/blog/introducing-devin) · [Don't Build Multi-Agents](https://cognition.com/blog/dont-build-multi-agents) · [SWE-bench Technical Report](https://cognition.com/blog/swe-bench-technical-report)
- [Levels of AGI（arXiv:2311.02462）](https://arxiv.org/abs/2311.02462)
