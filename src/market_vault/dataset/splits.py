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

from .split_models import (
    CHRONOLOGICAL_SPLITTER_VERSION,
    SPLIT_ASSIGNMENT_SCHEMA_VERSION,
    SPLIT_ASSIGNMENT_COLUMNS,
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
    _expected_split_assignment,
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

    # The single shared classification rule (also used by
    # ChronologicalSplitResult.__post_init__ for semantic re-derivation) so
    # construction and validation can never drift.
    assignments = [
        _expected_split_assignment(
            sample_key=sample.sample_key,
            sample_version_id=sample.sample_version_id,
            feature_window_close=sample.feature_window_close,
            label_status=sample.label_status,
            actual_label_end_time=sample.actual_label_end_time,
            spec=spec,
            train_boundary=train_boundary,
            validation_boundary=validation_boundary,
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
