"""Optional, lazy facade for Hermes heartbeat integration.

This module does not patch Hermes.  Gateway call sites may invoke the facade
and retain ownership of delivery.  Imports of probes and heartbeat logic are
postponed until shadow/live mode so the default off mode has no adapter cost.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from importlib import import_module
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from agent_beacon import LineageKey, StateRegistry


class BeaconMode(str, Enum):
    """Supported integration modes; disabled unless explicitly enabled."""

    OFF = "off"
    SHADOW = "shadow"
    LIVE = "live"

    @classmethod
    def parse(cls, value: "BeaconMode | str" = OFF) -> "BeaconMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Beacon mode must be one of: off, shadow, live") from exc


@dataclass(frozen=True, slots=True)
class HookResult:
    """Candidate text and the text selected for Hermes to display."""

    mode: BeaconMode
    candidate: str | None
    visible_text: str | None
    supported: bool


def apply_heartbeat(
    *,
    session_key: str,
    run_session_id: str,
    lineage: Any,
    observed_at: datetime,
    mode: BeaconMode | str = BeaconMode.OFF,
    visible_text: str | None = None,
    registry: "StateRegistry | None" = None,
    current_agent_activity: Mapping[str, Any] | None = None,
) -> HookResult:
    """Apply Beacon's optional heartbeat policy without modifying Hermes.

    Off preserves existing text and does not load adapter runtime modules.
    Shadow samples and computes a candidate but preserves existing text. Live
    returns only an evidence-supported candidate; absence or contract drift is
    fail-closed to no visible Beacon claim.
    """
    selected_mode = BeaconMode.parse(mode)
    if selected_mode is BeaconMode.OFF:
        return HookResult(selected_mode, None, visible_text, False)
    if session_key != lineage.session_key:
        selected_text = visible_text if selected_mode is BeaconMode.SHADOW else None
        return HookResult(selected_mode, None, selected_text, False)

    try:
        probes = import_module("agent_beacon_hermes.probes")
        heartbeat_module = import_module("agent_beacon_hermes.heartbeat")
        snapshot = probes.probe_runtime(
            session_key,
            run_session_id=run_session_id,
            current_agent_activity=current_agent_activity,
        )
        result = heartbeat_module.heartbeat(
            snapshot,
            lineage,
            observed_at,
            mode=selected_mode.value,
            visible_text=visible_text,
            registry=registry,
        )
        candidate = result.candidate
        supported = isinstance(candidate, str) and bool(candidate)
        selected_text = visible_text if selected_mode is BeaconMode.SHADOW else (
            candidate if supported else None
        )
        return HookResult(selected_mode, candidate if supported else None, selected_text, supported)
    except Exception:
        # Hermes is optional and its probe APIs are internal. Never turn import,
        # signature, or runtime drift into an unsupported waiting claim.
        selected_text = visible_text if selected_mode is BeaconMode.SHADOW else None
        return HookResult(selected_mode, None, selected_text, False)
