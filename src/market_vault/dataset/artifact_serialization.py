"""Deterministic Dataset artifact serialization (v0.5.0 PR-6).

This module implements the fixed byte contracts of the materialization
layer:

- the explicit logical ``DatasetSchema`` to PyArrow schema mapping
  (``string`` -> ``pa.string()``, ``int64`` -> ``pa.int64()``,
  ``float64`` -> ``pa.float64()``, ``bool`` -> ``pa.bool_()``,
  ``date32`` -> ``pa.date32()``, ``timestamp_us_utc`` ->
  ``pa.timestamp("us", tz="UTC")``; field order and nullability preserved;
  unknown logical types fail closed);
- the single-file ``dataset.parquet`` writer with fixed writer options
  (``zstd``, ``use_dictionary=False``, ``write_statistics=True``,
  ``coerce_timestamps="us"``, ``allow_truncated_timestamps=False``,
  Parquet format version and data page version pinned) and fixed UTF-8
  schema metadata keys;
- the Parquet readback used by the materializer's verification (schema,
  metadata, rows, content identity; NaN / Infinity never accepted);
- the deterministic spec artifacts: canonical JSON text that is also valid
  YAML (UTF-8, ``ensure_ascii=True``, ``sort_keys=True``, compact
  separators, trailing newline, no BOM), regenerated from the typed
  FeatureSpec / LabelSpec / ChronologicalSplitSpec models — parseable by
  the existing ``parse_feature_spec`` / ``parse_label_spec`` contracts and
  by the strict package-internal split artifact parser — so artifact bytes
  are stable for the same models and the pins are exactly the existing
  SpecPins;
- the deterministic non-identity ``build_report.json`` payload with the
  fixed build-report schema version.

Nothing in this module uses current time, random values, paths, mtimes,
pandas as an authoritative input, schema inference, or the local timezone.
The materializer calls these helpers in its fixed write order; the helpers
themselves never commit a build directory and never write ``_SUCCESS``.
"""

from __future__ import annotations

import hashlib
import json
import math
import numbers
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .content import logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime
from .materialization_models import (
    DATASET_BUILD_REPORT_SCHEMA_VERSION,
    DATASET_MANIFEST_FILENAME,
    DATASET_MATERIALIZER_VERSION,
    DATASET_PARQUET_FILENAME,
    DATASET_SUCCESS_FILENAME,
    DatasetMaterializationError,
)
from .models import SPEC_KIND_SPLIT, DatasetField, DatasetSchema
from .spec_models import FeatureSpec, LabelSpec
from .split_models import ChronologicalSplitSpec, chronological_split_spec_pin

# ---------------------------------------------------------------------------
# PyArrow schema mapping.
# ---------------------------------------------------------------------------

#: Fixed Parquet schema metadata keys (all UTF-8 bytes). They are artifact
#: record facts and never enter ``DatasetSchema`` or any identity.
PARQUET_METADATA_KEY_DATASET_ID = "market_vault.dataset_id"
PARQUET_METADATA_KEY_SCHEMA_ID = "market_vault.dataset_schema_id"
PARQUET_METADATA_KEY_CONTENT_ID = "market_vault.logical_dataset_content_id"
PARQUET_METADATA_KEY_FORMAT_VERSION = "market_vault.serialization_format_version"
PARQUET_METADATA_KEY_ROW_ORDER = "market_vault.row_order"
PARQUET_METADATA_KEY_MATERIALIZER = "market_vault.materializer_version"

_PARQUET_METADATA_KEYS = (
    PARQUET_METADATA_KEY_DATASET_ID,
    PARQUET_METADATA_KEY_SCHEMA_ID,
    PARQUET_METADATA_KEY_CONTENT_ID,
    PARQUET_METADATA_KEY_FORMAT_VERSION,
    PARQUET_METADATA_KEY_ROW_ORDER,
    PARQUET_METADATA_KEY_MATERIALIZER,
)

#: Fixed PyArrow writer options (documented in the materialization contract;
#: never overridable by callers). Byte-identical Parquet across PyArrow
#: versions is not claimed; the logical content, schema, dataset_id, and
#: verification results are the contract.
PARQUET_COMPRESSION = "zstd"
PARQUET_USE_DICTIONARY = False
PARQUET_WRITE_STATISTICS = True
PARQUET_COERCE_TIMESTAMPS = "us"
PARQUET_ALLOW_TRUNCATED_TIMESTAMPS = False
PARQUET_FORMAT_VERSION = "2.6"
PARQUET_DATA_PAGE_VERSION = "2.0"

_READ_CHUNK_SIZE = 1024 * 1024


def _logical_type_to_arrow_type(logical_type: str) -> pa.DataType:
    """Explicit logical type to PyArrow type mapping (fail closed on any
    unknown logical type; no schema inference)."""
    if logical_type == "string":
        return pa.string()
    if logical_type == "int64":
        return pa.int64()
    if logical_type == "float64":
        return pa.float64()
    if logical_type == "bool":
        return pa.bool_()
    if logical_type == "date32":
        return pa.date32()
    if logical_type == "timestamp_us_utc":
        return pa.timestamp("us", tz="UTC")
    raise DatasetMaterializationError(
        f"unsupported logical type {logical_type!r}; supported: string, "
        "int64, float64, bool, date32, timestamp_us_utc"
    )


def _dataset_schema_to_arrow(
    schema: DatasetSchema,
    *,
    dataset_id: str,
    dataset_schema_id_value: str,
    logical_dataset_content_id_value: str,
    serialization_format_version: str,
    row_order: str,
) -> pa.Schema:
    """Explicit PyArrow schema for one logical Dataset schema.

    Field order and nullability are preserved exactly; the fixed metadata
    keys are attached as UTF-8 bytes. ``timestamp_us_utc`` is always UTC
    microseconds; no milliseconds, no nanoseconds, no local timezone, no
    dictionary substitution, and no pandas index.
    """
    if not isinstance(schema, DatasetSchema):
        raise DatasetMaterializationError(
            f"schema must be a DatasetSchema, got {type(schema).__name__}"
        )
    fields = [
        pa.field(field.name, _logical_type_to_arrow_type(field.logical_type), nullable=field.nullable)
        for field in schema.fields
    ]
    metadata = {
        PARQUET_METADATA_KEY_DATASET_ID: str(dataset_id).encode("utf-8"),
        PARQUET_METADATA_KEY_SCHEMA_ID: str(dataset_schema_id_value).encode("utf-8"),
        PARQUET_METADATA_KEY_CONTENT_ID: str(logical_dataset_content_id_value).encode("utf-8"),
        PARQUET_METADATA_KEY_FORMAT_VERSION: str(serialization_format_version).encode("utf-8"),
        PARQUET_METADATA_KEY_ROW_ORDER: str(row_order).encode("utf-8"),
        PARQUET_METADATA_KEY_MATERIALIZER: DATASET_MATERIALIZER_VERSION.encode("utf-8"),
    }
    return pa.schema(fields, metadata=metadata)


def _arrow_scalar(field: DatasetField, value):
    """Validate and convert one row value to the exact Python scalar that
    PyArrow accepts for ``field`` (fail closed, no inference, no silent
    conversion, no pandas input)."""
    if value is None:
        if not field.nullable:
            raise DatasetMaterializationError(
                f"non-nullable field {field.name!r} received null"
            )
        return None
    logical_type = field.logical_type
    if logical_type == "string":
        if not isinstance(value, str):
            raise DatasetMaterializationError(
                f"field {field.name!r} expects string, got {type(value).__name__}"
            )
        return value
    if logical_type == "int64":
        if type(value) is bool or not isinstance(value, numbers.Integral):
            raise DatasetMaterializationError(
                f"field {field.name!r} expects int64, got {type(value).__name__}"
            )
        integer = int(value)
        if not -(2**63) <= integer <= 2**63 - 1:
            raise DatasetMaterializationError(
                f"field {field.name!r} int64 value out of range: {integer}"
            )
        return integer
    if logical_type == "float64":
        if type(value) is bool or not isinstance(value, numbers.Real):
            raise DatasetMaterializationError(
                f"field {field.name!r} expects float64, got {type(value).__name__}"
            )
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            raise DatasetMaterializationError(
                f"field {field.name!r} rejects NaN and positive/negative "
                f"infinity, got {number!r}"
            )
        return number
    if logical_type == "bool":
        if type(value) is not bool:
            raise DatasetMaterializationError(
                f"field {field.name!r} expects bool, got {type(value).__name__}"
            )
        return value
    if logical_type == "date32":
        if isinstance(value, datetime):
            raise DatasetMaterializationError(
                f"field {field.name!r} is date32 and rejects datetime values"
            )
        if not isinstance(value, date):
            raise DatasetMaterializationError(
                f"field {field.name!r} expects date32, got {type(value).__name__}"
            )
        return value
    if logical_type == "timestamp_us_utc":
        # The identity layer accepts datetime (and pd.Timestamp) and rejects
        # naive timestamps; UTC microsecond normalization is the existing
        # contract, never an implicit local-timezone conversion.
        return normalize_utc_datetime(value, f"field {field.name!r}")
    raise DatasetMaterializationError(
        f"unsupported logical type {logical_type!r}"
    )


def _validate_rows(
    rows, schema: DatasetSchema
) -> tuple[tuple[object, ...], ...]:
    """Strict pre-write row boundary: tuple-of-tuples, exact field count.

    Type / nullability / NaN / Infinity validation of the values themselves
    is performed by the existing logical content identity (called by the
    materializer before this helper) and again per scalar here; a list,
    generator, string, or bytes row is never silently converted.
    """
    if not isinstance(rows, tuple):
        raise DatasetMaterializationError(
            "rows must be a tuple of schema-ordered immutable tuples"
        )
    expected = len(schema.fields)
    for row in rows:
        if not isinstance(row, tuple):
            raise DatasetMaterializationError(
                "every row must be an immutable tuple; list, generator, "
                "string, and bytes rows are rejected and never silently "
                "converted"
            )
        if len(row) != expected:
            raise DatasetMaterializationError(
                f"every row must carry exactly the schema field count, got "
                f"{len(row)} for a schema with {expected} fields"
            )
    return rows


def _rows_to_arrow_table(
    rows: tuple[tuple[object, ...], ...],
    schema: DatasetSchema,
    arrow_schema: pa.Schema,
) -> pa.Table:
    """Build the single PyArrow table from the verified logical rows.

    Values are converted per logical field with explicit type checks; the
    table is constructed from typed column arrays under the explicit arrow
    schema, never by schema inference and never from a pandas DataFrame.
    """
    arrays = []
    for index, field in enumerate(schema.fields):
        arrays.append(
            pa.array(
                [_arrow_scalar(field, row[index]) for row in rows],
                type=arrow_schema.field(index).type,
            )
        )
    return pa.Table.from_arrays(arrays, schema=arrow_schema)


def write_dataset_parquet(
    path: Path,
    *,
    schema: DatasetSchema,
    rows,
    dataset_id_value: str,
    dataset_schema_id_value: str,
    logical_dataset_content_id_value: str,
    serialization_format_version: str,
    row_order: str,
) -> None:
    """Write exactly one ``dataset.parquet`` with the fixed writer options.

    The schema, the metadata, and the physical row order are exactly those
    of the verified orchestration result; the empty Dataset writes a legal
    zero-row Parquet with the full schema and metadata. ``path`` must not
    exist yet (the staging contract guarantees this).
    """
    rows = _validate_rows(rows, schema)
    arrow_schema = _dataset_schema_to_arrow(
        schema,
        dataset_id=dataset_id_value,
        dataset_schema_id_value=dataset_schema_id_value,
        logical_dataset_content_id_value=logical_dataset_content_id_value,
        serialization_format_version=serialization_format_version,
        row_order=row_order,
    )
    table = _rows_to_arrow_table(rows, schema, arrow_schema)
    try:
        pq.write_table(
            table,
            path,
            compression=PARQUET_COMPRESSION,
            use_dictionary=PARQUET_USE_DICTIONARY,
            write_statistics=PARQUET_WRITE_STATISTICS,
            coerce_timestamps=PARQUET_COERCE_TIMESTAMPS,
            allow_truncated_timestamps=PARQUET_ALLOW_TRUNCATED_TIMESTAMPS,
            version=PARQUET_FORMAT_VERSION,
            data_page_version=PARQUET_DATA_PAGE_VERSION,
        )
    except pa.ArrowException as exc:
        raise DatasetMaterializationError(
            f"failed to write Dataset Parquet {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to write Dataset Parquet {path}: {exc}"
        ) from exc


def read_dataset_parquet(path: Path) -> pa.Table:
    """Read one ``dataset.parquet`` back (documented PyArrow read errors are
    wrapped as :class:`DatasetMaterializationError`)."""
    try:
        return pq.read_table(path)
    except pa.ArrowException as exc:
        raise DatasetMaterializationError(
            f"failed to read Dataset Parquet {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to read Dataset Parquet {path}: {exc}"
        ) from exc


def _table_to_logical_rows(table: pa.Table, schema: DatasetSchema):
    """Convert a read-back table to schema-ordered logical tuples.

    Every read-back column is converted to plain Python scalars
    (``datetime.date`` for date32, UTC microseconds ``datetime`` for
    timestamps); floats are rejected when NaN / Infinity appear; the result
    is compared against the expected rows and content identity by the
    materializer's verification.
    """
    if table.num_columns != len(schema.fields):
        raise DatasetMaterializationError(
            f"read-back Parquet has {table.num_columns} columns, expected "
            f"{len(schema.fields)}"
        )
    columns = [table.column(index).to_pylist() for index in range(table.num_columns)]
    rows = []
    for row_index in range(len(table)):
        values = [columns[index][row_index] for index in range(len(columns))]
        for field, value in zip(schema.fields, values):
            if value is not None and field.logical_type == "float64":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise DatasetMaterializationError(
                        f"read-back field {field.name!r} is not a real number"
                    )
                if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                    raise DatasetMaterializationError(
                        f"read-back field {field.name!r} contains NaN or "
                        "Infinity"
                    )
        rows.append(tuple(values))
    return tuple(rows)


def readback_rows_and_content_id(
    path: Path, schema: DatasetSchema
) -> tuple[tuple[tuple[object, ...], ...], str]:
    """Read back a ``dataset.parquet`` and recompute its logical content ID
    under the authoritative schema (row order preserved)."""
    table = read_dataset_parquet(path)
    rows = _table_to_logical_rows(table, schema)
    mappings = tuple(dict(zip((f.name for f in schema.fields), row)) for row in rows)
    content_id = logical_dataset_content_id(schema, mappings)
    return rows, content_id


# ---------------------------------------------------------------------------
# Deterministic spec artifacts (canonical JSON text that is also valid YAML).
# ---------------------------------------------------------------------------


def _canonical_json_bytes(payload: dict) -> bytes:
    """Deterministic UTF-8 canonical JSON with sorted keys, compact
    separators, ``ensure_ascii=True``, and a trailing newline (no BOM)."""
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return (text + "\n").encode("utf-8")


def _spec_common_payload(spec) -> dict:
    return {
        "spec_schema_version": spec.spec_schema_version,
        "kind": spec.kind,
        "name": spec.name,
        "version": spec.version,
        "output": {
            "name": spec.output.name,
            "logical_type": spec.output.logical_type,
            "nullable": spec.output.nullable,
        },
        "inputs": {"canonical_fields": list(spec.input_canonical_fields)},
        "transform": {"ref": spec.transform_ref},
        "parameters": {
            parameter.name: parameter.value for parameter in spec.parameters
        },
        "requirements": {
            "canonical_schema_versions": list(
                spec.requirements.canonical_schema_versions
            ),
            "source_schema_versions": list(
                spec.requirements.source_schema_versions
            ),
        },
    }


def feature_spec_artifact(spec: FeatureSpec) -> bytes:
    """Deterministic Feature spec artifact bytes for one typed
    :class:`FeatureSpec` (canonical JSON syntax that is also valid YAML;
    semantic parsing stays the existing ``parse_feature_spec`` contract)."""
    if not isinstance(spec, FeatureSpec):
        raise DatasetMaterializationError(
            f"feature spec artifact requires a FeatureSpec, got "
            f"{type(spec).__name__}"
        )
    return _canonical_json_bytes(_spec_common_payload(spec))


def label_spec_artifact(spec: LabelSpec) -> bytes:
    """Deterministic Label spec artifact bytes for one typed
    :class:`LabelSpec` (canonical JSON syntax that is also valid YAML;
    semantic parsing stays the existing ``parse_label_spec`` contract)."""
    if not isinstance(spec, LabelSpec):
        raise DatasetMaterializationError(
            f"label spec artifact requires a LabelSpec, got "
            f"{type(spec).__name__}"
        )
    payload = _spec_common_payload(spec)
    payload.update(
        {
            "observation_window": {
                "unit": spec.observation_window.unit,
                "start_offset": spec.observation_window.start_offset,
                "end_offset": spec.observation_window.end_offset,
            },
            "horizon": {
                "unit": spec.horizon.unit,
                "value": spec.horizon.value,
            },
            "alignment_rule": spec.alignment_rule,
            "missing_data_policy": spec.missing_data_policy,
            "cross_trading_day": {
                "allow": spec.cross_trading_day.allow,
                "boundary_rule": spec.cross_trading_day.boundary_rule,
            },
        }
    )
    return _canonical_json_bytes(payload)


def split_spec_artifact(spec: ChronologicalSplitSpec) -> bytes:
    """Deterministic Split spec artifact bytes for one typed
    :class:`ChronologicalSplitSpec` (canonical JSON syntax that is also
    valid YAML; semantic parsing stays the strict package-internal split
    artifact parser and the existing ``chronological_split_spec_pin``
    identity)."""
    if not isinstance(spec, ChronologicalSplitSpec):
        raise DatasetMaterializationError(
            f"split spec artifact requires a ChronologicalSplitSpec, got "
            f"{type(spec).__name__}"
        )
    return _canonical_json_bytes(
        {
            "spec_schema_version": spec.spec_schema_version,
            "kind": spec.kind,
            "name": spec.name,
            "version": spec.version,
            "boundary_timezone": spec.boundary_timezone,
            "train_end_date": spec.train_end_date.isoformat(),
            "validation_end_date": spec.validation_end_date.isoformat(),
            "test_end_date": spec.test_end_date.isoformat(),
            "assignment_rule": spec.assignment_rule,
            "purge_rule": spec.purge_rule,
            "incomplete_label_policy": spec.incomplete_label_policy,
            "out_of_range_policy": spec.out_of_range_policy,
        }
    )


def parse_split_spec_artifact(text: str) -> ChronologicalSplitSpec:
    """Strict, exact-field package-internal parse of one split spec
    artifact.

    Accepts only the exact field set of the canonical split artifact (no
    unknown, no missing fields) and reconstructs the
    :class:`ChronologicalSplitSpec` through its own fail-closed model
    validation; the resulting SpecPin is the existing
    ``chronological_split_spec_pin`` — no second split identity exists.
    The ``kind`` field must be exactly :data:`SPEC_KIND_SPLIT`: any other
    kind (``FEATURE``, ``LABEL``, empty, unknown, or a non-string value) is
    rejected and never silently converted to SPLIT.
    """
    if not isinstance(text, str):
        raise DatasetMaterializationError(
            f"split spec artifact text must be a string, got "
            f"{type(text).__name__}"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetMaterializationError(
            f"split spec artifact is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise DatasetMaterializationError(
            f"split spec artifact must be a JSON object, got "
            f"{type(payload).__name__}"
        )
    if not isinstance(payload.get("kind"), str):
        raise DatasetMaterializationError(
            f"split spec artifact kind must be a string, got "
            f"{payload.get('kind')!r}"
        )
    if payload["kind"] != SPEC_KIND_SPLIT:
        raise DatasetMaterializationError(
            f"split spec artifact kind must be {SPEC_KIND_SPLIT}, got "
            f"{payload['kind']!r}"
        )
    required = {
        "spec_schema_version",
        "kind",
        "name",
        "version",
        "boundary_timezone",
        "train_end_date",
        "validation_end_date",
        "test_end_date",
        "assignment_rule",
        "purge_rule",
        "incomplete_label_policy",
        "out_of_range_policy",
    }
    unknown = sorted(set(payload) - required)
    if unknown:
        raise DatasetMaterializationError(
            f"split spec artifact unknown field(s): {', '.join(unknown)}"
        )
    missing = sorted(required - set(payload))
    if missing:
        raise DatasetMaterializationError(
            f"split spec artifact missing field(s): {', '.join(missing)}"
        )
    try:
        return ChronologicalSplitSpec(
            spec_schema_version=payload["spec_schema_version"],
            name=payload["name"],
            version=payload["version"],
            boundary_timezone=payload["boundary_timezone"],
            train_end_date=date.fromisoformat(payload["train_end_date"]),
            validation_end_date=date.fromisoformat(
                payload["validation_end_date"]
            ),
            test_end_date=date.fromisoformat(payload["test_end_date"]),
            assignment_rule=payload["assignment_rule"],
            purge_rule=payload["purge_rule"],
            incomplete_label_policy=payload["incomplete_label_policy"],
            out_of_range_policy=payload["out_of_range_policy"],
        )
    except DatasetMaterializationError:
        raise
    except (DatasetError, ValueError, TypeError, KeyError) as exc:
        raise DatasetMaterializationError(
            f"invalid split spec artifact: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Build report (recorded facts only; never identity-bearing).
# ---------------------------------------------------------------------------


def _datetime_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def build_report_payload(result, built_at: datetime) -> dict:
    """Deterministic build-report payload for one orchestration result.

    Records fixed machine facts only: report schema version, materializer
    version, dataset identity facts, status, the explicit ``built_at`` and
    ``dataset_as_of`` (UTC microseconds), contract versions, row order,
    feature / label / canonical / completion / diagnostic counts, the stable
    split result identity facts, and the fixed output layout filenames.
    Never recorded: absolute output path, cwd, local timezone, process ID,
    hostname, username, branch, PR number, elapsed wall-clock time, random
    values, traceback, free-form warnings, ``created_new_build``, or the
    staging path.
    """
    diagnostics = result.diagnostics
    return {
        "report_schema_version": DATASET_BUILD_REPORT_SCHEMA_VERSION,
        "materializer_version": DATASET_MATERIALIZER_VERSION,
        "dataset_id": result.dataset_id,
        "dataset_kind": result.dataset_kind,
        "status": result.status,
        "built_at": _datetime_iso(built_at),
        "dataset_as_of": _datetime_iso(result.dataset_as_of),
        "dataset_schema_id": result.dataset_schema_id,
        "logical_dataset_content_id": result.logical_dataset_content_id,
        "logical_row_count": len(result.rows),
        "orchestration_contract_version": result.orchestration_contract_version,
        "row_order": result.row_order,
        "manifest_schema_version": result.manifest_schema_version,
        "serialization_format": result.serialization_format,
        "serialization_format_version": result.serialization_format_version,
        "feature_spec_count": len(result.feature_specs),
        "label_spec_count": len(result.label_specs),
        "canonical_build_pin_count": len(
            result.identity_input.canonical_builds
        ),
        "canonical_row_version_count": len(
            result.identity_input.canonical_row_version_ids
        ),
        "completion_complete_key_count": result.completion.complete_count,
        "completion_incomplete_key_count": result.completion.incomplete_count,
        "completion_missing_key_count": result.completion.missing_count,
        "request_count": diagnostics.request_count,
        "pit_sample_count": diagnostics.pit_sample_count,
        "feature_complete_sample_count": diagnostics.feature_complete_sample_count,
        "feature_excluded_sample_count": diagnostics.feature_excluded_sample_count,
        "label_complete_sample_count": diagnostics.label_complete_sample_count,
        "label_incomplete_sample_count": diagnostics.label_incomplete_sample_count,
        "split_sample_count": diagnostics.split_sample_count,
        "assigned_sample_count": diagnostics.assigned_sample_count,
        "purged_sample_count": diagnostics.purged_sample_count,
        "excluded_sample_count": diagnostics.excluded_sample_count,
        "split_spec_content_id": result.split_result.split_spec_pin.content_sha256,
        "split_result_id": result.split_result.split_result_id,
        "output_layout": {
            "dataset_parquet_filename": "dataset.parquet",
            "manifest_filename": DATASET_MANIFEST_FILENAME,
            "build_report_filename": "build_report.json",
            "split_spec_filename": "split_spec.yaml",
            "success_filename": DATASET_SUCCESS_FILENAME,
            "feature_specs_dirname": "feature_specs",
            "label_specs_dirname": "label_specs",
        },
    }


def build_report_bytes(result, built_at: datetime) -> bytes:
    """Deterministic ``build_report.json`` bytes for one result and
    ``built_at`` (same inputs -> same bytes; a different ``built_at`` may
    change the bytes but never the ``dataset_id``)."""
    return _canonical_json_bytes(build_report_payload(result, built_at))


# ---------------------------------------------------------------------------
# File facts.
# ---------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    """Streaming SHA-256 of one closed artifact file (1 MiB chunks)."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to hash artifact file {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def file_byte_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError as exc:
        raise DatasetMaterializationError(
            f"failed to stat artifact file {path}: {exc}"
        ) from exc
