from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry
from agent_beacon.machine import can_transition


@pytest.mark.parametrize(
    ("source", "targets"),
    [
        (Phase.ANNOUNCED, {Phase.ACTIVE, Phase.BLOCKED, Phase.PAUSED, Phase.COMPLETED}),
        (Phase.ACTIVE, {Phase.ACTIVE, Phase.BLOCKED, Phase.PAUSED, Phase.COMPLETED}),
        (Phase.BLOCKED, set()),
        (Phase.PAUSED, set()),
        (Phase.COMPLETED, set()),
    ],
)
def test_exact_transition_matrix(source, targets):
    for target in Phase:
        assert can_transition(source, target) is (target in targets)


@pytest.mark.parametrize("closed_phase", [Phase.BLOCKED, Phase.PAUSED, Phase.COMPLETED])
def test_closed_phase_is_terminal_for_same_run(closed_phase):
    registry = StateRegistry()
    key = LineageKey("p", "telegram", "a", "c", "t", "s", "r")
    now = datetime.now(timezone.utc)
    assert registry.observe(Evidence(key, now, closed_phase)).emit

    decision = registry.observe(Evidence(key, now + timedelta(seconds=1), Phase.ACTIVE))

    assert not decision.emit
    assert decision.reason == "terminal"
    assert registry.phase(key) is closed_phase


def test_resume_requires_distinct_run_id():
    registry = StateRegistry()
    old_run = LineageKey("p", "telegram", "a", "c", "t", "s", "run-1")
    resumed_run = LineageKey("p", "telegram", "a", "c", "t", "s", "run-2")
    now = datetime.now(timezone.utc)
    assert registry.observe(Evidence(old_run, now, Phase.PAUSED)).emit

    resumed = registry.observe(Evidence(resumed_run, now + timedelta(seconds=1), Phase.ACTIVE))

    assert resumed.emit
    assert resumed.event is not None
    assert resumed.event.lineage == resumed_run
    assert registry.phase(old_run) is Phase.PAUSED
    assert registry.phase(resumed_run) is Phase.ACTIVE


def test_stale_observation_is_suppressed_without_regression():
    registry = StateRegistry()
    key = LineageKey("p", "telegram", "a", "c", "t", "s", "r")
    now = datetime.now(timezone.utc)
    assert registry.observe(Evidence(key, now, Phase.ACTIVE)).emit
    stale = registry.observe(Evidence(key, now, Phase.BLOCKED))
    assert not stale.emit
    assert stale.reason == "stale"
    assert registry.phase(key) is Phase.ACTIVE


def test_no_evidence_means_no_emit():
    decision = StateRegistry().observe(None)
    assert not decision.emit
    assert decision.event is None
    assert decision.reason == "no_evidence"
