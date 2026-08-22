from datetime import datetime, timedelta, timezone

import pytest

from agent_beacon.policy import time_policy


def test_elapsed_alone_never_becomes_an_eta():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = time_policy(now, elapsed=timedelta(minutes=20))
    assert result.eta is None


def test_bounded_counts_allow_eta_and_next_report_is_strictly_future():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = time_policy(now, elapsed=timedelta(seconds=40), total_count=10, completed_count=2)
    assert result.eta == timedelta(seconds=160)
    assert now < result.next_report_at <= now + timedelta(seconds=300)


def test_default_next_report_is_capped_at_300_seconds():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = time_policy(now, elapsed=timedelta(days=2))
    assert now < result.next_report_at <= now + timedelta(seconds=300)


@pytest.mark.parametrize("total,completed", [(0, 0), (2, -1), (2, 3)])
def test_invalid_bounded_counts_rejected(total, completed):
    with pytest.raises(ValueError):
        time_policy(datetime.now(timezone.utc), total_count=total, completed_count=completed)
