"""Cross-connection durability: two writers, one coherent ledger.

Every test here opens two independent SqliteStore connections on the same
temp file and releases both threads from a barrier, so the interleaving is
real rather than simulated.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
import threading

import pytest

from agent_beacon import LineageKey, Phase
from agent_beacon.ledger import (
    RunConflictError,
    RunLedger,
    TerminalRunError,
)
from agent_beacon.store import SqliteStore

NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=30)

_SCOPE = {
    "profile": "p",
    "platform": "telegram",
    "account": "a",
    "chat_id": "c",
    "topic_id": "t",
    "session_key": "s",
}


def key(run="r", **overrides):
    return LineageKey(**{**_SCOPE, **overrides}, run_id=run)


def race(path, first, second):
    """Run two ledger calls on separate connections, released together."""
    barrier = threading.Barrier(2)

    def run(call):
        with SqliteStore(path) as store:
            ledger = RunLedger(store=store)
            barrier.wait(timeout=30)
            try:
                return call(ledger)
            except Exception as error:  # returned for assertion, not swallowed
                return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, first), pool.submit(run, second)]
        return [future.result(timeout=30) for future in futures]


def assert_coherent(ledger, lineage):
    """History must be one unbroken chain ending at the persisted phase."""
    history = ledger.history(lineage)
    assert history, f"no history for {lineage.run_id}"
    assert history[0].from_state is None
    for previous, item in zip(history, history[1:]):
        assert item.from_state is previous.to_state
    assert history[-1].to_state is ledger.get(lineage).phase
    return history


def assert_no_lock_errors(results):
    assert not [r for r in results if isinstance(r, sqlite3.Error)], results


def test_terminate_versus_terminate_yields_one_winner_and_no_split_history(tmp_path):
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        RunLedger(store=store).open_run(key(), NOW)

    results = race(
        path,
        lambda ledger: ledger.terminate(key(), LATER, Phase.COMPLETED),
        lambda ledger: ledger.terminate(key(), LATER, Phase.BLOCKED),
    )
    assert_no_lock_errors(results)

    losers = [r for r in results if isinstance(r, Exception)]
    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], TerminalRunError)

    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        history = assert_coherent(ledger, key())
        assert ledger.get(key()).phase is winners[0].phase
        assert [item.to_state for item in history] == [
            Phase.ANNOUNCED,
            winners[0].phase,
        ]


def test_activate_versus_terminate_never_records_a_post_terminal_transition(tmp_path):
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        RunLedger(store=store).open_run(key(), NOW)

    results = race(
        path,
        lambda ledger: ledger.activate(key(), LATER),
        lambda ledger: ledger.terminate(key(), LATER, Phase.COMPLETED),
    )
    assert_no_lock_errors(results)

    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        history = assert_coherent(ledger, key())
        terminal = [i for i, item in enumerate(history) if item.to_state is Phase.COMPLETED]
        assert len(terminal) == 1
        assert terminal[0] == len(history) - 1, "a write landed after the terminal one"
        assert ledger.get(key()).phase is Phase.COMPLETED
    failures = [r for r in results if isinstance(r, Exception)]
    assert all(isinstance(error, RunConflictError) for error in failures)


def test_concurrent_openings_pause_the_shared_prior_run_exactly_once(tmp_path):
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        RunLedger(store=store).open_run(key("old"), NOW)

    results = race(
        path,
        lambda ledger: ledger.open_for_user_input(key("new-a"), LATER),
        lambda ledger: ledger.open_for_user_input(key("new-b"), LATER),
    )
    assert_no_lock_errors(results)
    assert not [r for r in results if isinstance(r, Exception)], results

    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        old_history = assert_coherent(ledger, key("old"))
        assert [item.to_state for item in old_history] == [
            Phase.ANNOUNCED,
            Phase.PAUSED,
        ]
        # "old" was paused by exactly one of the two openings.
        assert sum(
            1
            for result in results
            for record in result.preempted
            if record.lineage.run_id == "old"
        ) == 1
        for run in ("new-a", "new-b"):
            assert_coherent(ledger, key(run))
        # The later opening supersedes the earlier one; exactly one survives.
        assert len(ledger.nonterminal()) == 1


def test_concurrent_preemption_pauses_a_prior_run_exactly_once(tmp_path):
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        RunLedger(store=store).open_run(key("old"), NOW)

    results = race(
        path,
        lambda ledger: ledger.preempt_for_new_run(key("new-a"), LATER),
        lambda ledger: ledger.preempt_for_new_run(key("new-b"), LATER),
    )
    assert_no_lock_errors(results)
    assert sum(len(result) for result in results) == 1

    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        assert [item.to_state for item in assert_coherent(ledger, key("old"))] == [
            Phase.ANNOUNCED,
            Phase.PAUSED,
        ]


def test_a_stale_guarded_update_appends_no_history(tmp_path):
    """A losing writer must not leave a transition behind."""
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        RunLedger(store=store).open_run(key(), NOW)

    race(
        path,
        lambda ledger: ledger.terminate(key(), LATER, Phase.PAUSED),
        lambda ledger: ledger.terminate(key(), LATER, Phase.PAUSED),
    )

    with SqliteStore(path) as store:
        # Replay of the same outcome is idempotent, so still exactly two rows.
        assert len(RunLedger(store=store).history(key())) == 2


def test_write_transactions_reject_nested_use_deterministically(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        with store.write_transaction():
            with pytest.raises(RuntimeError):
                with store.write_transaction():
                    pass
        # The outer transaction still commits cleanly and the store stays usable.
        with store.write_transaction() as connection:
            assert connection.execute("SELECT 1").fetchone() == (1,)
