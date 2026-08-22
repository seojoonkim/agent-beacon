"""Atomic `open_for_user_input`: pause the conversation, open the newcomer."""

from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import LineageKey, Phase
from agent_beacon.ledger import RunConflictError, RunLedger
from agent_beacon.store import SqliteStore

NOW = datetime(2026, 4, 1, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=30)

_SCOPE = {
    "profile": "p",
    "platform": "telegram",
    "account": "a",
    "chat_id": "c",
    "topic_id": "t",
    "session_key": "s",
}


def key(run="new", **overrides):
    return LineageKey(**{**_SCOPE, **overrides}, run_id=run)


def test_opening_pauses_prior_runs_and_announces_the_incoming_run(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("old-announced"), NOW)
        ledger.open_run(key("old-active"), NOW)
        ledger.activate(key("old-active"), NOW)

        result = ledger.open_for_user_input(key("new"), LATER)

        assert result.opened.lineage == key("new")
        assert result.opened.phase is Phase.ANNOUNCED
        assert result.opened.opened_at == LATER
        assert [r.lineage.run_id for r in result.preempted] == [
            "old-active",
            "old-announced",
        ]
        assert all(r.phase is Phase.PAUSED for r in result.preempted)
        assert [r.lineage.run_id for r in ledger.nonterminal()] == ["new"]


def test_opening_appends_exactly_one_pause_transition_per_prior_run(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("ann"), NOW)
        ledger.open_run(key("act"), NOW)
        ledger.activate(key("act"), NOW)

        ledger.open_for_user_input(key("new"), LATER)

        assert [
            (t.from_state, t.to_state) for t in ledger.history(key("ann"))
        ] == [(None, Phase.ANNOUNCED), (Phase.ANNOUNCED, Phase.PAUSED)]
        assert [
            (t.from_state, t.to_state) for t in ledger.history(key("act"))
        ] == [
            (None, Phase.ANNOUNCED),
            (Phase.ANNOUNCED, Phase.ACTIVE),
            (Phase.ACTIVE, Phase.PAUSED),
        ]
        assert [
            (t.from_state, t.to_state) for t in ledger.history(key("new"))
        ] == [(None, Phase.ANNOUNCED)]


def test_opening_rolls_back_every_pause_when_the_incoming_run_exists(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("old"), NOW)
        ledger.open_run(key("new"), NOW)
        ledger.activate(key("new"), NOW)
        before = ledger.get(key("old"))
        history_before = ledger.history(key("old"))
        new_before = ledger.get(key("new"))

        with pytest.raises(RunConflictError):
            ledger.open_for_user_input(key("new"), LATER)

        assert ledger.get(key("old")) == before
        assert ledger.history(key("old")) == history_before
        assert ledger.get(key("new")) == new_before
        assert [t.to_state for t in ledger.history(key("new"))] == [
            Phase.ANNOUNCED,
            Phase.ACTIVE,
        ]


@pytest.mark.parametrize(
    "field",
    ["profile", "platform", "account", "chat_id", "topic_id", "session_key"],
)
def test_opening_isolates_runs_differing_in_any_single_scope_field(tmp_path, field):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        other = key("old", **{field: "different"})
        ledger.open_run(other, NOW)
        before = ledger.get(other)

        result = ledger.open_for_user_input(key("new"), LATER)

        assert result.preempted == ()
        assert ledger.get(other) == before
        assert [t.to_state for t in ledger.history(other)] == [Phase.ANNOUNCED]


def test_opening_never_pauses_a_prior_row_sharing_the_incoming_run_id(tmp_path):
    """A same-run_id row in a *different* scope is out of scope; the same
    scope and run_id is the incoming run itself and would conflict."""
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        elsewhere = key("new", chat_id="other-chat")
        ledger.open_run(elsewhere, NOW)
        ledger.open_run(key("old"), NOW)

        result = ledger.open_for_user_input(key("new"), LATER)

        assert [r.lineage.run_id for r in result.preempted] == ["old"]
        assert ledger.get(elsewhere).phase is Phase.ANNOUNCED


def test_opening_leaves_terminal_prior_runs_untouched(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("done"), NOW)
        ledger.terminate(key("done"), NOW, Phase.COMPLETED)
        before = ledger.get(key("done"))
        history_before = ledger.history(key("done"))

        result = ledger.open_for_user_input(key("new"), LATER)

        assert result.preempted == ()
        assert ledger.get(key("done")) == before
        assert ledger.history(key("done")) == history_before


def test_opening_rejects_timezone_naive_timestamps_without_mutating_anything(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("old"), NOW)
        before = ledger.get(key("old"))

        with pytest.raises(ValueError):
            ledger.open_for_user_input(key("new"), datetime(2026, 4, 1))

        assert ledger.get(key("old")) == before
        assert ledger.nonterminal() == [before]


def test_opening_keeps_pause_timestamps_monotonic_past_a_stalled_clock(tmp_path):
    with SqliteStore(tmp_path / "db") as store:
        ledger = RunLedger(store=store)
        opened = ledger.open_run(key("old"), NOW)

        result = ledger.open_for_user_input(key("new"), NOW - timedelta(seconds=10))

        assert result.preempted[0].updated_at > opened.updated_at
        assert ledger.get(key("old")).updated_at == result.preempted[0].updated_at


def test_opening_survives_a_restart(tmp_path):
    path = tmp_path / "db"
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        ledger.open_run(key("old"), NOW)
        ledger.open_for_user_input(key("new"), LATER)
    with SqliteStore(path) as store:
        ledger = RunLedger(store=store)
        assert ledger.get(key("old")).phase is Phase.PAUSED
        assert ledger.get(key("new")).phase is Phase.ANNOUNCED
