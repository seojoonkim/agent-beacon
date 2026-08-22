"""Exact-lineage shutdown closure without unsupported runtime claims."""

from dataclasses import dataclass
from datetime import datetime
import math
from numbers import Real

from agent_beacon import LineageKey, Phase, StateRegistry, TaskStatusEvent

from .probes import ProbeSnapshot


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    event: TaskStatusEvent | None
    text: str | None


def _safe_age(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return f"{numeric:g}"


def shutdown_lineage(
    registry: StateRegistry,
    lineage: LineageKey,
    observed_at: datetime,
    *,
    snapshot: ProbeSnapshot | None = None,
    progress_age_seconds: object = None,
) -> ShutdownResult:
    """Close only ``lineage`` using claims supported by the supplied snapshot."""
    stalling = bool(
        snapshot
        and any(worker.status in {"stalling", "stalled"} for worker in snapshot.workers)
    )
    phase = Phase.BLOCKED if stalling else Phase.PAUSED
    event = registry.close(lineage, observed_at, phase=phase)
    if event is None:
        return ShutdownResult(None, None)

    if stalling:
        age = _safe_age(progress_age_seconds)
        detail = f"; last progress {age} seconds ago" if age is not None else ""
        return ShutdownResult(event, f"Blocked: stalled delegation{detail}.")

    worker_count = len(snapshot.workers) if snapshot is not None else 0
    if worker_count:
        noun = "worker" if worker_count == 1 else "workers"
        text = f"Paused: shutdown interrupted {worker_count} corroborated live {noun}."
    else:
        text = "Paused: run interrupted by shutdown."
    return ShutdownResult(event, text)
