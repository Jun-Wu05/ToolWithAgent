# PRD：字段调整 skills 接入与事件名称枚举字段输出

## 问题陈述

作为日志解析规则生成工具的使用者，我可以在会话中上传 Base64 解析规则、或通过「日志类型提取 → 标准字段映射」链路生成子规则，但**无法对已有规则做字段级调整**：说「添加字段 X 值为 Y」「删除字段 Z」「把 A 和 B 合并成 C」时系统不认识这些意图——仓库 `skills/` 下已设计好三个字段操作技能（add-fields / delete-fields / merge-fields，含纯函数脚本），但从未接入 agent 主流程（无步骤类型、无适配器、无路由语义）。

同时，标准字段映射链路生成的子规则目前只有固定字段【日志类型】，缺少事件级标识：我需要每条子规则额外输出枚举字段【事件名称】（值域为附件定义的 6 个威胁类 + 15 个非威胁类），以及与【事件名称】绑定的【事件级别】（威胁类 → 提醒，非威胁类 → 信息），用于下游系统区分威胁/非威胁事件。

## 解决方案

按现行 ADR-0005 类型化计划架构接入三个字段操作技能：PlannerAgent 新增三类操作语义（add_fields / delete_fields / merge_fields），产出类型化步骤后由声明式注册表驱动的适配器调用 `skills/*/scripts/*.py` 纯函数（单一事实源），结果写回 session，可继续填充/导出。不使用 agno Skills/RouterAgent 挂载（与 ADR-0005 双轨并存、且与框架强耦合）。

【事件名称】通过标准字段映射链路自动标注：映射成功后，对每条子规则用单次 LLM 批量调用做两段式判定（先威胁/非威胁分组，再组内选具体类），输出经 21 值白名单确定性校验后，与查表绑定的【事件级别】一并写入子规则 `parser.filter`（addFields，与【日志类型】同构）和 `normalize`（末尾条目）。

两类输入数据殊途同归（对应 CONTEXT.md 数据源）：用户上传的 Base64 解析规则（`session.decoded_config`）与链路生成的子规则（`session.mapped_sub_rules`），字段调整对两者都可用；事件名称标注只挂在标准字段映射链路（对 `mapped_sub_rules` 生成时自动执行）。

## 用户故事

US-1：作为上传了 Base64 解析规则的使用者，我想要说「添加字段 主机ip，值为 1.1.1.1」时系统在规则的每个 entity 上新增该字段（parser.filter 追加 addFields + normalize 追加条目），以便扩展规则字段。

US-2：作为使用者，我想要新字段的值支持固定值或 `%{已有字段}` 引用两种形式，以便覆盖静态标注与跨字段引用两类需求。

US-3：作为使用者，我想要说「删除字段 a 和 b」时系统移除对应字段（filter 追加 removeFields + normalize 移除条目），以便清理无用字段。

US-4：作为使用者，我想要删除系统保留字段（original_log、rule_name_list、日志类型）时被明确拦截并提示原因，以便不破坏规则结构。

US-5：作为使用者，我想要说「把字段 a 和 b 合并成 d，分隔符 -」时系统追加 merger filter 并生成合并预览条目，以便聚合信息。

US-6：作为使用者，我想要上述三类操作对「链路生成的子规则（mapped_sub_rules）」同样可用，以便在自动生成结果上继续手工微调。

US-7：作为使用者，我想要字段调整后的配置可以导出为 Base64 下载（含步骤产物直接导出），以便交付到目标系统。

US-8：作为使用者，我想要标准字段映射完成后，每条子规则自动带有【事件名称】（21 个合法分类名之一）和按绑定关系写入的【事件级别】，以便下游区分威胁/非威胁事件。

US-9：作为使用者，我想要事件名称的判定依据（reason）可见、判定失败或无法归类的子规则被标注「待人工确认」而不是写入错误值，以便核查与补正。

US-10：作为使用者，我想要手动通过字段添加写【事件名称】时系统校验值必须在 21 个合法分类名内，并自动联动写入绑定的【事件级别】，以便手工修正时不出绑定错乱。

US-11：作为维护者，我想要三个 skills 脚本先修复已知缺陷（入口规则 filter=null 崩溃、空 normalize 静默虚报成功、保留字段缺失）再接线，以便线上数据不踩坑。

US-12：作为维护者，我想要以后新增/删除一个字段操作技能只需「脚本 + 契约类 + 注册表一行 + 提示词一条」，以便低成本扩展技能集。

## UI 与设计要求

**UI 模式：`headless`**

本 PRD 全部为 agent 后端能力（步骤契约、适配器、判定模块），交互复用现有 Chainlit 聊天界面与统一执行报告渲染，无新增可视化页面。

## 实现决策

### 字段调整步骤契约（add_fields / delete_fields / merge_fields）

在 Planner 公共契约中新增三个步骤类型并加入 StepSpec 判别联合：add_fields（field_name、field_value、value_type=fixed|reference、config_ref）、delete_fields（fields 元组、config_ref）、merge_fields（source_fields ≥2、target_field、sep、config_ref）。config_ref 复用现有 ConfigRef（session.decoded_config | session.mapped_sub_rules），并存时沿用既定约定优先 mapped_sub_rules。导出产物类型新增 field_adjusted_config 下载类型。

### 字段调整适配器与声明式注册表

新建适配器模块，含声明式注册表 `{步骤类型 → skills 脚本路径 → 函数名}` 与参数化适配器：从 ExecutionContext 按 config_ref 读 session 配置 → 调用 skills 脚本纯函数 → 成功后写回 session 同一字段 → 产出含 Base64 内容的配置导出产物（供 export 步骤以 step: 依赖导出）。skill 脚本经 importlib 从 skills/ 目录加载，保持 skills 脚本为单一事实源，不在适配器内复制逻辑。事件名称绑定守卫内建于适配器：手动添加【事件名称】时校验 21 值白名单（非法返回稳定错误码 invalid_event_name），并自动联动添加绑定的【事件级别】。

### skills 脚本修复（filter=null / 空 normalize / 保留字段）

三个 skills 脚本接线前修复：entity 的 parser.filter 为 None 时初始化为空数组再追加（入口规则模板 filter 即为 null）；normalize 为空的 entity 不再静默计入成功数，返回消息区分「已应用/跳过」；delete 的保留字段集合扩展为 original_log、rule_name_list、日志类型，命中返回 error 并提示。字段操作应用到数据中的每一个 entity（含入口规则与子规则混合数据）。

### 事件名称 21 枚举值与事件级别绑定表

威胁组 6 值：网络攻击、病毒检测、邮件告警、终端告警、蜜罐告警、其他告警；非威胁组 15 值：登录事件、审计事件、会话操作、进程操作、用户操作、资源监控、邮件操作、dns查询、dns响应、数据库操作、ssh连接、认证事件、telnet连接、网络连接、web访问。绑定关系为确定性查表：威胁组任一值 → 事件级别「提醒」，非威胁组任一值 → 「信息」；级别由代码写入，不经 LLM。「存在威胁事件/非威胁事件」仅是判定分组概念，不作为字段值。

### 事件名称判定（LLM 两段式 + 确定性校验）

判定模块复用日志解析管线的 LLM 客户端与提供商注册表配置，单次批量调用覆盖全部子规则。每条子规则组装四类信号：日志类型名、样本日志（截断）、normalize 字段名列表、规则名。提示词内置两段式判定程序：先按两组判定逻辑分组（威胁：攻击行为特征、安全设备来源、block/deny/drop 动作词；非威胁：正常业务、认证、运维行为），再组内按「特征 + 操作类型枚举」选具体类，并内置附件的区分规则（如：有 URL 归 web访问 而非 网络连接；22 端口 SSH 协议交互归 ssh连接 而非 登录事件；会话建立/销毁归 会话操作）。输出严格 JSON（每条 rule_name → {event_name, group, reason}）。代码侧做确定性校验：event_name ∈ 21 值白名单、group 与所属组一致；非法输出带错误反馈重试一次；仍非法时威胁组兜底「其他告警」，非威胁组不写入并在报告列出待人工确认（宁缺勿错）。

### 事件名称写入子规则（filter addFields + normalize 条目）

确定性写入函数对每条子规则：parser.filter 末尾追加 `{"fields": {"事件名称": <分类名>, "事件级别": <提醒|信息>}, "name": "addFields", "id": ""}`（与现有【日志类型】addFields 同构）；normalize 末尾追加两条目（field 分别为 event_name/event_level、sim=True、entity=事件、core=False、index 分别为 事件名称/事件级别）。全部格式（纯 JSON、syslog+JSON、KV）的子规则均写入；入口规则不动。重新执行字段映射时子规则全新生成并重判，天然幂等。

> **2026-09-03 修订（#177）**：原文的 `entity=日志` 是与标准字段目录冲突的过时决策——
> 目录中 event_name/event_level 的对象均为「事件」（log_type 的对象才是「日志」），
> 目标平台对 `event_name日志` 组合无法解析。且标准字段目录（系统属性名称/字段名称/对象）
> 是对象归属的 SSOT：字段映射写入的 field/entity 一律由目录确定性解析，目录外名称降级
> 为未匹配，不再从 对象.xlsx 回填或默认「事件」。

### 标准字段映射链路挂接

字段映射适配器在映射成功产出子规则后、原子写回 session 之前挂接判定与写入；判定 LLM 失败重试一次，仍失败整步失败（稳定错误码 event_classify_failed），不静默跳过。映射输入排除集合（EXCLUDED_FIELD_INDICES）增加 事件名称、事件级别，防止后续重复映射把固定字段当原始字段。判定表（子规则 → 事件名称 → 理由）随执行结果消息展示。

### Planner 操作语义与消歧

Planner 提示词操作目录新增三条字段调整操作语义（参数必须显式、config_ref 取自可用配置目录），并新增消歧规则：「删除字段 X」是 delete_fields，「取消/删除 X 的映射」是 remove_mapping，两者不可互换；合并需源字段≥2 与目标字段名；添加【事件名称】时的枚举与绑定语义。渲染层操作标签新增三个中文名。

## 测试决策

### skills 脚本纯函数 seam

三个脚本以纯函数直接测试（deepcopy 不改原数据、返回 status/data/message 契约）：覆盖 filter=null 初始化、空 normalize 跳过计数、保留字段拦截、字段冲突、引用型值原样保留。先例：脚本曾有本地手动运行记录，本 seam 将其纳入 pytest。

### StepAdapter 协议 seam

适配器用构造的假 session（SessionState）与步骤对象测试：config_ref 读映射（decoded_config ↔ decoded_data、mapped_sub_rules）、成功写回 session、缺配置返回 needs_input(config_required)、脚本 error 透传为稳定错误码、事件名称白名单校验与级别联动。先例：现有 fill/remove_mapping/export 适配器测试同模式。

### 契约校验 seam

pydantic StepSpec 校验：三新类型的必填参数、merge 源字段≥2、ConfigRef 合法值、StepSpec 判别联合接受新类型、PlanDecision 依赖校验不回归。

### 事件名称判定 seam（注入假 LLM）

判定模块通过依赖注入假 LLM 客户端测试：21 值白名单校验、group 一致性校验、非法输出重试、威胁组兜底、非威胁组待确认列表、写入函数的 filter/normalize 结构与绑定查表（21 值 × 级别全断言）。先例：FieldMappingAdapter 的 candidate_retriever/object_map_loader 构造假件模式。

### E2E base64 规则锚点

用仓库测试数据（4 个 Base64 规则：1 个入口规则 + 3 个真实子规则样本）走完整链路断言：解码 → 增/删/合并 → 结构正确（dict key 顺序不变，Base64 输出稳定）→ 导出。字段映射链路断言子规则含【日志类型】+【事件名称】+【事件级别】及绑定值。

## 范围外

- agno Skills/RouterAgent 挂载方案（与 ADR-0005 冲突，已决策不采用）。
- 正则提取、base64 解码字段两个技能的接入（skills 设计文档中已有知识素材，作为后续独立需求）。
- multi-step-plan 技能的复活（已被 ADR-0005 类型化计划取代，仅标注废弃）。
- 用户上传规则（decoded_config）上的事件名称自动标注（本 PRD 只挂在标准字段映射链路；用户可经 add_fields 手工添加，绑定守卫保证级别正确）。
- 新的可视化 UI 页面。

## 补充说明

**已确认的边界决策**（grill 拷问结论，2026-08-25）：

| # | 边界问题 | 决策 |
|---|---|---|
| 1 | 两类配置并存时 config_ref 优先级 | 沿用既定约定：优先 session.mapped_sub_rules |
| 2 | 非威胁组判定失败兜底 | 宁缺勿错：不写入，报告列待人工确认 |
| 3 | 入口规则与子规则混合数据 | 字段操作应用到每一个 entity |
| 4 | 手动添加事件名称 | 白名单硬校验 + 自动联动事件级别 |
| 5 | delete 保留字段 | original_log / rule_name_list / 日志类型；事件名称/事件级别可删 |
| 6 | merge 引用型字段 | normalize result 记录 %{a}%{b} 预览值，运行时由 merger filter 实际拼接 |
| 7 | 重判幂等性 | 重新映射即全新生成+重判；手动改值后再映射会被覆盖 |

**风险**：事件名称判定准确率依赖 LLM 与提示词质量，验收以 3 个真实子规则样本的自动化锚点断言 + 360 真实数据 37 类判定表人工核对；判定知识源文件中 #病毒检测 段的「威胁类型」清单实为字段名列表（数据瑕疵），提示词整理时只取其特征描述。

**依赖**：ADR-0005（类型化计划）、ADR-0007（提供商注册表，判定模块复用其 LLM 客户端配置）；本 PRD 将新增 ADR-0008（字段调整技能接入方式）。
