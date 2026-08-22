import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import LineageKey, Phase
from agent_beacon.ledger import RunConflictError, RunLedger, UnknownRunError
from agent_beacon.store import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def key(run="r"):
    return LineageKey("p", "telegram", "a", "c", "t", "s", run)


def test_open_run_records_an_announced_run_readable_by_get(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        record = ledger.open_run(key(), NOW)
        assert record.lineage == key()
        assert record.phase is Phase.ANNOUNCED
        assert record.opened_at == NOW
        assert ledger.get(key()) == record


def test_activate_moves_an_announced_run_to_active(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        later = NOW + timedelta(seconds=5)
        record = ledger.activate(key(), later)
        assert record.phase is Phase.ACTIVE
        assert record.updated_at == later
        assert ledger.get(key()).phase is Phase.ACTIVE


def test_activating_an_unknown_run_raises(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        with pytest.raises(UnknownRunError):
            RunLedger(store=store).activate(key(), NOW)


def test_get_of_an_unknown_run_raises(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        with pytest.raises(UnknownRunError):
            RunLedger(store=store).get(key())


def test_reopening_the_same_run_raises_a_conflict(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        with pytest.raises(RunConflictError):
            ledger.open_run(key(), NOW + timedelta(seconds=1))


def test_timezone_naive_timestamps_are_rejected(tmp_path):
    naive = datetime(2026, 1, 1)
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        with pytest.raises(ValueError):
            ledger.open_run(key(), naive)
        ledger.open_run(key(), NOW)
        with pytest.raises(ValueError):
            ledger.activate(key(), naive)


def test_nonterminal_lists_open_runs_in_lineage_order(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("b"), NOW)
        ledger.open_run(key("a"), NOW)
        ledger.activate(key("a"), NOW)
        assert [record.lineage for record in ledger.nonterminal()] == [key("a"), key("b")]


def test_active_run_survives_close_and_reopen_of_the_same_path(tmp_path):
    path = tmp_path / "beacon.sqlite3"
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        ledger.activate(key(), NOW + timedelta(seconds=1))
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        record = ledger.get(key())
        assert record.phase is Phase.ACTIVE
        assert record.opened_at == NOW
        assert record.updated_at == NOW + timedelta(seconds=1)
        assert [item.lineage for item in ledger.nonterminal()] == [key()]


def test_opening_a_pre_ledger_database_retains_load_open_behaviour(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    lineage_key = json.dumps(key().to_dict(), sort_keys=True, separators=(",", ":"))
    payload = json.dumps(
        {
            "schema_version": "1",
            "lineage": key().to_dict(),
            "phase": "announced",
            "observed_at": NOW.isoformat(),
            "waiting_on_worker": False,
            "live_worker_count": 0,
            "process_active": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    legacy = sqlite3.connect(path)
    with legacy:
        legacy.execute(
            """CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                lineage_key TEXT NOT NULL,
                event_json TEXT NOT NULL
            )"""
        )
        legacy.execute(
            """CREATE TABLE current_lineages (
                lineage_key TEXT PRIMARY KEY,
                event_json TEXT NOT NULL,
                is_open INTEGER NOT NULL CHECK (is_open IN (0, 1))
            )"""
        )
        legacy.execute(
            "INSERT INTO current_lineages(lineage_key, event_json, is_open) VALUES (?, ?, 1)",
            (lineage_key, payload),
        )
    legacy.close()

    with SqliteStore(path) as store:
        assert [event.lineage for event in store.load_open()] == [key()]
        assert RunLedger(store=store).nonterminal() == []
