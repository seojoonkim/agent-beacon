# Changelog

All notable changes to Agent Beacon are documented here.

## [0.2.0] - 2026-08-22

### Added

- Authoritative SQLite run ledger with durable lifecycle records and transition history.
- Atomic `open_for_user_input`, which pauses superseded nonterminal runs and opens the incoming run in one transaction.
- Typed public ledger records, results, and conflict, terminal, unknown-run, and corruption errors.
- Read-only, fail-closed Hermes `sessions.json` restart-handoff projection with exact session and run ownership checks.

### Changed

- Ledger reads now fail closed when persisted run state is malformed or internally inconsistent.
- Concurrent lifecycle updates use guarded writes to prevent contradictory transitions and duplicate terminal history.

### Operational note

- This release does not imply or perform a live Hermes rollout. The handoff projection is non-authoritative and cannot mutate Hermes sessions or the Agent Beacon ledger; live enablement remains host-version specific and requires the verified seams and rollback described below.

## [0.1.0] - 2026-08-22

### Added

- Framework-neutral typed status events and immutable seven-part lineage identity.
- Evidence-driven state registry with terminal closure and no run resurrection.
- Deterministic deduplication, rendering, time policy, JSON Schema, and SQLite persistence.
- Redaction and unknown-field rejection by construction.
- First Hermes adapter with exact-current-run delegation probes; background
  processes fail closed until Hermes exposes owning-run identity.
- `off`, `shadow`, and fail-closed `live` heartbeat decisions.
- Explicit Hermes source routing and stable non-secret account fingerprint contract.
- Shutdown and abandoned-lineage recovery helpers.
- Regression coverage for no-worker/no-waiting, account/profile/chat/topic/session/run isolation, stale evidence, closure, and adapter drift.

### Operational note

- Live Hermes rollout is intentionally host-version specific and is not implied by installing this package. Hosts must provide and verify the required heartbeat seam and rollback path.
