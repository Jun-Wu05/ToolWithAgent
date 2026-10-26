# DISCUSSIONS.md — 待讨论问题与优化方向

> 本文件存放**已提出、但尚未正式讨论定稿**的优化方向与开放问题，作为讨论排队区。
> 使用规则：
>
> - 新议题按 `D-NNN` 递增编号追加在「待讨论」下，写明提出日期、状态与关联文档。
> - 讨论定稿后：产出 ADR / PRD / Issue，然后把本条移入「已定稿归档」（保留一行结论与指向链接），不再保留全文。
> - 本文件只收未决议题，不收结论；结论的归宿是 `docs/adr/`、`docs/prd/` 或 GitHub Issue。

---

## 待讨论

### D-001: 重试机制升级——从「固定重试 N 次」到「模型自主判断 + 系统硬限制兜底」

- 提出日期：2026-09-20
- 状态：待讨论
- 关联：[ADR-0011 有界自恢复循环](docs/adr/0011-bounded-self-recovery.md)（已明确「全面 agent loop（L3）」在评估基线佐证前不放开，见其「排除的替代方案」与 agent-autonomy-evolution PRD Phase 4 门禁——本议题即重新打开该方向，需先回答门禁问题）

**目标**：将当前「固定重试 N 次」升级为「模型自主判断是否继续 + 系统硬限制兜底」。

核心循环参考 Claude Tool Use：

```text
Agent 判断下一步
→ 调用 Tool
→ Tool 返回结果
→ Agent 观察结果
→ 继续调用 Tool 或输出最终结果
```

当模型返回 `tool_use` 时继续执行工具；当模型不再调用工具并正常结束时，表示模型认为任务完成。Anthropic API 通过 `stop_reason` 区分 `tool_use`、`end_turn` 等状态。

ToolWithAgent 可改造为：

- **Tool 内部**：保留 timeout、429/5xx、少量确定性 retry。
- **Agent**：根据失败原因决定 `retry / switch_strategy / inspect_more / fallback / finish`。
- **Validator**：模型认为完成后再次检查结果；未通过则把错误反馈给 Agent 继续处理。
- **Runtime**：设置 `max_steps`、`max_tool_calls`、总耗时、同动作最大重试、用户取消等硬停止条件。

例如正则失败后，不再固定「再试一次」，而由 Agent 判断修改正则、增加样本、切换解析策略或结束。

原则：

> **模型决定「是否还值得继续、下一步做什么」；代码决定「最多允许继续多久」。**

参考：

- [Anthropic Tool Use 实现文档](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
- [Anthropic Tool Use 概览](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)

### D-002: CLAUDE.md 定位为 Claude Code 的项目级上下文说明书

- 提出日期：2026-09-20
- 状态：待讨论
- 关联：根目录现有 [CLAUDE.md](CLAUDE.md)、[AGENTS.md](AGENTS.md)、[CONTEXT.md](CONTEXT.md)

**目标**：将 `CLAUDE.md` 定位为 **Claude Code 的项目级上下文说明书**，用于统一项目开发方式，而不是系统提示词。

`CLAUDE.md` 会作为项目指令注入模型上下文，因此：

- 不能覆盖 Anthropic 的安全规则、系统限制或 deny 权限。
- 不能授权模型执行本身无权限或被禁止的操作。
- 可以约束编码风格、架构边界、测试要求、开发流程和项目 SOP。

ToolWithAgent 根目录 `CLAUDE.md` 建议补充：

- **项目定位与核心能力**：字段映射、威胁类型、枚举、日志解析、规则生成。
- **架构原则**：Frontend、Application、Agent Runtime、Tools、Knowledge、Provider 解耦。
- **开发原则**：固定流程使用 Workflow，不确定决策使用受控 Agent；业务逻辑不得直接堆入 Prompt。
- **常用命令**：启动、测试、评测、构建。
- **修改规范**：修改前检查 ADR/PRD，优先复用现有 Tool/Application，业务变更必须补测试。
- **已知约束**：SiliconFlow API 稳定性、Provider 解耦、缓存与重试策略。

同时建议增加目录级 `CLAUDE.md`：`agent/` 管 Agent/Tool/Prompt 规范，`application/` 管执行与状态，`web/` 管前端边界，`tests/` 管测试规范。

原则：

> **根目录写稳定总规则，目录级写局部规则，详细设计继续放 `docs/`。**

规则编写三原则（约束 CLAUDE.md 中每条规则的写法）：

1. **写约束不写愿望**——「不要加注释」比「写简洁的代码」更有用，模型对禁止性规则的遵守远强于建议性规则。
2. **写具体不写抽象**——「函数名用驼峰」比「遵循项目风格」更有用，模型需要明确的判断标准。
3. **写原因不写指令**——「VuePress 1.x 插件版本必须统一为 1.5.3，混用会导致运行时错误」比「注意插件版本」更有用，知道原因模型才能举一反三。

---

## 已定稿归档

（讨论定稿的议题在此保留一行结论 + 产出链接；无）
