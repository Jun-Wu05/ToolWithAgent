# Agent 指令

## Agent skills

### Issue 跟踪器

GitHub Issues（`Jun-Wu05/ToolWithAgent`，用 `gh` CLI）。见 `docs/agents/issue-tracker.md`。

### Issue 实施 SOP（worktree 隔离）

每个 issue 在独立 git worktree 中实施、PR 合并后即删：开分支 → 补环境文件 → 基线绿 → 领取协议复核 → 实施 → PR（`Closes #NNN`）→ 清理。见 `docs/agents/issue-workflow.md`。

### Triage 标签

状态：needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix；类别：bug / enhancement / design-input。见 `docs/agents/triage-labels.md`。

### Domain 领域文档

根目录 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。
