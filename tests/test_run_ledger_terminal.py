from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import LineageKey, Phase
from agent_beacon.ledger import (
    RunConflictError,
    RunLedger,
    RunTransition,
    TerminalRunError,
)
from agent_beacon.store import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
MICROSECOND = timedelta(microseconds=1)


def key(run="r"):
    return LineageKey("p", "telegram", "a", "c", "t", "s", run)


def ledger_at(path):
    return RunLedger(store=SqliteStore(path))


@pytest.mark.parametrize("phase", [Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED])
def test_terminate_records_each_terminal_outcome(tmp_path, phase):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        ledger.activate(key(), NOW + timedelta(seconds=1))
        record = ledger.terminate(key(), NOW + timedelta(seconds=2), phase)
        assert record.phase is phase
        assert record.is_terminal
        assert record.updated_at == NOW + timedelta(seconds=2)
        assert ledger.get(key()) == record
        assert ledger.nonterminal() == []


def test_open_run_records_the_initial_announced_transition(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        assert ledger.history(key()) == [
            RunTransition(key(), None, Phase.ANNOUNCED, NOW),
        ]


def test_history_is_ordered_with_from_and_to_states(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        ledger.activate(key(), NOW + timedelta(seconds=1))
        ledger.activate(key(), NOW + timedelta(seconds=2))
        ledger.terminate(key(), NOW + timedelta(seconds=3), Phase.COMPLETED)
        assert ledger.history(key()) == [
            RunTransition(key(), None, Phase.ANNOUNCED, NOW),
            RunTransition(key(), Phase.ANNOUNCED, Phase.ACTIVE, NOW + timedelta(seconds=1)),
            RunTransition(key(), Phase.ACTIVE, Phase.ACTIVE, NOW + timedelta(seconds=2)),
            RunTransition(key(), Phase.ACTIVE, Phase.COMPLETED, NOW + timedelta(seconds=3)),
        ]


def test_history_is_scoped_to_its_lineage(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("a"), NOW)
        ledger.open_run(key("b"), NOW)
        ledger.terminate(key("b"), NOW + timedelta(seconds=1), Phase.PAUSED)
        assert [item.to_state for item in ledger.history(key("a"))] == [Phase.ANNOUNCED]


def test_activating_a_terminal_run_raises_terminal_run_error(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        ledger.terminate(key(), NOW + timedelta(seconds=1), Phase.COMPLETED)
        with pytest.raises(TerminalRunError):
            ledger.activate(key(), NOW + timedelta(seconds=2))


def test_terminal_run_error_is_a_run_conflict_error():
    assert issubclass(TerminalRunError, RunConflictError)


def test_a_distinct_second_terminal_state_is_rejected(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        ledger.terminate(key(), NOW + timedelta(seconds=1), Phase.BLOCKED)
        with pytest.raises(TerminalRunError):
            ledger.terminate(key(), NOW + timedelta(seconds=2), Phase.COMPLETED)
        assert ledger.get(key()).phase is Phase.BLOCKED


def test_replaying_the_same_terminal_state_is_idempotent(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        first = ledger.terminate(key(), NOW + timedelta(seconds=1), Phase.PAUSED)
        replayed = ledger.terminate(key(), NOW + timedelta(seconds=9), Phase.PAUSED)
        assert replayed == first
        assert ledger.get(key()) == first
        assert len(ledger.history(key())) == 2


def test_terminal_state_survives_restart_and_still_rejects_writes(tmp_path):
    path = tmp_path / "beacon.sqlite3"
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        ledger.terminate(key(), NOW + timedelta(seconds=1), Phase.COMPLETED)
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        assert ledger.get(key()).phase is Phase.COMPLETED
        with pytest.raises(TerminalRunError):
            ledger.activate(key(), NOW + timedelta(seconds=2))
        with pytest.raises(RunConflictError):
            ledger.open_run(key(), NOW + timedelta(seconds=3))
        assert [item.to_state for item in ledger.history(key())] == [
            Phase.ANNOUNCED,
            Phase.COMPLETED,
        ]


def test_updated_at_is_monotonic_for_equal_or_earlier_timestamps(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        same = ledger.activate(key(), NOW)
        assert same.updated_at == NOW + MICROSECOND
        earlier = ledger.activate(key(), NOW - timedelta(days=1))
        assert earlier.updated_at == NOW + 2 * MICROSECOND
        ended = ledger.terminate(key(), NOW - timedelta(days=1), Phase.COMPLETED)
        assert ended.updated_at == NOW + 3 * MICROSECOND
        assert [item.at for item in ledger.history(key())] == [
            NOW,
            NOW + MICROSECOND,
            NOW + 2 * MICROSECOND,
            NOW + 3 * MICROSECOND,
        ]


@pytest.mark.parametrize("phase", [Phase.ANNOUNCED, Phase.ACTIVE])
def test_terminate_rejects_a_nonterminal_phase(tmp_path, phase):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        with pytest.raises(ValueError):
            ledger.terminate(key(), NOW + timedelta(seconds=1), phase)
        assert ledger.get(key()).phase is Phase.ANNOUNCED
        assert len(ledger.history(key())) == 1


def test_terminate_rejects_timezone_naive_timestamps(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        with pytest.raises(ValueError):
            ledger.terminate(key(), datetime(2026, 1, 2), Phase.COMPLETED)
        assert ledger.get(key()).phase is Phase.ANNOUNCED
        assert len(ledger.history(key())) == 1


def test_failed_transitions_leave_runs_and_history_unchanged(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key(), NOW)
        terminal = ledger.terminate(key(), NOW + timedelta(seconds=1), Phase.BLOCKED)
        before = ledger.history(key())
        for call in (
            lambda: ledger.activate(key(), NOW + timedelta(seconds=5)),
            lambda: ledger.terminate(key(), NOW + timedelta(seconds=5), Phase.COMPLETED),
            lambda: ledger.open_run(key(), NOW + timedelta(seconds=5)),
        ):
            with pytest.raises(RunConflictError):
                call()
        assert ledger.get(key()) == terminal
        assert ledger.history(key()) == before


def test_history_of_an_unknown_run_is_empty(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        assert RunLedger(store=SqliteStore(tmp_path / "db2")).history(key()) == []
        assert RunLedger(store=store).history(key()) == []
