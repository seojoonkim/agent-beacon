"""Heartbeat evidence decision and shadow/live rendering."""

from dataclasses import dataclass
from datetime import datetime

from agent_beacon import (
    Decision,
    Evidence,
    LineageKey,
    Phase,
    StateRegistry,
    WorkerObservation,
    render,
)

from .probes import ProbeSnapshot


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    decision: Decision
    candidate: str | None
    visible_text: str | None


def heartbeat(
    snapshot: ProbeSnapshot,
    lineage: LineageKey,
    observed_at: datetime,
    *,
    mode: str,
    visible_text: str | None = None,
    registry: StateRegistry | None = None,
) -> HeartbeatResult:
    """Return Beacon's decision plus candidate and mode-selected visible text."""
    if mode not in {"shadow", "live"}:
        raise ValueError("heartbeat mode must be shadow or live")
    registry = registry or StateRegistry()

    live_workers = tuple(
        WorkerObservation(worker.worker_id, True) for worker in snapshot.workers
    )
    process_active = any(process.active for process in snapshot.processes)
    if not live_workers and not process_active:
        decision = registry.observe(None)
        return HeartbeatResult(
            decision=decision,
            candidate=None,
            visible_text=visible_text if mode == "shadow" else None,
        )

    evidence = Evidence(
        lineage=lineage,
        observed_at=observed_at,
        phase=Phase.ACTIVE,
        waiting_on_worker=bool(live_workers),
        workers=live_workers,
        process_active=process_active,
    )
    decision = registry.observe(evidence)
    candidate = render(decision.event) if decision.emit and decision.event is not None else None
    selected = visible_text if mode == "shadow" else candidate
    return HeartbeatResult(decision, candidate, selected)
