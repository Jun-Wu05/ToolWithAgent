"""Export only safe Run/event metadata from a local V2 acceptance SQLite archive.

Usage: python extract_fixture.py PATH_TO_SQLITE
The output is committed so rendering needs no archive or secrets.
"""
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ACCEPTED_RUN = "a946359d-ebf7-49df-a2ee-04809fe6b98e"
SUMMARY_KEYS = ("phase", "progress_status", "operation", "pipeline_stage", "error_code", "current_batch", "total_batches", "elapsed_seconds")


def export(database: Path):
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    query = """SELECT r.id, r.status, t.type AS kind, r.queued_at, r.started_at,
                      r.finished_at, r.error_code, r.error_message
               FROM runs r JOIN tasks t ON r.task_id=t.id
               WHERE t.conversation_id=(SELECT t2.conversation_id FROM tasks t2
                 JOIN runs r2 ON r2.task_id=t2.id WHERE r2.id=?)
               ORDER BY r.queued_at, r.id"""
    runs = []
    for item in connection.execute(query, (ACCEPTED_RUN,)):
        run = dict(item)
        run.pop("error_message")  # Free text is not exported.
        run["events"] = []
        for event in connection.execute("SELECT sequence,scope_type,scope_id,event_type,status,summary_json,created_at FROM run_events WHERE run_id=? ORDER BY sequence", (run["id"],)):
            safe = {key: event[key] for key in ("sequence", "scope_type", "scope_id", "event_type", "status", "created_at")}
            source = json.loads(event["summary_json"])
            safe["summary"] = {key: source[key] for key in SUMMARY_KEYS if key in source}
            run["events"].append(safe)
        runs.append(run)
    if not any(run["id"] == ACCEPTED_RUN for run in runs):
        raise RuntimeError("Accepted Run was not found")
    target = HERE / "run-fixture.json"
    target.write_text(json.dumps(runs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "run-fixture.js").write_text("window.fixtureRuns = " + json.dumps(runs, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"{len(runs)} runs, {sum(len(run['events']) for run in runs)} events")


if __name__ == "__main__":
    export(Path(sys.argv[1]))
