import pytest

from agent_beacon_hermes.lineage import lineage_from_session_key


def test_full_seven_field_lineage_with_explicit_run_id():
    lineage = lineage_from_session_key(
        "agent:main:telegram:thread:-100123:77",
        profile="default",
        account="bot-primary",
        run_id="run-42",
    )
    assert lineage.as_tuple() == (
        "default", "telegram", "bot-primary", "-100123", "77",
        "agent:main:telegram:thread:-100123:77", "run-42",
    )


@pytest.mark.parametrize(
    ("key", "platform", "chat_id", "topic_id"),
    [
        ("agent:main:telegram:dm:123", "telegram", "123", "none"),
        ("agent:coder:discord:thread:456:789", "discord", "456", "789"),
        ("agent:main:telegram:thread:-100:55:user", "telegram", "-100", "55"),
    ],
)
def test_platform_chat_topic_follow_documented_hermes_shape(key, platform, chat_id, topic_id):
    lineage = lineage_from_session_key(
        key, profile="default", account="account", run_id="run"
    )
    assert (lineage.platform, lineage.chat_id, lineage.topic_id) == (
        platform, chat_id, topic_id
    )


def test_malformed_key_fails_closed():
    with pytest.raises(ValueError):
        lineage_from_session_key("telegram:123", profile="default", account="a", run_id="r")


def test_run_id_is_never_implicitly_generated():
    with pytest.raises(TypeError):
        lineage_from_session_key("agent:main:telegram:dm:123", profile="default", account="a")


def test_explicit_routing_context_overrides_ambiguous_session_key_parts():
    lineage = lineage_from_session_key(
        "agent:zeon:telegram:dm:legacy-chat:legacy-topic",
        profile="zeon",
        account="telegram:credential-fingerprint",
        run_id="session-1:4",
        platform="telegram",
        chat_id="46291309",
        topic_id="77",
    )
    assert lineage.as_tuple()[:5] == (
        "zeon", "telegram", "telegram:credential-fingerprint", "46291309", "77"
    )
