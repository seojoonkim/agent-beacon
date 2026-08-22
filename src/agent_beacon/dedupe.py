"""Deterministic evidence fingerprinting and bounded duplicate suppression."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json

from .event import Evidence
from .lineage import LineageKey


def fingerprint(evidence: Evidence) -> str:
    """Return a stable fingerprint excluding the observation timestamp.

    Workers are a set-like snapshot for status purposes, so adapter ordering does
    not affect identity.
    """
    payload = {
        "lineage": evidence.lineage.to_dict(),
        "phase": evidence.phase.value,
        "waiting_on_worker": evidence.waiting_on_worker,
        "workers": sorted((worker.worker_id, worker.live) for worker in evidence.workers),
        "process_active": evidence.process_active,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class _Emission:
    fingerprint: str
    phase: object
    emitted_at: datetime


class EventDeduplicator:
    def __init__(self, suppression_window: timedelta = timedelta(seconds=60)) -> None:
        if suppression_window < timedelta(0):
            raise ValueError("suppression_window cannot be negative")
        self.suppression_window = suppression_window
        self._emissions: dict[LineageKey, _Emission] = {}

    def should_emit(self, evidence: Evidence) -> bool:
        current = fingerprint(evidence)
        previous = self._emissions.get(evidence.lineage)
        duplicate = (
            previous is not None
            and previous.phase == evidence.phase
            and previous.fingerprint == current
            and evidence.observed_at - previous.emitted_at <= self.suppression_window
        )
        if duplicate:
            return False
        self._emissions[evidence.lineage] = _Emission(current, evidence.phase, evidence.observed_at)
        return True

    def forget(self, lineage: LineageKey) -> None:
        self._emissions.pop(lineage, None)
