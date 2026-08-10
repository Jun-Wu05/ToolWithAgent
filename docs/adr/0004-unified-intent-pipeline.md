# ADR-0004：统一意图管道（理解层 Synthesis → 参数化指令 → 校验 → 执行）

**日期**：2026-08-10
**状态**：已采纳（待实现）

## 背景

复合意图处理链路存在三套并行的意图理解机制（issue #15 根因分析）：

1. **detect_intent 关键词路由**（route_config.py）：单关键词命中直调 handler
2. **RouterAgent 语义路由**（team.run）：模糊/复合意图交 LLM 分解
3. **handler 内部参数猜测**：每个 handler 从 user_text 正则抠参 / LLM 推断 / 隐式 session 状态

三套机制叠加导致：
- 同一指令因关键词命中不同走完全不同代码路径，体验不一致
- handler 接口取最大公约数（接受 `user_text` 自行猜参），编排责任泄漏到执行层
- PLAN 标记 `[PLAN:enum|threat|fill]` 无参数，RouterAgent 理解的语义（字段名、目标位置）全部丢失
- #15 bug：fill 步骤从「填回去」这种自然语言中正则抠不出字段名，静默跳过填充

ADR-0002 的快路径/慢路径基于「RouterAgent 能力有限」的前提。#12/#13 给 RouterAgent 加了 multi-step-plan skill 后，该前提已部分失效，但路由架构未随之重新审视。

## 决策

采用**统一意图管道**，借鉴 Claude Code Coordinator 的「理解→综合→执行」模式：

```
用户输入
  ↓
理解层（RouterAgent）
  ├── Synthesis：读懂用户意图 + session 状态 + 字段列表
  ├── 产出自包含的步骤计划（JSON，每步含 type + params + data_deps）
  └── 单意图 → 直接路由（等效旧快路径，但经由理解层判断）
  ↓
校验层（纯 Python，零 LLM）
  ├── ① 结构校验：JSON schema 合法性
  ├── ② 语义校验：params 对照 session 状态（字段存在性、数据来源）
  └── 校验失败 → 不执行，追问用户（不静默跳过）
  ↓
执行层（参数化 handler）
  ├── 接收显式参数，不从原文猜测
  ├── 执行后自验证（结果非空才算成功）
  └── 三入口（计划执行 / 自然语言 / 按钮）共用参数化核心接口
```

### 核心架构原则：步骤指令自包含

分解出的每个步骤，必须携带执行所需的全部参数。Handler 不从原文猜测，不依赖隐式 session 状态推断参数。这一原则借鉴自 Claude Code 的 Coordinator 规范："Workers can't see your conversation. Every prompt must be self-contained."

### 计划格式

RouterAgent 产出 JSON 嵌入 `[PLAN:{...}]` 标记（向后兼容旧式无参数标记）：

```
[PLAN:{"steps":[
  {"type":"enum","params":{"field":"漏洞名称"}},
  {"type":"threat","data_deps":["enum"]},
  {"type":"fill","params":{"field":"threat_type","source":"threat"}}
]}]
```

### 三层校验

| 层 | 内容 | 失败处理 |
|----|------|---------|
| ① 结构校验 | JSON schema、步骤类型合法、data_deps 引用有效 | 回退旧式标记 + 追问 |
| ② 语义校验 | params 对照 session（字段存在、数据来源匹配） | 不执行，追问用户 |
| ③ 执行后验证 | 结果非空、mapped_sub_rules 确实变更 | 标记失败，停止后续步骤 |

校验层为纯 Python 代码，零 LLM 调用。

## 理由

1. **体验一致性**：所有指令走同一条「理解→执行」管道，不再因关键词命中不同而走不同路径、得到不一致结果
2. **正确性保障**：三层校验在理解层（可能出错）和执行层（确定性、不质疑指令）之间加闸。语义校验对照 session 状态，参数与实际数据不匹配时不执行
3. **局部性**：参数解析 + 校验集中到管道（step_planner + 校验层），handler 只管执行。新增步骤类型时，只需声明参数契约，无需改 handler 内部
4. **Claude Code 实证**：Coordinator 通过 Synthesis 产出自包含指令（带文件路径、行号），而非传话筒式转发。其明确禁止的反模式 "based on your findings"，正是当前 step_planner 原文透传的做法

## 与 ADR-0002 的关系

**增强而非废弃**：ADR-0002 的快路径/慢路径性能优化（明确意图跳过 RouterAgent）保留。统一管道在理解层内部仍可利用 detect_intent 的关键词判断作为 route_hint（加速路由），但不再作为独立分流——所有意图都经由理解层判断，detect_intent 的结果作为 hint 传入而非决定路径。

## 迁移策略

四阶段渐进迁移，每阶段可独立交付、可验证、可回滚（详见 issue 拆分）：

1. **建管道**（纯新增）：校验层 + 结构化计划解析 + 参数化 handler 接口，新旧双轨并存
2. **接通**：复合意图走新管道，#15 场景验证
3. **收编**：自然语言/按钮入口逐个接入参数化接口
4. **清理**：删除旧的正则/猜测逻辑

## 后果

- **正面**：体验一致；正确性有校验保障；handler 接口缩小（参数化）；参数解析局部化；新增步骤类型只需声明契约
- **负面**：统一管道初期所有指令都经由 RouterAgent 理解，比旧快路径多 1 次 LLM 调用（~5-10s）。detect_intent 作为 route_hint 可部分缓解（RouterAgent 有了 hint 后路由更准，但不跳过）
- **迁移期**：双轨并存增加代码复杂度，阶段 4 清理后消除
