"""
全局状态管理 - 从 chainlit_app.py 提取

本模块管理需要在多个模块间共享的全局状态。
避免在多个文件中维护重复的全局变量。
"""

# Agno 日志桥接安装标志（全局）
_agno_bridge_installed: bool = False


def is_agno_bridge_installed() -> bool:
    """检查 Agno 日志桥接是否已安装"""
    return _agno_bridge_installed


def set_agno_bridge_installed(installed: bool) -> None:
    """设置 Agno 日志桥接安装状态"""
    global _agno_bridge_installed
    _agno_bridge_installed = installed