"""Wire-schema version contract."""

SCHEMA_VERSION = "2"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1", SCHEMA_VERSION})


def require_supported_version(version: object) -> None:
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported schema version: {version!r}")
