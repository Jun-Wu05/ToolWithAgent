# ToolWithAgent V2 技术实施规格

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不改变现有 Chainlit 入口行为的前提下，新增可独立启动、持久化、可诊断的 React + FastAPI V2，并优先交付“上传 → 字段映射 → 对话内摘要 → 原位放大编辑 → 原子应用 → 新产物版本”的完整垂直切片。

**Architecture:** V2 采用独立 Web/API/Worker/SQLite 运行面，API 负责鉴权、命令校验与查询，Worker 从持久化 FIFO 队列领取 Run，在 Application 公共边界内调用既有 Planner、PlanExecutor 和 Adapter。V2 不读取、不迁移、不双写 Chainlit Session；两个入口只共享 Application/Contracts/Agent 业务源码与只读标准字段表。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、SQLAlchemy 2、Alembic、SQLite（WAL）、Uvicorn、cryptography、React 18、TypeScript、Vite、React Router、TanStack Query、Vitest、Testing Library、Playwright、pytest。

---

## 1. 文档状态与约束

- 状态：可拆 Issue、可按任务实施。
- 产品基线：`docs/prd/toolwithagent-v2-product-experience.md`。
- 交互基线：`docs/design/prototypes/` 下四个 V2 原型；当前只锁定布局和交互，不锁定最终视觉。
- 架构决策：`docs/adr/0009-application-runtime-ownership.md`、`docs/adr/0011-bounded-self-recovery.md`、`docs/adr/0013-chainlit-v2-parallel-entry.md`。
- 现有 Chainlit 启动命令、端口、依赖环境、Session 和导出行为保持不变。
- 共享 Application 代码的扩展必须默认兼容现有调用方；禁止为 V2 复制字段映射、字段调整、枚举、威胁映射或导出实现。
- 本规格中的“消息”是产品展示记录，“Task”是原子业务操作，“Run”是一次执行尝试，“Artifact”是成功后发布的不可变正式产物，“Draft”不是 Artifact，也不得进入 Agent 输入。

## 2. 首版范围

### 2.1 必须交付

1. 开发期角色模拟：User、Developer、Admin；后端权限检查不能只依赖前端隐藏。
2. 会话、消息、文件、Task、Run、执行事件、调用、Artifact、Draft、确认事项、审计的 SQLite 持久化。
3. 单 Worker 持久化 FIFO 队列；重启恢复排队任务，运行中任务转为可诊断失败，不自动重复产生业务副作用。
4. User 工作台、任务列表、运行记录、右侧执行/产物抽屉。
5. 对话内嵌字段映射摘要，以及保留左侧导航和 Composer 的原位放大编辑。
6. 对话内嵌字段变更摘要，以及按变更组选择、确认、原子应用和整次撤销。
7. Developer Run 详情页。
8. Admin 系统状态、队列、Provider/模型、用户角色和审计。
9. 模型超时/结构化输出错误的一次自动重试、用户重跑、取消、迟到结果丢弃。
10. 同一组脱敏样本的 Chainlit/V2 双入口兼容验收。

### 2.2 明确不做

- Chainlit 历史迁移、双写或共享任务中心。
- 完整登录、SSO、多租户和细粒度数据授权。
- 多 Worker、队列调序、分布式锁、消息中间件。
- 通用 Workflow 编排器、Terminal、Skill 商店、复杂 Artifact DAG。
- 在线编辑标准字段表、Prompt 或用户正式产物。
- 枚举手工编辑器、成本大屏和最终品牌视觉。

## 3. 目标目录与依赖边界

```text
v2/
  backend/
    pyproject.toml
    alembic.ini
    alembic/
      env.py
      versions/
    toolwithagent_v2/
      api/
        app.py
        dependencies.py
        errors.py
        routes/
          auth.py
          conversations.py
          uploads.py
          tasks.py
          runs.py
          artifacts.py
          mapping_drafts.py
          field_changes.py
          developer.py
          admin.py
      application/
        commands.py
        queries.py
        permissions.py
        run_service.py
        mapping_draft_service.py
        field_change_service.py
        artifact_service.py
        diagnostic_service.py
      domain/
        enums.py
        transitions.py
        errors.py
      infrastructure/
        db.py
        models.py
        repositories.py
        blob_store.py
        queue.py
        redaction.py
        standard_field_version.py
      runtime/
        application_bridge.py
        persisted_session.py
        progress_recorder.py
        worker.py
      settings.py
      main.py
    tests/
      unit/
      integration/
      contract/
  frontend/
    package.json
    vite.config.ts
    src/
      app/
      api/
      components/
      features/
        workbench/
        mapping-editor/
        field-changes/
        execution-drawer/
        run-detail/
        admin/
      routes/
      styles/
      test/
    tests/e2e/
  data/
    .gitkeep
  README.md
```

允许的依赖方向：

```text
V2 React → V2 FastAPI → V2 application → V2 domain
                         │
                         ├─→ V2 infrastructure
                         └─→ V2 runtime bridge → 根目录 application/ → contracts/
                                                   └─ adapters → agent/domain/skills

Chainlit web/ ────────────────────────────────→ 根目录 application/
```

边界规则：

- `v2/backend/toolwithagent_v2/runtime/application_bridge.py` 是 V2 调用既有 Application 的唯一组合入口。
- 根目录 `application/`、`contracts/`、`agent/` 不得导入 `toolwithagent_v2`。
- V2 API 路由不得直接调用根目录 Adapter，也不得直接执行模型；只提交命令或查询。
- Worker 不持有 HTTP Request、浏览器连接或内存 Session。它从数据库重建 `PersistedSession`，调用 bridge，并以数据库事务发布结果。
- 前端不得根据中文提示词推断状态；只消费稳定枚举、错误码和能力字段。

## 4. 运行拓扑

```text
Browser :5173
    │ HTTP + SSE
    ▼
FastAPI :8100 ── SQLite WAL ── V2 Worker
    │                 │             │
    │                 ├─ metadata   ├─ Application bridge
    │                 └─ queue      └─ uploads/artifacts blob store
    ▼
GET/POST commands and projections

Chainlit :8000 ──────────────── Application（原路径不变）
```

- 开发默认端口：前端 `5173`、API `8100`、Chainlit `8000`。
- API 和 Worker 是两个独立进程，使用同一个 V2 数据目录。
- 实时更新使用 SSE；状态变更仍以数据库为事实源，SSE 断线后用 `after=<event-sequence>` 补取，不依赖进程内广播保证正确性。
- SQLite 开启 foreign keys、busy timeout 和 WAL。首版只允许一个 Worker；设置 `V2_WORKER_CONCURRENCY` 仅控制未来扩展预留，首版校验值必须为 1。
- 上传文件与正式产物存文件系统，数据库只保存相对存储键、哈希、大小、类型和血缘。任何 API 不返回服务器绝对路径。

## 5. 持久化模型

所有 ID 使用 UUID 字符串；所有时间以 UTC ISO 8601 存储；表含 `created_at`，可变聚合含 `updated_at` 和整数 `revision` 做乐观并发。

| 表 | 关键字段与约束 |
|---|---|
| `users` | `id`、`display_name`、`role`、`is_active`；开发期预置三个模拟用户 |
| `conversations` | `id`、`owner_id`、`title`、`archived_at` |
| `messages` | `conversation_id`、`actor`、`kind`、`content_json`；内容是安全展示投影，不保存隐藏推理 |
| `files` | `owner_id`、`conversation_id`、`original_name`、`media_type`、`size`、`sha256`、`storage_key`、`parse_status` |
| `tasks` | `conversation_id`、`owner_id`、`type`、聚合 `status`、`current_run_id` |
| `runs` | `task_id`、`attempt`、`status`、不可变 `input_snapshot_json`、`provider_config_revision`、`prompt_version`、`standard_field_version`、`queued_at`、`started_at`、`finished_at`、`cancel_requested_at`、`lease_owner`、`lease_expires_at`、`leader_epoch`、`fence_token`、`error_code` |
| `worker_leases` | 固定主键 `v2-primary`、`owner_id`、`lease_expires_at`、单调递增 `epoch`；全局只允许持有者领取 Run |
| `run_events` | `run_id`、`sequence`、`scope_type`、`scope_id`、`event_type`、`status`、`summary_json`；唯一 `(run_id, sequence)` |
| `conversation_events` | `conversation_id`、单调递增 `sequence`、`event_type`、`resource_type`、`resource_id`、安全 `payload_json`；唯一 `(conversation_id, sequence)`，作为 SSE outbox |
| `model_calls` | Run/Task/Skill/Tool/Request ID、Provider、模型、参数、Prompt/标准字段版本、重试序号、耗时、截断后的输入输出、错误码 |
| `artifacts` | `conversation_id`、`task_id`、`run_id`、`kind`、`version`、`status`、`storage_key`、`sha256`、`metadata_json`；成功事务内发布 |
| `artifact_edges` | `source_artifact_id`、`derived_artifact_id`、`relation`；用于过期传播，不提供通用图编辑 |
| `drafts` | `owner_id`、`conversation_id`、`base_artifact_id`、`kind`、`revision`、`status` |
| `draft_operations` | `draft_id`、`operation_key`、`scope_json`、`before_json`、`after_json`、`validation_json`；同一 key 幂等覆盖 |
| `confirmations` | `task_id`、`run_id`、`checkpoint_id`、`checkpoint_revision`、一次性 `token_sha256`、`kind`、`payload_json`、`status`、`expires_at`、`resolved_by`、`resolved_at` |
| `execution_checkpoints` | `run_id`、序列化类型化计划/确定性 continuation、下一动作、已完成结果引用、`revision`；不保存用户原文的新解释 |
| `idempotency_receipts` | `principal_id`、`operation_scope`、`key`、`request_sha256`、`status`、结果资源与响应投影；唯一 `(principal_id, operation_scope, key)` |
| `provider_configs` | Provider 当前 revision 指针；每次修改创建不可变配置版本 |
| `provider_config_versions` | `provider`、`model`、非敏感参数、`secret_version_id`、`revision`；Run 固定引用该 revision |
| `provider_secrets` | `ciphertext`、`nonce`、`key_id`、`created_at`；只保存认证加密结果，永不经读取 API 返回 |
| `audit_events` | 操作者、角色、动作、目标、原因、脱敏前后值、request ID、时间；只追加 |

### 5.1 状态机

Run 状态为 `queued`、`running`、`waiting_confirmation`、`succeeded`、`failed`、`cancelling`、`cancelled`。数据库只允许：

```text
queued → running | cancelled
running → waiting_confirmation | succeeded | failed | cancelling
waiting_confirmation → queued | failed | cancelling
cancelling → cancelled
```

- Task 是其当前 Run 的聚合投影；新 Run 创建时 Task 可从 `failed/cancelled/succeeded → queued`，历史 Run 不变。Task 不自行驱动执行。
- Worker 进程必须先竞争数据库中的全局 `v2-primary` lease 并定期续租；只有持有者可领取 Run。误启动的第二个进程保持 standby，不执行模型任务；持有者失联且 lease 过期后，standby 在接管事务中递增全局 `epoch`。
- 全局 lease 持有者领取 Run 时用单事务条件更新 `queued → running`，并把当前 `epoch` 写入 Run；FIFO 排序为 `queued_at, id`。
- 用户重跑创建同一 Task 的新 Run，`attempt + 1`，复制原 Run 的全部冻结快照：输入 Artifact/文件版本、类型化参数、Provider 配置 revision、Prompt 版本和标准字段版本。密钥由该配置 revision 的 secret version 在执行时解密，不复制密钥值。
- 排队取消在一个事务内直接 `queued → cancelled`；只有运行中或等待确认的 Run 才进入 `cancelling → cancelled`。
- Admin 强停会递增 `fence_token`、撤销 lease、记录原因并进入 cancelling/cancelled。Worker 发布结果时必须同时匹配 Run 状态、Run lease/fence，以及当前全局 leader 的 owner/epoch。leader 接管会使旧 leader 的运行中 Run 失去发布资格，并由恢复流程标记 `worker_lost`。
- 取消后到达的模型响应可以进入诊断记录，但提交事务必须检查 Run 仍为 `running`，否则丢弃业务结果。
- 进程异常遗留的 `running` Run 在启动恢复时标记 `failed / worker_lost`；用户可显式重跑。

等待确认时，Worker 在同一事务内保存 `execution_checkpoints`、确认事项、Run/Task 状态和 conversation outbox。确认事务必须同时校验：Task 的 current_run、Run 状态、run_id、checkpoint_id/revision、未过期的一次性 token 哈希；旧 Run 或旧 checkpoint 的确认一律拒绝。确认后只把已持久化的类型化 continuation 写入同一 Run，并执行 `waiting_confirmation → queued`；Worker 从 checkpoint 的下一动作继续，禁止重新调用 Planner 或重新解释用户原文。刷新、API 重启和 Worker 重启后均遵守此规则。

`ExecutionContinuation` 是根目录 Application 的可序列化最小契约，包含剩余 StepSpec、已完成结果 ledger 的 Artifact/诊断引用、依赖结果引用、恢复预算计数和创建时 SessionFacts digest。续跑前重新计算 digest；影响执行语义的事实已变化则以 `continuation_stale` 安全失败，不从头重跑。

### 5.2 Artifact 与 Draft

- 正式 Artifact 不可变；新版本使用同一 `kind` 下递增版本号。
- Blob 发布采用明确协议：先写唯一 staging key 并 fsync，校验哈希后在同卷原子 rename 到内容寻址 final key，最后用 SQLite 事务发布 Artifact、血缘、消息、状态和 outbox。final Blob 可在 DB 提交前短暂成为孤儿，但 DB 不得指向缺失 Blob。
- 启动对账删除超过保留期且无 Artifact 引用的 staging/orphan Blob；已发布 Artifact 缺 Blob 或哈希不符时标记 `corrupt` 并拒绝下载。测试必须覆盖写 staging、rename 后、DB commit 前后四个崩溃点。
- Task 只有在全部校验成功的 SQLite 事务中，才同时写 Artifact 元数据、血缘、消息结果摘要、状态和 outbox。
- 失败运行保留诊断快照，但不创建 `status=current` 的 Artifact。
- Draft 基于一个明确的 `base_artifact_id`；自动保存只改变 Draft。
- 应用 Draft 时校验 `base_artifact_id` 仍是预期版本、`revision` 匹配、标准字段未重复占用、目标未进黑名单；任一失败则事务回滚并保留 Draft。
- 上游新版本成功后，沿 `artifact_edges` 将下游标为 `stale`，不删除旧版本。

所有带 `Idempotency-Key` 的命令先在同一数据库事务内创建或读取 receipt。相同主体、操作域、key 和请求哈希返回原资源/响应；相同 key 但请求哈希不同返回 `idempotency_key_reused`；业务结果与 completed receipt 同事务提交。服务重启不影响去重。

## 6. HTTP 与事件契约

统一前缀 `/api/v2`。成功响应返回资源或命令结果；错误统一为：

```json
{
  "error": {
    "code": "mapping_target_conflict",
    "message": "该标准字段已被占用",
    "details": {},
    "request_id": "..."
  }
}
```

`code` 稳定，`message` 可本地化，`details` 不含密钥、Authorization、Cookie、服务器绝对路径或隐藏推理。创建消息/Run、retry、确认、Draft apply、undo 和管理写接口必须接受 `Idempotency-Key` 并使用持久化 receipt；Draft 修改同时接受 `If-Match: <revision>`。

### 6.1 身份、会话与文件

| 方法与路径 | 用途 |
|---|---|
| `GET /dev/identities`、`POST /dev/session` | 仅开发模式列出/切换模拟身份；生产模式路由不存在 |
| `GET /me` | 返回当前用户和能力集合 |
| `GET/POST /conversations` | 列表、新建会话 |
| `GET /conversations/{id}` | 返回会话头、消息投影、当前事项与最近 Artifact |
| `GET /conversations/{id}/events?after={sequence}` | SSE：只按 `conversation_events.sequence` 返回状态、进度、确认、消息和 Artifact outbox |
| `POST /conversations/{id}/messages` | 提交用户指令；有未应用 Draft 时返回 `draft_resolution_required` |
| `POST /conversations/{id}/files` | 流式上传、大小/类型校验、哈希去重和解析登记 |

### 6.2 Task、Run 与 Artifact

| 方法与路径 | 用途 |
|---|---|
| `GET /tasks?scope=mine&status=` | User 任务中心 |
| `GET /runs?scope=mine` | User 运行记录 |
| `GET /runs/{id}` | 按角色返回业务投影或诊断投影 |
| `POST /runs/{id}/retry` | 以冻结输入创建新 Run |
| `POST /runs/{id}/cancel` | 所有人只能取消权限范围内的 Run；需确认令牌 |
| `GET /artifacts/{id}` | 元数据、版本、来源、过期状态 |
| `GET /artifacts/{id}/content` | 小内容按角色预览；大内容分页/截断 |
| `GET /artifacts/{id}/download` | 下载并追加审计，复用现有文件名逻辑 |

### 6.3 字段映射 Draft

| 方法与路径 | 用途 |
|---|---|
| `GET /artifacts/{id}/mapping-view?sub_rule=&page=&page_size=50&q=&status=` | 服务端跨整条子规则搜索/筛选/分页 |
| `GET /standard-fields?exclude_used_for=&q=` | 返回可选中文标准字段及禁用原因 |
| `POST /artifacts/{id}/mapping-drafts` | 获取或创建当前用户 Draft |
| `PATCH /mapping-drafts/{id}/operations/{operation_key}` | 幂等保存单项修改并返回校验与联动候选 |
| `POST /mapping-drafts/{id}/replacement-confirmations` | 确认或取消“目标已占用”的替换操作 |
| `GET /mapping-drafts/{id}/same-source-candidates/{operation_key}` | 精确字段路径的跨子规则候选；冲突项不可选 |
| `POST /mapping-drafts/{id}/apply` | 原子应用全部已选修改，生成新 Artifact |
| `DELETE /mapping-drafts/{id}` | 丢弃 Draft |

字段行投影至少包含：`sub_rule_id`、`source_path`、原始字段、前三个去重非空样例、可展开的最多二十个带行号样例、当前标准字段、匹配证据、后端生成的提醒、状态、是否用户修改。下拉返回全部合法中文标准字段；已被当前子规则占用的目标仍可见并标记占用者，不能静默隐藏。用户选择占用目标时，后端返回替换确认；确认后以一个 Draft operation 原子表达“旧占用清空 + 新映射写入”，取消则不改变 Draft。事件名称、事件级别、日志类型和威胁类型等映射黑名单始终不可选。

### 6.4 字段变更

| 方法与路径 | 用途 |
|---|---|
| `GET /runs/{id}/field-change-preview` | 返回按子规则和原子组组织的业务变更 |
| `POST /runs/{id}/field-change-selection` | 保存组选择；不可拆的组由后端声明 |
| `POST /runs/{id}/field-change-apply` | 校验确认令牌并原子应用选中组 |
| `POST /artifacts/{id}/undo` | 针对一次提交生成恢复版本 |

Draft apply 不改写产生映射结果的历史 Run。API 以幂等命令冻结 `base_artifact_id + draft_id + draft_revision`，创建新的确定性 Task/Run，由 Worker 校验并发布新 Artifact；undo 同理冻结目标 Artifact/version 并创建新的确定性 Task/Run。两者都使用创建时的 Provider/Prompt/标准字段版本快照，若命令完全不需要模型则 Provider 只作审计引用。

若包含删除，apply 前必须先通过 `POST /tasks/{id}/confirmations` 创建一次绑定当前 run/checkpoint/revision 的合并确认；确认负载列出删除字段和下游影响。未选组在原 Run 中记为 `not_applied_by_user`，不保留为永久待办。明确的单字段、非删除且目标无歧义的变更可由 Worker 直接执行并发布版本，不进入 waiting_confirmation，但结果仍提供整次撤销。

### 6.5 Developer 与 Admin

- `GET /developer/runs/{id}/overview|timeline|calls|logs|artifacts`
- `GET /developer/runs/{id}/diagnostic-package`
- `GET /admin/system`
- `GET /admin/queue`
- `POST /admin/runs/{id}/force-stop`，body 必须包含非空原因
- `GET/PUT /admin/providers/{provider}`
- `POST /admin/providers/{provider}/test`
- `GET/PATCH /admin/users/{id}`
- `GET /admin/audit-events`

Developer 路由只读；Admin 不能编辑标准字段、Prompt 或正式 Artifact。Provider 更新只影响新 Run。管理端可重新输入密钥，但服务只保存由部署主密钥认证加密后的新 secret version；读取响应永远只返回 `configured: true|false`。旧 secret version 为重跑冻结 Run 保留，按数据保留策略清理。

## 7. V2 到既有 Application 的适配

### 7.1 PersistedSession

`runtime/persisted_session.py` 实现当前 Application 所需的最小 `get/set` 会话协议，但其数据来自某个 Run 的冻结快照：

- 读取：Run 输入 Artifact、已声明附件、模型配置快照、有限历史和安全 SessionFacts。
- 写入：先写入内存 staging 区，不直接修改数据库或 Blob。
- 提交：bridge 把成功后的 staging 转为候选 Artifact，由 V2 事务统一发布。
- 失败/取消：丢弃 staging，诊断事件单独保存。

不得把整个 ORM Session 伪装成 Chainlit Session，也不得让根目录 Application 知道数据库模型。

### 7.2 Application bridge

`runtime/application_bridge.py` 暴露三个 V2 内部入口：

```python
async def plan_and_execute(command: RunCommand, sink: RunRecorder) -> RunOutcome: ...
async def execute_deterministic(command: DeterministicRunCommand, sink: RunRecorder) -> RunOutcome: ...
async def resume_from_checkpoint(command: ContinuationCommand, sink: RunRecorder) -> RunOutcome: ...
async def apply_draft(command: DraftApplyCommand, sink: RunRecorder) -> RunOutcome: ...
```

- 自然语言仍调用 `application.request_runtime.run_user_request`，每次初始规划恰好一次 Planner。
- 等待确认前保存类型化 checkpoint；确认、Draft 应用、撤销和 checkpoint 续跑走确定性入口，不重新解释用户原文或重复已完成步骤。
- `application.adapters.composition.create_default_adapters` 仍是生产 Adapter 唯一组合入口。
- bridge 负责把 Application 的 ProgressEvent、ExecutionReport、Artifact 和稳定错误码翻译为 V2 记录；不改写业务语义。
- 如果现有公共接口不足，只能在根目录 `application/` 新增默认兼容的协议或回调，并增加 Chainlit 回归测试；不得从 V2 导入 `web/` 私有函数。

### 7.3 Worker 循环

1. 在短事务内按 FIFO 领取一条 queued Run，写 lease、fence token、状态、run event 和 conversation outbox。
2. 关闭事务，加载冻结输入到 PersistedSession。
3. 在 Run 作用域内解析 Provider/模型快照并执行 bridge。
4. 每个进度节点追加 run_event；需要推送到用户的变化在同一事务写 conversation outbox；模型调用写 model_calls，并先经 redaction。
5. 每个可取消边界检查 `cancel_requested_at`。
6. 成功时先完成 Blob staging/rename，再在一个短事务内校验状态、lease 与 fence，发布 Artifact 元数据、更新血缘/过期状态、消息、Run/Task 和 outbox。
7. 失败时保存错误码、可见摘要和诊断引用，不发布正式 Artifact。
8. 清理 lease；继续领取下一条。

V2 Worker 不新增业务重试层，只记录既有 Application/Adapter 产生的 retry/recovery 事件，避免和 ADR-0011、字段映射批处理重复叠加。契约测试必须锁定：Planner 失败不重试；允许的瞬时步骤同参最多一次；正则生成保留既有一次修复重试；威胁来源最多一次重推导；每计划总恢复预算沿用 ADR-0011。用户重跑才创建新 Run。

## 8. 前端信息架构与状态

### 8.1 路由

```text
/                         → 重定向 /workbench/:conversationId 或新会话
/workbench/:conversationId
/tasks
/runs
/developer/runs/:runId
/admin
/admin/runs
/admin/providers
/admin/users
/admin/audit
```

路由守卫只用于体验；API 仍逐请求鉴权。Developer 可访问诊断页但不能访问管理写接口；Admin 包含 Developer 读取能力。

### 8.2 工作台组合

`features/workbench/WorkbenchPage.tsx` 固定包含：

- `ConversationSidebar`
- `ConversationHeader`
- `ConversationTimeline`
- `ActiveTaskBanner`
- `Composer`
- 单实例 `ContextDrawer`

字段映射与字段变更不是独立顶级路由。对话结果卡点击“查看结果/查看变更”后，`WorkbenchPage` 把中间区域切换为 `MappingEditorWorkspace` 或 `FieldChangeWorkspace`；左侧栏、Composer、会话 ID 和右侧抽屉保持不变。应用成功后恢复时间线，并滚动到新结果消息。

### 8.3 数据获取与交互规则

- TanStack Query 管理服务端状态；组件本地状态只保存展开、选中 Tab、当前页和临时输入。
- SSE 事件只消费持久化 conversation outbox，用于缓存失效和增量提示；页面刷新后必须完全通过 REST 恢复。
- Draft 每次编辑先更新本地行，再做 300–500ms 防抖 PATCH；离开前无需依赖浏览器 unload 保存。
- 服务端返回 revision 冲突时停止自动覆盖，重新获取并提示用户选择重新加载。
- 搜索、筛选和分页由后端执行；切换页不丢 Draft 标记。
- 状态必须同时使用文字/图标，不只依赖颜色。
- 默认浅色；主题仅存 localStorage，不进入服务端业务模型。
- 所有业务文本按普通文本渲染；原始 JSON 使用安全代码查看器，不用 `dangerouslySetInnerHTML`。

## 9. 权限、安全与隐私

| 能力 | User | Developer | Admin |
|---|---:|---:|---:|
| 读写自己的会话/任务/Draft | 是 | 否 | 否 |
| 取消自己的 Run | 是 | 否 | 是（管理动作） |
| 查看所有 Run 诊断 | 否 | 只读 | 只读 |
| 下载诊断包 | 否 | 是 | 是 |
| 强停异常 Run | 否 | 否 | 是，必须填原因 |
| Provider/模型、用户角色 | 否 | 否 | 是 |
| 编辑正式 Artifact/标准字段/Prompt | 否 | 否 | 否 |

- 资源查询必须同时按主体和能力过滤，不能“先查出再在前端隐藏”。
- 上传名永不直接作为磁盘路径；storage key 由系统生成，下载文件名经白名单清理。
- 限制单文件大小、请求体、JSON 展示大小和诊断包内容；大字段按需加载。
- redaction 在写日志、model_calls、audit 和诊断包前执行，覆盖 API key、Authorization、Cookie、常见 secret 字段和 ProviderSpec 声明的密钥环境变量。
- 不存储或展示模型思维链。可展示确定性验证事实、候选证据、输入输出和“可能原因”，但推测必须显式标注。
- Provider 密钥使用部署提供的主密钥做认证加密；主密钥缺失时拒绝密钥写入和依赖密钥的 Run，并返回 `secret_key_unavailable`，不能降级为明文。密文记录带 `key_id`，轮换时先加入新 key，再由维护命令重包旧 secret，确认无旧引用后移除旧 key。明文只存在于请求/执行进程内存，不写入 Run 快照、日志、审计或诊断包。
- 所有管理写操作写 audit_events；敏感字段 before/after 只记录 configured 状态变化。

## 10. 配置、启动与故障恢复

V2 使用独立环境变量前缀：

```text
TWA_V2_ENV=development
TWA_V2_API_HOST=127.0.0.1
TWA_V2_API_PORT=8100
TWA_V2_DATABASE_URL=sqlite:///.../v2/data/toolwithagent-v2.db
TWA_V2_UPLOAD_DIR=.../v2/data/uploads
TWA_V2_ARTIFACT_DIR=.../v2/data/artifacts
TWA_V2_WORKER_ID=worker-local-1
TWA_V2_WORKER_CONCURRENCY=1
TWA_V2_SESSION_SIGNING_KEY=...
TWA_V2_SECRET_MASTER_KEY_ID=local-v1
TWA_V2_SECRET_MASTER_KEY=...
TWA_V2_MAX_UPLOAD_MB=50
```

精确开发命令在实现后固化为：

```powershell
python -m venv v2/.venv
v2/.venv/Scripts/pip install -e ./v2/backend
v2/.venv/Scripts/python -m alembic -c v2/backend/alembic.ini upgrade head
v2/.venv/Scripts/python -m toolwithagent_v2.main api
v2/.venv/Scripts/python -m toolwithagent_v2.main worker
npm --prefix v2/frontend install
npm --prefix v2/frontend run dev
```

Chainlit 仍使用 `chainlit run web/chainlit_app.py`，不加载 V2 数据库迁移，也不要求 V2 进程存在。

启动恢复规则：

- 数据库迁移失败：API/Worker 拒绝启动，Chainlit 不受影响。
- Blob 缺失或哈希不符：相关 Run 以稳定错误码失败，旧 Artifact 元数据保留。
- Worker 丢失：过期 lease 的 running Run 标为 `worker_lost`，不静默重放。
- SSE 断开：前端指数退避重连并从最后 sequence 补取。
- Provider 配置变更：只影响创建后的 Run；进行中 Run 使用冻结快照。
- API/Worker 启动：执行 Blob 对账，清理超期 staging/orphan；已发布但损坏的 Artifact 标为 corrupt。

## 11. 测试策略与合入门禁

测试分为六层：

- 后端单元测试：Task/Run 状态转换、权限、脱敏、Draft 校验、FIFO、Artifact 版本。
- 后端集成测试：真实临时 SQLite 与 Blob 目录，覆盖事务、确认后续跑、outbox 补取、重启幂等、revision 和 Blob crash point。
- Application 契约测试：验证 bridge 的冻结输入、事件转换、成功发布、失败不发布和取消。
- 前端组件测试：嵌入结果、原位切换、Draft 自动保存、冲突、权限和主题。
- Playwright E2E：启动 API、Worker 和前端，用测试 Provider 跑关键路径。
- 双入口验收：同一脱敏样本从 Chainlit 与 V2 执行，比对结果、文件名和平台导入。

每个实现 Issue 的最小门禁：

```powershell
python -X utf8 -m pytest -q
v2/.venv/Scripts/python -m pytest -q v2/backend/tests
npm --prefix v2/frontend run test -- --run
npm --prefix v2/frontend run lint
npm --prefix v2/frontend run build
```

涉及端到端行为时增加 `npm --prefix v2/frontend run test:e2e`。涉及根目录生产 Python 时，先运行 `python -X utf8 scripts/generate_source_code_analysis.py`，再跑全量 pytest。V2 实施符合仓库 worktree 判据，按 `docs/agents/issue-workflow.md` 从 master 建短命分支和独立 worktree。

## 12. 分阶段实施计划

以下任务都按红—绿—重构执行；commit 文案是建议值，实际实施仍需关联 Issue 并遵守仓库 SOP。

### Task 1：建立 V2 独立骨架和架构门禁

**Files:**
- Create: `v2/backend/pyproject.toml`
- Create: `v2/backend/toolwithagent_v2/{__init__.py,main.py,settings.py}`
- Create: `v2/backend/toolwithagent_v2/api/app.py`
- Create: `v2/backend/tests/contract/test_package_boundaries.py`
- Create: `v2/frontend/package.json`
- Create: `v2/frontend/src/app/App.tsx`
- Create: `v2/frontend/src/test/setup.ts`
- Create: `v2/README.md`
- Modify: `tests/test_application_composition_architecture.py`

1. 先写边界测试：根目录 Application/Contracts/Agent 不得导入 V2，V2 不得导入 `web`。
2. 运行目标测试，确认因包和入口不存在而失败。
3. 建立最小 FastAPI `/health/live`、React shell 和独立依赖文件。
4. 运行边界测试、后端测试、前端测试和构建。
5. 建议 commit：`feat(v2): scaffold isolated api and web entry`。

### Task 2：数据库、迁移与 Blob 存储

**Files:**
- Create: `v2/backend/alembic.ini`
- Create: `v2/backend/alembic/env.py`
- Create: `v2/backend/alembic/versions/0001_initial_runtime.py`
- Create: `v2/backend/toolwithagent_v2/infrastructure/{db.py,models.py,repositories.py,blob_store.py,idempotency.py,outbox.py}`
- Create: `v2/backend/toolwithagent_v2/domain/{enums.py,transitions.py,errors.py}`
- Create: `v2/backend/tests/unit/test_transitions.py`
- Create: `v2/backend/tests/integration/{test_migrations.py,test_blob_store.py,test_idempotency.py,test_outbox.py}`

1. 先测试 Task/Run 非法状态转换、空库迁移、Blob 路径穿越、哈希、四个发布崩溃点、outbox 单调序列和跨重启幂等。
2. 在 `0001_initial_runtime.py` 中实现第 5 节全部首版表（含全局 `worker_leases` 与 Run 的 `leader_epoch`）、外键、唯一约束、索引和 SQLite pragmas。
3. 用临时目录升级数据库，创建、关闭并重开，验证数据仍在。
4. 建议 commit：`feat(v2): add durable runtime schema and blob storage`。

### Task 3：开发身份、权限与审计底座

**Files:**
- Create: `v2/backend/toolwithagent_v2/application/permissions.py`
- Create: `v2/backend/toolwithagent_v2/api/{dependencies.py,routes/auth.py}`
- Create: `v2/backend/toolwithagent_v2/infrastructure/redaction.py`
- Create: `v2/backend/tests/unit/{test_permissions.py,test_redaction.py}`
- Create: `v2/backend/tests/integration/test_auth_and_audit_api.py`

1. 参数化测试 User/Developer/Admin 能力矩阵和跨用户 404/403。
2. 测试开发身份路由在 production 下不存在。
3. 测试密钥、Authorization、Cookie、嵌套 secret 在落库前脱敏。
4. 实现 request ID、中间件、模拟身份和只追加审计。
5. 建议 commit：`feat(v2): enforce roles and redact diagnostic data`。

### Task 4：会话、文件、消息与 REST/SSE 查询

**Files:**
- Create: `v2/backend/toolwithagent_v2/api/routes/{conversations.py,uploads.py}`
- Create: `v2/backend/toolwithagent_v2/application/{commands.py,queries.py}`
- Create: `v2/backend/tests/integration/{test_conversation_api.py,test_upload_api.py,test_conversation_events.py}`

1. 先测试新会话、流式上传、类型/大小拒绝、哈希、跨用户隔离和基于 conversation outbox 的 SSE 断线补取。
2. 文件解析复用 `application/file_input.py`；若缺少纯函数入口，先补兼容接口及根仓测试。
3. 消息只保存安全投影；未解决 Draft 时提交消息返回稳定冲突码。
4. 建议 commit：`feat(v2): persist conversations uploads and event streams`。

### Task 5：持久化队列、Worker 和取消语义

**Files:**
- Create: `v2/backend/toolwithagent_v2/infrastructure/queue.py`
- Create: `v2/backend/toolwithagent_v2/runtime/{worker.py,progress_recorder.py}`
- Create: `v2/backend/toolwithagent_v2/application/run_service.py`
- Create: `v2/backend/toolwithagent_v2/api/routes/{tasks.py,runs.py}`
- Create: `v2/backend/tests/integration/{test_fifo_queue.py,test_worker_leader_lease.py,test_worker_recovery.py,test_run_cancel.py,test_run_retry.py,test_confirmation_resume.py,test_force_stop_fence.py}`

1. 先测试 FIFO、全局 leader lease、两个 Worker 进程只有一个执行、失联后递增 epoch 接管、旧 leader 迟到结果不能发布、排队直接取消、重启后 queued 保留、过期 running → worker_lost、重跑复制完整冻结快照。
2. 测试确认 checkpoint 在 API/Worker 重启后从下一确定性动作继续，Planner 调用计数不增加；旧 Run/旧 revision/过期 token 的确认均失败。
3. 用可控 Future 模拟取消和 Admin 强停后的迟到响应，断言 lease/fence 失效、无 Artifact 且最终 cancelled。
4. 实现 Worker 命令、lease、fence、checkpoint 和短事务领取/发布。
5. 建议 commit：`feat(v2): add durable fifo worker and cancellation`。

### Task 6：Application bridge 与最小业务闭环

**Files:**
- Create: `v2/backend/toolwithagent_v2/runtime/{persisted_session.py,application_bridge.py}`
- Create: `v2/backend/toolwithagent_v2/application/artifact_service.py`
- Create: `v2/backend/toolwithagent_v2/api/routes/artifacts.py`
- Create: `v2/backend/tests/contract/{test_application_bridge.py,test_atomic_artifact_publish.py}`
- Create: `v2/backend/tests/integration/{test_artifact_api.py,test_artifact_download_names.py}`
- Modify: `application/execution.py`
- Modify only if required: `application/request_runtime.py`
- Modify only if required: `application/progress.py`
- Modify: `tests/test_application_execution_architecture.py`
- Create: `tests/test_execution_continuation.py`

1. 用根仓测试先定义 `ExecutionContinuation`：剩余步骤、ledger/依赖引用、恢复预算和 SessionFacts digest 可序列化；续跑不重复完成步骤，digest 漂移时安全失败。
2. 用 Fake Planner/Adapter 测试：自然语言一次 Planner、checkpoint 续跑和其他确定性命令零 Planner、成功 staging 发布、失败/取消不发布。
3. 锁定重试所有权：Worker 不重试；Application 的瞬时重试、正则修复、威胁重推导和总预算次数与 ADR-0011 一致。
4. 实现 Artifact 元数据/预览/下载路由，测试角色权限、corrupt 拒绝下载和现有文件名兼容。
5. 实现最小 Session 协议和 Progress recorder，不导入 Chainlit。
6. 运行根仓完整测试，确认 Chainlit 行为不变。
7. 建议 commit：`feat(v2): bridge durable runs to application runtime`。

### Task 7：React 工作台基础

**Files:**
- Create: `v2/frontend/src/api/{client.ts,types.ts,queries.ts,events.ts}`
- Create: `v2/frontend/src/routes/router.tsx`
- Create: `v2/frontend/src/features/workbench/{WorkbenchPage.tsx,ConversationSidebar.tsx,ConversationTimeline.tsx,ActiveTaskBanner.tsx,Composer.tsx}`
- Create: `v2/frontend/src/features/execution-drawer/ContextDrawer.tsx`
- Create: `v2/frontend/src/styles/{tokens.css,global.css}`
- Create: `v2/frontend/src/features/workbench/WorkbenchPage.test.tsx`

1. 先测抽屉默认关闭、状态提示、刷新恢复、停止入口、浅色默认和主题记忆。
2. 实现路由、Query Client、SSE 失效策略与响应式三栏骨架。
3. 视觉仅遵循已确认的布局原型和可访问性，不做最终品牌打磨。
4. 建议 commit：`feat(v2): build persistent conversation workbench`。

### Task 8：字段映射首条端到端垂直切片

**Files:**
- Create: `v2/backend/toolwithagent_v2/application/mapping_draft_service.py`
- Create: `v2/backend/toolwithagent_v2/api/routes/mapping_drafts.py`
- Create: `v2/backend/tests/unit/test_mapping_draft_validation.py`
- Create: `v2/backend/tests/integration/{test_mapping_draft_api.py,test_mapping_apply_atomicity.py}`
- Create: `v2/frontend/src/features/mapping-editor/{MappingResultCard.tsx,MappingEditorWorkspace.tsx,MappingTable.tsx,StandardFieldSelect.tsx,SameSourceDialog.tsx}`
- Create: `v2/frontend/src/features/mapping-editor/MappingEditorWorkspace.test.tsx`
- Create: `v2/frontend/tests/e2e/mapping-flow.spec.ts`

1. 后端先锁定：50 条分页、全子规则搜索、中文标准字段、黑名单、一对一占用、占用目标替换确认与取消、精确同路径联动、revision 冲突、失败保留 Draft。
2. 前端先锁定：结果默认嵌入对话；点击后只替换中间区域；左栏和 Composer 保留；应用后回到同一消息流。
3. 实现上传 Excel → Task/Run → Worker 映射 → 摘要 → 编辑 → 自动保存；apply 幂等创建冻结 base Artifact/Draft revision 的新确定性 Task/Run，再原子发布新 Artifact。
4. E2E 刷新 API/Worker 后恢复 Draft，并验证未应用 Draft 不进入 Agent 输入。
5. 建议 commit：`feat(v2): deliver embedded field mapping workflow`。

### Task 9：字段变更预览、应用与撤销

**Files:**
- Create: `v2/backend/toolwithagent_v2/application/field_change_service.py`
- Create: `v2/backend/toolwithagent_v2/api/routes/field_changes.py`
- Create: `v2/backend/tests/unit/test_field_change_groups.py`
- Create: `v2/backend/tests/integration/{test_field_change_apply.py,test_artifact_undo.py}`
- Create: `v2/frontend/src/features/field-changes/{FieldChangeResultCard.tsx,FieldChangeWorkspace.tsx,DeleteConfirmationDialog.tsx}`
- Create: `v2/frontend/tests/e2e/field-change-flow.spec.ts`

1. 测试同字段操作不可拆、跨字段原子组、未选组记为未应用、删除只确认一次，以及明确单字段非删除变更不等待确认直接执行。
2. 测试任一组失败全部回滚；撤销幂等创建新确定性 Task/Run，生成恢复版本并将下游标 stale。
3. 保持与映射相同的对话嵌入、原位放大和返回交互。
4. 建议 commit：`feat(v2): add grouped field changes and versioned undo`。

### Task 10：Developer Run 诊断页

**Files:**
- Create: `v2/backend/toolwithagent_v2/application/diagnostic_service.py`
- Create: `v2/backend/toolwithagent_v2/api/routes/developer.py`
- Create: `v2/backend/tests/integration/{test_developer_diagnostics.py,test_diagnostic_package.py}`
- Create: `v2/frontend/src/features/run-detail/{RunDetailPage.tsx,OverviewTab.tsx,TimelineTab.tsx,CallsTab.tsx,LogsTab.tsx,ArtifactsTab.tsx}`
- Create: `v2/frontend/src/features/run-detail/RunDetailPage.test.tsx`

1. 测试失败节点默认选中、自动重试相邻、未执行原因、调用/日志互链和大内容按需加载。
2. 测试 Developer 全程只读；诊断包默认不含上传原文件，所有凭据脱敏。
3. 概览优先确定性错误与证据，推测显示“可能原因”。
4. 建议 commit：`feat(v2): add read-only run diagnostics`。

### Task 11：Admin 控制面

**Files:**
- Create: `v2/backend/toolwithagent_v2/api/routes/admin.py`
- Create: `v2/backend/toolwithagent_v2/infrastructure/secrets.py`
- Create: `v2/backend/tests/integration/{test_admin_queue.py,test_admin_providers.py,test_admin_users.py}`
- Create: `v2/backend/tests/unit/test_secret_store.py`
- Create: `v2/frontend/src/features/admin/{AdminLayout.tsx,SystemPage.tsx,RunsPage.tsx,ProvidersPage.tsx,UsersPage.tsx,AuditPage.tsx}`
- Create: `v2/frontend/tests/e2e/admin-flow.spec.ts`

1. 测试取消 queued、强停原因与 fence、审计脱敏、密钥只以认证密文落库且不回显、连接测试不创建业务 Task。
2. 测试主密钥缺失/错误时安全失败，key rotation 可重包旧 secret，旧配置 revision 在轮换期间仍可供冻结 Run 使用。
3. 测试角色变更只影响下一请求，不中断 active Run。
4. 不提供调序、服务重启、标准字段/Prompt/Artifact 编辑。
5. 建议 commit：`feat(v2): add audited admin control plane`。

### Task 12：兼容验收、运维文档与发布门禁

**Files:**
- Create: `v2/backend/tests/fixtures/sanitized_acceptance/`
- Create: `v2/backend/tests/contract/test_export_compatibility.py`
- Create: `docs/testing/toolwithagent-v2-acceptance.md`
- Modify: `README.md`
- Modify: `docs/architecture/架构概览.md`
- Modify: `docs/architecture/代码级设计说明.md`
- Modify: `.env.example`
- Modify: `CHANGELOG.md`

1. 固化脱敏样本和规范化输出，比对字段映射、枚举填充、字段调整、威胁复核和导出命名。
2. 跑根仓、V2 后端、前端和 E2E 全套测试。
3. 分别启动 Chainlit 与 V2，人工验证平台导入及产品规格的 18 条验收场景。
4. 记录版本、commit、样本哈希、命令和结果；共享业务差异阻止发布。
5. 建议 commit：`docs(v2): finalize dual-entry acceptance and operations`。

## 13. 第一阶段完成定义

第一阶段只在以下条件同时满足时完成：

- 字段映射切片可在服务重启后继续，Draft、确认和队列状态不丢失。
- 对话默认展示嵌入摘要；放大处理不离开工作台，不丢左侧导航和 Composer。
- Draft 原子应用后产生不可变新 Artifact，并返回原消息流。
- 取消、Worker 丢失、模型迟到和原子校验失败都不发布部分正式结果。
- Developer 能从 Run 定位失败调用、日志和 Artifact 元数据，且凭据始终脱敏。
- 根仓完整 pytest 通过，Chainlit 启动和关键业务行为无回归。
- V2 后端、前端、构建和字段映射 E2E 通过。

Admin 完整控制面、字段变更与全量双入口验收属于后续切片，但数据模型和权限边界不得在第一阶段用临时字段绕过。

## 14. 风险与决策记录

| 风险 | 处理 |
|---|---|
| 把 Chainlit Session 原样持久化 | PersistedSession + 冻结输入 + staging，不序列化 UI Session |
| API 与 Worker 同时写 Run | 状态条件更新、短事务、成功发布单事务 |
| SQLite 锁竞争 | 单 Worker、WAL、busy timeout、事务内不做模型或文件 I/O |
| 用户重跑拿到最新输入 | Run 保存不可变输入快照，重跑复制原快照 |
| 取消后迟到响应污染产物 | 发布前检查状态和取消标记 |
| Draft 被 Agent 当成正式数据 | Draft 独立存储，只有 apply 后 Artifact 可进入 SessionFacts |
| 前端复制业务校验 | 后端返回能力、禁用原因和错误码，前端只做即时提示 |
| 诊断泄露密钥或原始数据 | 写入前统一脱敏、按角色投影、大内容按需加载 |
| V2 改动破坏 Chainlit | 单向依赖门禁、根仓回归、同样本双入口验收 |
| 过早支持分布式执行 | 首版固定单 Worker；多 Worker 需单独 ADR 和数据库选型 |

## 15. 待后续 ADR、但不阻塞首版的事项

- 正式认证/SSO 与数据保留周期。
- 多 Worker 时从 SQLite 迁移到服务型数据库及可靠队列的触发指标。
- 生产 Secret Manager 选型。
- V2 稳定后 Chainlit 的长期保留或下线门槛。
- 枚举手工编辑器与更复杂 Artifact 关系可视化。

这些事项不得以“未来会解决”为由削弱首版的权限、原子性、血缘、脱敏和可恢复性。

## 16. 历史能力继承矩阵与 Issue 门禁

V2 首版按 `application/adapters/composition.py::create_default_adapters` 的生产组合继承全部 13 类 Step。V2 只通过 Application 公共契约调用这些能力，不在 API、Worker 或 React 中复制业务实现。表中的根仓测试是继承基线；对应 V2 contract/E2E 是 #272 放行所需的新增证据。

| 能力 / Step | Application 事实源与公共缝 | V2 Issue | 根仓契约 / 回归基线 | V2 contract / E2E 门禁 | 处置 |
|---|---|---|---|---|---|
| `log_parse` | `LogParseAdapter`、日志类型检测与规则生成 | #275 | `test_application_log_parsing_architecture.py`、`test_log_type_full_enumeration.py`、`test_log_parser_marker_fix.py` | 上传真实脱敏日志，验证类型、解析规则、稳定错误及失败不发布 Artifact | 首版继承；#258/#259 先修 |
| `log_knowledge_submit` | `LogKnowledgeSubmitAdapter`、ADR-0012 store/repository | #275、#271 | `test_log_knowledge_submission.py`、`test_log_knowledge_store_contract.py`、`test_log_knowledge_repository.py` | 申请资格、幂等提交、终态，以及 Admin 审核/替代/回放/安全展示 | 首版继承；审核只进 #271 |
| `field_mapping` | `FieldMappingAdapter`、batch/input/conflict policy、event classifier | #266、#267 | `test_application_field_mapping_architecture.py`、`test_event_classify.py`、`test_standard_field_entity_validation.py`、`test_syslog_json_body_key_regression.py` | 上传→映射→事件名称标注→Draft→冲突处理→原子应用→新 Artifact | 首版继承并增强编辑体验 |
| `enum_extract` | `EnumExtractAdapter`、枚举提取工具与 Prompt | #276 | `test_application_enum_architecture.py`、`test_single_intent_execution.py` | 指定目标字段提取；空结果稳定失败；成功产物可被下一轮引用 | 首版继承 |
| `threat_mapping` | `ThreatMappingAdapter`、threat chain policy | #276 | `test_application_threat_architecture.py`、`test_threat_chain.py`、`test_threat_chain_policy.py` | 来源覆盖、一次复核、映射产物与证据；#277 修复后纳入回归 | 首版继承；#277 阻塞 #276 |
| `fill` | `FillAdapter`、枚举填充契约 | #276 | `test_single_intent_execution.py`、`test_threat_chain.py` | 基于冻结来源 Artifact 填充；冲突或失败不覆盖旧成功版本 | 首版继承 |
| `remove_mapping` | `RemoveMappingAdapter` | #276 | `test_application_config_architecture.py`、`test_single_intent_execution.py` | 取消指定映射、保留血缘并生成新版本 | 首版继承 |
| `export` | `ExportAdapter`、现有下载命名与编码约定 | #276、#272 | `test_candidate_table_export.py`、`test_plan_renderer.py` | JSON/Base64、中文编码、文件名和平台导入与 Chainlit 一致 | 首版继承；发布硬门禁 |
| `add_fields` | `FieldSkillAdapter` + add-fields skill | #268 | `test_application_field_skill_architecture.py`、`test_field_skill_ops.py` | 变更组预览、应用、版本化撤销 | 首版继承 |
| `delete_fields` | `FieldSkillAdapter` + delete-fields skill | #268 | `test_field_skill_ops.py`、`test_rule_targeting.py` | 保留字段校验、一次删除确认、原子回滚 | 首版继承 |
| `merge_fields` | `FieldSkillAdapter` + merge-fields skill | #268 | `test_field_skill_extensions.py`、`test_rule_targeting.py` | 多字段关联操作不可拆分，失败不发布 | 首版继承 |
| `decode_fields` | `FieldSkillAdapter` + base64-decode-fields skill | #268 | `test_field_skill_extensions.py`、`test_rule_targeting.py` | 多目标选择、预览、原子应用与回滚 | 首版继承 |
| `regex_extract` | `FieldSkillAdapter` + regex-extract skill | #268 | `test_field_skill_extensions.py`、`test_field_skill_reference_policy.py` | 来源引用、生成/执行失败分层和产物版本 | 首版继承 |
| proposal / confirm / cancel | `PlanExecutor`、类型化 checkpoint、确认 token | #265、#267、#268 | `test_plan_executor.py`、`test_application_request_runtime.py`、`test_execution_recovery.py` | 刷新/重启后确认续跑；旧 revision/token 拒绝；取消阻止迟到发布 | 首版横切契约 |
| 可引用跨轮产物 | Session artifact catalog 与来源绑定 | #265、#276 | `test_referenceable_session_artifacts.py` | 只引用当前主数据的最近兼容成功 Artifact；替换/清空主数据后失效 | 首版横切契约 |
| 有界自恢复 | `RecoveryOrchestrator`、既有计划与 execution ledger | #265、#276 | `test_execution_recovery.py` | 仅允许瞬时重试、结构修正、系统推导参数重推导；按计划计数预算，不改用户点名参数；覆盖手工产物时升级追问并留审计 | 首版横切契约 |
| 最近执行摘要 | `recent_execution` 安全目录 | #265、#276 | `test_recent_execution_summary.py` | 仅保存当前与上一计划的步骤状态、错误类别、产物目录和计数；主数据替换时失效 | 首版横切契约 |
| `SessionFacts` | `contracts/session_facts.py` 的安全投影 | #264、#265 | `test_application_request_runtime.py`、`test_referenceable_session_artifacts.py` | 持久化事实可重建；Planner 只收到投影，不收到 UI Session | 首版横切契约 |
| 事件名称标注 | event classifier、字段映射产物、21 值分类表与事件级别确定性绑定 | #266 | `test_event_classify.py`、`test_application_field_mapping_architecture.py`、`test_application_session_projection.py`、`test_rule_targeting.py` | 每条子规则仅写合法分类名，事件级别确定性联动；判定失败宁缺勿错并标记待人工确认 | 首版继承 |
| 进度与 Run 事件 | Application progress sink、Run/conversation outbox | #265、#269 | `test_progress_reporting.py`、`test_plan_renderer.py` | 事件带 Run/Step/Artifact 关联，SSE 断线按 sequence 补取 | 首版横切契约 |
| Provider 管理 | Provider registry 与冻结配置 revision | #271、#272 | `test_provider_registry.py` | Provider 切换只影响新 Run，密钥不回显，三条调用链一致 | 首版发布契约 |
| 导出兼容 | `ExportAdapter`、下载命名与编码约定 | #276、#272 | `test_single_intent_execution.py`、`test_application_config_architecture.py`、`test_execution_adapters.py`、`test_plan_renderer.py` | JSON/Base64、中文编码、根类型键顺序、命名和目标平台导入在双入口一致 | 首版发布契约 |

### 16.1 Issue 实施顺序

1. #262 固化本矩阵、PRD 索引和门禁；#227/#221/#80 关闭，#204/#205 的有效规格迁入 #271 后关闭。
2. #258、#259 修复共享日志解析缺陷；两项根仓回归通过前，#275 不得开始业务接入。
3. #264 提供独立入口，#265 提供持久化 Run、Worker、checkpoint、Artifact 和 fencing。
4. #263 在首个规格驱动的 UI 切片前完成人工设计基线验收；可与 #264/#265 的非 UI 基础设施并行。
5. #60 在首个真实 V2 业务切片 #275 前完成剩余 Chainlit 黄金基线；它不阻塞 #264/#265。
6. #275 交付日志解析与知识申请；#266/#267 交付字段映射与 Draft；#277 修复后 #276 才可交付枚举、威胁、填充、取消映射、跨轮产物与导出；#268 交付五类字段调整。
7. #269 完成用户 Task/Run/Artifact 抽屉，#270 完成 Developer 只读诊断，#271 完成 Provider、权限、队列和日志知识审核的唯一 Admin；#271 复用 ADR-0012 数据，不建设第二套日志知识审核台。
8. #272 对矩阵每一行收集根仓 contract、V2 contract/E2E 和同样本双入口证据；任一首版行缺失、共享业务差异未解释或平台导入失败均阻止发布。

### 16.2 范围边界

- #108 的多字段跨轮增强、#189 的自动枚举增强、#206/#207 的知识维护增强尚未进入稳定 Application 能力，不得暗中塞入 V2 首版。
- 这些增强后续进入主线时必须新增或更新对应矩阵行，并由 #272 的同类门禁覆盖。
- Chainlit 与 V2 旁路并行，不迁移、不读取、不双写旧会话；共享部分仅限 Application 业务源码和只读标准字段表。
