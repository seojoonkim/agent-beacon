"""Deterministic plain-text rendering from typed, allow-listed fields."""

from .event import TaskStatusEvent


def render(event: TaskStatusEvent) -> str:
    phase = event.phase.value.capitalize()
    if event.waiting_on_worker:
        noun = "worker" if event.live_worker_count == 1 else "workers"
        detail = f"waiting on {event.live_worker_count} live {noun}"
    elif event.process_active:
        detail = "background process active"
    else:
        detail = "no live worker observed"
    return f"{phase}: {detail}."
