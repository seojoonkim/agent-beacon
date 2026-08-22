"""Idempotent startup closure of persisted abandoned exact runs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agent_beacon import LineageKey, Phase, StateRegistry, TaskStatusEvent
from agent_beacon.store import SqliteStore


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    event: TaskStatusEvent
    text: str


def recover_abandoned(
    store: SqliteStore,
    outcomes: Mapping[LineageKey, Phase],
    observed_at: datetime,
) -> list[RecoveryResult]:
    """Close persisted open runs named by full lineage and explicit outcome."""
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    if any(outcome not in {Phase.PAUSED, Phase.BLOCKED} for outcome in outcomes.values()):
        raise ValueError("recovery outcome must be paused or blocked")

    open_events = store.load_open()
    registry = StateRegistry(store=store)
    results: list[RecoveryResult] = []
    for open_event in open_events:
        outcome = outcomes.get(open_event.lineage)
        if outcome is None:
            continue
        event = registry.close(open_event.lineage, observed_at, phase=outcome)
        if event is None:
            continue
        phase = outcome.value.capitalize()
        results.append(
            RecoveryResult(event, f"{phase}: abandoned run closed during startup recovery.")
        )
    return results
