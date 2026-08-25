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
