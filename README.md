# Agent Beacon

**Truthful, lineage-scoped status reporting for autonomous agents.**

Agent Beacon turns verified runtime evidence into progress, interruption, recovery, and closure events. It never treats elapsed time, a prompt, or a generic heartbeat as proof that a worker is active.

Hermes Agent is the first adapter. The core package is framework-neutral.

## Why

Agent status messages are easy to fabricate accidentally: “still working,” “waiting for a subagent,” or an ETA can survive after the worker has stopped, belong to another chat, or refer to a previous run. Agent Beacon makes those claims evidence-bound.

Core guarantees:

- **No worker, no waiting claim.**
- **Evidence or silence.** Unsupported claims emit nothing.
- **Full lineage isolation.** Identity includes profile, platform, account, chat, topic, session, and run.
- **Terminal closure.** Announced runs end as `completed`, `blocked`, or `paused`.
- **No run resurrection.** Resumption creates a new `run_id`.
- **Honest time language.** Elapsed time alone never becomes an ETA.
- **Redaction by construction.** Renderers cannot access prompts, tool arguments/results, chain of thought, credentials, or provider internals.

## Install

```bash
python -m pip install agent-beacon
```

For local development:

```bash
git clone https://github.com/seojoonkim/agent-beacon.git
cd agent-beacon
python -m pip install -e '.[dev]'
pytest
```

Python 3.11 or newer is required.

## Core example

```python
from datetime import datetime, timezone

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry, WorkerObservation, render

lineage = LineageKey(
    profile="example-profile",
    platform="telegram",
    account="bot:2e91…",
    chat_id="example-chat",
    topic_id="none",
    session_key="agent:example:telegram:direct:example-chat",
    run_id="run-2026-08-22-001",
)

registry = StateRegistry()
evidence = Evidence(
    lineage=lineage,
    observed_at=datetime.now(timezone.utc),
    phase=Phase.ACTIVE,
    waiting_on_worker=True,
    workers=(WorkerObservation(worker_id="worker-1", live=True),),
)

decision = registry.observe(evidence)
text = render(decision.event) if decision.emit else None
```

`StateRegistry` is the sole event producer. Callers provide typed evidence; they do not construct user-visible status claims directly.

## Hermes adapter

`agent_beacon_hermes` provides:

- delegation probes scoped to the exact Hermes `session_key` and current run session
- explicit `profile/platform/account/chat/topic/session/run` lineage construction
- `off`, `shadow`, and `live` heartbeat decisions
- fail-closed behavior when Hermes internals drift
- idempotent shutdown and abandoned-lineage recovery helpers

The adapter is optional. Importing `agent_beacon` does not import Hermes.

Hermes background-process snapshots are deliberately not treated as v0.1
evidence because the inspected API does not expose an exact owning run session.

### Modes

- `off`: no adapter import or behavior change
- `shadow`: compute Beacon output while preserving existing user-visible bytes
- `live`: emit only supported, runtime-backed Beacon output; unsupported or failed probes return silence

A host integration must preserve exact routing and pass a stable, non-secret account fingerprint. Never use the profile name as an account identity.

## Event identity

Every lookup uses the complete immutable key:

```text
(profile, platform, account, chat_id, topic_id, session_key, run_id)
```

Partial-key merging is intentionally unsupported.

## Architecture and security

- [Architecture and invariants](docs/architecture.md)
- [Security and privacy contract](SECURITY.md)
- [Contribution guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

The public event schema is distributed at `agent_beacon/schema/task-status-event-v1.json`.

## Current release boundary

v0.1.0 delivers the framework-neutral core and the first Hermes adapter contract. Operational live rollout remains host-version specific: an integration must provide a verified heartbeat seam, exact source routing, current-run identity, fail-closed suppression, and rollback before enabling `live`.

## License

MIT. See [LICENSE](LICENSE).
