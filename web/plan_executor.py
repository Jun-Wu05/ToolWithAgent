"""兼容入口：执行运行时已迁入 Application。"""

from application.execution import ExecutionContext, PlanExecutor, StepAdapter

__all__ = ["ExecutionContext", "PlanExecutor", "StepAdapter"]
