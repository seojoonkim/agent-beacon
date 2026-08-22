"""Pack 3: conversation-scoped new-message preemption."""

from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import LineageKey, Phase
from agent_beacon.ledger import RunLedger
from agent_beacon.store import SqliteStore

PREEMPT_NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)
PREEMPT_LATER = PREEMPT_NOW + timedelta(seconds=30)

_SCOPE = {
    "profile": "p",
    "platform": "telegram",
    "account": "a",
    "chat_id": "c",
    "topic_id": "t",
    "session_key": "s",
}


def preempt_key(run="new", **overrides):
    return LineageKey(**{**_SCOPE, **overrides}, run_id=run)


def test_preempt_pauses_announced_and_active_runs_in_the_same_conversation(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("old-announced"), PREEMPT_NOW)
        ledger.open_run(preempt_key("old-active"), PREEMPT_NOW)
        ledger.activate(preempt_key("old-active"), PREEMPT_NOW)

        paused = ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)

        assert [r.lineage.run_id for r in paused] == ["old-active", "old-announced"]
        assert all(r.phase is Phase.PAUSED for r in paused)
        assert ledger.get(preempt_key("old-announced")).phase is Phase.PAUSED
        assert ledger.get(preempt_key("old-active")).phase is Phase.PAUSED


def test_preempt_does_not_open_or_touch_the_new_lineage_itself(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("old"), PREEMPT_NOW)

        ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)

        assert [r.lineage.run_id for r in ledger.nonterminal()] == []


def test_preempt_excludes_the_new_lineage_when_it_is_already_nonterminal(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("new"), PREEMPT_NOW)
        ledger.activate(preempt_key("new"), PREEMPT_NOW)
        ledger.open_run(preempt_key("old"), PREEMPT_NOW)

        paused = ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)

        assert [r.lineage.run_id for r in paused] == ["old"]
        assert ledger.get(preempt_key("new")).phase is Phase.ACTIVE
        assert [t.to_state for t in ledger.history(preempt_key("new"))] == [
            Phase.ANNOUNCED,
            Phase.ACTIVE,
        ]


def test_preempt_leaves_the_new_lineage_untouched_when_it_is_already_terminal(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("new"), PREEMPT_NOW)
        ledger.terminate(preempt_key("new"), PREEMPT_NOW, Phase.COMPLETED)
        before = ledger.get(preempt_key("new"))

        assert ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER) == []
        assert ledger.get(preempt_key("new")) == before


@pytest.mark.parametrize(
    "field",
    ["profile", "platform", "account", "chat_id", "topic_id", "session_key"],
)
def test_preempt_isolates_runs_differing_in_any_single_scope_field(tmp_path, field):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        other = preempt_key("old", **{field: "different"})
        ledger.open_run(other, PREEMPT_NOW)
        before = ledger.get(other)

        assert ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER) == []
        assert ledger.get(other) == before
        assert [t.to_state for t in ledger.history(other)] == [Phase.ANNOUNCED]


@pytest.mark.parametrize("terminal", [Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED])
def test_preempt_leaves_terminal_runs_and_their_history_unchanged(tmp_path, terminal):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("done"), PREEMPT_NOW)
        ledger.terminate(preempt_key("done"), PREEMPT_NOW, terminal)
        before = ledger.get(preempt_key("done"))
        history_before = ledger.history(preempt_key("done"))

        assert ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER) == []
        assert ledger.get(preempt_key("done")) == before
        assert ledger.history(preempt_key("done")) == history_before


def test_preempt_is_idempotent_on_a_second_call(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("old"), PREEMPT_NOW)
        first = ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)
        history = ledger.history(preempt_key("old"))

        second = ledger.preempt_for_new_run(
            preempt_key("new"), PREEMPT_LATER + timedelta(seconds=5)
        )

        assert len(first) == 1
        assert second == []
        assert ledger.history(preempt_key("old")) == history


def test_preempt_history_records_prior_state_to_paused_exactly_once(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("ann"), PREEMPT_NOW)
        ledger.open_run(preempt_key("act"), PREEMPT_NOW)
        ledger.activate(preempt_key("act"), PREEMPT_NOW)

        ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)

        assert [
            (t.from_state, t.to_state) for t in ledger.history(preempt_key("ann"))
        ] == [(None, Phase.ANNOUNCED), (Phase.ANNOUNCED, Phase.PAUSED)]
        assert [
            (t.from_state, t.to_state) for t in ledger.history(preempt_key("act"))
        ] == [
            (None, Phase.ANNOUNCED),
            (Phase.ANNOUNCED, Phase.ACTIVE),
            (Phase.ACTIVE, Phase.PAUSED),
        ]


def test_preempt_returns_records_in_deterministic_lineage_key_order(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        for run in ("r-c", "r-a", "r-b"):
            ledger.open_run(preempt_key(run), PREEMPT_NOW)

        paused = ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)

        assert [r.lineage.run_id for r in paused] == ["r-a", "r-b", "r-c"]


def test_preempt_updated_at_is_monotonic_past_a_stalled_clock(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        opened = ledger.open_run(preempt_key("old"), PREEMPT_NOW)

        stale = PREEMPT_NOW - timedelta(seconds=10)
        paused = ledger.preempt_for_new_run(preempt_key("new"), stale)

        assert paused[0].updated_at > opened.updated_at
        assert ledger.get(preempt_key("old")).updated_at == paused[0].updated_at


def test_preempt_rejects_naive_timestamps_without_mutating_the_database(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("old"), PREEMPT_NOW)
        before = ledger.get(preempt_key("old"))
        history_before = ledger.history(preempt_key("old"))

        with pytest.raises(ValueError):
            ledger.preempt_for_new_run(preempt_key("new"), datetime(2026, 3, 1))

        assert ledger.get(preempt_key("old")) == before
        assert ledger.history(preempt_key("old")) == history_before


def test_preempt_survives_a_restart_with_paused_state_and_terminal_immutability(tmp_path):
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        ledger.open_run(preempt_key("old"), PREEMPT_NOW)
        ledger.open_run(preempt_key("done"), PREEMPT_NOW)
        ledger.terminate(preempt_key("done"), PREEMPT_NOW, Phase.COMPLETED)
        ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER)

    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        assert ledger.get(preempt_key("old")).phase is Phase.PAUSED
        assert ledger.get(preempt_key("done")).phase is Phase.COMPLETED
        assert [t.to_state for t in ledger.history(preempt_key("done"))] == [
            Phase.ANNOUNCED,
            Phase.COMPLETED,
        ]
        assert ledger.preempt_for_new_run(preempt_key("new"), PREEMPT_LATER) == []
