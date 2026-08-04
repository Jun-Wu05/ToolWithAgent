# Issue 01：detect_intent 引导提示 + 测试基线

> 此内容由 AI 在分拣期间生成。

Status: ready-for-agent
Category: enhancement

## 构建内容

增强 detect_intent 的状态前置检查，在降级时（如 mapping 无数据）让 reason 包含引导信息。同时新建 tests/ 目录和 test_route_config.py，覆盖 detect_intent 所有分支作为测试基线。

## UI 模式

headless

## PRD 绑定

- **父 PRD Issue：** `.scratch/agent-intent-guidance/PRD.md`
- **Seam：** `web/route_config.py` 的 `detect_intent(user_text, user_session)` 纯函数
- **覆盖的用户故事：** US-1
- **PRD 必读：**
  1. 父 PRD — PRD「实现决策」› **detect_intent 引导提示**
  2. 父 PRD — PRD「测试决策」› **detect_intent 路由测试**
  3. 父 PRD — 用户故事 `US-1`
- **接口 SSOT：** PRD「实现决策」detect_intent 引导提示子项 + `docs/adr/0002-fast-slow-path-routing.md`
- **行为 SSOT：** issue 验收标准 + PRD「测试决策」detect_intent 路由测试子项

## 验收标准

- [ ] detect_intent("映射", 无数据 session) 返回 ("general", reason 含引导上传提示)（PRD 依据：`PRD 实现决策 › detect_intent 引导提示`；`用户故事 US-1`）
- [ ] detect_intent("映射", 有数据 session) 返回 ("mapping", ...)（PRD 依据：`PRD 测试决策 › detect_intent 路由测试`；`用户故事 US-1`）
- [ ] tests/test_route_config.py 新建，覆盖 mapping/threat/enum/log_parser/general/fill/ambiguous 各分支（PRD 依据：`PRD 测试决策 › detect_intent 路由测试`）
- [ ] tests/ 目录不被 .gitignore 忽略（可追踪）（PRD 依据：`PRD 测试决策 › detect_intent 路由测试`）

## 依赖

无 — 可立即开始

## 阻塞项

无 — 可立即开始
