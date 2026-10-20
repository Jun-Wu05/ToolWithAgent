# Issue 131 Architecture Baseline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不修改生产代码行为的前提下，为父 Issue #130 建立可追溯、可复验的零回归基线，并为 #132 的串行迁移提供人工放行依据。

**Architecture:** 以当前 `github/master` 提交为冻结点，从离线测试、真实 Planner 语义评测和真实 Chainlit 主路径三个接缝采集证据。所有运行证据写入 `outputs/issue130-baseline/20260828/`，不暂存、不提交；最终摘要发布到 GitHub Issue #131。

**Tech Stack:** Python 3、pytest、Agno/Pydantic Planner、Chainlit、Kimi WebBridge、GitHub CLI。

---

### Task 1: 冻结基线元数据

**Files:**
- Create: `outputs/issue130-baseline/20260828/baseline.md`
- Reference: `pyproject.toml`
- Reference: `docs/architecture/测试场景手册.md`

**Step 1: 记录提交与工作区状态**

Run: `git rev-parse HEAD`、`git status --short --branch`、`git log -1 --format=fuller`

Expected: HEAD 为 `github/master` 当前稳定提交；任何既有未跟踪文件单独列出，不纳入基线提交。

**Step 2: 收集测试清单**

Run: `python -m pytest --collect-only -q`

Expected: 收集成功，并记录测试文件数与测试用例数。

**Step 3: 校验模型配置但不读取密钥值**

记录 provider、model ID、聊天密钥是否存在、Embedding 密钥是否存在；禁止把密钥值写入终端、日志或报告。

### Task 2: 运行完整离线回归

**Files:**
- Create: `outputs/issue130-baseline/20260828/pytest.xml`
- Modify: `outputs/issue130-baseline/20260828/baseline.md`

**Step 1: 执行完整测试**

Run: `python -m pytest -q --junitxml=outputs/issue130-baseline/20260828/pytest.xml`

Expected: 全部通过；第三方 `traceloop` 的 Pydantic v2 弃用警告允许保留。

**Step 2: 记录结果**

将通过数、失败数、耗时、警告与 JUnit 文件 SHA-256 写入 `baseline.md`。

### Task 3: 运行真实 Planner 语义评测

**Files:**
- Create: `outputs/issue130-baseline/20260828/planner-semantic-eval.ndjson`
- Modify: `outputs/issue130-baseline/20260828/baseline.md`
- Reference: `evaluation/planner_semantic_eval.py`

**Step 1: 每条核心语料运行三次**

Run: `python evaluation/planner_semantic_eval.py --runs 3 --output outputs/issue130-baseline/20260828/planner-semantic-eval.ndjson`

Expected: 退出码 0，所有 schema 与语义断言通过；记录总调用数、失败数、延迟和 token 观测。

**Step 2: 记录模型调用冻结证据**

确认每次语义样例只调用 Planner 一次；确定性入口不在本评测中引入额外 Planner 调用。

### Task 4: 运行真实 Chainlit 主路径验收

**Files:**
- Create: `outputs/issue130-baseline/20260828/browser-report.md`
- Create: `outputs/issue130-baseline/20260828/*.png`
- Create: `outputs/issue130-baseline/20260828/downloads/*`
- Reference: `outputs/acceptance_checklist.md`
- Reference: `archive/testdata/logtype/test/KV/KvHeadQiming.xlsx`

**Step 1: 启动隔离的 Chainlit 进程**

Run: `chainlit run web/chainlit_app.py`

Expected: `http://127.0.0.1:8000` 可访问；只停止本次启动并记录 PID 的进程。

**Step 2: 验证设置与文件上传**

使用环境变量中的 provider/model，浏览器密钥框保持空白；上传 `KvHeadQiming.xlsx`，确认主数据建立且无密钥或真实路径泄漏。

**Step 3: 验证主业务链路**

依序执行日志类型提取、字段映射、枚举提取、威胁类型映射、填充、取消映射、字段调整和导出。记录可观察的 Session 变化、ExecutionReport、稳定错误码、Planner/专业模型调用阶段与产物下载。

**Step 4: 验证近期回归点**

复验 #148 的事件名称非法改名不会部分执行，以及 #149 的信息型问题直接从 SessionFacts 回答。

**Step 5: 检查下载产物**

对下载的 Base64 JSON 检查根类型、键顺序、中文编码、`normalize`、`mappings`、固定字段绑定和文件名；成功提示不能替代产物检查。

### Task 5: 发布 #131 基线结论

**Files:**
- Modify: `outputs/issue130-baseline/20260828/baseline.md`
- Modify: `outputs/issue130-baseline/20260828/browser-report.md`

**Step 1: 校验没有生产代码变更**

Run: `git diff --exit-code -- agent contracts web skills`

Expected: 退出码 0。

**Step 2: 发布 Issue 评论**

使用 `gh issue comment 131` 发布提交、测试统计、语义评测、浏览器验收、已知风险和证据路径；不发布密钥、真实敏感数据或本地绝对路径。

**Step 3: 等待人工门禁**

若所有门禁通过，将 #131 标记为 `ready-for-human`，等待人工明确确认后才关闭 #131、放行 #132。若任一门禁失败，保持 #132 阻塞并报告最小复现，不在本 Issue 中修复。
