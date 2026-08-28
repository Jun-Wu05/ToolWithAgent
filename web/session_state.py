"""兼容入口：会话运行时已迁入 Application。"""

from application.session_state import PrimaryDatasetSnapshot, SessionState

__all__ = ["PrimaryDatasetSnapshot", "SessionState"]
