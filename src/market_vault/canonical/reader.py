"""Verified read-only access to immutable Canonical build artifacts.

:func:`load_verified_canonical_build` reads one committed Canonical build
directory and returns a fully verified :class:`VerifiedCanonicalBuild`:
every file, hash, count, schema, provenance record, and logical identity in
the artifact is re-checked, and any inconsistency fails closed with
:class:`CanonicalArtifactValidationError`. The reader never writes, repairs,
or rewrites anything, and it never accesses OpenD or the network.

The file-level validation reuses the strict output-file and provenance
validators of :mod:`market_vault.canonical.materialization` — the same code
that validates existing builds on idempotent materialization — so the read
side and the write side share one artifact contract instead of drifting into
two. The reader additionally verifies the exact bars Parquet schema,
reconstructs every canonical row, and recomputes all logical identities
(``canonical_bar_key``, ``canonical_row_version_id``, ``canonical_content_id``,
``resolution_content_id``, ``gap_content_id``, ``canonical_build_id``) from
the actual contents before comparing them with the manifest.

The returned ``build_path`` is descriptive metadata only; it never
participates in any identity.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .bars import DEFAULT_DATASET_KIND
from .gaps import GAP_POLICY_VERSION, GapRange
from .identity import (
    canonical_bar_key,
    canonical_build_id,
    canonical_content_id,
    canonical_row_version_id,
    gap_content_id,
    resolution_content_id,
)
from .manifest import (
    GAP_POLICY_LIMITATIONS,
    MANIFEST_SCHEMA_VERSION,
    STATUS_COMPLETE,
    STATUS_EMPTY,
)
from .materialization import (
    _validate_existing_output_files,
    _validate_manifest_provenance,
    gap_schema,
)
from .models import (
    CanonicalBar,
    CanonicalMaterializationError,
    CanonicalRequestKey,
    CanonicalResolutionEntry,
    CanonicalSourceRef,
)
from .schema import OPTIONAL_MARKET_COLUMNS, canonical_bars_schema

#: Exact top-level manifest field set written by the v1 canonical materializer.
MANIFEST_TOP_LEVEL_FIELDS = frozenset(
    (
        "manifest_schema_version",
        "status",
        "dataset_kind",
        "canonical_build_id",
        "canonical_content_id",
        "resolution_content_id",
        "gap_content_id",
        "canonical_builder_version",
        "canonical_schema_version",
        "materializer_version",
        "gap_policy_version",
        "created_at",
        "normalized_request",
        "source_snapshot_count",
        "canonical_row_count",
        "gap_range_count",
        "resolution_row_count",
        "min_event_time",
        "max_event_time",
        "min_archive_available_at",
        "max_archive_available_at",
        "source_snapshot_provenance",
        "output_files",
        "gap_policy_limitations",
    )
)

_NORMALIZED_REQUEST_FIELDS = frozenset(
    (
        "symbols",
        "trade_dates",
        "interval",
        "requested_session",
        "adjustment",
        "source_schema_version",
    )
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

#: Canonical bar string columns (non-nullable, non-empty).
_BAR_TEXT_COLUMNS = (
    "canonical_bar_key",
    "canonical_row_version_id",
    "dataset_kind",
    "code",
    "interval",
    "adjustment",
    "ingestion_run_id",
    "physical_snapshot_hash",
    "logical_source_rows_hash",
    "source_schema_version",
    "canonical_builder_version",
    "requested_session",
    "session",
    "snapshot_file",
)

_BAR_TIMESTAMP_COLUMNS = (
    "event_time",
    "market_available_at",
    "archive_available_at",
)

_BAR_MARKET_FLOAT_COLUMNS = ("open", "high", "low", "close", "volume")


class CanonicalArtifactValidationError(CanonicalMaterializationError):
    """Structured validation failure of a committed Canonical build artifact.

    Raised for every filesystem, JSON, UTF-8, Parquet, hash, schema, and
    identity inconsistency found while verifying a build directory. Low-level
    exceptions (``OSError``, ``UnicodeDecodeError``, ``json.JSONDecodeError``,
    PyArrow failures, identity ``ValueError``) are never part of the public
    contract; they are always converted to this structured error.
    """


@dataclass(frozen=True)
class VerifiedCanonicalBuild:
    """A fully verified immutable Canonical build artifact.

    Produced exclusively by :func:`load_verified_canonical_build`; every
    field is re-validated against the actual artifact contents. ``bars`` are
    reconstructed canonical rows (deterministic order: ``event_time`` ASC,
    then ``canonical_bar_key`` ASC, the same order the materializer writes).
    ``canonical_row_version_ids`` is the sorted, deduplicated row-version set
    of this build. ``source_snapshot_provenance`` mirrors the manifest's
    ordered provenance records as typed source references.
    ``manifest_payload`` is the raw verified manifest; ``build_path`` is
    descriptive metadata only and never participates in any identity.
    """

    canonical_build_id: str
    canonical_content_id: str
    resolution_content_id: str
    gap_content_id: str
    canonical_builder_version: str
    canonical_schema_version: str
    materializer_version: str
    gap_policy_version: str
    status: str
    normalized_request: dict
    bars: tuple[CanonicalBar, ...]
    canonical_row_version_ids: tuple[str, ...]
    source_snapshot_provenance: tuple[CanonicalSourceRef, ...]
    gap_ranges: tuple[GapRange, ...]
    gap_count: int
    manifest_payload: dict
    build_path: Path


def load_verified_canonical_build(build_dir) -> VerifiedCanonicalBuild:
    """Read and strictly verify one immutable Canonical build directory.

    The build root must contain ``manifest.json`` and ``_SUCCESS``; the
    manifest schema version must be the current Canonical manifest version;
    the directory name must carry the manifest's ``canonical_build_id``; every
    listed output file must match its recorded byte size, SHA-256, and row
    count with no symlinks anywhere on the path; bars Parquet schemas must
    exactly equal :func:`market_vault.canonical.schema.canonical_bars_schema`;
    every row identity is recomputed and compared; ``canonical_content_id``,
    ``resolution_content_id``, ``gap_content_id``, and ``canonical_build_id``
    are recomputed from the actual contents and must match the manifest; and
    manifest counts, min/max timestamps, source provenance, and EMPTY-build
    invariants are checked against the actual contents.

    Any inconsistency raises :class:`CanonicalArtifactValidationError`.
    Nothing is written, repaired, or rewritten.
    """
    try:
        root = Path(build_dir)
    except TypeError as exc:
        raise CanonicalArtifactValidationError(
            f"build_dir must be a path, got {build_dir!r}"
        ) from exc
    try:
        return _load_verified_build(root)
    except CanonicalArtifactValidationError:
        raise
    except CanonicalMaterializationError as exc:
        raise CanonicalArtifactValidationError(str(exc)) from exc
    except Exception as exc:
        raise CanonicalArtifactValidationError(
            f"failed to read canonical build artifact {root}: {exc}"
        ) from exc


def _fail(reason: str) -> None:
    raise CanonicalArtifactValidationError(reason)


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        _fail(f"{label} must not be a symlink: {path}")


def _require_text(value, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string, got {value!r}")
    return value


def _require_sha256(value, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value):
        _fail(f"{label} must be a 64-character lowercase SHA-256 hex string, got {value!r}")
    return value


def _verified_timestamp(value, label: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        _fail(f"{label} is not a timestamp: {value!r}")
        raise AssertionError("unreachable") from exc
    if stamp.tzinfo is None:
        _fail(f"{label} must be timezone-aware, got a naive timestamp")
    return stamp.tz_convert("UTC").as_unit("us")


def _manifest_timestamp(value, label: str) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        _fail(f"manifest {label} is not a valid timestamp: {value!r}")
        raise AssertionError("unreachable") from exc
    if stamp.tzinfo is None:
        _fail(f"manifest {label} must be timezone-aware")
    return stamp.tz_convert("UTC").as_unit("us")


def _verified_bar(row: dict) -> CanonicalBar:
    """Reconstruct and validate one canonical bar from a verified Parquet row.

    The Parquet schema has already been verified to exactly equal
    ``canonical_bars_schema()``, so the columns and types are fixed; values
    are still checked defensively so a corrupt file cannot produce an
    inconsistent row.
    """
    for name in _BAR_TEXT_COLUMNS:
        value = row.get(name)
        if not isinstance(value, str) or not value:
            _fail(f"bars row has invalid {name}: {value!r}")
    for name in _BAR_TIMESTAMP_COLUMNS:
        if not isinstance(row.get(name), datetime):
            _fail(f"bars row has invalid {name}: {row.get(name)!r}")
    event_time = _verified_timestamp(row["event_time"], "bars row event_time")
    market_available_at = _verified_timestamp(
        row["market_available_at"], "bars row market_available_at"
    )
    archive_available_at = _verified_timestamp(
        row["archive_available_at"], "bars row archive_available_at"
    )
    for name in _BAR_MARKET_FLOAT_COLUMNS:
        value = row.get(name)
        if not isinstance(value, float) or value != value or value in (
            float("inf"),
            float("-inf"),
        ):
            _fail(f"bars row has invalid market float {name}: {value!r}")
    extra_fields = []
    for name in OPTIONAL_MARKET_COLUMNS:
        value = row.get(name)
        if value is None:
            continue
        if not isinstance(value, float) or value != value:
            _fail(f"bars row has invalid optional field {name}: {value!r}")
        extra_fields.append((name, value))
    for name in ("requested_trade_date", "market_calendar_date"):
        value = row.get(name)
        if not isinstance(value, date):
            _fail(f"bars row has invalid {name}: {value!r}")
    return CanonicalBar(
        canonical_bar_key=row["canonical_bar_key"],
        canonical_row_version_id=row["canonical_row_version_id"],
        dataset_kind=row["dataset_kind"],
        code=row["code"],
        interval=row["interval"],
        adjustment=row["adjustment"],
        event_time=event_time,
        market_available_at=market_available_at,
        archive_available_at=archive_available_at,
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        extra_fields=tuple(extra_fields),
        ingestion_run_id=row["ingestion_run_id"],
        physical_snapshot_hash=row["physical_snapshot_hash"],
        logical_source_rows_hash=row["logical_source_rows_hash"],
        source_schema_version=row["source_schema_version"],
        canonical_builder_version=row["canonical_builder_version"],
        requested_trade_date=row["requested_trade_date"],
        requested_session=row["requested_session"],
        market_calendar_date=row["market_calendar_date"],
        session=row["session"],
        snapshot_file=row["snapshot_file"],
    )


def _read_bars(build_root: Path, records: list[dict]) -> list[CanonicalBar]:
    bars: list[CanonicalBar] = []
    for record in sorted(records, key=lambda item: item["relative_path"]):
        path = build_root / record["relative_path"]
        try:
            schema = pq.read_schema(path)
        except Exception as exc:
            _fail(f"failed to read bars parquet schema {record['relative_path']!r}: {exc}")
        if not schema.equals(canonical_bars_schema(), check_metadata=False):
            _fail(
                f"bars parquet schema mismatch: {record['relative_path']!r} does not "
                "exactly equal canonical_bars_schema()"
            )
        try:
            table = pq.read_table(path)
        except Exception as exc:
            _fail(f"failed to read bars parquet {record['relative_path']!r}: {exc}")
        for row in table.to_pylist():
            bars.append(_verified_bar(row))
    return bars


def _gap_from_row(row: dict) -> GapRange:
    for name in (
        "gap_id",
        "gap_policy_version",
        "dataset_kind",
        "code",
        "interval",
        "adjustment",
        "session",
    ):
        value = row.get(name)
        if not isinstance(value, str) or not value:
            _fail(f"gaps row has invalid {name}: {value!r}")
    market_calendar_date = row.get("market_calendar_date")
    if not isinstance(market_calendar_date, date):
        _fail(f"gaps row has invalid market_calendar_date: {market_calendar_date!r}")
    for name in (
        "previous_event_time",
        "next_event_time",
        "missing_from_event_time",
        "missing_to_event_time",
    ):
        if not isinstance(row.get(name), datetime):
            _fail(f"gaps row has invalid {name}: {row.get(name)!r}")
    missing_bar_count = row.get("missing_bar_count")
    if type(missing_bar_count) is not int or missing_bar_count < 0:
        _fail(f"gaps row has invalid missing_bar_count: {missing_bar_count!r}")
    return GapRange(
        gap_id=row["gap_id"],
        gap_policy_version=row["gap_policy_version"],
        dataset_kind=row["dataset_kind"],
        code=row["code"],
        interval=row["interval"],
        adjustment=row["adjustment"],
        market_calendar_date=market_calendar_date,
        session=row["session"],
        previous_event_time=_verified_timestamp(
            row["previous_event_time"], "gaps row previous_event_time"
        ),
        next_event_time=_verified_timestamp(
            row["next_event_time"], "gaps row next_event_time"
        ),
        missing_from_event_time=_verified_timestamp(
            row["missing_from_event_time"], "gaps row missing_from_event_time"
        ),
        missing_to_event_time=_verified_timestamp(
            row["missing_to_event_time"], "gaps row missing_to_event_time"
        ),
        missing_bar_count=missing_bar_count,
    )


def _read_gaps(build_root: Path, records: list[dict]) -> list[GapRange]:
    gaps: list[GapRange] = []
    for record in sorted(records, key=lambda item: item["relative_path"]):
        path = build_root / record["relative_path"]
        try:
            schema = pq.read_schema(path)
        except Exception as exc:
            _fail(f"failed to read gaps parquet schema {record['relative_path']!r}: {exc}")
        if not schema.equals(gap_schema(), check_metadata=False):
            _fail(
                f"gaps parquet schema mismatch: {record['relative_path']!r} does not "
                "exactly equal gap_schema()"
            )
        try:
            table = pq.read_table(path)
        except Exception as exc:
            _fail(f"failed to read gaps parquet {record['relative_path']!r}: {exc}")
        for row in table.to_pylist():
            gaps.append(_gap_from_row(row))
    return gaps


_RESOLUTION_REF_FIELDS = frozenset(
    (
        "ingestion_run_id",
        "physical_snapshot_hash",
        "logical_source_rows_hash",
        "source_schema_version",
        "requested_trade_date",
        "requested_session",
        "snapshot_file",
    )
)


def _resolution_source_ref(ref: dict) -> CanonicalSourceRef:
    if not isinstance(ref, dict):
        _fail("resolution source reference must be an object")
    missing = sorted(field for field in _RESOLUTION_REF_FIELDS if field not in ref)
    if missing:
        _fail(f"resolution source reference missing field(s): {', '.join(missing)}")
    for name in (
        "ingestion_run_id",
        "physical_snapshot_hash",
        "logical_source_rows_hash",
        "source_schema_version",
        "requested_session",
        "snapshot_file",
    ):
        _require_text(ref[name], f"resolution ref {name}")
    try:
        trade_date = date.fromisoformat(ref["requested_trade_date"])
    except (TypeError, ValueError) as exc:
        _fail(f"resolution ref requested_trade_date must be an ISO date: {ref['requested_trade_date']!r}")
        raise AssertionError("unreachable") from exc
    return CanonicalSourceRef(
        ingestion_run_id=ref["ingestion_run_id"],
        physical_snapshot_hash=ref["physical_snapshot_hash"],
        logical_source_rows_hash=ref["logical_source_rows_hash"],
        source_schema_version=ref["source_schema_version"],
        snapshot_file=ref["snapshot_file"],
        requested_trade_date=trade_date,
        requested_session=ref["requested_session"],
    )


def _resolution_entries(rows: list[dict]) -> list[CanonicalResolutionEntry]:
    entries = []
    for row in rows:
        if not isinstance(row, dict):
            _fail("resolution.jsonl entry must be an object")
        if set(row) != {"canonical_bar_key", "selected", "equivalent_discarded_sources"}:
            _fail(f"resolution.jsonl entry has unexpected fields: {sorted(row)}")
        bar_key = _require_text(row.get("canonical_bar_key"), "resolution canonical_bar_key")
        selected = row.get("selected")
        if not isinstance(selected, dict):
            _fail("resolution entry selected must be an object")
        discarded = row.get("equivalent_discarded_sources")
        if discarded is None:
            discarded = []
        if not isinstance(discarded, list):
            _fail("resolution entry equivalent_discarded_sources must be a list")
        entries.append(
            CanonicalResolutionEntry(
                canonical_bar_key=bar_key,
                selected=_resolution_source_ref(selected),
                equivalent_discarded=tuple(_resolution_source_ref(item) for item in discarded),
            )
        )
    return entries


def _source_stable_identity(ref: CanonicalSourceRef) -> tuple:
    """Path-independent stable source identity (schema-version-free 5-tuple).

    Mirrors the manifest provenance record identity; the request-level
    ``source_schema_version`` is carried separately on the ref and is
    identical for every source of one build.
    """
    return (
        ref.ingestion_run_id,
        ref.physical_snapshot_hash,
        ref.logical_source_rows_hash,
        ref.requested_trade_date,
        ref.requested_session,
    )


def _bar_stable_identity(bar: CanonicalBar) -> tuple:
    """Bar-level stable source identity, matching ``_source_stable_identity``."""
    return (
        bar.ingestion_run_id,
        bar.physical_snapshot_hash,
        bar.logical_source_rows_hash,
        bar.requested_trade_date,
        bar.requested_session,
    )


def _validate_normalized_request(section) -> dict:
    if not isinstance(section, dict):
        _fail("manifest normalized_request must be an object")
    unknown = sorted(set(section) - _NORMALIZED_REQUEST_FIELDS)
    if unknown:
        _fail(f"manifest normalized_request unknown field(s): {', '.join(unknown)}")
    missing = sorted(_NORMALIZED_REQUEST_FIELDS - set(section))
    if missing:
        _fail(f"manifest normalized_request missing field(s): {', '.join(missing)}")
    symbols = section["symbols"]
    if not isinstance(symbols, list) or not symbols or any(
        not isinstance(item, str) or not item for item in symbols
    ):
        _fail("manifest normalized_request symbols must be a non-empty list of non-empty strings")
    trade_dates = section["trade_dates"]
    if not isinstance(trade_dates, list) or not trade_dates:
        _fail("manifest normalized_request trade_dates must be a non-empty list")
    for item in trade_dates:
        if not isinstance(item, str):
            _fail(f"manifest normalized_request trade_dates must be ISO strings, got {item!r}")
        try:
            date.fromisoformat(item)
        except ValueError as exc:
            _fail(f"manifest normalized_request trade_dates entry is not an ISO date: {item!r}")
            raise AssertionError("unreachable") from exc
    for name in ("interval", "requested_session", "adjustment", "source_schema_version"):
        _require_text(section[name], f"manifest normalized_request {name}")
    return section


def _load_verified_build(build_root: Path) -> VerifiedCanonicalBuild:
    if not build_root.exists():
        _fail(f"canonical build directory does not exist: {build_root}")
    if not build_root.is_dir():
        _fail(f"canonical build path is not a directory: {build_root}")
    _reject_symlink(build_root, "build directory")

    manifest_path = build_root / "manifest.json"
    success_path = build_root / "_SUCCESS"
    if not manifest_path.exists():
        _fail(f"canonical build manifest.json is missing: {build_root}")
    if not success_path.exists():
        _fail(f"canonical build _SUCCESS is missing: {build_root}")
    _reject_symlink(manifest_path, "manifest.json")
    _reject_symlink(success_path, "_SUCCESS")
    if not success_path.is_file():
        _fail(f"canonical build _SUCCESS must be a regular file: {build_root}")

    try:
        text = manifest_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalArtifactValidationError(
            f"canonical build manifest.json is not valid UTF-8: {build_root}"
        ) from exc
    except OSError as exc:
        raise CanonicalArtifactValidationError(
            f"failed to read canonical build manifest.json: {build_root}: {exc}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CanonicalArtifactValidationError(
            f"canonical build manifest.json is not valid JSON: {build_root}"
        ) from exc
    if not isinstance(payload, dict):
        _fail(f"canonical build manifest must be a JSON object: {build_root}")

    unknown = sorted(set(payload) - MANIFEST_TOP_LEVEL_FIELDS)
    if unknown:
        _fail(f"manifest has unknown top-level field(s): {', '.join(unknown)}")
    missing = sorted(MANIFEST_TOP_LEVEL_FIELDS - set(payload))
    if missing:
        _fail(f"manifest is missing top-level field(s): {', '.join(missing)}")

    if payload["manifest_schema_version"] != MANIFEST_SCHEMA_VERSION:
        _fail(
            f"manifest schema mismatch: expected {MANIFEST_SCHEMA_VERSION}, "
            f"got {payload['manifest_schema_version']!r}"
        )
    if payload["dataset_kind"] != DEFAULT_DATASET_KIND:
        _fail(f"manifest dataset_kind mismatch: got {payload['dataset_kind']!r}")
    if payload["gap_policy_limitations"] != list(GAP_POLICY_LIMITATIONS):
        _fail("manifest gap_policy_limitations mismatch")

    build_id = _require_sha256(payload["canonical_build_id"], "manifest canonical_build_id")
    directory_id = build_root.name.removeprefix("build_id=")
    if build_root.name == directory_id or directory_id != build_id:
        _fail(
            f"build directory name {build_root.name!r} does not match manifest "
            f"canonical_build_id {build_id}"
        )
    status = _require_text(payload["status"], "manifest status")
    if status not in (STATUS_COMPLETE, STATUS_EMPTY):
        _fail(f"manifest status must be COMPLETE or EMPTY, got {status!r}")
    for name in (
        "canonical_content_id",
        "resolution_content_id",
        "gap_content_id",
    ):
        _require_sha256(payload[name], f"manifest {name}")
    for name in (
        "canonical_builder_version",
        "canonical_schema_version",
        "materializer_version",
        "gap_policy_version",
    ):
        _require_text(payload[name], f"manifest {name}")

    request = _validate_normalized_request(payload["normalized_request"])

    # Shared strict output-file and provenance validation: path safety,
    # symlink rejection, byte size, SHA-256, and row counts of every listed
    # file, plus provenance/resolution identity equality.
    try:
        resolution_rows = _validate_existing_output_files(build_root, payload)
        _validate_manifest_provenance(payload, resolution_rows, build_root)
    except CanonicalMaterializationError as exc:
        raise CanonicalArtifactValidationError(str(exc)) from exc

    bar_records = [r for r in payload["output_files"] if r["file_role"] == "bars"]
    bars = _read_bars(build_root, bar_records)

    # Every row identity is recomputed and compared; keys and row versions
    # must be unique; row versions must be valid SHA-256 hex digests.
    seen_keys: set[str] = set()
    seen_versions: set[str] = set()
    for bar in bars:
        if bar.canonical_bar_key in seen_keys:
            _fail(f"duplicate canonical_bar_key in bars: {bar.canonical_bar_key}")
        seen_keys.add(bar.canonical_bar_key)
        _require_sha256(bar.canonical_row_version_id, "bars row canonical_row_version_id")
        if bar.canonical_row_version_id in seen_versions:
            _fail(
                f"duplicate canonical_row_version_id in bars: {bar.canonical_row_version_id}"
            )
        seen_versions.add(bar.canonical_row_version_id)
        recomputed_key = canonical_bar_key(
            dataset_kind=bar.dataset_kind,
            code=bar.code,
            interval=bar.interval,
            adjustment=bar.adjustment,
            event_time=bar.event_time,
        )
        if recomputed_key != bar.canonical_bar_key:
            _fail(
                f"bars row canonical_bar_key does not match its recomputed value: "
                f"{bar.canonical_bar_key}"
            )
        recomputed_version = canonical_row_version_id(
            canonical_bar_key=bar.canonical_bar_key,
            ingestion_run_id=bar.ingestion_run_id,
            source_snapshot_content_hash=bar.physical_snapshot_hash,
            source_schema_version=bar.source_schema_version,
            canonical_builder_version=bar.canonical_builder_version,
        )
        if recomputed_version != bar.canonical_row_version_id:
            _fail(
                f"bars row canonical_row_version_id does not match its recomputed value: "
                f"{bar.canonical_row_version_id}"
            )

    row_count = len(bars)
    if payload["canonical_row_count"] != row_count:
        _fail(
            f"manifest canonical_row_count {payload['canonical_row_count']} does not "
            f"match actual bar row count {row_count}"
        )

    resolution = _resolution_entries(resolution_rows)
    if payload["resolution_row_count"] != len(resolution):
        _fail(
            f"manifest resolution_row_count {payload['resolution_row_count']} does not "
            f"match actual resolution entry count {len(resolution)}"
        )
    resolution_keys = {entry.canonical_bar_key for entry in resolution}
    if resolution_keys != seen_keys:
        _fail("resolution canonical_bar_key values do not exactly match emitted bar keys")

    # Every bar's stable source identity must be referenced by resolution
    # (selected or equivalent-discarded); manifest provenance and resolution
    # identities were already checked equal above.
    resolution_identities: set[tuple] = set()
    for entry in resolution:
        resolution_identities.add(_source_stable_identity(entry.selected))
        for ref in entry.equivalent_discarded:
            resolution_identities.add(_source_stable_identity(ref))
    for bar in bars:
        if _bar_stable_identity(bar) not in resolution_identities:
            _fail(
                f"bars row source provenance is not referenced by resolution: "
                f"{bar.canonical_bar_key}"
            )

    source_identity_count = len(resolution_identities)
    if payload["source_snapshot_count"] != source_identity_count:
        _fail(
            f"manifest source_snapshot_count {payload['source_snapshot_count']} does not "
            f"match the stable physical source identity count {source_identity_count}"
        )

    gap_records = [r for r in payload["output_files"] if r["file_role"] == "gaps"]
    gap_ranges = _read_gaps(build_root, gap_records)
    if payload["gap_range_count"] != len(gap_ranges):
        _fail(
            f"manifest gap_range_count {payload['gap_range_count']} does not match "
            f"actual gap range count {len(gap_ranges)}"
        )

    # Status/row-count consistency and EMPTY-build invariants.
    if status == STATUS_COMPLETE:
        if row_count == 0:
            _fail("COMPLETE build must contain at least one bar row")
    else:
        if row_count != 0:
            _fail("EMPTY build must contain zero bar rows")
        if resolution:
            _fail("EMPTY build must contain zero resolution entries")
        if payload["source_snapshot_provenance"]:
            _fail("EMPTY build must contain zero source snapshots")
        if any(
            payload[name] is not None
            for name in (
                "min_event_time",
                "max_event_time",
                "min_archive_available_at",
                "max_archive_available_at",
            )
        ):
            _fail("EMPTY build must have null min/max timestamp ranges")

    # Manifest min/max timestamp ranges must match the actual contents.
    if bars:
        min_event = min((bar.event_time for bar in bars))
        max_event = max((bar.event_time for bar in bars))
        min_archive = min((bar.archive_available_at for bar in bars))
        max_archive = max((bar.archive_available_at for bar in bars))
    else:
        min_event = max_event = min_archive = max_archive = None
    _check_range(payload, "min_event_time", min_event)
    _check_range(payload, "max_event_time", max_event)
    _check_range(payload, "min_archive_available_at", min_archive)
    _check_range(payload, "max_archive_available_at", max_archive)

    # Recompute all logical identities from the actual contents.
    content_id = canonical_content_id(tuple(bars))
    if content_id != payload["canonical_content_id"]:
        _fail("recomputed canonical_content_id does not match the manifest")
    resolution_id = resolution_content_id(tuple(resolution))
    if resolution_id != payload["resolution_content_id"]:
        _fail("recomputed resolution_content_id does not match the manifest")
    gap_id = gap_content_id(tuple(gap_ranges), GAP_POLICY_VERSION)
    if gap_id != payload["gap_content_id"]:
        _fail("recomputed gap_content_id does not match the manifest")
    request_key = CanonicalRequestKey(
        interval=request["interval"],
        requested_session=request["requested_session"],
        adjustment=request["adjustment"],
        source_schema_version=request["source_schema_version"],
    )
    recomputed_build_id = canonical_build_id(
        symbols=request["symbols"],
        trade_dates=[date.fromisoformat(item) for item in request["trade_dates"]],
        request_key=request_key,
        canonical_content_id=content_id,
        resolution_content_id=resolution_id,
        gap_content_id=gap_id,
        selected_row_version_ids=sorted(seen_versions),
        canonical_builder_version=payload["canonical_builder_version"],
        canonical_schema_version=payload["canonical_schema_version"],
        materializer_version=payload["materializer_version"],
        gap_policy_version=payload["gap_policy_version"],
    )
    if recomputed_build_id != payload["canonical_build_id"]:
        _fail("recomputed canonical_build_id does not match the manifest")

    # Typed source provenance from the verified manifest. Manifest provenance
    # records carry no source_schema_version; every resolution ref does, and
    # the manifest/resolution identities were already checked equal above, so
    # each provenance record resolves to a resolution ref by its
    # schema-version-free stable identity.
    resolution_ref_by_identity = {}
    for entry in resolution:
        resolution_ref_by_identity.setdefault(
            _source_stable_identity(entry.selected), entry.selected
        )
        for ref in entry.equivalent_discarded:
            resolution_ref_by_identity.setdefault(_source_stable_identity(ref), ref)
    provenance_refs = []
    for row in payload["source_snapshot_provenance"]:
        try:
            provenance_trade_date = date.fromisoformat(row["requested_trade_date"])
        except (TypeError, ValueError) as exc:
            _fail(
                f"source_snapshot_provenance requested_trade_date must be an ISO date: "
                f"{row['requested_trade_date']!r}"
            )
            raise AssertionError("unreachable") from exc
        key = (
            row["ingestion_run_id"],
            row["physical_snapshot_hash"],
            row["logical_source_rows_hash"],
            provenance_trade_date,
            row["requested_session"],
        )
        resolved = resolution_ref_by_identity.get(key)
        if resolved is None:
            _fail("source_snapshot_provenance record has no resolution source match")
        provenance_refs.append(resolved)

    # Deterministic output ordering: bars by (event_time, canonical_bar_key)
    # and gaps by (dataset_kind, code, interval, adjustment,
    # market_calendar_date, session, previous_event_time), matching the
    # materializer's documented order.
    bars.sort(key=lambda bar: (bar.event_time, bar.canonical_bar_key))
    gap_ranges.sort(
        key=lambda gap: (
            gap.dataset_kind,
            gap.code,
            gap.interval,
            gap.adjustment,
            gap.market_calendar_date,
            gap.session,
            gap.previous_event_time,
        )
    )
    return VerifiedCanonicalBuild(
        canonical_build_id=build_id,
        canonical_content_id=payload["canonical_content_id"],
        resolution_content_id=payload["resolution_content_id"],
        gap_content_id=payload["gap_content_id"],
        canonical_builder_version=payload["canonical_builder_version"],
        canonical_schema_version=payload["canonical_schema_version"],
        materializer_version=payload["materializer_version"],
        gap_policy_version=payload["gap_policy_version"],
        status=status,
        normalized_request=request,
        bars=tuple(bars),
        canonical_row_version_ids=tuple(sorted(seen_versions)),
        source_snapshot_provenance=tuple(provenance_refs),
        gap_ranges=tuple(gap_ranges),
        gap_count=len(gap_ranges),
        manifest_payload=payload,
        build_path=build_root,
    )


def _check_range(payload: dict, key: str, actual) -> None:
    declared = _manifest_timestamp(payload.get(key), key)
    if actual is None:
        if declared is not None:
            _fail(f"manifest {key} must be null for an empty build")
        return
    if declared is None:
        _fail(f"manifest {key} is null but the build contains bars")
    if declared != actual:
        _fail(
            f"manifest {key} {declared} does not match the actual content {actual}"
        )
