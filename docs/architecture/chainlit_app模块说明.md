# Chainlit Web 模块说明

> **文档版本**：2026-08-31
> **对应分支**：`codex/issue144-documentation-zero-regression`
> **架构决策**：ADR-0009

---

## 1. 边界

`web/` 是 Chainlit 适配层，只负责输入、生命周期、每会话并发锁、进度和结果渲染。业务请求、执行策略、会话状态、模型生命周期、字段检索、文件解码和全部 StepAdapter 归属 `application/`。

## 2. 模块职责

| 模块 | 职责 | Application 接缝 |
|---|---|---|
| `chainlit_app.py` | 注册聊天启动、设置更新、消息三个生命周期钩子 | 只转发到 Web handler |
| `start_handler.py` | 创建 SessionState、设置 UI、日志桥和字段缓存初始化 | SessionState、field_runtime |
| `settings_handler.py` | 设置控件、模型列表、连接探针和用户反馈 | model_runtime |
| `message_router.py` | 每会话锁、Team 获取、文件/文本分发和请求追踪 | model_runtime |
| `file_handlers.py` | 读取 Chainlit 元素、Excel 分流、表格展示和上传提示 | file_input、enum_mapping_attachments |
| `user_message_handlers.py` | 调用自然语言请求运行时并渲染决策/报告 | request_runtime |
| `action_callbacks.py` | 注册 10 个用户可见 Action callback 并构造完整 StepSpec | deterministic_plan |
| `deterministic_plan.py` | 为按钮请求装配进度并转发执行 | request_runtime |
| `chainlit_progress.py` | ProgressEvent → 持续更新的 TaskList | contracts.progress |
| `plan_renderer.py` | Clarification、Guidance、ExecutionReport、表格与附件 | contracts.planner_models |
| `llm_client.py` | Agno 日志桥与 Token 用量观测 | 无业务执行 |
| `file_handler.py`、`parsers.py`、`utils.py` | Chainlit 元素/展示辅助与安全解析 | 无运行时所有权 |

## 3. 注册门禁

生命周期只允许注册一次：

- `@cl.on_chat_start`
- `@cl.on_settings_update`
- `@cl.on_message`

Action callback 固定为 10 个：

1. fill_threat_with_field
2. confirm_fill
3. start_enum_fill
4. export_rules
5. export_sub_rules
6. apply_field_mapping
7. export_mapped_sub_rules
8. export_field_mapping_excel
9. export_batch_field_mapping_excel
10. export_enum_mapping_excel

`tests/test_web_entry_architecture.py` 静态校验注册数量和名称，并阻止 Web 入口直接拥有 Team、Provider 或字段检索依赖。

## 4. 数据流

### 4.1 文本

```text
Chainlit Message
  → message_router.on_message（同 Session 串行）
  → application.model_runtime.ensure_team
  → user_message_handlers.handle_user_message
  → application.request_runtime.run_user_request
  → PlanDecision / ExecutionReport
  → plan_renderer
```

### 4.2 文件

```text
Chainlit Element
  → file_handlers（读取、类型识别）
  ├─ 数据 Excel → application.file_input.commit_primary_dataset
  ├─ Base64/JSON/TXT → application.file_input.simple_decode + commit_primary_dataset
  └─ 枚举附件 → application.enum_mapping_attachments.commit_enum_mapping_attachment
  → Chainlit 用户反馈
```

新的有效主数据原子替换旧数据；无效上传不改变当前主数据。Web 不直接维护 Session 生命周期规则。

### 4.3 按钮

```text
Action callback
  → 完整 StepSpec / ExecutePlan
  → application.request_runtime.run_deterministic_plan
  → ExecutionReport
  → plan_renderer
```

按钮名称、参数、表格、提示与附件是用户可观察契约。确定性按钮不调用 Planner。

## 5. 设置与启动

启动时从环境配置或会话覆盖懒初始化 Team；用户无需先保存设置。连接探针成功后才应用新配置并重置 Team，失败时保留旧设置。`application/model_runtime.py` 统一密钥解析、配置应用和 Team 生命周期，Web 只维护控件与提示。

## 6. 进度和安全

Application 发布 ProgressEvent；Web 维护一个持续更新的 Chainlit TaskList。超过 10 秒无新阶段时只刷新等待时间。界面和日志不得展示隐藏推理、API key、真实路径、原始日志样本或完整模型 JSON。用户主动提交的自然语言可以按既有策略记录明文，文件内容和认证信息不适用该例外。

## 7. 相关文档

- [架构概览](./架构概览.md)
- [代码级设计说明](./代码级设计说明.md)
- [统一 Planner 架构](./统一Planner架构.md)
- [测试场景手册](./测试场景手册.md)
