# Issue #275 V2 日志解析与知识申请实施计划

> Follow AGENTS.md, issue-workflow.md, CONTEXT.md, ADR-0009/0013 and #275. Work only in this worktree.

**Goal:** 从持久会话中的日志文件创建可恢复的日志类型提取 Run，发布完整成功的分类 Artifact，并通过显式按钮提交日志知识申请。

**Architecture:** 复用 V2 SQLite、Blob、Run lease/fence 与 outbox。Run 冻结文件身份、可选分类特征字段和源 Artifact；Worker 通过 Application 公共执行入口工作，只有完整成功且 fence 有效时发布。普通用户 REST 只返回安全摘要。

## 1. 完整成功门禁

- 先为非空 PARTIAL 分类添加红测试：步骤失败，不回填样本，不替换旧分类或申请快照。
- 修正 application/adapters/log_parse.py：仅 SUCCESS 提交分类；FAILED、PARTIAL 和未知状态返回稳定失败。生产 Python 变更后按 SOP 重生成源码分析快照。
- 运行定向及根仓全量 pytest。

## 2. 冻结命令与 bridge

- 增加 POST /api/v2/conversations/{id}/log-parse，输入 {file_id, feature_field?}。验证文件属于当前用户会话且校验成功；冻结 file_id、sha256、storage_key、media_type、feature_field。重跑沿用原快照。
- Worker 校验 Blob/哈希，构建最小 PersistedSession 和 raw_log_lines，经 run_deterministic_plan、LogParseStep、默认 Adapter 组合执行。不复制 Pipeline，不读取 Chainlit 会话。
- 文本/JSON/NDJSON、CSV 和 Excel 日志输入保持 Application 解码语义；Excel 数据表须有“原始日志”列。异常转稳定错误，不终止 Worker。

## 3. 发布与投影

- 仅完整 SUCCESS 经现有 staging/rename/SQLite 事务发布不可变 log_classification Artifact；同事务记录 Run 成功、消息和 outbox。完整分类、coverage、规则与真实样例血缘存于受保护 Blob，REST/SSE 不包含原始日志或服务器路径。
- FAILED/PARTIAL 只存稳定原因，保留旧成功 Artifact。取消、强停、旧 epoch 结果受现有 fence 阻断。重启后从 SQLite/Blob 恢复相同结果。
- 消息流显示日志类型、数量、coverage 和规则摘要；抽屉只显示安全执行摘要。

## 4. 显式知识申请

- 只为有资格、仍属于当前主数据的已发布分类 Artifact 开放 POST /api/v2/artifacts/{id}/submit-log-knowledge。后端从冻结分类和同一文件重建快照，创建 LogKnowledgeSubmitStep 的确定性 Run。
- 复用既有 Adapter/Repository，持久化 created、pending_duplicate、already_approved、stale、error 和申请编号。重复点击受控；过期/仓储失败不损坏分类结果。审核与替代留给 #271。
- 防跨用户读写，样例原文不进入消息/SSE/普通用户详情。

## 5. UI 与验证

- 文件行提供“提取日志类型”和可选分类特征字段；结果卡片展示安全摘要、coverage、规则及有资格时的知识申请按钮。运行、失败、重试、取消和申请终态沿用 Run API 与事件刷新。
- V2 集成测试使用假 Application/Repository，不调用真实 Provider；React 测试覆盖成功、失败、资格、提交、恢复及敏感信息。跑根仓全量 pytest、V2 全量 pytest、前端 test/lint/build，并做独立 Reviewer 复核。
- #60 Chainlit 黄金基线完成前不合并 PR；用户已确认先开发并做自动验证。

**Assumptions:** 本切片从文件行显式发起解析，Composer 文本仍按 #264 保存；通用自然语言业务规划由后续切片承接。
