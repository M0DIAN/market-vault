"""Chronological split assignment and actual-label-end purge core (v0.4.0
PR-8).

Answers the v0.4.0 PR-8 question: given explicit split sample timing facts
(``ChronologicalSplitSample``) and a frozen ``ChronologicalSplitSpec``, assign
each sample a nominal split by the local-market date of its feature window
close in the spec's explicitly declared IANA boundary timezone, exclude
caller-declared INCOMPLETE labels, purge TRAIN/VALIDATION samples whose actual
label end crosses the next-local-midnight exclusive boundary, and produce a
deterministic :class:`ChronologicalSplitResult` with the fixed assignment
schema, rows, schema/content identities, result identity, and diagnostics.

The data-flow boundary of this PR:

```text
explicit split sample timing facts
    -> chronological nominal assignment
    -> incomplete-label exclusion
    -> actual-label-end purge
    -> deterministic split-assignment content
```

This layer never computes Feature or Label values, never executes transforms,
never reads a ``LabelSpec.horizon`` or any nominal horizon, never infers label
completeness from PIT diagnostics, never builds a DatasetManifest, never
writes Dataset Parquet or a Dataset build directory, and never touches OpenD
or the network. ``actual_label_end_time`` is the only purge time fact.

All failures surface as :class:`SplitValidationError`; input sample order is
never semantic (samples are sorted by ``sample_key``) and duplicate sample
keys fail closed.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from .split_models import (
    CHRONOLOGICAL_SPLITTER_VERSION,
    LABEL_STATUS_INCOMPLETE,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
    REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
    REASON_CODE_INCOMPLETE_LABEL,
    SPLIT_ASSIGNMENT_SCHEMA_VERSION,
    SPLIT_ASSIGNMENT_COLUMNS,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
    ChronologicalSplitAssignment,
    ChronologicalSplitDiagnostics,
    ChronologicalSplitResult,
    ChronologicalSplitSample,
    ChronologicalSplitSpec,
    SplitValidationError,
    chronological_split_result_id,
    chronological_split_spec_content_id,
    chronological_split_spec_pin,
    split_assignment_content_id,
    split_assignment_schema,
    split_assignment_schema_id,
    _assignment_rows,
    _derive_diagnostics,
    _next_local_midnight_utc,
)

__all__ = [
    "SPLIT_ASSIGNMENT_COLUMNS",
    "assign_chronological_splits",
    "chronological_split_result_id",
    "chronological_split_spec_content_id",
    "chronological_split_spec_pin",
    "split_assignment_content_id",
    "split_assignment_schema",
    "split_assignment_schema_id",
]


def _nominal_split_for_date(close_date, spec: ChronologicalSplitSpec) -> str | None:
    """Nominal split by the local-market date of the feature window close.

    ``close_date <= train_end_date`` -> TRAIN;
    ``train_end_date < close_date <= validation_end_date`` -> VALIDATION;
    ``validation_end_date < close_date <= test_end_date`` -> TEST;
    otherwise None (out of range).
    """
    if close_date <= spec.train_end_date:
        return SPLIT_TRAIN
    if close_date <= spec.validation_end_date:
        return SPLIT_VALIDATION
    if close_date <= spec.test_end_date:
        return SPLIT_TEST
    return None


def _assign_sample(
    sample: ChronologicalSplitSample,
    spec: ChronologicalSplitSpec,
    boundary_timezone: str,
    train_boundary,
    validation_boundary,
) -> ChronologicalSplitAssignment:
    """Fixed per-sample processing order:

    1. nominal split by the feature close local-market date;
    2. feature close after test end -> EXCLUDED (FEATURE_CLOSE_AFTER_TEST_END);
    3. INCOMPLETE label -> EXCLUDED (INCOMPLETE_LABEL);
    4. TRAIN with actual label end crossing the train boundary -> PURGED;
    5. VALIDATION with actual label end crossing the validation boundary ->
       PURGED;
    6. otherwise ASSIGNED with ``final_split == nominal_split``.
    """
    feature_close = sample.feature_window_close
    close_date = feature_close.astimezone(ZoneInfo(boundary_timezone)).date()

    nominal = _nominal_split_for_date(close_date, spec)

    if nominal is None:
        return ChronologicalSplitAssignment(
            sample_key=sample.sample_key,
            sample_version_id=sample.sample_version_id,
            feature_window_close=feature_close,
            feature_window_close_date=close_date,
            label_status=sample.label_status,
            actual_label_end_time=sample.actual_label_end_time,
            nominal_split=None,
            final_split=None,
            assignment_status=SPLIT_STATUS_EXCLUDED,
            reason_code=REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
            purge_boundary=None,
        )

    if sample.label_status == LABEL_STATUS_INCOMPLETE:
        return ChronologicalSplitAssignment(
            sample_key=sample.sample_key,
            sample_version_id=sample.sample_version_id,
            feature_window_close=feature_close,
            feature_window_close_date=close_date,
            label_status=sample.label_status,
            actual_label_end_time=sample.actual_label_end_time,
            nominal_split=nominal,
            final_split=None,
            assignment_status=SPLIT_STATUS_EXCLUDED,
            reason_code=REASON_CODE_INCOMPLETE_LABEL,
            purge_boundary=None,
        )

    actual_end = sample.actual_label_end_time
    if nominal == SPLIT_TRAIN and actual_end is not None and actual_end >= train_boundary:
        return ChronologicalSplitAssignment(
            sample_key=sample.sample_key,
            sample_version_id=sample.sample_version_id,
            feature_window_close=feature_close,
            feature_window_close_date=close_date,
            label_status=sample.label_status,
            actual_label_end_time=actual_end,
            nominal_split=SPLIT_TRAIN,
            final_split=None,
            assignment_status=SPLIT_STATUS_PURGED,
            reason_code=REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
            purge_boundary=train_boundary,
        )
    if (
        nominal == SPLIT_VALIDATION
        and actual_end is not None
        and actual_end >= validation_boundary
    ):
        return ChronologicalSplitAssignment(
            sample_key=sample.sample_key,
            sample_version_id=sample.sample_version_id,
            feature_window_close=feature_close,
            feature_window_close_date=close_date,
            label_status=sample.label_status,
            actual_label_end_time=actual_end,
            nominal_split=SPLIT_VALIDATION,
            final_split=None,
            assignment_status=SPLIT_STATUS_PURGED,
            reason_code=REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
            purge_boundary=validation_boundary,
        )

    return ChronologicalSplitAssignment(
        sample_key=sample.sample_key,
        sample_version_id=sample.sample_version_id,
        feature_window_close=feature_close,
        feature_window_close_date=close_date,
        label_status=sample.label_status,
        actual_label_end_time=actual_end,
        nominal_split=nominal,
        final_split=nominal,
        assignment_status=SPLIT_STATUS_ASSIGNED,
        reason_code=None,
        purge_boundary=None,
    )


def assign_chronological_splits(
    samples, spec: ChronologicalSplitSpec
) -> ChronologicalSplitResult:
    """Deterministically assign chronological splits and apply
    actual-label-end purging.

    Input sample order is never semantic: samples are validated and sorted by
    ``sample_key``. Duplicate sample keys fail closed even when their
    ``sample_version_id`` or content differs; there is no silent
    deduplication. No randomization, shuffling, hashing-based grouping, or
    UTC-date grouping is ever applied.

    Raises :class:`SplitValidationError` on invalid inputs, duplicate sample
    keys, or any inconsistent identity.
    """
    if not isinstance(spec, ChronologicalSplitSpec):
        raise SplitValidationError(
            f"samples must be assigned under a ChronologicalSplitSpec, "
            f"got {type(spec).__name__}"
        )
    try:
        sample_items = tuple(samples)
    except (TypeError, ValueError) as exc:
        raise SplitValidationError(
            "samples must be an iterable of ChronologicalSplitSample"
        ) from exc
    for item in sample_items:
        if not isinstance(item, ChronologicalSplitSample):
            raise SplitValidationError(
                f"samples must contain ChronologicalSplitSample instances, "
                f"got {type(item).__name__}"
            )
    keys = [sample.sample_key for sample in sample_items]
    if len(set(keys)) != len(keys):
        raise SplitValidationError(
            "duplicate sample_key in samples: the same logical sample may not "
            "appear twice in one split result"
        )
    samples_sorted = tuple(
        sorted(sample_items, key=lambda sample: sample.sample_key)
    )

    train_boundary = _next_local_midnight_utc(
        spec.train_end_date, spec.boundary_timezone
    )
    validation_boundary = _next_local_midnight_utc(
        spec.validation_end_date, spec.boundary_timezone
    )

    assignments = [
        _assign_sample(
            sample,
            spec,
            spec.boundary_timezone,
            train_boundary,
            validation_boundary,
        )
        for sample in samples_sorted
    ]

    schema = split_assignment_schema()
    rows = _assignment_rows(tuple(assignments))
    diagnostics = _derive_diagnostics(tuple(assignments))
    pin = chronological_split_spec_pin(spec)
    schema_id = split_assignment_schema_id()
    content_id = split_assignment_content_id(rows)
    result_id = chronological_split_result_id(
        splitter_version=CHRONOLOGICAL_SPLITTER_VERSION,
        split_spec_content_id=pin.content_sha256,
        assignment_schema_version=SPLIT_ASSIGNMENT_SCHEMA_VERSION,
        assignment_schema_id=schema_id,
        assignment_content_id=content_id,
        sample_count=len(assignments),
    )
    return ChronologicalSplitResult(
        split_spec=spec,
        split_spec_pin=pin,
        splitter_version=CHRONOLOGICAL_SPLITTER_VERSION,
        assignments=tuple(assignments),
        assignment_schema=schema,
        assignment_rows=rows,
        assignment_schema_id=schema_id,
        assignment_content_id=content_id,
        split_result_id=result_id,
        diagnostics=diagnostics,
    )
