# Issue 01：简化 detect_intent 为快路径预筛器

Status: ready-for-agent
Category: enhancement

## 构建内容

将 detect_intent 从全权路由器降级为快路径预筛器。删除消歧规则、状态前置检查、ambiguous 返回。保留单关键词快路径命中和填充模式强制。

## UI 模式

headless

## PRD 绑定

- **父 PRD Issue：** `.scratch/autonomous-agent-routing/PRD.md`
- **Seam：** `web/route_config.py` 的 `detect_intent` 纯函数
- **覆盖的用户故事：** US-2, US-4
- **PRD 必读：**
  1. PRD「实现决策」› **detect_intent 简化**
  2. PRD「测试决策」› **detect_intent 快路径预筛测试**
  3. PRD — 用户故事 `US-2`, `US-4`

## 验收标准

- [ ] detect_intent 保留填充模式强制（threat_fill_mode/enum_fill_mode）（PRD 依据：`PRD 实现决策 › detect_intent 简化`）
- [ ] detect_intent 保留填充动作识别（"填充到"→fill）（PRD 依据：`PRD 实现决策 › detect_intent 简化`）
- [ ] detect_intent 保留单关键词命中→快路径（mapping/threat/enum_extract/log_parser）（PRD 依据：`PRD 实现决策 › detect_intent 简化`）
- [ ] detect_intent 不再有 ambiguous 返回（多关键词冲突→general）（PRD 依据：`PRD 实现决策 › detect_intent 简化`；`用户故事 US-2`）
- [ ] _has_data_for_mapping 及 _THREAT_STRONG_PHRASES 等消歧常量删除（PRD 依据：`PRD 实现决策 › detect_intent 简化`）
- [ ] tests/test_route_config.py 调整：ambiguous 测试改为 general，_has_data_for_mapping 测试删除（PRD 依据：`PRD 测试决策 › detect_intent 快路径预筛测试`）

## 依赖

无 — 可立即开始
