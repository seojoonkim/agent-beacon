from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
import threading

import pytest

from agent_beacon import CompletionReport, Evidence, LineageKey, Phase, StateRegistry
from agent_beacon.store import SqliteStore


def key(run="r"):
    return LineageKey("p", "telegram", "a", "c", "t", "s", run)


def test_concurrent_first_open_reliably_enables_wal(tmp_path):
    workers = 24
    rounds = 40

    def open_store(path, ready):
        ready.wait()
        with SqliteStore(path):
            pass

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for round_number in range(rounds):
            path = tmp_path / f"brand-new-{round_number}.sqlite3"
            ready = threading.Barrier(workers)
            futures = [pool.submit(open_store, path, ready) for _ in range(workers)]
            for future in futures:
                future.result()

            with sqlite3.connect(path) as connection:
                assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_wal_initialization_does_not_mask_other_operational_errors(tmp_path, monkeypatch):
    real_connect = sqlite3.connect

    class FailingConnection:
        def __init__(self, *args, **kwargs):
            self.connection = real_connect(*args, **kwargs)

        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA journal_mode=WAL":
                raise sqlite3.OperationalError("not a lock error")
            return self.connection.execute(sql, *args, **kwargs)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    connection = FailingConnection(tmp_path / "failure.sqlite3")
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connection)

    with pytest.raises(sqlite3.OperationalError, match="not a lock error"):
        SqliteStore(tmp_path / "failure.sqlite3")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_open_lineage_survives_store_and_registry_restart(tmp_path):
    path = tmp_path / "beacon.sqlite3"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(path) as store:
        assert StateRegistry(store=store).observe(Evidence(key(), now, Phase.ANNOUNCED)).emit
    with SqliteStore(path) as store:
        assert [event.lineage for event in store.load_open()] == [key()]
        assert StateRegistry(store=store).phase(key()) is Phase.ANNOUNCED


def test_failed_terminal_append_does_not_consume_registry_state_or_retry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class FailOnceStore:
        def __init__(self):
            self.events = []
            self.fail = False

        def load_open(self):
            return []

        def append(self, event):
            if self.fail:
                self.fail = False
                raise sqlite3.OperationalError("simulated write failure")
            self.events.append(event)

        def append_many(self, events):
            self.events.extend(events)

    store = FailOnceStore()
    registry = StateRegistry(store=store)
    assert registry.observe(Evidence(key(), now, Phase.ANNOUNCED)).emit
    report = CompletionReport("completed", ("ran task",), ("checked output",), ("none",))
    completion = Evidence(
        key(), now + timedelta(seconds=1), Phase.COMPLETED, completion_report=report
    )

    store.fail = True
    with pytest.raises(sqlite3.OperationalError, match="simulated write failure"):
        registry.observe(completion)

    assert registry.phase(key()) is Phase.ANNOUNCED
    retry = registry.observe(completion)
    assert retry.emit
    assert retry.event is not None
    assert retry.event.completion_report == report


def test_shutdown_closes_every_announced_lineage_as_paused_and_is_idempotent(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(tmp_path / "db") as store:
        registry = StateRegistry(store=store)
        for index in range(3):
            assert registry.observe(Evidence(key(str(index)), now, Phase.ANNOUNCED)).emit
        closed = registry.close_all(now + timedelta(seconds=1))
        assert len(closed) == 3
        assert {event.phase for event in closed} == {Phase.PAUSED}
        assert registry.close_all(now + timedelta(seconds=2)) == []
        assert store.load_open() == []


def test_close_all_supports_each_legal_closure_outcome(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for phase in (Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED):
        with SqliteStore(tmp_path / phase.value) as store:
            registry = StateRegistry(store=store)
            registry.observe(Evidence(key(phase.value), now, Phase.ANNOUNCED))
            report = (
                CompletionReport("completed", ("closed run",), ("store checked",), ("none",))
                if phase is Phase.COMPLETED
                else None
            )
            assert registry.close_all(
                now + timedelta(seconds=1), phase=phase, completion_report=report
            )[0].phase is phase
            assert store.load_open() == []


def test_concurrent_observations_are_serialized(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(tmp_path / "db") as store:
        registry = StateRegistry(store=store)
        def observe(index):
            return registry.observe(Evidence(key(str(index)), now, Phase.ANNOUNCED)).emit
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(observe, range(40)))
        assert len(store.load_open()) == 40
