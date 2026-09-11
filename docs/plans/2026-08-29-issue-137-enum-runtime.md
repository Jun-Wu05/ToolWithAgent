# Enum Runtime Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将枚举提取、枚举填充和枚举映射附件生命周期迁入 Application，保持全部用户可观察行为与调用次数不变。

**Architecture:** 以 `EnumExtractAdapter`、`EnumFillAdapter` 和枚举映射附件提交模块形成三个深层模块。Web 只保留 Chainlit 上传展示与尚未迁移的威胁链路；旧枚举导入路径只重导出 Application 的同一对象。

**Tech Stack:** Python、asyncio、Pydantic、pytest、Chainlit 兼容垫片。

---

### Task 1: 冻结 Application 枚举接缝

**Files:**
- Create: `tests/test_application_enum_architecture.py`
- Test: `tests/test_single_intent_execution.py`
- Test: `tests/test_file_handlers.py`

**Step 1: Write the failing test**

验证 Application 枚举模块不导入 `web`/`chainlit`，默认组合入口直接使用 Application `EnumExtractAdapter`，旧 `EnumFillAdapter` 路径与新对象身份相同。

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_application_enum_architecture.py`
Expected: FAIL，因为 Application 枚举适配器和附件模块尚不存在。

**Step 3: Write minimal implementation**

仅创建公开模块与同对象兼容导出，不搬运行为。

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_application_enum_architecture.py`
Expected: 部分通过，行为测试仍为红色。

### Task 2: 迁移枚举提取适配器

**Files:**
- Create: `application/adapters/enum_extract.py`
- Modify: `application/adapters/__init__.py`
- Modify: `web/adapters/agent_ops.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`
- Test: `tests/test_application_enum_architecture.py`
- Test: `tests/test_single_intent_execution.py`

**Step 1: Write the failing test**

用计数 LLM 假件验证一次枚举提取只加载一次 Prompt、调用一次直连模型，参数仍为 `temperature=0.1`、`max_tokens=500`、`timeout=120`；成功后保持字段顺序并同时提交展示结果与可引用会话产物，失败不覆盖旧结果。

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_application_enum_architecture.py -k extract`
Expected: FAIL，因为枚举提取仍由 Web 的广口适配器拥有。

**Step 3: Write minimal implementation**

把枚举提取实现迁入 `EnumExtractAdapter`；通过 `agent.prompts.load_enum_extract_prompt()` 读取同一 Prompt；使用 Application `parse_json_safe()`；默认组合入口直接注册新适配器。`ProfessionalAgentAdapter` 不再拥有枚举分支。

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_application_enum_architecture.py tests/test_single_intent_execution.py`
Expected: PASS。

### Task 3: 迁移枚举填充适配器

**Files:**
- Create: `application/adapters/enum_fill.py`
- Create: `application/adapters/fill_shared.py`
- Modify: `web/adapters/config_ops.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`
- Test: `tests/test_application_enum_architecture.py`
- Test: `tests/test_rule_targeting.py`
- Test: `tests/test_execution_adapters.py`

**Step 1: Write the failing test**

验证枚举填充保持规则顺序、旧贡献替换、固定字段解绑、稳定错误码和 `enummapping_config` Base64 解码文本；Session 只在完整计算成功后更新。

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_application_enum_architecture.py -k fill`
Expected: FAIL，因为真实实现仍在 Web。

**Step 3: Write minimal implementation**

原样迁移 `EnumFillAdapter`；把枚举与威胁共用的固定字段解绑实现移到 Application Adapter 私有共享模块，Web 的威胁填充继续调用同一函数；`FillAdapter` 委派 Application 枚举适配器。

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_execution_adapters.py tests/test_rule_targeting.py tests/test_application_enum_architecture.py`
Expected: PASS。

### Task 4: 迁移枚举映射附件生命周期

**Files:**
- Create: `application/enum_mapping_attachments.py`
- Modify: `web/file_handlers.py`
- Test: `tests/test_application_enum_architecture.py`
- Test: `tests/test_file_handlers.py`
- Test: `tests/test_referenceable_session_artifacts.py`

**Step 1: Write the failing test**

通过 Application 公共函数验证不同 Sheet 累积、同名 Sheet 完整替换、旧枚举贡献标记过期、待重填集合更新，以及解析失败前 Session 不变化。

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_application_enum_architecture.py -k attachment`
Expected: FAIL，因为提交函数仍归 Web。

**Step 3: Write minimal implementation**

迁移 `_commit_enum_workbook` 的全部确定性状态转换；Web 上传处理器只负责读取 Excel、调用 Application 函数并渲染预览。旧私有函数保留同对象别名供迁移期测试兼容。

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_file_handlers.py tests/test_referenceable_session_artifacts.py tests/test_application_enum_architecture.py`
Expected: PASS。

### Task 5: 回归与提交

**Files:**
- Modify: directly affected current architecture documentation only if it names the old production owner

**Step 1: Run focused regression**

Run: `pytest -q tests/test_application_enum_architecture.py tests/test_file_handlers.py tests/test_single_intent_execution.py tests/test_referenceable_session_artifacts.py tests/test_rule_targeting.py tests/test_execution_adapters.py tests/test_progress_reporting.py tests/test_plan_renderer.py`
Expected: PASS。

**Step 2: Run full regression**

Run: `pytest -q`
Expected: PASS；若 Windows 临时目录权限失败，获批后在沙箱外重跑同一命令。

**Step 3: Review staged change**

Run: `git diff --check` and `git status --short`
Expected: 只包含 #137 代码与测试；用户已有未跟踪文件不暂存。

**Step 4: Commit**

Run: `git commit -m "refactor(application): migrate enum runtime"`
Expected: 生成单一逻辑提交；本轮不推送，等待下一次“继续”。
