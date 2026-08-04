# Issue 03：操作完成后下一步提示

> 此内容由 AI 在分拣期间生成。

Status: ready-for-agent
Category: enhancement

## 构建内容

在各操作成功完成后（字段映射/威胁映射/枚举提取/填充），在响应末尾追加下一步操作建议。提取 `_get_next_step_hint(user_session)` 辅助函数，根据 session 状态判断哪些操作可用，集中逻辑避免散落。

## UI 模式

headless

## PRD 绑定

- **父 PRD Issue：** `.scratch/agent-intent-guidance/PRD.md`
- **Seam：** `web/response_handler.py` process_team_response 各操作成功分支
- **覆盖的用户故事：** US-2
- **PRD 必读：**
  1. 父 PRD — PRD「实现决策」› **完成后下一步提示**
  2. 父 PRD — PRD「测试决策」› **detect_intent 路由测试**
  3. 父 PRD — 用户故事 `US-2`
- **接口 SSOT：** PRD「实现决策」完成后下一步提示子项
- **行为 SSOT：** issue 验收标准

## 验收标准

- [ ] 字段映射成功回复末尾提示"可提取枚举值或做威胁类型映射"（PRD 依据：`PRD 实现决策 › 完成后下一步提示`；`用户故事 US-2`）
- [ ] 威胁映射成功回复末尾提示"可填充到解析规则"（PRD 依据：`PRD 实现决策 › 完成后下一步提示`；`用户故事 US-2`）
- [ ] 枚举提取成功回复末尾提示"可上传映射表后填充，或进行威胁类型映射"（PRD 依据：`PRD 实现决策 › 完成后下一步提示`；`用户故事 US-2`）
- [ ] 填充成功回复末尾提示"可继续填充其他字段或导出"（PRD 依据：`PRD 实现决策 › 完成后下一步提示`；`用户故事 US-2`）
- [ ] `_get_next_step_hint` 提取为独立函数，根据 session 状态返回可用操作建议（PRD 依据：`PRD 实现决策 › 完成后下一步提示`）

## 依赖

- Issue 01（response_handler 改动基础）

## 阻塞项

无
