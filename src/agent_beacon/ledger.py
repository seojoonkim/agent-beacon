"""Durable per-run ledger built on the SQLite store."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import sqlite3

from .event import Phase
from .lineage import LineageKey
from .machine import can_transition
from .store import SqliteStore

_TERMINAL = frozenset({Phase.BLOCKED, Phase.PAUSED, Phase.COMPLETED})


class UnknownRunError(LookupError):
    """Raised when a lineage has no recorded run."""


class RunConflictError(ValueError):
    """Raised when a run transition contradicts the recorded state."""


class TerminalRunError(RunConflictError):
    """Raised when a write targets a run that has already reached a terminal phase."""


class CorruptLedgerError(RuntimeError):
    """Raised when a persisted run cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class RunTransition:
    lineage: LineageKey
    from_state: Phase | None
    to_state: Phase
    at: datetime


@dataclass(frozen=True, slots=True)
class RunRecord:
    lineage: LineageKey
    phase: Phase
    opened_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        return self.phase in _TERMINAL


@dataclass(frozen=True, slots=True)
class UserInputOpenResult:
    """The run opened for new input and the prior runs it superseded."""

    opened: RunRecord
    preempted: tuple[RunRecord, ...]


def _require_aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("run timestamps must be timezone-aware")
    return moment


def _monotonic(at: datetime, previous: datetime) -> datetime:
    """Keep updated_at strictly increasing even when clocks stall or go backwards."""
    return max(at, previous + timedelta(microseconds=1))


def _key(lineage: LineageKey) -> str:
    return json.dumps(lineage.to_dict(), sort_keys=True, separators=(",", ":"))


def _scope(lineage: LineageKey) -> tuple[str, ...]:
    """The conversation a run belongs to: everything about its identity but the run id."""
    return (
        lineage.profile,
        lineage.platform,
        lineage.account,
        lineage.chat_id,
        lineage.topic_id,
        lineage.session_key,
    )


def _record(row: sqlite3.Row | tuple) -> RunRecord:
    """Strictly decode one persisted runs row, failing closed on corruption."""
    try:
        lineage_key, phase, opened_at, updated_at, is_terminal = row
        record = RunRecord(
            lineage=LineageKey.from_dict(json.loads(lineage_key)),
            phase=Phase(phase),
            opened_at=datetime.fromisoformat(opened_at),
            updated_at=datetime.fromisoformat(updated_at),
        )
    except (TypeError, ValueError, KeyError, OverflowError) as error:
        raise CorruptLedgerError("invalid persisted run row") from error
    if record.opened_at.tzinfo is None or record.updated_at.tzinfo is None:
        raise CorruptLedgerError("persisted run timestamps must be timezone-aware")
    if type(is_terminal) is not int or is_terminal not in (0, 1):
        raise CorruptLedgerError("persisted run terminal flag must be integer 0 or 1")
    if (is_terminal == 1) != record.is_terminal:
        raise CorruptLedgerError("persisted run phase and terminal flag disagree")
    return record


class RunLedger:
    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    def open_run(self, lineage: LineageKey, at: datetime) -> RunRecord:
        _require_aware(at)
        record = RunRecord(lineage, Phase.ANNOUNCED, at, at)
        with self._store.write_transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO runs(lineage_key, phase, opened_at, updated_at, is_terminal)
                       VALUES (?, ?, ?, ?, 0)""",
                    (_key(lineage), record.phase.value, at.isoformat(), at.isoformat()),
                )
            except sqlite3.IntegrityError as error:
                raise RunConflictError(f"run already open: {lineage}") from error
            self._append(connection, lineage, None, Phase.ANNOUNCED, at)
        return record

    def open_for_user_input(
        self, lineage: LineageKey, at: datetime
    ) -> UserInputOpenResult:
        """Atomically supersede this conversation's open runs and announce one."""
        _require_aware(at)
        incoming_key = _key(lineage)
        opened = RunRecord(lineage, Phase.ANNOUNCED, at, at)
        preempted: list[RunRecord] = []

        with self._store.write_transaction() as connection:
            # Reject an exact replay before changing prior runs, while still
            # failing closed if the exact row itself is malformed.
            existing = connection.execute(
                """SELECT lineage_key, phase, opened_at, updated_at, is_terminal
                   FROM runs WHERE lineage_key = ?""",
                (incoming_key,),
            ).fetchone()
            if existing is not None:
                _record(existing)
                raise RunConflictError(f"run already open: {lineage}")

            rows = connection.execute(
                """SELECT lineage_key, phase, opened_at, updated_at, is_terminal
                   FROM runs"""
            ).fetchall()
            scope = _scope(lineage)
            superseded = sorted(
                (
                    record
                    for record in map(_record, rows)
                    if not record.is_terminal
                    and _scope(record.lineage) == scope
                    and record.lineage != lineage
                ),
                key=lambda record: record.lineage.as_tuple(),
            )

            for record in superseded:
                moment = _monotonic(at, record.updated_at)
                updated = connection.execute(
                    """UPDATE runs SET phase = ?, updated_at = ?, is_terminal = 1
                       WHERE lineage_key = ? AND phase = ? AND is_terminal = 0""",
                    (
                        Phase.PAUSED.value,
                        moment.isoformat(),
                        _key(record.lineage),
                        record.phase.value,
                    ),
                ).rowcount
                if updated != 1:
                    raise RunConflictError(
                        f"run changed while opening user input: {record.lineage}"
                    )
                self._append(
                    connection, record.lineage, record.phase, Phase.PAUSED, moment
                )
                preempted.append(
                    RunRecord(record.lineage, Phase.PAUSED, record.opened_at, moment)
                )

            connection.execute(
                """INSERT INTO runs(lineage_key, phase, opened_at, updated_at, is_terminal)
                   VALUES (?, ?, ?, ?, 0)""",
                (incoming_key, Phase.ANNOUNCED.value, at.isoformat(), at.isoformat()),
            )
            self._append(connection, lineage, None, Phase.ANNOUNCED, at)

        return UserInputOpenResult(opened=opened, preempted=tuple(preempted))

    def activate(self, lineage: LineageKey, at: datetime) -> RunRecord:
        _require_aware(at)
        with self._store.write_transaction() as connection:
            current = self._get(connection, lineage)
            if current.is_terminal:
                raise TerminalRunError(f"cannot activate a {current.phase.value} run")
            if not can_transition(current.phase, Phase.ACTIVE):
                raise RunConflictError(f"cannot activate a {current.phase.value} run")
            moment = _monotonic(at, current.updated_at)
            updated = connection.execute(
                """UPDATE runs SET phase = ?, updated_at = ?
                   WHERE lineage_key = ? AND phase = ? AND is_terminal = 0""",
                (
                    Phase.ACTIVE.value,
                    moment.isoformat(),
                    _key(lineage),
                    current.phase.value,
                ),
            ).rowcount
            if updated != 1:
                # Someone moved the run out from under the phase we read.
                self._reject_stale(connection, lineage, Phase.ACTIVE)
            self._append(connection, lineage, current.phase, Phase.ACTIVE, moment)
        return RunRecord(lineage, Phase.ACTIVE, current.opened_at, moment)

    def terminate(self, lineage: LineageKey, at: datetime, phase: Phase) -> RunRecord:
        _require_aware(at)
        if phase not in _TERMINAL:
            raise ValueError(f"not a terminal phase: {phase.value}")
        with self._store.write_transaction() as connection:
            current = self._get(connection, lineage)
            if current.is_terminal:
                # Replaying the same outcome is a no-op; a different one is a contradiction.
                if current.phase is phase:
                    return current
                raise TerminalRunError(
                    f"run already {current.phase.value}; cannot mark it {phase.value}"
                )
            if not can_transition(current.phase, phase):
                raise RunConflictError(
                    f"cannot move a {current.phase.value} run to {phase.value}"
                )
            moment = _monotonic(at, current.updated_at)
            updated = connection.execute(
                """UPDATE runs SET phase = ?, updated_at = ?, is_terminal = 1
                   WHERE lineage_key = ? AND phase = ? AND is_terminal = 0""",
                (
                    phase.value,
                    moment.isoformat(),
                    _key(lineage),
                    current.phase.value,
                ),
            ).rowcount
            if updated != 1:
                # Lost the race: replay the winner's outcome or report the clash,
                # but never append a second transition.
                latest = self._get(connection, lineage)
                if latest.is_terminal and latest.phase is phase:
                    return latest
                self._reject_stale(connection, lineage, phase, latest=latest)
            self._append(connection, lineage, current.phase, phase, moment)
        return RunRecord(lineage, phase, current.opened_at, moment)

    def preempt_for_new_run(
        self, new_lineage: LineageKey, at: datetime
    ) -> list[RunRecord]:
        """Pause every nonterminal prior run sharing new_lineage's conversation scope.

        The new lineage is neither opened nor activated here; this only closes the
        runs it supersedes. Selection and all writes share one transaction so a
        concurrent reader never sees a half-preempted conversation.
        """
        _require_aware(at)
        scope = _scope(new_lineage)
        preempted: list[RunRecord] = []
        with self._store.write_transaction() as connection:
            rows = connection.execute(
                """SELECT lineage_key, phase, opened_at, updated_at, is_terminal
                   FROM runs"""
            ).fetchall()
            superseded = sorted(
                (
                    record
                    for record in map(_record, rows)
                    if not record.is_terminal
                    and _scope(record.lineage) == scope
                    and record.lineage.run_id != new_lineage.run_id
                ),
                key=lambda record: record.lineage.as_tuple(),
            )
            for record in superseded:
                moment = _monotonic(at, record.updated_at)
                updated = connection.execute(
                    """UPDATE runs SET phase = ?, updated_at = ?, is_terminal = 1
                       WHERE lineage_key = ? AND phase = ? AND is_terminal = 0""",
                    (
                        Phase.PAUSED.value,
                        moment.isoformat(),
                        _key(record.lineage),
                        record.phase.value,
                    ),
                ).rowcount
                if updated != 1:
                    # Another preemptor already closed this run; leave its history alone.
                    continue
                self._append(
                    connection, record.lineage, record.phase, Phase.PAUSED, moment
                )
                preempted.append(
                    RunRecord(
                        record.lineage, Phase.PAUSED, record.opened_at, moment
                    )
                )
        return preempted

    def history(self, lineage: LineageKey) -> list[RunTransition]:
        with self._store.transaction() as connection:
            rows = connection.execute(
                """SELECT from_state, to_state, at FROM run_transitions
                   WHERE lineage_key = ? ORDER BY sequence""",
                (_key(lineage),),
            ).fetchall()
        return [
            RunTransition(
                lineage=lineage,
                from_state=None if from_state is None else Phase(from_state),
                to_state=Phase(to_state),
                at=datetime.fromisoformat(at),
            )
            for from_state, to_state, at in rows
        ]

    @classmethod
    def _reject_stale(
        cls,
        connection: sqlite3.Connection,
        lineage: LineageKey,
        target: Phase,
        latest: RunRecord | None = None,
    ) -> None:
        """Re-read a run whose guarded update matched no row and raise accordingly."""
        if latest is None:
            latest = cls._get(connection, lineage)
        if latest.is_terminal:
            raise TerminalRunError(
                f"run already {latest.phase.value}; cannot mark it {target.value}"
            )
        raise RunConflictError(
            f"cannot move a {latest.phase.value} run to {target.value}"
        )

    @staticmethod
    def _append(
        connection: sqlite3.Connection,
        lineage: LineageKey,
        from_state: Phase | None,
        to_state: Phase,
        at: datetime,
    ) -> None:
        connection.execute(
            """INSERT INTO run_transitions(lineage_key, from_state, to_state, at)
               VALUES (?, ?, ?, ?)""",
            (
                _key(lineage),
                None if from_state is None else from_state.value,
                to_state.value,
                at.isoformat(),
            ),
        )

    def get(self, lineage: LineageKey) -> RunRecord:
        with self._store.transaction() as connection:
            return self._get(connection, lineage)

    def nonterminal(self) -> list[RunRecord]:
        with self._store.transaction() as connection:
            rows = connection.execute(
                """SELECT lineage_key, phase, opened_at, updated_at, is_terminal
                   FROM runs ORDER BY lineage_key"""
            ).fetchall()
        records = [_record(row) for row in rows]
        return [record for record in records if not record.is_terminal]

    @staticmethod
    def _get(connection: sqlite3.Connection, lineage: LineageKey) -> RunRecord:
        row = connection.execute(
            """SELECT lineage_key, phase, opened_at, updated_at, is_terminal FROM runs
               WHERE lineage_key = ?""",
            (_key(lineage),),
        ).fetchone()
        if row is None:
            raise UnknownRunError(f"no run for lineage: {lineage}")
        return _record(row)
