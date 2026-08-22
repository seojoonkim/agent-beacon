"""Complete, immutable identity for one agent run."""

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class LineageKey:
    profile: str
    platform: str
    account: str
    chat_id: str
    topic_id: str
    session_key: str
    run_id: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in self.as_tuple()):
            raise ValueError("all lineage components must be non-empty strings")

    def as_tuple(self) -> tuple[str, ...]:
        return tuple(getattr(self, field.name) for field in fields(self))

    def to_dict(self) -> dict[str, str]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> "LineageKey":
        return cls(**value)
