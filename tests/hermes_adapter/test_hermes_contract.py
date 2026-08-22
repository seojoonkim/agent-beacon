"""Read-only AST contract against the isolated official Hermes worktree."""

import ast
from pathlib import Path

import pytest


UPSTREAM = Path("/private/tmp/hermes-agent-beacon-upstream")


def _tree(relative: str) -> ast.Module:
    path = UPSTREAM / relative
    if not path.is_file():
        pytest.fail(f"official Hermes contract source is missing: {path}")
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(relative: str, name: str, *, parent: str | None = None):
    tree = _tree(relative)
    nodes = tree.body
    if parent is not None:
        classes = [node for node in nodes if isinstance(node, ast.ClassDef) and node.name == parent]
        assert len(classes) == 1, f"missing exact class {parent} in {relative}"
        nodes = classes[0].body
    else:
        # Some gateway seams are deliberately local closures. Static traversal
        # verifies them without importing the side-effectful gateway module.
        nodes = ast.walk(tree)
    matches = [
        node
        for node in nodes
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(matches) == 1, f"missing exact function {name} in {relative}"
    return matches[0]


def _signature(node):
    args = node.args
    return (
        tuple(arg.arg for arg in args.posonlyargs),
        tuple(arg.arg for arg in args.args),
        tuple(arg.arg for arg in args.kwonlyargs),
        args.vararg.arg if args.vararg else None,
        args.kwarg.arg if args.kwarg else None,
        len(args.defaults),
        len(args.kw_defaults),
    )


def test_official_hermes_probe_symbols_and_exact_signatures():
    assert _signature(_function("tools/async_delegation.py", "has_live_for_session")) == (
        (), ("session_key", "origin_ui_session_id", "parent_session_id"), (), None, None, 3, 0
    )
    assert _signature(_function("tools/async_delegation.py", "list_async_delegations")) == (
        (), (), (), None, None, 0, 0
    )
    assert _signature(_function("tools/delegate_tool.py", "list_active_subagents")) == (
        (), (), (), None, None, 0, 0
    )
    assert _signature(
        _function("tools/process_registry.py", "has_active_for_session", parent="ProcessRegistry")
    ) == ((), ("self", "session_key", "max_active_age"), (), None, None, 1, 0)
    assert _signature(
        _function("tools/process_registry.py", "list_sessions", parent="ProcessRegistry")
    ) == ((), ("self", "task_id", "session_key"), (), None, None, 2, 0)

    assignments = [
        node
        for node in _tree("tools/process_registry.py").body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    assert any(
        any(isinstance(target, ast.Name) and target.id == "process_registry" for target in node.targets)
        if isinstance(node, ast.Assign)
        else isinstance(node.target, ast.Name) and node.target.id == "process_registry"
        for node in assignments
    ), "missing process_registry singleton"


def test_official_hermes_gateway_integration_seams_exist_without_importing_gateway():
    long_running = _function("gateway/run.py", "_notify_long_running")
    assert isinstance(long_running, ast.AsyncFunctionDef)
    assert _signature(long_running) == ((), (), (), None, None, 0, 0)

    shutdown = _function(
        "gateway/run.py", "_notify_active_sessions_of_shutdown", parent="GatewayRunner"
    )
    resume = _function(
        "gateway/run.py", "_schedule_resume_pending_sessions", parent="GatewayRunner"
    )
    assert isinstance(shutdown, ast.AsyncFunctionDef)
    assert _signature(shutdown) == ((), ("self",), (), None, None, 0, 0)
    assert _signature(resume) == ((), ("self", "platform"), (), None, None, 1, 0)
