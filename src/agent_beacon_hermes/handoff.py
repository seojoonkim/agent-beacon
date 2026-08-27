"""Read-only, fail-closed projection of a Hermes restart handoff.

This projection is non-authoritative evidence only. It never writes the
sessions file and never mutates or queries the Agent Beacon ledger.
"""

from dataclasses import dataclass
from pathlib import Path
import json

from agent_beacon import LineageKey


@dataclass(frozen=True, slots=True)
class ResumeHandoffProjection:
    """Safe identity and evidence fields of one pending restart handoff."""

    lineage: LineageKey
    resume_token: str
    resume_reason: str | None


def read_resume_handoff(
    path: str | Path, lineage: LineageKey
) -> ResumeHandoffProjection | None:
    """Project the pending handoff owned by ``lineage``, or None if unproven."""
    document = _load(path)
    if not isinstance(document, dict):
        return None

    entry = document.get(lineage.session_key)
    if not isinstance(entry, dict):
        return None
    if entry.get("session_key") != lineage.session_key:
        return None
    if entry.get("resume_pending") is not True:
        return None
    if "suspended" in entry and entry["suspended"] is not False:
        return None

    handoff = entry.get("runtime_resume_handoff")
    if not isinstance(handoff, dict):
        return None
    if "auto_resume_blocked" in handoff and handoff["auto_resume_blocked"] is not False:
        return None

    token = handoff.get("resume_token")
    if not isinstance(token, str) or not token.strip():
        return None
    reason = entry.get("resume_reason")
    if reason is not None and (
        not isinstance(reason, str) or not reason.strip()
    ):
        return None

    run_id = handoff.get("agent_beacon_run_id")
    if not isinstance(run_id, str) or run_id != lineage.run_id:
        return None
    if not _lineage_claim_matches(handoff, lineage):
        return None

    return ResumeHandoffProjection(lineage=lineage, resume_token=token, resume_reason=reason)


def _load(path: str | Path) -> object | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def _lineage_claim_matches(handoff: dict, lineage: LineageKey) -> bool:
    claim = handoff.get("agent_beacon_lineage")
    if not isinstance(claim, dict):
        return False
    try:
        parsed = LineageKey.from_dict(claim)
    except (TypeError, ValueError):
        return False
    return parsed == lineage
