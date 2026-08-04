"""Deterministic ``dataset_id`` for derived datasets.

``dataset_id`` is a versioned SHA-256 over all identity-bearing normalized
fields of a :class:`DatasetIdentityInput`: dataset kind, normalized scope,
optional ``dataset_as_of`` cutoff, logical content ID, schema ID, ordered
Canonical build pins, explicitly pinned canonical row versions, Feature /
Label / Split spec fingerprints, implementation fingerprints, the completion
summary, gap references, the manifest schema version, and the serialization
format contract. It never depends on ``built_at``, output directories,
manifest file paths, Canonical ``snapshot_file`` or build paths, generated
Parquet file paths or byte hashes, local timezone, input list order, or
dictionary insertion order.
"""

from __future__ import annotations

from .content import dataset_schema_id
from .encoding import DatasetError, encode_identity
from .models import (
    CanonicalBuildPin,
    CompletionSummary,
    DatasetIdentityInput,
    GapReference,
    ImplementationPin,
    SpecPin,
)

_DATASET_ID_PREFIX = "dataset-id"
_SCOPE_PREFIX = "dataset-scope"
_BUILD_PREFIX = "dataset-canonical-build"
_SOURCE_PREFIX = "dataset-source-snapshot"
_SPEC_PREFIX = "dataset-spec"
_IMPLEMENTATION_PREFIX = "dataset-implementation"
_COMPLETION_PREFIX = "dataset-completion"
_COMPLETION_ENTRY_PREFIX = "dataset-completion-entry"
_GAP_REFERENCE_PREFIX = "dataset-gap-reference"


def _reject_duplicate_specs(specs: tuple[SpecPin, ...]) -> None:
    seen: set[tuple] = set()
    for spec in specs:
        key = (spec.kind, spec.name, spec.version)
        if key in seen:
            raise DatasetError(
                f"duplicate spec pin ({spec.kind}, {spec.name!r}, {spec.version!r})"
            )
        seen.add(key)


def _reject_duplicate_implementations(implementations: tuple[ImplementationPin, ...]) -> None:
    seen: set[tuple] = set()
    for item in implementations:
        key = (item.name, item.version)
        if key in seen:
            raise DatasetError(
                f"duplicate implementation pin ({item.name!r}, {item.version!r})"
            )
        seen.add(key)


def normalize_dataset_identity_input(identity_input: DatasetIdentityInput) -> DatasetIdentityInput:
    """Validate cross-field consistency of one identity input.

    Fails closed on: a ``dataset_schema_id`` that does not match the declared
    schema; duplicate or conflicting Canonical build pins; a canonical
    row-version ID not covered by the pinned Canonical builds; duplicate
    (kind, name, version) spec pins; duplicate (name, version) implementation
    pins; and gap references that name an unpinned build or disagree with the
    pinned build's gap content. Returns the input unchanged (its models
    normalize at construction).
    """
    if not isinstance(identity_input, DatasetIdentityInput):
        raise DatasetError(
            f"dataset_id requires a DatasetIdentityInput, got {type(identity_input).__name__}"
        )
    expected_schema_id = dataset_schema_id(identity_input.schema)
    if identity_input.dataset_schema_id != expected_schema_id:
        raise DatasetError("dataset_schema_id does not match the declared schema")

    builds = identity_input.canonical_builds
    pin_by_build_id: dict[str, CanonicalBuildPin] = {}
    for pin in builds:
        if pin.canonical_build_id in pin_by_build_id:
            raise DatasetError(
                f"duplicate canonical build pin {pin.canonical_build_id}"
            )
        pin_by_build_id[pin.canonical_build_id] = pin

    covered: set[str] = set()
    for pin in builds:
        covered.update(pin.canonical_row_version_ids)
    uncovered = sorted(set(identity_input.canonical_row_version_ids) - covered)
    if uncovered:
        raise DatasetError(
            "canonical row-version ID(s) not covered by the pinned canonical "
            f"builds: {uncovered}"
        )

    specs: list[SpecPin] = list(identity_input.feature_specs) + list(identity_input.label_specs)
    if identity_input.split_spec is not None:
        specs.append(identity_input.split_spec)
    _reject_duplicate_specs(tuple(specs))
    _reject_duplicate_implementations(identity_input.implementations)

    for ref in identity_input.gap_references:
        pin = pin_by_build_id.get(ref.canonical_build_id)
        if pin is None:
            raise DatasetError(
                f"gap reference names unknown canonical build {ref.canonical_build_id}"
            )
        if ref.gap_content_id != pin.gap_content_id:
            raise DatasetError(
                f"gap reference content does not match pinned build {ref.canonical_build_id}"
            )
    return identity_input


def _scope_digest(scope) -> str:
    return encode_identity(
        _SCOPE_PREFIX,
        {
            "symbols": "\x1e".join(scope.symbols),
            "trade_dates": "\x1e".join(value.isoformat() for value in scope.trade_dates),
            "adjustment": scope.adjustment,
            "interval": scope.interval,
            "requested_session": scope.requested_session,
        },
    )


def _source_snapshot_digest(snapshot) -> str:
    return encode_identity(
        _SOURCE_PREFIX,
        {
            "ingestion_run_id": snapshot.ingestion_run_id,
            "physical_snapshot_hash": snapshot.physical_snapshot_hash,
            "logical_source_rows_hash": snapshot.logical_source_rows_hash,
            "source_schema_version": snapshot.source_schema_version,
            "requested_trade_date": snapshot.requested_trade_date,
            "requested_session": snapshot.requested_session,
        },
    )


def _build_pin_digest(pin: CanonicalBuildPin) -> str:
    snapshot_digests = [
        _source_snapshot_digest(snapshot) for snapshot in pin.source_snapshots
    ]
    return encode_identity(
        _BUILD_PREFIX,
        {
            "canonical_build_id": pin.canonical_build_id,
            "canonical_content_id": pin.canonical_content_id,
            "canonical_builder_version": pin.canonical_builder_version,
            "canonical_schema_version": pin.canonical_schema_version,
            "materializer_version": pin.materializer_version,
            "gap_policy_version": pin.gap_policy_version,
            "gap_content_id": pin.gap_content_id,
            "status": pin.status,
            "canonical_row_version_ids": "\x1e".join(pin.canonical_row_version_ids),
            "source_snapshots": "\x1e".join(sorted(snapshot_digests)),
        },
    )


def _spec_digest(spec: SpecPin) -> str:
    return encode_identity(
        _SPEC_PREFIX,
        {
            "kind": spec.kind,
            "name": spec.name,
            "version": spec.version,
            "content_sha256": spec.content_sha256,
        },
    )


def _implementation_digest(item: ImplementationPin) -> str:
    return encode_identity(
        _IMPLEMENTATION_PREFIX,
        {
            "name": item.name,
            "version": item.version,
            "content_sha256": item.content_sha256,
        },
    )


def _completion_digest(summary: CompletionSummary) -> str:
    entry_digests = [
        encode_identity(
            _COMPLETION_ENTRY_PREFIX,
            {
                "code": entry.code,
                "trade_date": entry.trade_date,
                "status": entry.status,
                "reason_code": entry.reason_code,
            },
        )
        for entry in summary.entries
    ]
    return encode_identity(
        _COMPLETION_PREFIX,
        {
            "complete_count": summary.complete_count,
            "incomplete_count": summary.incomplete_count,
            "missing_count": summary.missing_count,
            "entries": "\x1e".join(sorted(entry_digests)),
        },
    )


def _gap_reference_digest(ref: GapReference) -> str:
    return encode_identity(
        _GAP_REFERENCE_PREFIX,
        {
            "canonical_build_id": ref.canonical_build_id,
            "gap_content_id": ref.gap_content_id,
            "gap_range_count": ref.gap_range_count,
        },
    )


def dataset_id(identity_input: DatasetIdentityInput) -> str:
    """Versioned SHA-256 over all identity-bearing normalized fields.

    Changing the logical content, output logical schema or field order,
    Canonical build/content/row version, source physical snapshot identity,
    Feature/Label/Split spec content hash, transform implementation
    version/hash, ``dataset_as_of``, scope, completion state, gap content
    reference, manifest schema version, serialization format/version, or the
    identity encoding version changes the ID. Input list order and
    dictionary insertion order never change it.
    """
    identity_input = normalize_dataset_identity_input(identity_input)
    build_digests = [_build_pin_digest(pin) for pin in identity_input.canonical_builds]
    feature_digests = [_spec_digest(spec) for spec in identity_input.feature_specs]
    label_digests = [_spec_digest(spec) for spec in identity_input.label_specs]
    implementation_digests = [
        _implementation_digest(item) for item in identity_input.implementations
    ]
    gap_digests = [_gap_reference_digest(ref) for ref in identity_input.gap_references]
    return encode_identity(
        _DATASET_ID_PREFIX,
        {
            "dataset_kind": identity_input.dataset_kind,
            "scope": _scope_digest(identity_input.scope),
            "dataset_as_of": identity_input.dataset_as_of,
            "logical_dataset_content_id": identity_input.logical_dataset_content_id,
            "dataset_schema_id": identity_input.dataset_schema_id,
            "canonical_builds": "\x1e".join(sorted(build_digests)),
            "canonical_row_version_ids": "\x1e".join(
                sorted(identity_input.canonical_row_version_ids)
            ),
            "feature_specs": "\x1e".join(sorted(feature_digests)),
            "label_specs": "\x1e".join(sorted(label_digests)),
            "split_spec": _spec_digest(identity_input.split_spec) if identity_input.split_spec else None,
            "implementations": "\x1e".join(sorted(implementation_digests)),
            "completion": _completion_digest(identity_input.completion),
            "gap_references": "\x1e".join(sorted(gap_digests)),
            "manifest_schema_version": identity_input.manifest_schema_version,
            "serialization_format": identity_input.serialization_format,
            "serialization_format_version": identity_input.serialization_format_version,
        },
    )
