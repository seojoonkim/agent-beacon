from datetime import datetime, timezone

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry, WorkerObservation, render


def key():
    return LineageKey("p", "telegram", "a", "c", "t", "s", "r")


def test_waiting_requires_live_worker_evidence():
    decision = StateRegistry().observe(
        Evidence(key(), datetime.now(timezone.utc), Phase.ACTIVE, waiting_on_worker=True)
    )
    assert not decision.emit
    assert decision.reason == "no_live_worker"


def test_no_workers_never_renders_waiting_language():
    decision = StateRegistry().observe(Evidence(key(), datetime.now(timezone.utc), Phase.ACTIVE))
    assert decision.emit
    text = render(decision.event).lower()
    assert "waiting" not in text
    assert "subagent" not in text
    assert "delegat" not in text


def test_process_only_evidence_does_not_claim_subagent():
    decision = StateRegistry().observe(
        Evidence(key(), datetime.now(timezone.utc), Phase.ACTIVE, process_active=True)
    )
    text = render(decision.event).lower()
    assert "process" in text
    assert "waiting" not in text
    assert "subagent" not in text
    assert "delegat" not in text


def test_live_worker_can_support_waiting_claim_and_render_is_deterministic():
    evidence = Evidence(
        key(), datetime(2026, 1, 2, tzinfo=timezone.utc), Phase.ACTIVE,
        waiting_on_worker=True,
        workers=(WorkerObservation("worker-1", live=True),),
    )
    event = StateRegistry().observe(evidence).event
    assert render(event) == render(event)
    assert "waiting on 1 live worker" in render(event).lower()
