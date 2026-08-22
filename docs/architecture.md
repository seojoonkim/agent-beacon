# Agent Beacon v0.1 Architecture

## Purpose

Agent Beacon turns verified agent-runtime evidence into truthful, lineage-scoped progress, interruption, recovery, and closure messages. It never treats elapsed time, a prompt, or a generic session heartbeat as proof that a worker is active.

Hermes Agent is the first adapter. The core remains framework-neutral and has no Hermes imports.

## v0.1 boundary

### Core package: `agent_beacon`

- `event.py`: typed `TaskStatusEvent`, `Evidence`, `WorkerObservation`, and enums.
- `lineage.py`: immutable full lineage key.
- `machine.py`: legal state transitions.
- `registry.py`: sole event producer; transition, evidence, closure, and lineage enforcement.
- `policy.py`: honest ETA and next-report policy.
- `dedupe.py`: deterministic event fingerprinting and suppression.
- `redact.py`: allow-list validation and safe text handling.
- `render.py`: deterministic plain-text renderer.
- `store.py`: SQLite append/load/closure persistence.
- `schema/task-status-event-v1.json`: public JSON Schema.

### Hermes adapter: `agent_beacon_hermes`

- `probes.py`: the only Hermes-importing module.
- `lineage.py`: Hermes session key and runtime context to `LineageKey`.
- `heartbeat.py`: evidence snapshot to shadow/live heartbeat decision.
- `shutdown.py`: per-lineage interruption and closure rendering.
- `recovery.py`: restart sweep of persisted open lineages.
- `hooks.py`: adapter installation and mode selection (`off`, `shadow`, `live`).

## Public API

```python
from agent_beacon import (
    Evidence,
    LineageKey,
    Phase,
    StateRegistry,
    TaskStatusEvent,
    WorkerObservation,
    render,
)
from agent_beacon.store import SqliteStore

Decision = StateRegistry.observe(evidence)
text = render(Decision.event) if Decision.emit else None
```

`StateRegistry` is the only public event producer. Callers provide evidence; they do not construct user-visible claims directly.

## Event identity and isolation

Every registry and persistence lookup uses the complete immutable tuple:

```text
(profile, platform, account, chat_id, topic_id, session_key, run_id)
```

There is no partial-key lookup in the public API. Evidence from another lineage is rejected rather than merged. A generated `run_id` prevents a fresh agent/session binding from inheriting stale status under a reused session key.

## State machine

User-visible phases:

```text
announced -> active | blocked | paused | completed
active    -> active | blocked | paused | completed
blocked   -> terminal
paused    -> terminal
completed -> terminal
```

`blocked`, `paused`, and `completed` are terminal closure outcomes for an announced run. No closed lineage can reopen. A resumed operation starts a new lineage with a distinct `run_id` and may then enter `active`.

Internal observations may be suppressed as `unknown`, `no_evidence`, `stale`, or `duplicate`; these are decisions, not user-visible phases.

## Invariants

1. **No worker, no waiting claim.** Waiting on a subagent/delegation requires at least one live worker observation for the exact lineage.
2. **Evidence or silence.** No evidence yields no event, not a generic status sentence.
3. **Monotonic evidence.** An observation at or before the last accepted timestamp is stale and cannot regress state.
4. **Closure.** Every emitted/announced lineage closes terminally as `completed`, `blocked`, or `paused`. Resumption requires a distinct `run_id`; `close_all()` is idempotent.
5. **Full lineage isolation.** Profile, platform, account, chat, topic, session, and run are all part of identity.
6. **Honest time language.** Elapsed time alone never becomes an ETA. When completion cannot be bounded, expose only a future next-report SLA.
7. **Deterministic dedupe.** Equivalent phase/evidence within the suppression window emits once; phase changes bypass suppression.
8. **Redaction by construction.** Worker observations contain no prompt, goal, raw arguments/results, chain of thought, credentials, or provider internals. Rendering reads only typed allow-listed fields.
9. **Fail closed on adapter drift.** Missing or changed Hermes probes degrade to no Beacon message, never a guessed claim.

## Hermes evidence mapping

Verified against official Hermes `origin/main` worktree at `/private/tmp/hermes-agent-beacon-upstream`:

- `tools.async_delegation.has_live_for_session()` is the authoritative async-worker liveness predicate. Live states are `running`, `stalling`, and `finalizing`.
- `tools.async_delegation.list_async_delegations()` supplies durable/live delegation snapshots, including child activity and progress age.
- `tools.delegate_tool.list_active_subagents()` supplies the synchronous subagent tree without agent-owner internals.
- Hermes process snapshots are session-scoped but do not expose exact owning-run identity, so v0.1 deliberately excludes them from status evidence.
- `gateway.run._should_emit_long_running_notification()` remains the owner/session validity guard.
- `gateway.run._notify_long_running()` is the existing heartbeat seam.
- `gateway.run._notify_active_sessions_of_shutdown()` is the existing per-session shutdown seam.
- `gateway.run.stop()` and `_schedule_resume_pending_sessions()` define drain/restart boundaries; Beacon observes these boundaries but does not replace Hermes persistence or completion delivery.

The adapter polls existing registries at Hermes' existing heartbeat boundary. v0.1 does not patch delegation callbacks, duplicate Hermes state, or consume the completion queue.

## Minimal upstream integration

Hermes integration stays optional and surgical:

1. Add a display setting `beacon: off | shadow | live`, default `off`.
2. At `_notify_long_running()`, invoke the adapter after the existing ownership guard. In shadow mode, persist/compare Beacon output without replacing the user-visible message. In live mode, use Beacon output only when it emits; unsupported claims are suppressed rather than replaced by generic waiting text.
3. At `_notify_active_sessions_of_shutdown()`, ask Beacon for a per-lineage closure message instead of one fixed sentence.
4. After resume-pending scheduling, run an idempotent recovery sweep for Beacon's own open-lineage ledger.
5. Import lazily; when Agent Beacon is absent or a probe contract fails, preserve current Hermes behavior in `off`/`shadow`, and fail closed to silence for Beacon-specific claims in `live`.

No edits are made to `tools/async_delegation.py`, `tools/delegate_tool.py`, or `tools/process_registry.py` in v0.1.

## TDD order

1. Schema and full lineage identity.
2. Transition matrix, terminal state, stale observation rejection.
3. Headline regression: no live worker can never render waiting/delegation language.
4. Profile/chat/topic/session/run isolation.
5. ETA honesty, next-report SLA, deterministic rendering, dedupe.
6. Redaction and unknown-field rejection.
7. SQLite restart, concurrency, idempotent closure, abandoned-lineage recovery.
8. Hermes probe and adapter contract tests using fakes, followed by contract tests against official Hermes source.

Required named regressions include:

- `test_no_workers_never_renders_waiting_language`
- `test_waiting_requires_live_worker_evidence`
- `test_process_only_evidence_does_not_claim_subagent`
- `test_different_profile_same_session_key_isolated`
- `test_same_chat_different_topic_isolated`
- `test_stalled_delegation_closes_blocked`
- `test_shutdown_closes_every_announced_lineage_as_paused`
- `test_recovery_sweep_closes_abandoned_lineage`
- `test_render_omits_prompt_args_results_and_secret_tokens`
- `test_identical_evidence_within_window_suppressed`
- `test_open_lineage_survives_restart`

## Rollout gates

The first public release is shadow-capable. Live rollout is an operational phase, not evidence that the library itself is correct.

1. Full deterministic suite and schema validation pass.
2. Shadow on one low-traffic profile: zero probe errors, unsupported claims, lineage violations, or open-lineage leaks.
3. Shadow on two profiles including multi-topic traffic: zero cross-topic/account/profile mixing.
4. Shadow on at least one profile using real delegation work: every worker claim is corroborated by a same-snapshot live probe.
5. Shadow on all five profiles across forced restart and drain boundaries: every announced lineage closes exactly once.
6. Live on one profile with instant config rollback.
7. Expand one profile at a time only if no unsupported claim occurs. A single unsupported emitted claim is a rollback trigger.

A profile is not considered validated merely because no message appeared; fixtures and deliberate smoke runs must exercise active, stalled, shutdown, resume, and closure paths.

## Deferred from v0.1

- Non-Hermes adapters.
- Learned ETA or historical duration prediction.
- Push/event-driven hooks into delegation callbacks or completion queues.
- Multi-gateway shared writers to one SQLite file.
- Rich platform formatting and localization.
- Billing, audit-log, or exactly-once event-stream guarantees.

## Operational rollout gates (not completed by the package release)

An operational Hermes live rollout is complete only when:

- Core and adapter tests pass from a clean install.
- Public JSON Schema validates every emitted event fixture.
- Official Hermes contract tests resolve the documented symbols and shapes.
- Existing Hermes worktree remains untouched; adapter changes are developed against the isolated official worktree.
- Five-profile shadow logs prove no unsupported waiting claim and no lineage leakage.
- Safe restart and Telegram smoke tests prove truthful active, paused/recovering, and terminal closure messages.
- The repository release used by the rollout contains README, security/privacy contract, contribution guide, license, changelog, reproducible release workflow, and a tagged public release.

## Risks

- Polling can miss short-lived work between samples. Such work is not announced and creates no closure obligation; Beacon is a status surface, not an audit ledger.
- Best-effort child activity may be absent even while a worker is live. Render “active worker, detail unavailable,” never “no worker.”
- Shutdown and startup sweeps can race. Persistence closure must be transactional and idempotent.
- Hermes internal symbols can drift. Adapter contract CI must track Hermes `main`; drift degrades to silence rather than fabricated status.
- Generic fallback text can reintroduce the original defect. In live mode, an unsupported Beacon claim must not fall back to “waiting for a subagent.”

## Upstream maintenance strategy

Agent Beacon is separately versioned and published. Hermes consumes it as an optional dependency and keeps only narrow call-site hooks. Contract CI runs against Hermes `main`, while the core tests run without Hermes installed. Wire/schema versioning is independent from package versioning because persisted events outlive a process and possibly a package upgrade.
