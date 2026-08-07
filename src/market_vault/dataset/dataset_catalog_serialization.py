"""Deterministic Catalog snapshot serialization (v0.6.0 PR-6).

This module fixes the exact byte contracts of one physical Catalog
snapshot: the ``catalog.json`` logical payload and the ``manifest.json``
physical manifest. The writer side produces canonical UTF-8 JSON (no BOM,
sorted keys, compact separators, trailing newline) from the frozen typed
models only; the parser side strictly reconstructs the frozen typed
nested models from the exact field set and requires the re-serialization
of the typed records to reproduce the actual bytes exactly, so any
non-canonical representation (whitespace, key order, timestamp text,
BOM) fails closed.

The ``catalog.json`` payload is the complete lossless record of every
PR-5 :class:`DatasetCatalogEntry`: the typed content facts (the exact
PR-5 field set — no manifest-internal field is copied), the recorded
non-content observed metadata, and the self-validated per-Dataset content
ID. It is deterministic: the same :class:`~market_vault.dataset.
dataset_catalog_builder_models.DatasetCatalogBuildResult` always produces
byte-identical ``catalog.json`` — the current time, the ``output_root``,
the snapshot path, the machine name, cwd, mtimes, and candidate / scan
order never enter it. The snapshot ``built_at`` is recorded only in
``manifest.json``, never in ``catalog.json``.

``manifest.json`` is the fixed physical manifest: schema / snapshot-ID /
materializer / builder versions, the snapshot ID, the Catalog content
identity, the UTC-microsecond ``built_at``, the dataset count, and the
exact ``catalog.json`` byte facts (fixed relative path, real non-negative
byte size, lowercase SHA-256). It never records the ``output_root``, the
snapshot absolute path, the machine name, cwd, or the current time.

All parse failures raise :class:`DatasetCatalogError` (the unified PR-5
contract error); the materializer and the verified reader convert them to
their own fail-closed errors at their public boundaries with the
``__cause__`` preserved. This module never reads or writes files, never
scans directories, never uses the current time, and never accesses
settings or the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Mapping

from .artifact_serialization import _canonical_json_bytes
from .dataset_catalog_builder_models import (
    DATASET_CATALOG_BUILDER_VERSION,
    DatasetCatalogBuildResult,
)
from .dataset_catalog_identity import _dataset_catalog_content_id_from_facts
from .dataset_catalog_models import (
    DATASET_CATALOG_CONTRACT_VERSION,
    DATASET_CATALOG_CONTENT_ID_VERSION,
    DATASET_CATALOG_ENTRY_SCHEMA_VERSION,
    CanonicalBuildPin,
    CompletionSummary,
    DatasetCatalogDatasetFacts,
    DatasetCatalogError,
    DatasetScope,
    SpecPin,
)
from .models import CompletionEntry, SourceSnapshotPin
from .dataset_catalog_snapshot_identity import (
    DATASET_CATALOG_MATERIALIZER_VERSION,
    DATASET_CATALOG_SNAPSHOT_ID_VERSION,
    DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION,
    DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION,
)
from .dataset_catalog_materialization_models import (
    DATASET_CATALOG_CATALOG_FILENAME,
)
from .encoding import DatasetError, normalize_utc_datetime

__all__ = [
    "ParsedCatalogEntry",
    "ParsedCatalogPayload",
    "ParsedManifestPayload",
    "catalog_payload_bytes",
    "manifest_payload_bytes",
    "parse_catalog_bytes",
    "parse_manifest_bytes",
]

_UTF8_BOM = b"\xef\xbb\xbf"

#: Exact field set of the ``catalog.json`` top level.
_CATALOG_TOP_LEVEL_FIELDS = frozenset(
    {
        "snapshot_schema_version",
        "catalog_contract_version",
        "catalog_entry_schema_version",
        "catalog_content_id_version",
        "builder_version",
        "catalog_content_id",
        "dataset_count",
        "datasets",
    }
)

#: Exact field set of one ``datasets`` array record.
_DATASET_RECORD_FIELDS = frozenset(
    {"content_id", "dataset_facts", "observed_metadata"}
)

#: Exact field set of one observed-metadata record.
_OBSERVED_METADATA_FIELDS = frozenset({"built_at", "build_path"})

#: Exact PR-5 content-facts field set (nothing else is ever copied).
_FACTS_FIELDS = frozenset(
    {
        "dataset_id",
        "dataset_kind",
        "status",
        "logical_row_count",
        "dataset_schema_id",
        "logical_dataset_content_id",
        "dataset_as_of",
        "scope",
        "feature_spec_pins",
        "label_spec_pins",
        "split_spec_pin",
        "canonical_build_pins",
        "canonical_row_version_ids",
        "completion",
    }
)

_SCOPE_FIELDS = frozenset(
    {"symbols", "trade_dates", "interval", "adjustment", "requested_session"}
)

_SPEC_PIN_FIELDS = frozenset({"kind", "name", "version", "content_sha256"})

_CANONICAL_BUILD_PIN_FIELDS = frozenset(
    {
        "canonical_build_id",
        "canonical_content_id",
        "canonical_builder_version",
        "canonical_schema_version",
        "materializer_version",
        "gap_policy_version",
        "gap_content_id",
        "status",
        "canonical_row_version_ids",
        "source_snapshots",
    }
)

_SOURCE_SNAPSHOT_FIELDS = frozenset(
    {
        "ingestion_run_id",
        "physical_snapshot_hash",
        "logical_source_rows_hash",
        "source_schema_version",
        "requested_trade_date",
        "requested_session",
    }
)

_COMPLETION_FIELDS = frozenset(
    {"complete_count", "incomplete_count", "missing_count", "entries"}
)

_COMPLETION_ENTRY_FIELDS = frozenset({"code", "trade_date", "status", "reason_code"})

#: Exact field set of ``manifest.json``.
_MANIFEST_FIELDS = frozenset(
    {
        "manifest_schema_version",
        "snapshot_id_version",
        "materializer_version",
        "builder_version",
        "snapshot_id",
        "catalog_content_id",
        "built_at",
        "dataset_count",
        "catalog_file",
    }
)

_CATALOG_FILE_FIELDS = frozenset({"relative_path", "byte_size", "sha256"})


@dataclass(frozen=True)
class _SerializedEntry:
    """One entry in its canonical serialization shape: the self-validated
    content ID, the typed content facts, and the non-content observed
    facts (``built_at`` normalized, ``build_path`` as forward-slash text).
    Both the writer (from :class:`DatasetCatalogEntry`) and the parser
    (from the reconstructed typed records) build exactly this shape, so
    the canonical-bytes check compares like with like."""

    content_id: str
    dataset_facts: DatasetCatalogDatasetFacts
    observed_built_at: datetime
    observed_build_path: str


@dataclass(frozen=True)
class ParsedCatalogEntry:
    """One strictly parsed ``datasets`` record: the typed reconstructed
    content facts, the parsed non-content observed facts (never a live
    ``Path`` — the recorded build location is historical text only), and
    the recorded content ID."""

    content_id: str
    dataset_facts: DatasetCatalogDatasetFacts
    observed_built_at: datetime
    observed_build_path: str


@dataclass(frozen=True)
class ParsedCatalogPayload:
    """The strictly parsed top-level ``catalog.json`` facts and the
    strictly parsed entries, with every version field validated against
    the current constants and the canonical-bytes equality already
    enforced."""

    snapshot_schema_version: str
    catalog_contract_version: str
    catalog_entry_schema_version: str
    catalog_content_id_version: str
    builder_version: str
    catalog_content_id: str
    dataset_count: int
    entries: tuple[ParsedCatalogEntry, ...]


@dataclass(frozen=True)
class ParsedManifestPayload:
    """The strictly parsed ``manifest.json`` facts with every version
    field validated against the current constants and the canonical-bytes
    equality already enforced."""

    manifest_schema_version: str
    snapshot_id_version: str
    materializer_version: str
    builder_version: str
    snapshot_id: str
    catalog_content_id: str
    built_at: datetime
    dataset_count: int
    catalog_relative_path: str
    catalog_byte_size: int
    catalog_sha256: str


# ---------------------------------------------------------------------------
# Writer side (deterministic payloads from typed models only).
# ---------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    """UTC microsecond ISO text of one instant (the snapshot datetime
    representation)."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _spec_pin_payload(pin: SpecPin) -> dict:
    return {
        "kind": pin.kind,
        "name": pin.name,
        "version": pin.version,
        "content_sha256": pin.content_sha256,
    }


def _source_snapshot_payload(snapshot: SourceSnapshotPin) -> dict:
    return {
        "ingestion_run_id": snapshot.ingestion_run_id,
        "physical_snapshot_hash": snapshot.physical_snapshot_hash,
        "logical_source_rows_hash": snapshot.logical_source_rows_hash,
        "source_schema_version": snapshot.source_schema_version,
        "requested_trade_date": snapshot.requested_trade_date.isoformat(),
        "requested_session": snapshot.requested_session,
    }


def _canonical_build_pin_payload(pin: CanonicalBuildPin) -> dict:
    return {
        "canonical_build_id": pin.canonical_build_id,
        "canonical_content_id": pin.canonical_content_id,
        "canonical_builder_version": pin.canonical_builder_version,
        "canonical_schema_version": pin.canonical_schema_version,
        "materializer_version": pin.materializer_version,
        "gap_policy_version": pin.gap_policy_version,
        "gap_content_id": pin.gap_content_id,
        "status": pin.status,
        "canonical_row_version_ids": list(pin.canonical_row_version_ids),
        "source_snapshots": [
            _source_snapshot_payload(snapshot) for snapshot in pin.source_snapshots
        ],
    }


def _completion_entry_payload(entry: CompletionEntry) -> dict:
    return {
        "code": entry.code,
        "trade_date": entry.trade_date.isoformat(),
        "status": entry.status,
        "reason_code": entry.reason_code,
    }


def _completion_payload(completion: CompletionSummary) -> dict:
    return {
        "complete_count": completion.complete_count,
        "incomplete_count": completion.incomplete_count,
        "missing_count": completion.missing_count,
        "entries": [
            _completion_entry_payload(entry) for entry in completion.entries
        ],
    }


def _scope_payload(scope: DatasetScope) -> dict:
    return {
        "symbols": list(scope.symbols),
        "trade_dates": [trade_date.isoformat() for trade_date in scope.trade_dates],
        "interval": scope.interval,
        "adjustment": scope.adjustment,
        "requested_session": scope.requested_session,
    }


def _facts_payload(facts: DatasetCatalogDatasetFacts) -> dict:
    """The exact lossless PR-5 facts record (the complete identity-bearing
    field set; no manifest-internal field is ever copied)."""
    return {
        "dataset_id": facts.dataset_id,
        "dataset_kind": facts.dataset_kind,
        "status": facts.status,
        "logical_row_count": facts.logical_row_count,
        "dataset_schema_id": facts.dataset_schema_id,
        "logical_dataset_content_id": facts.logical_dataset_content_id,
        "dataset_as_of": (
            _iso(facts.dataset_as_of) if facts.dataset_as_of is not None else None
        ),
        "scope": _scope_payload(facts.scope),
        "feature_spec_pins": [
            _spec_pin_payload(pin) for pin in facts.feature_spec_pins
        ],
        "label_spec_pins": [
            _spec_pin_payload(pin) for pin in facts.label_spec_pins
        ],
        "split_spec_pin": (
            _spec_pin_payload(facts.split_spec_pin)
            if facts.split_spec_pin is not None
            else None
        ),
        "canonical_build_pins": [
            _canonical_build_pin_payload(pin) for pin in facts.canonical_build_pins
        ],
        "canonical_row_version_ids": list(facts.canonical_row_version_ids),
        "completion": _completion_payload(facts.completion),
    }


def _entry_payload(entry: _SerializedEntry) -> dict:
    return {
        "content_id": entry.content_id,
        "dataset_facts": _facts_payload(entry.dataset_facts),
        "observed_metadata": {
            "built_at": _iso(entry.observed_built_at),
            "build_path": entry.observed_build_path,
        },
    }


def _catalog_payload_dict(
    entries: tuple[_SerializedEntry, ...], builder_version: str
) -> dict:
    by_id: dict = {}
    for entry in entries:
        by_id[entry.dataset_facts.dataset_id] = entry.dataset_facts
    return {
        "snapshot_schema_version": DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION,
        "catalog_contract_version": DATASET_CATALOG_CONTRACT_VERSION,
        "catalog_entry_schema_version": DATASET_CATALOG_ENTRY_SCHEMA_VERSION,
        "catalog_content_id_version": DATASET_CATALOG_CONTENT_ID_VERSION,
        "builder_version": builder_version,
        "catalog_content_id": _dataset_catalog_content_id_from_facts(by_id),
        "dataset_count": len(entries),
        "datasets": [_entry_payload(entry) for entry in entries],
    }


def catalog_payload_bytes(result: DatasetCatalogBuildResult) -> bytes:
    """Deterministic canonical ``catalog.json`` bytes of one
    :class:`DatasetCatalogBuildResult`.

    The same build result always produces byte-identical bytes; the
    current time, ``output_root``, snapshot path, host, cwd, mtimes, scan
    order, and candidate order never enter them. The snapshot
    ``built_at`` is deliberately absent — it belongs to ``manifest.json``
    only.
    """
    if not isinstance(result, DatasetCatalogBuildResult):
        raise DatasetCatalogError(
            "catalog_payload_bytes requires a DatasetCatalogBuildResult, got "
            f"{type(result).__name__}"
        )
    serialized = tuple(
        _SerializedEntry(
            content_id=entry.content_id,
            dataset_facts=entry.dataset_facts,
            observed_built_at=entry.observed_metadata.built_at,
            observed_build_path=entry.observed_metadata.build_path.as_posix(),
        )
        for entry in result.entries
    )
    return _canonical_json_bytes(
        _catalog_payload_dict(serialized, result.builder_version)
    )


def manifest_payload_dict(
    *,
    snapshot_id: str,
    catalog_content_id: str,
    dataset_count: int,
    built_at: datetime,
    catalog_byte_size: int,
    catalog_sha256: str,
) -> dict:
    """The exact deterministic ``manifest.json`` payload (physical facts
    only). ``built_at`` is normalized to UTC microseconds; the fixed
    ``catalog_file.relative_path`` is always ``catalog.json``."""
    return {
        "manifest_schema_version": DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION,
        "snapshot_id_version": DATASET_CATALOG_SNAPSHOT_ID_VERSION,
        "materializer_version": DATASET_CATALOG_MATERIALIZER_VERSION,
        "builder_version": DATASET_CATALOG_BUILDER_VERSION,
        "snapshot_id": snapshot_id,
        "catalog_content_id": catalog_content_id,
        "built_at": _iso(normalize_utc_datetime(built_at, "built_at")),
        "dataset_count": dataset_count,
        "catalog_file": {
            "relative_path": DATASET_CATALOG_CATALOG_FILENAME,
            "byte_size": catalog_byte_size,
            "sha256": catalog_sha256,
        },
    }


def manifest_payload_bytes(
    *,
    snapshot_id: str,
    catalog_content_id: str,
    dataset_count: int,
    built_at: datetime,
    catalog_byte_size: int,
    catalog_sha256: str,
) -> bytes:
    """Deterministic canonical ``manifest.json`` bytes of one snapshot."""
    return _canonical_json_bytes(
        manifest_payload_dict(
            snapshot_id=snapshot_id,
            catalog_content_id=catalog_content_id,
            dataset_count=dataset_count,
            built_at=built_at,
            catalog_byte_size=catalog_byte_size,
            catalog_sha256=catalog_sha256,
        )
    )


# ---------------------------------------------------------------------------
# Parser side (strict exact-field typed reconstruction; canonical bytes).
# ---------------------------------------------------------------------------


def _parse_json_object(payload: bytes, label: str) -> dict:
    """UTF-8 without BOM, JSON object with an exact field set; the field
    set itself is checked by the caller."""
    if payload.startswith(_UTF8_BOM):
        raise DatasetCatalogError(f"{label} must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetCatalogError(f"{label} is not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetCatalogError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DatasetCatalogError(f"{label} must be a JSON object")
    return data


def _require_exact_fields(
    data: Mapping, expected: frozenset, label: str
) -> None:
    unknown = sorted(set(data) - set(expected))
    if unknown:
        raise DatasetCatalogError(f"{label} unknown field(s): {', '.join(unknown)}")
    missing = sorted(set(expected) - set(data))
    if missing:
        raise DatasetCatalogError(f"{label} missing field(s): {', '.join(missing)}")


def _require_string(value, label: str) -> str:
    if not isinstance(value, str):
        raise DatasetCatalogError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    return value


def _require_non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise DatasetCatalogError(
            f"{label} must be a real non-negative integer, got {value!r}"
        )
    return value


def _parse_datetime(value, label: str) -> datetime:
    if not isinstance(value, str):
        raise DatasetCatalogError(
            f"{label} must be an ISO datetime string, got {type(value).__name__}"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DatasetCatalogError(
            f"{label} must be a valid ISO datetime, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise DatasetCatalogError(
            f"{label} must be timezone-aware, got a naive value {value!r}"
        )
    return normalize_utc_datetime(parsed, label)


def _parse_date(value, label: str) -> date:
    if not isinstance(value, str):
        raise DatasetCatalogError(
            f"{label} must be an ISO date string, got {type(value).__name__}"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DatasetCatalogError(
            f"{label} must be a valid ISO date, got {value!r}"
        ) from exc


def _parse_scope(data: dict) -> DatasetScope:
    _require_exact_fields(data, _SCOPE_FIELDS, "dataset_facts.scope")
    try:
        return DatasetScope(
            symbols=tuple(
                _require_string(symbol, "scope.symbols entry")
                for symbol in data["symbols"]
            ),
            trade_dates=tuple(
                _parse_date(trade_date, "scope.trade_dates entry")
                for trade_date in data["trade_dates"]
            ),
            adjustment=_require_string(data["adjustment"], "scope.adjustment"),
            interval=_require_string(data["interval"], "scope.interval"),
            requested_session=_require_string(
                data["requested_session"], "scope.requested_session"
            ),
        )
    except TypeError as exc:
        raise DatasetCatalogError(
            f"dataset_facts.scope.symbols / trade_dates must be JSON arrays: {exc}"
        ) from exc


def _parse_spec_pin(data: dict, label: str) -> SpecPin:
    _require_exact_fields(data, _SPEC_PIN_FIELDS, label)
    return SpecPin(
        kind=_require_string(data["kind"], f"{label}.kind"),
        name=_require_string(data["name"], f"{label}.name"),
        version=_require_string(data["version"], f"{label}.version"),
        content_sha256=_require_string(
            data["content_sha256"], f"{label}.content_sha256"
        ),
    )


def _parse_source_snapshot(data: dict, label: str) -> SourceSnapshotPin:
    _require_exact_fields(data, _SOURCE_SNAPSHOT_FIELDS, label)
    return SourceSnapshotPin(
        ingestion_run_id=_require_string(
            data["ingestion_run_id"], f"{label}.ingestion_run_id"
        ),
        physical_snapshot_hash=_require_string(
            data["physical_snapshot_hash"], f"{label}.physical_snapshot_hash"
        ),
        logical_source_rows_hash=_require_string(
            data["logical_source_rows_hash"], f"{label}.logical_source_rows_hash"
        ),
        source_schema_version=_require_string(
            data["source_schema_version"], f"{label}.source_schema_version"
        ),
        requested_trade_date=_parse_date(
            data["requested_trade_date"], f"{label}.requested_trade_date"
        ),
        requested_session=_require_string(
            data["requested_session"], f"{label}.requested_session"
        ),
    )


def _parse_canonical_build_pin(data: dict, label: str) -> CanonicalBuildPin:
    _require_exact_fields(data, _CANONICAL_BUILD_PIN_FIELDS, label)
    try:
        snapshots_data = data["source_snapshots"]
    except KeyError:
        raise DatasetCatalogError(f"{label} missing field(s): source_snapshots")
    if not isinstance(snapshots_data, list):
        raise DatasetCatalogError(
            f"{label}.source_snapshots must be a JSON array"
        )
    try:
        return CanonicalBuildPin(
            canonical_build_id=_require_string(
                data["canonical_build_id"], f"{label}.canonical_build_id"
            ),
            canonical_content_id=_require_string(
                data["canonical_content_id"], f"{label}.canonical_content_id"
            ),
            canonical_builder_version=_require_string(
                data["canonical_builder_version"],
                f"{label}.canonical_builder_version",
            ),
            canonical_schema_version=_require_string(
                data["canonical_schema_version"],
                f"{label}.canonical_schema_version",
            ),
            materializer_version=_require_string(
                data["materializer_version"], f"{label}.materializer_version"
            ),
            gap_policy_version=_require_string(
                data["gap_policy_version"], f"{label}.gap_policy_version"
            ),
            gap_content_id=_require_string(
                data["gap_content_id"], f"{label}.gap_content_id"
            ),
            status=_require_string(data["status"], f"{label}.status"),
            canonical_row_version_ids=tuple(
                _require_string(version, f"{label}.canonical_row_version_ids entry")
                for version in data["canonical_row_version_ids"]
            ),
            source_snapshots=tuple(
                _parse_source_snapshot(
                    item, f"{label}.source_snapshots entry"
                )
                for item in snapshots_data
            ),
        )
    except TypeError as exc:
        raise DatasetCatalogError(
            f"{label}.canonical_row_version_ids must be a JSON array: {exc}"
        ) from exc


def _parse_completion_entry(data: dict, label: str) -> CompletionEntry:
    _require_exact_fields(data, _COMPLETION_ENTRY_FIELDS, label)
    return CompletionEntry(
        code=_require_string(data["code"], f"{label}.code"),
        trade_date=_parse_date(data["trade_date"], f"{label}.trade_date"),
        status=_require_string(data["status"], f"{label}.status"),
        reason_code=(
            _require_string(data["reason_code"], f"{label}.reason_code")
            if data["reason_code"] is not None
            else None
        ),
    )


def _parse_completion(data: dict) -> CompletionSummary:
    _require_exact_fields(data, _COMPLETION_FIELDS, "dataset_facts.completion")
    try:
        entries_data = data["entries"]
    except KeyError:
        raise DatasetCatalogError(
            "dataset_facts.completion missing field(s): entries"
        )
    if not isinstance(entries_data, list):
        raise DatasetCatalogError(
            "dataset_facts.completion.entries must be a JSON array"
        )
    return CompletionSummary(
        complete_count=_require_non_negative_int(
            data["complete_count"], "dataset_facts.completion.complete_count"
        ),
        incomplete_count=_require_non_negative_int(
            data["incomplete_count"], "dataset_facts.completion.incomplete_count"
        ),
        missing_count=_require_non_negative_int(
            data["missing_count"], "dataset_facts.completion.missing_count"
        ),
        entries=tuple(
            _parse_completion_entry(item, "dataset_facts.completion.entries entry")
            for item in entries_data
        ),
    )


def _parse_facts(data: dict) -> DatasetCatalogDatasetFacts:
    _require_exact_fields(data, _FACTS_FIELDS, "dataset_facts")
    try:
        feature_data = data["feature_spec_pins"]
        label_data = data["label_spec_pins"]
        canonical_data = data["canonical_build_pins"]
        row_version_data = data["canonical_row_version_ids"]
    except KeyError:
        raise DatasetCatalogError("dataset_facts missing array field(s)")
    for name, items in (
        ("feature_spec_pins", feature_data),
        ("label_spec_pins", label_data),
        ("canonical_build_pins", canonical_data),
        ("canonical_row_version_ids", row_version_data),
    ):
        if not isinstance(items, list):
            raise DatasetCatalogError(
                f"dataset_facts.{name} must be a JSON array"
            )
    split_pin_data = data["split_spec_pin"]
    if split_pin_data is not None and not isinstance(split_pin_data, dict):
        raise DatasetCatalogError(
            "dataset_facts.split_spec_pin must be a JSON object or null"
        )
    dataset_as_of_value = data["dataset_as_of"]
    if dataset_as_of_value is not None:
        dataset_as_of = _parse_datetime(
            dataset_as_of_value, "dataset_facts.dataset_as_of"
        )
    else:
        dataset_as_of = None
    return DatasetCatalogDatasetFacts(
        dataset_id=_require_string(data["dataset_id"], "dataset_facts.dataset_id"),
        dataset_kind=_require_string(
            data["dataset_kind"], "dataset_facts.dataset_kind"
        ),
        status=_require_string(data["status"], "dataset_facts.status"),
        logical_row_count=_require_non_negative_int(
            data["logical_row_count"], "dataset_facts.logical_row_count"
        ),
        dataset_schema_id=_require_string(
            data["dataset_schema_id"], "dataset_facts.dataset_schema_id"
        ),
        logical_dataset_content_id=_require_string(
            data["logical_dataset_content_id"],
            "dataset_facts.logical_dataset_content_id",
        ),
        dataset_as_of=dataset_as_of,
        scope=_parse_scope(data["scope"]),
        feature_spec_pins=tuple(
            _parse_spec_pin(item, "dataset_facts.feature_spec_pins entry")
            for item in feature_data
        ),
        label_spec_pins=tuple(
            _parse_spec_pin(item, "dataset_facts.label_spec_pins entry")
            for item in label_data
        ),
        split_spec_pin=(
            _parse_spec_pin(
                split_pin_data, "dataset_facts.split_spec_pin"
            )
            if split_pin_data is not None
            else None
        ),
        canonical_build_pins=tuple(
            _parse_canonical_build_pin(
                item, "dataset_facts.canonical_build_pins entry"
            )
            for item in canonical_data
        ),
        canonical_row_version_ids=tuple(
            _require_string(
                version, "dataset_facts.canonical_row_version_ids entry"
            )
            for version in row_version_data
        ),
        completion=_parse_completion(data["completion"]),
    )


def _parse_dataset_record(data: dict) -> ParsedCatalogEntry:
    _require_exact_fields(data, _DATASET_RECORD_FIELDS, "datasets entry")
    facts_data = data["dataset_facts"]
    if not isinstance(facts_data, dict):
        raise DatasetCatalogError(
            "datasets entry dataset_facts must be a JSON object"
        )
    observed_data = data["observed_metadata"]
    if not isinstance(observed_data, dict):
        raise DatasetCatalogError(
            "datasets entry observed_metadata must be a JSON object"
        )
    _require_exact_fields(
        observed_data, _OBSERVED_METADATA_FIELDS, "observed_metadata"
    )
    return ParsedCatalogEntry(
        content_id=_require_string(data["content_id"], "datasets entry content_id"),
        dataset_facts=_parse_facts(facts_data),
        observed_built_at=_parse_datetime(
            observed_data["built_at"], "observed_metadata.built_at"
        ),
        observed_build_path=_require_string(
            observed_data["build_path"], "observed_metadata.build_path"
        ),
    )


def _parse_catalog_bytes(payload: bytes) -> ParsedCatalogPayload:
    data = _parse_json_object(payload, "catalog.json")
    _require_exact_fields(data, _CATALOG_TOP_LEVEL_FIELDS, "catalog.json")
    if data["snapshot_schema_version"] != DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION:
        raise DatasetCatalogError(
            "catalog.json snapshot_schema_version must be "
            f"{DATASET_CATALOG_SNAPSHOT_SCHEMA_VERSION}, got "
            f"{data['snapshot_schema_version']!r}"
        )
    if data["catalog_contract_version"] != DATASET_CATALOG_CONTRACT_VERSION:
        raise DatasetCatalogError(
            "catalog.json catalog_contract_version must be "
            f"{DATASET_CATALOG_CONTRACT_VERSION}, got "
            f"{data['catalog_contract_version']!r}"
        )
    if (
        data["catalog_entry_schema_version"]
        != DATASET_CATALOG_ENTRY_SCHEMA_VERSION
    ):
        raise DatasetCatalogError(
            "catalog.json catalog_entry_schema_version must be "
            f"{DATASET_CATALOG_ENTRY_SCHEMA_VERSION}, got "
            f"{data['catalog_entry_schema_version']!r}"
        )
    if data["catalog_content_id_version"] != DATASET_CATALOG_CONTENT_ID_VERSION:
        raise DatasetCatalogError(
            "catalog.json catalog_content_id_version must be "
            f"{DATASET_CATALOG_CONTENT_ID_VERSION}, got "
            f"{data['catalog_content_id_version']!r}"
        )
    if data["builder_version"] != DATASET_CATALOG_BUILDER_VERSION:
        raise DatasetCatalogError(
            "catalog.json builder_version must be "
            f"{DATASET_CATALOG_BUILDER_VERSION}, got "
            f"{data['builder_version']!r}"
        )
    datasets_data = data["datasets"]
    if not isinstance(datasets_data, list):
        raise DatasetCatalogError("catalog.json datasets must be a JSON array")
    entries = tuple(
        _parse_dataset_record(item) for item in datasets_data
    )
    # Canonical bytes: re-serializing the strictly parsed typed records
    # must reproduce the actual bytes exactly.
    serialized = tuple(
        _SerializedEntry(
            content_id=entry.content_id,
            dataset_facts=entry.dataset_facts,
            observed_built_at=entry.observed_built_at,
            observed_build_path=entry.observed_build_path,
        )
        for entry in entries
    )
    rebuilt = _canonical_json_bytes(
        _catalog_payload_dict(serialized, data["builder_version"])
    )
    if rebuilt != payload:
        raise DatasetCatalogError(
            "catalog.json must be the exact canonical serialization of the "
            "parsed records (any formatting, key-order, whitespace, BOM, or "
            "timestamp-representation difference is rejected)"
        )
    return ParsedCatalogPayload(
        snapshot_schema_version=data["snapshot_schema_version"],
        catalog_contract_version=data["catalog_contract_version"],
        catalog_entry_schema_version=data["catalog_entry_schema_version"],
        catalog_content_id_version=data["catalog_content_id_version"],
        builder_version=data["builder_version"],
        catalog_content_id=_require_string(
            data["catalog_content_id"], "catalog.json catalog_content_id"
        ),
        dataset_count=_require_non_negative_int(
            data["dataset_count"], "catalog.json dataset_count"
        ),
        entries=entries,
    )


def parse_catalog_bytes(payload: bytes) -> ParsedCatalogPayload:
    """Strict exact-field parse of ``catalog.json`` bytes into the frozen
    typed records (fail closed on every violation; the canonical-bytes
    equality is enforced inside)."""
    if not isinstance(payload, bytes):
        raise DatasetCatalogError(
            f"catalog payload must be bytes, got {type(payload).__name__}"
        )
    try:
        return _parse_catalog_bytes(payload)
    except DatasetCatalogError:
        raise
    except (DatasetError, TypeError, ValueError, KeyError) as exc:
        raise DatasetCatalogError(f"invalid catalog.json: {exc}") from exc


def _parse_manifest_bytes(payload: bytes) -> ParsedManifestPayload:
    data = _parse_json_object(payload, "manifest.json")
    _require_exact_fields(data, _MANIFEST_FIELDS, "manifest.json")
    if data["manifest_schema_version"] != DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION:
        raise DatasetCatalogError(
            "manifest.json manifest_schema_version must be "
            f"{DATASET_CATALOG_SNAPSHOT_MANIFEST_VERSION}, got "
            f"{data['manifest_schema_version']!r}"
        )
    if data["snapshot_id_version"] != DATASET_CATALOG_SNAPSHOT_ID_VERSION:
        raise DatasetCatalogError(
            "manifest.json snapshot_id_version must be "
            f"{DATASET_CATALOG_SNAPSHOT_ID_VERSION}, got "
            f"{data['snapshot_id_version']!r}"
        )
    if data["materializer_version"] != DATASET_CATALOG_MATERIALIZER_VERSION:
        raise DatasetCatalogError(
            "manifest.json materializer_version must be "
            f"{DATASET_CATALOG_MATERIALIZER_VERSION}, got "
            f"{data['materializer_version']!r}"
        )
    if data["builder_version"] != DATASET_CATALOG_BUILDER_VERSION:
        raise DatasetCatalogError(
            "manifest.json builder_version must be "
            f"{DATASET_CATALOG_BUILDER_VERSION}, got "
            f"{data['builder_version']!r}"
        )
    catalog_file_data = data["catalog_file"]
    if not isinstance(catalog_file_data, dict):
        raise DatasetCatalogError(
            "manifest.json catalog_file must be a JSON object"
        )
    _require_exact_fields(
        catalog_file_data, _CATALOG_FILE_FIELDS, "manifest.json catalog_file"
    )
    relative_path = _require_string(
        catalog_file_data["relative_path"],
        "manifest.json catalog_file.relative_path",
    )
    if relative_path != DATASET_CATALOG_CATALOG_FILENAME:
        raise DatasetCatalogError(
            "manifest.json catalog_file.relative_path must be exactly "
            f"{DATASET_CATALOG_CATALOG_FILENAME!r}, got {relative_path!r}"
        )
    rebuilt = _canonical_json_bytes(
        manifest_payload_dict(
            snapshot_id=_require_string(
                data["snapshot_id"], "manifest.json snapshot_id"
            ),
            catalog_content_id=_require_string(
                data["catalog_content_id"], "manifest.json catalog_content_id"
            ),
            dataset_count=_require_non_negative_int(
                data["dataset_count"], "manifest.json dataset_count"
            ),
            built_at=_parse_datetime(data["built_at"], "manifest.json built_at"),
            catalog_byte_size=_require_non_negative_int(
                catalog_file_data["byte_size"],
                "manifest.json catalog_file.byte_size",
            ),
            catalog_sha256=_require_string(
                catalog_file_data["sha256"], "manifest.json catalog_file.sha256"
            ),
        )
    )
    if rebuilt != payload:
        raise DatasetCatalogError(
            "manifest.json must be the exact canonical serialization of the "
            "parsed records (any formatting, key-order, whitespace, BOM, or "
            "timestamp-representation difference is rejected)"
        )
    return ParsedManifestPayload(
        manifest_schema_version=data["manifest_schema_version"],
        snapshot_id_version=data["snapshot_id_version"],
        materializer_version=data["materializer_version"],
        builder_version=data["builder_version"],
        snapshot_id=_require_string(data["snapshot_id"], "manifest.json snapshot_id"),
        catalog_content_id=_require_string(
            data["catalog_content_id"], "manifest.json catalog_content_id"
        ),
        built_at=_parse_datetime(data["built_at"], "manifest.json built_at"),
        dataset_count=_require_non_negative_int(
            data["dataset_count"], "manifest.json dataset_count"
        ),
        catalog_relative_path=relative_path,
        catalog_byte_size=_require_non_negative_int(
            catalog_file_data["byte_size"],
            "manifest.json catalog_file.byte_size",
        ),
        catalog_sha256=_require_string(
            catalog_file_data["sha256"], "manifest.json catalog_file.sha256"
        ),
    )


def parse_manifest_bytes(payload: bytes) -> ParsedManifestPayload:
    """Strict exact-field parse of ``manifest.json`` bytes into the frozen
    typed record (fail closed on every violation; the canonical-bytes
    equality is enforced inside)."""
    if not isinstance(payload, bytes):
        raise DatasetCatalogError(
            f"manifest payload must be bytes, got {type(payload).__name__}"
        )
    try:
        return _parse_manifest_bytes(payload)
    except DatasetCatalogError:
        raise
    except (DatasetError, TypeError, ValueError, KeyError) as exc:
        raise DatasetCatalogError(f"invalid manifest.json: {exc}") from exc
