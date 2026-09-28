"""SQLite connection and initial V2 runtime migration."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3




def migrate(path: Path) -> None:
    """Upgrade an empty or existing V2 database to the current Alembic revision."""
    from alembic import command
    from alembic.config import Config
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    config.set_main_option("sqlalchemy.url", "sqlite:///" + path.as_posix())
    command.upgrade(config, "head")

@contextmanager
def connect(path: Path):
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        yield db
    finally:
        db.close()
