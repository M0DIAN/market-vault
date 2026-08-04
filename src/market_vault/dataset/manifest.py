"""Versioned derived-dataset manifest contract.

The Dataset manifest is the authority describing one derived dataset build:
logical content identity, output logical schema, normalized scope,
``dataset_as_of`` cutoff, pinned immutable Canonical builds and row versions,
Feature/Label/Split/Transform fingerprints, the per-key completion summary,
gap references, the declared serialization contract, and recorded output-file
facts.

Serialization is deterministic: UTF-8, sorted JSON keys, compact separators,
``ensure_ascii=True`` (fixed and documented), stable list ordering, UTC
microsecond ISO timestamps, and a trailing newline. Every manifest is
re-validated for identity consistency before serialization, and only the
current manifest schema version may be built, serialized, or parsed.
``built_at`` and output file byte hashes are recorded facts; they never enter
``dataset_id``.

This core writes exactly one standalone manifest file. It does not commit a
Dataset build directory, does not create ``_SUCCESS``, and does not read or
write Dataset Parquet.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .content import dataset_schema_id
from .encoding import DatasetError, normalize_utc_datetime
from .identity import dataset_id, normalize_dataset_identity_input
from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    CanonicalBuildPin,
    CompletionEntry,
    CompletionSummary,
    DatasetField,
    DatasetIdentityInput,
    DatasetManifest,
    DatasetOutputFile,
    DatasetSchema,
    DatasetScope,
    GapReference,
    ImplementationPin,
    SourceSnapshotPin,
    SpecPin,
)

__all__ = [
    "build_dataset_manifest",
    "serialize_dataset_manifest",
    "validate_dataset_manifest",
    "write_dataset_manifest_atomic",
]

_TOP_LEVEL_FIELDS = {
    "manifest_schema_version",
    "dataset_id",
    "dataset_kind",
    "status",
    "built_at",
    "dataset_as_of",
    "logical_dataset_content_id",
    "dataset_schema_id",
    "schema",
    "scope",
    "canonical_builds",
    "canonical_row_version_ids",
    "feature_specs",
    "label_specs",
    "split_spec",
    "implementations",
    "completion",
    "gap_references",
    "serialization_format",
    "serialization_format_version",
    "logical_row_count",
    "output_files",
}


def _datetime_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # Values are UTC-normalized at model construction; force the explicit
    # microsecond format so every serialized instant has the same shape.
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _canonical_build_payload(pin: CanonicalBuildPin) -> dict:
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
            {
                "ingestion_run_id": snapshot.ingestion_run_id,
                "physical_snapshot_hash": snapshot.physical_snapshot_hash,
                "logical_source_rows_hash": snapshot.logical_source_rows_hash,
                "source_schema_version": snapshot.source_schema_version,
                "requested_trade_date": snapshot.requested_trade_date.isoformat(),
                "requested_session": snapshot.requested_session,
            }
            for snapshot in pin.source_snapshots
        ],
    }


def _spec_payload(spec: SpecPin) -> dict:
    return {
        "kind": spec.kind,
        "name": spec.name,
        "version": spec.version,
        "content_sha256": spec.content_sha256,
    }


def _implementation_payload(item: ImplementationPin) -> dict:
    return {
        "name": item.name,
        "version": item.version,
        "content_sha256": item.content_sha256,
    }


def _output_file_payload(record: DatasetOutputFile) -> dict:
    return {
        "relative_path": record.relative_path,
        "file_role": record.file_role,
        "row_count": record.row_count,
        "byte_size": record.byte_size,
        "sha256": record.sha256,
        "content_role": record.content_role,
    }


def _manifest_payload(manifest: DatasetManifest) -> dict:
    return {
        "manifest_schema_version": manifest.manifest_schema_version,
        "dataset_id": manifest.dataset_id,
        "dataset_kind": manifest.dataset_kind,
        "status": manifest.status,
        "built_at": _datetime_iso(manifest.built_at),
        "dataset_as_of": _datetime_iso(manifest.dataset_as_of),
        "logical_dataset_content_id": manifest.logical_dataset_content_id,
        "dataset_schema_id": manifest.dataset_schema_id,
        "schema": {
            "fields": [
                {
                    "name": field.name,
                    "logical_type": field.logical_type,
                    "nullable": field.nullable,
                }
                for field in manifest.schema.fields
            ]
        },
        "scope": {
            "symbols": list(manifest.scope.symbols),
            "trade_dates": [value.isoformat() for value in manifest.scope.trade_dates],
            "adjustment": manifest.scope.adjustment,
            "interval": manifest.scope.interval,
            "requested_session": manifest.scope.requested_session,
        },
        "canonical_builds": [
            _canonical_build_payload(pin) for pin in manifest.canonical_builds
        ],
        "canonical_row_version_ids": list(manifest.canonical_row_version_ids),
        "feature_specs": [_spec_payload(spec) for spec in manifest.feature_specs],
        "label_specs": [_spec_payload(spec) for spec in manifest.label_specs],
        "split_spec": _spec_payload(manifest.split_spec) if manifest.split_spec else None,
        "implementations": [
            _implementation_payload(item) for item in manifest.implementations
        ],
        "completion": {
            "complete_count": manifest.completion.complete_count,
            "incomplete_count": manifest.completion.incomplete_count,
            "missing_count": manifest.completion.missing_count,
            "entries": [
                {
                    "code": entry.code,
                    "trade_date": entry.trade_date.isoformat(),
                    "status": entry.status,
                    "reason_code": entry.reason_code,
                }
                for entry in manifest.completion.entries
            ],
        },
        "gap_references": [
            {
                "canonical_build_id": ref.canonical_build_id,
                "gap_content_id": ref.gap_content_id,
                "gap_range_count": ref.gap_range_count,
            }
            for ref in manifest.gap_references
        ],
        "serialization_format": manifest.serialization_format,
        "serialization_format_version": manifest.serialization_format_version,
        "logical_row_count": manifest.logical_row_count,
        "output_files": [
            _output_file_payload(record) for record in manifest.output_files
        ],
    }


def _identity_input_from_manifest(manifest: DatasetManifest) -> DatasetIdentityInput:
    return DatasetIdentityInput(
        dataset_kind=manifest.dataset_kind,
        scope=manifest.scope,
        dataset_as_of=manifest.dataset_as_of,
        schema=manifest.schema,
        dataset_schema_id=manifest.dataset_schema_id,
        logical_dataset_content_id=manifest.logical_dataset_content_id,
        canonical_builds=manifest.canonical_builds,
        canonical_row_version_ids=manifest.canonical_row_version_ids,
        feature_specs=manifest.feature_specs,
        label_specs=manifest.label_specs,
        split_spec=manifest.split_spec,
        implementations=manifest.implementations,
        completion=manifest.completion,
        gap_references=manifest.gap_references,
        manifest_schema_version=manifest.manifest_schema_version,
        serialization_format=manifest.serialization_format,
        serialization_format_version=manifest.serialization_format_version,
    )


def build_dataset_manifest(
    identity_input: DatasetIdentityInput,
    *,
    built_at: datetime,
    status: str,
    logical_row_count: int,
    output_files: tuple[DatasetOutputFile, ...] = (),
) -> DatasetManifest:
    """Deterministic manifest for one derived dataset build.

    ``dataset_id`` is independently recomputed from the identity-bearing
    fields and never trusted from any caller-supplied value. ``built_at`` and
    output-file facts are recorded but never enter ``dataset_id``. No Dataset
    Parquet writer exists yet; ``output_files`` may be empty.
    """
    normalized = normalize_dataset_identity_input(identity_input)
    if normalized.manifest_schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
        raise DatasetError(
            f"manifest schema version {normalized.manifest_schema_version!r} is not "
            f"supported; only {DATASET_MANIFEST_SCHEMA_VERSION!r} is supported by "
            f"this manifest core"
        )
    computed_id = dataset_id(normalized)
    built_at = normalize_utc_datetime(built_at, "built_at")
    if status not in (STATUS_COMPLETE, STATUS_EMPTY):
        raise DatasetError(f"manifest status must be COMPLETE or EMPTY, got {status!r}")
    if type(logical_row_count) is not int or logical_row_count < 0:
        raise DatasetError("logical_row_count must be a non-negative integer")
    return DatasetManifest(
        manifest_schema_version=normalized.manifest_schema_version,
        dataset_id=computed_id,
        dataset_kind=normalized.dataset_kind,
        status=status,
        built_at=built_at,
        dataset_as_of=normalized.dataset_as_of,
        logical_dataset_content_id=normalized.logical_dataset_content_id,
        dataset_schema_id=normalized.dataset_schema_id,
        schema=normalized.schema,
        scope=normalized.scope,
        canonical_builds=normalized.canonical_builds,
        canonical_row_version_ids=normalized.canonical_row_version_ids,
        feature_specs=normalized.feature_specs,
        label_specs=normalized.label_specs,
        split_spec=normalized.split_spec,
        implementations=normalized.implementations,
        completion=normalized.completion,
        gap_references=normalized.gap_references,
        serialization_format=normalized.serialization_format,
        serialization_format_version=normalized.serialization_format_version,
        logical_row_count=logical_row_count,
        output_files=tuple(output_files),
    )


def _validate_manifest_consistency(manifest: DatasetManifest) -> None:
    """Re-validate one manifest before serialization or after parsing.

    A manually constructed or ``dataclasses.replace``-modified inconsistent
    manifest must never serialize. At minimum re-verifies: the stored
    ``dataset_schema_id`` equals the schema recomputation; the stored
    ``dataset_id`` equals the identity-bearing-field recomputation; spec
    containers hold the right kinds; Canonical build pins are unique; row
    versions are covered by the pinned builds; gap references are unique and
    consistent with the pinned builds; status/``logical_row_count``
    combinations are valid; ``built_at`` is timezone-aware; and output
    relative paths are unique.
    """
    if not isinstance(manifest, DatasetManifest):
        raise DatasetError(
            f"manifest must be a DatasetManifest, got {type(manifest).__name__}"
        )
    if manifest.manifest_schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
        raise DatasetError(
            f"manifest schema version {manifest.manifest_schema_version!r} is not "
            f"supported; only {DATASET_MANIFEST_SCHEMA_VERSION!r} is supported by "
            f"this manifest core"
        )
    if manifest.status not in (STATUS_COMPLETE, STATUS_EMPTY):
        raise DatasetError(
            f"manifest status must be COMPLETE or EMPTY, got {manifest.status!r}"
        )
    if manifest.status == STATUS_EMPTY and manifest.logical_row_count != 0:
        raise DatasetError("status EMPTY requires logical_row_count == 0")
    if manifest.status == STATUS_COMPLETE and manifest.logical_row_count == 0:
        raise DatasetError(
            "status COMPLETE requires at least one logical row; zero rows must be EMPTY"
        )
    if not isinstance(manifest.built_at, datetime) or manifest.built_at.tzinfo is None:
        raise DatasetError("manifest built_at must be a timezone-aware datetime")
    expected_schema_id = dataset_schema_id(manifest.schema)
    if manifest.dataset_schema_id != expected_schema_id:
        raise DatasetError(
            "stored dataset_schema_id does not match the declared schema"
        )
    expected_dataset_id = dataset_id(_identity_input_from_manifest(manifest))
    if manifest.dataset_id != expected_dataset_id:
        raise DatasetError(
            "stored dataset_id does not match the identity-bearing fields"
        )
    for record in manifest.output_files:
        if not isinstance(record, DatasetOutputFile):
            raise DatasetError(
                f"output_files must contain DatasetOutputFile instances, "
                f"got {type(record).__name__}"
            )
    paths = [record.relative_path for record in manifest.output_files]
    if len(set(paths)) != len(paths):
        raise DatasetError("duplicate output file relative_path")


def serialize_dataset_manifest(manifest: DatasetManifest) -> bytes:
    """Deterministic UTF-8 JSON with sorted keys, compact separators,
    ``ensure_ascii=True``, stable list ordering, UTC microsecond ISO
    timestamps, and a trailing newline.

    The manifest is re-validated for identity consistency first: an
    inconsistent or unsupported-version manifest is never serialized."""
    if not isinstance(manifest, DatasetManifest):
        raise DatasetError(
            f"serialize_dataset_manifest requires a DatasetManifest, "
            f"got {type(manifest).__name__}"
        )
    _validate_manifest_consistency(manifest)
    text = json.dumps(
        _manifest_payload(manifest),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return (text + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Strict parsing (used by validate_dataset_manifest).
# ---------------------------------------------------------------------------


def _require_mapping(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise DatasetError(f"{label} must be an object")
    return value


def _require_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise DatasetError(f"{label} must be a list")
    return value


def _require_string(value, label: str) -> str:
    if not isinstance(value, str):
        raise DatasetError(f"{label} must be a string, got {type(value).__name__}")
    return value


def _parse_datetime_iso(value, label: str) -> datetime:
    if not isinstance(value, str):
        raise DatasetError(f"{label} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DatasetError(f"{label} must be an ISO datetime, got {value!r}") from exc
    if parsed.tzinfo is None:
        raise DatasetError(f"{label} must be timezone-aware, got naive {value!r}")
    return normalize_utc_datetime(parsed, label)


def _parse_date_iso(value, label: str) -> date:
    if not isinstance(value, str):
        raise DatasetError(f"{label} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DatasetError(f"{label} must be an ISO date, got {value!r}") from exc


def _parse_int(value, label: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise DatasetError(f"{label} must be an integer, got {type(value).__name__}")
    return value


def _parse_bool(value, label: str) -> bool:
    if type(value) is not bool:
        raise DatasetError(f"{label} must be a bool, got {type(value).__name__}")
    return value


def _parse_schema(value) -> DatasetSchema:
    section = _require_mapping(value, "schema")
    unknown = sorted(set(section) - {"fields"})
    if unknown:
        raise DatasetError(f"schema unknown field(s): {', '.join(unknown)}")
    if "fields" not in section:
        raise DatasetError("schema missing required field 'fields'")
    fields = []
    for index, item in enumerate(_require_list(section["fields"], "schema.fields")):
        record = _require_mapping(item, f"schema.fields[{index}]")
        missing = sorted({"name", "logical_type", "nullable"} - set(record))
        if missing:
            raise DatasetError(
                f"schema.fields[{index}] missing required field(s): {', '.join(missing)}"
            )
        unknown = sorted(set(record) - {"name", "logical_type", "nullable"})
        if unknown:
            raise DatasetError(
                f"schema.fields[{index}] unknown field(s): {', '.join(unknown)}"
            )
        fields.append(
            DatasetField(
                name=_require_string(record["name"], f"schema.fields[{index}].name"),
                logical_type=_require_string(record["logical_type"], f"schema.fields[{index}].logical_type"),
                nullable=_parse_bool(record["nullable"], f"schema.fields[{index}].nullable"),
            )
        )
    return DatasetSchema(tuple(fields))


def _parse_scope(value) -> DatasetScope:
    section = _require_mapping(value, "scope")
    required = {"symbols", "trade_dates", "adjustment", "interval", "requested_session"}
    missing = sorted(required - set(section))
    if missing:
        raise DatasetError(f"scope missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(section) - required)
    if unknown:
        raise DatasetError(f"scope unknown field(s): {', '.join(unknown)}")
    symbols = [
        _require_string(item, "scope.symbols") for item in _require_list(section["symbols"], "scope.symbols")
    ]
    trade_dates = [
        _parse_date_iso(item, "scope.trade_dates")
        for item in _require_list(section["trade_dates"], "scope.trade_dates")
    ]
    return DatasetScope(
        symbols=symbols,
        trade_dates=trade_dates,
        adjustment=_require_string(section["adjustment"], "scope.adjustment"),
        interval=_require_string(section["interval"], "scope.interval"),
        requested_session=_require_string(section["requested_session"], "scope.requested_session"),
    )


def _parse_source_snapshot(value) -> SourceSnapshotPin:
    record = _require_mapping(value, "source_snapshots")
    required = {
        "ingestion_run_id",
        "physical_snapshot_hash",
        "logical_source_rows_hash",
        "source_schema_version",
        "requested_trade_date",
        "requested_session",
    }
    missing = sorted(required - set(record))
    if missing:
        raise DatasetError(f"source snapshot missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(record) - required)
    if unknown:
        raise DatasetError(f"source snapshot unknown field(s): {', '.join(unknown)}")
    return SourceSnapshotPin(
        ingestion_run_id=_require_string(record["ingestion_run_id"], "ingestion_run_id"),
        physical_snapshot_hash=_require_string(record["physical_snapshot_hash"], "physical_snapshot_hash"),
        logical_source_rows_hash=_require_string(record["logical_source_rows_hash"], "logical_source_rows_hash"),
        source_schema_version=_require_string(record["source_schema_version"], "source_schema_version"),
        requested_trade_date=_parse_date_iso(record["requested_trade_date"], "requested_trade_date"),
        requested_session=_require_string(record["requested_session"], "requested_session"),
    )


def _parse_canonical_build(value) -> CanonicalBuildPin:
    record = _require_mapping(value, "canonical_builds")
    required = {
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
    missing = sorted(required - set(record))
    if missing:
        raise DatasetError(
            f"canonical build pin missing required field(s): {', '.join(missing)}"
        )
    unknown = sorted(set(record) - required)
    if unknown:
        raise DatasetError(f"canonical build pin unknown field(s): {', '.join(unknown)}")
    return CanonicalBuildPin(
        canonical_build_id=_require_string(record["canonical_build_id"], "canonical_build_id"),
        canonical_content_id=_require_string(record["canonical_content_id"], "canonical_content_id"),
        canonical_builder_version=_require_string(record["canonical_builder_version"], "canonical_builder_version"),
        canonical_schema_version=_require_string(record["canonical_schema_version"], "canonical_schema_version"),
        materializer_version=_require_string(record["materializer_version"], "materializer_version"),
        gap_policy_version=_require_string(record["gap_policy_version"], "gap_policy_version"),
        gap_content_id=_require_string(record["gap_content_id"], "gap_content_id"),
        status=_require_string(record["status"], "canonical build status"),
        canonical_row_version_ids=[
            _require_string(item, "canonical_row_version_ids")
            for item in _require_list(record["canonical_row_version_ids"], "canonical_row_version_ids")
        ],
        source_snapshots=[
            _parse_source_snapshot(item)
            for item in _require_list(record["source_snapshots"], "source_snapshots")
        ],
    )


def _parse_spec(value, label: str) -> SpecPin:
    record = _require_mapping(value, label)
    required = {"kind", "name", "version", "content_sha256"}
    missing = sorted(required - set(record))
    if missing:
        raise DatasetError(f"{label} missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(record) - required)
    if unknown:
        raise DatasetError(f"{label} unknown field(s): {', '.join(unknown)}")
    return SpecPin(
        kind=_require_string(record["kind"], f"{label}.kind"),
        name=_require_string(record["name"], f"{label}.name"),
        version=_require_string(record["version"], f"{label}.version"),
        content_sha256=_require_string(record["content_sha256"], f"{label}.content_sha256"),
    )


def _parse_implementation(value) -> ImplementationPin:
    record = _require_mapping(value, "implementations")
    required = {"name", "version", "content_sha256"}
    missing = sorted(required - set(record))
    if missing:
        raise DatasetError(f"implementation pin missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(record) - required)
    if unknown:
        raise DatasetError(f"implementation pin unknown field(s): {', '.join(unknown)}")
    content = record["content_sha256"]
    if content is not None:
        content = _require_string(content, "implementation content_sha256")
    return ImplementationPin(
        name=_require_string(record["name"], "implementation name"),
        version=_require_string(record["version"], "implementation version"),
        content_sha256=content,
    )


def _parse_completion(value) -> CompletionSummary:
    section = _require_mapping(value, "completion")
    required = {"complete_count", "incomplete_count", "missing_count", "entries"}
    missing = sorted(required - set(section))
    if missing:
        raise DatasetError(f"completion missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(section) - required)
    if unknown:
        raise DatasetError(f"completion unknown field(s): {', '.join(unknown)}")
    entries = []
    for index, item in enumerate(_require_list(section["entries"], "completion.entries")):
        record = _require_mapping(item, f"completion.entries[{index}]")
        missing = sorted({"code", "trade_date", "status", "reason_code"} - set(record))
        if missing:
            raise DatasetError(
                f"completion.entries[{index}] missing required field(s): {', '.join(missing)}"
            )
        unknown = sorted(set(record) - {"code", "trade_date", "status", "reason_code"})
        if unknown:
            raise DatasetError(
                f"completion.entries[{index}] unknown field(s): {', '.join(unknown)}"
            )
        reason = record["reason_code"]
        if reason is not None:
            reason = _require_string(reason, f"completion.entries[{index}].reason_code")
        entries.append(
            CompletionEntry(
                code=_require_string(record["code"], f"completion.entries[{index}].code"),
                trade_date=_parse_date_iso(record["trade_date"], f"completion.entries[{index}].trade_date"),
                status=_require_string(record["status"], f"completion.entries[{index}].status"),
                reason_code=reason,
            )
        )
    return CompletionSummary(
        complete_count=_parse_int(section["complete_count"], "completion.complete_count"),
        incomplete_count=_parse_int(section["incomplete_count"], "completion.incomplete_count"),
        missing_count=_parse_int(section["missing_count"], "completion.missing_count"),
        entries=tuple(entries),
    )


def _parse_gap_reference(value) -> GapReference:
    record = _require_mapping(value, "gap_references")
    required = {"canonical_build_id", "gap_content_id", "gap_range_count"}
    missing = sorted(required - set(record))
    if missing:
        raise DatasetError(f"gap reference missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(record) - required)
    if unknown:
        raise DatasetError(f"gap reference unknown field(s): {', '.join(unknown)}")
    return GapReference(
        canonical_build_id=_require_string(record["canonical_build_id"], "gap reference canonical_build_id"),
        gap_content_id=_require_string(record["gap_content_id"], "gap reference gap_content_id"),
        gap_range_count=_parse_int(record["gap_range_count"], "gap reference gap_range_count"),
    )


def _parse_output_file(value) -> DatasetOutputFile:
    record = _require_mapping(value, "output_files")
    required = {"relative_path", "file_role", "row_count", "byte_size", "sha256", "content_role"}
    missing = sorted(required - set(record))
    if missing:
        raise DatasetError(f"output file record missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(record) - required)
    if unknown:
        raise DatasetError(f"output file record unknown field(s): {', '.join(unknown)}")
    return DatasetOutputFile(
        relative_path=_require_string(record["relative_path"], "output relative_path"),
        file_role=_require_string(record["file_role"], "output file_role"),
        row_count=_parse_int(record["row_count"], "output row_count"),
        byte_size=_parse_int(record["byte_size"], "output byte_size"),
        sha256=_require_string(record["sha256"], "output sha256"),
        content_role=_require_string(record["content_role"], "output content_role"),
    )


def _parse_manifest(payload: dict) -> DatasetManifest:
    manifest_schema_version = _require_string(payload["manifest_schema_version"], "manifest_schema_version")
    dataset_as_of_value = payload["dataset_as_of"]
    dataset_as_of = (
        _parse_datetime_iso(dataset_as_of_value, "dataset_as_of")
        if dataset_as_of_value is not None
        else None
    )
    split_spec_value = payload["split_spec"]
    split_spec = _parse_spec(split_spec_value, "split_spec") if split_spec_value is not None else None
    return DatasetManifest(
        manifest_schema_version=manifest_schema_version,
        dataset_id=_require_string(payload["dataset_id"], "dataset_id"),
        dataset_kind=_require_string(payload["dataset_kind"], "dataset_kind"),
        status=_require_string(payload["status"], "status"),
        built_at=_parse_datetime_iso(payload["built_at"], "built_at"),
        dataset_as_of=dataset_as_of,
        logical_dataset_content_id=_require_string(payload["logical_dataset_content_id"], "logical_dataset_content_id"),
        dataset_schema_id=_require_string(payload["dataset_schema_id"], "dataset_schema_id"),
        schema=_parse_schema(payload["schema"]),
        scope=_parse_scope(payload["scope"]),
        canonical_builds=[
            _parse_canonical_build(item)
            for item in _require_list(payload["canonical_builds"], "canonical_builds")
        ],
        canonical_row_version_ids=[
            _require_string(item, "canonical_row_version_ids")
            for item in _require_list(payload["canonical_row_version_ids"], "canonical_row_version_ids")
        ],
        feature_specs=[
            _parse_spec(item, "feature_specs")
            for item in _require_list(payload["feature_specs"], "feature_specs")
        ],
        label_specs=[
            _parse_spec(item, "label_specs")
            for item in _require_list(payload["label_specs"], "label_specs")
        ],
        split_spec=split_spec,
        implementations=[
            _parse_implementation(item)
            for item in _require_list(payload["implementations"], "implementations")
        ],
        completion=_parse_completion(payload["completion"]),
        gap_references=[
            _parse_gap_reference(item)
            for item in _require_list(payload["gap_references"], "gap_references")
        ],
        serialization_format=_require_string(payload["serialization_format"], "serialization_format"),
        serialization_format_version=_require_string(payload["serialization_format_version"], "serialization_format_version"),
        logical_row_count=_parse_int(payload["logical_row_count"], "logical_row_count"),
        output_files=[
            _parse_output_file(item)
            for item in _require_list(payload["output_files"], "output_files")
        ],
    )


def validate_dataset_manifest(payload) -> DatasetManifest:
    """Strictly validate a serialized Dataset manifest and return the model.

    Accepts bytes, str, or an already-parsed object. Invalid UTF-8 bytes are
    reported as DatasetError, never as UnicodeDecodeError. Missing or unknown
    top-level fields fail; unsupported manifest schema versions are rejected
    before v1-shaped parsing; nested record shapes are validated; identity
    consistency is re-verified (schema ID and dataset ID recomputation,
    spec-container kinds, duplicate pins, row-version coverage, gap-reference
    uniqueness, status/count combinations, output paths). Round-tripping
    ``manifest -> deterministic JSON -> validated manifest`` preserves every
    logical field and identity.
    """
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DatasetError(f"manifest payload is not valid UTF-8: {exc}") from exc
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"manifest payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DatasetError(
            f"manifest payload must be a JSON object, got {type(payload).__name__}"
        )
    unknown = sorted(set(payload) - _TOP_LEVEL_FIELDS)
    if unknown:
        raise DatasetError(f"unknown manifest field(s): {', '.join(unknown)}")
    missing = sorted(_TOP_LEVEL_FIELDS - set(payload))
    if missing:
        raise DatasetError(f"missing manifest field(s): {', '.join(missing)}")
    # Reject unsupported schema versions before attempting v1-shaped parsing.
    if payload["manifest_schema_version"] != DATASET_MANIFEST_SCHEMA_VERSION:
        raise DatasetError(
            f"unsupported manifest schema version "
            f"{payload['manifest_schema_version']!r}; only "
            f"{DATASET_MANIFEST_SCHEMA_VERSION!r} is supported"
        )

    manifest = _parse_manifest(payload)
    _validate_manifest_consistency(manifest)
    return manifest


def _handle_existing_destination(path: Path, data: bytes, idempotent: bool) -> None:
    """Apply the overwrite policy to an existing destination.

    Default mode refuses; idempotent mode accepts only byte-identical
    content. Never touches or replaces the existing content otherwise.
    """
    if not idempotent:
        raise DatasetError(f"destination already exists: {path}")
    try:
        existing = path.read_bytes()
    except OSError as exc:
        raise DatasetError(
            f"failed to read existing destination {path}: {exc}"
        ) from exc
    if existing != data:
        raise DatasetError(
            f"destination exists with different manifest content: {path}"
        )


def write_dataset_manifest_atomic(
    path: Path,
    manifest: DatasetManifest,
    *,
    idempotent: bool = False,
) -> None:
    """Write exactly one manifest file atomically and never overwrite.

    The payload is serialized (and its identity consistency validated)
    before the destination is touched. A unique temporary sibling file is
    written, flushed, and closed, then published with ``os.link`` — an
    atomic same-filesystem no-replace operation that fails with
    ``FileExistsError`` if the destination exists. A destination that
    appears during the race window between the existence check and the link
    is therefore never overwritten; the overwrite policy is simply
    re-applied. Temporary files are cleaned up after exceptions. The default
    overwrite policy refuses an existing destination; ``idempotent=True``
    accepts an existing byte-identical manifest and never silently replaces
    different content. This helper does not commit a Dataset build directory
    and does not create ``_SUCCESS``.
    """
    data = serialize_dataset_manifest(manifest)
    path = Path(path)
    if path.exists():
        _handle_existing_destination(path, data, idempotent)
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatasetError(
            f"failed to create parent directory {path.parent}: {exc}"
        ) from exc
    temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex[:12]}")
    try:
        with temp.open("xb") as fh:
            fh.write(data)
            fh.flush()
    except OSError as exc:
        _cleanup_temp(temp)
        raise DatasetError(f"failed to write temporary manifest {temp}: {exc}") from exc
    try:
        # Atomic no-replace publication (works on POSIX and Windows/NTFS).
        os.link(temp, path)
    except FileExistsError:
        # The destination appeared during the race window; re-apply the
        # overwrite policy without ever touching its contents.
        _cleanup_temp(temp)
        _handle_existing_destination(path, data, idempotent)
        return
    except OSError as exc:
        _cleanup_temp(temp)
        raise DatasetError(
            f"failed to atomically publish manifest {path}: {exc}"
        ) from exc
    try:
        temp.unlink()
    except OSError as exc:
        raise DatasetError(
            f"manifest published at {path} but failed to clean temporary "
            f"file {temp}: {exc}"
        ) from exc


def _cleanup_temp(temp: Path) -> None:
    try:
        temp.unlink()
    except OSError:
        pass
