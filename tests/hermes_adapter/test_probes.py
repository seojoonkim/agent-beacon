import builtins
import sys
from types import ModuleType, SimpleNamespace

from agent_beacon_hermes.probes import ProbeSnapshot, probe_runtime


SESSION = "agent:main:telegram:thread:-100:77"
RUN_SESSION = "session-1"


def install_fake_hermes(monkeypatch, *, async_records=(), sync_records=(), processes=(), live=True, active=True):
    tools = ModuleType("tools")
    async_mod = ModuleType("tools.async_delegation")
    async_mod.has_live_for_session = lambda **kwargs: live
    async_mod.list_async_delegations = lambda: list(async_records)
    delegate_mod = ModuleType("tools.delegate_tool")
    delegate_mod.list_active_subagents = lambda: list(sync_records)
    process_mod = ModuleType("tools.process_registry")
    process_mod.process_registry = SimpleNamespace(
        has_active_for_session=lambda key: active,
        list_sessions=lambda **kwargs: list(processes),
    )
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.async_delegation", async_mod)
    monkeypatch.setitem(sys.modules, "tools.delegate_tool", delegate_mod)
    monkeypatch.setitem(sys.modules, "tools.process_registry", process_mod)


def test_async_accepts_only_exact_session_run_and_live_statuses(monkeypatch):
    install_fake_hermes(monkeypatch, async_records=[
        {"delegation_id": "run", "session_key": SESSION, "origin_session_id": "", "parent_session_id": RUN_SESSION, "status": "running", "goal": "secret"},
        {"delegation_id": "stall", "session_key": SESSION, "origin_session_id": "", "parent_session_id": RUN_SESSION, "status": "stalling"},
        {"delegation_id": "final", "session_key": SESSION, "origin_session_id": "", "parent_session_id": RUN_SESSION, "status": "finalizing"},
        {"delegation_id": "done", "session_key": SESSION, "origin_session_id": "", "parent_session_id": RUN_SESSION, "status": "completed"},
        {"delegation_id": "old", "session_key": SESSION, "origin_session_id": "", "parent_session_id": "session-0", "status": "running"},
        {"delegation_id": "other", "session_key": SESSION + "x", "origin_session_id": "", "parent_session_id": RUN_SESSION, "status": "running"},
    ], active=False)
    snapshot = probe_runtime(SESSION, run_session_id=RUN_SESSION)
    assert [(w.worker_id, w.source, w.status) for w in snapshot.workers] == [
        ("run", "async", "running"),
        ("stall", "async", "stalling"),
        ("final", "async", "finalizing"),
    ]
    assert snapshot.workers[1].status == "stalling"
    assert all(not hasattr(w, "goal") for w in snapshot.workers)


def test_sync_worker_is_allow_list_normalized_and_processes_fail_closed(monkeypatch):
    install_fake_hermes(
        monkeypatch,
        sync_records=[{"subagent_id": "sync-1", "status": "running", "goal": "secret", "args": "secret"}],
        processes=[
            SimpleNamespace(id="proc-1", session_key=SESSION, parent_session_id=RUN_SESSION, exited=False, command="secret", result="secret"),
            SimpleNamespace(id="old-proc", session_key=SESSION, parent_session_id="session-0", exited=False),
        ],
        live=False,
    )
    snapshot = probe_runtime(
        SESSION,
        run_session_id=RUN_SESSION,
        current_agent_activity={"current_tool": "delegate_task"},
    )
    assert [(w.worker_id, w.source, w.status) for w in snapshot.workers] == [("current-turn-delegate", "sync", "running")]
    assert snapshot.processes == ()
    forbidden = {"goal", "prompt", "args", "results", "result", "command"}
    assert forbidden.isdisjoint(snapshot.workers[0].__dataclass_fields__)



def test_global_sync_snapshot_is_never_used_as_lineage_evidence(monkeypatch):
    install_fake_hermes(monkeypatch, sync_records=[{"subagent_id": "other-chat", "status": "running"}], live=False, active=False)
    assert probe_runtime(SESSION, run_session_id=RUN_SESSION) == ProbeSnapshot()


def test_exact_turn_activity_is_the_only_sync_worker_evidence(monkeypatch):
    install_fake_hermes(monkeypatch, live=False, active=False)
    snapshot = probe_runtime(SESSION, run_session_id=RUN_SESSION, current_agent_activity={"current_tool": "delegate_task"})
    assert [(w.worker_id, w.source, w.status) for w in snapshot.workers] == [("current-turn-delegate", "sync", "running")]


def test_lazy_importerror_degrades_to_empty_evidence(monkeypatch):
    real_import = builtins.__import__
    def fail_tools(name, *args, **kwargs):
        if name.startswith("tools"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fail_tools)
    assert probe_runtime(SESSION, run_session_id=RUN_SESSION) == ProbeSnapshot()


def test_runtime_shape_failure_degrades_to_empty_evidence(monkeypatch):
    install_fake_hermes(monkeypatch, async_records=None)
    sys.modules["tools.async_delegation"].list_async_delegations = lambda: {"wrong": "shape"}
    assert probe_runtime(SESSION, run_session_id=RUN_SESSION) == ProbeSnapshot()


def test_runtime_probe_failure_degrades_to_empty_evidence(monkeypatch):
    install_fake_hermes(monkeypatch)
    def fail(**kwargs):
        raise RuntimeError("runtime drift")
    sys.modules["tools.async_delegation"].has_live_for_session = fail
    assert probe_runtime(SESSION, run_session_id=RUN_SESSION) == ProbeSnapshot()


def test_missing_run_session_id_fails_closed(monkeypatch):
    install_fake_hermes(monkeypatch)
    assert probe_runtime(SESSION, run_session_id="") == ProbeSnapshot()
