"""Wire-schema version contract."""

SCHEMA_VERSION = "1"


def require_supported_version(version: object) -> None:
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version: {version!r}")
