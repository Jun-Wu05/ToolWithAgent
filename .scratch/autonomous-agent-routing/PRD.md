# PRD：自主 Agent 架构改进 — 统一路由决策

## 问题陈述

当前系统的路由决策分散在 Python 硬编码和 RouterAgent 两处，导致：

1. **Agent 不自主**：detect_intent 用9个布尔标志+多层消歧规则做本该由 Agent 思考的决策。每出现新边界 case（如 log_parser 无数据、威胁vs映射冲突），都要在 Python 加一层 if-else。
2. **双路由不一致**：Python detect_intent 和 RouterAgent 做重叠的路由决策，但规则覆盖范围不同（Python 有 _has_data_for_mapping，RouterAgent 有 router.md 前置检查），导致矛盾（如 detect_intent 降级 general 但 RouterAgent 仍路由到 FieldMappingAgent 返回空 items）。
3. **引导硬编码**：_get_next_step_hint 用5条 if/else 生成引导文本，RouterAgent 的 router.md 有重叠的引导规则，两者可能冲突。

根本原因：Python 代码「抢」了本该由 Agent 自主完成的决策（路由消歧、状态判断、引导建议）。

## 解决方案

将 detect_intent 从「全权路由器」降级为「快路径预筛器」：

- **快路径**（detect_intent 保留）：只处理高置信度单关键词命中（纯"映射"/"威胁"/"枚举"/"日志解析"），省1次 LLM 调用
- **慢路径**（RouterAgent 全权）：所有不确定的情况（消歧、状态检查、引导）交给 RouterAgent 自主思考

核心原则：**Python 只做确定性高、无需思考的快速判断；涉及理解、消歧、状态感知的决策全部交给 Agent。**

## 用户故事

US-1：作为安全分析师，我想要在说"日志类型提取"但还没上传文件时，系统主动引导我上传数据（而非跑 Pipeline 产出垃圾结果），以便我不浪费时间等无效处理。

US-2：作为安全分析师，我想要在说"威胁类型字段映射"时，系统自主判断我到底是要威胁映射还是字段映射（而非靠 Python 关键词优先级硬编码决定），以便复合意图被正确理解。

US-3：作为新用户，我想要在操作完成后收到基于当前状态的个性化引导（而非硬编码模板），以便我知道下一步该做什么。

US-4：作为开发者，我想要在新增操作类型时只需修改 router.md prompt（而非修改 detect_intent 的 Python 消歧逻辑），以便快速扩展系统能力。

## 实现决策

### detect_intent 简化

将 detect_intent 从「全权路由器」降级为「快路径预筛器」：
- 保留：填充模式强制（threat_fill_mode/enum_fill_mode → 直接返回对应意图）
- 保留：填充动作识别（"填充到/填充/填入" → 返回 "fill"）
- 保留：单关键词精确命中 → 快路径（mapping/threat/enum_extract/log_parser）
- **删除**：消歧规则（_THREAT_STRONG_PHRASES/_THREAT_ACTION_PHRASES/has_mapping_strong）→ 交 RouterAgent
- **删除**：状态前置检查（_has_data_for_mapping）→ 交 RouterAgent
- **删除**：ambiguous 返回 → 多关键词冲突时走 general（RouterAgent 处理）
- **删除**：_has_data_for_mapping 辅助函数（不再需要）

### RouterAgent prompt 增强

router.md 增加：
- **全局前置检查**：路由到任何需要数据的 Agent 前，检查 session_summary 有无数据。无数据时直接引导上传，不路由。
  - 覆盖 FieldMappingAgent（已有）、LogParserAgent（新增）、EnumAgent 提取（新增）
- **消歧能力**：威胁vs映射冲突时，RouterAgent 根据语义判断（而非 Python 短语匹配）
- **引导生成**：操作完成后或意图不清时，根据 session_summary 生成个性化引导

### 冗余代码删除

- **删除** `_get_next_step_hint`（response_handler.py）：引导交 RouterAgent
- **删除** `_has_data_for_mapping`（route_config.py）：前置检查交 RouterAgent
- **简化** `handle_user_message`（user_message_handlers.py）：detect_intent 简化后，部分早期return分支合并

### ADR-0002 重新讨论

当前 ADR-0002：快路径直调省1次LLM调用
重新定义：快路径只处理**高置信度单关键词**（省1次LLM），所有复杂/模糊/无数据情况走 RouterAgent（Agent自主思考）。RouterAgent 的职责从"被绕过的路由器"变为"全权路由+引导决策者"。

## 测试决策

### detect_intent 快路径预筛测试

测试接缝：`web/route_config.py` 的 `detect_intent(user_text, user_session)` 纯函数。

测试覆盖：
- 单关键词命中 → 快路径（mapping/threat/enum_extract/log_parser/fill）
- 多关键词冲突 → general（交 RouterAgent，不再有 ambiguous）
- 无关键词 → general
- 填充模式强制 → 对应意图
- **已有测试需调整**：ambiguous 相关测试改为 general；_has_data_for_mapping 相关测试删除

### RouterAgent 引导行为验证

验证接缝：`web/response_handler.py` general 分支 + `agent/prompts/router.md` prompt 内容

测试覆盖：
- general 分支不再返回 {"items":[]}（防御过滤保留）
- router.md 包含全局前置检查规则

## 范围外

- 不改 Agent 层（Team/MemberAgent 构造不变）
- 不改工具层（field_retriever/rule_generator/mapping_utils 不变）
- 不改状态层（SessionState 结构不变）
- 候选2（数据源统一）和候选3（字符串→工具调用）独立于本 PRD，后续增量实施
- 复合意图分解（"提取枚举值再威胁映射"）仍为后续 PRD

## 补充说明

### 风险

1. **性能**：更多请求走慢路径（2次LLM调用）。但快路径仍覆盖最常见的明确意图（纯"映射"/"威胁"等），只有复杂/模糊情况才走慢路径。
2. **RouterAgent 消歧准确率**：依赖 LLM 语义理解能力。需充分测试 router.md prompt 的消歧效果。
3. **引导质量**：RouterAgent 生成的引导文本质量取决于 prompt 和模型能力。

### 与 ADR 的关系

- ADR-0001（自定义历史）：RouterAgent 读对话历史辅助消歧
- ADR-0002（快路径/慢路径）：**本 PRD 重新定义分界**
- ADR-0003（统一枚举填充）：填充逻辑不受影响
