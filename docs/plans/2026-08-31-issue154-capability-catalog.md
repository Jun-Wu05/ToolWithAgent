# 领域能力目录与所有权 Schema Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立一个版本化、可测试的领域能力目录，使维护者和 Agent 能按模块接口、依赖、接缝与生命周期导航当前生产代码。

**Architecture:** 新文档作为导航 SSOT，不参与运行时注册。目录使用固定 schema 描述模块职责与上下游，并为延迟导入、重导出和动态加载提供显式证据；架构概览与 README 只提供入口链接。

**Tech Stack:** Markdown、Python、pytest、现有源码分析生成器

---

### Task 1: 冻结能力目录文档契约

**Files:**
- Create: `tests/test_capability_catalog_documentation.py`
- Test: `tests/test_capability_catalog_documentation.py`

**Step 1: Write the failing test**

新增测试读取目标 Markdown，断言元数据、固定 schema、核心能力条目、生命周期分类、静态分析盲区、软性预算声明和导航链接。

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_capability_catalog_documentation.py`
Expected: FAIL，因为领域能力目录尚不存在。

**Step 3: Review the RED failure**

确认失败只来自目标文档/导航缺失，而不是测试收集或编码错误。

### Task 2: 建立领域能力目录

**Files:**
- Create: `docs/architecture/领域能力目录.md`
- Modify: `docs/architecture/架构概览.md`
- Modify: `README.md`
- Test: `tests/test_capability_catalog_documentation.py`

**Step 1: Write minimal documentation implementation**

创建包含文档元数据、schema 说明、能力索引、依赖与测试接缝、生命周期状态、静态分析盲区和维护规则的目录。至少覆盖 Application 运行时、类型化契约、标准字段、字段映射、日志解析、解析规则生成、枚举/威胁/填充、字段调整 Skills、Prompt/模型与审计候选。

**Step 2: Add stable navigation**

从架构概览相关文档和 README 文档导航链接到新目录；不引入运行时注册或生成时导入。

**Step 3: Run test to verify it passes**

Run: `pytest -q tests/test_capability_catalog_documentation.py`
Expected: PASS。

### Task 3: 验证架构局部性与文档一致性

**Files:**
- Modify if needed: `docs/architecture/领域能力目录.md`
- Modify if needed: `tests/test_capability_catalog_documentation.py`

**Step 1: Run relevant architecture tests**

Run: `pytest -q tests/test_source_code_analysis.py tests/test_application_architecture.py tests/test_capability_catalog_documentation.py`
Expected: PASS。

**Step 2: Verify source references**

Run: `python scripts/generate_source_code_analysis.py --check`
Expected: 若脚本不支持 `--check`，记录该事实并改用已有 source analysis pytest 验证，不改写生成产物。

**Step 3: Review diff and scope**

确认 diff 仅包含领域能力目录、两个导航入口、文档契约测试；不修改生产运行时或候选模块。

### Task 4: 提交与双远端同步

**Files:**
- Add only: `docs/architecture/领域能力目录.md`
- Add only: `docs/architecture/架构概览.md`
- Add only: `README.md`
- Add only: `tests/test_capability_catalog_documentation.py`

**Step 1: Run final checks**

Run: `git diff --check`
Expected: PASS。

**Step 2: Commit**

Run: `git commit -m "docs(architecture): add capability ownership catalog"`

**Step 3: Push both remotes**

推送 `codex/issue154-capability-catalog` 到 GitHub 与已授权 GitCode 远端，不创建 PR/MR，不合并 main。
