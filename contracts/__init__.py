"""框架无关的类型契约包（Issue #87）。

Planner/Executor/Adapter 三层共享的纯类型：
- planner_models：PlanDecision / StepSpec / Artifact 类型契约
- progress：进度事件抽象（不依赖 Chainlit）
- session_facts：SessionFacts 不可变事实契约

依赖方向：application/web/agent → contracts；本包禁止导入运行时或领域实现。
"""
