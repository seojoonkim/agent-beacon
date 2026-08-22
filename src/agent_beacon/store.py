"""Thread-safe SQLite event ledger and open-lineage persistence."""

from pathlib import Path
import json
import sqlite3
import threading
from typing import Iterable

from .event import Phase, TaskStatusEvent


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    lineage_key TEXT NOT NULL,
                    event_json TEXT NOT NULL
                )"""
            )
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS current_lineages (
                    lineage_key TEXT PRIMARY KEY,
                    event_json TEXT NOT NULL,
                    is_open INTEGER NOT NULL CHECK (is_open IN (0, 1))
                )"""
            )

    @staticmethod
    def _key(event: TaskStatusEvent) -> str:
        return json.dumps(event.lineage.to_dict(), sort_keys=True, separators=(",", ":"))

    def append(self, event: TaskStatusEvent) -> None:
        payload = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
        lineage_key = self._key(event)
        is_open = int(event.phase not in {Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED})
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO events(lineage_key, event_json) VALUES (?, ?)",
                (lineage_key, payload),
            )
            self._connection.execute(
                """INSERT INTO current_lineages(lineage_key, event_json, is_open)
                   VALUES (?, ?, ?)
                   ON CONFLICT(lineage_key) DO UPDATE SET
                     event_json=excluded.event_json, is_open=excluded.is_open""",
                (lineage_key, payload, is_open),
            )

    def append_many(self, events: Iterable[TaskStatusEvent]) -> None:
        events = tuple(events)
        with self._lock, self._connection:
            for event in events:
                payload = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
                lineage_key = self._key(event)
                is_open = int(event.phase not in {Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED})
                self._connection.execute(
                    "INSERT INTO events(lineage_key, event_json) VALUES (?, ?)",
                    (lineage_key, payload),
                )
                self._connection.execute(
                    """INSERT INTO current_lineages(lineage_key, event_json, is_open)
                       VALUES (?, ?, ?)
                       ON CONFLICT(lineage_key) DO UPDATE SET
                         event_json=excluded.event_json, is_open=excluded.is_open""",
                    (lineage_key, payload, is_open),
                )

    def load_open(self) -> list[TaskStatusEvent]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT event_json FROM current_lineages WHERE is_open = 1 ORDER BY lineage_key"
            ).fetchall()
        return [TaskStatusEvent.from_dict(json.loads(row[0])) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
