# ADR-0008：字段调整技能的类型化接线

- 状态：已接受
- 日期：2026-08-25
- 关联：CONTEXT.md「字段调整」「事件名称标注」术语；PRD issue #124；ADR-0005

## 背景

skills/ 目录下已设计三个字段操作技能（add-fields / delete-fields / merge-fields，各含 SKILL.md 与纯函数脚本），设计时假定走 agno 的 Skills/RouterAgent 机制（SKILL.md description 驱动运行时分发，依赖 base64_decode_tool 等 agno @tool）。探查确认该机制从未接线：agent/web 代码对 skills 目录零引用，意图路由与 StepAdapter 表中没有对应条目。同时 ADR-0005 已用「PlannerAgent 类型化计划 + PlanExecutor + StepAdapter」取代了早期基于 skill 的 `[PLAN:]` 路由方案——再引入 agno Skills 挂载会形成两套路由语义并存。

## 决策

字段操作技能按现行类型化计划架构接入，**不使用** agno Skills/RouterAgent：

1. **skills 脚本是单一事实源**：字段操作的全部数据逻辑留在 `skills/<name>/scripts/<op>.py` 纯函数（CLI 可独立运行）；适配器经 importlib 按声明式注册表 `{步骤类型 → 脚本路径 → 函数名}` 加载调用，不在适配器内复制逻辑。
2. **类型化步骤**：新增 `add_fields` / `delete_fields` / `merge_fields` 三种 StepSpec（携带字段名/值/来源/分隔符/config_ref），PlannerAgent 提示词扩展对应操作语义与消歧（删除字段 ≠ 取消映射）。
3. **声明式注册表**：新增一个字段操作技能 = 脚本 + 契约类 + 注册表一行 + 提示词一条；删除反向。无运行时自动发现、无静默生效，所有改动显式可测试。
4. **事件名称绑定确定性**：手动添加【事件名称】的合法性校验（21 值白名单）与【事件级别】联动写入在适配器层查表完成，LLM 不参与绑定。

## 公共不变量

- PlanExecutor 按 `step.type` 分派到 FieldSkillAdapter；适配器读 config_ref 对应 session 配置 → 调脚本 → 写回**同一**来源，禁止跨来源隐式迁移。
- 脚本返回 `{"status", "data", "message"}` 契约；适配器把中文错误消息映射为稳定错误码（field_conflict / reserved_field_rejected / field_not_found / insufficient_source_fields / invalid_event_name / event_level_conflict / config_required）。
- 保留字段集合（original_log / rule_name_list / 日志类型）由脚本层统一拦截。

## 取舍

相比 agno Skills 挂载（丢文件夹即生效），本方案增删技能需要 3-4 个显式改动点，换来：路由与执行完全复用 ADR-0005 基建（ExecutionReport / 进度 / 渲染 / 会话写回）、pydantic 契约校验拒绝错参、与 agno 解耦（更换 LLM 框架时计划/契约/脚本全部保留，只动模型调用层）。skills 的触发语义沉淀进 planner.md 操作目录而非运行时分发，SKILL.md 保留为技能知识与调用链路文档。

## 附带决策：事件名称标注挂接

标准字段映射链路在映射成功后、原子写回前，对每条子规则 LLM 判定【事件名称】（两段式：先威胁/非威胁分组、再组内选 21 分类名之一），事件级别按绑定查表写入（威胁组→提醒、非威胁组→信息）。判定输出过白名单与分组一致性校验，非法带反馈重试一次、跨轮合并已接受条目；仍失败宁缺勿错——威胁倾向由 LLM 选「其他告警」兜底，代码不写入任何猜测值，未判定子规则在报告列「待人工确认」。LLM 整体失败重试一次后整步失败（event_classify_failed），保持原子写回。测试经 conftest 守卫隔离真实 LLM：默认空判定（存量行为不变），显式注入 llm_client 时透传真实判定逻辑。

## 附录：子规则寻址与填充即解绑（#126 定案，2026-08-26）

- **寻址**：五个字段调整步骤可选 `target_rule_names`（SessionFacts 暴露子规则名单，Planner 不得编造）或 `rule_group`（threat/non_threat 按已标注事件名称确定性分组），互斥、缺省全部。脚本层以 `target_names` 过滤实现（单一事实源）；适配器负责名单校验（rule_name_not_found）、组解析（event_annotation_required）与 delete 悬空引用守卫（field_reference_conflict：merger 源字段与 `%{字段}` 占位）。入口规则暂不参与寻址（#129）。
- **填充即解绑**：固定字段的 addFields 绑定值运行时优先于 normalize 值映射，用户显式枚举填充固定字段时由 fill 适配器先解绑（unbind_fixed_fields 删绑定键、保留 normalize）再写 mappings——显式填充即显式放弃绑定，恢复绑定靠重新映射。与「映射目标黑名单」（防映射占用）构成固定字段的两面保护：默认绑定独占，显式填充可解绑。
- **skip_existing**：批量加字段遇部分子规则已有同名字段时跳过并如实报告，取代整体失败；事件名称联动守卫在此模式下关闭级别冲突检查（跳过语义接管）。
- **展示分离**：标注明细（EventAnnotationRow：judged/uncertain）进入 FieldMappingArtifact，渲染为独立表格块置于字段映射表格上方；重映射在消息中明示「手动调整已被覆盖」。
