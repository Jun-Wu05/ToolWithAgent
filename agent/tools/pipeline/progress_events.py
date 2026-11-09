"""Optional pipeline observer shared by the public headless Agent facades."""
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Callable, Iterator

from contracts.progress import PipelineErrorCode, PipelineStage, ProgressStatus

PipelineObserver = Callable[[PipelineStage, ProgressStatus, PipelineErrorCode | None], None]
_observer: ContextVar[PipelineObserver | None] = ContextVar("pipeline_progress_observer", default=None)


@contextmanager
def observe_pipeline(observer: PipelineObserver | None) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def emit_pipeline(stage: PipelineStage, status: ProgressStatus,
                  error_code: PipelineErrorCode | None = None) -> None:
    observer = _observer.get()
    if observer is not None:
        try:
            observer(stage, status, error_code)
        except Exception:
            # Progress is observational; no UI/Store outage may alter classification.
            pass
