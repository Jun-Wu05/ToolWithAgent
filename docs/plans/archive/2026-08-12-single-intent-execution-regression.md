# Single Intent Execution Regression Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 Base64 配置枚举填充回归，并保证七类单一业务操作能够通过类型化 PlanExecutor 到达正确执行结果或稳定的输入请求。

**Architecture:** FillStep 同时声明映射来源与配置目标来源，执行器不再把 decoded config 与 mapped sub-rules 混为同一前置条件。SessionFacts 只暴露脱敏的可用来源事实，适配器按显式 config_ref 修改对应结构并验证变更；日志记录安全事实、步骤契约和失败谓词。

**Tech Stack:** Python、Pydantic v2、Agno、Chainlit、pytest。

---

### Task 1: 锁定真实上传回归

**Files:**
- Modify: `tests/test_execution_adapters.py`
- Modify: `tests/test_plan_executor.py`

1. 新增只有 `decoded_data/raw_base64/enum_preview`、没有 `mapped_sub_rules` 的失败测试。
2. 运行聚焦测试，确认错误为 `fillable_config_required`。
3. 保留失败输出作为修复反馈回路。

### Task 2: 显式声明填充配置来源

**Files:**
- Modify: `web/planner_models.py`
- Modify: `web/session_facts.py`
- Modify: `agent/prompts/planner.md`
- Modify: `web/deterministic_plan.py`
- Modify: `web/action_callbacks.py`

1. 为 FillStep 增加 `config_ref`，仅允许 `session.decoded_config`、`session.mapped_sub_rules` 或声明的本次步骤引用。
2. SessionFacts 暴露可用配置来源，不暴露配置内容。
3. Planner 与按钮显式选择来源；两种来源同时存在且用户未限定时采用领域确定性优先级并记录该选择。
4. 增加非法来源与隐式缺省契约测试。

### Task 3: 修复 Base64 完整配置填充

**Files:**
- Modify: `agent/shared/mapping_utils.py`
- Modify: `web/execution_adapters.py`
- Modify: `web/planner_models.py`
- Test: `tests/test_execution_adapters.py`

1. 新增保持根结构的配置填充函数，递归寻找 normalize，按目标字段去重追加 mappings。
2. EnumFillAdapter 根据 config_ref 选择 decoded_data 或 mapped_sub_rules。
3. 返回完整配置的 ConfigExportArtifact，并把更新后的结构写回同一 session 字段。
4. 以执行前后映射数量验证 changed_count，零变更仍失败。

### Task 4: 增加可追溯安全日志

**Files:**
- Modify: `web/user_message_handlers.py`
- Modify: `web/plan_executor.py`
- Modify: `web/execution_adapters.py`
- Test: `tests/test_plan_executor.py`

1. 记录脱敏 SessionFacts 摘要、plan_id、step_id、operation、source_ref、config_ref 和目标字段数量。
2. 前置拦截记录 required/observed 谓词，不记录用户原文、文件名、路径或映射原值。
3. 适配器记录来源、变更前后计数和稳定错误类别。

### Task 5: 七类单一意图执行矩阵

**Files:**
- Create: `tests/test_single_intent_execution.py`
- Modify: `web/execution_adapters.py`
- Modify: `web/plan_executor.py`

1. 覆盖 log_parse、field_mapping、enum_extract、threat_mapping、fill、remove_mapping、export。
2. 专业 LLM 可替换，但不得 mock PlanExecutor 或执行核心。
3. 每项断言适配器确实被调用、结果状态正确、session 变更符合操作契约。
4. 输入不足必须返回稳定 needs_input，不允许异常或静默成功。

### Task 6: 回归与清理

**Files:**
- Modify: `tests/test_chinese_readability.py`（仅在新增模块时）
- Modify: `docs/architecture/统一Planner架构.md`

1. 运行聚焦测试和完整 pytest。
2. 导入 Chainlit 应用烟测。
3. 扫描 DEBUG 探针、旧 Fill 隐式来源和英文新增注释。
4. 运行 `git diff --check`。
