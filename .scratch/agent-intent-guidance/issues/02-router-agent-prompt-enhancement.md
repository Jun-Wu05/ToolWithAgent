# Issue 02：RouterAgent prompt 增强 + session_summary 引导

> 此内容由 AI 在分拣期间生成。

Status: ready-for-agent
Category: enhancement

## 构建内容

增强 RouterAgent 的 prompt（router.md），让其在 general 路径时读取 session_summary 感知当前状态（有文件？有映射？有枚举表？），根据状态主动建议下一步操作。新手求助时列出当前可用操作和前置条件。

## UI 模式

headless

## PRD 绑定

- **父 PRD Issue：** `.scratch/agent-intent-guidance/PRD.md`
- **Seam：** `agent/prompts/router.md` prompt 文本 + `web/session_state.py` get_session_summary
- **覆盖的用户故事：** US-3
- **PRD 必读：**
  1. 父 PRD — PRD「实现决策」› **RouterAgent prompt 增强**
  2. 父 PRD — PRD「测试决策」› **detect_intent 路由测试**
  3. 父 PRD — 用户故事 `US-3`
- **接口 SSOT：** PRD「实现决策」RouterAgent prompt 增强子项 + `docs/adr/0002-fast-slow-path-routing.md`
- **行为 SSOT：** issue 验收标准 + PRD「测试决策」

## 验收标准

- [ ] session_summary 包含当前状态全感知（文件/映射/子规则/枚举/威胁/日志解析），供 RouterAgent 读取（PRD 依据：`PRD 实现决策 › RouterAgent prompt 增强`；`用户故事 US-3`）
- [ ] router.md 增强：general 路径时根据 session_summary 主动建议下一步操作（PRD 依据：`PRD 实现决策 › RouterAgent prompt 增强`；`用户故事 US-3`）
- [ ] 新手"不会用"→ general → RouterAgent 列出当前可用操作和前置条件（如"你有数据吗？请先上传"）（PRD 依据：`用户故事 US-3`）

## 依赖

- Issue 01（detect_intent 引导提示需先就位，RouterAgent 才能据此引导）

## 阻塞项

无
