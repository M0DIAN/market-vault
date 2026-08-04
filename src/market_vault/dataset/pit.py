"""Two-clock point-in-time sample assembly core.

Answers the v0.4.0 PR-6 question: given sample windows and an optional
``dataset_as_of``, which Canonical rows were legally visible at those times,
which immutable Canonical builds they come from, and how to record the
association deterministically.

:func:`assemble_point_in_time_samples` consumes verified Canonical build
artifacts (:class:`market_vault.canonical.reader.VerifiedCanonicalBuild`) and
frozen :class:`PITSampleRequest` definitions and produces a deterministic
:class:`PITAssemblyResult` with canonical build pins, selected row-version
IDs, gap references, the fixed sample-to-row association schema and rows,
and the association schema/content IDs — everything a future Dataset builder
needs without building the final DatasetManifest.

Two clocks are enforced per row:

- **market clock**: a Feature row must have ``market_available_at <=
  feature_window_close``; a Label row must have ``market_available_at <=
  label_window_close``. Rows available exactly at the close are allowed;
  rows available after the close are excluded and counted.
- **archive clock**: when ``dataset_as_of`` is set, a row must additionally
  have ``archive_available_at <= dataset_as_of``. Rows archived exactly at
  the cutoff are allowed; later rows are excluded and counted.

This module never computes Feature or Label values, never writes Dataset
Parquet, never builds a DatasetManifest, and never accesses OpenD or the
network.
"""

from __future__ import annotations

from ..canonical.reader import VerifiedCanonicalBuild
from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime
from .models import (
    CanonicalBuildPin,
    DatasetField,
    DatasetSchema,
    GapReference,
    SourceSnapshotPin,
)
from .pit_identity import pit_sample_key, pit_sample_version_id
from .pit_models import (
    PIT_ASSEMBLER_VERSION,
    PIT_ROLE_FEATURE,
    PIT_ROLE_LABEL,
    PITAssemblyDiagnostics,
    PITAssemblyError,
    PITAssemblyResult,
    PITDiagnostics,
    PITSample,
    PITSampleRequest,
)

__all__ = [
    "PIT_ASSOCIATION_COLUMNS",
    "assemble_point_in_time_samples",
    "pit_association_content_id",
    "pit_association_schema",
    "pit_association_schema_id",
]

#: Fixed authoritative column order of the sample-to-row association schema.
PIT_ASSOCIATION_COLUMNS = (
    "sample_key",
    "sample_version_id",
    "role",
    "position",
    "canonical_build_id",
    "canonical_bar_key",
    "canonical_row_version_id",
    "code",
    "event_time",
    "market_available_at",
    "archive_available_at",
)


def pit_association_schema() -> DatasetSchema:
    """Fixed logical Dataset schema of the sample-to-row association.

    Uses the PR-12 ``DatasetField`` / ``DatasetSchema`` model; the schema ID
    is the existing ``dataset_schema_id`` encoding. ``role`` is FEATURE or
    LABEL; ``position`` restarts at 0 per sample and role and follows the
    deterministic time sort, never the input order.
    """
    return DatasetSchema(
        tuple(
            DatasetField(name, logical_type, nullable=False)
            for name, logical_type in (
                ("sample_key", "string"),
                ("sample_version_id", "string"),
                ("role", "string"),
                ("position", "int64"),
                ("canonical_build_id", "string"),
                ("canonical_bar_key", "string"),
                ("canonical_row_version_id", "string"),
                ("code", "string"),
                ("event_time", "timestamp_us_utc"),
                ("market_available_at", "timestamp_us_utc"),
                ("archive_available_at", "timestamp_us_utc"),
            )
        )
    )


def pit_association_schema_id() -> str:
    """Deterministic schema ID of the association schema (PR-12 encoding)."""
    return dataset_schema_id(pit_association_schema())


def pit_association_content_id(rows) -> str:
    """Deterministic logical content ID of association rows (PR-12 encoding).

    Zero-row content gets a deterministic, request-independent content ID
    tied to the association schema; no placeholder row is fabricated.
    """
    return logical_dataset_content_id(pit_association_schema(), rows)


def assemble_point_in_time_samples(builds, requests, *, dataset_as_of=None) -> PITAssemblyResult:
    """Deterministically assemble point-in-time samples from verified builds.

    All input lists are order-insensitive: builds and requests are processed
    in deterministic order, identical canonical rows across builds are
    deduplicated, and conflicting candidates for the same
    ``canonical_bar_key`` fail closed — the "newest build", filesystem mtime,
    manifest ``created_at``, and input order are never used to pick a winner.
    No synthetic bars are generated and nothing is interpolated or
    forward-filled.

    Raises :class:`PITAssemblyError` on duplicate sample keys, conflicting or
    uncovered canonical rows, or cross-market-calendar-date label candidates.
    """
    build_items = tuple(builds)
    for item in build_items:
        if not isinstance(item, VerifiedCanonicalBuild):
            raise PITAssemblyError(
                f"builds must contain VerifiedCanonicalBuild instances, "
                f"got {type(item).__name__}"
            )
    builds_sorted = tuple(sorted(build_items, key=lambda build: build.canonical_build_id))

    request_items = tuple(requests)
    for item in request_items:
        if not isinstance(item, PITSampleRequest):
            raise PITAssemblyError(
                f"requests must contain PITSampleRequest instances, "
                f"got {type(item).__name__}"
            )
    request_keys = [pit_sample_key(request) for request in request_items]
    if len(set(request_keys)) != len(request_keys):
        raise PITAssemblyError("duplicate sample_key in requests")
    requests_sorted = sorted(request_items, key=pit_sample_key)

    if dataset_as_of is not None:
        try:
            dataset_as_of = normalize_utc_datetime(dataset_as_of, "dataset_as_of")
        except DatasetError as exc:
            raise PITAssemblyError(str(exc)) from exc

    candidates = _reconcile_rows(builds_sorted)
    version_to_candidate = {
        candidate["bar"].canonical_row_version_id: candidate for candidate in candidates
    }
    considered_build_ids = tuple(sorted({build.canonical_build_id for build in builds_sorted}))

    all_gap_ranges = tuple(
        gap for build in builds_sorted for gap in build.gap_ranges
    )
    samples = []
    selected_versions: set[str] = set()
    for request in requests_sorted:
        sample = _assemble_sample(
            request, dataset_as_of, candidates, considered_build_ids, all_gap_ranges
        )
        samples.append(sample)
        selected_versions.update(sample.feature_canonical_row_version_ids)
        selected_versions.update(sample.label_canonical_row_version_ids)

    pins = _build_pins(builds_sorted, selected_versions, version_to_candidate)
    gap_references = _build_gap_references(builds_sorted)

    samples_sorted = tuple(sorted(samples, key=lambda sample: sample.sample_key))
    association_rows = _association_rows(samples_sorted, version_to_candidate)
    schema = pit_association_schema()
    diagnostics = PITAssemblyDiagnostics(
        sample_count=len(samples_sorted),
        total_feature_rows=sum(
            len(sample.feature_canonical_row_version_ids) for sample in samples_sorted
        ),
        total_label_rows=sum(
            len(sample.label_canonical_row_version_ids) for sample in samples_sorted
        ),
        feature_market_future_excluded_count=sum(
            sample.diagnostics.feature_market_future_excluded_count
            for sample in samples_sorted
        ),
        feature_archive_future_excluded_count=sum(
            sample.diagnostics.feature_archive_future_excluded_count
            for sample in samples_sorted
        ),
        label_market_future_excluded_count=sum(
            sample.diagnostics.label_market_future_excluded_count
            for sample in samples_sorted
        ),
        label_archive_future_excluded_count=sum(
            sample.diagnostics.label_archive_future_excluded_count
            for sample in samples_sorted
        ),
        considered_canonical_build_ids=considered_build_ids,
    )
    return PITAssemblyResult(
        samples=samples_sorted,
        canonical_build_pins=pins,
        canonical_row_version_ids=tuple(sorted(selected_versions)),
        gap_references=gap_references,
        association_schema=schema,
        association_rows=tuple(association_rows),
        association_schema_id=dataset_schema_id(schema),
        association_content_id=logical_dataset_content_id(schema, association_rows),
        diagnostics=diagnostics,
    )


def _row_comparator(bar) -> tuple:
    """Full identity-bearing row content for cross-build reconciliation.

    Everything except ``snapshot_file`` (movable descriptive provenance):
    row version, market values, availability instants, classification, and
    stable source provenance.
    """
    return (
        bar.canonical_row_version_id,
        bar.event_time,
        bar.market_available_at,
        bar.archive_available_at,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.volume,
        bar.extra_fields,
        bar.ingestion_run_id,
        bar.physical_snapshot_hash,
        bar.logical_source_rows_hash,
        bar.source_schema_version,
        bar.canonical_builder_version,
        bar.requested_trade_date,
        bar.requested_session,
        bar.market_calendar_date,
        bar.session,
    )


def _reconcile_rows(builds: tuple) -> list[dict]:
    """Deterministic cross-build reconciliation of all candidate rows.

    Every row of every build must be covered by that build's declared
    row-version set. Rows sharing a ``canonical_bar_key`` are deduplicated
    only when they are completely identical (row version, market values, and
    provenance); any other combination fails closed instead of silently
    choosing a winner.
    """
    candidates: list[dict] = []
    for build in builds:
        declared = set(build.canonical_row_version_ids)
        for bar in build.bars:
            if bar.canonical_row_version_id not in declared:
                raise PITAssemblyError(
                    f"canonical row version {bar.canonical_row_version_id} is not "
                    f"covered by the declared provenance of canonical build "
                    f"{build.canonical_build_id}"
                )
            candidates.append({"bar": bar, "build_ids": (build.canonical_build_id,)})

    by_key: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_key.setdefault(candidate["bar"].canonical_bar_key, []).append(candidate)

    reconciled: list[dict] = []
    for bar_key in sorted(by_key):
        group = by_key[bar_key]
        reference = _row_comparator(group[0]["bar"])
        for candidate in group[1:]:
            if _row_comparator(candidate["bar"]) != reference:
                raise PITAssemblyError(
                    f"conflicting canonical candidates for canonical_bar_key {bar_key}: "
                    "rows differ in row version, market values, or provenance; "
                    "no silent winner is allowed"
                )
        merged = {
            "bar": group[0]["bar"],
            "build_ids": tuple(
                sorted({build_id for candidate in group for build_id in candidate["build_ids"]})
            ),
        }
        reconciled.append(merged)
    return reconciled


def _matches(bar, request: PITSampleRequest, window_start, window_close) -> bool:
    return (
        bar.code == request.code
        and bar.interval == request.interval
        and bar.adjustment == request.adjustment
        and bar.requested_session == request.requested_session
        and window_start <= bar.event_time < window_close
    )


def _select(candidates: list[dict], window_close, dataset_as_of) -> tuple:
    """Apply the market clock, then the optional archive clock.

    Exclusions are counted in that fixed order, so the counters are mutually
    exclusive and sum to the candidate count.
    """
    selected: list[dict] = []
    market_excluded = 0
    archive_excluded = 0
    for candidate in candidates:
        bar = candidate["bar"]
        if bar.market_available_at > window_close:
            market_excluded += 1
            continue
        if dataset_as_of is not None and bar.archive_available_at > dataset_as_of:
            archive_excluded += 1
            continue
        selected.append(candidate)
    return selected, market_excluded, archive_excluded


def _row_sort_key(candidate: dict) -> tuple:
    bar = candidate["bar"]
    return (
        bar.event_time,
        bar.market_available_at,
        bar.canonical_bar_key,
        bar.canonical_row_version_id,
    )


def _gap_overlaps(gap, window_start, window_close) -> bool:
    return (
        gap.missing_from_event_time < window_close
        and gap.missing_to_event_time >= window_start
    )


def _assemble_sample(
    request: PITSampleRequest,
    dataset_as_of,
    candidates: list[dict],
    considered_build_ids: tuple,
    all_gap_ranges: tuple,
) -> PITSample:
    feature_window = request.feature_window
    label_window = request.label_window

    feature_candidates = [
        candidate
        for candidate in candidates
        if _matches(
            candidate["bar"], request, feature_window.start, feature_window.close
        )
    ]
    label_candidates = (
        [
            candidate
            for candidate in candidates
            if _matches(
                candidate["bar"], request, label_window.start, label_window.close
            )
        ]
        if label_window is not None
        else []
    )

    # Default no-cross-trading-day label policy: every label row must belong
    # to the anchor market-calendar date; selecting a row of any other date
    # fails closed (no allow_cross_day temporary switch in this PR).
    for candidate in label_candidates:
        bar = candidate["bar"]
        if bar.market_calendar_date != request.anchor_market_calendar_date:
            raise PITAssemblyError(
                f"label candidate {bar.canonical_bar_key} has market_calendar_date "
                f"{bar.market_calendar_date}, which differs from the anchor "
                f"{request.anchor_market_calendar_date}; cross-market-calendar-date "
                "labels require an explicit spec opt-in and are not supported yet"
            )

    feature_selected, feature_market_excluded, feature_archive_excluded = _select(
        feature_candidates, feature_window.close, dataset_as_of
    )
    if label_window is not None:
        label_selected, label_market_excluded, label_archive_excluded = _select(
            label_candidates, label_window.close, dataset_as_of
        )
    else:
        label_selected, label_market_excluded, label_archive_excluded = [], 0, 0

    feature_selected.sort(key=_row_sort_key)
    label_selected.sort(key=_row_sort_key)
    feature_versions = tuple(
        candidate["bar"].canonical_row_version_id for candidate in feature_selected
    )
    label_versions = tuple(
        candidate["bar"].canonical_row_version_id for candidate in label_selected
    )

    sample_key = pit_sample_key(request)
    sample_version_id = pit_sample_version_id(
        sample_key=sample_key,
        dataset_as_of=dataset_as_of,
        feature_canonical_row_version_ids=feature_versions,
        label_canonical_row_version_ids=label_versions,
        considered_canonical_build_ids=considered_build_ids,
        assembler_version=PIT_ASSEMBLER_VERSION,
    )

    # Known internal gaps overlapping the window. Absence of known gaps never
    # implies a complete session: without an authoritative session schedule
    # only observed rows, known gaps, and exclusion counts are recorded.
    feature_gap_ids = sorted(
        {
            gap.gap_id
            for gap in all_gap_ranges
            if _gap_overlaps(gap, feature_window.start, feature_window.close)
        }
    )
    label_gap_ids = (
        sorted(
            {
                gap.gap_id
                for gap in all_gap_ranges
                if _gap_overlaps(gap, label_window.start, label_window.close)
            }
        )
        if label_window is not None
        else ()
    )

    diagnostics = PITDiagnostics(
        feature_candidate_count=len(feature_candidates),
        feature_selected_count=len(feature_selected),
        feature_market_future_excluded_count=feature_market_excluded,
        feature_archive_future_excluded_count=feature_archive_excluded,
        label_candidate_count=len(label_candidates),
        label_selected_count=len(label_selected),
        label_market_future_excluded_count=label_market_excluded,
        label_archive_future_excluded_count=label_archive_excluded,
        known_feature_gap_ids=feature_gap_ids,
        known_label_gap_ids=label_gap_ids,
        empty_observation_window=not feature_candidates,
    )
    return PITSample(
        sample_key=sample_key,
        sample_version_id=sample_version_id,
        request=request,
        dataset_as_of=dataset_as_of,
        feature_canonical_row_version_ids=feature_versions,
        label_canonical_row_version_ids=label_versions,
        considered_canonical_build_ids=considered_build_ids,
        diagnostics=diagnostics,
    )


def _build_pins(builds: tuple, selected_versions: set, version_to_candidate: dict) -> tuple:
    """CanonicalBuildPins from the verified manifests and actually selected rows.

    A pin records only the row versions actually selected by this assembly
    and only the source snapshots those rows reference. Paths and
    ``created_at`` never participate; pins are deduplicated by build ID
    (identical artifacts passed twice) and sorted deterministically.
    """
    pins_by_id: dict[str, CanonicalBuildPin] = {}
    for build in builds:
        selected_for_build = tuple(
            sorted(selected_versions & set(build.canonical_row_version_ids))
        )
        snapshots: list[SourceSnapshotPin] = []
        for version in selected_for_build:
            bar = version_to_candidate[version]["bar"]
            snapshots.append(
                SourceSnapshotPin(
                    ingestion_run_id=bar.ingestion_run_id,
                    physical_snapshot_hash=bar.physical_snapshot_hash,
                    logical_source_rows_hash=bar.logical_source_rows_hash,
                    source_schema_version=bar.source_schema_version,
                    requested_trade_date=bar.requested_trade_date,
                    requested_session=bar.requested_session,
                )
            )
        pins_by_id[build.canonical_build_id] = CanonicalBuildPin(
            canonical_build_id=build.canonical_build_id,
            canonical_content_id=build.canonical_content_id,
            canonical_builder_version=build.canonical_builder_version,
            canonical_schema_version=build.canonical_schema_version,
            materializer_version=build.materializer_version,
            gap_policy_version=build.gap_policy_version,
            gap_content_id=build.gap_content_id,
            status=build.status,
            canonical_row_version_ids=selected_for_build,
            source_snapshots=snapshots,
        )
    return tuple(sorted(pins_by_id.values(), key=lambda pin: pin.canonical_build_id))


def _build_gap_references(builds: tuple) -> tuple:
    """Strictly one GapReference per considered build, sorted by build ID."""
    references = []
    seen: set[str] = set()
    for build in builds:
        if build.canonical_build_id in seen:
            continue
        seen.add(build.canonical_build_id)
        references.append(
            GapReference(
                canonical_build_id=build.canonical_build_id,
                gap_content_id=build.gap_content_id,
                gap_range_count=build.gap_count,
            )
        )
    return tuple(sorted(references, key=lambda ref: ref.canonical_build_id))


def _association_rows(samples: tuple, version_to_candidate: dict) -> list[dict]:
    """Deterministic sample-to-row association rows in fixed column order.

    Rows are emitted per sample (sorted by ``sample_key``), per role
    (FEATURE then LABEL), in deterministic time-sorted position order. For a
    row deduplicated across identical builds the first (sorted) build ID is
    recorded.
    """
    rows = []
    for sample in samples:
        for role, versions in (
            (PIT_ROLE_FEATURE, sample.feature_canonical_row_version_ids),
            (PIT_ROLE_LABEL, sample.label_canonical_row_version_ids),
        ):
            for position, version in enumerate(versions):
                candidate = version_to_candidate[version]
                bar = candidate["bar"]
                rows.append(
                    {
                        "sample_key": sample.sample_key,
                        "sample_version_id": sample.sample_version_id,
                        "role": role,
                        "position": position,
                        "canonical_build_id": candidate["build_ids"][0],
                        "canonical_bar_key": bar.canonical_bar_key,
                        "canonical_row_version_id": version,
                        "code": bar.code,
                        "event_time": bar.event_time,
                        "market_available_at": bar.market_available_at,
                        "archive_available_at": bar.archive_available_at,
                    }
                )
    return rows
