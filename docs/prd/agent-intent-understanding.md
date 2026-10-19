# PRD：Agent 意图引导增强

## 问题陈述

当前 Agent 在明确意图时通过快路径直调 MemberAgent，响应快、省 token。但意图引导场景表现不足：

1. **模糊意图无引导**：用户说"我要字段映射"但没上传文件，系统要么直调 FieldMappingAgent 报错重试，要么返回不知所云的回复。Agent 不主动引导用户"请先上传文件"。
2. **完成后无下一步提示**：用户完成威胁类型映射后，系统不主动提示"可以将结果填充到解析规则"，用户不知道还能做什么。
3. **新手无引导**：新用户说"我不清楚怎么用"，系统不列出当前可用操作和前置条件。

根本原因：RouterAgent 在 general 路径时缺乏结构化的引导能力，不会根据 session 状态主动建议下一步。

## 解决方案

增强 RouterAgent 的引导能力：

1. **detect_intent 引导提示**：状态前置检查触发降级时（如无数据但要求映射），返回 `general` 并附带引导提示，RouterAgent 据此引导用户。
2. **RouterAgent prompt 增强**：让 RouterAgent 在 general 路径时读取 session_summary 感知当前状态（有文件？有映射？有枚举表？），根据状态主动建议下一步操作。
3. **完成后提示**：各操作完成后（映射/提取/填充），在响应末尾提示用户下一步可选操作。

## 用户故事

US-1：作为新用户，我想要在说"字段映射"但还没上传文件时，系统主动告诉我"请先上传 Excel 或 Base64 配置文件"，以便我知道下一步该做什么。

US-2：作为安全分析师，我想要在完成威胁类型映射后，系统主动提示"可以将结果填充到解析规则，请说'填充到xxx字段'"，以便我知道下一步操作选项。

US-3：作为新用户，我想要在说"我不清楚怎么用"时，系统列出当前可用的操作和前置条件（你有数据吗？你有映射结果吗？），以便我快速上手。

## 实现决策

### detect_intent 引导提示

当状态前置检查触发降级（如无数据但要求映射）时，在 reason 里附带引导提示：

- 当前：`return "general", "映射意图但无数据，交 RouterAgent 引导上传"`
- 扩展后：`return "general", "映射意图但无数据，交 RouterAgent 引导上传", guidance="请先上传 Excel 或 Base64 配置文件"`
- RouterAgent 收到 guidance 后作为回复主体

### RouterAgent prompt 增强

增强 router.md，让 RouterAgent 在 general 路径时：
- 读取 session_summary 感知当前状态（有文件？有映射？有枚举表？有子规则？）
- 根据状态主动建议下一步操作（而非被动等待）
- 新手求助时列出当前可用操作和前置条件

### 完成后下一步提示

各操作完成后（字段映射/威胁映射/枚举提取/填充），在响应末尾附加下一步操作建议：
- 字段映射完成 → "可以提取枚举值或做威胁类型映射"
- 威胁映射完成 → "可以说'填充到xxx字段'将结果写入解析规则"
- 枚举提取完成 → "可以上传映射表后填充，或进行威胁类型映射"
- 填充完成 → "可以继续填充其他字段，或导出最终配置"

实现方式：response_handler 在各操作的成功回复末尾追加提示文本（基于 session 状态判断哪些操作可用）。

## 测试决策

### detect_intent 路由测试

测试接缝：`web/route_config.py` 的 `detect_intent(user_text, user_session) -> (intent, reason)` 纯函数。

测试文件：`tests/test_route_config.py`（新建 tests/ 目录，可追踪，不被 gitignore 忽略）

测试覆盖：
- 单一意图（现有行为回归）：mapping/threat/enum/log_parser/general/fill 各分支
- 状态前置检查：mapping 无数据 → general；有数据 → mapping
- 填充动作识别：fill 类型判定（威胁/枚举/无类型用 last_fill_type）
- 消歧规则：威胁+映射冲突、ambiguous
- **引导提示**（新增）：无数据时 reason 含引导信息

## 范围外

- **复合意图分解**（后续 PRD）：一条消息含多个操作（如"提取枚举值再威胁映射"），系统分解为步骤序列。US-1/US-3/US-6 移至此 PRD。
- 不重写 RouterAgent 为 TeamMode.tasks（非确定性风险，见 ADR-0002）
- 不做跨进程持久化（见 ADR-0001）
- 不改 FieldMappingAgent/ThreatAgent/EnumAgent 的内部逻辑（只改路由和编排层）
- eval/ 死文件已按用户确认清理（conftest/test_candidate_recall/test_full_mapping_cli/test_llm_accuracy/test_skills_e2e；test_logtype_regex_generation、scripts/、tools/、golden/、test_data/ 保留）
- 不做 NLU/意图分类模型（保持关键词+规则+LLM fallback 的三层架构）

## 补充说明

### 与 ADR 的关系

- ADR-0001（自定义历史）：复合意图执行时，对话历史让 Agent 感知之前的操作结果
- ADR-0002（快/慢路径）：复合意图走慢路径（RouterAgent 分解），单一明确意图仍走快路径
- ADR-0003（统一枚举填充）：复合意图中的填充步骤走 fill_dispatcher

### 风险

1. **复合意图识别准确率**：关键词+规则可能误判复合（如"威胁类型字段映射"是单一映射不是复合）。需在测试中覆盖边界 case。
2. **执行时间**：复合操作多步串行，总耗时 = 各步之和。需提示用户等待。
3. **RouterAgent 分解能力依赖 LLM 质量**：RouterAgent 的分解正确性取决于 prompt 和模型能力，需充分测试。

### 依赖

- CONTEXT.md 术语对齐（已完成）
- ADR-0001/0002/0003 架构决策（已完成）
- fill_dispatcher 统一填充（已实现）
- history_store 对话历史（已实现）
