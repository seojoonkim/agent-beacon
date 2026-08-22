"""Injectable UTC clock used at side-effect boundaries."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
