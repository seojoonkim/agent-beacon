import json
from datetime import datetime, timezone
from importlib.resources import files

import pytest

from agent_beacon import CompletionReport, LineageKey, Phase, TaskStatusEvent


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
    assert original.to_dict()["schema_version"] == "2"


def test_completed_event_round_trips_its_structured_completion_report():
    original = TaskStatusEvent(
        lineage=LineageKey("p", "telegram", "a", "c", "t", "s", "r"),
        phase=Phase.COMPLETED,
        observed_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        waiting_on_worker=False,
        live_worker_count=0,
        process_active=False,
        completion_report=CompletionReport(
            "completed", ("ran recovery",), ("ledger is clear",), ("none",)
        ),
    )

    assert TaskStatusEvent.from_dict(original.to_dict()) == original
    assert original.to_dict()["completion_report"] == {
        "outcome": "completed",
        "actions": ["ran recovery"],
        "verification": ["ledger is clear"],
        "remaining_issues": ["none"],
    }


def test_unknown_schema_version_is_rejected():
    payload = event().to_dict()
    payload["schema_version"] = "3"
    with pytest.raises(ValueError, match="schema version"):
        TaskStatusEvent.from_dict(payload)


def test_public_schemas_preserve_v1_and_declare_v2_completion_contract():
    root = files("agent_beacon").joinpath("schema")
    v1 = json.loads(root.joinpath("task-status-event-v1.json").read_text())
    v2 = json.loads(root.joinpath("task-status-event-v2.json").read_text())

    assert v1["properties"]["schema_version"]["const"] == "1"
    assert "completion_report" not in v1["properties"]
    assert v2["properties"]["schema_version"]["const"] == "2"
    assert v2["additionalProperties"] is False


def test_legacy_v1_completed_event_without_report_remains_readable():
    payload = event().to_dict()
    payload.update(schema_version="1", phase="completed")

    restored = TaskStatusEvent.from_dict(payload)

    assert restored.phase is Phase.COMPLETED
    assert restored.completion_report is None
    assert restored.to_dict() == payload


def test_legacy_v1_rejects_v2_completion_report_field():
    payload = event().to_dict()
    payload.update(
        schema_version="1",
        phase="completed",
        completion_report={
            "outcome": "completed",
            "actions": ["ran task"],
            "verification": ["checked output"],
            "remaining_issues": ["none"],
        },
    )

    with pytest.raises(ValueError, match="schema version 1"):
        TaskStatusEvent.from_dict(payload)


def test_completion_report_rejects_non_type_object_at_runtime_boundary():
    with pytest.raises(ValueError, match="CompletionReport"):
        TaskStatusEvent(
            lineage=LineageKey("p", "telegram", "a", "c", "t", "s", "r"),
            phase=Phase.COMPLETED,
            observed_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
            waiting_on_worker=False,
            live_worker_count=0,
            process_active=False,
            completion_report={},  # type: ignore[arg-type]
        )


def test_v2_schema_rejects_whitespace_only_completion_strings():
    schema = json.loads(
        files("agent_beacon").joinpath("schema/task-status-event-v2.json").read_text()
    )
    outcome = schema["properties"]["completion_report"]["properties"]["outcome"]
    assert outcome["pattern"] == r".*\S.*"
