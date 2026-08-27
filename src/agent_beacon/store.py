"""Thread-safe SQLite event ledger and open-lineage persistence."""

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import threading
import time
from typing import Iterable, Iterator

from .event import Phase, TaskStatusEvent

# Long enough that two independent connections serialize instead of surfacing
# "database is locked" to callers.
_BUSY_TIMEOUT_SECONDS = 30.0


def _is_transient_lock_error(error: sqlite3.OperationalError) -> bool:
    error_code = getattr(error, "sqlite_errorcode", None)
    if error_code is not None and error_code & 0xFF in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }:
        return True
    return str(error).lower() in {
        "database is locked",
        "database table is locked",
        "database schema is locked",
    }


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._write_depth = 0
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, timeout=_BUSY_TIMEOUT_SECONDS
        )
        try:
            with self._connection:
                self._connection.execute(
                    f"PRAGMA busy_timeout={int(_BUSY_TIMEOUT_SECONDS * 1000)}"
                )
                deadline = time.monotonic() + _BUSY_TIMEOUT_SECONDS
                while True:
                    try:
                        self._connection.execute("PRAGMA journal_mode=WAL")
                        break
                    except sqlite3.OperationalError as error:
                        if not _is_transient_lock_error(error):
                            raise
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise
                        time.sleep(min(0.01, remaining))
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
                self._connection.execute(
                    """CREATE TABLE IF NOT EXISTS runs (
                        lineage_key TEXT PRIMARY KEY,
                        phase TEXT NOT NULL,
                        opened_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        is_terminal INTEGER NOT NULL CHECK (is_terminal IN (0, 1))
                    )"""
                )
                self._connection.execute(
                    "CREATE INDEX IF NOT EXISTS runs_nonterminal ON runs(is_terminal, lineage_key)"
                )
                self._connection.execute(
                    """CREATE TABLE IF NOT EXISTS run_transitions (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        lineage_key TEXT NOT NULL,
                        from_state TEXT,
                        to_state TEXT NOT NULL,
                        at TEXT NOT NULL
                    )"""
                )
                self._connection.execute(
                    """CREATE INDEX IF NOT EXISTS run_transitions_lineage
                       ON run_transitions(lineage_key, sequence)"""
                )
        except BaseException:
            self._connection.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialized, atomic access to the underlying connection."""
        with self._lock, self._connection:
            yield self._connection

    @contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """An explicit BEGIN IMMEDIATE write transaction on this store.

        The write lock is taken up front, so two connections racing on the same
        file serialize on the busy timeout rather than failing mid-transaction.
        Nesting is rejected deterministically and leaves the outer transaction
        untouched.
        """
        with self._lock:
            if self._write_depth:
                raise RuntimeError("write_transaction is not reentrant")
            self._connection.execute("BEGIN IMMEDIATE")
            self._write_depth = 1
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
            finally:
                self._write_depth = 0

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
