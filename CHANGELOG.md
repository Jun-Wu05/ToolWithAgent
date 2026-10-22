# Changelog

- feat(v2): 字段变更分组预览、一次删除确认、确定性原子应用与版本化撤销（#268）；复用共享 Skill，支持上传配置根结构与递归下游过期传播。

本文件记录 ToolWithAgent 项目的所有重要变更，遵循 [Keep a Changelog](https://keepachangelog.com/) 格式，版本号采用 Bug 修复递增规则 (`v0.0.x`)。

## [Unreleased]

> 注:2026-09-07(#180 时代)至 2026-09 下旬(#356 之前)的条目未回溯补记;以下自 #356 起恢复连续记录。

### Added
- V2 视觉公共原语（#308）：统一状态圆点与文字、三态任务提示、单实例上下文抽屉和折叠工具调用块；抽屉支持键盘标签切换、Esc 关闭与焦点返回，保留标签页内输入及既有权限和迟到响应守卫。
- V2 视觉 Token 基线（#307）：按定稿 OKLCH 规格统一明暗颜色、两档边线、圆角和工具类，移除组件硬编码颜色；首次绘制前恢复主题，提供只读规格自检命令。
- V2 后处理与跨轮产物（#276）：复用枚举提取、威胁类型映射、填充、取消值映射和导出；主数据与枚举附件分离，冻结来源并原子发布，真实方案确认不重新规划，恢复耗尽保存成功前缀与预算；确定性清空停用输入并保留历史，保持配置根结构与下载命名。V2 功能先合入 `codex/v2-development`，持续吸收 master，完整交付验收后再决定默认入口。
- V2 字段映射草稿编辑（#267）：按子规则自动保存人工选择，确认占用替换与精确路径联动，以 revision 阻止旧版本覆盖；应用通过确定性 Task/Run 原子发布新 Artifact，失败保留草稿与旧结果，发送新消息前明确应用、丢弃或返回编辑。
- tests/factories.py 测试会话构造工厂基座:make_session_state 唯一入口 + make_recording_session(写入顺序契约)+ 两个场景预设,40+ 测试文件统一收口(#357 #371)
- 威胁类型链路自动化（#173，ADR-0010）：字段映射判出威胁子规则后执行后确定性续跑 枚举提取→威胁映射→加字段→填充 四步；来源字段 X=候选检索相似度最高且覆盖全部威胁子规则（会话覆盖优先），判不出降级固定值「其他」；值映射确定性全覆盖兜底；「威胁类型」成为第 4 个映射目标黑名单字段；威胁映射产物填充目标固定为「威胁类型」（修复跨轮血缘漂移）；planner.md 新增四步链路指令与换来源话术（复合指令从 2 步变 4 步，breaking）；威胁类型链路六阶段 threat_chain 日志
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
- fix(enum-fill): 目标字段逐字段严格校验+全部已存在幂等成功+生效 Sheet 清单(#402)——#400 守卫从"任一命中放行"收紧为逐字段校验,任一映射表目标字段在配置中无同名条目时稳定失败并列出缺失字段,不再部分静默丢弃;全部已存在时幂等成功(StepResult 新增 idempotent_no_change 标记,执行层 no_effect 降级豁免),不再误报失败;填充消息逐字段给出新增/已存在计数;枚举预览消息展示生效 Sheet 清单,累积残留可见
- fix(upload): 解析规则上传不再清空枚举映射附件(#400,#101 语义收窄)——clear_decoded_data 保留 enum_* 附件状态(映射表/预览/填充账本),主数据本体与其余派生状态照旧全清;显式重置(清空数据/切换文件)经 clear_session_data 全清含附件;EnumFillAdapter 新增目标字段零匹配守卫(Sheet 名与配置字段不一致时稳定失败,不再静默写错条目或静默 no_effect);行为变化:换主数据后既有枚举映射表沿用生效,需重置走显式清空或重传同名 Sheet;同消息"解析规则+枚举表"任一顺序上传后可直接填充,不再触发 missing_enum_mapping_table 澄清循环
- feat(threat): 威胁类型填充写 value 占位(#398)——apply_fill_to_config 新增可选 value_placeholder 参数(缺省保持只写 mappings 旧行为);threat_fill 按规则计算占位:映射值唯一→该值、多值→「其他」,单值/多值/降级三类路径恒有占位,与事件字段 value 形态(#393/#395)对齐
- feat(event): 非威胁事件绑定操作类型字段(#395)——EVENT_NAME_OPERATION_ENUM_BINDING 固化提示词已定义枚举的 7 个非威胁类(登录/审计/会话/进程/用户操作/资源监控/邮件操作);判定输出契约新增 operation_type(类内白名单校验,非法/缺失降级「其他」,未定义枚举的类留空);apply 对绑定类写第三条 normalize 条目(恒等映射+value+按样本数复制 result)并同步 addFields;threat 分类的 classify_sub_rule_events 返回值扩为三元组;ENUM_AUTO_MAPPING_EXCLUSIONS 注释更新
- feat(threat): 威胁映射终态失败降级写「其他」(#394,部分调整 #277)——模型调用异常/空结果/覆盖校验拒绝三个分支从安全失败改为降级成功:全部映射行落「其他」、步骤消息与 [THREAT_MAPPING] 日志留痕、链路摘要追加"N 步结果已降级为「其他」";纯数字代码来源与标准枚举不可用两类非模型失败保留失败;威胁事件导出恒有威胁类型映射行
- fix(export): 事件名称/事件级别 normalize 条目补齐 mappings 与默认值——事件名称恒等 EQUAL 映射+value;事件级别按整型码表(信息0/提醒1/警告2/严重3/紧急4)写码值、mappings 记录显示值→码值;字段映射链按子规则既有 result 长度推导样本数复制 result;skill 链 metadata 拷贝键扩展 mappings/value(威胁类型路径不变);导出平台不再解析出空值(#392)
- 仓库遗留数据清理:config 死数据 threat_type_config.json(ThreatAgent 时代加载入口已随死代码清理删除,现行威胁标准枚举单一事实源为 config/标准字段.txt)与 空规则.txt(rule_generator 模板出处样本)删除;evaluation/planner_eval 7 份历史 results_*.json 基线删除(cases.json 与 run_eval.py 保留);docs/plans 28 份已完结实施计划归档至 docs/plans/archive/(2026-09-21 V2 技术实施计划原地保留,V2 线在用);README 目录树与 rule_generator/templates.py 注释同步
- 批次十二结构收口:_do_classify_log_features(约 282 行路由器)拆显式字段/体键覆盖率/两段 Step 2a 四阶段函数,只搬移不合并、KV/JSON 版刻意差异保留;render_execution_report 拆产物元素收集与字段映射下载发送两函数,五路 artifact_type 分派表驱动、门控语义各自持有;新增 7 条路由分支钉桩(#387)
- fix(planner): 威胁来源事实矛盾拒绝——模型声明 threat_source_not_found 但字段在 threat_source_fields 中时改写为 planner_source_fact_conflict 稳定拒绝,不替模型生成执行计划;planner.md 换链路来源契约重写(#385)
- 批次十一结构收口:kv_extractor 复制阶梯收口与清洗常量内联、log_classifier 分隔符回退对称化、field_mapping._execute_field_mapping 拆 _MappingPreparation/_StagedOutputs 四阶段;「钉桩先行+边界切开」方法论首次系统使用(#383)
- 会话类型化收官(三步走):SessionState dict 兼容层退役、生产垫片 _session_get/_session_set 删除(96 处调用点属性直读直写)、ExecutionContext.session 等约 20 处签名收窄 SessionState、file_input/request_runtime/threat_chain 三处 dict 兜底分支拆除、build_batch_llm_input 假会话参数直传 original_log_sample(#366 #368 #374 #376)
- 全部测试迁移 make_session_state 工厂基座(执行链路 5 文件 + 其余 23 文件两批完成)(#370 #372)
- 安全区死代码清理:logs_enum_tool 整模块、base64_tool(#161 挂起的独立审计执行完毕)、agent/core/agent.py 迁移残留、enum_extract_tool 四死函数、config 死数据(threat_nomal.txt/knowledge_base//对象.xlsx)删除;message_router 幻影延迟导入拆除;字段映射与导出的数据源守卫双份收口 require_rule_source_fields(#378)
- 重构批次:ConfigRef 读取双源收口与循环导入修复(#354 #355)、会话垫片 7 份同型拷贝收口(#351)、LLM 响应解析收口共享 parser(#345)、FormatContext 收紧(#347)、plan_renderer kinds 收紧(#348)、FieldMappingBatchRunner.run() 拆阶段(#358)、field_retriever 候选检索主函数拆解(#359)
- 候选检索新增结构化出口（#180）：`batch_retrieve_candidates_table` 返回 field → [(标准名, 得分, 英文名, by_stripped变体)]，`batch_retrieve_candidates` 改由该表渲染 markdown（字节不变，表征测试零改写保持绿）；一对一冲突裁决改消费结构化表并删除 `_parse_candidate_scores` 正则反解析（web 侧第二套正则已随 #178 删除）；批处理 prompt 仍在注入边界渲染 markdown，生产输入字节不变
- Application 运行时提取完成：SessionFacts 投影、PlanExecutor、全部业务 Adapter、FieldMappingBatchRunner、文件输入、Prompt 组合、模型/历史/字段运行时与 Web 请求入口统一落位；Web 收缩为 Chainlit 输入、生命周期、进度和渲染，并新增 ADR-0009、静态依赖门禁与最终源码分析快照（#130 #132–#144）
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

### Removed
- 安全区死代码清理包（#378）：logs_enum_tool.py（零外部调用的 2 个 @tool）、base64_tool.py 及其 characterization 测试（#161 审计四重零生产导入实证后授权删除）、agent/core/agent.py 迁移残留、enum_extract_tool.py 四个零引用格式化函数、application/history.py clear_history、web/file_handlers.py enum_excel_path 墓碑读取、config/{threat_nomal.txt, knowledge_base/, 对象.xlsx} 死数据
- 死代码清理包（#178）：删除零消费的 `agent/tools/pipeline/models.py` TypedDict 层；`agent/core/tracing.py` 的 `sync_wrapper`/`to_dict`/`TraceContext.set/reset`（保留 span 与 trace_request）；零调用的 `agent/shared/threat_fill.py` 遗留副本（生产链路在 `application/adapters/threat_fill.py`）；`generate_rules` 的 `mode="both"` 死分支与 `file_name` 返回键、`generate_sub_rule` 的 `is_pure_json` 死参、零消费导出 `extract_sub_rule_mapping_info`/`apply_enum_fill_to_sub_rules`；`web/action_callbacks.py` 5 个无按钮构造点的死 callback 及仅被死代码读写的 `batch_mapping_results` 会话字段

### Fixed
- field_retriever Layer 1.5「去前缀变体精确匹配」因 str 字段名对 int 键 dict 做成员检查从未生效;修复后嵌套字段(如 data.severity)变体精确命中恢复置顶 1.00 候选(#363)
- 正则生成重试对「无正则失败」构造反馈导致崩溃(#352)
- 日志保留策略未按设计生效（#176）：`agent/logs` 无限累积（清理只在应用启动触发，pytest/子进程/CLI 等非应用进程不经过）且稳态每类实为 3 份而非 2；清理改挂 `setup_logger` 首次创建共享日志文件分支（每进程至多一次，任何产生日志的进程都会触发），`cleanup_old_logs` 改为每前缀总数 = keep_count（活动文件计入额度且永不删除），稳态回到「当前 + 上一次」2 份/类
- 导出字段携带错误对象（#177）：事件固定字段 entity 由「日志」改为目录规定的「事件」（目标平台不再显示 event_name日志）；标准字段目录成为名称/对象 SSOT——apply 写入与 validator 校验均按目录确定性解析（英文字段名/前后空白等变体规范化为目录规范名，目录外名称降级未匹配，对象取目录对象列首个，多值逗号分隔与 对象.xlsx 历史语义一致）；退役 对象.xlsx 回填与 object_map_loader 接缝（加载失败静默空表、未知名称默认「事件」两缺陷一并消除）；上传配置既有非法组合只诊断不改写（find_non_catalog_field_entities 报告来源与数量）
- 纯 KV 日志分类在 format_info 为空（解析为 None）时抛 UnboundLocalError（#179）：`_classify_kv_features` 的 `body_logs` 改为无条件初始化并回退默认分隔符；塌缩永不可达的防御 try/except；删除 `_classify_json_features` 从未使用的 `format_info` 死参与 4 个传 None 调用点
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
