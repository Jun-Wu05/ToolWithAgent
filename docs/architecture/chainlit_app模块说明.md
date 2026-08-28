# chainlit_app 模块说明

> **文档版本**：2026-08-28
> **对应分支**：`refactor/chainlit-app-split-20260612`

---

## 1. 重构概述

**目标**：将 1400 行的 `chainlit_app.py` 拆分为 9 个平级模块

**变更**：
- 主文件精简至 60 行（减少 96%）
- 保持向后兼容
- 扁平化结构，无子目录

**新增模块**：
| 模块 | 行数 | 职责 |
|------|------|------|
| start_handler.py | ~130 | 聊天开始初始化 |
| settings_handler.py | ~180 | 模型设置更新 |
| message_router.py | ~30 | 消息路由分发 |
| upload_handlers.py | ~250 | 文件上传处理 |
| user_message_handlers.py | ~140 | Planner、Application 执行器与 Renderer 的薄编排 |
| action_callbacks.py | ~250 | Action 回调 |
| utils.py | ~150 | 纯辅助函数 |
| global_state.py | ~30 | 全局状态管理 |

---

## 2. 模块职责

### 2.1 chainlit_app.py（薄入口）
仅保留 Chainlit 生命周期钩子 + 转发，60 行无业务逻辑

### 2.2 start_handler.py
@cl.on_chat_start 实现：Agno 日志桥接、SessionState 初始化、后台缓存初始化

### 2.3 settings_handler.py
@cl.on_settings_update 实现：重置设置、供应商切换、API 测试、Team 重置

### 2.4 message_router.py
@cl.on_message 分发：文件 → upload_handlers，文本 → user_message_handlers

### 2.5 upload_handlers.py
文件上传处理：Excel 类型检测、Base64 解码和 SessionFacts 所需状态建立

### 2.6 user_message_handlers.py
用户文本处理：调用 Planner 一次、执行类型化计划并统一渲染报告

### 2.7 action_callbacks.py
确定性事件适配：业务按钮构造 StepSpec 并复用 PlanExecutor；Excel 展示导出不改变领域状态

### 2.8 utils.py
纯辅助函数：JSON 解析、结果渲染、Excel 检测（无 Chainlit 依赖）

### 2.9 global_state.py
全局状态管理：Agno 日志桥接标志

### 2.10 Application 运行时接缝
`SessionState`、`PlanExecutor`、执行结果账本与 `NullProgressSink` 位于 `application/`。Web 只在组合根注入领域预检和日志，并保留 Chainlit 生命周期及渲染职责。导出 Adapter 已迁入 Application；其余业务 Adapter 仍暂存 `web/adapters/`。

---

## 3. 调用关系

```text
用户 → chainlit_app.py → message_router.py
  ├─ 文件 → file_handlers.py → SessionFacts
  └─ 文本 → user_message_handlers.py → PlannerAgent → Application PlanExecutor
按钮 → action_callbacks.py → StepSpec → Application PlanExecutor
Application PlanExecutor → StepAdapter → ExecutionReport → plan_renderer.py
```

---

## 4. 数据流

### 文件上传
用户上传 → 文件类型识别/解码 → 更新 SessionState → SessionFacts 投影

### 用户文本
用户输入 → PlannerAgent → PlanDecision → PlanExecutor → StepAdapter → 一次汇总

### 日志解析
类型化 LogParseStep → ProfessionalAgentAdapter → 日志 Pipeline → log_classification

---

## 5. 设计原则

1. **边界清晰**：`web/` 保留 Chainlit 交互与组合，运行时核心归属 `application/`
2. **避免循环依赖**：Application 运行时不反向导入 Web
3. **会话类型统一**：使用 `SessionState` 数据类
4. **失败关闭**：Planner 或步骤校验失败时不回退关键词路由
5. **职责单一**：每个模块职责明确

---

## 6. 相关文档

- [架构概览](./架构概览.md)
- [代码级设计说明](./代码级设计说明.md)
- [统一Planner架构](./统一Planner架构.md)
