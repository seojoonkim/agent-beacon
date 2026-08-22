from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry
from agent_beacon.store import SqliteStore
from agent_beacon_hermes.recovery import recover_abandoned


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def lineage(*, profile="default", chat="chat", topic="topic", session="session", run="run"):
    return LineageKey(profile, "telegram", "account", chat, topic, session, run)


def persist_open(store, key):
    assert StateRegistry(store=store).observe(Evidence(key, NOW, Phase.ANNOUNCED)).emit


def test_recovery_loads_persisted_exact_run_and_closes_explicit_outcome(tmp_path):
    paused = lineage(run="recovery-paused")
    blocked = lineage(run="recovery-blocked")
    path = tmp_path / "recovery-explicit.sqlite3"
    with SqliteStore(path) as store:
        registry = StateRegistry(store=store)
        assert registry.observe(Evidence(paused, NOW, Phase.ANNOUNCED)).emit
        assert registry.observe(Evidence(blocked, NOW, Phase.ACTIVE, process_active=True)).emit

    with SqliteStore(path) as store:
        results = recover_abandoned(
            store,
            {paused: Phase.PAUSED, blocked: Phase.BLOCKED},
            NOW + timedelta(seconds=1),
        )
        assert [(item.event.lineage, item.event.phase, item.text) for item in results] == [
            (blocked, Phase.BLOCKED, "Blocked: abandoned run closed during startup recovery."),
            (paused, Phase.PAUSED, "Paused: abandoned run closed during startup recovery."),
        ]
        assert store.load_open() == []


def test_recovery_is_idempotent_never_reopens_or_touches_terminal_rows(tmp_path):
    open_key = lineage(run="recovery-open-once")
    terminal_key = lineage(run="recovery-already-terminal")
    path = tmp_path / "recovery-idempotent.sqlite3"
    with SqliteStore(path) as store:
        registry = StateRegistry(store=store)
        assert registry.observe(Evidence(open_key, NOW, Phase.ANNOUNCED)).emit
        assert registry.observe(Evidence(terminal_key, NOW, Phase.ANNOUNCED)).emit
        assert registry.close(terminal_key, NOW + timedelta(microseconds=1), phase=Phase.COMPLETED)

        first = recover_abandoned(store, {open_key: Phase.PAUSED, terminal_key: Phase.BLOCKED}, NOW + timedelta(seconds=1))
        second = recover_abandoned(store, {open_key: Phase.BLOCKED}, NOW + timedelta(seconds=2))
        assert len(first) == 1
        assert first[0].event.lineage == open_key
        assert second == []
        restarted = StateRegistry(store=store)
        assert restarted.phase(open_key) is None
        assert restarted.phase(terminal_key) is None


def test_recovery_does_not_mix_any_lineage_component(tmp_path):
    target = lineage(run="recovery-target")
    variants = [
        lineage(profile="other-profile", run="recovery-target"),
        LineageKey("default", "discord", "account", "chat", "topic", "session", "recovery-target"),
        LineageKey("default", "telegram", "other-account", "chat", "topic", "session", "recovery-target"),
        lineage(chat="other-chat", run="recovery-target"),
        lineage(topic="other-topic", run="recovery-target"),
        lineage(session="other-session", run="recovery-target"),
        lineage(run="other-run"),
    ]
    path = tmp_path / "recovery-isolation.sqlite3"
    with SqliteStore(path) as store:
        registry = StateRegistry(store=store)
        for key in (target, *variants):
            assert registry.observe(Evidence(key, NOW, Phase.ANNOUNCED)).emit

        results = recover_abandoned(store, {target: Phase.PAUSED}, NOW + timedelta(seconds=1))
        assert [result.event.lineage for result in results] == [target]
        assert {event.lineage for event in store.load_open()} == set(variants)


def test_recovery_output_cannot_contain_raw_lineage_or_caller_strings(tmp_path):
    secret = "RAW_PROMPT_GOAL_ARGS_RESULT_PROVIDER_SECRET"
    key = LineageKey(secret, "telegram", secret, secret, secret, secret, secret)
    with SqliteStore(tmp_path / "recovery-redaction.sqlite3") as store:
        persist_open(store, key)
        result = recover_abandoned(store, {key: Phase.BLOCKED}, NOW + timedelta(seconds=1))[0]
        assert result.text == "Blocked: abandoned run closed during startup recovery."
        assert secret not in result.text


@pytest.mark.parametrize("outcome", [Phase.ANNOUNCED, Phase.ACTIVE, Phase.COMPLETED])
def test_recovery_accepts_only_explicit_paused_or_blocked_outcome(tmp_path, outcome):
    key = lineage(run=f"recovery-invalid-{outcome.value}")
    with SqliteStore(tmp_path / f"recovery-invalid-{outcome.value}.sqlite3") as store:
        persist_open(store, key)
        with pytest.raises(ValueError):
            recover_abandoned(store, {key: outcome}, NOW + timedelta(seconds=1))
        assert [event.lineage for event in store.load_open()] == [key]
