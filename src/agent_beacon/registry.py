"""Lineage-scoped evidence acceptance and sole event production."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
from typing import Protocol

from .dedupe import EventDeduplicator
from .event import Evidence, Phase, TaskStatusEvent
from .lineage import LineageKey
from .machine import can_transition


class EventStore(Protocol):
    def append(self, event: TaskStatusEvent) -> None: ...
    def append_many(self, events: tuple[TaskStatusEvent, ...]) -> None: ...
    def load_open(self) -> list[TaskStatusEvent]: ...


@dataclass(frozen=True, slots=True)
class Decision:
    emit: bool
    event: TaskStatusEvent | None = None
    reason: str | None = None


class StateRegistry:
    def __init__(
        self,
        *,
        store: EventStore | None = None,
        suppression_window: timedelta = timedelta(seconds=60),
    ) -> None:
        self._accepted: dict[LineageKey, Evidence] = {}
        self._store = store
        self._dedupe = EventDeduplicator(suppression_window)
        self._lock = threading.RLock()
        if store is not None:
            for event in store.load_open():
                self._accepted[event.lineage] = Evidence(
                    lineage=event.lineage,
                    observed_at=event.observed_at,
                    phase=event.phase,
                    waiting_on_worker=False,
                    process_active=event.process_active,
                )

    def observe(self, evidence: Evidence | None) -> Decision:
        if evidence is None:
            return Decision(False, reason="no_evidence")

        with self._lock:
            previous = self._accepted.get(evidence.lineage)
            if previous is not None:
                if previous.phase in {Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED}:
                    return Decision(False, reason="terminal")
                if evidence.observed_at <= previous.observed_at:
                    return Decision(False, reason="stale")
                if not can_transition(previous.phase, evidence.phase):
                    return Decision(False, reason="illegal_transition")

            if evidence.waiting_on_worker and evidence.live_worker_count == 0:
                return Decision(False, reason="no_live_worker")

            # Accepted observations advance monotonic state even when their
            # equivalent user-visible event is suppressed.
            self._accepted[evidence.lineage] = evidence
            if not self._dedupe.should_emit(evidence):
                return Decision(False, reason="duplicate")

            event = self._event_from_evidence(evidence)
            if self._store is not None:
                self._store.append(event)
            return Decision(True, event=event)

    @staticmethod
    def _event_from_evidence(evidence: Evidence) -> TaskStatusEvent:
        return TaskStatusEvent(
            lineage=evidence.lineage,
            phase=evidence.phase,
            observed_at=evidence.observed_at,
            waiting_on_worker=evidence.waiting_on_worker,
            live_worker_count=evidence.live_worker_count,
            process_active=evidence.process_active,
        )

    def phase(self, lineage: LineageKey) -> Phase | None:
        with self._lock:
            accepted = self._accepted.get(lineage)
            return accepted.phase if accepted else None

    def close(
        self,
        lineage: LineageKey,
        observed_at: datetime,
        *,
        phase: Phase = Phase.PAUSED,
    ) -> TaskStatusEvent | None:
        """Close one exact open lineage, returning its sole terminal event."""
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if phase not in {Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED}:
            raise ValueError("closure phase must be completed, blocked, or paused")

        with self._lock:
            previous = self._accepted.get(lineage)
            if previous is None or previous.phase in {
                Phase.COMPLETED,
                Phase.BLOCKED,
                Phase.PAUSED,
            }:
                return None
            timestamp = max(observed_at, previous.observed_at + timedelta(microseconds=1))
            evidence = Evidence(lineage=lineage, observed_at=timestamp, phase=phase)
            event = self._event_from_evidence(evidence)
            self._accepted[lineage] = evidence
            self._dedupe.forget(lineage)
            if self._store is not None:
                self._store.append(event)
            return event

    def close_all(
        self,
        observed_at: datetime,
        *,
        phase: Phase = Phase.PAUSED,
    ) -> list[TaskStatusEvent]:
        """Close every currently open lineage exactly once.

        Shutdown uses the default ``paused`` outcome. Recovery and normal
        completion may explicitly select blocked or completed.
        """
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if phase not in {Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED}:
            raise ValueError("closure phase must be completed, blocked, or paused")

        with self._lock:
            events: list[TaskStatusEvent] = []
            for lineage, previous in tuple(self._accepted.items()):
                if previous.phase in {Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED}:
                    continue
                timestamp = max(observed_at, previous.observed_at + timedelta(microseconds=1))
                evidence = Evidence(lineage=lineage, observed_at=timestamp, phase=phase)
                event = self._event_from_evidence(evidence)
                self._accepted[lineage] = evidence
                self._dedupe.forget(lineage)
                events.append(event)
            if self._store is not None and events:
                self._store.append_many(tuple(events))
            return events
