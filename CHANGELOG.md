# Changelog

本文件记录 ToolWithAgent 项目的所有重要变更，遵循 [Keep a Changelog](https://keepachangelog.com/) 格式，版本号采用 Bug 修复递增规则 (`v0.0.x`)。

## [Unreleased]

### Added
- Prompt 迁移：将 `log_parser_pipeline.py` 中的 LLM prompt 从字符串常量迁移到独立 `.md` 文件（`agent/prompts/log_format_identify.md`、`agent/prompts/log_classify_feature.md`）
- 枚举提取 Prompt 输出格式严格约束：禁止前导说明文字、markdown 代码块、多行输出
- 枚举提取 LLM 输出格式遵从度检测日志（`[ENUM_EXTRACT] LLM 未遵守纯 JSON 输出格式`）
- 自平衡括号 JSON 提取器，替代脆弱的 `\{[^}]+\}` 正则

### Changed
- Prompt 改写为 XML 格式，移除硬编码测试数据
- 移除分类表中废弃的 `severity`/`attack_type` 列

### Fixed
- `header_regex` 特征提取在 JSON 格式下也能优先执行
- `_aggregate_by_log_type` 支持非 JSON 格式（semicolon/kv/comma/space/cef）+ `value_count=0` 时继续调 LLM 而非早期失败
- 传递 `format_info` 到 `_aggregate_by_log_type` 支持 `header_regex` 提取
- `log_parser_pipeline` timeout 90s + JSON 子串回退修复

---

## [v0.0.11] — 2026-05-13

### Added
- LogParserAgent：日志格式识别 + 特征分类 + 向量知识库集成
- 结构化指纹向量知识库 — `generate_structured_fingerprint` + Pipeline 集成存储
- LogParserAgent 路由：`router.md` + 关键词预筛 + 意图映射

### Changed
- 精简重构 Pipeline，移除 Agent 依赖
- Pipeline 语法修复 + `_do_*` 纯函数重构

### Fixed
- `SessionState` 缺少 `raw_log_lines` 字段导致数据表格路径崩溃
- `_is_enum_mapping_excel()` 列头检测，防止数据表格被误判为枚举映射表
- LogParserAgent ReadTimeout — 日志解析路由仅送原始日志列，避免全量 Excel 数据超时
- Excel 非枚举映射表上传后数据未填入 `user_session`，导致 LogParserAgent 等下游不可用
- 日志解析路由的 NameError 和 Excel 提示优化

---

## [v0.0.10] — 2026-05-12

### Changed
- 重构 `pending_base64` → `raw_base64`，枚举填充触发移至 `handle_user_message` 路由

### Fixed
- LLM 推断枚举字段名替代脆弱的正则方式
- 增强文件上传成功消息，显示日志行数
- 移除误导性的"正在进行标准字段映射处理"上传消息
- `SessionState` 缺少 `raw_base64` 字段
- 已有枚举 Excel 时"枚举值填充"误入提取流程，增加上下文感知路由
- `enum_field_tool` 中 Excel `orgValue=0` 的行被 falsy 检查丢弃
- 枚举分流优先级 + 纯文本上传 `original_log` 兜底

---

## [v0.0.9] — 2026-05-11

### Added
- BM25 混合检索 + 基于规则的字段标签（CACHE v1→v2）

### Fixed
- ThreatAgent `output_schema` 解析 — 兼容 `{items: [...]}` 格式解包
- ThreatAgent `markdown=False` + 删除矛盾指令；`field_retriever` 删除 `_bm25_merged` 死变量

---

## [v0.0.8] — 2026-05-09

### Added
- 双 Provider 支持 + 字段映射优化（v2 撤销 0.60 硬阈值）

### Changed
- P2 分批+并行优化：`BATCH_SIZE=25`，`asyncio.gather` 并行分批（semaphore 2-3 路）
- Agent 架构精简 — 数据文件迁移 + 死代码清理

### Fixed
- 分批映射用户反馈 3 项修复

---

## [v0.0.7] — 2026-05-08

### Changed
- 拆分 `chainlit_app.py` 文件上传逻辑到 `file_handler.py`

---

## [v0.0.6] — 2026-05-07

### Added
- ThreatAgent `output_schema` 杜绝非规范格式输出
- `response_handler` 兼容 Pydantic 对象
- P2 优化：清空数据快捷路径 + 欢迎提示 + 字段 >50 自动分批 + 拒绝检测修复 + `top_k=3`

### Changed
- FieldMappingAgent 超时优化 — P0/P1 全部完成

### Fixed
- 补全未匹配输出格式示例，强化联动约束防止分裂输出
- `SessionState` 添加 `pop()` 方法，修复威胁填充 `pending_base64` 取值报错
- `llm_client` `len()` 兼容 `output_schema` 返回的 Pydantic 对象
- 威胁类型去重 + `pending_base64` 自动消费，避免重复上传

---

## [v0.0.5] — 2026-05-06

### Added
- Agent 自决清空机制 + Base64 预判检测 + 用户输入日志
- `field_retriever` 添加精确名称匹配回退（camelCase 规范化）

### Fixed
- 三个测试问题修复 + Embedding API 增强
- Base64 误判修复 — Try-Decode+JSON 验证替换 `_looks_like_base64` 启发式
- `top_k` 3→5 扩展语义检索候选数，解决 `destAddress`/`srcAddress` 等字段匹配候选不足问题

### Changed
- 从 Git 追踪中移除 `tmp/`、`tests/`、`archive/docs/context_summary` 目录

---

## [v0.0.1] — 2026-04-XX

### Added
- 初始项目基础：Base64 编解码、标准字段映射、威胁类型标准化、枚举字段批量处理
- 桌面 GUI 应用（已归档至 `reference/gui/`）
- Chainlit Web 交互界面
- Agent 系统：Team 调用、意图路由、会话管理