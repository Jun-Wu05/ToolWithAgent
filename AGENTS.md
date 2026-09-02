# Agent 指令

## Agent skills

### Issue 跟踪器

GitHub Issues（`Jun-Wu05/ToolWithAgent`，用 `gh` CLI）。见 `docs/agents/issue-tracker.md`。

### Issue 实施 SOP（worktree 隔离 + 小改动直通）

每个 issue 从 master 开短命分支、PR 合并后即删分支：开分支 → 领取协议复核 → 实施（全量 pytest 绿）→ PR（`Closes #NNN`）→ 清理。**较大改动（≥3 文件/跨模块/需分组提交/主 worktree 有相交 WIP）建独立 git worktree 隔离；小改动按判据直通**，判据表见 `docs/agents/issue-workflow.md`。

### Triage 标签

状态：needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix；类别：bug / enhancement / design-input。见 `docs/agents/triage-labels.md`。

### Domain 领域文档

根目录 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。
