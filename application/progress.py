"""Application 运行时使用的无界面进度实现。"""

from contracts.progress import ProgressEvent


class NullProgressSink:
    """在无界面执行环境中丢弃进度事件。"""

    async def publish(self, event: ProgressEvent) -> None:
        """保持异步接口一致且不产生副作用。"""
        return None
