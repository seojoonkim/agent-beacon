"""Construction of complete Beacon lineage from Hermes session keys."""

from agent_beacon import LineageKey


_NO_TOPIC = "none"


def lineage_from_session_key(
    session_key: str,
    *,
    profile: str,
    account: str,
    run_id: str,
    platform: str | None = None,
    chat_id: str | None = None,
    topic_id: str | None = None,
) -> LineageKey:
    """Parse Hermes' ``agent:<namespace>:<platform>:<chat_type>:...`` key.

    ``run_id`` is deliberately required: a reused Hermes session key must not
    inherit status from a previous agent/run binding.
    """
    if not all(isinstance(value, str) and value for value in (session_key, profile, account, run_id)):
        raise ValueError("session key and lineage context must be non-empty strings")
    parts = session_key.split(":")
    if len(parts) < 5 or parts[0] != "agent" or not parts[1] or not parts[2] or not parts[3]:
        raise ValueError("unsupported Hermes session key shape")

    parsed_platform, chat_type = parts[2], parts[3]
    routing = parts[4:]
    # Slack inserts workspace scope before chat/thread identifiers.
    if parsed_platform == "slack":
        if len(routing) < 2:
            raise ValueError("Slack session key has no chat identifier")
        routing = routing[1:]
    if not routing or not routing[0]:
        raise ValueError("Hermes session key has no chat identifier")

    parsed_chat_id = routing[0]
    # Hermes puts the effective thread/topic directly after chat_id. This is
    # positional for threaded DMs and for group/channel topic keys; any later
    # component is a participant discriminator rather than routing identity.
    parsed_topic_id = routing[1] if len(routing) > 1 else _NO_TOPIC
    effective_platform = parsed_platform if platform is None else platform
    effective_chat_id = parsed_chat_id if chat_id is None else chat_id
    effective_topic_id = parsed_topic_id if topic_id is None else topic_id
    if not all(
        isinstance(value, str) and value
        for value in (effective_platform, effective_chat_id, effective_topic_id)
    ):
        raise ValueError("explicit routing context must be non-empty strings")
    return LineageKey(
        profile,
        effective_platform,
        account,
        effective_chat_id,
        effective_topic_id,
        session_key,
        run_id,
    )
