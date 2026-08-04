"""Offline deterministic tests for the chronological split and
actual-label-end purge foundation (v0.4.0 PR-8).

Covers the frozen split models and version constants, the sample fact model,
nominal feature-window-close local-date assignment, INCOMPLETE-label
exclusion, TRAIN/VALIDATION actual-label-end purging, DST-safe
next-local-midnight exclusive boundaries, the deterministic
schema/content/result identities, the SpecPin(kind=SPLIT) / dataset_id
integration, and the fail-closed tampering envelope. No network, no OpenD,
no stored market data, no current time, no locale, no filesystem mtimes, no
file writes, and no dict insertion order is ever depended on.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import market_vault.dataset as dataset_pkg
from market_vault.dataset import (
    CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION,
    CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION,
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    CHRONOLOGICAL_SPLITTER_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
    REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
    REASON_CODE_INCOMPLETE_LABEL,
    SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    SPLIT_ASSIGNMENT_SCHEMA_VERSION,
    SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
    SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
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
    CompletionSummary,
    DatasetError,
    DatasetField,
    DatasetIdentityInput,
    DatasetSchema,
    DatasetScope,
    SpecPin,
    SplitValidationError,
    assign_chronological_splits,
    chronological_split_result_id,
    chronological_split_spec_content_id,
    chronological_split_spec_pin,
    dataset_id,
    dataset_schema_id,
    logical_dataset_content_id,
    split_assignment_content_id,
    split_assignment_schema,
    split_assignment_schema_id,
)

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ny(year, month, day, hour=16, minute=0, second=0, microsecond=0):
    """Timezone-aware instant in America/New_York (the fixture timezone)."""
    return datetime(
        year, month, day, hour, minute, second, microsecond, tzinfo=NY
    )


def make_spec(**overrides) -> ChronologicalSplitSpec:
    """Default fixture spec: America/New_York, 2024-06-28 / 2024-07-31 /
    2024-08-30 boundaries.

    With this spec:
    - train_boundary_exclusive = 2024-06-29 00:00 EDT = 2024-06-29 04:00 UTC
    - validation_boundary_exclusive = 2024-08-01 00:00 EDT =
      2024-08-01 04:00 UTC
    """
    values = dict(
        spec_schema_version=CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
        name="chrono_split",
        version="v1",
        boundary_timezone="America/New_York",
        train_end_date=date(2024, 6, 28),
        validation_end_date=date(2024, 7, 31),
        test_end_date=date(2024, 8, 30),
        assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        purge_rule=SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
        incomplete_label_policy=SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
        out_of_range_policy=SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    )
    values.update(overrides)
    return ChronologicalSplitSpec(**values)


def make_sample(
    key_text: str,
    *,
    version_text: str | None = None,
    close=None,
    status: str = LABEL_STATUS_COMPLETE,
    actual_end=None,
) -> ChronologicalSplitSample:
    """One split sample with derived 64-char lowercase SHA identities.

    COMPLETE samples default their actual label end to one hour after the
    feature window close (a legal value that stays inside the split date).
    """
    close = close if close is not None else ny(2024, 6, 28, 16, 0)
    if actual_end is None and status == LABEL_STATUS_COMPLETE:
        # Only fill the default when the close is a real instant; invalid
        # close values must reach the model untouched and fail closed.
        actual_end = close + timedelta(hours=1) if isinstance(close, datetime) else None
    return ChronologicalSplitSample(
        sample_key=sha(key_text),
        sample_version_id=sha(version_text if version_text is not None else key_text + "#v1"),
        feature_window_close=close,
        label_status=status,
        actual_label_end_time=actual_end,
    )


def make_identity_input(split_pin: SpecPin | None) -> DatasetIdentityInput:
    """Minimal valid DatasetIdentityInput carrying one split pin."""
    schema = DatasetSchema((DatasetField("x", "int64", False),))
    scope = DatasetScope(
        symbols=("SPY",),
        trade_dates=(date(2024, 1, 2),),
        adjustment="NONE",
        interval="1m",
        requested_session="ALL",
    )
    return DatasetIdentityInput(
        dataset_kind="market-samples-dataset",
        scope=scope,
        dataset_as_of=None,
        schema=schema,
        dataset_schema_id=dataset_schema_id(schema),
        logical_dataset_content_id=logical_dataset_content_id(schema, []),
        canonical_builds=(),
        canonical_row_version_ids=(),
        feature_specs=(),
        label_specs=(),
        split_spec=split_pin,
        implementations=(),
        completion=CompletionSummary(0, 0, 0, ()),
        gap_references=(),
    )


def assignment_of(result, key_text: str) -> ChronologicalSplitAssignment:
    return next(
        assignment
        for assignment in result.assignments
        if assignment.sample_key == sha(key_text)
    )


# ---------------------------------------------------------------------------
# A. Models and versions.
# ---------------------------------------------------------------------------


def test_split_validation_error_is_dataset_error():
    assert issubclass(SplitValidationError, DatasetError)


@pytest.mark.parametrize(
    "model",
    [
        ChronologicalSplitSpec,
        ChronologicalSplitSample,
        ChronologicalSplitAssignment,
        ChronologicalSplitDiagnostics,
        ChronologicalSplitResult,
    ],
)
def test_all_split_models_are_frozen(model):
    with pytest.raises(FrozenInstanceError):
        instance = None
        if model is ChronologicalSplitSpec:
            instance = make_spec()
        elif model is ChronologicalSplitSample:
            instance = make_sample("s")
        elif model is ChronologicalSplitAssignment:
            result = assign_chronological_splits(
                [make_sample("s")], make_spec()
            )
            instance = result.assignments[0]
        elif model is ChronologicalSplitDiagnostics:
            instance = ChronologicalSplitDiagnostics(
                sample_count=1, assigned_count=1, train_assigned_count=1,
                validation_assigned_count=0, test_assigned_count=0,
                purged_count=0, train_purged_count=0, validation_purged_count=0,
                excluded_count=0, incomplete_label_excluded_count=0,
                out_of_range_excluded_count=0,
            )
        else:
            instance = assign_chronological_splits([make_sample("s")], make_spec())
        setattr(instance, "anything", 1)


def test_spec_kind_is_fixed_split():
    assert make_spec().kind == "SPLIT"


def test_spec_kind_is_not_a_constructor_parameter():
    with pytest.raises(TypeError):
        ChronologicalSplitSpec(
            spec_schema_version=CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
            name="x",
            version="v1",
            boundary_timezone="America/New_York",
            train_end_date=date(2024, 1, 1),
            validation_end_date=date(2024, 1, 2),
            test_end_date=date(2024, 1, 3),
            assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
            purge_rule=SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
            incomplete_label_policy=SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
            out_of_range_policy=SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
            kind="SPLIT",
        )


def test_dataclasses_replace_cannot_forge_spec_kind():
    spec = make_spec()
    with pytest.raises((TypeError, ValueError)):
        replace(spec, kind="TRAIN")


def test_current_schema_version_is_accepted():
    spec = make_spec()
    assert spec.spec_schema_version == CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION


@pytest.mark.parametrize(
    "schema_version",
    [
        "market-vault-chronological-split-spec-v0",
        "market-vault-chronological-split-spec-v2",
        "market-vault-chronological-split-spec-v1-future",
        "unknown-schema",
        "",
    ],
)
def test_old_future_and_unknown_schema_versions_are_rejected(schema_version):
    with pytest.raises(SplitValidationError):
        make_spec(spec_schema_version=schema_version)


@pytest.mark.parametrize(
    "name", ["", "ChronoSplit", "chrono-split", "1chrono", "chrono split", "chrono\x07"]
)
def test_invalid_spec_names_are_rejected(name):
    with pytest.raises(SplitValidationError):
        make_spec(name=name)


@pytest.mark.parametrize(
    "version", ["", "v0", "v01", "V1", "1", "v1.0", "v1\x1f"]
)
def test_invalid_spec_versions_are_rejected(version):
    with pytest.raises(SplitValidationError):
        make_spec(version=version)


def test_unsafe_control_and_separator_text_is_rejected():
    with pytest.raises(SplitValidationError):
        make_spec(boundary_timezone="America/New\x1fYork")
    with pytest.raises(SplitValidationError):
        make_spec(boundary_timezone="America/New\x00York")


def test_invalid_timezone_is_rejected():
    with pytest.raises(SplitValidationError):
        make_spec(boundary_timezone="America/New_York2")
    with pytest.raises(SplitValidationError):
        make_spec(boundary_timezone="Etc/Unknown")
    with pytest.raises(SplitValidationError):
        make_spec(boundary_timezone="CST")


def test_timezone_has_no_system_local_fallback():
    # A name that can never resolve must fail; the machine's local timezone
    # is never consulted as a fallback.
    with pytest.raises(SplitValidationError):
        make_spec(boundary_timezone="")


def test_strict_boundary_ordering_is_enforced():
    # train < validation < test is required; equal and reversed dates fail.
    with pytest.raises(SplitValidationError):
        make_spec(
            train_end_date=date(2024, 6, 28),
            validation_end_date=date(2024, 6, 28),
            test_end_date=date(2024, 6, 30),
        )
    with pytest.raises(SplitValidationError):
        make_spec(
            train_end_date=date(2024, 6, 28),
            validation_end_date=date(2024, 7, 31),
            test_end_date=date(2024, 7, 31),
        )
    with pytest.raises(SplitValidationError):
        make_spec(
            train_end_date=date(2024, 8, 1),
            validation_end_date=date(2024, 7, 31),
            test_end_date=date(2024, 8, 30),
        )


def test_boundary_dates_accept_date_objects_and_strict_iso_strings():
    as_dates = make_spec(
        train_end_date=date(2024, 6, 28),
        validation_end_date=date(2024, 7, 31),
        test_end_date=date(2024, 8, 30),
    )
    as_strings = make_spec(
        train_end_date="2024-06-28",
        validation_end_date="2024-07-31",
        test_end_date="2024-08-30",
    )
    assert as_dates == as_strings
    assert chronological_split_spec_content_id(as_dates) == (
        chronological_split_spec_content_id(as_strings)
    )


def test_datetime_boundary_is_rejected_not_silently_truncated():
    # A datetime must never be silently converted to its date.
    with pytest.raises(SplitValidationError):
        make_spec(train_end_date=datetime(2024, 6, 28, 16, 0, tzinfo=UTC))
    with pytest.raises(SplitValidationError):
        make_spec(validation_end_date=datetime(2024, 7, 31, tzinfo=UTC))
    with pytest.raises(SplitValidationError):
        make_spec(train_end_date="2024-6-28")
    with pytest.raises(SplitValidationError):
        make_spec(train_end_date="20240628")
    with pytest.raises(SplitValidationError):
        make_spec(train_end_date=20240628)


def test_v1_fixed_rule_values_only():
    with pytest.raises(SplitValidationError):
        make_spec(assignment_rule="ROW_NUMBER")
    with pytest.raises(SplitValidationError):
        make_spec(purge_rule="NOMINAL_HORIZON")
    with pytest.raises(SplitValidationError):
        make_spec(incomplete_label_policy="INCLUDE")
    with pytest.raises(SplitValidationError):
        make_spec(out_of_range_policy="INCLUDE")


# ---------------------------------------------------------------------------
# B. Sample fact model.
# ---------------------------------------------------------------------------


def _raw_sample(sample_key, sample_version_id) -> ChronologicalSplitSample:
    return ChronologicalSplitSample(
        sample_key=sample_key,
        sample_version_id=sample_version_id,
        feature_window_close=ny(2024, 6, 28),
        label_status=LABEL_STATUS_COMPLETE,
        actual_label_end_time=ny(2024, 6, 28, 21),
    )


def test_sample_key_requires_strict_lowercase_sha256():
    assert make_sample("s").sample_key == sha("s")
    with pytest.raises(SplitValidationError):
        _raw_sample("x" * 64, sha("v"))
    with pytest.raises(SplitValidationError):
        _raw_sample(sha("s").upper(), sha("v"))


def test_sample_version_id_requires_strict_lowercase_sha256():
    with pytest.raises(SplitValidationError):
        _raw_sample(sha("s"), "v" * 64)
    with pytest.raises(SplitValidationError):
        _raw_sample(sha("s"), sha("v").upper())


def test_uppercase_sha_is_rejected_not_silently_lowered():
    with pytest.raises(SplitValidationError):
        _raw_sample(sha("s").upper(), sha("v"))
    with pytest.raises(SplitValidationError):
        _raw_sample(sha("s"), sha("v").upper())


def test_naive_feature_window_close_is_rejected():
    with pytest.raises(SplitValidationError):
        make_sample("s", close=datetime(2024, 6, 28, 16, 0))


def test_timezone_equivalent_feature_closes_normalize_identically():
    sample_ny = make_sample(
        "s", close=ny(2024, 6, 28, 16, 0), actual_end=ny(2024, 6, 28, 21, 0)
    )
    sample_utc = make_sample(
        "s",
        close=datetime(2024, 6, 28, 20, 0, tzinfo=UTC),
        actual_end=datetime(2024, 6, 29, 1, 0, tzinfo=UTC),
    )
    result_ny = assign_chronological_splits([sample_ny], make_spec())
    result_utc = assign_chronological_splits([sample_utc], make_spec())
    assert result_ny.assignment_rows == result_utc.assignment_rows
    assert result_ny.assignment_content_id == result_utc.assignment_content_id
    assert result_ny.split_result_id == result_utc.split_result_id


def test_microsecond_precision_is_normalized():
    # Sub-microsecond precision (nanoseconds) is truncated to microseconds;
    # Python's datetime constructor cannot even express it, so pandas
    # Timestamps are used for the fine variant.
    sample_fine = make_sample(
        "s",
        close=pd.Timestamp("2024-06-28T20:00:00.123456789Z"),
        actual_end=pd.Timestamp("2024-06-29T00:00:00.123456789Z"),
    )
    sample_truncated = make_sample(
        "s",
        close=datetime(2024, 6, 28, 20, 0, 0, 123456, tzinfo=UTC),
        actual_end=datetime(2024, 6, 29, 0, 0, 0, 123456, tzinfo=UTC),
    )
    result_fine = assign_chronological_splits([sample_fine], make_spec())
    result_truncated = assign_chronological_splits(
        [sample_truncated], make_spec()
    )
    assert result_fine.assignment_rows == result_truncated.assignment_rows
    assert result_fine.split_result_id == result_truncated.split_result_id


def test_complete_label_requires_actual_label_end_time():
    with pytest.raises(SplitValidationError):
        ChronologicalSplitSample(
            sample_key=sha("s"),
            sample_version_id=sha("s#v1"),
            feature_window_close=ny(2024, 6, 28),
            label_status=LABEL_STATUS_COMPLETE,
            actual_label_end_time=None,
        )


def test_incomplete_label_without_actual_end_is_accepted():
    sample = make_sample("s", status=LABEL_STATUS_INCOMPLETE, actual_end=None)
    assert sample.label_status == LABEL_STATUS_INCOMPLETE
    result = assign_chronological_splits([sample], make_spec())
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL


def test_incomplete_label_with_partial_actual_end_is_accepted():
    sample = make_sample(
        "s",
        status=LABEL_STATUS_INCOMPLETE,
        actual_end=ny(2024, 6, 29, 12, 0),
    )
    result = assign_chronological_splits([sample], make_spec())
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL
    assert assignment.actual_label_end_time == ny(2024, 6, 29, 12, 0)


def test_naive_actual_label_end_is_rejected():
    with pytest.raises(SplitValidationError):
        make_sample(
            "s", actual_end=datetime(2024, 6, 28, 21, 0)
        )


def test_actual_label_end_before_feature_close_is_rejected():
    with pytest.raises(SplitValidationError):
        make_sample(
            "s",
            close=ny(2024, 6, 28, 16, 0),
            actual_end=ny(2024, 6, 28, 15, 0),
        )
    # Ending exactly at the feature window close is legal (>= contract).
    sample = make_sample(
        "s", close=ny(2024, 6, 28, 16, 0), actual_end=ny(2024, 6, 28, 16, 0)
    )
    assert sample.actual_label_end_time == ny(2024, 6, 28, 16, 0)


def test_wrong_types_and_bools_are_rejected():
    with pytest.raises(SplitValidationError):
        _raw_sample(123, sha("v"))
    with pytest.raises(SplitValidationError):
        ChronologicalSplitSample(
            sample_key=sha("s"), sample_version_id=sha("v"),
            feature_window_close=ny(2024, 6, 28),
            label_status=True,
            actual_label_end_time=ny(2024, 6, 28, 21),
        )
    with pytest.raises(SplitValidationError):
        make_sample("s", close=123)
    with pytest.raises(SplitValidationError):
        make_sample("s", status="PARTIAL")
    with pytest.raises(SplitValidationError):
        make_sample("s", actual_end=456)


# ---------------------------------------------------------------------------
# C. Nominal split assignment.
# ---------------------------------------------------------------------------


def test_close_on_train_end_date_is_train():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28, 16, 0))], make_spec()
    )
    assignment = result.assignments[0]
    assert assignment.nominal_split == SPLIT_TRAIN
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TRAIN


def test_close_day_after_train_end_is_validation():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 29, 16, 0))], make_spec()
    )
    assignment = result.assignments[0]
    assert assignment.nominal_split == SPLIT_VALIDATION
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED


def test_close_on_validation_end_date_is_validation():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 7, 31, 16, 0))], make_spec()
    )
    assert result.assignments[0].nominal_split == SPLIT_VALIDATION
    assert result.assignments[0].final_split == SPLIT_VALIDATION


def test_close_day_after_validation_end_is_test():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 8, 1, 16, 0))], make_spec()
    )
    assert result.assignments[0].nominal_split == SPLIT_TEST


def test_close_on_test_end_date_is_test():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 8, 30, 16, 0))], make_spec()
    )
    assert result.assignments[0].nominal_split == SPLIT_TEST
    assert result.assignments[0].final_split == SPLIT_TEST


def test_close_day_after_test_end_is_excluded():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 8, 31, 16, 0))], make_spec()
    )
    assignment = result.assignments[0]
    assert assignment.nominal_split is None
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END


def test_feature_close_uses_declared_timezone_local_date():
    # 2024-06-29 02:30 UTC is 2024-06-28 22:30 EDT: local date 2024-06-28.
    result = assign_chronological_splits(
        [make_sample("s", close=datetime(2024, 6, 29, 2, 30, tzinfo=UTC))],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.feature_window_close_date == date(2024, 6, 28)
    assert assignment.nominal_split == SPLIT_TRAIN


def test_utc_date_and_market_local_date_diverge_at_boundaries():
    # UTC date says 2024-06-29 (validation boundary day) but local date is
    # 2024-06-28 (train end day): the declared timezone date wins.
    result = assign_chronological_splits(
        [make_sample("s", close=datetime(2024, 6, 29, 3, 0, tzinfo=UTC))],
        make_spec(),
    )
    assert result.assignments[0].feature_window_close_date == date(2024, 6, 28)
    assert result.assignments[0].nominal_split == SPLIT_TRAIN

    # 2024-06-29 04:00 UTC is 2024-06-29 00:00 EDT: local date 2024-06-29.
    result = assign_chronological_splits(
        [make_sample("s", close=datetime(2024, 6, 29, 4, 0, tzinfo=UTC))],
        make_spec(),
    )
    assert result.assignments[0].feature_window_close_date == date(2024, 6, 29)
    assert result.assignments[0].nominal_split == SPLIT_VALIDATION


def test_input_order_never_affects_assignments_content_or_result_id():
    samples = [
        make_sample("a", close=ny(2024, 6, 28)),
        make_sample("b", close=ny(2024, 7, 31)),
        make_sample("c", close=ny(2024, 8, 30)),
        make_sample("d", close=ny(2024, 8, 31)),
    ]
    forward = assign_chronological_splits(samples, make_spec())
    reversed_input = assign_chronological_splits(
        list(reversed(samples)), make_spec()
    )
    shuffled = assign_chronological_splits(
        [samples[2], samples[0], samples[3], samples[1]], make_spec()
    )
    assert forward.assignments == reversed_input.assignments
    assert forward.assignments == shuffled.assignments
    assert forward.assignment_content_id == reversed_input.assignment_content_id
    assert forward.split_result_id == reversed_input.split_result_id
    assert forward.split_result_id == shuffled.split_result_id


def test_duplicate_sample_key_is_rejected():
    duplicate = [
        make_sample("dup"),
        make_sample("dup", version_text="dup#v2"),
    ]
    with pytest.raises(SplitValidationError):
        assign_chronological_splits(duplicate, make_spec())


def test_same_sample_key_with_different_version_id_is_still_rejected():
    with pytest.raises(SplitValidationError):
        assign_chronological_splits(
            [
                make_sample("same", version_text="same#v1"),
                make_sample("same", version_text="same#v2"),
            ],
            make_spec(),
        )


# ---------------------------------------------------------------------------
# D. Actual-label-end purging.
# ---------------------------------------------------------------------------

TRAIN_BOUNDARY_UTC = datetime(2024, 6, 29, 4, 0, 0, tzinfo=UTC)
VALIDATION_BOUNDARY_UTC = datetime(2024, 8, 1, 4, 0, 0, tzinfo=UTC)


def test_train_actual_end_below_boundary_is_kept():
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 6, 28),
                actual_end=TRAIN_BOUNDARY_UTC - _us(1),
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TRAIN
    assert assignment.reason_code is None
    assert assignment.purge_boundary is None


def _us(count: int):
    from datetime import timedelta

    return timedelta(microseconds=count)


def test_train_actual_end_exactly_at_boundary_is_purged():
    result = assign_chronological_splits(
        [
            make_sample(
                "s", close=ny(2024, 6, 28), actual_end=TRAIN_BOUNDARY_UTC
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.final_split is None
    assert assignment.nominal_split == SPLIT_TRAIN
    assert assignment.reason_code == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY


def test_train_actual_end_above_boundary_is_purged():
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 6, 28),
                actual_end=datetime(2024, 6, 29, 12, 0, tzinfo=UTC),
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.reason_code == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY


def test_validation_actual_end_below_boundary_is_kept():
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 7, 31),
                actual_end=VALIDATION_BOUNDARY_UTC - _us(1),
            )
        ],
        make_spec(),
    )
    assert result.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED
    assert result.assignments[0].final_split == SPLIT_VALIDATION


def test_validation_actual_end_exactly_at_boundary_is_purged():
    result = assign_chronological_splits(
        [
            make_sample(
                "s", close=ny(2024, 7, 31), actual_end=VALIDATION_BOUNDARY_UTC
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.nominal_split == SPLIT_VALIDATION
    assert assignment.reason_code == (
        REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
    )


def test_validation_actual_end_above_boundary_is_purged():
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 7, 31),
                actual_end=datetime(2024, 8, 2, 0, 0, tzinfo=UTC),
            )
        ],
        make_spec(),
    )
    assert result.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert result.assignments[0].reason_code == (
        REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
    )


def test_test_split_has_no_fourth_split_purge():
    # A TEST sample whose actual label end runs far past the test end date is
    # still ASSIGNED: there is no fourth split to leak into, and label
    # integrity is controlled by the explicit label_status.
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 8, 30),
                actual_end=datetime(2024, 9, 30, 0, 0, tzinfo=UTC),
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TEST
    assert assignment.reason_code is None
    assert assignment.purge_boundary is None


def test_incomplete_train_label_is_excluded_not_purged():
    # Even with a partial actual end that crosses the train boundary, the
    # INCOMPLETE exclusion precedes any purge check.
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 6, 28),
                status=LABEL_STATUS_INCOMPLETE,
                actual_end=datetime(2024, 6, 30, 0, 0, tzinfo=UTC),
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL
    assert assignment.final_split is None
    assert assignment.purge_boundary is None


def test_incomplete_validation_label_is_excluded():
    result = assign_chronological_splits(
        [
            make_sample(
                "s", close=ny(2024, 7, 31), status=LABEL_STATUS_INCOMPLETE
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL


def test_out_of_range_reason_precedence_is_fixed():
    # A sample past the test end is EXCLUDED with FEATURE_CLOSE_AFTER_TEST_END
    # even when its label is INCOMPLETE: the out-of-range check comes first.
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 8, 31),
                status=LABEL_STATUS_INCOMPLETE,
                actual_end=None,
            )
        ],
        make_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END
    assert assignment.nominal_split is None


def test_purge_boundary_records_exact_utc_instant():
    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 6, 28),
                actual_end=datetime(2024, 6, 29, 5, 0, tzinfo=UTC),
            )
        ],
        make_spec(),
    )
    assert result.assignments[0].purge_boundary == TRAIN_BOUNDARY_UTC

    result = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 7, 31),
                actual_end=datetime(2024, 8, 2, 0, 0, tzinfo=UTC),
            )
        ],
        make_spec(),
    )
    assert result.assignments[0].purge_boundary == VALIDATION_BOUNDARY_UTC


def test_train_reason_code_is_exact():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 29, 1, 0))],
        make_spec(),
    )
    assert result.assignments[0].reason_code == (
        REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
    )


def test_validation_reason_code_is_exact():
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 7, 31), actual_end=ny(2024, 8, 1, 1, 0))],
        make_spec(),
    )
    assert result.assignments[0].reason_code == (
        REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
    )


def test_status_invariants_hold_across_a_mixed_batch():
    samples = [
        make_sample("train-kept", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 28, 21)),
        make_sample("train-purged", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 29, 1)),
        make_sample("val-kept", close=ny(2024, 7, 31), actual_end=ny(2024, 7, 31, 21)),
        make_sample("val-purged", close=ny(2024, 7, 31), actual_end=ny(2024, 8, 1, 1)),
        make_sample("test", close=ny(2024, 8, 30), actual_end=ny(2024, 8, 31, 1)),
        make_sample("incomplete", close=ny(2024, 6, 28), status=LABEL_STATUS_INCOMPLETE),
        make_sample("out-of-range", close=ny(2024, 8, 31)),
    ]
    result = assign_chronological_splits(samples, make_spec())
    for assignment in result.assignments:
        if assignment.assignment_status == SPLIT_STATUS_ASSIGNED:
            assert assignment.final_split == assignment.nominal_split
            assert assignment.reason_code is None
            assert assignment.purge_boundary is None
        elif assignment.assignment_status == SPLIT_STATUS_PURGED:
            assert assignment.nominal_split in (SPLIT_TRAIN, SPLIT_VALIDATION)
            assert assignment.final_split is None
            assert assignment.purge_boundary is not None
        else:
            assert assignment.final_split is None
            assert assignment.reason_code in (
                REASON_CODE_INCOMPLETE_LABEL,
                REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
            )


def test_one_microsecond_change_can_flip_purge_outcome():
    below = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28), actual_end=TRAIN_BOUNDARY_UTC - _us(1))],
        make_spec(),
    )
    exactly = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28), actual_end=TRAIN_BOUNDARY_UTC)],
        make_spec(),
    )
    assert below.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED
    assert exactly.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert below.split_result_id != exactly.split_result_id


def test_same_feature_close_with_different_actual_ends_differs():
    kept = make_sample(
        "kept", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 28, 21)
    )
    purged = make_sample(
        "purged", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 29, 1)
    )
    result = assign_chronological_splits([kept, purged], make_spec())
    by_key = {a.sample_key: a for a in result.assignments}
    assert by_key[sha("kept")].assignment_status == SPLIT_STATUS_ASSIGNED
    assert by_key[sha("purged")].assignment_status == SPLIT_STATUS_PURGED
    assert by_key[sha("kept")].feature_window_close_date == date(2024, 6, 28)
    assert by_key[sha("purged")].feature_window_close_date == date(2024, 6, 28)


def test_no_nominal_horizon_input_exists():
    sample_field_names = {f.name for f in fields(ChronologicalSplitSample)}
    assert "horizon" not in sample_field_names
    assert "label_window_close" not in sample_field_names
    assert "purge_length" not in sample_field_names
    spec_field_names = {f.name for f in fields(ChronologicalSplitSpec)}
    assert "horizon" not in spec_field_names
    assert "purge_minutes" not in spec_field_names
    assert "embargo" not in spec_field_names


def test_split_layer_never_reads_labelspec_horizon():
    import market_vault.dataset.splits as splits_module
    import market_vault.dataset.split_models as split_models_module

    for module in (splits_module, split_models_module):
        assert not hasattr(module, "LabelSpec")
        assert not hasattr(module, "LabelHorizon")
        assert not hasattr(module, "FeatureSpec")
        assert not hasattr(module, "SpecVersionRequirements")


# ---------------------------------------------------------------------------
# E. DST and date boundaries.
# ---------------------------------------------------------------------------


def test_spring_forward_next_local_midnight_is_correct():
    # America/New_York springs forward 2024-03-10 02:00 -> 03:00. The next
    # local midnight after 2024-03-09 is 2024-03-10 00:00 EST = 05:00 UTC,
    # not the +24h instant 2024-03-10 00:00 EDT = 04:00 UTC.
    spec = make_spec(
        train_end_date=date(2024, 3, 9),
        validation_end_date=date(2024, 3, 30),
        test_end_date=date(2024, 4, 30),
    )
    # 2024-03-10 04:30 UTC is 2024-03-09 23:30 EST: still before the next
    # local midnight, so the TRAIN sample is kept.
    kept = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 3, 8, 16),
                actual_end=datetime(2024, 3, 10, 4, 30, tzinfo=UTC),
            )
        ],
        spec,
    )
    assert kept.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED

    # Exactly at 2024-03-10 00:00 EST = 05:00 UTC: purged.
    purged = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 3, 8, 16),
                actual_end=datetime(2024, 3, 10, 5, 0, tzinfo=UTC),
            )
        ],
        spec,
    )
    assert purged.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert purged.assignments[0].purge_boundary == datetime(
        2024, 3, 10, 5, 0, tzinfo=UTC
    )


def test_fall_back_next_local_midnight_is_correct():
    # America/New_York falls back 2024-11-03 02:00 -> 01:00. The next local
    # midnight after 2024-11-02 is the first occurrence 2024-11-03 00:00 EDT
    # = 04:00 UTC, not the +24h instant 2024-11-03 00:00 EST = 05:00 UTC.
    spec = make_spec(
        train_end_date=date(2024, 11, 2),
        validation_end_date=date(2024, 11, 29),
        test_end_date=date(2024, 12, 31),
    )
    # 2024-11-03 04:30 UTC is 2024-11-03 00:30 EST: after the first-occurrence
    # local midnight, so the TRAIN sample is purged.
    purged = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 11, 1, 16),
                actual_end=datetime(2024, 11, 3, 4, 30, tzinfo=UTC),
            )
        ],
        spec,
    )
    assert purged.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert purged.assignments[0].purge_boundary == datetime(
        2024, 11, 3, 4, 0, tzinfo=UTC
    )

    # One microsecond before: 2024-11-02 23:59:59.999999 EDT, kept.
    kept = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 11, 1, 16),
                actual_end=datetime(2024, 11, 3, 3, 59, 59, 999999, tzinfo=UTC),
            )
        ],
        spec,
    )
    assert kept.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED


def test_boundaries_are_never_constructed_with_fixed_24h_deltas():
    # The spring-forward and fall-back cases above are exactly the
    # distinguishing tests: a fixed timedelta(hours=24) construction would
    # place the spring boundary at 04:00 UTC (04:30 kept would instead be
    # purged) and the fall-back boundary at 05:00 UTC (04:30 purged would
    # instead be kept). Both behaviors prove local-calendar midnight.
    spring_spec = make_spec(
        train_end_date=date(2024, 3, 9),
        validation_end_date=date(2024, 3, 30),
        test_end_date=date(2024, 4, 30),
    )
    spring = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 3, 8, 16),
                actual_end=datetime(2024, 3, 10, 4, 30, tzinfo=UTC),
            )
        ],
        spring_spec,
    )
    assert spring.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED

    fall_spec = make_spec(
        train_end_date=date(2024, 11, 2),
        validation_end_date=date(2024, 11, 29),
        test_end_date=date(2024, 12, 31),
    )
    fall = assign_chronological_splits(
        [
            make_sample(
                "s",
                close=ny(2024, 11, 1, 16),
                actual_end=datetime(2024, 11, 3, 4, 30, tzinfo=UTC),
            )
        ],
        fall_spec,
    )
    assert fall.assignments[0].assignment_status == SPLIT_STATUS_PURGED


def test_equivalent_timezone_representations_give_identical_results():
    sample_ny = make_sample(
        "s",
        close=ny(2024, 6, 28, 16, 0),
        actual_end=ny(2024, 6, 29, 0, 0),
    )
    sample_utc = make_sample(
        "s",
        close=datetime(2024, 6, 28, 20, 0, tzinfo=UTC),
        actual_end=datetime(2024, 6, 29, 4, 0, tzinfo=UTC),
    )
    result_ny = assign_chronological_splits([sample_ny], make_spec())
    result_utc = assign_chronological_splits([sample_utc], make_spec())
    assert result_ny.assignments == result_utc.assignments
    assert result_ny.assignment_content_id == result_utc.assignment_content_id
    assert result_ny.split_result_id == result_utc.split_result_id


# ---------------------------------------------------------------------------
# F. Identity / SpecPin / dataset_id.
# ---------------------------------------------------------------------------


def test_spec_content_id_is_lowercase_sha256():
    content_id = chronological_split_spec_content_id(make_spec())
    assert _SHA_HEX.fullmatch(content_id)
    assert content_id == content_id.lower()


def test_same_semantics_produce_the_same_content_id():
    first = make_spec()
    second = make_spec(
        train_end_date="2024-06-28",
        validation_end_date="2024-07-31",
        test_end_date="2024-08-30",
    )
    assert chronological_split_spec_content_id(first) == (
        chronological_split_spec_content_id(second)
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "other_split"},
        {"version": "v2"},
        {"boundary_timezone": "America/Chicago"},
        {"train_end_date": date(2024, 6, 27)},
        {"validation_end_date": date(2024, 8, 1)},
        {"test_end_date": date(2024, 8, 31)},
    ],
)
def test_every_semantic_field_change_changes_the_content_id(overrides):
    base = chronological_split_spec_content_id(make_spec())
    variant = chronological_split_spec_content_id(make_spec(**overrides))
    assert variant != base


def test_spec_pin_kind_is_split():
    pin = chronological_split_spec_pin(make_spec())
    assert pin.kind == "SPLIT"
    assert isinstance(pin, SpecPin)


def test_spec_pin_fields_are_exact():
    spec = make_spec()
    pin = chronological_split_spec_pin(spec)
    assert pin.kind == "SPLIT"
    assert pin.name == spec.name
    assert pin.version == spec.version
    assert pin.content_sha256 == chronological_split_spec_content_id(spec)
    assert _SHA_HEX.fullmatch(pin.content_sha256)


def test_same_split_semantics_give_same_dataset_id():
    first = make_identity_input(chronological_split_spec_pin(make_spec()))
    second = make_identity_input(
        chronological_split_spec_pin(
            make_spec(
                train_end_date="2024-06-28",
                validation_end_date="2024-07-31",
                test_end_date="2024-08-30",
            )
        )
    )
    assert dataset_id(first) == dataset_id(second)


def test_boundary_change_changes_dataset_id():
    base = dataset_id(make_identity_input(chronological_split_spec_pin(make_spec())))
    moved = dataset_id(
        make_identity_input(
            chronological_split_spec_pin(
                make_spec(validation_end_date=date(2024, 8, 1))
            )
        )
    )
    assert moved != base


def test_timezone_change_changes_dataset_id():
    base = dataset_id(make_identity_input(chronological_split_spec_pin(make_spec())))
    moved = dataset_id(
        make_identity_input(
            chronological_split_spec_pin(
                make_spec(boundary_timezone="America/Chicago")
            )
        )
    )
    assert moved != base


def test_rule_changes_fail_closed_at_v1():
    with pytest.raises(SplitValidationError):
        make_spec(purge_rule="NOMINAL_HORIZON")
    with pytest.raises(SplitValidationError):
        make_spec(assignment_rule="ROW_INDEX")


def test_split_pin_cannot_sit_in_feature_or_label_containers():
    pin = chronological_split_spec_pin(make_spec())
    schema = DatasetSchema((DatasetField("x", "int64", False),))
    scope = DatasetScope(
        symbols=("SPY",),
        trade_dates=(date(2024, 1, 2),),
        adjustment="NONE",
        interval="1m",
        requested_session="ALL",
    )
    with pytest.raises(DatasetError):
        DatasetIdentityInput(
            dataset_kind="k", scope=scope, dataset_as_of=None, schema=schema,
            dataset_schema_id=dataset_schema_id(schema),
            logical_dataset_content_id=logical_dataset_content_id(schema, []),
            canonical_builds=(), canonical_row_version_ids=(),
            feature_specs=(pin,), label_specs=(),
            split_spec=None, implementations=(),
            completion=CompletionSummary(0, 0, 0, ()), gap_references=(),
        )
    with pytest.raises(DatasetError):
        DatasetIdentityInput(
            dataset_kind="k", scope=scope, dataset_as_of=None, schema=schema,
            dataset_schema_id=dataset_schema_id(schema),
            logical_dataset_content_id=logical_dataset_content_id(schema, []),
            canonical_builds=(), canonical_row_version_ids=(),
            feature_specs=(), label_specs=(),
            split_spec=SpecPin(
                kind="FEATURE", name="f", version="v1", content_sha256=sha("x")
            ),
            implementations=(),
            completion=CompletionSummary(0, 0, 0, ()), gap_references=(),
        )


# ---------------------------------------------------------------------------
# G. Assignment content and result identities.
# ---------------------------------------------------------------------------


def test_assignment_schema_field_order_is_exact():
    schema = split_assignment_schema()
    assert [field.name for field in schema.fields] == [
        "sample_key",
        "sample_version_id",
        "feature_window_close",
        "feature_window_close_date",
        "label_status",
        "actual_label_end_time",
        "nominal_split",
        "final_split",
        "assignment_status",
        "reason_code",
        "purge_boundary",
    ]
    assert [(f.logical_type, f.nullable) for f in schema.fields] == [
        ("string", False),
        ("string", False),
        ("timestamp_us_utc", False),
        ("date32", False),
        ("string", False),
        ("timestamp_us_utc", True),
        ("string", True),
        ("string", True),
        ("string", False),
        ("string", True),
        ("timestamp_us_utc", True),
    ]


def test_assignment_schema_id_is_stable():
    assert split_assignment_schema_id() == dataset_schema_id(
        split_assignment_schema()
    )
    assert split_assignment_schema_id() == split_assignment_schema_id()


def test_row_order_does_not_affect_content_id():
    samples = [
        make_sample("a", close=ny(2024, 6, 28)),
        make_sample("b", close=ny(2024, 7, 31)),
        make_sample("c", close=ny(2024, 8, 30)),
    ]
    result = assign_chronological_splits(samples, make_spec())
    reversed_rows = list(reversed(result.assignment_rows))
    assert split_assignment_content_id(reversed_rows) == (
        result.assignment_content_id
    )


def test_duplicate_logical_row_affects_content_id():
    result = assign_chronological_splits(
        [make_sample("a", close=ny(2024, 6, 28))], make_spec()
    )
    duplicated = result.assignment_rows + (result.assignment_rows[0],)
    assert split_assignment_content_id(duplicated) != result.assignment_content_id


def test_assign_api_rejects_duplicate_samples():
    with pytest.raises(SplitValidationError):
        assign_chronological_splits(
            [make_sample("dup"), make_sample("dup", version_text="dup#v2")],
            make_spec(),
        )


def test_sample_version_change_changes_content_and_result_ids():
    base = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28))], make_spec()
    )
    changed = assign_chronological_splits(
        [make_sample("s", version_text="s#v2", close=ny(2024, 6, 28))],
        make_spec(),
    )
    assert changed.assignment_content_id != base.assignment_content_id
    assert changed.split_result_id != base.split_result_id


def test_assignment_change_changes_content_and_result_ids():
    kept = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 28, 21))],
        make_spec(),
    )
    purged = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 29, 1))],
        make_spec(),
    )
    assert purged.assignment_content_id != kept.assignment_content_id
    assert purged.split_result_id != kept.split_result_id


def test_zero_samples_have_deterministic_content_and_result_ids():
    first = assign_chronological_splits([], make_spec())
    second = assign_chronological_splits([], make_spec())
    assert first.assignments == ()
    assert first.assignment_rows == ()
    assert first.assignment_content_id == second.assignment_content_id
    assert first.split_result_id == second.split_result_id
    assert first.diagnostics.sample_count == 0


def test_diagnostics_counts_are_exact_for_a_mixed_batch():
    samples = [
        make_sample("train-kept", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 28, 21)),
        make_sample("train-purged", close=ny(2024, 6, 28), actual_end=ny(2024, 6, 29, 1)),
        make_sample("val-kept", close=ny(2024, 7, 31), actual_end=ny(2024, 7, 31, 21)),
        make_sample("val-purged", close=ny(2024, 7, 31), actual_end=ny(2024, 8, 1, 1)),
        make_sample("test", close=ny(2024, 8, 30), actual_end=ny(2024, 8, 31, 1)),
        make_sample("incomplete", close=ny(2024, 6, 28), status=LABEL_STATUS_INCOMPLETE),
        make_sample("out-of-range", close=ny(2024, 8, 31)),
    ]
    result = assign_chronological_splits(samples, make_spec())
    diagnostics = result.diagnostics
    assert diagnostics.sample_count == 7
    assert diagnostics.assigned_count == 3
    assert diagnostics.train_assigned_count == 1
    assert diagnostics.validation_assigned_count == 1
    assert diagnostics.test_assigned_count == 1
    assert diagnostics.purged_count == 2
    assert diagnostics.train_purged_count == 1
    assert diagnostics.validation_purged_count == 1
    assert diagnostics.excluded_count == 2
    assert diagnostics.incomplete_label_excluded_count == 1
    assert diagnostics.out_of_range_excluded_count == 1


def test_diagnostics_invariants_are_strict():
    # sample_count != assigned + purged + excluded.
    with pytest.raises(SplitValidationError):
        ChronologicalSplitDiagnostics(
            sample_count=3, assigned_count=1, train_assigned_count=1,
            validation_assigned_count=0, test_assigned_count=0,
            purged_count=0, train_purged_count=0, validation_purged_count=0,
            excluded_count=0, incomplete_label_excluded_count=0,
            out_of_range_excluded_count=0,
        )
    # assigned_count != train + validation + test assigned.
    with pytest.raises(SplitValidationError):
        ChronologicalSplitDiagnostics(
            sample_count=2, assigned_count=2, train_assigned_count=0,
            validation_assigned_count=0, test_assigned_count=1,
            purged_count=0, train_purged_count=0, validation_purged_count=0,
            excluded_count=0, incomplete_label_excluded_count=0,
            out_of_range_excluded_count=0,
        )
    # purged_count != train_purged + validation_purged.
    with pytest.raises(SplitValidationError):
        ChronologicalSplitDiagnostics(
            sample_count=2, assigned_count=0, train_assigned_count=0,
            validation_assigned_count=0, test_assigned_count=0,
            purged_count=1, train_purged_count=0, validation_purged_count=0,
            excluded_count=2, incomplete_label_excluded_count=1,
            out_of_range_excluded_count=1,
        )
    # excluded_count != incomplete + out of range excluded.
    with pytest.raises(SplitValidationError):
        ChronologicalSplitDiagnostics(
            sample_count=1, assigned_count=0, train_assigned_count=0,
            validation_assigned_count=0, test_assigned_count=0,
            purged_count=0, train_purged_count=0, validation_purged_count=0,
            excluded_count=1, incomplete_label_excluded_count=0,
            out_of_range_excluded_count=0,
        )


def test_diagnostics_bools_are_never_counts():
    with pytest.raises(SplitValidationError):
        ChronologicalSplitDiagnostics(
            sample_count=True, assigned_count=0, train_assigned_count=0,
            validation_assigned_count=0, test_assigned_count=0,
            purged_count=0, train_purged_count=0, validation_purged_count=0,
            excluded_count=0, incomplete_label_excluded_count=0,
            out_of_range_excluded_count=0,
        )


def test_tampered_assignment_schema_id_fails_closed():
    result = assign_chronological_splits([make_sample("s")], make_spec())
    with pytest.raises(SplitValidationError):
        replace(result, assignment_schema_id=sha("forged"))


def test_tampered_assignment_content_id_fails_closed():
    result = assign_chronological_splits([make_sample("s")], make_spec())
    with pytest.raises(SplitValidationError):
        replace(result, assignment_content_id=sha("forged"))


def test_tampered_split_result_id_fails_closed():
    result = assign_chronological_splits([make_sample("s")], make_spec())
    with pytest.raises(SplitValidationError):
        replace(result, split_result_id=sha("forged"))


def test_tampered_diagnostics_fail_closed():
    result = assign_chronological_splits([make_sample("s")], make_spec())
    forged = ChronologicalSplitDiagnostics(
        sample_count=0, assigned_count=0, train_assigned_count=0,
        validation_assigned_count=0, test_assigned_count=0,
        purged_count=0, train_purged_count=0, validation_purged_count=0,
        excluded_count=0, incomplete_label_excluded_count=0,
        out_of_range_excluded_count=0,
    )
    with pytest.raises(SplitValidationError):
        replace(result, diagnostics=forged)


def test_tampered_assignment_status_combinations_fail_closed():
    result = assign_chronological_splits([make_sample("s")], make_spec())
    assignment = result.assignments[0]
    # An ASSIGNED row cannot carry a reason code.
    with pytest.raises(SplitValidationError):
        replace(
            assignment,
            assignment_status=SPLIT_STATUS_ASSIGNED,
            reason_code=REASON_CODE_INCOMPLETE_LABEL,
        )
    # A PURGED row must have its matching crossing reason and a boundary.
    with pytest.raises(SplitValidationError):
        replace(
            assignment,
            assignment_status=SPLIT_STATUS_PURGED,
            reason_code=REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
        )
    with pytest.raises(SplitValidationError):
        replace(
            assignment,
            assignment_status=SPLIT_STATUS_PURGED,
            reason_code=REASON_CODE_INCOMPLETE_LABEL,
            purge_boundary=TRAIN_BOUNDARY_UTC,
        )
    # An EXCLUDED row must carry a stable exclusion reason.
    with pytest.raises(SplitValidationError):
        replace(
            assignment,
            assignment_status=SPLIT_STATUS_EXCLUDED,
            reason_code=REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
        )
    with pytest.raises(SplitValidationError):
        replace(assignment, assignment_status=SPLIT_STATUS_EXCLUDED, reason_code=None)
    # An EXCLUDED/INCOMPLETE_LABEL row must have final_split None; the ASSIGNED
    # row keeps final_split == TRAIN, so the forged combination fails closed.
    with pytest.raises(SplitValidationError):
        replace(
            assignment,
            assignment_status=SPLIT_STATUS_EXCLUDED,
            reason_code=REASON_CODE_INCOMPLETE_LABEL,
            label_status=LABEL_STATUS_INCOMPLETE,
        )
    # Swapping the assignments tuple for a duplicate-key one fails closed at
    # the result level.
    with pytest.raises(SplitValidationError):
        replace(result, assignments=(assignment, assignment))


def test_result_ids_are_sensitive_to_contract_versions():
    spec = make_spec()
    result = assign_chronological_splits([make_sample("s")], spec)
    content_id = chronological_split_spec_content_id(spec)
    variant = chronological_split_result_id(
        splitter_version="market-vault-chronological-splitter-v2",
        split_spec_content_id=content_id,
        assignment_schema_version=SPLIT_ASSIGNMENT_SCHEMA_VERSION,
        assignment_schema_id=result.assignment_schema_id,
        assignment_content_id=result.assignment_content_id,
        sample_count=len(result.assignments),
    )
    assert variant != result.split_result_id
    variant_schema = chronological_split_result_id(
        splitter_version=CHRONOLOGICAL_SPLITTER_VERSION,
        split_spec_content_id=content_id,
        assignment_schema_version="market-vault-split-assignment-schema-v2",
        assignment_schema_id=result.assignment_schema_id,
        assignment_content_id=result.assignment_content_id,
        sample_count=len(result.assignments),
    )
    assert variant_schema != result.split_result_id


# ---------------------------------------------------------------------------
# H. Public boundaries.
# ---------------------------------------------------------------------------


def test_package_public_exports_include_the_split_api():
    for name in (
        "CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION",
        "CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION",
        "CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION",
        "CHRONOLOGICAL_SPLITTER_VERSION",
        "SPLIT_ASSIGNMENT_SCHEMA_VERSION",
        "SPLIT_TRAIN",
        "SPLIT_VALIDATION",
        "SPLIT_TEST",
        "LABEL_STATUS_COMPLETE",
        "LABEL_STATUS_INCOMPLETE",
        "SPLIT_STATUS_ASSIGNED",
        "SPLIT_STATUS_PURGED",
        "SPLIT_STATUS_EXCLUDED",
        "SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE",
        "SPLIT_PURGE_RULE_ACTUAL_LABEL_END",
        "SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE",
        "SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE",
        "REASON_CODE_INCOMPLETE_LABEL",
        "REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END",
        "REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY",
        "REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY",
        "ChronologicalSplitSpec",
        "ChronologicalSplitSample",
        "ChronologicalSplitAssignment",
        "ChronologicalSplitDiagnostics",
        "ChronologicalSplitResult",
        "SplitValidationError",
        "chronological_split_spec_content_id",
        "chronological_split_spec_pin",
        "assign_chronological_splits",
        "split_assignment_schema",
        "split_assignment_schema_id",
        "split_assignment_content_id",
        "chronological_split_result_id",
        "SPLIT_ASSIGNMENT_COLUMNS",
    ):
        assert name in dataset_pkg.__all__
        assert hasattr(dataset_pkg, name)


def test_public_exports_leak_no_private_helpers():
    assert all(not name.startswith("_") for name in dataset_pkg.__all__)
    import market_vault.dataset.splits as splits_module

    assert all(not name.startswith("_") for name in splits_module.__all__)
    for private in (
        "_assignment_rows",
        "_derive_diagnostics",
        "_next_local_midnight_utc",
        "_assign_sample",
        "_nominal_split_for_date",
    ):
        assert not hasattr(dataset_pkg, private)
        assert private not in dataset_pkg.__all__


def test_split_layer_imports_or_executes_no_feature_or_label_transform():
    import market_vault.dataset.splits as splits_module

    # Assignment works on plain explicit facts; no spec object is ever needed.
    result = assign_chronological_splits(
        [make_sample("s", close=ny(2024, 6, 28))], make_spec()
    )
    assert result.assignments[0].final_split == SPLIT_TRAIN
    # The split modules do not import the Feature/Label spec machinery.
    for name in ("FeatureSpec", "LabelSpec", "LabelHorizon", "specs"):
        assert not hasattr(splits_module, name)


def test_split_layer_never_touches_network_or_opend():
    import market_vault.dataset.splits as splits_module
    import market_vault.dataset.split_models as split_models_module

    for module in (splits_module, split_models_module):
        for name in ("requests", "urllib", "socket", "opend", "moomoo_sdk"):
            assert not hasattr(module, name)
    import sys

    assert not any(
        "opend" in name.lower() for name in sys.modules
    )


def test_split_layer_writes_no_files(tmp_path):
    import os

    previous_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assign_chronological_splits(
            [make_sample("s", close=ny(2024, 6, 28))], make_spec()
        )
    finally:
        os.chdir(previous_cwd)
    assert list(tmp_path.iterdir()) == []


def test_existing_pit_and_dataset_exports_are_unchanged():
    for name in (
        "pit_sample_key",
        "pit_sample_version_id",
        "pit_association_schema",
        "assemble_point_in_time_samples",
        "dataset_id",
        "dataset_schema_id",
        "build_dataset_manifest",
        "SpecPin",
        "SPEC_KIND_SPLIT",
    ):
        assert name in dataset_pkg.__all__
        assert hasattr(dataset_pkg, name)


def test_dataset_id_algorithm_is_unchanged():
    # Identical identity inputs produce identical dataset IDs and the split
    # pin participates through the existing algorithm.
    pin = chronological_split_spec_pin(make_spec())
    first = dataset_id(make_identity_input(pin))
    second = dataset_id(make_identity_input(pin))
    assert first == second
    assert first == dataset_id(make_identity_input(pin))


def test_split_result_version_constants_are_explicit_and_versioned():
    assert CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION.startswith("market-vault-")
    assert CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION.startswith("market-vault-")
    assert CHRONOLOGICAL_SPLITTER_VERSION.startswith("market-vault-")
    assert SPLIT_ASSIGNMENT_SCHEMA_VERSION.startswith("market-vault-")
    assert CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION.startswith("market-vault-")
    # The spec schema version is never reused from the Feature/Label specs.
    assert CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION != "market-vault-feature-spec-v1"
    assert CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION != "market-vault-label-spec-v1"
