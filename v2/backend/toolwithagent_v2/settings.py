"""V2-only configuration; no Chainlit environment or data is reused."""
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    development: bool = True
    max_upload_bytes: int = 20 * 1024 * 1024
    worker_concurrency: int = 1

    @classmethod
    def from_env(cls) -> "Settings":
        default = Path(__file__).resolve().parents[3] / "tmp" / "v2-data"
        concurrency = int(os.environ.get("V2_WORKER_CONCURRENCY", "1"))
        if concurrency != 1:
            raise ValueError("V2_WORKER_CONCURRENCY must be 1")
        return cls(
            data_dir=Path(os.environ.get("V2_DATA_DIR", default)).resolve(),
            development=os.environ.get("V2_MODE", "development") == "development",
            worker_concurrency=concurrency,
        )
