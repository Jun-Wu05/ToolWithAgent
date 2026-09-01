# Issue #165 Field Mapping One-to-One Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在字段映射写回前确定性消除“不同原始字段占用同一标准字段”的冲突，并完整报告裁决结果。

**Architecture:** 新增无 Session 写入的 Application 冲突裁决模块，接收映射行、上传配置已有映射和可注入候选检索函数；按“既有映射占用 → 1.00 精确命中 → 目标候选相似度 → 原行序”选出保留者，并把落选行改为既有的“未匹配”形态。`FieldMappingAdapter` 在批次合并与数量校验之后、任何 apply 或 Session 写回之前调用一次，两个配置写回路径共享结果；Embedding 不可用时降级为行序，不调用 LLM。

**Tech Stack:** Python 3.11、dataclasses、Pydantic、pytest、Application adapters、现有字段候选检索文本契约。

---

### Task 1: 冻结冲突裁决规则

**Files:**
- Create: `tests/test_field_mapping_conflicts.py`
- Create: `application/field_mapping_conflicts.py`

**Step 1: Write failing unit tests**

覆盖以下输入输出：

```python
rows = [
    {"原始字段名": "src", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
    {"原始字段名": "client", "系统属性名称": "源IP", "匹配状态": "匹配成功"},
]
outcome = resolve_field_mapping_conflicts(rows, candidate_retriever=fake)
assert outcome.rows[0]["匹配状态"] == "匹配成功"
assert outcome.rows[1] == {
    "原始字段名": "client", "系统属性名称": "未匹配", "匹配状态": "未匹配"
}
```

- 精确命中 1.00 优先于普通相似度。
- 无精确命中时目标字段分数高者优先。
- 同分、空候选、检索抛错时按原行序，且不失败。
- 三行同目标只保留一行；无冲突原样直通。
- 上传配置已有非空 field 占用目标时，新行落选，既有映射不参与改写。

**Step 2: Run tests to verify red**

Run: `python -m pytest -q tests/test_field_mapping_conflicts.py`

Expected: FAIL because `application.field_mapping_conflicts` does not exist.

**Step 3: Implement minimal pure resolver**

实现冻结数据结构：

```python
@dataclass(frozen=True)
class FieldMappingConflictDetail:
    standard_field: str
    winner: str
    losers: tuple[str, ...]
    reason: str

@dataclass(frozen=True)
class FieldMappingConflictOutcome:
    rows: tuple[dict[str, Any], ...]
    details: tuple[FieldMappingConflictDetail, ...]
```

解析候选文本中的 `原始字段 → 标准字段(分数, 字段名)` 证据；只处理匹配成功且目标不是“未匹配”的行。复制并改写落选行，不修改调用方输入。

**Step 4: Run unit tests to verify green**

Run: `python -m pytest -q tests/test_field_mapping_conflicts.py`

Expected: PASS.

### Task 2: 接入 Adapter 原子写回路径

**Files:**
- Modify: `application/adapters/field_mapping.py`
- Modify: `application/adapters/professional.py`
- Test: `tests/test_execution_adapters.py`

**Step 1: Write failing adapter tests**

- 两个新映射撞同一标准字段：`last_mapping_data` 与 Artifact 中落选行均为“未匹配”，配置只写一个 field。
- 消息包含冲突组数、保留者、落选者与裁决依据。
- #163 场景：上传配置已有 field 占用目标，新字段撞入时落选；已有 `field/entity/sim/core` 不变。
- 同一个原始字段跨多个子规则共享映射仍全部写回。
- 裁决只复用候选检索，不产生额外专业 Agent 调用。

**Step 2: Run adapter tests to verify red**

Run: `python -m pytest -q tests/test_execution_adapters.py -k "一对一 or 占用冲突 or 跨子规则共享"`

Expected: FAIL because Adapter still writes every successful row.

**Step 3: Integrate resolver**

- `FieldMappingAdapter` 保存与批次 Runner 相同的 `candidate_retriever` 注入接缝。
- 行数校验后调用 resolver，并用裁决后的 rows 构造 `FieldMappingRow`、apply、Artifact 和 `last_mapping_data`。
- 成功消息追加：`检测到 N 组占用冲突，保留 N 个、K 个置未匹配`，随后逐组列出保留者、落选者和依据。
- `ProfessionalAgentAdapter` 保持构造参数透传兼容；Prompt 与 apply 函数不改。

**Step 4: Run focused regressions**

Run: `python -m pytest -q tests/test_field_mapping_conflicts.py tests/test_execution_adapters.py tests/test_field_mapping_apply.py tests/test_field_vocabulary.py`

Expected: PASS.

### Task 3: 同步领域与架构文档

**Files:**
- Modify: `CONTEXT.md`
- Modify: `docs/architecture/代码级设计说明.md`
- Modify: `docs/architecture/领域能力目录.md`
- Regenerate: `docs/source-code-analysis.html`

**Step 1: Document the invariant**

- 字段映射结果满足“不同原始字段不可占用同一标准字段”。
- 跨子规则同名原始字段共享不属于冲突。
- 冻结裁决顺序、Embedding 降级和 #163 既有映射占用语义。

**Step 2: Regenerate source analysis**

Run: `python scripts/generate_source_code_analysis.py`

Expected: production file inventory includes the new resolver and current line counts.

### Task 4: 验证、提交与发布

**Files:**
- Verify: all Issue #165 scoped changes

**Step 1: Run architecture and full tests**

Run: `python -m pytest -q tests/test_application_field_mapping_architecture.py tests/test_application_execution_architecture.py tests/test_documentation_architecture.py tests/test_capability_catalog_documentation.py`

Run: `python -m pytest -q`

Run: `git diff --check`

Expected: all tests pass; only existing warnings remain.

**Step 2: Commit and publish**

Commit: `fix(mapping): enforce one-to-one standard fields`

- 精确暂存 #165 文件，不包含用户的 `docs/prd/application-runtime-extraction.md` 或 `outputs/`。
- 推送分支到 GitHub 与 GitCode。
- 快进合并到 `master`，推送两个远端，以中文证据关闭 #165。
- 不创建 PR/MR。
