"""Read-only, fail-closed Hermes sessions.json restart-handoff projection."""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry
from agent_beacon.store import SqliteStore
from agent_beacon_hermes.handoff import ResumeHandoffProjection, read_resume_handoff


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)
SESSION = "handoff-session"
RUN = "handoff-run"


def handoff_lineage(*, session=SESSION, run=RUN):
    return LineageKey("default", "telegram", "account", "chat", "topic", session, run)


def handoff_entry(**overrides):
    handoff = {
        "resume_token": "token-abc",
        "agent_beacon_run_id": RUN,
    }
    handoff.update(overrides.pop("handoff", {}))
    entry = {
        "session_key": SESSION,
        "resume_pending": True,
        "resume_reason": "restart",
        "runtime_resume_handoff": handoff,
    }
    entry.update(overrides)
    return entry


def write_sessions(tmp_path, payload, name="sessions.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_handoff_projection_reads_exact_pending_entry_for_owning_run(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry()})
    projection = read_resume_handoff(path, handoff_lineage())
    assert projection == ResumeHandoffProjection(
        lineage=handoff_lineage(), resume_token="token-abc", resume_reason="restart"
    )


def test_handoff_projection_allows_absent_resume_reason_as_none(tmp_path):
    entry = handoff_entry()
    del entry["resume_reason"]
    path = write_sessions(tmp_path, {SESSION: entry})
    assert read_resume_handoff(path, handoff_lineage()).resume_reason is None


def test_handoff_projection_returns_none_for_missing_sessions_file(tmp_path):
    assert read_resume_handoff(tmp_path / "absent.json", handoff_lineage()) is None


def test_handoff_projection_returns_none_for_directory_path_instead_of_file(tmp_path):
    assert read_resume_handoff(tmp_path, handoff_lineage()) is None


def test_handoff_projection_returns_none_for_malformed_json_bytes(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_top_level_wrapper_shape(tmp_path):
    path = write_sessions(tmp_path, {"sessions": {SESSION: handoff_entry()}})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_top_level_list_shape(tmp_path):
    path = write_sessions(tmp_path, [handoff_entry()])
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_non_mapping_entry_value(tmp_path):
    path = write_sessions(tmp_path, {SESSION: "not-an-entry"})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_mapping_key_and_embedded_session_key_mismatch(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry(session_key="other-session")})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_never_scans_other_keys_for_matching_session_key(tmp_path):
    path = write_sessions(tmp_path, {"other-key": handoff_entry()})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_resume_pending_false(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry(resume_pending=False)})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_truthy_non_bool_resume_pending(tmp_path):
    for truthy in (1, "yes", ["x"]):
        path = write_sessions(tmp_path, {SESSION: handoff_entry(resume_pending=truthy)})
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_integer_or_string_true_resume_pending(tmp_path):
    for value in (1, "true"):
        path = write_sessions(tmp_path, {SESSION: handoff_entry(resume_pending=value)})
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_missing_resume_pending_field(tmp_path):
    entry = handoff_entry()
    del entry["resume_pending"]
    path = write_sessions(tmp_path, {SESSION: entry})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_suspended_session(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry(suspended=True)})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_allows_explicitly_unsuspended_session(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry(suspended=False)})
    assert read_resume_handoff(path, handoff_lineage()).resume_token == "token-abc"


def test_handoff_projection_rejects_non_bool_suspended(tmp_path):
    for value in (1, "true", "other"):
        path = write_sessions(tmp_path, {SESSION: handoff_entry(suspended=value)})
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_non_dict_runtime_resume_handoff(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry(runtime_resume_handoff="token-abc")})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_missing_runtime_resume_handoff(tmp_path):
    entry = handoff_entry()
    del entry["runtime_resume_handoff"]
    path = write_sessions(tmp_path, {SESSION: entry})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_missing_empty_or_non_string_resume_token(tmp_path):
    for token in (None, "", 12345, {"value": "t"}):
        path = write_sessions(
            tmp_path, {SESSION: handoff_entry(handoff={"resume_token": token})}
        )
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_whitespace_only_resume_token(tmp_path):
    for token in (" ", "\t\n"):
        path = write_sessions(
            tmp_path, {SESSION: handoff_entry(handoff={"resume_token": token})}
        )
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_non_string_resume_reason(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry(resume_reason=7)})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_whitespace_only_resume_reason(tmp_path):
    for reason in (" ", "\t\n"):
        path = write_sessions(tmp_path, {SESSION: handoff_entry(resume_reason=reason)})
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_auto_resume_blocked_handoff(tmp_path):
    path = write_sessions(
        tmp_path, {SESSION: handoff_entry(handoff={"auto_resume_blocked": True})}
    )
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_non_bool_auto_resume_blocked(tmp_path):
    for value in (1, "true", "other"):
        path = write_sessions(
            tmp_path, {SESSION: handoff_entry(handoff={"auto_resume_blocked": value})}
        )
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_missing_agent_beacon_run_id(tmp_path):
    entry = handoff_entry()
    del entry["runtime_resume_handoff"]["agent_beacon_run_id"]
    path = write_sessions(tmp_path, {SESSION: entry})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_mismatched_or_non_string_agent_beacon_run_id(tmp_path):
    for run_id in ("other-run", "", None, 42):
        path = write_sessions(
            tmp_path, {SESSION: handoff_entry(handoff={"agent_beacon_run_id": run_id})}
        )
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_accepts_optional_exact_full_lineage(tmp_path):
    path = write_sessions(
        tmp_path,
        {SESSION: handoff_entry(handoff={"agent_beacon_lineage": handoff_lineage().to_dict()})},
    )
    assert read_resume_handoff(path, handoff_lineage()).lineage == handoff_lineage()


def test_handoff_projection_rejects_mismatched_optional_full_lineage(tmp_path):
    other = handoff_lineage(session=SESSION, run=RUN).to_dict() | {"chat_id": "other-chat"}
    path = write_sessions(
        tmp_path, {SESSION: handoff_entry(handoff={"agent_beacon_lineage": other})}
    )
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_rejects_malformed_optional_full_lineage(tmp_path):
    for malformed in ({"profile": "default"}, {"bogus": "x"}, "default", ["default"], {}):
        path = write_sessions(
            tmp_path, {SESSION: handoff_entry(handoff={"agent_beacon_lineage": malformed})}
        )
        assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_ignores_other_entry_sharing_the_same_resume_token(tmp_path):
    other = handoff_entry(session_key="other-session")
    path = write_sessions(tmp_path, {"other-session": other})
    assert read_resume_handoff(path, handoff_lineage()) is None


def test_handoff_projection_exposes_only_safe_identity_and_evidence_fields(tmp_path):
    secret = "sk-live-super-secret"
    path = write_sessions(
        tmp_path,
        {
            SESSION: handoff_entry(
                handoff={
                    "incomplete_goal": secret,
                    "failing_tests": [secret],
                    "prompt": secret,
                    "credentials": {"api_key": secret},
                }
            )
        },
    )
    projection = read_resume_handoff(path, handoff_lineage())
    assert {field for field in projection.__dataclass_fields__} == {
        "lineage",
        "resume_token",
        "resume_reason",
    }
    assert secret not in repr(projection)
    assert not hasattr(projection, "incomplete_goal")


def test_handoff_projection_leaves_sessions_file_byte_for_byte_unchanged(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry()})
    before = digest(path)
    assert read_resume_handoff(path, handoff_lineage()) is not None
    assert read_resume_handoff(path, handoff_lineage(run="absent-run")) is None
    assert digest(path) == before


def test_handoff_projection_leaves_sqlite_ledger_bytes_and_rows_unchanged(tmp_path):
    ledger_path = tmp_path / "handoff-ledger.sqlite3"
    key = handoff_lineage()
    with SqliteStore(ledger_path) as store:
        assert StateRegistry(store=store).observe(Evidence(key, NOW, Phase.ANNOUNCED)).emit
        before_open = [event.lineage for event in store.load_open()]
    before = digest(ledger_path)

    path = write_sessions(tmp_path, {SESSION: handoff_entry()})
    assert read_resume_handoff(path, key) is not None

    assert digest(ledger_path) == before
    with SqliteStore(ledger_path) as store:
        assert [event.lineage for event in store.load_open()] == before_open


def test_handoff_projection_accepts_string_path_argument(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry()})
    assert read_resume_handoff(str(path), handoff_lineage()).resume_token == "token-abc"


def test_handoff_projection_is_immutable_and_hashable(tmp_path):
    path = write_sessions(tmp_path, {SESSION: handoff_entry()})
    projection = read_resume_handoff(path, handoff_lineage())
    assert hash(projection) == hash(
        ResumeHandoffProjection(handoff_lineage(), "token-abc", "restart")
    )
    try:
        projection.resume_token = "mutated"
    except AttributeError:
        pass
    else:  # pragma: no cover - immutability is asserted
        raise AssertionError("projection must be immutable")
