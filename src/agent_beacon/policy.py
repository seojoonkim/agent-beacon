"""Conservative time language policy: bounded arithmetic or no ETA."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class TimePolicy:
    eta: timedelta | None
    next_report_at: datetime


def time_policy(
    now: datetime,
    *,
    elapsed: timedelta | None = None,
    total_count: int | None = None,
    completed_count: int | None = None,
    max_report_seconds: int = 300,
) -> TimePolicy:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if max_report_seconds <= 0:
        raise ValueError("max_report_seconds must be positive")
    if elapsed is not None and elapsed < timedelta(0):
        raise ValueError("elapsed cannot be negative")
    if (total_count is None) != (completed_count is None):
        raise ValueError("total_count and completed_count must be provided together")

    eta = None
    if total_count is not None and completed_count is not None:
        if total_count <= 0 or completed_count < 0 or completed_count > total_count:
            raise ValueError("invalid bounded completion counts")
        if elapsed is not None and elapsed < timedelta(0):
            raise ValueError("elapsed cannot be negative")
        if elapsed is not None and completed_count > 0:
            eta = elapsed / completed_count * (total_count - completed_count)

    report_delay = timedelta(seconds=max_report_seconds)
    if eta is not None and eta > timedelta(0):
        report_delay = min(report_delay, eta)
    # A report SLA is always strictly in the future, including completed counts.
    report_delay = max(report_delay, timedelta(microseconds=1))
    return TimePolicy(eta=eta, next_report_at=now + report_delay)


def estimate_eta(
    elapsed: timedelta | None, total_count: int | None = None, completed_count: int | None = None
) -> timedelta | None:
    """Small convenience API for callers that only need the bounded ETA."""
    from datetime import timezone

    return time_policy(
        datetime.now(timezone.utc), elapsed=elapsed,
        total_count=total_count, completed_count=completed_count,
    ).eta
