# PRD：ToolWithAgent 渐进式自主能力演进（失败自恢复 → 知识闭环）

> 状态：已确认（2026-09-10 grill-with-docs 拷问定稿；依据 [自主性差距报告](../research/agent-autonomy-gap-review.md)）
> GitHub 父 Issue：[#221](https://github.com/Jun-Wu05/ToolWithAgent/issues/221)；子 issue：#222 Phase 0 清理、#223 最近执行摘要、#224 自恢复①、#225 自恢复③（确定性）、#226 追问生成化、#227 门禁复核（HITL）
> 技术决策：[ADR-0011 有界自恢复循环](../adr/0011-bounded-self-recovery.md)；领域术语见 CONTEXT.md「自恢复」「最近执行摘要」条目与角色边界表
> UI 模式：`headless`（无新增可视化页面；追问文案经现有 Chainlit 渲染）
> 前置依赖：Phase 3 依赖 shared-log-knowledge-review（#190/#191）；Phase 0/1/2 无前置
> 实施状态：已拆解为 issue（见上）并放行（#228/#229/#230 均已进 master）；Phase 0 → 1 → 2 → 3 → 4 串行，每阶段评估门禁通过才进下一阶段
> 拆解时的已批准收缩：② 结构修正零证据不在 Phase 1 实施；③ 用确定性启发式（威胁链候选得分表下一候选），LLM 调用 0 次，满足 ADR-0011「≤1 次」上界
> 演进取向：渐进式半自主（L1 → L2 → 评估门禁后选择性 L3），**不推翻现有确定性骨架**

## 问题陈述

用户对系统的核心体感是「不智能」，具体为两点，且均有代码级根因：

1. **失败的点很奇怪**。大量失败由中文表层正则守卫触发（`agent/core/planner.py:86-108` 填充动词表、`application/execution_policy.py:127-158` 字段白名单），命中位置由正则覆盖面决定而非用户语义决定；Planner 失败即转追问、零重试（`planner.py:38-39`，一次 Planner 不变量）；执行步骤非 SUCCESS 立即 break（`application/execution.py:162`），系统没有「先看会话事实里有没有答案」的自恢复路径。
2. **回答很机械**。追问文案是 `message_code` 模板渲染（`web/plan_renderer.py:100-103`）；Planner 只见 SessionFacts 目录不见值（`contracts/session_facts.py:18-42`），历史窗口仅 6 条 × 2000 字符（`planner.py:52-57`），无法生成有上下文的自然回复。

同时，系统存在一批「名为 agent 实为遗骸」的模块（未接线的 EnumAgent/LogParserAgent、零引用的 resilience 熔断、从未挂载的 confirmation_tool），README 宣称与实际不符，误导维护与后续演进。

按 Anthropic《Building Effective Agents》分类，本系统是 workflow（固定编排）而非 agent；本 PRD 不改变这一定位的正确性取舍（ADR-0005 失败关闭、类型化计划、原子写回、审计账本全部保留），而是在已被 ADR-0010 威胁链验证过的「执行后构造新计划续跑」接缝上，**渐进引入有界自恢复与观察反馈**。

## 解决方案（终极实现形态）

保留全部确定性资产，新增四个模块，把「一次规划 → 顺序执行 → 失败即停问人」升级为「一次规划 → 有界循环（执行 → 观察 → 自恢复 → 终止判定）」：

```diff
 Planner（一次调用不变量，ADR-0005 保留）
   职责不变：用户话语 → 初始 PlanDecision
+ RecoveryOrchestrator（自恢复决策器）
   输入：类型化失败步骤 + error_code + SessionFacts（含最近执行摘要）——不含用户原文
   输出：受限修订枚举 retry_as_is / restructure / rederive_system_param / escalate
   ①瞬时重试 ②结构修正 = 确定性策略；③系统推导参数重推导 = 唯一 LLM 调用
   不修改用户显式点名参数（含大小写差异）；修订后计划照过 policy 校验 + PlanExecutor
+ RecoveryBudget（计划级预算）
   每计划 ≤2 次、③ ≤1 次、同步骤 ① ≤1 次；可配，0 = 现状；会话级只计数
+ ObservationBuilder（最近执行摘要）
   ExecutionReport → 当前 + 上一份计划的步骤级摘要入 SessionFacts.recent_execution
   每步仅 step_id/type/status/error_code/产物目录与计数，不含值
+ ClarificationComposer（追问生成化）
   升级追问文案由 LLM 基于 SessionFacts + 失败原因生成（卡在哪/试了什么/建议选哪个）
   与 Planner 同视野（不见业务值）；choices 仍由确定性代码供给；文案过渲染校验
 PlanExecutor + 12 个类型化步骤        ← 保留，角色升级为「agent 的工具集」
 保障层：Pydantic/白名单/原子写回/审计账本/HITL 兜底 ← 全保留
```

**终止判定**：计划全部 SUCCESS → 正常终止；动作超出合法动作集 / 动作不可逆（会覆盖用户手动产物）/ 预算穷尽 / 修订连续非法 → 升级追问（ClarificationComposer 文案）。预算设 0 即完全回到现状行为（演进可逆）。

**非目标**：不推翻 ADR-0005（初始规划仍一次成型，Planner 自身失败不重试）；不允许语义改参；不迁移 OpenAI Agents SDK / LangGraph；不引入多 agent 协作（Cognition 单线程警示，规则抽取需要一致性）；不一步到位 L3 全自主（需 Phase 4 评估门禁）；不改变任何现有用户可观察的导出格式与 Session 数据生命周期。

## 用户故事

- **US-1：**作为安全分析师，我在步骤因超时、限流或坏 JSON 失败时，希望系统原样重试一次而不是立刻报错，以便瞬时故障不打断我的工作。
- **US-2：**作为安全分析师，我在 Planner 把步骤顺序排错时，希望系统自动重排后继续，以便不为系统自己的编排错误买单。
- **US-3：**作为安全分析师，我在威胁链自动选的来源字段结果全落「其他」时，希望系统换一个候选字段重跑一次，以便不必手动纠正系统自己猜错的值。
- **US-4：**作为安全分析师，我亲口点名的字段名（哪怕只差大小写）不希望系统擅自替换，以便导出配置不被错误改参污染——系统应停下追问并列出可用字段。
- **US-5：**作为安全分析师，我被追问时希望收到「卡在哪、系统试了什么、建议选哪个」的自然语言说明（而非 message_code 模板），以便一次回复就能推进任务。
- **US-6：**作为安全分析师，我花时间做的手动字段调整、规则数据源字段、枚举映射附件不希望被任何自恢复动作静默覆盖，以便自恢复只帮忙不添乱。
- **US-7：**作为新用户，我希望同类日志第二次解析明显更快且结果一致（知识库读回路），以便复用历史工作。
- **US-8：**作为项目维护者，我希望 README 与代码一致、遗骸模块被清理，以便维护与 AI 导航不再被误导。
- **US-9：**作为项目负责人，我希望每个阶段的自主度放开都有评估门禁（planner_eval 基线对比），以便复杂度只在可度量改善时增加。
- **US-10：**作为运维人员，我希望恢复调用独立计数、可归因、可通过预算 0 一键回滚，以便延迟与费用不失控。
- **US-11：**作为领域知识维护者，我希望威胁/事件分类从 prompt 文本变为可治理数据，以便独立更新、审计并与知识治理台衔接。

## 实现决策

### Phase 0：遗骸清理与文档对齐（零风险）

删除测试逐项执行：EnumAgent/LogParserAgent（`agent/core/team.py:156-214`）、`agent/core/resilience.py`（或接线，默认删）、`agent/tools/confirmation_tool.py`、`skills/multi-step-plan/` 遗物；README:158 等宣称修正为实际架构。全量 pytest 绿为验收。

### Phase 1：失败自恢复 MVP（首个垂直切片，ADR-0011）

1. **ObservationBuilder**：ExecutionReport → 最近执行摘要（当前 + 上一份计划）扩入 SessionFacts.recent_execution；每步仅 step_id/type/status/error_code/产物目录与计数，遵守「值不外泄」。新计划开始滚动，主数据替换清空。ADR-0010 威胁链保持行为不变，成为该机制首个消费场景。
2. **RecoveryOrchestrator**：新模块 `application/recovery.py`。输入不含用户原文；输出受限修订枚举。①② 为确定性策略（错误码分类表 + 依赖图重排）；③ 为独立类型化 LLM 调用（输出 schema = 重推导目标 + 新策略选择 + 理由）。修订后计划必须通过 `DefaultExecutionPolicy.validate_plan / validate_step`。
3. **不可逆门禁**：修订动作会覆盖或删除用户手动产物（手动字段调整、规则数据源字段、枚举映射附件贡献、手工改过的事件名称）→ 不进入自恢复，直接升级追问。判定为确定性函数（读 SessionState 手动产物标记）。
4. **RecoveryBudget**：计划级，每计划合计 ≤2、③ ≤1、同步骤 ① ≤1；配置项，0 = 现状；会话级计数供指标。
5. **ClarificationComposer**：升级追问文案生成；输入 = SessionFacts + 失败 error_code + 恢复尝试摘要 + 确定性 choices；不见业务值；生成文案过渲染校验，choices 不得被生成器增删改。
6. **审计**：每次自恢复/升级追问记录恢复类型、error_code、修订内容、结果；独立 `recovery` logger，挂既有 TraceContext。
7. **灰度**：按 step.type 白名单启用，先只读类（枚举提取/字段映射/日志类型提取），后写类（填充/字段调整）。

### Phase 2：知识数据化与工具面评估

威胁分类表（`threat_type.md:26` 约 130 类）迁 config 数据 + 按需注入；21 事件名常量同步数据化。标准字段候选「预注入 vs 检索工具」先离线评估（planner_eval 对比准确率/调用次数/成本），达标才改——批处理经济学可能证明现状更优。

### Phase 3：日志知识库读回路

按 shared-log-knowledge-review PRD 实施（结构 hash + Jaccard，不用 embedding，与该 PRD 决策一致）；命中且确定性回放校验通过 → 跳过 LLM 直出。依赖 #190/#191。

### Phase 4：评估门禁与后续放开

汇总 Phase 1-3 指标，决定是否议 L3（持续规划循环）。不达标即停在当前层级。

### 与现行决策的关系

- **ADR-0005**：保留不违反——初始规划仍恰好一次；自恢复不重调 Planner，Planner 自身失败不在自恢复范围。
- **ADR-0008**：保留——12 类型化步骤 + 声明式注册表即 agent 工具集。
- **ADR-0006**：延伸——产物槽位之外新增最近执行摘要，仍不暴露业务值。
- **ADR-0010**：泛化——威胁链行为不变，成为执行摘要机制首个消费场景。
- **ADR-0011**：本 PRD Phase 1 的技术决策记录（合法动作集、隔离、预算、不可逆判据、追问视野、摘要粒度）。
- **application-runtime-extraction 的策略冻结**：范围仅限该重构；本 PRD 的恢复调用是新增调用点，不属于其冻结的既有阶段。
- **CONTEXT.md「不代用户改参」**：自恢复是其延伸而非例外——只处理系统自己造成或自己判定的问题。

## 测试决策

- **RecoveryOrchestrator**：接缝 = `application/recovery.py` 纯函数 + 注入 fake LLM（仅 ③ 路径）；覆盖：①② 不触发 LLM 调用断言、修订枚举每种分支、修订后计划过/不过 policy、用户点名参数不变断言（含大小写差异场景 → escalate）、预算穷尽转升级追问、不可逆门禁直转升级追问、预算 0 行为逐字节等于现状。
- **ObservationBuilder**：接缝 = ExecutionReport → SessionFacts 投影纯函数；覆盖：当前 + 上一份滚动、主数据替换清空、值不外泄断言（序列化不含业务值样本）。
- **ClarificationComposer**：接缝 = 生成文案 + 确定性 choices；覆盖：choices 与守卫输出逐项一致、生成器输入不含业务值断言、渲染不回归。
- **评估门禁（Phase 1 验收）**：复用 `outputs/planner_eval/` 基线冻结对比 + e2e 脚本；指标：追问率下降、任务完成率上升、③ 修订被 policy 拒绝率 ≤ 阈值、恢复调用成本占比可控；现有 82 个离线测试全绿，无行为回归。
- **灰度**：按 step.type 白名单启用，先只读类，后写类。

## 拷问结论（2026-09-10 grill-with-docs，已定稿）

| # | 问题 | 结论 | 落点 |
|---|---|---|---|
| 1 | 自恢复修改计划的边界 | 用户显式点名参数一律不碰（含大小写差异）；仅系统推导参数可重推导 | CONTEXT.md「自恢复」 |
| 2 | 合法动作集与隔离 | ①瞬时重试 ②结构修正 ③系统推导参数重推导；不见用户原文；输出受限修订枚举；①②确定性、③ 才用 LLM | CONTEXT.md + ADR-0011 |
| 3 | 不可逆判据 | = 覆盖或删除用户手动产物；导出/写库/删字段本身不算 | CONTEXT.md「用户手动产物」 |
| 4 | 预算口径与 N | 计划级；每计划 ≤2、③ ≤1、同步骤 ① ≤1；0 = 现状；会话级只计数 | ADR-0011 |
| 5 | 追问生成器视野 | 与 Planner 同视野，不见任何业务值 | CONTEXT.md 角色边界 |
| 6 | 最近执行摘要 | 当前 + 上一份计划；每步 step_id/type/status/error_code/产物目录与计数 | CONTEXT.md「最近执行摘要」+ ADR-0011 |
| 7 | ADR-0011 | 现在写，状态已接受 | docs/adr/0011-bounded-self-recovery.md |
