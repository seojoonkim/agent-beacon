# Changelog

All notable changes to Agent Beacon are documented here.

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
