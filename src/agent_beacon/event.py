"""Typed evidence and public status event values."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .lineage import LineageKey
from .schema import SCHEMA_VERSION, require_supported_version


class Phase(str, Enum):
    ANNOUNCED = "announced"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class WorkerObservation:
    worker_id: str
    live: bool

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("worker_id must not be empty")
        if type(self.live) is not bool:
            raise ValueError("live must be a boolean")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkerObservation":
        # Untyped adapter data always crosses the strict allow-list boundary.
        from .redact import worker_observation_from_dict

        return worker_observation_from_dict(value)


@dataclass(frozen=True, slots=True)
class Evidence:
    lineage: LineageKey
    observed_at: datetime
    phase: Phase
    waiting_on_worker: bool = False
    workers: tuple[WorkerObservation, ...] = ()
    process_active: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(self, "workers", tuple(self.workers))

    @property
    def live_worker_count(self) -> int:
        return sum(worker.live for worker in self.workers)


@dataclass(frozen=True, slots=True)
class TaskStatusEvent:
    lineage: LineageKey
    phase: Phase
    observed_at: datetime
    waiting_on_worker: bool
    live_worker_count: int
    process_active: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_supported_version(self.schema_version)
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.live_worker_count < 0:
            raise ValueError("live_worker_count cannot be negative")
        if self.waiting_on_worker and self.live_worker_count == 0:
            raise ValueError("waiting_on_worker requires a live worker")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lineage": self.lineage.to_dict(),
            "phase": self.phase.value,
            "observed_at": self.observed_at.isoformat(),
            "waiting_on_worker": self.waiting_on_worker,
            "live_worker_count": self.live_worker_count,
            "process_active": self.process_active,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskStatusEvent":
        require_supported_version(value.get("schema_version"))
        return cls(
            schema_version=value["schema_version"],
            lineage=LineageKey.from_dict(value["lineage"]),
            phase=Phase(value["phase"]),
            observed_at=datetime.fromisoformat(value["observed_at"]),
            waiting_on_worker=value["waiting_on_worker"],
            live_worker_count=value["live_worker_count"],
            process_active=value["process_active"],
        )
