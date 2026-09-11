"""
Agent Core 模块

延迟导出主要的 Agent 和 Team 接口。

设计说明（循环 import 治理）：
  原先本文件在顶层 eager 导入 agent.core.team，而 team.py 又顶层导入
  agent.tools，agent.tools.__init__ 链上的若干 pipeline 子模块又会回头导入
  agent.core.model_config 等，每次都会触发本 __init__ 重跑，形成
  agent.tools ↔ agent.core 的循环 import。

  采用 PEP 562 模块级 __getattr__：仅在被实际访问包级属性（agent.core.xxx）
  时才延迟加载对应子模块。全仓现有代码均用「直接子模块路径」导入
  （from agent.core.team import ...），不会触发本机制；但它保留了包级 re-export
  的兼容性，同时让顶层导入阶段彻底不再互相咬合。
"""

# 显式的公开名称清单，供 __all__ 与 __getattr__、IDE 静态检查使用。
# 子模块路径已在 team.py / agent.py 中定义，这里仅声明可被包级访问。
__all__ = [
    # Agent 工具函数
    # Team
    "create_data_mapping_team",
    "create_field_mapping_agent",
    "create_threat_agent",
]

# 子模块名 → 实际定义所在模块的映射（延迟导入用）。
_LAZY_MODULES = {
    "create_data_mapping_team": "agent.core.team",
    "create_field_mapping_agent": "agent.core.team",
    "create_threat_agent": "agent.core.team",
}


def __getattr__(name):
    """PEP 562：访问 agent.core.<name> 时按需从对应子模块加载。

    打断循环 import：顶层导入 agent.tools 时不会再触发 agent.core.team 的
    eager 加载，因为 __init__ 不再在模块级别执行任何子模块导入。
    """
    module_path = _LAZY_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module 'agent.core' has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value  # 缓存，后续访问直接命中
    return value
