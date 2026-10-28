# V2 页面视觉基线 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将既有 V2 页面按 `docs/design/v2-visual-baseline.md` §5 落地，并保留人工联合验收边界。

**Architecture:** 复用已交付的 Token、StatusText、ContextPanel 和样式工具类。会话列表仅增加 owner 范围内最新 Run 的状态摘要，前端在有证据时渲染状态，不推断空会话。

**Tech Stack:** React、TypeScript、CSS Token、FastAPI、SQLite、Vitest、pytest。

---

## 任务 1：页面状态与视觉

**文件：** `v2/frontend/src/UserHistory.tsx`、`RunDiagnostics.tsx`、`MappingWorkspace.tsx`、`FieldChangesWorkspace.tsx`、`VisualPrimitives.tsx`、`workbench.css` 及相邻测试。

1. 在页面测试中覆盖状态文字、过滤 chips、真实耗时和映射修改标识。
2. 运行定向 Vitest，确认旧视图不满足新断言。
3. 复用现有原语和 Token 完成最小样式改动，运行定向 Vitest。

## 任务 2：最近会话的状态证据

**文件：** `v2/backend/toolwithagent_v2/infrastructure/store.py`、`v2/backend/tests/test_user_history.py`、`v2/frontend/src/api.ts`、`App.tsx`、`App.test.tsx`。

1. 测试空会话状态为空、有 Run 时仅显示本用户最新当前 Run 状态，切换用户不泄露其他会话。
2. 修改 `list_conversations` 的 owner 限定 SQL，一次查询带回 `latest_run_status`。
3. 扩展前端摘要类型，在最近会话项渲染 StatusText；测试有状态与无状态两种情况。

## 任务 3：验证与交接

**文件：** `docs/design/v2-309-acceptance.md`。

1. 运行根仓 pytest、V2 后端 pytest、前端全量 Vitest、lint 和 build。
2. 记录自动核对证据，人工明暗、多视口和浏览器终验交给 #310 联合执行。
3. 检查 diff 和 V2 基线，再提交并准备 Draft PR 全文供用户确认。
