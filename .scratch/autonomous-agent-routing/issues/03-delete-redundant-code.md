# Issue 03：删除冗余代码 + 测试调整

Status: ready-for-agent
Category: enhancement

## 构建内容

删除 detect_intent 简化后不再需要的冗余代码：_get_next_step_hint、_has_data_for_mapping、refusal_signatures 中的硬编码关键词。调整测试。

## UI 模式

headless

## PRD 绑定

- **父 PRD Issue：** `.scratch/autonomous-agent-routing/PRD.md`
- **Seam：** `web/response_handler.py`, `web/route_config.py`, `tests/test_route_config.py`
- **覆盖的用户故事：** US-3, US-4
- **PRD 必读：**
  1. PRD「实现决策」› **冗余代码删除**
  2. PRD「测试决策」› **detect_intent 快路径预筛测试**
  3. PRD — 用户故事 `US-3`, `US-4`

## 验收标准

- [ ] _get_next_step_hint 删除（引导交 RouterAgent）（PRD 依据：`PRD 实现决策 › 冗余代码删除`；`用户故事 US-3`）
- [ ] _has_data_for_mapping 删除（前置检查交 RouterAgent）（PRD 依据：`PRD 实现决策 › 冗余代码删除`）
- [ ] handle_user_message 简化（合并不再需要的早期return分支）（PRD 依据：`PRD 实现决策 › 冗余代码删除`）
- [ ] tests/test_route_config.py 全部通过（调整后回归）（PRD 依据：`PRD 测试决策 › detect_intent 快路径预筛测试`）

## 依赖

- Issue 01（detect_intent 简化后才知道哪些代码冗余）

## 阻塞项

无
