# Hermes adapter pack 1 delegated-run closure

## Observed facts

- The worker produced the requested pack but exited at its iteration limit before rerunning the final lineage edit through the full suite.
- Parent verification initially found a pytest import-name collision: both core and adapter directories contained `test_lineage.py` without package isolation.
- Product source compiled; official Hermes worktree remained clean.

## Root cause

The delegated pack spent too much budget repeatedly inspecting broad upstream source and exhausted its iteration allowance. The duplicated pytest module basename was not covered by the worker's last focused run.

## Prevention applied

- Renamed the adapter test to `test_hermes_lineage.py` so collection is unambiguous without adding package-marker behavior.
- Keep later packs to one lifecycle concern and unique test basenames.
- Parent must run the whole repository suite after every delegated pack, regardless of worker completion prose.

## Verification

`python3 -m pytest && python3 -m compileall -q src tests && git diff --check` passed with 55 tests. The official Hermes worktree remained clean.
