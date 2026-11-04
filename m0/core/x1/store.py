"""X1 append-only evidence store (JSONL). No update/delete API by design (S-5)."""
from __future__ import annotations

import fcntl
import json
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterator


class AppendOnlyStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def append(self, kind: str, payload: Any) -> None:
        if is_dataclass(payload):
            payload = asdict(payload)
        record = json.dumps({"kind": kind, "payload": payload},
                            ensure_ascii=False, default=str) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                # The descriptor keeps its lock through close/flush. A reader
                # in another process must not parse a partially written record.
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(record)

    def read(self, kind: str | None = None) -> Iterator[dict]:
        with self._lock:
            if not self.path.exists():
                return
            with self.path.open(encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                lines = f.readlines()
        # Do not hold a process lock across yield: callers may append while
        # consuming this fixed prefix. Corrupt persistent rows still raise.
        for line in lines:
            rec = json.loads(line)
            if kind is None or rec["kind"] == kind:
                yield rec

    # Deliberately absent: update(), delete(), truncate().
