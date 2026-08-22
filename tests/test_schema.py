import json
from datetime import datetime, timezone
from importlib.resources import files

import pytest

from agent_beacon import LineageKey, Phase, TaskStatusEvent


def event():
    return TaskStatusEvent(
        lineage=LineageKey("p", "telegram", "a", "c", "t", "s", "r"),
        phase=Phase.ACTIVE,
        observed_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        waiting_on_worker=True,
        live_worker_count=1,
        process_active=False,
    )


def test_schema_version_round_trip():
    original = event()
    assert TaskStatusEvent.from_dict(original.to_dict()) == original
    assert original.to_dict()["schema_version"] == "1"


def test_unknown_schema_version_is_rejected():
    payload = event().to_dict()
    payload["schema_version"] = "2"
    with pytest.raises(ValueError, match="schema version"):
        TaskStatusEvent.from_dict(payload)


def test_public_schema_is_packaged_and_declares_v1():
    schema = json.loads(files("agent_beacon").joinpath("schema/task-status-event-v1.json").read_text())
    assert schema["properties"]["schema_version"]["const"] == "1"
    assert schema["additionalProperties"] is False
