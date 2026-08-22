# Contributing

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

## Design rules

1. `StateRegistry` remains the sole producer of user-visible events.
2. Every state lookup uses the full seven-part lineage key.
3. A waiting/delegation claim requires live evidence for the exact current run.
4. Missing or incompatible adapter data fails closed to silence.
5. Renderers consume typed allow-listed fields only.
6. A terminal run cannot reopen; resumption creates a new `run_id`.
7. Elapsed time is not an ETA.

## Test-driven changes

Add a failing regression before changing behavior. At minimum run:

```bash
pytest
python -m compileall -q src tests
```

For Hermes adapter changes, include contract fixtures for realistic Telegram and threaded routing, current-run `parent_session_id`, account separation, unsupported shapes, and exception handling. Do not depend on a developer's running Hermes instance.

## Scope

Keep the core framework-neutral. Framework-specific imports belong only in adapter packages. Do not add telemetry, network calls, or credential collection to the core.

## Pull requests

Explain:

- the claim being made safer or more accurate
- the exact runtime evidence that supports it
- lineage and privacy implications
- failure behavior and rollback
- tests that prove no-worker/no-claim and cross-lineage isolation
