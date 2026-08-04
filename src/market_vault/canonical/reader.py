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
two. The reader additionally verifies that the stored ``normalized_request``
is in canonical form, that every reconstructed row satisfies the manifest and
request contract, that each resolution entry binds exactly to its bar, that
the gap sidecar exactly equals the gaps re-derived from the bars (and that
each gap's boundary bars resolve uniquely), that the exact bars Parquet
schema matches ``canonical_bars_schema()``, and that all logical identities
(``canonical_bar_key``, ``canonical_row_version_id``,
``canonical_content_id``, ``resolution_content_id``, ``gap_content_id``,
``canonical_build_id``) are recomputed from the actual contents and match the
manifest.

The returned ``VerifiedCanonicalBuild`` is deeply immutable: the normalized
request is a frozen typed model and the manifest payload is stored as the
deterministic immutable bytes of the verified manifest file. ``build_path``
is descriptive metadata only; it never participates in any identity.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ..intraday_audit import parse_intraday_interval
from .bars import DEFAULT_DATASET_KIND
from .gaps import GAP_POLICY_VERSION, GapRange, derive_internal_gap_ranges
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
    CanonicalGapArithmeticError,
    CanonicalMaterializationError,
    CanonicalRequestKey,
    CanonicalResolutionEntry,
    CanonicalSourceRef,
)
from .schema import OPTIONAL_MARKET_COLUMNS, canonical_bars_schema

#: Reserved encoding separators of the Canonical identity layer.
_CANONICAL_SEPARATORS = ("\x1e", "\x1f", "|")

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
class VerifiedCanonicalRequest:
    """Frozen, deeply immutable normalized request of a verified build.

    Produced by the reader only after strict canonical-form validation of the
    stored ``normalized_request``: ``symbols`` are non-empty, uppercase,
    whitespace-free, sorted, deduplicated strings; ``trade_dates`` are
    sorted, deduplicated ISO dates; ``interval`` is normalized lowercase and
    parseable as an intraday interval; ``requested_session`` and
    ``adjustment`` are normalized uppercase; ``source_schema_version`` is a
    non-empty canonical string; control characters and reserved encoding
    separators are rejected.
    """

    symbols: tuple[str, ...]
    trade_dates: tuple[date, ...]
    interval: str
    requested_session: str
    adjustment: str
    source_schema_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "trade_dates", tuple(self.trade_dates))
        for name in (
            "interval",
            "requested_session",
            "adjustment",
            "source_schema_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise CanonicalArtifactValidationError(
                    f"VerifiedCanonicalRequest {name} must be a non-empty string"
                )


@dataclass(frozen=True)
class GapBoundaryBars:
    """The boundary bars of one internal gap, resolved from the same build.

    ``previous_archive_available_at`` is the archive availability of the bar
    before the gap; ``next_market_available_at`` is the market availability
    of the bar after the gap (the earliest instant the gap could be
    confirmed); ``next_archive_available_at`` is that bar's archive
    availability. The reader fails closed when a gap's boundary bars cannot
    be resolved uniquely.
    """

    gap_id: str
    previous_archive_available_at: pd.Timestamp
    next_market_available_at: pd.Timestamp
    next_archive_available_at: pd.Timestamp


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
    ``gap_ranges`` are the verified gap sidecar rows (each proven equal to
    the gaps re-derived from the bars); ``gap_boundaries`` carries one
    :class:`GapBoundaryBars` per gap, aligned by index. The build is deeply
    immutable: ``normalized_request`` is a frozen typed model and
    ``manifest_payload`` is the deterministic immutable manifest bytes.
    ``build_path`` is descriptive metadata only and never participates in
    any identity.
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
    normalized_request: VerifiedCanonicalRequest
    bars: tuple[CanonicalBar, ...]
    canonical_row_version_ids: tuple[str, ...]
    source_snapshot_provenance: tuple[CanonicalSourceRef, ...]
    gap_ranges: tuple[GapRange, ...]
    gap_boundaries: tuple[GapBoundaryBars, ...]
    gap_count: int
    manifest_payload: bytes
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


def _require_non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{label} must be a non-negative integer, got {value!r}")
    return value


def _reject_unsafe_text(value: str, label: str) -> None:
    """Control characters (C0 range) and reserved encoding separators fail,
    mirroring the Canonical materialization contract."""
    if any(ord(character) < 32 for character in value):
        _fail(f"control character in {label}: {value!r}")
    for separator in _CANONICAL_SEPARATORS:
        if separator in value:
            _fail(f"canonical encoding separator in {label}: {value!r}")


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


def _gap_equals(derived: GapRange, actual: GapRange) -> bool:
    """Exact field-by-field equality of one re-derived and one sidecar gap."""
    return (
        derived.gap_id == actual.gap_id
        and derived.gap_policy_version == actual.gap_policy_version
        and derived.dataset_kind == actual.dataset_kind
        and derived.code == actual.code
        and derived.interval == actual.interval
        and derived.adjustment == actual.adjustment
        and derived.market_calendar_date == actual.market_calendar_date
        and derived.session == actual.session
        and derived.previous_event_time == actual.previous_event_time
        and derived.next_event_time == actual.next_event_time
        and derived.missing_from_event_time == actual.missing_from_event_time
        and derived.missing_to_event_time == actual.missing_to_event_time
        and derived.missing_bar_count == actual.missing_bar_count
    )


def _resolve_gap_boundaries(
    bars: list[CanonicalBar], gap_ranges: list[GapRange]
) -> tuple[GapBoundaryBars, ...]:
    """Resolve each gap's previous/next boundary bars from the same build.

    A boundary bar must exist in the same (dataset_kind, code, interval,
    adjustment, market_calendar_date, session) group with the exact boundary
    event time; any gap that cannot be resolved uniquely fails closed.
    """
    by_group_and_time: dict[tuple, CanonicalBar] = {}
    for bar in bars:
        group = (
            bar.dataset_kind,
            bar.code,
            bar.interval,
            bar.adjustment,
            bar.market_calendar_date,
            bar.session,
        )
        by_group_and_time[(group, bar.event_time)] = bar
    boundaries = []
    for gap in gap_ranges:
        group = (
            gap.dataset_kind,
            gap.code,
            gap.interval,
            gap.adjustment,
            gap.market_calendar_date,
            gap.session,
        )
        previous = by_group_and_time.get((group, gap.previous_event_time))
        next_bar = by_group_and_time.get((group, gap.next_event_time))
        if previous is None or next_bar is None:
            _fail(
                f"gap {gap.gap_id} boundary bars cannot be resolved uniquely "
                "from the build contents"
            )
        boundaries.append(
            GapBoundaryBars(
                gap_id=gap.gap_id,
                previous_archive_available_at=previous.archive_available_at,
                next_market_available_at=next_bar.market_available_at,
                next_archive_available_at=next_bar.archive_available_at,
            )
        )
    return tuple(boundaries)


def _validate_normalized_request(section) -> VerifiedCanonicalRequest:
    """Strict canonical-form validation of the stored normalized request.

    The stored representation must already be normalized exactly as the
    materializer normalizes it (uppercase stripped symbols, sorted and
    deduplicated; sorted ISO trade dates; lowercase parseable interval;
    uppercase session/adjustment; stripped schema version; no control
    characters or encoding separators). A non-canonical stored
    representation fails closed; it is never silently re-sorted or accepted.
    """
    if not isinstance(section, dict):
        _fail("manifest normalized_request must be an object")
    unknown = sorted(set(section) - _NORMALIZED_REQUEST_FIELDS)
    if unknown:
        _fail(f"manifest normalized_request unknown field(s): {', '.join(unknown)}")
    missing = sorted(_NORMALIZED_REQUEST_FIELDS - set(section))
    if missing:
        _fail(f"manifest normalized_request missing field(s): {', '.join(missing)}")

    symbols = section["symbols"]
    if not isinstance(symbols, list) or not symbols:
        _fail("manifest normalized_request symbols must be a non-empty list")
    seen_symbols: set[str] = set()
    previous_symbol: str | None = None
    for item in symbols:
        if not isinstance(item, str) or not item:
            _fail(f"manifest normalized_request symbol must be a non-empty string: {item!r}")
        if item != item.strip().upper():
            _fail(
                f"manifest normalized_request symbol is not in canonical form "
                f"(uppercase, no leading/trailing whitespace): {item!r}"
            )
        _reject_unsafe_text(item, "normalized_request symbol")
        if item in seen_symbols:
            _fail(f"manifest normalized_request symbols must be deduplicated: {item!r}")
        seen_symbols.add(item)
        if previous_symbol is not None and item < previous_symbol:
            _fail("manifest normalized_request symbols must be sorted ascending")
        previous_symbol = item

    trade_dates = section["trade_dates"]
    if not isinstance(trade_dates, list) or not trade_dates:
        _fail("manifest normalized_request trade_dates must be a non-empty list")
    seen_dates: set[date] = set()
    previous_date_text: str | None = None
    parsed_trade_dates: list[date] = []
    for item in trade_dates:
        if not isinstance(item, str):
            _fail(f"manifest normalized_request trade_dates must be ISO strings, got {item!r}")
        try:
            parsed = date.fromisoformat(item)
        except ValueError as exc:
            _fail(f"manifest normalized_request trade_dates entry is not an ISO date: {item!r}")
            raise AssertionError("unreachable") from exc
        if item != parsed.isoformat():
            _fail(f"manifest normalized_request trade_dates entry is not canonical: {item!r}")
        if parsed in seen_dates:
            _fail(f"manifest normalized_request trade_dates must be deduplicated: {item!r}")
        seen_dates.add(parsed)
        if previous_date_text is not None and item < previous_date_text:
            _fail("manifest normalized_request trade_dates must be sorted ascending")
        previous_date_text = item
        parsed_trade_dates.append(parsed)

    interval = _require_text(section["interval"], "manifest normalized_request interval")
    if interval != interval.strip().lower():
        _fail(f"manifest normalized_request interval is not in canonical form: {interval!r}")
    _reject_unsafe_text(interval, "normalized_request interval")
    try:
        parse_intraday_interval(interval)
    except ValueError as exc:
        _fail(f"manifest normalized_request interval is not parseable: {interval!r}: {exc}")
        raise AssertionError("unreachable") from exc

    for name in ("requested_session", "adjustment"):
        value = _require_text(section[name], f"manifest normalized_request {name}")
        if value != value.strip().upper():
            _fail(f"manifest normalized_request {name} is not in canonical form: {value!r}")
        _reject_unsafe_text(value, f"normalized_request {name}")

    schema_version = _require_text(
        section["source_schema_version"], "manifest normalized_request source_schema_version"
    )
    if schema_version != schema_version.strip():
        _fail(
            f"manifest normalized_request source_schema_version is not in canonical form: "
            f"{schema_version!r}"
        )
    _reject_unsafe_text(schema_version, "normalized_request source_schema_version")

    return VerifiedCanonicalRequest(
        symbols=tuple(symbols),
        trade_dates=tuple(parsed_trade_dates),
        interval=interval,
        requested_session=section["requested_session"],
        adjustment=section["adjustment"],
        source_schema_version=schema_version,
    )


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
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise CanonicalArtifactValidationError(
            f"failed to read canonical build manifest.json: {build_root}: {exc}"
        ) from exc
    try:
        text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalArtifactValidationError(
            f"canonical build manifest.json is not valid UTF-8: {build_root}"
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

    # Top-level counts must be real non-negative ints; bools never pass.
    for name in (
        "source_snapshot_count",
        "canonical_row_count",
        "gap_range_count",
        "resolution_row_count",
    ):
        _require_non_negative_int(payload[name], f"manifest {name}")

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

    # Every bar must satisfy the manifest/request contract field by field.
    for bar in bars:
        if bar.dataset_kind != payload["dataset_kind"]:
            _fail(
                f"bar {bar.canonical_bar_key} dataset_kind does not match the manifest: "
                f"{bar.dataset_kind!r}"
            )
        if bar.code not in request.symbols:
            _fail(
                f"bar {bar.canonical_bar_key} code {bar.code!r} is not in the "
                "normalized request symbols"
            )
        if bar.requested_trade_date not in request.trade_dates:
            _fail(
                f"bar {bar.canonical_bar_key} requested_trade_date "
                f"{bar.requested_trade_date} is not in the normalized request trade dates"
            )
        if bar.interval != request.interval:
            _fail(
                f"bar {bar.canonical_bar_key} interval {bar.interval!r} does not match "
                f"the normalized request interval {request.interval!r}"
            )
        if bar.adjustment != request.adjustment:
            _fail(
                f"bar {bar.canonical_bar_key} adjustment {bar.adjustment!r} does not match "
                f"the normalized request adjustment {request.adjustment!r}"
            )
        if bar.requested_session != request.requested_session:
            _fail(
                f"bar {bar.canonical_bar_key} requested_session {bar.requested_session!r} "
                f"does not match the normalized request requested_session "
                f"{request.requested_session!r}"
            )
        if bar.source_schema_version != request.source_schema_version:
            _fail(
                f"bar {bar.canonical_bar_key} source_schema_version "
                f"{bar.source_schema_version!r} does not match the normalized request "
                f"source_schema_version {request.source_schema_version!r}"
            )
        if bar.canonical_builder_version != payload["canonical_builder_version"]:
            _fail(
                f"bar {bar.canonical_bar_key} canonical_builder_version "
                f"{bar.canonical_builder_version!r} does not match the manifest "
                f"canonical_builder_version {payload['canonical_builder_version']!r}"
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

    # Every resolution entry must bind exactly to its bar: the entry's
    # selected source must match the bar's own source field by field, and the
    # discarded sources must neither duplicate the selected source nor each
    # other. Manifest provenance and resolution identity sets were already
    # checked equal above; this per-key binding is the stronger contract.
    entry_by_key = {entry.canonical_bar_key: entry for entry in resolution}
    resolution_identities: set[tuple] = set()
    for bar in bars:
        entry = entry_by_key[bar.canonical_bar_key]
        selected = entry.selected
        if (
            selected.ingestion_run_id != bar.ingestion_run_id
            or selected.physical_snapshot_hash != bar.physical_snapshot_hash
            or selected.logical_source_rows_hash != bar.logical_source_rows_hash
            or selected.source_schema_version != bar.source_schema_version
            or selected.requested_trade_date != bar.requested_trade_date
            or selected.requested_session != bar.requested_session
            or selected.snapshot_file != bar.snapshot_file
        ):
            _fail(
                f"resolution selected source does not match its canonical bar: "
                f"{bar.canonical_bar_key}"
            )
        resolution_identities.add(_source_stable_identity(selected))
        seen_discarded: set[tuple] = set()
        for ref in entry.equivalent_discarded:
            identity = _source_stable_identity(ref)
            if identity == _source_stable_identity(selected):
                _fail(
                    f"equivalent_discarded_sources must not duplicate the selected "
                    f"source: {bar.canonical_bar_key}"
                )
            if identity in seen_discarded:
                _fail(
                    f"equivalent_discarded_sources contains a duplicate stable source "
                    f"identity: {bar.canonical_bar_key}"
                )
            seen_discarded.add(identity)
            resolution_identities.add(identity)

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
    # Deterministic gap ordering (the materializer's documented order).
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

    # The gap sidecar must exactly equal the gaps re-derived from the bars.
    interval_seconds = int(parse_intraday_interval(request.interval).total_seconds())
    try:
        derived_gaps = derive_internal_gap_ranges(tuple(bars), interval_seconds)
    except CanonicalGapArithmeticError as exc:
        raise CanonicalArtifactValidationError(
            f"gap sidecar cannot be re-derived from the bars: {exc}"
        ) from exc
    if len(derived_gaps) != len(gap_ranges):
        _fail(
            "gap sidecar does not match the gaps re-derived from the bars "
            "(count mismatch)"
        )
    for derived, actual in zip(derived_gaps, gap_ranges):
        if not _gap_equals(derived, actual):
            _fail(
                f"gap sidecar does not match the gaps re-derived from the bars: "
                f"{actual.gap_id}"
            )
    gap_boundaries = _resolve_gap_boundaries(bars, gap_ranges)

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
        interval=request.interval,
        requested_session=request.requested_session,
        adjustment=request.adjustment,
        source_schema_version=request.source_schema_version,
    )
    recomputed_build_id = canonical_build_id(
        symbols=list(request.symbols),
        trade_dates=list(request.trade_dates),
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

    # Deterministic output ordering: bars by (event_time, canonical_bar_key),
    # matching the materializer's documented order. Gaps were already sorted
    # above in their documented order before the re-derivation comparison.
    bars.sort(key=lambda bar: (bar.event_time, bar.canonical_bar_key))
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
        gap_boundaries=gap_boundaries,
        gap_count=len(gap_ranges),
        manifest_payload=manifest_bytes,
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
