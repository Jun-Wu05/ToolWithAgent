# 自主 Agent 架构改进方案（基于 zoom-out + improve-codebase-architecture）

## 首选候选：统一路由决策（候选1）

### 核心改变
将 `detect_intent` 从「全权路由器」降级为「快路径预筛器」：

**改前**：detect_intent 做9个布尔标志+多层消歧+状态前置检查 → 快路径直调或降级general
**改后**：detect_intent 只做高置信度单关键词命中（纯"映射"/"威胁"/"枚举"/"日志解析"）→ 命中走快路径，不命中/复杂/无数据 → 全部交 RouterAgent

### 具体改动

#### Phase 1：简化 detect_intent（route_config.py）
- 保留：填充模式强制（threat_fill_mode/enum_fill_mode）
- 保留：单关键词精确命中 → 快路径（mapping/threat/enum/log_parser）
- **删除**：消歧规则（_THREAT_STRONG_PHRASES等）→ 交 RouterAgent
- **删除**：状态前置检查（_has_data_for_mapping）→ 交 RouterAgent
- **删除**：ambiguous 返回 → 不确定就走 general（RouterAgent 处理）

#### Phase 2：增强 RouterAgent（router.md）
- router.md 已有路由前置检查（无数据不路由到 FieldMappingAgent）
- 增强：增加日志解析/枚举提取的前置检查（无数据时引导上传）
- 增强：消歧规则（威胁vs映射）从 Python 移到 prompt

#### Phase 3：删除冗余（response_handler.py / user_message_handlers.py）
- 删除 `_get_next_step_hint`（候选4，引导交 RouterAgent）
- 删除 `_has_data_for_mapping`（候选5，前置检查交 RouterAgent）
- 简化 `handle_user_message` 的分支（候选1简化后，很多早期return分支不再需要）

### ADR-0002 重新讨论
当前 ADR-0002：快路径直调省1次LLM调用
重新定义：快路径只处理**高置信度单关键词**（省1次LLM），复杂/模糊/无数据走 RouterAgent（Agent自主思考）

### 不做的事
- 不改 Agent 层（Team/MemberAgent 构造不变）
- 不改工具层（field_retriever/rule_generator/mapping_utils 不变）
- 不改状态层（SessionState 不变）
- 候选2/3 独立于候选1，可后续增量实施

### 验证流程
改完后走 /to-prd → /to-issues → /tdd 实现这个架构改进

## 你想先探索哪个候选？还是确认候选1作为首选，开始走 /to-prd？