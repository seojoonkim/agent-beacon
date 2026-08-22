from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry
from agent_beacon.store import SqliteStore
from agent_beacon_hermes.probes import NormalizedWorker, ProbeSnapshot
from agent_beacon_hermes.shutdown import shutdown_lineage


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def lineage(*, profile="default", chat="chat", topic="topic", session="session", run="run"):
    return LineageKey(profile, "telegram", "account", chat, topic, session, run)


def announce(registry, key):
    assert registry.observe(Evidence(key, NOW, Phase.ANNOUNCED)).emit


def test_shutdown_closes_only_exact_lineage_paused_once(tmp_path):
    target = lineage(run="shutdown-target")
    other = lineage(topic="other-topic", run="shutdown-other")
    with SqliteStore(tmp_path / "shutdown-exact.sqlite3") as store:
        registry = StateRegistry(store=store)
        announce(registry, target)
        announce(registry, other)

        result = shutdown_lineage(registry, target, NOW + timedelta(seconds=1))

        assert result.event is not None
        assert result.event.lineage == target
        assert result.event.phase is Phase.PAUSED
        assert result.text == "Paused: run interrupted by shutdown."
        assert registry.phase(other) is Phase.ANNOUNCED
        assert [event.lineage for event in store.load_open()] == [other]
        assert shutdown_lineage(registry, target, NOW + timedelta(seconds=2)).event is None


def test_shutdown_worker_claim_requires_corroborated_snapshot():
    key = lineage(run="shutdown-worker-proof")
    registry = StateRegistry()
    announce(registry, key)
    without_probe = shutdown_lineage(registry, key, NOW + timedelta(seconds=1))
    assert "worker" not in without_probe.text.lower()

    other_key = lineage(run="shutdown-worker-proof-2")
    announce(registry, other_key)
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker-1", "async", "running"),))
    with_probe = shutdown_lineage(registry, other_key, NOW + timedelta(seconds=1), snapshot=snapshot)
    assert with_probe.text == "Paused: shutdown interrupted 1 corroborated live worker."


def test_stalling_delegation_closes_blocked_with_safe_progress_age_only():
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker-1", "async", "stalling"),))

    aged = lineage(run="shutdown-stalling-aged")
    registry = StateRegistry()
    announce(registry, aged)
    result = shutdown_lineage(
        registry,
        aged,
        NOW + timedelta(seconds=1),
        snapshot=snapshot,
        progress_age_seconds=125,
    )
    assert result.event.phase is Phase.BLOCKED
    assert result.text == "Blocked: stalled delegation; last progress 125 seconds ago."

    generic = lineage(run="shutdown-stalling-generic")
    announce(registry, generic)
    result = shutdown_lineage(registry, generic, NOW + timedelta(seconds=1), snapshot=snapshot)
    assert result.event.phase is Phase.BLOCKED
    assert result.text == "Blocked: stalled delegation."


@pytest.mark.parametrize("unsafe_age", [True, -1, float("nan"), float("inf"), "9"])
def test_stalling_unsafe_progress_age_never_invents_duration(unsafe_age):
    key = lineage(run=f"shutdown-unsafe-{type(unsafe_age).__name__}-{unsafe_age!r}")
    registry = StateRegistry()
    announce(registry, key)
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker-1", "async", "stalling"),))
    result = shutdown_lineage(
        registry,
        key,
        NOW + timedelta(seconds=1),
        snapshot=snapshot,
        progress_age_seconds=unsafe_age,
    )
    assert result.text == "Blocked: stalled delegation."


def test_non_stalling_snapshot_does_not_force_blocked_or_leak_raw_strings():
    secret = "RAW_PROMPT_GOAL_ARGS_RESULT_PROVIDER_SECRET"
    key = lineage(profile=secret, chat=secret, topic=secret, session=secret, run=secret)
    registry = StateRegistry()
    announce(registry, key)
    snapshot = ProbeSnapshot(workers=(NormalizedWorker(secret, "async", "running"),))
    result = shutdown_lineage(registry, key, NOW + timedelta(seconds=1), snapshot=snapshot)
    assert result.event.phase is Phase.PAUSED
    assert result.text == "Paused: shutdown interrupted 1 corroborated live worker."
    assert secret not in result.text


def test_shutdown_rejects_naive_timestamp():
    registry = StateRegistry()
    key = lineage(run="shutdown-naive")
    announce(registry, key)
    with pytest.raises(ValueError):
        shutdown_lineage(registry, key, datetime(2026, 8, 22))
