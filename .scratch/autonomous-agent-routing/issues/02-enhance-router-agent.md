# Issue 02：增强 RouterAgent 全权路由+引导

Status: ready-for-agent
Category: enhancement

## 构建内容

增强 router.md prompt，让 RouterAgent 全权处理消歧、状态前置检查、引导。增加日志解析/枚举提取的前置检查（无数据时引导上传）。

## UI 模式

headless

## PRD 绑定

- **父 PRD Issue：** `.scratch/autonomous-agent-routing/PRD.md`
- **Seam：** `agent/prompts/router.md` prompt 文本
- **覆盖的用户故事：** US-1, US-2, US-3
- **PRD 必读：**
  1. PRD「实现决策」› **RouterAgent prompt 增强**
  2. PRD「测试决策」› **RouterAgent 引导行为验证**
  3. PRD — 用户故事 `US-1`, `US-3`

## 验收标准

- [ ] router.md 包含全局前置检查（路由到任何需要数据的Agent前检查session_summary有无数据）（PRD 依据：`PRD 实现决策 › RouterAgent prompt 增强`；`用户故事 US-1`）
- [ ] router.md 覆盖 FieldMappingAgent + LogParserAgent + EnumAgent 的前置检查（PRD 依据：`PRD 实现决策 › RouterAgent prompt 增强`；`用户故事 US-1`）
- [ ] router.md 包含消歧能力（威胁vs映射冲突时语义判断）（PRD 依据：`PRD 实现决策 › RouterAgent prompt 增强`；`用户故事 US-2`）
- [ ] router.md 包含引导生成（操作完成后/意图不清时根据session_summary生成个性化引导）（PRD 依据：`PRD 实现决策 › RouterAgent prompt 增强`；`用户故事 US-3`）

## 依赖

- Issue 01（detect_intent 简化后，RouterAgent 承担更多路由职责）

## 阻塞项

无
