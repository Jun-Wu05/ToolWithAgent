# Changelog

本文件记录 ToolWithAgent 项目的所有重要变更，遵循 [Keep a Changelog](https://keepachangelog.com/) 格式，版本号采用 Bug 修复递增规则 (`v0.0.x`)。

## [Unreleased]

### Added
- 统一 Planner 架构（ADR-0005）：独立 PlannerAgent + 类型化 PlanDecision/StepSpec + PlanExecutor 依赖账本，按钮入口复用同一执行器（#45 #53 #58）
- 七类产物统一渲染：字段映射表、威胁映射表、枚举列表、日志分类详情与规则动作、配置下载一次汇总展示（#63 #68）
- 字段映射成功后自动回填配置并产出 Base64 下载（#51）；映射结果落表展示（#49）
- Planner 超时诊断：结构化 MODEL_CALL_TIMEOUT 日志与失败关闭追问（#71）
- 复合计划真实链路回归：三步复合依次传递账本并产出唯一导出（#39 #57）
- 决策互斥、导出来源约束与 guidance 路径回归（#42 #56）；单意图失败关闭与依赖校准回归（#36–#40 #55）；#50/#51 回归测试可追溯性标注（#54）
- 对话记忆机制：`web/history_store.py` 自定义轻量记忆（append_history/format_history_for_prompt），SessionState 加 conversation_history 字段，build_llm_input 拼 最近5轮对话历史
- 路由意图消歧：`detect_intent()` 带消歧规则（威胁vs映射冲突、「填充」动作识别优先于枚举提取、ambiguous→RouterAgent）
- Excel→映射→枚举填充连续操作：`apply_enum_fill_to_sub_rules()` 桥接 sub_rules↔normalize[]，handle_enum_fill_flow 数据源优先级（mapped_sub_rules>raw_base64>提示上传），不再要求重传 Base64
- LLM决策→web 动作桥接：扩展 `[SESSION_ACTION:]` 标记集（activate_enum_fill/activate_threat_fill），RouterAgent 决策可触发填充流程
- Agent 自主性增强：Team 加 `enable_agentic_state` + `add_session_state_to_context`，FieldMappingAgent tool_call_limit 1→3
- 快路径/慢路径分流（借鉴 ClaudeCode）：detect_intent 状态前置检查（mapping 无数据→general），general 意图跳过 embedding 检索 + JSON 解析 + 重试
- session_summary 增强：全状态感知（文件/映射/子规则/枚举/威胁/日志解析）
- 并发安全：per-session asyncio.Lock（message_router.py）
- 字段映射导出新增「检索候选top3」列（`web/action_callbacks.py`），区分检索问题 vs LLM 误判
- 检索链路 DEBUG 级诊断日志（`field_retriever.py` RETRIEVE_DEBUG_TRACE），逐字段打印候选排名轨迹
- 中文同义词桥接：`field_synonyms.json` 升级为 264 条 `{en, zh}` 结构，query 文本拼接中文同义词提升跨语言召回
- tag 规则外置：`config/tag_rules.json`（token 级匹配，修正 code/severity 误归类，新增 threat/http tag）
- 精确匹配 compact key：`_compact_field_name()` 消除 file_name/filename 命名鸿沟
- 复合 key 回退查询：`_expand_field_name`/`_collect_zh_synonyms` 修复 133 个带下划线死条目
- Layer1 精确匹配扩展中文索引：系统属性名 + synonyms.zh 反向索引
- 标准字段表扩充至 625 条（新增设备名称/主机名称/主机ID/事件名称/事件级别）
- Prompt 迁移：将 `log_parser_pipeline.py` 中的 LLM prompt 从字符串常量迁移到独立 `.md` 文件
- 枚举提取 Prompt 输出格式严格约束：禁止前导说明文字、markdown 代码块、多行输出
- 自平衡括号 JSON 提取器，替代脆弱的 `\{[^}]+\}` 正则

### Changed
- 字段映射下载契约显式化：`filled_config` 单载荷改为 `download_kind/download_content`，Excel 日志映射导出 mapped_sub_rules、真实配置导出 mapped_config、无回填目标不附下载；恢复日志分类历史渲染（详情/样本/完整 JSON）与规则导出动作（#75）
- 删除死代码 `build_llm_input`（曾把旧枚举结果注入威胁输入）与可读性清理（#44 #59）
- 可读性清理（-230行）：双重访问清理（getattr or get → .get()，hasattr/else 5行 → [k]=v），提取批处理 helper（batch_mapping_helper.py），提取数据源 helper（_resolve_fill_data_source），魔法字符串集中（EXCLUDED_FIELD_INDICES）
- 移除 BM25 混合检索，回归纯向量检索（中文同义词接入后纯向量召回充分，BM25 净负面）
- 删除 ABBR_EXPANSIONS 硬编码（69条），合并进外置 `field_synonyms.json`
- 死代码清理（-1006行）：删除 `threat_type_tool.py`、`session_manager.py`、`team_web.py` + agent.py 死函数
- `requirements.txt` 移除 `rank_bm25` 依赖
- refusal-retry 指令放宽：从「禁止输出任何索取性文字」改为「允许说明具体缺什么字段及用途」
- process_team_response 加 intent 参数，按意图分流处理（general 跳过 JSON 解析）
- 枚举提取优先 raw_log_lines（Excel 原始日志列干净文本），回退 original_log
- Prompt 改写为 XML 格式，移除硬编码测试数据
- Pipeline 分类输出 schema 清理：移除废弃字段

### Fixed
- 字段映射来源排除 Excel 列头：有真实日志字段时 `available_fields` 只含日志字段与子规则字段，`decoded_fields` 仅作配置场景回退；数据表 Excel 缺"原始日志"列在上传时拒绝（#78 #81）
- Planner 两步复合修复："提取枚举值并做威胁类型映射"生成 `enum_extract → threat_mapping` 依赖链，威胁映射使用内置分类表、不依赖枚举映射表（#79 #82）
- 枚举提取从原始日志行取值，不再依赖已删除的旧结果通道（#70）
- 上传 Base64 配置可直接枚举填充，不再错误要求先生成子规则（#67 #69）
- RFC5424 头+KV body 日志误识别为 JSON 时确定性纠正（#22 #61）
- 多子规则回写正确性锁定，映射/更新计数区分（#23 #62）
- 映射输入排除系统元字段 original_log/日志类型（#50）
- 字段映射漏字段补查+兜底未匹配，不再整步作废（#48）
- 字段映射超时批次一次性拆分重试
- list 根配置（多规则数组）填充支持
- 填充动作识别优先于枚举提取：「枚举值填充进子规则」不再被「枚举值」抢到提取
- enum_excel_path 被数据表格覆盖：_handle_excel_data_table 不再错误覆盖枚举映射表路径
- refusal 误判：无数据时 LLM 引导上传不再被误判为拒绝响应（加 has_decoded_data 条件）
- general 意图跑 embedding 检索：「你好」不再触发全量字段语义检索
- `_generate_feature_identifier` KV 正则 Group1 利用 `header_end_marker` 跳过 syslog 头部
- `fill_sample_logs` 自动从 `classification.get("feature_identifier")` 提取正则
- `header_regex` 特征提取在 JSON 格式下也能优先执行
- `_aggregate_by_log_type` 支持非 JSON 格式 + `value_count=0` 时继续调 LLM
- `log_parser_pipeline` timeout 90s + JSON 子串回退修复
- `log_classify_feature.md` Prompt 双捕获组修复
- `_render_log_parser_result` 对齐新 pipeline 输出字段
- `rule_generator.py`、`log_sample_filler.py`、`log_classifier.py` 废弃字段残留引用清理

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