# ToolWithAgent 应用运行时提取与零回归架构深化 PRD

> 状态：已确认，发布为 GitHub 父 Issue；待稳定基线后实施  
> GitHub 父 Issue：[#130](https://github.com/Jun-Wu05/ToolWithAgent/issues/130)  
> UI 模式：`headless`  
> 实施状态：仅建立 PRD 与 Issues；当前功能工作区完成并形成稳定基线前不得实施

## 问题陈述

ToolWithAgent 已通过独立 PlannerAgent、类型化计划、PlanExecutor、StepAdapter、SessionFacts 和可引用会话产物建立了正确的业务执行模型，但物理模块归属未完整表达这套设计：无 Chainlit 依赖的 PlanExecutor、SessionState 和 StepAdapter 实现仍位于 Web 包；SessionFacts 数据接口同时包含会话投影实现，并反向依赖 Web 实现；字段映射 Adapter 承担了批处理、重试、补查、产物与提交等过多实现；上传文件解码仍位于一个被误命名为 Agent 的模块；Prompt 文件与加载实现分散在两个包。

这使维护者难以区分 Chainlit 入口、应用运行时、类型化接口和领域实现，形成 `contracts → web → agent` 的反向依赖，并增加后续替换界面入口、迁移 Agent 框架和定位字段映射问题的成本。

本次工作不能影响任何现有功能使用。用户可观察行为、类型化计划语义、模型调用阶段、重试与并发策略、Session 数据生命周期、错误码、导出格式、按钮行为和 Chainlit 交互均须保持不变。当前工作区仍有功能开发尚未完成，因此本 PRD 只提前固化计划和创建 Issues；实施必须等待稳定基线建立后再严格串行进行。

## 解决方案

新增顶层 `application` 包，承载与 Chainlit 和具体 Agent 框架无关的应用运行时。Web 包收缩为 Chainlit 入口、上传交互、设置和渲染；Contracts 包只保留类型化接口与不变量；Application 的运行时核心只依赖 Contracts 和标准库；Application Adapters 在明确接缝处对接专业 Agent、领域函数和字段调整 Skills。

迁移采用按业务链路的垂直切片：每个 Issue 都从类型化步骤贯穿 PlanExecutor、StepAdapter、领域实现、Session 写回、ExecutionReport 和回归测试。旧导入路径在迁移期仅作兼容重导出，不保留第二份实现；全部内部调用者迁移后，在本 PRD 完成前删除兼容入口。

字段映射先原样迁移，再独立提取已在领域文档中定义的 FieldMappingBatchRunner。该提取只移动现有批处理实现的模块所有权，不改变批大小、并发、超时、重试、补查、模型调用或原子写回行为。上传文件解码从误命名的 Agent 模块原样迁入 Application 文件输入模块；不同业务 Base64 导出格式保持各自现状，不强制统一。Prompt 加载实现归入 Prompt 包，但 Prompt 内容、函数名称、返回类型和缺失策略全部保持不变。

## 用户故事

- **US-1：**作为项目维护者，我想从目录结构直接区分 Chainlit 入口与应用运行时，以便无需阅读大量实现即可找到一次计划执行的真实所有者。
- **US-2：**作为项目维护者，我想让 PlanExecutor、SessionState 和类型化步骤执行不依赖 Chainlit，以便未来从 CLI、HTTP 或其他入口复用相同业务行为。
- **US-3：**作为契约维护者，我想让 Contracts 只定义类型和不变量，不导入 Web 或领域实现，以便契约保持稳定并避免反向依赖。
- **US-4：**作为现有用户，我想在架构重构后继续以完全相同的方式上传文件、输入自然语言、点击按钮和下载结果，以便无需学习或适配任何新行为。
- **US-5：**作为现有用户，我想让日志类型提取、字段映射、事件名称标注、枚举提取、威胁类型映射、填充、取消映射、字段调整和导出结果保持不变，以便已有工作流不受影响。
- **US-6：**作为运维人员，我想让相同请求的 Planner、专业 Agent、批次、重试和补查次数不因重构增加，以便延迟、费用和限流风险不发生意外变化。
- **US-7：**作为字段映射维护者，我想通过一个 FieldMappingBatchRunner 接口使用现有分批、并发、超时拆批、重试和漏字段补查行为，以便批处理知识集中且 Adapter 不再泄漏执行策略。
- **US-8：**作为文件上传链路维护者，我想让 Base64、JSON 和纯文本解码归属于应用文件输入模块，以便确定性文件处理不再伪装成 Agent 实现。
- **US-9：**作为 Prompt 维护者，我想在 Prompt 包中找到 Prompt 文件和对应加载实现，以便路径、编码和缺失行为具有局部性。
- **US-10：**作为重构实施者，我想逐条迁移业务链路并临时兼容旧导入路径，以便每个 Issue 完成后项目仍可运行和独立验收。
- **US-11：**作为测试维护者，我想通过最高层级接缝验证业务行为，并通过静态规则阻止依赖方向再次退化，以便测试保护契约而不是绑定私有实现。
- **US-12：**作为项目负责人，我想在当前功能开发完成前阻止任何架构 Issue 被领取，以便未提交功能与架构迁移不会混在同一基线中。
- **US-13：**作为项目负责人，我想让所有架构 Issues 严格串行放行，以便多个 Agent 不会同时修改核心运行时和相同导入路径。
- **US-14：**作为后续架构维护者，我想在本阶段完成后自动进入“领域能力模块深化”评审，以便标准字段体系、领域能力目录和疑似无调用模块不会被遗忘。
- **US-15：**作为新加入的维护者，我想让 README、领域上下文、现行架构说明、ADR、测试手册和源码分析快照与重构后的代码一致，以便不会被已经失效的目录、依赖方向或阅读路径误导。

## 实现决策

### Application 运行时模块归属

新增 Application 运行时模块，按执行、会话、可引用会话产物、进度、文件输入和 StepAdapter 组织。Web 只保留 Chainlit 生命周期、消息、按钮、上传交互、设置和渲染。Application 运行时不得依赖 Chainlit。

### Application 内部单向依赖

执行、会话、可引用会话产物和进度等运行时核心只依赖 Contracts 与标准库；Application Adapters 可以在接缝处依赖专业 Agent、领域函数和 Skills；Web 只能通过 Application 公共入口执行业务。`create_default_adapters` 继续作为唯一适配器组合入口。

### Contracts 接口与 SessionFacts 投影分离

SessionFacts 类型、可引用会话产物类型和 Planner 契约保留在 Contracts；会话读取、可用字段收集、配置目标绑定和事实投影实现迁入 Application Session 模块。Contracts 不再导入 Web、Application、Chainlit 或领域实现。

### 业务链路垂直迁移

迁移按业务链路切片，而不是按目录或文件水平切片。每个切片包含类型化计划、PlanExecutor 分派、StepAdapter、领域调用、Session 写回、ExecutionReport 和相关测试，完成后必须有一条可独立验证的完整路径。

### 临时兼容入口

迁移期旧导入路径只允许从新模块重导出相同对象，不得保留或执行第二份实现。新代码禁止继续导入旧路径。仓库外部已确认没有直接 Python 模块依赖，因此所有临时兼容入口必须在本 PRD 完成前删除。

### FieldMappingBatchRunner 行为冻结提取

字段映射先原样迁入 Application Adapters，再独立提取 FieldMappingBatchRunner。Runner 只接收从现有 Adapter 原样迁入的分批、并发、模型调用、超时拆批、重试、`Retry-After`、漏字段补查、去重和顺序保持实现；Adapter 保留 StepSpec 翻译、进度、产物构建、事件名称标注挂接和 Session 一次性提交。本 PRD 禁止调整任何执行策略。

### 上传文件解码归属

现有 `simple_decode` 及其 Base64 尝试、JSON 验证、纯文本回退、normalize 字段提取、original_log 提取和行数限制原样迁入 Application 文件输入模块。旧 Agent 包入口迁移期兼容重导出，内部调用者切换后删除。`simple_encode` 是否保留只依据调用审计，不在本 PRD 顺手改变其他业务编码入口。

### Base64 业务格式保持

解析规则、字段映射、枚举填充、威胁类型填充和配置产物的 Base64 输出继续保留各自既有 JSON 根结构、键顺序、分隔格式、中文编码、返回类型和错误行为。本 PRD 不建立一个参数化的通用 Codec，也不统一导出字节。

### Prompt 加载归属

日志解析、字段映射、威胁类型和枚举等 Prompt 加载实现归入 Prompt 包；Prompt 文件内容、公开 `load_*` 函数、拼接顺序、模型参数、缓存行为和缺失策略不变。旧 Core Prompt 入口迁移期兼容重导出，内部调用者切换后删除。

### Skills 动态加载保持

Field Skill Adapter 迁移后仍通过现有声明式注册表加载 Skills 脚本；脚本路径、函数名、返回契约、单一事实源地位和从非仓库根目录启动时的定位行为不变。不引入 Agno Skills 自动发现。

### 模型调用与执行策略冻结

每条自然语言业务请求仍恰好调用 Planner 一次；确定性按钮和清空操作不调用 Planner；专业 Agent 调用阶段、字段映射批次数、最大并发、超时、重试次数、补查条件和事件名称标注调用均保持不变。不新增模型兜底、网络调用或初始化探测。

### 用户可观察契约冻结

Chainlit 操作方式、按钮名称与注册、上传规则、用户可见关键提示、稳定错误码、Session 数据生命周期、可引用会话产物、ExecutionReport、下载文件名、配置结构和导出语义保持不变。普通开发日志不要求逐字一致，但安全字段、追踪字段和用户可见消息保持兼容。

### 既有模块删除限制

当前 PRD 只删除本轮迁移产生或使用的兼容入口。既有疑似无调用模块、Base64 历史 Tool、Web 单常量模块和重复日志桥接状态均不在本轮删除；它们进入第二阶段证据审计。删除必须以生产导入、动态注册、包级重导出、测试依赖和外部依赖均为零为前提。

### 严格串行与实施阻塞

父 PRD和全部子 Issues 创建时标记为 `ready-for-human`。当前功能工作区完成并形成稳定提交前不得实施。基线 Issue 完成后，每次只允许一个实施 Issue 转为 `ready-for-agent`；前一 Issue 全量回归并合并后才放行下一 Issue。

### 第二阶段续接

本阶段最后建立 HITL 复盘切片，基于迁移后的真实依赖图起草“ToolWithAgent 领域能力模块深化”PRD，覆盖 StandardFieldCatalog、领域能力目录、日志分类策略、Field Skill Adapter 深化以及既有疑似无调用模块和重复状态审计。

### 架构文档同步与历史边界

文档同步是各实施 Issue 的完成条件，不是重构完成后的可选清理。每个垂直切片必须同步其直接影响的现行文档；最终另设文档总校验切片，统一更新 `README.md` 的目录结构、架构说明与文档导航，更新 `CONTEXT.md` 的当前领域边界和物理路径，校准 `docs/architecture/架构概览.md`、`docs/architecture/代码级设计说明.md`、`docs/architecture/chainlit_app模块说明.md`、`docs/architecture/统一Planner架构.md` 与 `docs/architecture/测试场景手册.md`，并按 `docs/architecture/文档维护规范.md` 更新元数据和 `CHANGELOG.md`。

Application 运行时归属、单向依赖、迁移兼容边界和零行为变化原则属于新的架构决策，实施时新增下一编号 ADR；该 ADR 记录最终决定及后果，不用 PRD 替代 ADR。`docs/source-code-analysis.html` 必须在最终代码状态重新生成并校验文件清单、物理行数、语义层、依赖关系、职责和推荐阅读顺序。带日期的历史方案、已废弃架构和明确标识为旧版的 HTML 保留其历史原貌，不批量改写为现状；现行文档引用历史材料时必须明确标注其历史性质。

## 测试决策

### 重构前行为基线 seam

当前功能开发完成后，实施第一步必须重新统计并运行全量测试、Planner 语义评测和真实 Chainlit 验收，记录关键输入、Session 变化、模型调用次数和导出产物。当前观察到的约 39 个测试文件与 338 个测试用例只作为计划参考，不作为未来实施基线。

### PlanExecutor 契约 seam

使用真实类型化计划、SessionState 与可控假 Adapter 验证步骤依赖、执行顺序、失败关闭、结果账本、ExecutionReport、执行后验证、可引用会话产物和稳定错误码。测试通过公共 PlanExecutor 接口，不绑定迁移后的私有辅助函数。

### Application 组合 seam

通过唯一适配器组合入口和内存 Session 验证日志类型提取、字段映射、枚举提取、威胁类型映射、填充、取消映射、字段调整与导出的完整业务路径。真实 LLM 在常规测试中使用计数假件隔离。

### 主数据与会话生命周期 seam

验证 Excel、Base64、TXT 输入，主数据原子替换，无效上传保持旧数据，枚举映射附件累积与同名替换，过期配置，清空数据，可引用会话产物失效和跨轮引用行为。

### Chainlit 接线 seam

验证应用启动、设置、消息入口、文件上传、全部 Action callback 注册、确定性按钮、进度、汇总渲染、表格和下载附件。新增启动处理器和回调注册清单的冒烟测试，弥补当前直接覆盖不足。

### 架构依赖 seam

使用静态导入测试强制：Contracts 不导入 Web、Application、Chainlit 或领域实现；Agent 与 Skills 不导入 Web 或 Chainlit；Application 运行时核心不导入 Chainlit、Agno 或具体领域实现；Web 可依赖 Application；跨包生产代码不得新增下划线私有名导入；旧兼容路径引用数最终为零。

### 资源定位与动态加载 seam

从仓库根目录和非仓库根目录验证全部 Prompt、标准字段资源和 Skills 注册脚本均可定位；检查包级 `__all__`、延迟 `__getattr__`、冷启动导入顺序、动态 importlib 加载和循环导入。

### 字段映射调用策略 seam

使用计数假件验证迁移前后 Planner、专业 Agent、字段映射批次、重试、补查和事件名称标注调用次数一致；验证批大小、最大并发、超时拆批、`Retry-After`、乱序结果、重复字段、漏字段和原子提交行为。

### 导出产物语义与字节 seam

分别为上传解码、解析规则、字段映射、枚举填充、威胁类型填充和字段调整建立特征测试。比较 JSON 根类型、键顺序、分隔格式、中文编码、Base64 解码文本、文件名和错误行为；不使用一个统一格式覆盖各业务入口。

### 安全与可观测性 seam

验证 SessionFacts 不暴露密钥、真实路径或原始敏感值；日志保持脱敏；稳定追踪字段、中文业务名称、进度心跳和 Token 用量桥接不因迁移重复或丢失。

### 全量回归与真实浏览器验收 seam

每个 Issue 必须在迁移前后运行相关测试和全量测试。最终关闭父 PRD 前必须运行 Planner 语义评测，并通过真实 Chainlit 浏览器完成模型设置、Excel 上传、日志类型提取、字段映射、枚举提取、威胁类型映射、填充、字段调整、导出、Base64 直接操作、失败追问和跨轮产物引用。任何门禁失败均不得判定完成。

### 文档一致性 seam

每个实施 Issue 验证其变更涉及的现行文档不存在旧生产路径、旧职责归属或失效内部链接。最终文档总校验必须扫描 `README.md`、`CONTEXT.md` 和现行架构文档，确认旧路径仅出现在迁移说明或明确的历史上下文中；确认新 ADR 已进入 README 文档导航；确认 `CHANGELOG.md` 按维护规范记录本轮架构变化；并将 `docs/source-code-analysis.html` 的生产文件集合、逐文件行数、总行数和依赖关系与最终仓库扫描结果逐项比对。文档不得包含密钥、真实敏感日志、业务配置数据或本地绝对路径。

## 范围外

- 不修改任何现有业务语义、类型化计划语义或用户使用方式。
- 不调整模型调用、Prompt 内容、模型参数、重试、并发、批大小、超时或漏字段补查策略。
- 不迁移到 OpenAI Agents SDK、LangGraph 或其他 Agent 框架。
- 不全面重组现有领域工具目录。
- 不在本阶段引入 StandardFieldCatalog 或重构标准字段检索与映射知识。
- 不深化日志分类内部策略或 Field Skill Adapter 的内部目标解析。
- 不删除既有疑似无调用模块、历史 Base64 Tool、Web 单常量模块或重复日志桥接状态。
- 不新增或调整 Chainlit UI、按钮、文案、交互和视觉设计。
- 不并行实施多个核心运行时迁移 Issue。
- 不把带日期的历史方案、已废弃架构或明确标识为旧版的文档批量改写成当前架构；只维护作为当前事实源的入口、领域和现行架构文档。

## 补充说明

- 本计划 UI 模式为 `headless`；不创建 Design Issues、页面清单或设计稿。
- 本 PRD 与 ADR-0005、ADR-0006、ADR-0007、ADR-0008 一致，不重新讨论独立 PlannerAgent、可引用会话产物、提供商注册表或字段调整 Skills 的既有决策。
- `web/constants.py` 源自 2026-07-09 的“阶段 0 可读性清理”，意图集中“原始日志”列名，但在创建提交中即无任何调用者，属于未完成接线；本阶段不删除，交由第二阶段审计。
- `agent/core/agent.py` 自 2026-07-02 进入当前历史起就只包含确定性编解码函数；当前仅由文件上传链路调用 `simple_decode`，专业 Agent 的真实所有者为 Team 和独立 Planner 模块。
- 当前仓库外部不存在直接导入 ToolWithAgent Python 模块的脚本，也不存在依赖固定中文日志句子的自动化程序。
- 父 PRD及全部子 Issues 创建后保持 `ready-for-human`，直到当前功能开发完成并由用户明确放行。
- Issue 拆分采用“双层文档责任”：每个业务切片同步直接受影响的现行说明，最终文档总校验切片负责跨文档一致性、新 ADR、CHANGELOG 和源码分析 HTML 的最终快照，避免文档长期滞后或集中到最后才发现语义冲突。
