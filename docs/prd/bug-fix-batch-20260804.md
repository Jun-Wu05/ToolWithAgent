# PRD：13 个累积 bug 的验证性修复

## 问题陈述

作为日志解析规则生成工具的使用者与维护者，我发现系统在过去三天的快速迭代中累积了 13 个 bug，涵盖 KV 字段提取错位、真实样例截断、界面渲染截断、快路径误路由、字段来源错误、历史消息截断、Pydantic 序列化重复、SessionState 契约缺失、枚举提取 LLM 调用方式不当、以及复合意图分解功能未落地等问题。这些问题导致核心流程（上传日志→字段映射→枚举提取→威胁映射→填充→导出）在多个环节出错或崩溃。

stash 分支 `stash/wip-3day-changes`（commit `491aa0b`）保留了这三天的全部改动作为参考，但改动交织严重、未逐个验证，可能含互相影响。需要在稳定的 master 基线（`0e61757`，21 测试通过）上逐个验证性修复，每个修复独立可追溯。

## 解决方案

按风险递增分 5 个批次，逐批用 diagnose（建立反馈回路→复现→修复）+ tdd（红绿循环）验证性修复。stash 仅作参考，所有改动逐 hunk 手工挑选，禁止整体 cherry-pick。每个修复配套回归测试，累积成测试基线。

修复策略遵循 CONTEXT.md 的操作模型与角色边界：尊重 RouterAgent/FieldMappingAgent/ThreatAgent/EnumAgent/LogParserAgent 的职责划分，不引入跨角色的越权逻辑。

## 用户故事

US-1：作为维护者，我想要竖线分隔的 KV 日志能正确提取所有字段，以便字段映射阶段拿到完整的原始字段列表。

US-2：作为维护者，我想要纯 KV 日志的 real_samples 保留完整日志行而不被内嵌 JSON 子串截断，以便分类详情展示真实样例。

US-3：作为使用者，我想要界面分类详情正确显示含竖线分隔符的 KV 样例行而不被 Markdown 表格切列截断，以便看清完整日志内容。

US-4：作为使用者，我想要含多关键词冲突的用户消息（如"把这些枚举值进行威胁类型的映射"）被正确路由到 general 意图而非误触枚举提取快路径，以便避免 enum_handler 收到错误类型对象而崩溃。

US-5：作为使用者，我想要自然语言"映射"路径使用日志 KV 行的真实字段（uuid/name/srcIp 等）而非 Excel 列头（发生时间/事件名称）作为字段提示，以便 LLM 产出正确的字段映射。

US-6：作为使用者，我想要威胁类型映射路径能注入上一步提取的枚举值列表，以便 ThreatAgent 有数据可映射。

US-7：作为使用者，我想要历史消息不被过早截断（500→1500 字符），以便跨步骤的枚举值列表等长内容能在后续步骤中被完整看到。

US-8：作为维护者，我想要 Pydantic 对象转字符串的逻辑被提取为单一共享函数，以便消除 4 处分散的重复副本、统一序列化行为。

US-9：作为维护者，我想要 SessionState 有完整的字段契约并配套自动扫描的契约测试，以便任何新增 session 键写入都能被测试捕获、避免运行期 KeyError。

US-10：作为使用者，我想要枚举提取用直接的 LLM JSON 调用而非 RouterAgent 路由，以便避免路由解释 Markdown 污染 JSON 解析导致正则提取失败。

US-11：作为使用者，我想要含多个操作的复合意图（如"提取枚举值然后做威胁映射"）被分解为有序步骤逐一执行，以便复合请求不被丢弃或只处理一半。

US-12：作为维护者，我想要测试基础设施（conftest.py）就位，以便所有新增回归测试能在统一环境下运行。

## UI 与设计要求

**UI 模式：`headless`**

本 PRD 全部为后端/逻辑 bug 修复，无可视化 UI 页面。US-3 涉及的"界面 Markdown 渲染"是 Chainlit 消息渲染层的纯文本输出格式修正（表格→代码块），不属于独立 UI 页面，归为 headless 的输出契约修复。

## 实现决策

### KV 键名捕获组字符类化

`kv_extractor.py` 动态正则的键名捕获组从贪婪的 `(\S+)`（`\S` 匹配所有非空白含 `|`/`:`/`,` 等分隔符）改为字符类 `[^{排除集}=\s]+`。需先归一化 `field_delimit`（兼容 `" "`/`"space"`/`"\t"`），且仅当 `field_delimit="space"` 时把 `kv_delimit` 加入排除集。字符类方案对单字符分隔符天然正确。处理 `bad escape` 回归（只转义 `] \ ^ -` 四个元字符）。

### real_samples JSON 子串收紧

`llm_postprocessor.py` 的 `match_real_samples` 分支 C fallback，判断条件从 `"{" in matched_line` 收紧为 `matched_line.lstrip().startswith("{")`——只有整行以 `{` 开头才提取 JSON body，避免纯 KV 行中内嵌 JSON 子串（如 `dipGeo={"10.163.2.52":{...}}`）被误当作 body 截出。

### 分类详情渲染代码块化

`web/utils.py` 的 `render_log_parser_result`，把样例行从 Markdown 表格 `| 特征值 | 真实样例 |` 改为 `**{feature_val}**` + 围栏代码块 ```` ```\n{sample}\n``` ````，使 KV 行中的 `|` 分隔符在代码块内不被解析为表格列分隔符。纯展示层改动，不影响数据流。

### 快路径路由统一走 detect_intent

`web/user_message_handlers.py` 删除 `is_enum_extract`/`is_log_parser`/`is_enum`/`is_threat`/`is_mapping` 五个绕过 `detect_intent` 的野生布尔判断，改为 `if detected_intent == "enum":` / `if detected_intent == "log_parser":`。让多关键词冲突的消歧统一交由 `detect_intent`（route_config）处理。**不含** step_planner 集成和 Pydantic 防御（独立 bug）。

### 字段来源统一 field_source 抽取

新建 `web/field_source.py`，提供 `extract_log_fields_for_mapping(classification, raw_log_lines)`：两级优先级（log_classification 子规则的 normalize[].index → 原始日志 KV 正则兜底），去重排序，排除 Excel 列头。`input_builder.py`（mapping/general 路径）、`enum_handler.py`（字段提示）、`action_callbacks.py`（on_apply_field_mapping）三处复用。依赖 master 已存在的 `generate_sub_rules`（core.py）和 `EXCLUDED_FIELD_INDICES`（field_mapping.py）。**必须删除** action_callbacks.py 中 stash 残留的顶格 `from agent.tools.rule_generator.field_mapping import EXCLUDED_FIELD_INDICES` 死代码。

### threat 路径注入枚举值

`web/input_builder.py` 的 threat 分支，在拼装 LLM 输入时注入 `last_enum_extract_result`（由 enum_handler 已写入 session）的枚举值列表。`enum_result.get("value", [])` 提取值列表拼入上下文。与历史截断（MAX_ENTRY_CHARS）同属"枚举值在复合流程中丢失"根因的两半。

### 历史单条上限调整

`web/history_store.py` 的 `MAX_ENTRY_CHARS` 从 500 调整为 1500，使枚举值列表等长内容不被截断。**隐患**：`DEFAULT_HISTORY_MAX_CHARS`（总窗口，当前 2000）与新的单条上限 1500 几乎相等，1 条满长记录会吃满整个历史窗口导致多轮退化。需评估是否同步调大总窗口至 4000-6000。

### Pydantic 对象序列化共享函数

新建 `web/utils.py: content_to_str(result_content) -> str`，统一 `model_dump()` + `json.dumps(ensure_ascii=False)` + Pydantic v1/v2 双兼容。替换 `web/llm_client.py`、`web/response_handler.py`、`web/user_message_handlers.py` 三处分散的转换逻辑。**parsers.py 的 `_extract_items_from_pydantic` 不并入**（语义不同，它提取 items 列表而非 content→str）。**不参考 stash**（stash 未提取反而新增第 4 份副本）。

### SessionState pending_steps 字段 + 契约测试

`web/session_state.py` 新增 `pending_steps: Optional[List[str]]` 字段。配套契约测试 `test_session_state_contract.py`：用正则扫描 `web/` 全目录的 `session["key"]=` 写入，断言所有写入的键都在 SessionState 已定义，把运行期 KeyError 提前到测试期。**窄范围**：只加字段+契约测试，不含 step_planner 全功能（156 行新代码 + router prompt 改动），避免范围蔓延。

### enum_handler 切换 _call_llm_direct

`web/enum_handler.py` 的 `handle_enum_extract_flow`，LLM 调用从 `team.run`（RouterAgent route 模式，输出路由解释 Markdown）切换为 `asyncio.to_thread(_call_llm_direct, ...)`（master 已存在，返回纯字符串 JSON）。删掉 `result.content` 解包（`_call_llm_direct` 直接返回字符串）。`_call_llm_direct` 的 `force_json=True` 默认对 deepseek/siliconflow 加 `response_format=json_object`。

### 复合意图分解引擎 step_planner

新建 `web/step_planner.py`，四个函数：`parse_plan_marker(result_content)` 用正则 `\[PLAN:([a-z_|]+)\]` 提取步骤列表；`has_pending_steps`/`pop_next_step` 队列操作读写 `session["pending_steps"]`；`execute_step(step_type, ...)` 分发器（fill→fill_dispatcher，enum→enum_handler，log_parser→log_parser_handler，threat/mapping→call_team+process_team_response）；`execute_pending_steps` while 循环逐个 pop，任一步失败清空队列停止。纯逻辑部分可离线测试，threat/mapping 执行分支依赖 LLM 需 web 实测。`web/user_message_handlers.py` 仅取 7.6 段（parse→入队→stream 说明→execute），**剥离** 路由重构和 Pydantic 防御两块噪音。

### multi-step-plan skill 挂载

`agent/core/team.py` 挂载 `Skills(loaders=[LocalSkills(skills_dir)])`。新建 `skills/multi-step-plan/SKILL.md`（何时用/何时不用、步骤类型枚举 `{log_parser,mapping,enum,threat,fill}`、3 个示例）+ `references/step-types.md`（5 种步骤类型数据依赖表）。**用白名单挂载**（只加载 multi-step-plan 等业务 skill），避免 `_template` 被误加载为 RouterAgent 噪音技能。

## 测试决策

### tests/conftest.py 前置基础设施

新建 `tests/conftest.py`（注入项目根到 sys.path），是所有 stash 新增测试（9 个）能 import `web.*` / `agent.*` 的前提。master 当前无 conftest，只有 `tests/test_route_config.py` 一个测试。这是所有批次测试的前置依赖，第一批必须先落地。

### KV 提取竖线分隔回归

`test_kv_extractor.py`：用真实奇安信 NGSOC 管道分隔日志回归，覆盖竖线分隔提取、值不被串连、带方括号值、值含空格、各分隔符组合、中文键名、聚合覆盖率≥90%。隔离加载 `_load_kv_extractor_isolated()` 注入假 logger 避免 Windows WinError 32。

### real_samples 纯 KV 不截断回归

`test_match_real_samples.py`：三类回归——纯 KV 行 real_samples 等于完整行（断言以 `uuid=` 开头不截断）、纯 JSON 行保留 body、syslog 头+JSON 剥离头部。

### Markdown 渲染不截断回归

`test_render_and_fields.py` 的 `TestRenderRealSamplesNotTruncated`：断言 `name=`/`severity=`/`srcIp=` 等字段出现在结果中 + 结果含围栏代码块标记。与字段来源测试共享文件。

### 路由一致性回归

`test_user_message_routing.py`：用 monkeypatch 打桩下游 handler + asyncio.run 驱动 `handle_user_message`，5 个测试覆盖枚举×威胁冲突→general、纯枚举保留快路径、日志×枚举冲突→general、纯日志保留快路径、清空快捷键不变。不依赖 step_planner。

### field_source 字段提取回归

`test_field_source_fallback.py`：覆盖无 classification 从原始日志提 KV（含启明天阗 syslog+kv 和奇安信 NGSOC 竖线格式）、排除 Excel 列头、去重、空输入、general 意图用日志字段而非列头。

### threat 枚举注入回归

`test_threat_context.py`：3 个用例——注入全枚举值、无结果时不变、空列表不注入。FakeSession 自洽。

### SessionState 契约全量扫描

`test_session_state_contract.py`：正则扫描 web/ 全目录 session 写入 vs 已定义字段断言。master 当前全绿（约 20 个唯一键均已定义），是纯增量防护网。**删掉 pending_steps 专属断言改通用示例**（窄范围）。

### enum 不调 team.run 回归

`test_enum_handler_subscript.py`：用 `SpyTeam` 间谍对象验证 `team.run` 不被调用（即使 `_call_llm_direct` 因无 API key 抛异常也通过），CI 离线友好。

### step_planner 纯函数回归

`test_step_planner.py`：只测 `parse_plan_marker` + 队列管理纯函数（6 个 parse 用例 + 5 个队列用例），不测 `execute_step`/`execute_pending_steps`（异步+chainlit+LLM 难测）。用 FakeSession 模拟 session get/setitem。

## 范围外

- **agno_repo submodule 清理**：stash 分支误把 agno_repo 当 submodule（160000 mode），需 `git rm --cached agno_repo` + 加 .gitignore，但独立于 bug 修复，不在本 PRD 范围。
- **gitcode origin 迁移**：最终把 gitcode origin 指向 GitHub 是收尾工作，不在本 PRD 范围。
- **Windows 文件锁根治**：PermissionError WinError 32（logger 文件句柄争用）偶发，测试用隔离加载规避，根因修复不在本 PRD 范围。
- **批5 的 step_planner 集成测试**：threat/mapping 执行分支 + RouterAgent 是否触发 skill 只能 web 端实测，不纳入离线测试范围。

## 补充说明

### 批次依赖与顺序

- **批1**（KV正则 + real_samples截断 + Markdown渲染）：3 个独立低风险 `|` 同源 bug，验证工作流。
- **批2**（SessionState契约）：防护网优先，保护后续改动。
- **批3**（历史截断 + threat注入 + 快路径路由 + Pydantic序列化）：4 个确定性逻辑。3.2→3.1 强耦合；2.1 需剥离噪音；3.3 需自行实现。
- **批4**（field_source + enum切LLM）：2 个相关，enum_handler 中交织。
- **批5**（step_planner + skill挂载）：最高风险，依赖 LLM 行为。**前置依赖**：批3 的 Pydantic 序列化必须先落地（否则 parse_plan_marker 对 ThreatAgent 结果抛 TypeError）。

### 风险标注

- **stash 不可整体 cherry-pick**：所有 bug 的 stash diff 都混入无关改动（尤其 user_message_handlers.py 混入 step_planner + Pydantic + 路由三件事）。
- **批5 LLM 依赖点**：RouterAgent 是否触发 multi-step-plan skill（Progressive Discovery 是 LLM 驱动）、是否严格输出 `[PLAN:a|b]` 格式（正则严格，不允许大写/中文/空格）、步骤类型是否在白名单——只能 web 实测。
