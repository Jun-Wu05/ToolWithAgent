# PRD：ToolWithAgent 领域能力模块深化

| 属性 | 内容 |
| --- | --- |
| 状态 | 待人工评审 |
| 日期 | 2026-08-31 |
| 上游 PRD | GitHub #130「应用运行时提取与零回归架构深化」 |
| 评审入口 | GitHub #145「HITL：评审并建立第二阶段领域能力模块深化 PRD」 |
| 产品形态 | Headless；不新增或修改 UI |

## 1. 执行摘要

第一阶段已把 Chainlit 适配、Application 运行时、类型化契约和领域能力的依赖方向固化下来。第二阶段需要继续深化标准字段、日志分类和字段调整能力，使能力所有权、公开入口、策略边界与测试接缝更清晰，同时避免把“文件较大”或“静态分析未发现调用”误当作质量或删除依据。

本 PRD 建议先建立领域能力目录与只读 `StandardFieldCatalog`，再分别深化日志分类策略和 `FieldSkillAdapter`。所有迁移必须保留既有公开行为；Base64 Tool、Web 单常量模块、重复日志桥接状态及其他疑似无调用模块只进入证据审计，未经本 PRD 人工确认和后续独立 Issue 批准，不得删除、合并或顺手重构。

## 2. 背景与问题

当前领域能力横跨 `agent/core/`、`agent/tools/`、`agent/shared/`、日志 Pipeline、解析规则生成、`application/adapters/` 和 `skills/*/scripts/`。物理位置与能力所有权并不总是一致，主要问题包括：

1. 标准字段资源读取、同义词、索引、embedding、缓存和排序集中在大型检索模块中，`standard_mapper.py` 还存在部分重复读取逻辑。
2. 日志分类器同时承担 JSON/KV/Header 路径选择、特征定位、覆盖率、LLM fallback 与后处理，策略边界不够显式。
3. `FieldSkillAdapter` 同时承担动态加载、字段寻址、规则范围、引用守卫、事件绑定、错误映射和原子写回。
4. 静态源码分析无法可靠识别函数内延迟导入、包级重导出和动态注册，可能把在用模块误报为无调用。
5. 缺少统一的能力目录与删除证据门禁，维护者不容易区分公共入口、领域策略、集成适配器和历史候选。

## 3. 目标

- 建立可维护、可检索的领域能力目录，记录能力所有者、公共入口、依赖方向、测试接缝和生命周期状态。
- 建立只读 `StandardFieldCatalog`，统一标准字段 schema、名称/别名 lookup 和确定性索引语义。
- 将 embedding、缓存和候选排序保留为可替换的检索策略，不让 Catalog 承担网络与缓存生命周期。
- 使日志分类的策略选择、覆盖率计算和 fallback 边界显式化，同时保持 `LogParseAdapter` 行为不变。
- 深化 `FieldSkillAdapter` 的共享策略边界，同时保持 Skills 脚本为数据变换的单一事实源。
- 对疑似无调用或重复状态模块执行可复核的五类证据审计。
- 通过最高层测试接缝保护重构自由与零回归。

## 4. 非目标

- 不在本 PRD 或 #145 中直接删除 Base64 Tool、Web constants、`resilience.py`、`confirmation_tool.py` 或其他候选。
- 不因文件超过建议行数而机械拆分。
- 不改变日志分类、字段映射、字段调整、填充、事件名称标注或解析规则的产品语义。
- 不复制 `skills/*/scripts/` 中的数据变换逻辑到 Application 或 Agent 层。
- 不重新设计第一阶段已经确立的 PlannerAgent、PlanExecutor、StepAdapter、SessionFacts 或 Application/Web 物理边界。
- 不新增 UI 页面、控件或交互流程。
- 不在父 PRD 人工评审前创建实现 Issue。

## 5. 领域语言与架构约束

本 PRD 沿用 `CONTEXT.md` 的术语：映射、填充、分类特征字段、字段调整、事件名称标注、模型提供商、解析规则、子规则、入口规则、标准字段、主数据和可引用会话产物。

必须继续遵守 ADR-0005、ADR-0006、ADR-0008 与 ADR-0009：

- `web/` 只拥有 Chainlit 输入、生命周期、进度和渲染。
- `application/` 拥有运行时；`application/adapters/` 拥有 StepAdapter。
- Application core 只依赖 Contracts 与标准库；Adapter 可以依赖 Agent、领域能力与 Skills。
- 不允许领域模块反向依赖 Web。
- Skills 脚本是字段调整数据变换的单一事实源。
- 难以逆转的新技术决策才进入 ADR；普通文件移动或内部提取不单独建立 ADR。

## 6. 推荐实施顺序

### 阶段 A：能力目录与 StandardFieldCatalog

先建立领域能力清单和 Catalog characterization tests，再通过兼容入口逐步迁移标准字段读取者。现有 `application.field_runtime` 等公共入口的身份、参数和返回格式必须保持兼容。

### 阶段 B：日志分类策略深化

在 `LogParseAdapter` 公开行为不变的前提下，显式化 JSON、KV、Header 路径选择、覆盖率与 fallback 策略。每次提取采用独立垂直 Issue，不允许一次性重写分类 Pipeline。

### 阶段 C：Field Skill Adapter 深化

优先提取共享策略，而不是按五种操作机械复制 Adapter。候选边界包括：

- `FieldNameResolver`
- `RuleScopeResolver`
- `ReferenceGuard`
- `EventBindingPolicy`
- Skill registry / invocation seam

`FieldSkillAdapter` 继续负责类型化步骤翻译、进度发布、稳定错误映射、Session 原子写回与 Artifact 构造。

### 阶段 D：独立删除审计

强候选只能进入独立审计 Issue。审计通过不等于自动删除；删除仍需新的、明确授权的实现 Issue。

## 7. 功能需求与验收标准

### US-1：建立领域能力目录

作为架构维护者，我希望能按能力而非偶然文件位置导航代码，以便判断所有权、依赖方向和变更影响。

验收标准：

- 目录至少记录能力名称、职责、领域术语、公共入口、上游、下游、测试接缝、生命周期状态和负责人类别。
- 能区分 public entrypoint、domain transformation、policy、integration adapter、legacy/audit candidate。
- 记录延迟导入、包级重导出或动态加载等静态分析盲区。
- 目录是导航资产，不成为运行时服务定位器或新的全局注册中心。

### US-2：建立只读 StandardFieldCatalog

作为字段映射能力维护者，我希望标准字段 schema、名称和别名查询只有一个明确边界，以减少重复读取与隐式耦合。

验收标准：

- Catalog 统一标准字段、别名和确定性名称索引的加载与查询语义。
- Catalog 不发起模型/embedding 网络调用，不管理检索缓存生命周期，不执行候选排序。
- `field_retriever.py`、`standard_mapper.py` 和 Prompt loader 的迁移顺序有明确兼容计划。
- 现有公共入口、返回结构、字段排除规则与日志脱敏行为保持兼容。
- 缺失、损坏、schema 不兼容资源具有稳定、可测试的失败策略。

### US-3：显式化日志分类策略

作为日志解析维护者，我希望能独立理解和测试 JSON、KV 与 Header 分类路径，以便修改单一路径时不破坏其他路径。

验收标准：

- 策略选择、覆盖率计算、LLM fallback 与 postprocess 的边界可独立测试。
- `LogParseAdapter` 的调用顺序、Session 写回、进度、稳定错误和失败关闭语义不变。
- 显式分类特征字段、marker、coverage、单意图调用次数均有回归保护。
- `log_pattern_store.py` 被标记为延迟导入的在用知识库能力，不再列为无调用模块。
- 知识库存储失败继续保持非致命，不改变主分类结果。

### US-4：深化 Field Skill Adapter

作为字段调整维护者，我希望共享寻址与守卫策略有明确边界，以便扩展字段调整能力而不复制业务规则。

验收标准：

- 五类类型化步骤继续通过声明式注册表调用真实 Skills 脚本。
- Skills 脚本继续拥有添加、删除、合并、Base64 解码和正则提取的数据变换。
- 共享字段解析、规则范围、引用守卫和事件绑定策略可独立测试和复用。
- Session 写回保持原子性；失败不得留下部分修改。
- Artifact、稳定错误码、事件名称/事件级别绑定和 per-entity 行为保持兼容。

### US-5：建立删除证据门禁

作为仓库维护者，我希望删除候选必须经过统一审计，以避免静态分析误报导致生产回归。

验收标准：

- 每个候选逐项记录生产导入、动态注册、包级重导出、测试依赖和外部依赖证据。
- 仓库内“零引用”不得表述为外部依赖已经绝对为零。
- 外部依赖必须由维护者、部署清单、发布契约或等价证据确认。
- 证据不足时状态为 `needs-info` 或保留，不允许删除。
- 审计、characterization、删除分别使用独立 Issue；任一步不得顺手扩大范围。

### US-6：采用软性文件预算

作为评审者，我希望大文件能触发职责审查，但不会被机械地判为低质量。

验收标准：

- 新增或深化后的单一模块接近 400–500 行时，PR 必须解释其深职责或提出后续拆分 seam。
- 行数预算不作为 CI 硬门禁，不直接产生质量评分。
- 是否拆分同时考虑职责深度、耦合、公开契约、变化率和测试接缝。
- 小文件同样需要满足职责与依赖方向要求。

## 8. 四组最高层测试接缝

“最高层”表示优先保护系统对外可观察的稳定边界，而不是把内部函数结构写死。各组下面仍可增加单元测试。

### 8.1 Catalog 兼容接缝

- 标准字段与同义词资源 schema 兼容。
- 名称/别名 lookup 与索引确定性。
- cache meta 兼容和稳定失败策略。
- 现有公共入口身份、参数和返回格式。
- 字段排除与检索日志脱敏。

### 8.2 Log Parser 行为接缝

- `LogParseAdapter` 调用顺序、Session、进度和稳定错误。
- JSON/KV/Header 策略选择与显式分类特征字段。
- coverage、marker、fallback 和 postprocess。
- 单意图执行的调用次数。
- 分类失败不覆盖历史成功结果，知识库存储失败不影响主结果。

### 8.3 FieldSkillAdapter 契约接缝

- 类型化 Step 到声明式 Skill 调用的映射。
- 字段词汇、规则范围、引用与事件绑定守卫。
- Session 原子写回与失败不部分修改。
- Artifact 下载内容和稳定错误码。
- 五类操作及 per-entity 行为。

### 8.4 删除审计门禁接缝

- 自动扫描生产导入、动态注册、包级重导出和测试依赖。
- 对延迟导入与动态加载进行专项检查，避免静态 AST 假阴性。
- 外部依赖由人工证据确认。
- 未获得父 PRD 评审和独立删除 Issue 时，测试或流程必须阻止删除范围混入。

## 9. 当前证据矩阵

| 对象 | 仓库内证据 | 当前分类 | 本 PRD 决策 |
| --- | --- | --- | --- |
| `agent/tools/base64_tool.py` | 未发现生产导入、动态注册、重导出或测试 | 强审计候选 | 保留；后续独立审计 |
| `web/constants.py` | 单常量，未发现调用或测试 | 强审计候选 | 保留；后续独立审计 |
| Web 日志桥状态 | `global_state.py` 与 `llm_client.py` 各自维护安装状态 | 重复所有权候选 | 保留；后续建立单一生命周期 seam |
| `agent/tools/log_pattern_store.py` | 被知识库 wrapper 与 Header 路径延迟导入 | 在用能力 | 移出死代码候选；补直接测试 |
| `agent/core/resilience.py` | 未发现仓库内调用、导出或测试 | 强审计候选 | 保留；先确认外部依赖与历史意图 |
| `agent/tools/confirmation_tool.py` | 未发现仓库内调用、导出或测试 | 强审计候选 | 保留；与现行类型化 HITL 对照审计 |

完整证据基线位于 `outputs/issue145-domain-evidence/20260831/evidence.md`，作为评审附件，不作为生产运行时输入。

## 10. 建议的后续垂直 Issue

以下仅为父 PRD 获批后的拆解顺序，本 PRD 发布时不自动创建：

1. 建立领域能力目录与 ownership schema。
2. 为标准字段资源和现有入口建立 characterization tests。
3. 引入只读 StandardFieldCatalog 并迁移一个真实调用者。
4. 完成剩余标准字段读取者兼容迁移。
5. 提取一条日志分类策略 seam，并保持 Adapter 零回归。
6. 提取一条 Field Skill 共享策略 seam，并保持 Skills 单一事实源。
7. 为日志知识库存储补直接测试与兼容说明。
8. 分别审计 Base64 Tool、Web constants、重复日志桥状态、resilience 与 confirmation tool。

每个 Issue 必须是可独立领取、可回滚、可验证的垂直切片；不得创建“重写整个领域层”式大包任务。

## 11. 发布与回滚策略

- 先测试后迁移，每次只迁移一个公开调用路径。
- 旧公共入口在消费者迁移完成前保留兼容转发。
- 不采用双写领域状态；Session 仍由 Application 运行时原子提交。
- 任一 characterization 或架构测试失败时，回滚当前垂直切片，不扩大修复范围。
- 删除候选的回滚策略必须在独立删除 Issue 中说明，本 PRD 不预先授权。

## 12. 风险与缓解

| 风险 | 缓解措施 |
| --- | --- |
| Catalog 变成新的巨型服务 | 限定为只读 schema/lookup；检索策略和缓存生命周期留在外部 |
| 为追求小文件造成浅模块和跳转膨胀 | 行数只作 soft trigger，以职责深度和公开契约决定拆分 |
| 日志分类策略提取改变隐含语义 | 先建立 Adapter、coverage、fallback 和调用次数 characterization |
| Field Skill 规则被复制 | 强制 Skills 脚本保持数据变换单一事实源 |
| 静态分析误删延迟导入模块 | 五证据门禁加延迟导入专项扫描和人工外部依赖确认 |
| 父 PRD 变成无边界重构 | 每个能力使用独立垂直 Issue，父 PRD 评审前不创建实现任务 |

## 13. 成功指标

- 标准字段读取具有一个明确 Catalog 边界，重复资源读取减少且旧入口零回归。
- 领域能力目录覆盖本 PRD 四类核心能力和全部审计候选。
- 四组最高层测试接缝在 CI 中稳定通过。
- 日志分类与字段调整的内部策略可独立测试，Application/Web 依赖方向不倒置。
- 所有删除候选都有五类证据记录；本阶段无未经授权的删除或合并。
- 后续实现 Issue 均能独立领取、验证和回滚。

## 14. HITL 决策记录

2026-08-31，维护者确认：

- 接受 `StandardFieldCatalog + capability inventory` 优先，日志分类策略与 `FieldSkillAdapter` 后置。
- 接受 Catalog、Log Parser、FieldSkillAdapter、删除审计四组最高层测试接缝。
- 接受 400–500 行作为软性评审触发器，而非硬质量门禁。
- GitHub PRD 与后续 Issue 使用中文，代码标识符、路径和仓库既有英文标签保持原样。

本 PRD 发布后仍保持 `ready-for-human`，等待父 PRD 人工评审；评审通过前不得创建实现 Issue。
