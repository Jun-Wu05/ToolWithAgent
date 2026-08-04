# ADR-0001：自定义对话历史而非 Agno 原生记忆

**日期**：2026-07-16
**状态**：已采纳

## 背景

项目使用 Agno 框架（v2.5.17）的 Team route 模式 + 4 个 MemberAgent。Agno 提供原生记忆机制：`add_history_to_context=True` + `num_history_runs` + `db=SqliteDb` + `session_id`。

需要在多轮对话中让 Agent 记住上下文（如用户上传文件后问"帮我映射字段"，Agent 应知道已上传）。

## 决策

采用**自定义对话历史**（`web/history_store.py` + `SessionState.conversation_history`），而非 Agno 原生记忆。

历史存在 `SessionState.conversation_history`（Chainlit `user_session` 里，天然 per-session 隔离），由 `build_llm_input` 拼进 prompt 文本，Team 保持无状态单例。

## 理由

1. **Agno route 模式 session_id 传播有已知 bug**（agno-agi/agno#3534）——route 模式下 session_id 向 member 的传播不可靠，历史可能不生效。
2. **member 直调路径绕过 Team**——`llm_client.py` 在 intent 明确时直调 `member.run()` 跳过 RouterAgent，Agno 原生历史在 member 直调时不生效，需要给每个 member 单独配 db + session_id，比自定义更复杂。
3. **可维护性**——自定义历史在 web 层透明可控（存储、裁剪、窗口全在 `history_store.py` 可见），不依赖 Agno session 黑盒。Agno 升级（如 v2→v3 API 变更）不会破坏历史逻辑。
4. **暂不需跨进程持久化**——当前需求是会话内上下文顺畅，自定义完全够用。未来如需重启恢复，可在自定义基础上加持久化层。

## 后果

- **正面**：历史逻辑完全可控、可调试；不依赖 Agno session 机制；适配现有的 member 直调快路径架构。
- **负面**：未获得 Agno 框架的自动历史管理（存储、裁剪、跨会话）；如未来需要持久化，需自行实现。
- **不变**：Team 保持模块级单例（所有用户共用），不需要改 per-session 实例。
