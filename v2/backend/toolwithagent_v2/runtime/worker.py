"""Single-leader deterministic file-ingest worker."""
import argparse
import hashlib
import json
import threading
import time
import zipfile
from xml.etree.ElementTree import ParseError
from uuid import uuid4

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from toolwithagent_v2.infrastructure.store import Store
from toolwithagent_v2.settings import Settings


class Worker:
    def __init__(self, store: Store, worker_id: str | None = None, lease_seconds: float = 30):
        self.store = store
        self.worker_id = worker_id or str(uuid4())
        self.lease_seconds = lease_seconds

    def _validate(self, snapshot):
        key = snapshot["storage_key"]
        if not key.startswith("uploads/") or ".." in key.split("/"):
            return "file_missing"
        try:
            path = (self.store.root / key).resolve()
            if not path.is_relative_to((self.store.root / "uploads").resolve()) or not path.is_file():
                return "file_missing"
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != snapshot["sha256"]:
                return "file_hash_mismatch"
            try:
                media = snapshot["media_type"]
                if media == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                    with path.open("rb") as source:
                        workbook = load_workbook(source, read_only=True, data_only=True)
                        try:
                            for sheet in workbook.worksheets:
                                for _ in sheet.iter_rows(values_only=True):
                                    pass
                        finally:
                            workbook.close()
                elif media == "application/json":
                    json.loads(path.read_text(encoding="utf-8-sig"))
                elif media == "application/x-ndjson":
                    for line in path.read_text(encoding="utf-8-sig").splitlines():
                        if line.strip():
                            json.loads(line)
                else:
                    path.read_text(encoding="utf-8-sig")
            except (ValueError, UnicodeError, zipfile.BadZipFile, InvalidFileException, ParseError, KeyError, TypeError):
                return "invalid_file_content"
            return None
        except OSError:
            return "file_unreadable"

    def once(self) -> bool:
        claim = self.store.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if claim is None:
            return False
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(min(5, self.lease_seconds / 3)):
                if not self.store.renew(self.worker_id, claim, lease_seconds=self.lease_seconds):
                    break

        keeper = threading.Thread(target=heartbeat, daemon=True)
        keeper.start()
        try:
            error = self._validate(claim["input"])
        finally:
            stop.set()
            keeper.join()
        return self.store.finish(self.worker_id, claim, error)

    def run_forever(self, poll_seconds: float = 0.5):
        while True:
            if not self.once():
                time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = Worker(Store(Settings.from_env()))
    if args.once:
        worker.once()
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()
