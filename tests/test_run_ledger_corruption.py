"""Persisted rows are validated at every read boundary and fail closed."""

from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from agent_beacon import LineageKey, Phase
from agent_beacon.ledger import CorruptLedgerError, RunLedger
from agent_beacon.store import SqliteStore

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def key(run="r"):
    return LineageKey("p", "telegram", "a", "c", "t", "s", run)


def lineage_key(lineage):
    return json.dumps(lineage.to_dict(), sort_keys=True, separators=(",", ":"))


def seeded(path, phase=Phase.ANNOUNCED):
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        if phase is not Phase.ANNOUNCED:
            ledger.terminate(key(), NOW + timedelta(seconds=1), phase)


def tamper(path, **columns):
    connection = sqlite3.connect(path)
    with connection:
        assignments = ", ".join(f"{name} = ?" for name in columns)
        connection.execute(
            f"UPDATE runs SET {assignments} WHERE lineage_key = ?",
            (*columns.values(), lineage_key(key())),
        )
    connection.close()


def raw_row(path):
    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT phase, opened_at, updated_at, is_terminal FROM runs WHERE lineage_key = ?",
        (lineage_key(key()),),
    ).fetchone()
    connection.close()
    return row


TAMPERINGS = [
    pytest.param({"phase": "bogus"}, id="unknown-phase"),
    pytest.param({"is_terminal": 1}, id="terminal-flag-without-terminal-phase"),
    pytest.param({"opened_at": "2026-06-01T00:00:00"}, id="naive-opened-at"),
    pytest.param({"updated_at": "2026-06-01T00:00:00"}, id="naive-updated-at"),
    pytest.param({"opened_at": "not-a-timestamp"}, id="unparseable-opened-at"),
]


@pytest.mark.parametrize("columns", TAMPERINGS)
def test_get_fails_closed_on_a_malformed_row(tmp_path, columns):
    path = tmp_path / "db"
    seeded(path)
    tamper(path, **columns)
    before = raw_row(path)

    with SqliteStore(path) as store:
        with pytest.raises(CorruptLedgerError):
            RunLedger(store=store).get(key())

    assert raw_row(path) == before, "a malformed row must never be rewritten"


@pytest.mark.parametrize("columns", TAMPERINGS)
def test_nonterminal_fails_closed_on_a_malformed_row(tmp_path, columns):
    path = tmp_path / "db"
    seeded(path)
    tamper(path, **columns)
    before = raw_row(path)

    with SqliteStore(path) as store:
        with pytest.raises(CorruptLedgerError):
            RunLedger(store=store).nonterminal()

    assert raw_row(path) == before


def test_terminal_phase_with_a_cleared_flag_fails_closed(tmp_path):
    path = tmp_path / "db"
    seeded(path, Phase.COMPLETED)
    tamper(path, is_terminal=0)
    before = raw_row(path)

    with SqliteStore(path) as store:
        with pytest.raises(CorruptLedgerError):
            RunLedger(store=store).get(key())
        with pytest.raises(CorruptLedgerError):
            RunLedger(store=store).activate(key(), NOW + timedelta(seconds=5))

    assert raw_row(path) == before


@pytest.mark.parametrize("columns", TAMPERINGS)
def test_writes_against_a_malformed_row_fail_closed(tmp_path, columns):
    path = tmp_path / "db"
    seeded(path)
    tamper(path, **columns)
    before = raw_row(path)

    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        for call in (
            lambda: ledger.activate(key(), NOW + timedelta(seconds=5)),
            lambda: ledger.terminate(key(), NOW + timedelta(seconds=5), Phase.COMPLETED),
            lambda: ledger.preempt_for_new_run(key("new"), NOW + timedelta(seconds=5)),
            lambda: ledger.open_for_user_input(key("new"), NOW + timedelta(seconds=5)),
        ):
            with pytest.raises(CorruptLedgerError):
                call()

    assert raw_row(path) == before


def test_corrupt_ledger_error_is_not_silently_a_run_conflict():
    from agent_beacon.ledger import RunConflictError

    assert not issubclass(CorruptLedgerError, RunConflictError)
