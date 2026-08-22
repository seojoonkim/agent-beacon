from datetime import datetime, timezone

import pytest

from agent_beacon import LineageKey
from agent_beacon_hermes.hooks import BeaconMode, HookResult, apply_heartbeat
from agent_beacon_hermes.probes import NormalizedWorker, ProbeSnapshot


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)
LINEAGE = LineageKey("default", "telegram", "account", "chat", "topic", "session", "run")


def call(**kwargs):
    defaults = dict(
        session_key="session",
        run_session_id="session-1",
        lineage=LINEAGE,
        observed_at=NOW,
    )
    defaults.update(kwargs)
    return apply_heartbeat(**defaults)


def test_mode_contract_has_off_default_and_validates_exact_values():
    assert [mode.value for mode in BeaconMode] == ["off", "shadow", "live"]
    assert BeaconMode.parse() is BeaconMode.OFF
    assert BeaconMode.parse("shadow") is BeaconMode.SHADOW
    assert BeaconMode.parse(BeaconMode.LIVE) is BeaconMode.LIVE
    with pytest.raises(ValueError):
        BeaconMode.parse("enabled")


def test_off_returns_existing_text_without_loading_runtime(monkeypatch):
    monkeypatch.setattr("agent_beacon_hermes.hooks.import_module", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    result = call(visible_text="Existing Hermes text")
    assert result == HookResult(BeaconMode.OFF, None, "Existing Hermes text", False)


def test_shadow_computes_candidate_without_replacing_existing_text(monkeypatch):
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker", "async", "running"),))
    monkeypatch.setattr("agent_beacon_hermes.probes.probe_runtime", lambda session_key, **kwargs: snapshot)
    result = call(mode="shadow", visible_text="Existing Hermes text")
    assert result.candidate == "Active: waiting on 1 live worker."
    assert result.visible_text == "Existing Hermes text"
    assert result.supported is True


def test_live_returns_supported_candidate(monkeypatch):
    snapshot = ProbeSnapshot(workers=(NormalizedWorker("worker", "sync", "running"),))
    monkeypatch.setattr("agent_beacon_hermes.probes.probe_runtime", lambda session_key, **kwargs: snapshot)
    result = call(mode=BeaconMode.LIVE, visible_text="Unsupported waiting fallback")
    assert result.candidate == "Active: waiting on 1 live worker."
    assert result.visible_text == result.candidate
    assert result.supported is True


def test_import_drift_fails_closed_without_unsupported_waiting_claim(monkeypatch):
    monkeypatch.setattr("agent_beacon_hermes.hooks.import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
    result = call(mode="live", visible_text="Still waiting for a subagent")
    assert result == HookResult(BeaconMode.LIVE, None, None, False)


def test_probe_absence_in_shadow_preserves_existing_text(monkeypatch):
    probes = __import__("agent_beacon_hermes.probes", fromlist=["probe_runtime"])
    monkeypatch.setattr(probes, "probe_runtime", lambda session_key, **kwargs: ProbeSnapshot())
    result = call(mode="shadow", visible_text="Existing Hermes text")
    assert result.candidate is None
    assert result.visible_text == "Existing Hermes text"
    assert result.supported is False


def test_session_mismatch_fails_closed_without_probing(monkeypatch):
    monkeypatch.setattr("agent_beacon_hermes.hooks.import_module", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    result = call(session_key="other-session", mode="live", visible_text="Unsupported waiting fallback")
    assert result == HookResult(BeaconMode.LIVE, None, None, False)


def test_session_mismatch_in_shadow_preserves_existing_bytes(monkeypatch):
    monkeypatch.setattr("agent_beacon_hermes.hooks.import_module", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    result = call(session_key="other-session", mode="shadow", visible_text="Existing Hermes text")
    assert result == HookResult(BeaconMode.SHADOW, None, "Existing Hermes text", False)
