# Log Parsing Runtime Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `LogParseStep` 到日志分类、样本回填、规则导出和 `ExecutionReport` 的完整 tracer 迁入 Application 适配器接缝，并保持全部现有行为。

**Architecture:** 新建独立 `LogParseAdapter`，默认通过延迟 Agent 工具门面调用现有日志 Pipeline，并允许测试注入可控假件；Application 不导入 Web。确定性 JSON 解析归入 Application，五个日志 Prompt 加载实现归入现有 Prompt 包，旧入口仅重导出同一对象。字段映射、枚举、威胁和 Pipeline 内部策略不在本切片迁移。

**Tech Stack:** Python、Pydantic contracts、asyncio、pytest、AST 静态依赖门禁。

---

### Task 1: 冻结 Application 日志解析接口

**Files:**
- Create: `tests/test_application_log_parsing_architecture.py`

**Step 1: Write the failing test**

- 断言 `application.adapters.log_parse.LogParseAdapter` 可通过真实 `PlanExecutor` 和内存 Session 执行。
- 注入格式识别、分类与样本回填假件，断言调用顺序、参数、显式分类特征字段优先、Session 写回和 `LogClassificationArtifact` 完全一致。
- 断言非法格式与空分类保持 `log_format_invalid` / `log_parse_failed`，且不覆盖旧分类。
- 断言 Application 日志模块不导入 Web 或 Chainlit。

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_application_log_parsing_architecture.py -q`
Expected: FAIL，因为新 Application 模块尚不存在。

### Task 2: 迁移确定性 JSON 解析接缝

**Files:**
- Create: `application/parsing.py`
- Modify: `web/utils.py`
- Test: `tests/test_application_log_parsing_architecture.py`

**Step 1: Write the failing identity test**

断言旧 `web.utils.parse_json_safe` 与新 Application 函数是同一对象，并冻结 Markdown code fence、嵌入对象与非法 JSON 行为。

**Step 2: Implement the minimal move**

原样移动函数；Web 仅显式重导出，不保留第二份实现。

**Step 3: Run focused tests**

Run: `python -m pytest tests/test_application_log_parsing_architecture.py tests/test_parsers.py -q`
Expected: PASS。

### Task 3: 深化日志解析适配器模块

**Files:**
- Create: `application/adapters/log_parse.py`
- Modify: `application/adapters/__init__.py`
- Modify: `agent/tools/__init__.py`
- Modify: `web/adapters/agent_ops.py`
- Modify: `web/adapters/__init__.py`
- Modify: `web/execution_adapters.py`
- Test: `tests/test_application_log_parsing_architecture.py`
- Test: `tests/test_single_intent_execution.py`
- Test: `tests/test_execution_adapters.py`

**Step 1: Implement the minimal adapter**

- 从 Session 日志构造原文本。
- 严格保持格式识别 → JSON 解析 → 分类 → JSON 解析 → 样本回填 → Session 写回 → 类型化产物顺序。
- 默认依赖经 Agent 工具门面延迟解析；测试可注入假件。
- 保持非空 FAILED 分类结构当前仍成功的历史行为。

**Step 2: Rewire the composition seam**

唯一生产组合入口将 `log_parse` 直接注册到新适配器。旧 `ProfessionalAgentAdapter` 对 LogParseStep 只委托新对象；旧公开模块重导出相同类对象。

**Step 3: Run focused tests**

Run: `python -m pytest tests/test_application_log_parsing_architecture.py tests/test_single_intent_execution.py tests/test_execution_adapters.py tests/test_plan_executor.py tests/test_progress_reporting.py -q`
Expected: PASS，调用次数与稳定错误码不变。

### Task 4: 迁移日志 Prompt 加载实现

**Files:**
- Modify: `agent/prompts/__init__.py`
- Modify: `agent/core/prompts.py`
- Modify: `agent/tools/pipeline/log_format_identifier.py`
- Modify: `agent/tools/pipeline/log_classifier.py`
- Modify: `agent/tools/pipeline/log_feature_locator.py`
- Modify: `agent/tools/pipeline/log_header_processor.py`
- Test: `tests/test_application_log_parsing_architecture.py`

**Step 1: Write failing prompt tests**

- 五个公开加载函数的新旧对象身份相同。
- 内容逐字等于对应 Markdown。
- 从非仓库 CWD 冷导入并加载成功。
- 临时替换资源定位时缺失行为仍返回空字符串。

**Step 2: Move loaders without policy changes**

加载实现使用 Prompt 包自身目录；Pipeline 只导入 Prompt 包公开函数；旧 Core 入口只重导出。

**Step 3: Run prompt and pipeline tests**

Run: `python -m pytest tests/test_application_log_parsing_architecture.py tests/test_log_parser_marker_fix.py tests/test_log_format_consistency.py tests/test_explicit_feature_field.py tests/test_log_coverage_info.py -q`
Expected: PASS。

### Task 5: 验证日志分类到规则导出的 tracer

**Files:**
- Modify: `tests/test_application_log_parsing_architecture.py`

**Step 1: Add the tracer**

通过 `create_default_adapters` 执行日志分类，再通过 Application `ExportAdapter` 生成入口/子规则 Base64；断言 Session、`ExecutionReport`、规则 mode、解码结构与进度事件。

**Step 2: Run the tracer**

Run: `python -m pytest tests/test_application_log_parsing_architecture.py -q`
Expected: PASS。

### Task 6: 同步文档并完成回归

**Files:**
- Modify: `docs/architecture/架构概览.md`
- Modify: `docs/architecture/统一Planner架构.md`
- Modify: `docs/architecture/chainlit_app模块说明.md`

**Step 1: Update current architecture facts**

记录独立日志适配器、Prompt 加载归属和剩余 Web 业务适配器；不得宣称后续切片已完成。

**Step 2: Run verification**

Run: `python -m py_compile ...`
Expected: PASS。

Run: `python -m pytest -q`
Expected: 全部通过；系统临时目录权限失败时在获准的非沙箱环境重跑。

Run: `git diff --check`
Expected: 无错误。

### Task 7: 提交并回写 Issue

**Step 1: Review and stage only #134 files**

不得加入用户已有的 `docs/prd/application-runtime-extraction.md` 或 `outputs/`。

**Step 2: Commit**

Run: `git commit -m "refactor(application): migrate log parsing runtime"`

**Step 3: Update #134**

发布带 triage 免责声明的验证证据并关闭 Issue；不推送，除非用户再次明确要求。
