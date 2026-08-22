from datetime import datetime, timezone

import pytest

from agent_beacon import LineageKey, StateRegistry
from agent_beacon_hermes.heartbeat import heartbeat
from agent_beacon_hermes.probes import NormalizedProcess, NormalizedWorker, ProbeSnapshot


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def lineage(run="run"):
    return LineageKey("default", "telegram", "account", "chat", "topic", "session", run)


def test_no_evidence_has_no_beacon_text():
    result = heartbeat(ProbeSnapshot(), lineage(), NOW, mode="live", visible_text="Hermes fallback")
    assert result.candidate is None
    assert result.visible_text is None
    assert result.decision.emit is False
    assert result.decision.reason == "no_evidence"


def test_live_worker_has_deterministic_supported_active_text():
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker-1", "async", "running"),))
    result = heartbeat(snapshot, lineage(), NOW, mode="live")
    assert result.decision.emit is True
    assert result.candidate == "Active: waiting on 1 live worker."
    assert result.visible_text == result.candidate


def test_process_only_never_claims_waiting_subagent_or_delegation():
    snapshot = ProbeSnapshot(processes=(NormalizedProcess("proc-1", True),))
    result = heartbeat(snapshot, lineage(), NOW, mode="live")
    assert result.candidate == "Active: background process active."
    assert not any(word in result.candidate.lower() for word in ("waiting", "subagent", "delegation"))


def test_shadow_returns_candidate_and_decision_without_replacing_visible_text():
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker-1", "sync", "running"),))
    result = heartbeat(snapshot, lineage(), NOW, mode="shadow", visible_text="Existing Hermes text")
    assert result.decision.emit is True
    assert result.candidate == "Active: waiting on 1 live worker."
    assert result.visible_text == "Existing Hermes text"


def test_stalling_remains_active_evidence_not_blocked_terminal_mapping():
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker-1", "async", "stalling"),))
    result = heartbeat(snapshot, lineage(), NOW, mode="live")
    assert result.decision.event.phase.value == "active"
    assert result.candidate.startswith("Active:")


def test_unsupported_mode_rejected():
    with pytest.raises(ValueError):
        heartbeat(ProbeSnapshot(), lineage(), NOW, mode="off")


def test_registry_can_be_supplied_for_stateful_decisions():
    registry = StateRegistry()
    snapshot = ProbeSnapshot(processes=(NormalizedProcess("proc", True),))
    assert heartbeat(snapshot, lineage(), NOW, mode="live", registry=registry).decision.emit
