"""Detached immutable structural results; none represents authenticated authority."""

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType


_MAX_SOURCE_RECORDS = 256
_MAX_CIVIL_DATES = 36_600
# Physical before-allocation enforcement is deferred to the filesystem reader.
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_INVENTORY_BYTES = 128 * 1024 * 1024
_MAX_SOURCE_BODY_BYTES = 16 * 1024 * 1024
_MAX_JSON_NESTING = 32


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if type(value) is MappingProxyType:
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class _ParsedDocument:
    name: str
    canonical_bytes: bytes
    value: MappingProxyType


@dataclass(frozen=True, slots=True)
class _AdmittedManifest:
    """Phase-one manifest admission; not an admitting capability, only a result."""

    document: _ParsedDocument
    artifact_id: str
    documents: tuple[_ParsedDocument, ...]


@dataclass(frozen=True, slots=True)
class _SemanticFacts:
    """Consistency only: signatures, source claims and clocks are NOT authenticated."""

    documents: tuple[_ParsedDocument, ...]
    source_snapshot_id: str
    source_content_hash: str
    coverage_completion_evidence_id: str
    schedule_declaration_hash_without_archive: str
    schedule_content_id: str
    schedule_pin_id: str
    schedule_artifact_id: str
    archive_available_at: datetime
