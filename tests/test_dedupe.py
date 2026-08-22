from datetime import datetime, timedelta, timezone

from agent_beacon import Evidence, LineageKey, Phase, WorkerObservation
from agent_beacon.dedupe import EventDeduplicator, fingerprint


def key():
    return LineageKey("p", "telegram", "a", "c", "t", "s", "r")


def evidence(at, phase=Phase.ACTIVE, workers=()):
    return Evidence(key(), at, phase, workers=workers)


def test_fingerprint_is_independent_of_worker_ordering():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = WorkerObservation("a", True)
    b = WorkerObservation("b", False)
    assert fingerprint(evidence(now, workers=(a, b))) == fingerprint(evidence(now, workers=(b, a)))


def test_identical_evidence_within_window_suppressed_but_phase_change_bypasses():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dedupe = EventDeduplicator(suppression_window=timedelta(seconds=60))
    first = evidence(now, workers=(WorkerObservation("a", True),))
    assert dedupe.should_emit(first)
    assert not dedupe.should_emit(evidence(now + timedelta(seconds=10), workers=first.workers))
    assert dedupe.should_emit(
        evidence(now + timedelta(seconds=11), Phase.BLOCKED, workers=first.workers)
    )
    assert dedupe.should_emit(evidence(now + timedelta(seconds=80), workers=first.workers))


def test_registry_reports_duplicate_reason():
    from agent_beacon import StateRegistry

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    registry = StateRegistry(suppression_window=timedelta(seconds=60))
    assert registry.observe(evidence(now)).emit
    decision = registry.observe(evidence(now + timedelta(seconds=1)))
    assert not decision.emit
    assert decision.reason == "duplicate"
