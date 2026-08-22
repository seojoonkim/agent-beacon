from dataclasses import FrozenInstanceError, fields

import pytest

from agent_beacon import LineageKey


def test_lineage_key_is_immutable_and_has_the_complete_seven_fields():
    key = LineageKey("default", "telegram", "acct", "chat", "topic", "session", "run")

    assert tuple(field.name for field in fields(key)) == (
        "profile", "platform", "account", "chat_id", "topic_id", "session_key", "run_id"
    )
    assert len({key, LineageKey(*key.as_tuple())}) == 1
    with pytest.raises(FrozenInstanceError):
        key.run_id = "other"


def test_lineage_rejects_empty_components():
    with pytest.raises(ValueError):
        LineageKey("default", "telegram", "", "chat", "topic", "session", "run")
