"""Fail-closed, lazy Hermes runtime probes and allow-list normalization."""

from dataclasses import dataclass
from typing import Any, Mapping


_LIVE_ASYNC_STATUSES = frozenset({"running", "stalling", "finalizing"})
_LIVE_SYNC_STATUSES = frozenset({"running", "stalling", "finalizing", "active"})


@dataclass(frozen=True, slots=True)
class NormalizedWorker:
    worker_id: str
    source: str
    status: str


@dataclass(frozen=True, slots=True)
class NormalizedProcess:
    process_id: str
    active: bool


@dataclass(frozen=True, slots=True)
class ProbeSnapshot:
    workers: tuple[NormalizedWorker, ...] = ()
    processes: tuple[NormalizedProcess, ...] = ()


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("probe record is not a mapping")
    return value


def probe_runtime(
    session_key: str,
    *,
    run_session_id: str,
    current_agent_activity: Mapping[str, Any] | None = None,
) -> ProbeSnapshot:
    """Sample supported Hermes registries for exactly ``session_key``.

    Synchronous subagent registries are process-global and expose no owning
    session, so they are never accepted as lineage evidence. The gateway may
    instead pass the current turn's own activity snapshot; only an active
    ``delegate_task`` tool is normalized as synchronous-worker evidence.

    Any import, API, or shape drift invalidates the whole snapshot. Partial
    evidence could combine observations from different instants and is not
    sufficient for a user-visible claim.
    """
    try:
        if not isinstance(run_session_id, str) or not run_session_id:
            raise ValueError("run_session_id must be a non-empty string")
        from tools.async_delegation import has_live_for_session, list_async_delegations
        async_live = has_live_for_session(session_key=session_key)
        async_records = list_async_delegations()
        if type(async_live) is not bool:
            raise TypeError("liveness predicate did not return bool")
        if not isinstance(async_records, (list, tuple)):
            raise TypeError("registry snapshot did not return a sequence")

        workers: list[NormalizedWorker] = []
        if async_live:
            for raw in async_records:
                record = _mapping(raw)
                status = record.get("status")
                if (
                    record.get("session_key") != session_key
                    or record.get("parent_session_id") != run_session_id
                    or status not in _LIVE_ASYNC_STATUSES
                ):
                    continue
                worker_id = record.get("delegation_id")
                if not isinstance(worker_id, str) or not worker_id:
                    raise TypeError("async record has no delegation id")
                workers.append(NormalizedWorker(worker_id, "async", status))

        if current_agent_activity is not None:
            activity = _mapping(current_agent_activity)
            if activity.get("current_tool") == "delegate_task":
                workers.append(
                    NormalizedWorker("current-turn-delegate", "sync", "running")
                )

        # Hermes' public process snapshot is scoped to the gateway session but
        # does not expose the owning run session. Process evidence therefore
        # cannot satisfy Beacon's exact-current-run contract and is omitted.
        return ProbeSnapshot(tuple(workers), ())
    except Exception:
        # Hermes is optional and these are internal APIs. Any drift or runtime
        # failure means no evidence, never a best-effort user-visible claim.
        return ProbeSnapshot()
