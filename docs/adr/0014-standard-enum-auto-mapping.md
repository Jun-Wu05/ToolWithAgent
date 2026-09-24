# ADR-0014：标准枚举自动映射采用应用层代码 + 两阶段受约束 Prompt

- 状态：已接受
- 日期：2026-09-24
- 关联：issue #189、ADR-0009（Application 运行时归属）、ADR-0013（双入口共享业务代码）

## 背景

标准字段映射此前只写回字段名（normalize `field/entity/sim/core`），把字段映射到标准枚举字段后，值映射需要用户另行"导出 → 人工整理 → 再上传映射表"。#189 要求在同一次字段映射里自动补全枚举值映射，且不得写错规则：未知厂商的值语义无法理论穷举，抽样会漏值，模型可能缺失、重复或幻觉原值。

可选实现路径：纯代码同义词表（不可穷举）、单次 LLM 调用完成字段+值（无硬校验空间）、新增枚举审核 Agent/skill（引入第三个模型角色）、或在 Application 层用代码做发现与校验、LLM 只做受约束归类。

## 决策

采用应用层代码 + 两阶段受约束 Prompt，确定性优先：

- **值的发现与计数是纯代码**：`application/standard_enum_mapping.py` 按"子规则 × 原始字段"全量扫描本子规则的日志行（行归属沿用规则生成器自身语义），产出 ≤10 个唯一非空值的画像；LLM 不阅读原始日志。无全量日志时读 normalize `result` 并标记 `config-sample`。
- **字段名确定性命中优先**：`agent/core/standard_field_catalog.py` 的策略表 + `resolve_enum_field` 对 8 个目标字段做精确名/同义词解析，命中即绕过 LLM 字段判断；非精确字段走既有候选检索 + FieldMappingAgent，第一阶段输入注入分组值画像与增强候选元数据（含白名单，运行时从目录注入，不复制第二份）。
- **第二阶段复用 FieldMappingAgent**：orgValue→mappingValue 的语义归类通过既有成员的 `FieldMappingList` 结构化输出表达（原始字段名列承载 orgValue，系统属性名称列承载白名单标准值，未匹配表示不兼容），复用既有超时与一次重试；不新增 Agent、Planner Step、skill 或第三方依赖。
- **写回门禁是纯代码硬校验**：集合相等、EQUAL 逐字、orgValue 与解析器实际值逐字一致、mappingValue ∈ 白名单、全默认否决、已有不明 mappings 拒绝。任一失败即局部失败关闭：该画像零写入，对应子规则内该字段名映射降级"未匹配"，其他字段不受影响。

## 后果

- 用户不再需要为枚举字段手工上传映射表；界面与下载产物根结构不变（FieldMappingRow 三列与下载根结构保持），唯一新增可观测输出是画像级执行报告与步骤消息汇总。
- 第二阶段的模型输出天然受 output_schema 约束为三列结构，非法 JSON 按既有解析容错重试一次；语义错误由代码硬校验兜住，不存在"部分写入"。
- KV 值语义与解析器一致性由共享状态机（`extract_kv_pairs` 与 `split_kv_line_quote_aware` 同源）保证；该重构同时修复了 `field_retriever` 缓存重建路径缺失 `EMBEDDING_BATCH_SIZE` 导入的既有缺陷。
- 修改标准字段表（事件动作改枚举）会触发各 checkout 的 embedding 缓存 MD5 刷新链；本仓已按设计路径重建验证。
- "操作类型"的枚举化维持显式排除，待独立 issue 讨论；威胁类型继续走 #173 独占链路。
