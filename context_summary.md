# 上下文压缩总结 — ToolWithAgent 纯 Agent 项目重组

## 1. 核心目标

修复 `web/chainlit_app.py` 运行报错（ImportError）+ 将项目从"Agent+GUI 混杂"重组为"纯 Agent 项目"，GUI 代码归档至 `reference/gui/` 供逻辑参考。

## 2. 已完成分析

- **引用关系全量扫描**：`from src.` 共 13 处（`agent/core/tracing.py` 1处 + `web/` 8文件 11处 + `chainlit_app.py` 内联 2处）
- **共享工具识别**：仅 `src/logger.py`、`src/field_mapping_handler.py`、`src/threat_fill_handler.py` 被 Agent 侧引用，其余 `src/` 文件纯 GUI 专属
- **详细执行计划**：`docs/综合改造执行计划.md`（4 Phase, ~400 行）

## 3. 已确认决策

| 决策 | 结论 |
|------|------|
| 共享模块命名 | `agent/shared/` |
| `main.py` 处理 | 改指向 `reference/gui/` |
| `agent/agent.py` | 不动（未被当前 Team 模式使用） |
| 标准字段表 | **不缩减**，通过 prompt 认知负载优化代替 |
| 类名冲突（`field_mapping`） | 功能正常即可，重命名文件去掉 `_handler` 后缀 |

## 4. 当前卡点

**等待用户切换到 ACT MODE**。Plan 已完成并写入 `docs/综合改造执行计划.md`，但当前仍在 PLAN MODE 无法执行工具。

## 5. 下一步

执行 4 个 Phase：

| Phase | 内容 | 改动量 |
|-------|------|--------|
| **1** | Bug 修复：`call_team_with_retry`→`call_team` + `apply_field_mapping` 改为实例方法 | 1 文件 2 处 |
| **2** | 结构重组：新建 `agent/shared/` → 复制 3 文件 → 批量替换 12 处 import → `src/` 移入 `reference/gui/` | ~14 文件 |
| **3** | 性能优化：加 120s 超时 + 关键词预筛 + prompt 认知负载声明 | ~3 文件 |
| **4** | 全量验证 + Git 推送 | `pytest` + `chainlit run` |