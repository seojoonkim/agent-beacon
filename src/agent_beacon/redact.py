"""Allow-list construction and defense-in-depth redaction."""

import re
from typing import Any, Mapping

from .event import WorkerObservation

_WORKER_FIELDS = frozenset({"worker_id", "live"})
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*[^\s,;]+"
)
_PROVIDER_TOKEN = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9._-]{8,}\b")


def worker_observation_from_dict(value: Mapping[str, Any]) -> WorkerObservation:
    unknown = set(value) - _WORKER_FIELDS
    missing = _WORKER_FIELDS - set(value)
    if unknown:
        raise ValueError(f"unknown WorkerObservation fields: {sorted(unknown)!r}")
    if missing:
        raise ValueError(f"missing WorkerObservation fields: {sorted(missing)!r}")
    if not isinstance(value["worker_id"], str) or type(value["live"]) is not bool:
        raise ValueError("invalid WorkerObservation field types")
    return WorkerObservation(worker_id=value["worker_id"], live=value["live"])


def redact_text(value: str) -> str:
    """Remove common secret-shaped values from otherwise allow-listed text."""
    value = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _PROVIDER_TOKEN.sub("[REDACTED]", value)
