"""框架无关的类型契约包（Issue #87）。

Planner/Executor/Adapter 三层共享的纯类型与投影：
- planner_models：PlanDecision / StepSpec / Artifact 类型契约
- progress：进度事件抽象（不依赖 Chainlit）
- session_facts：SessionFacts 会话状态投影

依赖方向：web → contracts ← agent；本包禁止 import chainlit 与 web。
"""
