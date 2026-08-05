"""Shared PIT / Canonical execution provenance verification (v0.5.0 PR-4).

The built-in Feature executor (PR-3) and the built-in Label executor (PR-4)
share one strict PIT-to-Canonical binding and provenance verification path.
This private module holds the genuinely common parts so that the two
executors cannot drift into two subtly different implementations:

- :class:`ResolvedRow` — one row-version binding (reconciled bar plus every
  build that carries it, deterministically sorted);
- :func:`normalize_verified_builds` — VerifiedCanonicalBuild-only, duplicate-
  free, deterministically sorted build input normalization;
- :func:`reconcile_canonical_rows` — deterministic cross-build row-version
  reconciliation (identical rows deduplicate; conflicting rows fail closed;
  the "newest build", mtime, and input order never pick a winner);
- :func:`verify_pit_pin_binding` — the exact bidirectional Pin verification
  against the PIT facts (selected row-version union, one exact
  ``CanonicalBuildPin`` per supplied build, per-row ``SourceSnapshotPin``
  provenance mirroring the PIT ``_build_pins`` rule, and the considered
  build-id equality checks);
- :func:`expected_canonical_build_pin` — the exact reconstruction of one
  build's pin from the supplied build and the actually selected rows.

This module is **private**: it is never exported from
:mod:`market_vault.dataset`, and public executors never expose it. All
failures surface as the private :class:`ExecutionProvenanceError` (a
``DatasetError`` subclass); the public Feature entry point converts them to
:class:`FeatureExecutionError` and the public Label entry point converts
them to :class:`LabelExecutionError`, preserving the ``__cause__`` chain.

The PIT and Canonical modules are never modified, and no identity or
version constant is changed by this extraction.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..canonical.reader import VerifiedCanonicalBuild
from .encoding import DatasetError
from .models import CanonicalBuildPin, SourceSnapshotPin
from .pit import _row_comparator
from .pit_models import PITAssemblyResult

__all__: list[str] = []


class ExecutionProvenanceError(DatasetError):
    """Private fail-closed failure of the shared execution provenance path.

    Raised by :func:`normalize_verified_builds`,
    :func:`reconcile_canonical_rows`, :func:`verify_pit_pin_binding`, and
    :func:`expected_canonical_build_pin`. Public executors convert this
    error to their own public error at the entry boundary; it never leaks
    past a public API.
    """


@dataclass(frozen=True)
class ResolvedRow:
    """One row-version binding: the reconciled bar and every build that
    carries it (deterministically sorted)."""

    bar: object
    build_ids: tuple[str, ...]


def normalize_verified_builds(builds) -> tuple[VerifiedCanonicalBuild, ...]:
    """Verified builds only, deterministically sorted by build id; duplicate
    build ids fail closed."""
    try:
        items = tuple(builds)
    except TypeError as exc:
        raise ExecutionProvenanceError(
            "builds must be an iterable of VerifiedCanonicalBuild instances, "
            f"got {type(builds).__name__}"
        ) from exc
    for item in items:
        if not isinstance(item, VerifiedCanonicalBuild):
            raise ExecutionProvenanceError(
                "builds must contain VerifiedCanonicalBuild instances produced "
                f"by the verified reader, got {type(item).__name__}"
            )
    build_ids = [build.canonical_build_id for build in items]
    if len(set(build_ids)) != len(build_ids):
        raise ExecutionProvenanceError("duplicate canonical_build_id in builds")
    return tuple(sorted(items, key=lambda build: build.canonical_build_id))


def reconcile_canonical_rows(
    build_items: tuple,
) -> dict[str, ResolvedRow]:
    """Deterministic row-version binding across the supplied builds.

    Every bar must be covered by its build's declared row-version set, and
    every declared version must have a bar. Identical rows across builds
    deduplicate deterministically (the build-id sets are merged); the same
    version id with conflicting content fails closed — the "newest build",
    mtime, and input order never select a winner.
    """
    reconciled: dict[str, ResolvedRow] = {}
    for build in build_items:
        declared = set(build.canonical_row_version_ids)
        bar_versions = [bar.canonical_row_version_id for bar in build.bars]
        if len(set(bar_versions)) != len(bar_versions):
            raise ExecutionProvenanceError(
                f"build {build.canonical_build_id} contains duplicate bar "
                "canonical_row_version_id values"
            )
        if set(bar_versions) != declared:
            raise ExecutionProvenanceError(
                f"build {build.canonical_build_id} bars do not match its "
                "declared canonical row-version provenance exactly"
            )
        for bar in build.bars:
            existing = reconciled.get(bar.canonical_row_version_id)
            if existing is None:
                reconciled[bar.canonical_row_version_id] = ResolvedRow(
                    bar=bar, build_ids=(build.canonical_build_id,)
                )
            else:
                if _row_comparator(existing.bar) != _row_comparator(bar):
                    raise ExecutionProvenanceError(
                        f"conflicting canonical rows for row version id "
                        f"{bar.canonical_row_version_id}: identical row "
                        "versions from different builds disagree; no silent "
                        "winner is allowed"
                    )
                reconciled[bar.canonical_row_version_id] = ResolvedRow(
                    bar=existing.bar,
                    build_ids=tuple(
                        sorted(set(existing.build_ids) | {build.canonical_build_id})
                    ),
                )
    return reconciled


def verify_pit_pin_binding(
    pit_result: PITAssemblyResult,
    builds_by_id: dict,
    rows_by_version: dict,
) -> None:
    """Exact bidirectional Pin verification against the PIT facts.

    The PIT assembly result's own provenance facts are re-verified, never
    re-selected: the union of every sample's Feature and Label row version
    ids must equal ``pit_result.canonical_row_version_ids`` exactly; the
    Pin set must be exactly one Pin per supplied build (no duplicates, no
    extras); and every Pin must equal the Pin **exactly reconstructed**
    from the supplied build and the actually selected rows — identity
    fields, the selected row-version intersection, and the per-row
    ``SourceSnapshotPin`` provenance (``ingestion_run_id``,
    ``physical_snapshot_hash``, ``logical_source_rows_hash``,
    ``source_schema_version``, ``requested_trade_date``,
    ``requested_session``), mirroring the PIT ``_build_pins`` rules. Label
    rows never enter Feature transforms, but they are original PIT assembly
    provenance and therefore participate in this exact Pin verification.
    ``pit_result.diagnostics.considered_canonical_build_ids`` and every
    sample's ``considered_canonical_build_ids`` must equal the supplied
    build ids exactly. No "newest build", mtime, or input order ever picks
    a winner.
    """
    try:
        samples = tuple(pit_result.samples)
    except TypeError as exc:
        raise ExecutionProvenanceError(
            "pit_result.samples must be iterable"
        ) from exc
    selected: set[str] = set()
    for sample in samples:
        selected.update(sample.feature_canonical_row_version_ids)
        selected.update(sample.label_canonical_row_version_ids)

    try:
        declared_row_version_ids = tuple(pit_result.canonical_row_version_ids)
    except TypeError as exc:
        raise ExecutionProvenanceError(
            "pit_result.canonical_row_version_ids must be iterable"
        ) from exc
    if declared_row_version_ids != tuple(sorted(selected)):
        raise ExecutionProvenanceError(
            "pit_result.canonical_row_version_ids must equal the sorted union "
            "of all selected Feature and Label row version ids; missing or "
            "extra row versions fail closed"
        )

    try:
        pins = tuple(pit_result.canonical_build_pins)
    except TypeError as exc:
        raise ExecutionProvenanceError(
            "pit_result.canonical_build_pins must be iterable"
        ) from exc
    pin_ids = [pin.canonical_build_id for pin in pins]
    if len(set(pin_ids)) != len(pin_ids):
        raise ExecutionProvenanceError(
            "pit_result canonical_build_pins must not contain duplicate "
            "canonical_build_id values"
        )
    supplied_ids = tuple(sorted(builds_by_id))
    if set(pin_ids) != set(builds_by_id):
        raise ExecutionProvenanceError(
            "pit_result canonical_build_pins must correspond exactly to the "
            f"supplied builds; pinned {sorted(set(pin_ids))} vs supplied "
            f"{list(supplied_ids)}"
        )
    for build_id in supplied_ids:
        build = builds_by_id[build_id]
        pin = next(pin for pin in pins if pin.canonical_build_id == build_id)
        expected = expected_canonical_build_pin(build, selected, rows_by_version)
        if pin != expected:
            raise ExecutionProvenanceError(
                f"canonical build pin {build_id} does not exactly equal the "
                "pin reconstructed from the supplied build and the actually "
                "selected rows; identity fields, selected row versions, or "
                "source snapshot provenance mismatch"
            )

    if pit_result.diagnostics.considered_canonical_build_ids != supplied_ids:
        raise ExecutionProvenanceError(
            "pit_result diagnostics considered_canonical_build_ids must equal "
            f"the supplied build ids exactly; got "
            f"{tuple(pit_result.diagnostics.considered_canonical_build_ids)!r}"
        )
    for sample in samples:
        if sample.considered_canonical_build_ids != supplied_ids:
            raise ExecutionProvenanceError(
                f"sample {sample.sample_key!r} considered_canonical_build_ids "
                f"must equal the supplied build ids exactly; got "
                f"{tuple(sample.considered_canonical_build_ids)!r}"
            )


def expected_canonical_build_pin(
    build, selected: set, rows_by_version: dict
) -> CanonicalBuildPin:
    """Exactly reconstruct the canonical build pin of one supplied build
    from the actually selected rows, mirroring the PIT ``_build_pins``
    rules: the row-version intersection with the build's declared set and
    one source snapshot pin per selected row of the build."""
    selected_for_build = tuple(
        sorted(selected & set(build.canonical_row_version_ids))
    )
    snapshots: list[SourceSnapshotPin] = []
    for version in selected_for_build:
        resolved_row = rows_by_version.get(version)
        if resolved_row is None:
            raise ExecutionProvenanceError(
                f"PIT assembly selected row version {version} of build "
                f"{build.canonical_build_id}, which no supplied build contains"
            )
        bar = resolved_row.bar
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
    try:
        return CanonicalBuildPin(
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
    except DatasetError as exc:
        raise ExecutionProvenanceError(
            f"cannot reconstruct the expected canonical build pin of build "
            f"{build.canonical_build_id}: {exc}"
        ) from exc
