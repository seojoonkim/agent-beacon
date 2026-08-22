from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from agent_beacon import Evidence, LineageKey, Phase, StateRegistry
from agent_beacon.store import SqliteStore


def key(run="r"):
    return LineageKey("p", "telegram", "a", "c", "t", "s", run)


def test_open_lineage_survives_store_and_registry_restart(tmp_path):
    path = tmp_path / "beacon.sqlite3"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(path) as store:
        assert StateRegistry(store=store).observe(Evidence(key(), now, Phase.ANNOUNCED)).emit
    with SqliteStore(path) as store:
        assert [event.lineage for event in store.load_open()] == [key()]
        assert StateRegistry(store=store).phase(key()) is Phase.ANNOUNCED


def test_shutdown_closes_every_announced_lineage_as_paused_and_is_idempotent(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(tmp_path / "db") as store:
        registry = StateRegistry(store=store)
        for index in range(3):
            assert registry.observe(Evidence(key(str(index)), now, Phase.ANNOUNCED)).emit
        closed = registry.close_all(now + timedelta(seconds=1))
        assert len(closed) == 3
        assert {event.phase for event in closed} == {Phase.PAUSED}
        assert registry.close_all(now + timedelta(seconds=2)) == []
        assert store.load_open() == []


def test_close_all_supports_each_legal_closure_outcome(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for phase in (Phase.COMPLETED, Phase.BLOCKED, Phase.PAUSED):
        with SqliteStore(tmp_path / phase.value) as store:
            registry = StateRegistry(store=store)
            registry.observe(Evidence(key(phase.value), now, Phase.ANNOUNCED))
            assert registry.close_all(now + timedelta(seconds=1), phase=phase)[0].phase is phase
            assert store.load_open() == []


def test_concurrent_observations_are_serialized(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SqliteStore(tmp_path / "db") as store:
        registry = StateRegistry(store=store)
        def observe(index):
            return registry.observe(Evidence(key(str(index)), now, Phase.ANNOUNCED)).emit
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert all(pool.map(observe, range(40)))
        assert len(store.load_open()) == 40
