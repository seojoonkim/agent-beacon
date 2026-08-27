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
class CompletionReport:
    """Evidence-backed user-visible completion contract.

    Every field is required and non-empty so a terminal success cannot collapse
    into a bare ``completed`` flag that omits what ran or how it was checked.
    """

    outcome: str
    actions: tuple[str, ...]
    verification: tuple[str, ...]
    remaining_issues: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("outcome",):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in ("actions", "verification", "remaining_issues"):
            raw_values = getattr(self, field_name)
            if not isinstance(raw_values, (list, tuple)):
                raise ValueError(f"{field_name} must be a sequence of strings")
            values = tuple(raw_values)
            if not values or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must contain non-empty strings")
            object.__setattr__(self, field_name, values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "actions": list(self.actions),
            "verification": list(self.verification),
            "remaining_issues": list(self.remaining_issues),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompletionReport":
        expected = {"outcome", "actions", "verification", "remaining_issues"}
        if set(value) != expected:
            raise ValueError("completion_report fields must match the completion contract")
        return cls(
            outcome=value["outcome"],
            actions=value["actions"],
            verification=value["verification"],
            remaining_issues=value["remaining_issues"],
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    lineage: LineageKey
    observed_at: datetime
    phase: Phase
    waiting_on_worker: bool = False
    workers: tuple[WorkerObservation, ...] = ()
    process_active: bool = False
    completion_report: CompletionReport | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(self, "workers", tuple(self.workers))
        if self.completion_report is not None and not isinstance(
            self.completion_report, CompletionReport
        ):
            raise ValueError("completion_report must be a CompletionReport")
        if self.phase is Phase.COMPLETED and self.completion_report is None:
            raise ValueError("completed evidence requires completion_report")
        if self.phase is not Phase.COMPLETED and self.completion_report is not None:
            raise ValueError("completion_report is only valid for completed evidence")

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
    completion_report: CompletionReport | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_supported_version(self.schema_version)
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.live_worker_count < 0:
            raise ValueError("live_worker_count cannot be negative")
        if self.waiting_on_worker and self.live_worker_count == 0:
            raise ValueError("waiting_on_worker requires a live worker")
        if self.completion_report is not None and not isinstance(
            self.completion_report, CompletionReport
        ):
            raise ValueError("completion_report must be a CompletionReport")
        if self.schema_version == "1" and self.completion_report is not None:
            raise ValueError("completion_report is not valid for schema version 1")
        if (
            self.schema_version != "1"
            and self.phase is Phase.COMPLETED
            and self.completion_report is None
        ):
            raise ValueError("completed event requires completion_report")
        if self.phase is not Phase.COMPLETED and self.completion_report is not None:
            raise ValueError("completion_report is only valid for completed events")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "lineage": self.lineage.to_dict(),
            "phase": self.phase.value,
            "observed_at": self.observed_at.isoformat(),
            "waiting_on_worker": self.waiting_on_worker,
            "live_worker_count": self.live_worker_count,
            "process_active": self.process_active,
        }
        if self.completion_report is not None:
            value["completion_report"] = self.completion_report.to_dict()
        return value

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
            completion_report=(
                CompletionReport.from_dict(value["completion_report"])
                if value.get("completion_report") is not None
                else None
            ),
        )
