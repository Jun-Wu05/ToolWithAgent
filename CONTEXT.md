# CONTEXT.md — 领域术语表

> 本文件是项目领域语言的唯一权威来源。所有 skill（PRD、Issue、测试命名）必须使用此处定义的术语。

---

## 核心概念

### 映射（Mapping）

将原始数据对应到标准数据的过程。分为两个层级：

- **字段映射（Field Mapping）**：字段名对字段名。将设备厂商的原始字段名（如 `alarm_category`）对应到标准字段名（如"威胁类型"）。结果写入 normalize 项的 `field` 属性。
  - 避免：不要叫"字段匹配"或"字段对照"。

- **值映射（Value Mapping）**：值对值。将原始字段值（如"隐蔽隧道"）对应到标准值（如"隧道攻击"）。结果写入 normalize 项的 `mappings` 数组。值映射有两种来源：
  - **枚举提取（Enum Extract）**：从日志中用正则提取某字段的所有不同值，用户定义映射关系。值的来源是日志数据本身。
  - **威胁类型映射（Threat Type Mapping）**：值来自预定义的标准威胁分类表（标准字段表中的固定枚举值集合），用户输入原始值，LLM 对应到标准分类。

  > **关键关系**：威胁类型映射本质也是一种值映射（填充），只是其枚举值是预定义的标准分类，而非从日志提取。

### 填充（Fill）

将值映射的结果写入解析规则的 normalize 结构的 `mappings` 数组。

- 威胁类型填充和枚举填充在 apply 层面是同一操作（找 normalize 项 → 追加 mappings），区别只是 mappingType（REGULAR vs EQUAL）和值的来源。
- 支持**链式回写**：填充后更新 mapped_sub_rules，后续填充基于上次结果。
- 支持**取消映射**：清空指定字段的 mappings。

### 解析规则（Parsing Rule）

从日志格式识别 + 字段提取 + 标准字段映射生成的配置规则。结构包含 normalize 数组，每个 normalize 项有 index（原始字段名）、field（标准字段名）、mappings（值映射表）。

- **子规则（Sub Rule）**：按日志类型（如 AUDIT/IPS/RUN_INFO）拆分的解析规则，每种日志类型一条子规则，各有独立的 normalize 数组。
- **入口规则（Entry Rule）**：日志类型识别的顶层规则，用于判断日志行属于哪个子规则。

### 标准字段（Standard Field）

标准字段表（625条）定义的字段，是字段映射的目标。每条标准字段有：系统属性名称（中文）、字段名称（英文）、属性分类、描述、枚举值、对象。

---

## 操作模型

> **核心特征：操作非线性，用户可任意衔接。** 系统不强制操作顺序，用户在任何节点可以跳到任何其他节点。系统的职责是感知当前 session 状态（有什么数据），而非强制流程。

```
上传文件（Excel/Base64/TXT）→ 产出 raw_log_lines + decoded_data
  ↕ 可任意跳转
日志类型提取 → 识别格式 + 分类日志类型 → 产出 log_classification + 子规则
  ↕ 可任意跳转
字段映射 → 原始字段名 → 标准字段名 → 产出 mapped_sub_rules（normalize[].field 被标注）
  ↕ 可任意跳转
枚举提取 → 从日志用正则提取某字段的所有不同值 → 产出枚举值列表
  ↕ 可任意跳转
威胁类型映射 → 原始值 → 标准威胁分类 → 产出 last_threat_data
  ↕ 可任意跳转
填充 → 值映射结果写入 normalize[].mappings → 链式回写 mapped_sub_rules
  ↕ 可任意跳转
导出 → 填充后的子规则 → Base64 下载
```

### 日志类型（可选增强，非前提）

日志类型识别（AUDIT/IPS/RUN_INFO 等）**不是其他操作的必要前提**。系统在任何情况下都应合理工作：
- 用户做了日志类型提取 → 后续操作可按类型过滤，结果更精准
- 用户没做日志类型提取 → 系统仍正常工作（混合样本也接受，只是某字段只存在于子类型时匹配率较低属正常现象）
- 用户可在任何时点补做日志类型提取，不影响已有数据

### 数据源

两种输入殊途同归，都产出可供填充的 normalize 结构：

- **Excel 数据表格**：必须含"原始日志"列 → 提取 raw_log_lines → 日志解析 → 字段映射 → 生成子规则（mapped_sub_rules）。缺少"原始日志"列的数据表会在上传时被拒绝（提示重新上传正确格式）；枚举映射表 Excel 按列头单独识别，不受此限制
- **配置文件**（Base64/TXT）：含 normalize 数组结构 → 解码为 decoded_data

两种数据源产出的 normalize 结构都可供填充操作使用。

字段映射的候选字段有优先级：有真实日志字段（日志解析结果或原始日志行提取）时，只用日志字段与已有子规则字段，Excel 列头不参与映射；decoded_fields 仅在无日志字段时作为回退（对应只上传配置文件的场景）。

---

## 角色边界

| 角色 | 职责 | 不做的事 |
|---|---|---|
| PlannerAgent | 结合用户原文、有限历史与 SessionFacts 生成类型化计划 | 不持有业务工具，不执行任务 |
| PlanExecutor | 校验 session 语义、解析依赖、推进步骤并记录 ExecutionReport | 不理解用户原文，不做界面渲染 |
| FieldMappingAgent | 字段名 → 标准字段名映射 | 不做值映射或意图理解 |
| ThreatAgent | 原始值 → 标准威胁分类映射 | 不做字段映射或读取旧结果兜底 |
| Enum Extract Adapter | 为显式目标字段提取枚举值 | 不猜测目标字段，不做填充 |
| Log Parser Adapter | 日志格式识别 + 特征分类 | 不做字段/值映射 |
| Renderer | 渲染 Clarification、Guidance 或 ExecutionReport | 不执行业务、不解释 session |

---
## 架构原则：步骤指令自包含

> 参见 ADR-0005「独立 PlannerAgent 与自然语言统一入口」。

复合意图分解出的每个步骤，必须携带执行所需的全部参数（字段名、数据来源、目标位置）。Handler 接收显式参数执行，不从用户原文猜测，不依赖隐式 session 状态推断参数。

**分层职责**：
- **事实层（SessionFacts）**：集中投影 session 状态，不暴露敏感值
- **理解层（PlannerAgent）**：读懂用户意图，产出自包含的类型化步骤计划
- **执行层（PlanExecutor）**：集中校验、依赖解析、步骤推进和执行后验证
- **适配层（StepAdapter）**：接收类型化参数，只负责调用专业 Agent 或领域函数
- **渲染层（Renderer）**：只消费决策或 ExecutionReport，统一输出一次汇总

**适配层词汇**（2026-08-14 架构拷问固化）：
- **适配器包（web/adapters/）**：按操作落位的 StepAdapter 集合。`create_default_adapters` 是唯一公共入口，PlanExecutor 按 `step.type` 字符串键注册分派，不感知适配器内部结构。落位分三档：字段映射热点独立成模块，log_parse/enum_extract/threat_mapping 三个小操作共模块，fill/remove/export 简单适配器共模块。
- **FieldMappingBatchRunner**：字段映射批处理执行器。输入字段列表与执行策略，输出完整映射行结果（含并发分批、超时拆批、重试、漏字段补查）；适配器只做 StepSpec 翻译、进度事件、产物构建与 session 一次性提交。
- **依赖注入接缝**：适配器构造函数可选注入外部依赖（candidate_retriever / object_map_loader，默认值=现模块函数），与 PlannerService(runner=...) 同构。测试传构造假件，不 monkeypatch 模块私有属性。
- **工具门面**：web 跨包只允许导入 agent/tools 的公开名，禁止下划线私有名跨包引用。

**反模式（禁止）**把用户原文整句透传给执行层，让 handler 用正则/隐式状态自行抠参。这等同于把理解工作外包给执行器，是 #15 bug 的根因。
