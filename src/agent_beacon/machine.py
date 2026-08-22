"""Agent Beacon's deliberately small user-visible state machine."""

from .event import Phase

_TRANSITIONS = {
    Phase.ANNOUNCED: frozenset({Phase.ACTIVE, Phase.BLOCKED, Phase.PAUSED, Phase.COMPLETED}),
    Phase.ACTIVE: frozenset({Phase.ACTIVE, Phase.BLOCKED, Phase.PAUSED, Phase.COMPLETED}),
    Phase.BLOCKED: frozenset(),
    Phase.PAUSED: frozenset(),
    Phase.COMPLETED: frozenset(),
}


def can_transition(source: Phase, target: Phase) -> bool:
    return target in _TRANSITIONS[source]
