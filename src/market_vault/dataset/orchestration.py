"""Pure in-memory Dataset orchestration entry (v0.5.0 PR-5).

This module connects the already-shipped layers — verified Canonical builds,
PIT sample assembly, built-in Feature execution, built-in Label execution,
and chronological split / purge — into one deterministic, fail-closed,
pure in-memory Dataset build pipeline:

- explicit supervised-build inputs only (no paths, no registry, no
  transform callback, no clock, no current time, no writer, no filesystem);
- exactly one invocation of the PIT assembler, the Feature executor, the
  Label executor, and the chronological splitter;
- strict PIT / Feature / Label sample binding;
- Feature EXCLUDED samples filtered out of split assignment and rows;
- Label INCOMPLETE samples handed to the splitter with their true status
  and ``actual_label_end_time``;
- the authoritative logical Dataset schema, final logical rows, the
  scope-wide CompletionSummary, the merged ImplementationPins,
  ``logical_dataset_content_id``, ``DatasetIdentityInput``, and
  ``dataset_id``.

Nothing is written: no Dataset directory, no Parquet, no DatasetManifest,
no build report, no spec artifacts, no ``_SUCCESS``, and no
``build_dataset_manifest`` call. Materialization is PR-6; this entry is the
only trusted in-memory input to it. All documented validation failures of
the underlying layers surface as :class:`DatasetOrchestrationError` with
their ``__cause__`` preserved (fail closed, no partial result).
"""

from __future__ import annotations

from ..canonical.reader import VerifiedCanonicalBuild
from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime
from .feature_execution import execute_builtin_features
from .feature_models import FEATURE_VALUE_STATUS_COMPLETE
from .identity import dataset_id
from .label_execution import execute_builtin_labels
from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    DatasetIdentityInput,
    DatasetSchema,
    DatasetScope,
)
from .orchestration_models import (
    DATASET_KIND_SUPERVISED,
    DATASET_ORCHESTRATION_CONTRACT_VERSION,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    DatasetOrchestrationError,
    DatasetOrchestrationResult,
    _as_orchestration_error,
    _build_completion,
    _build_diagnostics,
    _build_logical_rows,
    _build_split_samples,
    _merge_implementation_pins,
    _row_mappings,
    _verify_sample_binding,
    dataset_orchestration_schema,
)
from .pit import assemble_point_in_time_samples
from .pit_models import PITSampleRequest
from .spec_models import FeatureSpec, LabelSpec
from .split_models import ChronologicalSplitSpec
from .splits import assign_chronological_splits

__all__ = ["orchestrate_dataset_build"]


def orchestrate_dataset_build(
    *,
    builds,
    requests,
    feature_specs,
    label_specs,
    split_spec,
    scope,
    schema,
    dataset_as_of,
    dataset_kind,
    manifest_schema_version,
    serialization_format,
    serialization_format_version,
) -> DatasetOrchestrationResult:
    """Deterministically orchestrate one supervised Dataset build in memory.

    All arguments are keyword-only. ``builds`` are verified Canonical builds
    (at least one; input order never matters); ``requests`` are
    ``PITSampleRequest`` instances (may be empty; every request must lie
    inside ``scope``); ``feature_specs`` / ``label_specs`` are the spec
    instances (at least one each, order-insensitive, no cross-kind mixing);
    ``split_spec`` is the ``ChronologicalSplitSpec``; ``scope`` is the
    ``DatasetScope``; ``schema`` must exactly equal the authoritative schema
    derived from the specs and ``dataset_as_of``; ``dataset_as_of`` is None
    or a timezone-aware datetime (normalized to UTC microseconds and used
    identically by PIT, the samples, the rows, and the identity);
    ``dataset_kind`` must be ``DATASET_KIND_SUPERVISED``;
    ``manifest_schema_version`` / ``serialization_format`` /
    ``serialization_format_version`` must be the current contract values.
    Any other value fails closed; the entry takes no output path, no
    filesystem, no clock, and no callback.

    The pipeline executes exactly once in the fixed order: preflight, scope /
    request consistency, authoritative schema derivation and exact match,
    ``assemble_point_in_time_samples``, ``execute_builtin_features``,
    ``execute_builtin_labels`` (both over the same PIT result), strict sample
    binding, ChronologicalSplitSample construction for Feature COMPLETE
    samples, ``assign_chronological_splits``, split-set equality, completion,
    final rows, ``dataset_schema_id``, ``logical_dataset_content_id``,
    ImplementationPin merge, ``DatasetIdentityInput``, and ``dataset_id``.

    Raises :class:`DatasetOrchestrationError` on any documented validation
    failure (fail closed; no partial result is ever returned).
    """
    try:
        return _orchestrate(
            builds=builds,
            requests=requests,
            feature_specs=feature_specs,
            label_specs=label_specs,
            split_spec=split_spec,
            scope=scope,
            schema=schema,
            dataset_as_of=dataset_as_of,
            dataset_kind=dataset_kind,
            manifest_schema_version=manifest_schema_version,
            serialization_format=serialization_format,
            serialization_format_version=serialization_format_version,
        )
    except (DatasetError, TypeError, ValueError, KeyError) as exc:
        _as_orchestration_error(
            exc, "orchestrate_dataset_build failed"
        )


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise DatasetOrchestrationError(reason)


def _orchestrate(
    *,
    builds,
    requests,
    feature_specs,
    label_specs,
    split_spec,
    scope,
    schema,
    dataset_as_of,
    dataset_kind,
    manifest_schema_version,
    serialization_format,
    serialization_format_version,
) -> DatasetOrchestrationResult:
    # 1. Freeze input iterables once; every later use is over frozen tuples.
    build_items = tuple(builds)
    request_items = tuple(requests)
    feature_items = tuple(feature_specs)
    label_items = tuple(label_specs)

    # 2. Input type and non-empty preflight.
    _require(
        build_items,
        "builds must contain at least one VerifiedCanonicalBuild",
    )
    for item in build_items:
        _require(
            isinstance(item, VerifiedCanonicalBuild),
            f"builds must contain VerifiedCanonicalBuild instances, got "
            f"{type(item).__name__}",
        )
    for item in request_items:
        _require(
            isinstance(item, PITSampleRequest),
            f"requests must contain PITSampleRequest instances, got "
            f"{type(item).__name__}",
        )
    _require(
        feature_items,
        "feature_specs must contain at least one FeatureSpec",
    )
    for item in feature_items:
        _require(
            isinstance(item, FeatureSpec),
            f"feature_specs must contain FeatureSpec instances, got "
            f"{type(item).__name__}",
        )
    _require(
        label_items,
        "label_specs must contain at least one LabelSpec",
    )
    for item in label_items:
        _require(
            isinstance(item, LabelSpec),
            f"label_specs must contain LabelSpec instances, got "
            f"{type(item).__name__}",
        )
    _require(
        isinstance(split_spec, ChronologicalSplitSpec),
        f"split_spec must be a ChronologicalSplitSpec, got "
        f"{type(split_spec).__name__}",
    )
    _require(
        isinstance(scope, DatasetScope),
        f"scope must be a DatasetScope, got {type(scope).__name__}",
    )
    _require(
        isinstance(schema, DatasetSchema),
        f"schema must be a DatasetSchema, got {type(schema).__name__}",
    )
    if dataset_as_of is not None:
        dataset_as_of = normalize_utc_datetime(dataset_as_of, "dataset_as_of")
    _require(
        dataset_kind == DATASET_KIND_SUPERVISED,
        f"dataset_kind must be {DATASET_KIND_SUPERVISED}, got "
        f"{dataset_kind!r}",
    )
    _require(
        manifest_schema_version == DATASET_MANIFEST_SCHEMA_VERSION,
        f"manifest_schema_version must be "
        f"{DATASET_MANIFEST_SCHEMA_VERSION}, got "
        f"{manifest_schema_version!r}",
    )
    _require(
        serialization_format == SERIALIZATION_FORMAT_PARQUET,
        f"serialization_format must be {SERIALIZATION_FORMAT_PARQUET}, got "
        f"{serialization_format!r}",
    )
    _require(
        serialization_format_version == SERIALIZATION_FORMAT_VERSION_PARQUET,
        f"serialization_format_version must be "
        f"{SERIALIZATION_FORMAT_VERSION_PARQUET}, got "
        f"{serialization_format_version!r}",
    )

    # 3. Scope / request consistency preflight.
    for item in request_items:
        _require(
            item.code in scope.symbols,
            f"request {item.code!r} is outside the scope symbols",
        )
        _require(
            item.anchor_market_calendar_date in scope.trade_dates,
            f"request anchor date "
            f"{item.anchor_market_calendar_date.isoformat()} for "
            f"{item.code!r} is outside the scope trade dates",
        )
        _require(
            item.interval == scope.interval,
            f"request interval {item.interval!r} must equal the scope "
            f"interval {scope.interval!r}",
        )
        _require(
            item.adjustment == scope.adjustment,
            f"request adjustment {item.adjustment!r} must equal the scope "
            f"adjustment {scope.adjustment!r}",
        )
        _require(
            item.requested_session == scope.requested_session,
            f"request requested_session {item.requested_session!r} must "
            f"equal the scope requested_session {scope.requested_session!r}",
        )

    # 4. Specs deterministic ordering and authoritative schema derivation.
    expected_schema = dataset_orchestration_schema(
        feature_items,
        label_items,
        include_dataset_as_of=dataset_as_of is not None,
    )

    # 5. Provided schema must exactly match the authoritative schema.
    if schema != expected_schema:
        raise DatasetOrchestrationError(
            "provided schema does not exactly equal the authoritative "
            "Dataset schema derived from the specs and dataset_as_of; "
            "field names, order, types, and nullability must match exactly"
        )

    # 6-7. PIT assembly; Feature and Label execution over the same result.
    pit_result = assemble_point_in_time_samples(
        build_items, request_items, dataset_as_of=dataset_as_of
    )
    feature_result = execute_builtin_features(
        build_items, pit_result, feature_items
    )
    label_result = execute_builtin_labels(
        build_items, pit_result, label_items
    )

    # 8-9. Strict PIT / Feature / Label sample binding.
    _verify_sample_binding(
        pit_result, feature_result, label_result, dataset_as_of
    )

    # 10-11. Feature EXCLUDED filtering and ChronologicalSplitSample
    # construction for the Feature COMPLETE samples.
    split_samples = _build_split_samples(feature_result, label_result)

    # 12. Chronological split and purge (single existing contract).
    split_result = assign_chronological_splits(split_samples, split_spec)

    # 13. Split sample set must exactly equal the Feature COMPLETE set.
    complete_keys = {
        sample.sample_key
        for sample in feature_result.samples
        if sample.status == FEATURE_VALUE_STATUS_COMPLETE
    }
    _require(
        {assignment.sample_key for assignment in split_result.assignments}
        == complete_keys,
        "split result samples must equal the Feature COMPLETE sample set",
    )

    # 14-16. Completion, final rows, physical order.
    completion = _build_completion(
        scope, pit_result, feature_result, label_result
    )
    rows = _build_logical_rows(
        pit_result, feature_result, label_result, split_result, expected_schema
    )

    # 17-18. Schema and content identities.
    schema_id = dataset_schema_id(expected_schema)
    content_id = logical_dataset_content_id(
        expected_schema, _row_mappings(rows, expected_schema)
    )

    # 19-21. Implementation pins, DatasetIdentityInput, dataset_id.
    implementations = _merge_implementation_pins(
        feature_result, label_result
    )
    identity_input = DatasetIdentityInput(
        dataset_kind=dataset_kind,
        scope=scope,
        dataset_as_of=dataset_as_of,
        schema=expected_schema,
        dataset_schema_id=schema_id,
        logical_dataset_content_id=content_id,
        canonical_builds=pit_result.canonical_build_pins,
        canonical_row_version_ids=pit_result.canonical_row_version_ids,
        feature_specs=feature_result.feature_spec_pins,
        label_specs=label_result.label_spec_pins,
        split_spec=split_result.split_spec_pin,
        implementations=implementations,
        completion=completion,
        gap_references=pit_result.gap_references,
        manifest_schema_version=manifest_schema_version,
        serialization_format=serialization_format,
        serialization_format_version=serialization_format_version,
    )
    dataset_id_value = dataset_id(identity_input)

    # 22. Deterministic diagnostics; status; result model re-verifies.
    diagnostics = _build_diagnostics(
        scope,
        len(request_items),
        pit_result,
        feature_result,
        label_result,
        split_result,
        rows,
        completion,
    )
    status = STATUS_EMPTY if not rows else STATUS_COMPLETE
    return DatasetOrchestrationResult(
        status=status,
        dataset_kind=dataset_kind,
        scope=scope,
        dataset_as_of=dataset_as_of,
        feature_specs=feature_items,
        label_specs=label_items,
        split_spec=split_spec,
        pit_result=pit_result,
        feature_result=feature_result,
        label_result=label_result,
        split_result=split_result,
        schema=expected_schema,
        rows=rows,
        dataset_schema_id=schema_id,
        logical_dataset_content_id=content_id,
        identity_input=identity_input,
        dataset_id=dataset_id_value,
        completion=completion,
        diagnostics=diagnostics,
        manifest_schema_version=manifest_schema_version,
        serialization_format=serialization_format,
        serialization_format_version=serialization_format_version,
        row_order=DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
        orchestration_contract_version=DATASET_ORCHESTRATION_CONTRACT_VERSION,
    )
