"""Optional Hermes adapter for Agent Beacon."""

from .heartbeat import HeartbeatResult, heartbeat
from .handoff import ResumeHandoffProjection, read_resume_handoff
from .hooks import BeaconMode, HookResult, apply_heartbeat
from .lineage import lineage_from_session_key
from .probes import NormalizedProcess, NormalizedWorker, ProbeSnapshot, probe_runtime
from .recovery import RecoveryResult, recover_abandoned
from .shutdown import ShutdownResult, shutdown_lineage

__all__ = [
    "BeaconMode",
    "HeartbeatResult",
    "HookResult",
    "NormalizedProcess",
    "NormalizedWorker",
    "ProbeSnapshot",
    "RecoveryResult",
    "ResumeHandoffProjection",
    "ShutdownResult",
    "apply_heartbeat",
    "heartbeat",
    "lineage_from_session_key",
    "probe_runtime",
    "read_resume_handoff",
    "recover_abandoned",
    "shutdown_lineage",
]
