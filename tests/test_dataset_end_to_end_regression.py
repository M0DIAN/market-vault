"""End-to-end Dataset determinism and leakage regression suite (v0.5.0
PR-9).

This suite exercises the complete public v0.5.0 execution chain as one
offline regression matrix:

    verified Canonical builds
        -> PIT sample assembly
        -> Feature execution
        -> Label execution
        -> split / purge
        -> Dataset orchestration
        -> immutable materialization
        -> verified Dataset reader

and optionally the Dataset CLI entry combination. It verifies the shipped
production chain; it does not develop new functionality. The seventeen
stable regression categories below extend the v0.4.0 eight-threat model
(``tests/test_leakage_threat_model.py``, documented in
``docs/contracts/leakage_threat_model_regression.md``) with
execution-layer end-to-end coverage: the v0.4.0 suite stops at PIT / split
/ identity layers, while this suite proves the defenses through final
Dataset rows and verified-reader results.

Every test is offline and deterministic: micro Canonical fixtures are
produced through the public builder -> materializer -> verified reader
chain (never hand-constructed ``VerifiedCanonicalBuild`` objects), fixed
dates / run IDs / timestamps, explicit timezone-aware UTC datetimes (naive
values fail closed), no current time, no randomness, no mtime identity
dependence, no sleep, no input-order dependence, no local-timezone
dependence, no OpenD, no network, no real market data, no reads of any
pre-existing data directory (all storage lives under ``tmp_path``), no
repo-directory writes, no model training, no backtesting, and no trading
signals. Positive Datasets are built exclusively through
``orchestrate_dataset_build`` -> ``materialize_dataset_artifacts`` ->
``load_verified_dataset``; no second builder, materializer, or reader is
implemented here.

The fixed regression IDs and the control/defense coverage matrix below are
machine identifiers shared with
``docs/contracts/dataset_end_to_end_regression.md``; the matrix guard
fails the suite if a whole category is ever deleted. The IDs introduce no
production API. No production source, identity algorithm, version
constant, dependency, or CI configuration is modified by this PR.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import market_vault.cli as cli_module
import market_vault.dataset as dataset_pkg
import market_vault.dataset.feature_execution as fe_mod
import market_vault.dataset.label_execution as le_mod
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
    BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    DATASET_FEATURE_SPECS_DIRNAME,
    DATASET_KIND_SUPERVISED,
    DATASET_LABEL_SPECS_DIRNAME,
    DATASET_MANIFEST_FILENAME,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_PARQUET_FILENAME,
    DATASET_SUCCESS_FILENAME,
    FEATURE_SPEC_SCHEMA_VERSION,
    FEATURE_VALUE_STATUS_COMPLETE,
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_SPEC_SCHEMA_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    MISSING_POLICY_EXCLUDE_SAMPLE,
    MISSING_POLICY_LABEL_INCOMPLETE,
    PITAssemblyError,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
    REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
    REASON_CODE_INCOMPLETE_LABEL,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
    SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VALIDATION,
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    ChronologicalSplitSample,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetArtifactValidationError,
    DatasetField,
    DatasetMaterializationError,
    DatasetOrchestrationError,
    DatasetOrchestrationResult,
    DatasetScope,
    FeatureSpec,
    FeatureTransformInput,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    LabelTransformInput,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    SplitValidationError,
    TransformRegistration,
    TransformRegistry,
    TransformWindowRequirement,
    WINDOW_BOUNDARY_INCLUSIVE,
    WINDOW_SOURCE_FIXED,
    WINDOW_SOURCE_LABEL_HORIZON,
    WINDOW_SOURCE_NONE,
    WINDOW_UNIT_BARS,
    WINDOW_UNIT_NONE,
    assign_chronological_splits,
    assemble_point_in_time_samples,
    dataset_orchestration_schema,
    feature_label_spec_content_id,
    feature_label_spec_pin,
    load_verified_dataset,
    materialize_dataset_artifacts,
    orchestrate_dataset_build,
    parse_feature_spec,
    transform_implementation_pin,
)
from market_vault.dataset.cli_models import DATASET_BUILD_PLAN_SCHEMA_VERSION
from market_vault.dataset.feature_registry import (
    built_in_feature_registrations,
)
from market_vault.dataset.label_registry import (
    built_in_label_registrations,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"
NY_ZONE = ZoneInfo(NY)

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_LOG = "market_vault.dataset.feature_transforms.log_return:log_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"
REF_MFE = "market_vault.dataset.label_transforms.maximum_favorable_excursion:maximum_favorable_excursion"

BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
BUILT_AT_ISO = "2026-08-05T12:00:00.000000+00:00"

PARQUET_OPTS = dict(
    compression="zstd",
    use_dictionary=False,
    write_statistics=True,
    coerce_timestamps="us",
    allow_truncated_timestamps=False,
    version="2.6",
    data_page_version="2.0",
)

# ---------------------------------------------------------------------------
# 1. Fixed end-to-end regression IDs and the coverage matrix.
# ---------------------------------------------------------------------------

DATASET_E2E_REGRESSION_IDS = (
    "E2E_FUTURE_FEATURE_LEAKAGE",
    "E2E_ARCHIVE_CUTOFF",
    "E2E_INCOMPLETE_LABEL",
    "E2E_ACTUAL_LABEL_END",
    "E2E_CROSS_DAY_REJECTION",
    "E2E_SPLIT_CROSSING_PURGE",
    "E2E_TRANSFORM_DRIFT",
    "E2E_SPEC_DRIFT",
    "E2E_SOURCE_SNAPSHOT_SUBSTITUTION",
    "E2E_ROW_COLUMN_ORDER",
    "E2E_STAGING_RESIDUE",
    "E2E_IMMUTABLE_CONFLICT",
    "E2E_REBUILD_EQUIVALENCE",
    "E2E_CORRUPTED_PARQUET",
    "E2E_CORRUPTED_MANIFEST",
    "E2E_NON_FINITE",
    "E2E_TIMEZONE_DST",
)

#: Every regression category must keep at least one positive control and one
#: defense test; the matrix guard below fails the suite if a whole category
#: is ever deleted or a declared test function is renamed/removed.
E2E_COVERAGE = {
    "E2E_FUTURE_FEATURE_LEAKAGE": {
        "control": [
            "test_e2e_future_feature_boundary_row_included",
            "test_e2e_future_feature_label_rows_never_feature_role",
        ],
        "defense": [
            "test_e2e_future_feature_input_order_no_leak",
            "test_e2e_future_feature_value_excludes_future_bars",
        ],
    },
    "E2E_ARCHIVE_CUTOFF": {
        "control": [
            "test_e2e_archive_cutoff_no_asof_no_cutoff",
            "test_e2e_archive_cutoff_rows_at_cutoff_included",
        ],
        "defense": [
            "test_e2e_archive_cutoff_after_cutoff_empty_dataset",
            "test_e2e_archive_cutoff_conflicting_rows_fail_closed",
            "test_e2e_archive_cutoff_asof_changes_identity",
            "test_e2e_archive_cutoff_naive_asof_rejected",
        ],
    },
    "E2E_INCOMPLETE_LABEL": {
        "control": [
            "test_e2e_incomplete_label_full_horizon_complete",
        ],
        "defense": [
            "test_e2e_incomplete_label_partial_rows_never_complete",
            "test_e2e_incomplete_label_insufficient_horizon_excluded",
            "test_e2e_incomplete_label_null_outputs_in_final_row",
        ],
    },
    "E2E_ACTUAL_LABEL_END": {
        "control": [
            "test_e2e_actual_label_end_equals_last_consumed_availability",
        ],
        "defense": [
            "test_e2e_actual_label_end_not_nominal_not_window_close",
            "test_e2e_actual_label_end_utc_microseconds",
        ],
    },
    "E2E_CROSS_DAY_REJECTION": {
        "control": [
            "test_e2e_cross_day_same_day_labels_ok",
        ],
        "defense": [
            "test_e2e_cross_day_window_fails_closed_nothing_published",
            "test_e2e_cross_day_allow_true_fails_closed",
            "test_e2e_cross_day_trading_days_horizon_fails_closed",
        ],
    },
    "E2E_SPLIT_CROSSING_PURGE": {
        "control": [
            "test_e2e_split_train_non_crossing_assigned",
        ],
        "defense": [
            "test_e2e_split_train_crossing_purged",
            "test_e2e_split_validation_crossing_purged",
            "test_e2e_split_test_no_fourth_boundary",
            "test_e2e_split_purge_uses_actual_end_not_nominal",
        ],
    },
    "E2E_TRANSFORM_DRIFT": {
        "control": [
            "test_e2e_transform_drift_control_pin_and_dataset_id",
        ],
        "defense": [
            "test_e2e_transform_drift_impl_version_changes_pin_and_dataset_id",
            "test_e2e_transform_drift_label_impl_changes_dataset_id",
        ],
    },
    "E2E_SPEC_DRIFT": {
        "control": [
            "test_e2e_spec_drift_equivalent_yaml_same_identity",
            "test_e2e_spec_drift_spec_order_irrelevant",
        ],
        "defense": [
            "test_e2e_spec_drift_semantic_param_changes_id",
            "test_e2e_spec_drift_label_horizon_changes_id",
            "test_e2e_spec_drift_transform_ref_changes_id",
        ],
    },
    "E2E_SOURCE_SNAPSHOT_SUBSTITUTION": {
        "control": [
            "test_e2e_source_substitution_clean_builds_same_logical_bars",
            "test_e2e_source_substitution_relocation_keeps_identity",
        ],
        "defense": [
            "test_e2e_source_substitution_different_run_changes_dataset_id",
            "test_e2e_source_substitution_mixed_manifest_rejected",
        ],
    },
    "E2E_ROW_COLUMN_ORDER": {
        "control": [
            "test_e2e_row_column_order_permutations_same_identity",
            "test_e2e_row_column_order_physical_sort_and_schema",
        ],
        "defense": [
            "test_e2e_row_column_order_reordered_rows_rejected",
            "test_e2e_row_column_order_reordered_columns_rejected",
            "test_e2e_row_column_order_dtype_change_rejected",
        ],
    },
    "E2E_STAGING_RESIDUE": {
        "control": [
            "test_e2e_staging_residue_foreign_staging_ignored",
        ],
        "defense": [
            "test_e2e_staging_residue_empty_dir_fails_closed",
            "test_e2e_staging_residue_partial_artifacts_fails_closed",
            "test_e2e_staging_residue_missing_success_fails_closed",
            "test_e2e_staging_residue_corrupt_success_fails_closed",
            "test_e2e_staging_residue_complete_uncommitted_fails_closed",
        ],
    },
    "E2E_IMMUTABLE_CONFLICT": {
        "control": [
            "test_e2e_immutable_conflict_identical_rebuild_idempotent",
        ],
        "defense": [
            "test_e2e_immutable_conflict_tampered_file_not_rewritten",
            "test_e2e_immutable_conflict_missing_file_fails_closed",
            "test_e2e_immutable_conflict_extra_file_fails_closed",
            "test_e2e_immutable_conflict_manifest_mismatch_fails_closed",
        ],
    },
    "E2E_REBUILD_EQUIVALENCE": {
        "control": [
            "test_e2e_rebuild_equivalence_identical_inputs",
            "test_e2e_rebuild_equivalence_output_root_relocation",
        ],
        "defense": [
            "test_e2e_rebuild_equivalence_different_built_at_no_conflict",
        ],
    },
    "E2E_CORRUPTED_PARQUET": {
        "control": [
            "test_e2e_corrupted_parquet_pristine_reads_cleanly",
        ],
        "defense": [
            "test_e2e_corrupted_parquet_arbitrary_bytes_rejected",
            "test_e2e_corrupted_parquet_value_change_rejected",
            "test_e2e_corrupted_parquet_row_order_rejected",
            "test_e2e_corrupted_parquet_column_order_rejected",
            "test_e2e_corrupted_parquet_dtype_change_rejected",
            "test_e2e_corrupted_parquet_metadata_change_rejected",
            "test_e2e_corrupted_parquet_no_write_repair",
        ],
    },
    "E2E_CORRUPTED_MANIFEST": {
        "control": [
            "test_e2e_corrupted_manifest_pristine_reads_cleanly",
        ],
        "defense": [
            "test_e2e_corrupted_manifest_non_canonical_json_rejected",
            "test_e2e_corrupted_manifest_schema_version_rejected",
            "test_e2e_corrupted_manifest_dataset_id_rejected",
            "test_e2e_corrupted_manifest_content_id_rejected",
            "test_e2e_corrupted_manifest_output_hash_rejected",
            "test_e2e_corrupted_manifest_spec_pin_rejected",
            "test_e2e_corrupted_manifest_canonical_pin_rejected",
            "test_e2e_corrupted_manifest_unknown_field_rejected",
            "test_e2e_corrupted_manifest_required_field_rejected",
        ],
    },
    "E2E_NON_FINITE": {
        "control": [
            "test_e2e_non_finite_control_finite_values_pass",
        ],
        "defense": [
            "test_e2e_non_finite_feature_nan_inf_fails_closed",
            "test_e2e_non_finite_label_impl_cannot_enter_chain",
            "test_e2e_non_finite_tampered_nan_rejected",
        ],
    },
    "E2E_TIMEZONE_DST": {
        "control": [
            "test_e2e_timezone_equivalent_representations_same_identity",
            "test_e2e_timezone_tz_env_no_effect",
            "test_e2e_timezone_utc_microsecond_output",
        ],
        "defense": [
            "test_e2e_timezone_naive_datetime_rejected",
            "test_e2e_timezone_dst_spring_forward_boundary",
            "test_e2e_timezone_dst_fall_back_boundary",
            "test_e2e_timezone_split_uses_declared_local_date",
            "test_e2e_timezone_invalid_iana_fails_closed",
        ],
    },
}


def test_e2e_coverage_matrix_keeps_control_and_defense_per_category():
    for category in DATASET_E2E_REGRESSION_IDS:
        coverage = E2E_COVERAGE[category]
        assert coverage["control"], f"{category}: no positive control test"
        assert coverage["defense"], f"{category}: no defense test"
        for name in coverage["control"] + coverage["defense"]:
            assert name in globals(), f"{category}: missing test function {name}"
    assert set(DATASET_E2E_REGRESSION_IDS) == set(E2E_COVERAGE)


# ---------------------------------------------------------------------------
# 2. Minimal deterministic storage and verified-Canonical fixtures.
# ---------------------------------------------------------------------------


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc(year, month, day, hour=0, minute=0, second=0, microsecond=0):
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)


def settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        opend_host="127.0.0.1",
        opend_port=11111,
        data_root=tmp_path / "data",
        catalog_path=tmp_path / "catalog" / "market_vault.duckdb",
        manifest_dir=tmp_path / "manifests",
        report_dir=tmp_path / "reports",
        request_pause_seconds=0,
    )


def calendar(cfg: Settings, *, trade_date: date = date(2026, 7, 1)) -> None:
    frame = pd.DataFrame(
        {"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]}
    )
    curated = normalize_trading_calendar(
        frame, market="US", code=None,
        requested_start_date=trade_date, requested_end_date=trade_date,
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"), source="moomoo",
        source_schema_version=cfg.source_schema_version, run_id="cal",
    )
    ParquetStore(cfg).write_trading_calendar_curated(
        curated, "MARKET", "US", trade_date, trade_date, "cal"
    )
    Catalog(cfg).refresh_trading_calendar_views()


def minute_keys(start: str, count: int) -> list[str]:
    base = pd.Timestamp(start, tz=NY)
    return [
        (base + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(count)
    ]


def write_snapshot(
    cfg: Settings,
    *,
    code: str,
    trade_date: date,
    run_id: str,
    time_keys: list[str],
    closes: list[float] | None = None,
    run_finished_at: datetime | None = None,
) -> None:
    count = len(time_keys)
    closes = closes or [100.5] * count
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * count,
            "name": [code] * count,
            "time_key": time_keys,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": closes,
            "volume": [100.0] * count,
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    store.write_curated(
        curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id
    )
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = run_finished_at or datetime(
        trade_date.year, trade_date.month, trade_date.day, 14, 0, tzinfo=UTC
    )
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def default_key() -> CanonicalRequestKey:
    return CanonicalRequestKey(
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )


def materialize(cfg: Settings, *, symbols=None, trade_dates=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=default_key(),
        output_root=output_root(cfg),
        created_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def verified(build_result):
    return load_verified_canonical_build(build_result.build_path)


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    """One shared offline catalog with the micro canonical builds, all
    produced through the public builder -> materializer -> verified reader
    chain:

    ``a``    US.MU 2026-07-01 09:30..09:35 NY (feature window rows),
             closes 100,110,112,118,120,110, archived 14:00Z
    ``f``    US.MU 2026-07-01 09:36..09:41 NY (future label rows),
             closes 100,110,120,130,140,150, archived 14:00Z
    ``fmin`` US.MU 2026-07-01 09:36 NY only (partial label coverage)
    ``c``    US.MU 2026-06-30 09:30..09:35 NY (TRAIN-day feature window)
    ``cf``   US.MU 2026-06-30 09:36..09:38 NY (TRAIN-day label rows)
    ``d``    US.NVDA 2026-07-02 09:30..09:31 NY (TEST-day feature window)
    ``df``   US.NVDA 2026-07-02 09:32..09:34 NY (TEST-day label rows)
    ``e``    US.MU 2026-07-03 09:30..09:31 NY (out-of-range day)
    """
    root = tmp_path_factory.mktemp("mv_e2e")
    cfg = settings(root)
    for trade_date in (
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    ):
        calendar(cfg, trade_date=trade_date)

    def build(code, trade_date, run_id, time_keys, **kwargs):
        write_snapshot(
            cfg, code=code, trade_date=trade_date, run_id=run_id,
            time_keys=time_keys, **kwargs,
        )
        return verified(
            materialize(cfg, symbols=[code], trade_dates=[trade_date])
        )

    a = build(
        "US.MU", date(2026, 7, 1), "run-a",
        minute_keys("2026-07-01 09:30:00", 6),
        closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
    )
    f = build(
        "US.MU", date(2026, 7, 1), "run-f",
        minute_keys("2026-07-01 09:36:00", 6),
        closes=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
    )
    fmin = build(
        "US.MU", date(2026, 7, 1), "run-fmin",
        minute_keys("2026-07-01 09:36:00", 1),
        closes=[100.0],
    )
    c = build(
        "US.MU", date(2026, 6, 30), "run-c",
        minute_keys("2026-06-30 09:30:00", 6),
        closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
    )
    cf = build(
        "US.MU", date(2026, 6, 30), "run-cf",
        minute_keys("2026-06-30 09:36:00", 3),
        closes=[100.0, 110.0, 120.0],
    )
    d = build(
        "US.NVDA", date(2026, 7, 2), "run-d",
        minute_keys("2026-07-02 09:30:00", 2),
        closes=[100.0, 110.0],
    )
    df = build(
        "US.NVDA", date(2026, 7, 2), "run-df",
        minute_keys("2026-07-02 09:32:00", 3),
        closes=[100.0, 110.0, 120.0],
    )
    e = build(
        "US.MU", date(2026, 7, 3), "run-e",
        minute_keys("2026-07-03 09:30:00", 2),
        closes=[100.0, 110.0],
    )
    return SimpleNamespace(a=a, f=f, fmin=fmin, c=c, cf=cf, d=d, df=df, e=e)


# ---------------------------------------------------------------------------
# Spec / request / scope / split / orchestration helpers.
# ---------------------------------------------------------------------------


def feature_spec(
    name: str = "sr",
    *,
    window_bars: int = 2,
    transform_ref: str = REF_SIMPLE,
    input_fields: tuple[str, ...] = ("close",),
) -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=input_fields,
        transform_ref=transform_ref,
        parameters=(SpecParameter("window_bars", window_bars),)
        if transform_ref in (REF_SIMPLE, REF_LOG)
        else (),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec(
    name: str = "fr",
    *,
    horizon: int = 2,
    transform_ref: str = REF_FORWARD,
    observation: tuple[int, int] | None = None,
    input_fields: tuple[str, ...] = ("close",),
    cross_day: CrossTradingDayPolicy | None = None,
) -> LabelSpec:
    if observation is None:
        observation = (horizon - 1, horizon - 1)
    if cross_day is None:
        cross_day = CrossTradingDayPolicy(False, None)
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=input_fields,
        transform_ref=transform_ref,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow("BARS", *observation),
        horizon=LabelHorizon("BARS", horizon),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=cross_day,
    )


def chronological_spec(
    *,
    train_end: date = date(2026, 6, 30),
    validation_end: date = date(2026, 7, 1),
    test_end: date = date(2026, 7, 2),
    boundary_timezone: str = NY,
) -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version=CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
        name="e2e_split",
        version="v1",
        boundary_timezone=boundary_timezone,
        train_end_date=train_end,
        validation_end_date=validation_end,
        test_end_date=test_end,
        assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        purge_rule=SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
        incomplete_label_policy=SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
        out_of_range_policy=SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    )


def request(
    *,
    code: str = "US.MU",
    anchor: date = date(2026, 7, 1),
    f_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
    f_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
    l_start=None,
    l_close=None,
) -> PITSampleRequest:
    if l_start is None:
        l_start = f_close
    if l_close is None:
        l_close = datetime(2026, 7, 1, 13, 42, tzinfo=UTC)
    return PITSampleRequest(
        code=code,
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor_market_calendar_date=anchor,
        feature_window_start=f_start,
        feature_window_close=f_close,
        label_window_start=l_start,
        label_window_close=l_close,
    )


def dataset_scope(
    *,
    symbols=("US.MU",),
    trade_dates=(date(2026, 7, 1),),
) -> DatasetScope:
    return DatasetScope(
        symbols=symbols,
        trade_dates=trade_dates,
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )


def inputs(
    fixtures,
    *,
    requests,
    builds=None,
    feature_specs=None,
    label_specs=None,
    split_spec=None,
    scope=None,
    dataset_as_of=None,
    **extra,
) -> dict:
    builds = builds if builds is not None else [fixtures.a, fixtures.f]
    feature_specs = (
        feature_specs if feature_specs is not None else [feature_spec()]
    )
    label_specs = label_specs if label_specs is not None else [label_spec()]
    split_spec = split_spec if split_spec is not None else chronological_spec()
    scope = scope if scope is not None else dataset_scope()
    schema = dataset_orchestration_schema(
        feature_specs, label_specs,
        include_dataset_as_of=dataset_as_of is not None,
    )
    kwargs = dict(
        builds=tuple(builds),
        requests=tuple(requests),
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=split_spec,
        scope=scope,
        schema=schema,
        dataset_as_of=dataset_as_of,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )
    kwargs.update(extra)
    return kwargs


def orchestrate(fixtures, *, requests, **overrides) -> DatasetOrchestrationResult:
    kwargs = inputs(fixtures, requests=requests, **overrides)
    return orchestrate_dataset_build(**kwargs)


def datasets_root(tmp_path) -> Path:
    return tmp_path / "datasets"


def materialize_once(
    fixtures,
    tmp_path,
    *,
    requests=None,
    built_at=BUILT_AT,
    output_root=None,
    **overrides,
):
    result = orchestrate(fixtures, requests=requests or [request()], **overrides)
    root = output_root or datasets_root(tmp_path)
    mresult = materialize_dataset_artifacts(result, output_root=root, built_at=built_at)
    return result, mresult


def read_verified(mresult) -> dataset_pkg.VerifiedDatasetBuild:
    return load_verified_dataset(mresult.build_path)


def split_sample(
    key_text: str,
    *,
    close,
    status: str = LABEL_STATUS_COMPLETE,
    actual_end=None,
) -> ChronologicalSplitSample:
    """Split fact sample; COMPLETE defaults its actual end to close + 1h."""
    if actual_end is None and status == LABEL_STATUS_COMPLETE:
        actual_end = close.astimezone(UTC) + timedelta(hours=1)
    return ChronologicalSplitSample(
        sample_key=sha(key_text),
        sample_version_id=sha(key_text + ":v"),
        feature_window_close=close.astimezone(UTC),
        label_status=status,
        actual_label_end_time=actual_end,
    )


def file_hashes(build: Path) -> dict[str, str]:
    hashes = {}
    for root, _, files in os.walk(build):
        for name in files:
            path = Path(root) / name
            rel = path.relative_to(build).as_posix()
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_dump(payload) -> str:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    )


def tamper_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    # newline="" disables the platform newline translation; the canonical
    # JSON contract is a bare "\n" terminator.
    path.write_text(canonical_dump(payload), encoding="utf-8", newline="")


def write_parquet_back(path: Path, table: pa.Table) -> None:
    pq.write_table(table, path, **PARQUET_OPTS)


def replace_column_preserving_schema(table: pa.Table, name: str, values) -> pa.Table:
    """Replace one column while preserving the original field's exact Arrow
    type and nullability (a tamper that changes only the values)."""
    field = table.schema.field(table.schema.get_field_index(name))
    column = pa.array(values, type=field.type)
    return table.set_column(
        table.schema.get_field_index(name), pa.field(name, field.type, field.nullable), column
    )


def row_by_name(schema, row: tuple) -> dict:
    return dict(zip((field.name for field in schema.fields), row))


# ---------------------------------------------------------------------------
# 3. Full-chain canaries.
# ---------------------------------------------------------------------------


def test_e2e_canary_complete_dataset_full_chain(fixtures, tmp_path):
    """The complete public chain, end to end, on one COMPLETE Dataset."""
    result, mresult = materialize_once(fixtures, tmp_path)
    assert result.status == STATUS_COMPLETE
    assert mresult.status == STATUS_COMPLETE
    assert mresult.created_new_build is True
    verified_build = read_verified(mresult)
    # The verified reader returns exactly the orchestrated facts.
    assert verified_build.dataset_id == result.dataset_id == mresult.dataset_id
    assert verified_build.status == STATUS_COMPLETE
    assert verified_build.schema == result.schema
    assert verified_build.rows == result.rows
    assert verified_build.build_path == mresult.build_path
    assert verified_build.manifest.dataset_id == result.dataset_id
    assert verified_build.manifest.logical_dataset_content_id == (
        result.logical_dataset_content_id
    )
    assert verified_build.manifest.scope == result.scope
    assert verified_build.manifest.canonical_builds == (
        result.pit_result.canonical_build_pins
    )
    assert verified_build.manifest.feature_specs == result.feature_result.feature_spec_pins
    assert verified_build.manifest.label_specs == result.label_result.label_spec_pins
    assert verified_build.manifest.split_spec == result.split_result.split_spec_pin
    assert set(verified_build.manifest.implementations) == set(
        result.identity_input.implementations
    )
    # Identity re-verified through the public functions.
    assert dataset_pkg.dataset_id(result.identity_input) == result.dataset_id
    assert dataset_pkg.logical_dataset_content_id(
        result.schema, result.logical_row_mappings()
    ) == result.logical_dataset_content_id
    # The one sample is COMPLETE with real Feature / Label / split facts.
    row = verified_build.rows[0]
    facts = row_by_name(verified_build.schema, row)
    assert facts["label_status"] == LABEL_STATUS_COMPLETE
    assert facts["assignment_status"] == SPLIT_STATUS_ASSIGNED
    assert facts["final_split"] == SPLIT_VALIDATION
    assert facts["sr"] == pytest.approx(-1.0 / 12.0, abs=1e-12)
    assert facts["fr"] is not None
    assert verified_build.split_result.split_result_id == result.split_result.split_result_id


def test_e2e_canary_empty_dataset_full_chain(fixtures, tmp_path):
    """An EMPTY Dataset through the same public chain: one Feature window
    with a single row cannot satisfy window_bars=2, so nothing is assigned
    and the Dataset materializes as EMPTY."""
    req = request(f_close=datetime(2026, 7, 1, 13, 31, tzinfo=UTC))
    result, mresult = materialize_once(fixtures, tmp_path, requests=[req])
    assert result.status == STATUS_EMPTY
    assert result.rows == ()
    assert mresult.status == STATUS_EMPTY
    assert mresult.logical_row_count == 0
    verified_build = read_verified(mresult)
    assert verified_build.status == STATUS_EMPTY
    assert verified_build.rows == ()
    assert verified_build.manifest.logical_row_count == 0
    assert verified_build.manifest.dataset_id == result.dataset_id
    # The physical Parquet still carries the authoritative schema.
    table = pq.read_table(mresult.build_path / DATASET_PARQUET_FILENAME)
    assert table.num_rows == 0
    assert [f.name for f in table.schema] == [
        field.name for field in result.schema.fields
    ]


def test_e2e_canary_cli_build_verify_inspect(fixtures, tmp_path, capsys):
    """The Dataset CLI entry combination over one bundle: dataset-build,
    then dataset-verify, then dataset-inspect. This is a public-entry
    combination test only; the CLI argument and JSON field contracts are
    covered by the dedicated CLI suite."""
    bundle = tmp_path / "bundle"
    specs = bundle / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "feature_sr.yaml").write_text(FEATURE_YAML, encoding="utf-8")
    (specs / "label_fr.yaml").write_text(LABEL_YAML, encoding="utf-8")
    plan = {
        "plan_schema_version": DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "canonical_build_dirs": [
            fixtures.a.build_path.as_posix(),
            fixtures.f.build_path.as_posix(),
        ],
        "feature_spec_files": ["specs/feature_sr.yaml"],
        "label_spec_files": ["specs/label_fr.yaml"],
        "requests": [default_request_dict()],
        "scope": default_scope_dict(),
        "split_spec": default_split_spec_dict(),
        "dataset_as_of": None,
        "output_root": "out",
        "built_at": BUILT_AT_ISO,
    }
    plan_path = bundle / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    def run(argv):
        code = cli_module.main(argv)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    code, out, err = run(["dataset-build", "--plan", str(plan_path)])
    assert code == 0, err
    assert err == ""
    build_payload = json.loads(out)
    assert build_payload["command"] == "dataset-build"
    dataset_id = build_payload["dataset_id"]
    build_dir = build_payload["build_path"]

    code, out, err = run(["dataset-verify", "--build-dir", build_dir])
    assert code == 0, err
    verify_payload = json.loads(out)
    assert verify_payload["command"] == "dataset-verify"
    assert verify_payload["dataset_id"] == dataset_id

    code, out, err = run(["dataset-inspect", "--build-dir", build_dir])
    assert code == 0, err
    inspect_payload = json.loads(out)
    assert inspect_payload["command"] == "dataset-inspect"
    assert inspect_payload["dataset_id"] == dataset_id

    # The CLI build is the same immutable Dataset the library chain makes.
    library_verified = load_verified_dataset(Path(build_dir))
    assert library_verified.dataset_id == dataset_id


FEATURE_YAML = """\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: sr
version: v1
output:
  name: sr
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.dataset.feature_transforms.simple_return:simple_return
parameters:
  window_bars: 2
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
"""

LABEL_YAML = """\
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: fr
version: v1
output:
  name: fr
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.dataset.label_transforms.forward_return:forward_return
parameters: {}
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
observation_window:
  unit: BARS
  start_offset: 1
  end_offset: 1
horizon:
  unit: BARS
  value: 2
alignment_rule: FEATURE_CLOSE_ALIGNED
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: false
  boundary_rule: null
"""


def default_request_dict() -> dict:
    return {
        "code": "US.MU",
        "interval": "1m",
        "adjustment": "NONE",
        "requested_session": "ALL",
        "anchor_market_calendar_date": "2026-07-01",
        "feature_window_start": "2026-07-01T13:30:00+00:00",
        "feature_window_close": "2026-07-01T13:36:00+00:00",
        "label_window_start": "2026-07-01T13:36:00+00:00",
        "label_window_close": "2026-07-01T13:42:00+00:00",
    }


def default_scope_dict() -> dict:
    return {
        "symbols": ["US.MU"],
        "trade_dates": ["2026-07-01"],
        "interval": "1m",
        "adjustment": "NONE",
        "requested_session": "ALL",
    }


def default_split_spec_dict() -> dict:
    return {
        "spec_schema_version": "market-vault-chronological-split-spec-v1",
        "name": "e2e_split",
        "version": "v1",
        "boundary_timezone": NY,
        "train_end_date": "2026-06-30",
        "validation_end_date": "2026-07-01",
        "test_end_date": "2026-07-02",
        "assignment_rule": "FEATURE_WINDOW_CLOSE_DATE",
        "purge_rule": "ACTUAL_LABEL_END",
        "incomplete_label_policy": "EXCLUDE",
        "out_of_range_policy": "EXCLUDE",
    }


# ---------------------------------------------------------------------------
# 4. E2E_FUTURE_FEATURE_LEAKAGE.
# ---------------------------------------------------------------------------


def test_e2e_future_feature_boundary_row_included(fixtures):
    """The last Feature row becomes market-available exactly at the window
    close (13:36Z) and is selected by the inclusive market clock."""
    result = orchestrate(fixtures, requests=[request()])
    sample = result.pit_result.samples[0]
    assert sample.diagnostics.feature_selected_count == 6
    assert sample.diagnostics.feature_market_future_excluded_count == 0
    assert result.feature_result.samples[0].status == FEATURE_VALUE_STATUS_COMPLETE


def test_e2e_future_feature_label_rows_never_feature_role(fixtures):
    """Rows of the future label window (09:36..09:41 NY) enter only the
    LABEL role of the sample and never the FEATURE role."""
    result = orchestrate(fixtures, requests=[request()])
    sample = result.pit_result.samples[0]
    feature_ids = set(sample.feature_canonical_row_version_ids)
    label_ids = set(sample.label_canonical_row_version_ids)
    assert label_ids
    assert feature_ids.isdisjoint(label_ids)
    future_version = fixtures.f.bars[0].canonical_row_version_id
    assert future_version in label_ids
    assert future_version not in feature_ids


def test_e2e_future_feature_input_order_no_leak(fixtures):
    """Reordering the build inputs never admits a future bar into the
    Feature window: identity and final rows are unchanged."""
    base = orchestrate(fixtures, requests=[request()])
    swapped = orchestrate(fixtures, requests=[request()], builds=[fixtures.f, fixtures.a])
    assert swapped.dataset_id == base.dataset_id
    assert swapped.rows == base.rows
    sample = swapped.pit_result.samples[0]
    future_version = fixtures.f.bars[0].canonical_row_version_id
    assert future_version not in set(sample.feature_canonical_row_version_ids)


def test_e2e_future_feature_value_excludes_future_bars(fixtures, tmp_path):
    """The final Dataset Feature value is computed from the PIT Feature rows
    only: the simple_return over closes [120, 110] is -1/12, not the -1/11
    that a leaked 13:36Z close=100 bar would produce."""
    result, mresult = materialize_once(fixtures, tmp_path)
    verified_build = read_verified(mresult)
    row = verified_build.rows[0]
    facts = row_by_name(verified_build.schema, row)
    assert facts["sr"] == pytest.approx(-1.0 / 12.0, abs=1e-12)
    assert facts["sr"] != pytest.approx(100.0 / 110.0 - 1.0, abs=1e-9)
    # The feature consumed exactly the last two Feature rows (13:34, 13:35).
    consumed = set(
        result.feature_result.samples[0].values[0].consumed_canonical_row_version_ids
    )
    last_two = {
        fixtures.a.bars[4].canonical_row_version_id,
        fixtures.a.bars[5].canonical_row_version_id,
    }
    assert consumed == last_two


# ---------------------------------------------------------------------------
# 5. E2E_ARCHIVE_CUTOFF.
# ---------------------------------------------------------------------------


def make_two_run_builds(tmp_path):
    """The same bars from two runs with different archive instants:
    run-a archived 14:00Z, run-a2 archived 15:00Z (per-run materialize so
    each build comes from its own audited snapshot)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    keys = minute_keys("2026-07-01 09:30:00", 4)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=keys, run_finished_at=utc(2026, 7, 1, 14, 0))
    build_a = verified(materialize(cfg))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a2",
                   time_keys=keys, run_finished_at=utc(2026, 7, 1, 15, 0))
    build_a2 = verified(materialize(cfg))
    return build_a, build_a2


def test_e2e_archive_cutoff_no_asof_no_cutoff(fixtures, tmp_path):
    """Without dataset_as_of there is no archive clock: every row of the
    feature window is selected."""
    result, mresult = materialize_once(fixtures, tmp_path)
    assert result.dataset_as_of is None
    assert mresult.status == STATUS_COMPLETE
    sample = result.pit_result.samples[0]
    assert sample.diagnostics.feature_selected_count == 6
    assert sample.diagnostics.feature_archive_future_excluded_count == 0


def test_e2e_archive_cutoff_rows_at_cutoff_included(fixtures, tmp_path):
    """Rows archived exactly at dataset_as_of pass the inclusive archive
    clock and produce a COMPLETE Dataset."""
    as_of = utc(2026, 7, 1, 14, 0)
    result, mresult = materialize_once(fixtures, tmp_path, dataset_as_of=as_of)
    assert mresult.status == STATUS_COMPLETE
    sample = result.pit_result.samples[0]
    assert sample.diagnostics.feature_archive_future_excluded_count == 0
    assert sample.diagnostics.feature_selected_count == 6
    assert result.identity_input.dataset_as_of == as_of


def test_e2e_archive_cutoff_after_cutoff_empty_dataset(tmp_path):
    """A run archived after dataset_as_of contributes no row to the final
    Dataset: the full chain materializes an EMPTY Dataset with no feature
    value and no label."""
    build_a, build_a2 = make_two_run_builds(tmp_path)
    # The later run alone under an earlier cutoff: everything is excluded.
    result, mresult = materialize_once(
        SimpleNamespace(a=build_a2, f=None, fmin=None, c=None, cf=None, d=None,
                         df=None, e=None),
        tmp_path,
        builds=[build_a2],
        requests=[request()],
        dataset_as_of=utc(2026, 7, 1, 14, 30),
    )
    assert result.status == STATUS_EMPTY
    assert result.rows == ()
    sample = result.pit_result.samples[0]
    assert sample.diagnostics.feature_archive_future_excluded_count == 4
    assert sample.diagnostics.feature_selected_count == 0
    verified_build = read_verified(mresult)
    assert verified_build.status == STATUS_EMPTY
    assert verified_build.rows == ()
    # No future bar was admitted by the earlier cutoff.
    assert all(
        bar.archive_available_at > utc(2026, 7, 1, 14, 30)
        for bar in build_a2.bars
    )


def test_e2e_archive_cutoff_conflicting_rows_fail_closed(tmp_path):
    """Two runs with the same canonical bars but different row versions fail
    closed in either input order instead of choosing the newest archive."""
    build_a, build_a2 = make_two_run_builds(tmp_path)
    cutoff = utc(2026, 7, 1, 14, 30)
    with pytest.raises(PITAssemblyError):
        assemble_point_in_time_samples(
            [build_a, build_a2], [request()], dataset_as_of=cutoff
        )
    with pytest.raises(PITAssemblyError):
        assemble_point_in_time_samples(
            [build_a2, build_a], [request()], dataset_as_of=cutoff
        )


def test_e2e_archive_cutoff_asof_changes_identity(tmp_path):
    """Different legal dataset_as_of values produce different contents and
    a different dataset_id for the same later-archived build."""
    build_a, build_a2 = make_two_run_builds(tmp_path)
    scope = SimpleNamespace(a=build_a2, f=None, fmin=None, c=None, cf=None,
                            d=None, df=None, e=None)
    early = orchestrate(scope, requests=[request()], builds=[build_a2],
                        dataset_as_of=utc(2026, 7, 1, 14, 30))
    late = orchestrate(scope, requests=[request()], builds=[build_a2],
                       dataset_as_of=utc(2026, 7, 1, 15, 0))
    assert early.status == STATUS_EMPTY
    assert late.status == STATUS_COMPLETE
    assert early.rows == ()
    assert len(late.rows) == 1
    assert early.dataset_id != late.dataset_id
    assert early.identity_input.dataset_as_of != late.identity_input.dataset_as_of


def test_e2e_archive_cutoff_naive_asof_rejected(fixtures):
    """A naive dataset_as_of fails closed before any build work."""
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()],
                    dataset_as_of=datetime(2026, 7, 1, 14, 0))


# ---------------------------------------------------------------------------
# 6. E2E_INCOMPLETE_LABEL.
# ---------------------------------------------------------------------------


def test_e2e_incomplete_label_full_horizon_complete(fixtures):
    """A full label horizon produces COMPLETE labels and an ASSIGNED row."""
    result = orchestrate(fixtures, requests=[request()])
    label_sample = result.label_result.samples[0]
    assert label_sample.status == LABEL_STATUS_COMPLETE
    assert label_sample.actual_label_end_time is not None
    assert result.split_result.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED


def test_e2e_incomplete_label_partial_rows_never_complete(fixtures):
    """Observing only part of the label horizon (one of two required bars)
    never turns the label COMPLETE: the value stays INCOMPLETE with the
    fixed MISSING_TARGET_ROW reason and no value."""
    result = orchestrate(fixtures, requests=[request()], builds=[fixtures.a, fixtures.fmin])
    label_sample = result.label_result.samples[0]
    assert label_sample.status == LABEL_STATUS_INCOMPLETE
    value = label_sample.values[0]
    assert value.status == LABEL_STATUS_INCOMPLETE
    assert value.value is None
    assert value.reason_code == "MISSING_TARGET_ROW"


def test_e2e_incomplete_label_insufficient_horizon_excluded(fixtures, tmp_path):
    """The full chain ends with an EXCLUDED split assignment carrying the
    INCOMPLETE_LABEL reason code."""
    result, mresult = materialize_once(
        fixtures, tmp_path, requests=[request()], builds=[fixtures.a, fixtures.fmin]
    )
    assert mresult.status == STATUS_COMPLETE
    verified_build = read_verified(mresult)
    row = verified_build.rows[0]
    facts = row_by_name(verified_build.schema, row)
    assert facts["label_status"] == LABEL_STATUS_INCOMPLETE
    assert facts["assignment_status"] == SPLIT_STATUS_EXCLUDED
    assert facts["reason_code"] == REASON_CODE_INCOMPLETE_LABEL
    assert facts["final_split"] is None
    assert facts["fr"] is None


def test_e2e_incomplete_label_null_outputs_in_final_row(fixtures, tmp_path):
    """The INCOMPLETE label output and its actual label end are null in the
    final Dataset row, never fabricated from the partial observation."""
    result, mresult = materialize_once(
        fixtures, tmp_path, requests=[request()], builds=[fixtures.a, fixtures.fmin]
    )
    verified_build = read_verified(mresult)
    row = verified_build.rows[0]
    facts = row_by_name(verified_build.schema, row)
    assert facts["label_status"] == LABEL_STATUS_INCOMPLETE
    assert facts["actual_label_end_time"] is None
    assert facts["fr"] is None
    assert facts["purge_boundary"] is None


# ---------------------------------------------------------------------------
# 7. E2E_ACTUAL_LABEL_END.
# ---------------------------------------------------------------------------


def test_e2e_actual_label_end_equals_last_consumed_availability(fixtures, tmp_path):
    """actual_label_end_time is the market-availability instant of the last
    actually consumed label input row, verified through the final row."""
    result, mresult = materialize_once(fixtures, tmp_path)
    value = result.label_result.samples[0].values[0]
    consumed = value.consumed_label_canonical_row_version_ids
    assert len(consumed) == 1
    last_bar = next(
        bar for bar in fixtures.f.bars
        if bar.canonical_row_version_id == consumed[-1]
    )
    expected_end = last_bar.market_available_at.to_pydatetime()
    assert value.actual_label_end_time == expected_end
    verified_build = read_verified(mresult)
    row = verified_build.rows[0]
    facts = row_by_name(verified_build.schema, row)
    assert facts["actual_label_end_time"] == expected_end
    # The end is the availability of the 13:37Z bar: 13:38Z.
    assert expected_end == utc(2026, 7, 1, 13, 38)


def test_e2e_actual_label_end_not_nominal_not_window_close(fixtures):
    """The end is never the last consumed row's event_time (the nominal
    horizon) and never label_window_close. An MFE horizon-3 label consumes
    bars 13:36..13:38Z: its availability end is 13:39Z."""
    mfe = label_spec("mfe", transform_ref=REF_MFE, horizon=3,
                     observation=(0, 2), input_fields=("close", "high"))
    req = request(l_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC))
    result = orchestrate(fixtures, requests=[req], label_specs=[mfe])
    value = result.label_result.samples[0].values[0]
    assert value.status == LABEL_STATUS_COMPLETE
    assert value.actual_label_end_time == utc(2026, 7, 1, 13, 39)
    # The last consumed row's event_time is 13:38Z; the window close is
    # 13:42Z; neither is the availability instant 13:39Z.
    assert value.actual_label_end_time != utc(2026, 7, 1, 13, 38)
    assert value.actual_label_end_time != req.label_window_close
    # The end is the availability of the last consumed row, not the nominal
    # horizon's event-time target: for the horizon-3 MFE label the target
    # event_time is 13:38Z while the end is 13:39Z.
    assert value.actual_label_end_time != (
        req.feature_window_close + timedelta(minutes=2)
    )


def test_e2e_actual_label_end_utc_microseconds(fixtures):
    """The end is UTC microsecond semantics on the actual consumed rows."""
    result = orchestrate(fixtures, requests=[request()])
    end = result.label_result.samples[0].actual_label_end_time
    assert end is not None
    assert end.tzinfo is not None
    assert end.utcoffset() == timedelta(0)
    assert end.microsecond % 1 == 0
    assert end == end.astimezone(NY_ZONE).astimezone(UTC)


# ---------------------------------------------------------------------------
# 8. E2E_CROSS_DAY_REJECTION.
# ---------------------------------------------------------------------------


def test_e2e_cross_day_same_day_labels_ok(fixtures, tmp_path):
    """Labels on the same market calendar date as the anchor flow through
    the full chain normally."""
    result, mresult = materialize_once(fixtures, tmp_path)
    assert mresult.status == STATUS_COMPLETE
    assert result.label_result.samples[0].status == LABEL_STATUS_COMPLETE


def test_e2e_cross_day_window_fails_closed_nothing_published(fixtures, tmp_path):
    """A label window reaching into a later market calendar date fails
    closed at PIT assembly; no Dataset directory or _SUCCESS is ever
    published."""
    req = request(
        code="US.NVDA",
        anchor=date(2026, 7, 1),
        f_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
        f_close=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
        l_start=datetime(2026, 7, 1, 13, 32, tzinfo=UTC),
        l_close=datetime(2026, 7, 2, 13, 35, tzinfo=UTC),
    )
    scope = dataset_scope(
        symbols=("US.MU", "US.NVDA"),
        trade_dates=(date(2026, 7, 1), date(2026, 7, 2)),
    )
    with pytest.raises(DatasetOrchestrationError) as exc_info:
        orchestrate(fixtures, requests=[req], builds=[fixtures.a, fixtures.d],
                    scope=scope)
    assert "cross-market-calendar-date" in str(exc_info.value)
    root = datasets_root(tmp_path)
    assert not root.exists()
    assert not list(tmp_path.rglob(DATASET_SUCCESS_FILENAME))


def test_e2e_cross_day_allow_true_fails_closed(fixtures, tmp_path):
    """cross_trading_day.allow=true is unsupported in the v0.5 execution
    scope and fails closed at orchestration; nothing is published."""
    allow = label_spec(cross_day=CrossTradingDayPolicy(True, "END_OF_TRADING_DAY"))
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], label_specs=[allow])
    assert not datasets_root(tmp_path).exists()


def test_e2e_cross_day_trading_days_horizon_fails_closed(fixtures, tmp_path):
    """A TRADING_DAYS horizon is outside the v0.5 execution scope and fails
    closed instead of truncating or rewriting the window to one day."""
    trading_days = label_spec(
        observation=(0, 0),
        cross_day=CrossTradingDayPolicy(True, "END_OF_TRADING_DAY"),
    )
    trading_days = replace(
        trading_days,
        observation_window=LabelObservationWindow("TRADING_DAYS", 0, 0),
        horizon=LabelHorizon("TRADING_DAYS", 1),
    )
    with pytest.raises(DatasetOrchestrationError):
        orchestrate(fixtures, requests=[request()], label_specs=[trading_days])
    assert not datasets_root(tmp_path).exists()


# ---------------------------------------------------------------------------
# 9. E2E_SPLIT_CROSSING_PURGE.
# ---------------------------------------------------------------------------


def test_e2e_split_train_non_crossing_assigned(fixtures, tmp_path):
    """A TRAIN-day sample whose actual label end stays below the train
    boundary is assigned, through the full chain."""
    req = request(
        anchor=date(2026, 6, 30),
        f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC),
        f_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC),
        l_start=datetime(2026, 6, 30, 13, 36, tzinfo=UTC),
        l_close=datetime(2026, 6, 30, 13, 39, tzinfo=UTC),
    )
    result, mresult = materialize_once(
        fixtures, tmp_path, requests=[req],
        builds=[fixtures.c, fixtures.cf],
        scope=dataset_scope(trade_dates=(date(2026, 6, 30),)),
    )
    assert mresult.status == STATUS_COMPLETE
    assignment = result.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TRAIN
    assert assignment.purge_boundary is None
    verified_build = read_verified(mresult)
    facts = row_by_name(verified_build.schema, verified_build.rows[0])
    assert facts["final_split"] == SPLIT_TRAIN
    assert facts["assignment_status"] == SPLIT_STATUS_ASSIGNED


def test_e2e_split_train_crossing_purged():
    """An actual label end at or past the train boundary purges the TRAIN
    sample with the exact reason and purge boundary."""
    spec = chronological_spec()
    boundary = utc(2026, 7, 1, 4, 0)
    sample = split_sample(
        "train-cross",
        close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
        actual_end=boundary,
    )
    result = assign_chronological_splits([sample], spec)
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.reason_code == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
    assert assignment.purge_boundary == boundary
    assert assignment.final_split is None
    assert assignment.nominal_split == SPLIT_TRAIN


def test_e2e_split_validation_crossing_purged():
    """The same purge rule applies to VALIDATION samples whose actual label
    end crosses the validation boundary."""
    spec = chronological_spec(
        train_end=date(2026, 6, 30), validation_end=date(2026, 7, 31),
        test_end=date(2026, 8, 31),
    )
    boundary = utc(2026, 8, 1, 4, 0)
    sample = split_sample(
        "validation-cross",
        close=datetime(2026, 7, 31, 16, 0, tzinfo=NY_ZONE),
        actual_end=boundary,
    )
    result = assign_chronological_splits([sample], spec)
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.reason_code == (
        REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
    )
    assert assignment.purge_boundary == boundary
    assert assignment.nominal_split == SPLIT_VALIDATION


def test_e2e_split_test_no_fourth_boundary():
    """TEST samples are never purged by an actual label end past
    test_end_date: there is no fourth boundary."""
    spec = chronological_spec(
        train_end=date(2026, 6, 30), validation_end=date(2026, 7, 31),
        test_end=date(2026, 8, 31),
    )
    sample = split_sample(
        "test-late",
        close=datetime(2026, 8, 31, 16, 0, tzinfo=NY_ZONE),
        actual_end=utc(2026, 9, 1, 10, 0),
    )
    result = assign_chronological_splits([sample], spec)
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TEST
    assert assignment.reason_code is None
    assert assignment.purge_boundary is None


def test_e2e_split_purge_uses_actual_end_not_nominal():
    """The purge decision uses only the actual label end: two samples with
    the same feature close (and therefore the same nominal horizon) differ
    only by their actual ends, and only the crossing one is purged."""
    spec = chronological_spec()
    boundary = utc(2026, 7, 1, 4, 0)
    below = split_sample(
        "train-below",
        close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
        actual_end=boundary - timedelta(microseconds=1),
    )
    crossing = split_sample(
        "train-cross",
        close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
        actual_end=boundary,
    )
    result = assign_chronological_splits([below, crossing], spec)
    by_key = {assignment.sample_key: assignment for assignment in result.assignments}
    assert by_key[sha("train-below")].assignment_status == SPLIT_STATUS_ASSIGNED
    assert by_key[sha("train-cross")].assignment_status == SPLIT_STATUS_PURGED


# ---------------------------------------------------------------------------
# 10. E2E_TRANSFORM_DRIFT.
# ---------------------------------------------------------------------------


def test_e2e_transform_drift_control_pin_and_dataset_id(fixtures):
    """Baseline: the built-in simple_return registration carries
    implementation version v1, which is identity-bearing."""
    result = orchestrate(fixtures, requests=[request()])
    assert any(
        pin.name == REF_SIMPLE and pin.version == "v1"
        for pin in result.feature_result.implementation_pins
    )
    assert set(result.identity_input.implementations) == set(
        result.feature_result.implementation_pins
    ) | set(result.label_result.implementation_pins)


def test_e2e_transform_drift_impl_version_changes_pin_and_dataset_id(
    fixtures, tmp_path, monkeypatch
):
    """A registration whose implementation version changes (same transform
    semantics, same spec) changes the ImplementationPin and therefore
    dataset_id, while execution still produces compatible output."""
    base = orchestrate(fixtures, requests=[request()])
    registration = next(
        reg for reg in built_in_feature_registrations()
        if reg.transform_ref == REF_SIMPLE
    )
    drifted = replace(registration, implementation_version="v2")
    assert drifted.implementation_fingerprint != registration.implementation_fingerprint
    registry = TransformRegistry((drifted,))
    monkeypatch.setattr(fe_mod, "built_in_feature_registry", lambda: registry)

    drifted_result = orchestrate(fixtures, requests=[request()])
    assert drifted_result.dataset_id != base.dataset_id
    drifted_pin = transform_implementation_pin(drifted)
    assert any(
        pin.name == REF_SIMPLE and pin.version == "v2"
        for pin in drifted_result.feature_result.implementation_pins
    )
    assert drifted_pin not in base.identity_input.implementations
    assert drifted_pin in drifted_result.identity_input.implementations
    # Compatible output: identical logical rows and feature values.
    assert drifted_result.rows == base.rows
    assert drifted_result.logical_dataset_content_id == (
        base.logical_dataset_content_id
    )
    # The drifted build still materializes and verifies end to end.
    md = materialize_dataset_artifacts(
        drifted_result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    verified_build = read_verified(md)
    assert verified_build.dataset_id == drifted_result.dataset_id
    assert verified_build.rows == drifted_result.rows


def test_e2e_transform_drift_label_impl_changes_dataset_id(
    fixtures, monkeypatch
):
    """The same seam on the Label registry: a Label implementation-version
    change is identity-bearing for the Dataset."""
    base = orchestrate(fixtures, requests=[request()])
    registration = next(
        reg for reg in built_in_label_registrations()
        if reg.transform_ref == REF_FORWARD
    )
    drifted = replace(registration, implementation_version="v2")
    registry = TransformRegistry((drifted,))
    monkeypatch.setattr(le_mod, "built_in_label_registry", lambda: registry)
    drifted_result = orchestrate(fixtures, requests=[request()])
    assert drifted_result.dataset_id != base.dataset_id
    assert drifted_result.rows == base.rows
    assert any(
        pin.name == REF_FORWARD and pin.version == "v2"
        for pin in drifted_result.label_result.implementation_pins
    )


# ---------------------------------------------------------------------------
# 11. E2E_SPEC_DRIFT.
# ---------------------------------------------------------------------------


def _feature_yaml_equivalent() -> tuple[str, str]:
    """Two YAML documents with the same semantics but different key order
    and whitespace."""
    ordered = """\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: sr
version: v1
output:
  name: sr
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.dataset.feature_transforms.simple_return:simple_return
parameters:
  window_bars: 2
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
"""
    reordered = """\
requirements:
  source_schema_versions:
    - "10.9"
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
parameters:
  window_bars: 2
transform:
  ref: market_vault.dataset.feature_transforms.simple_return:simple_return
inputs:
  canonical_fields:
    - close
output:
  nullable: false
  logical_type: float64
  name: sr
version: v1
name: sr
kind: FEATURE
spec_schema_version: market-vault-feature-spec-v1
"""
    return ordered, reordered


def test_e2e_spec_drift_equivalent_yaml_same_identity(fixtures, tmp_path):
    """YAML key order and whitespace never enter the spec content ID, the
    SpecPin, or dataset_id."""
    ordered, reordered = _feature_yaml_equivalent()
    spec_a = parse_feature_spec(ordered)
    spec_b = parse_feature_spec(reordered)
    assert feature_label_spec_content_id(spec_a) == feature_label_spec_content_id(spec_b)
    assert feature_label_spec_pin(spec_a) == feature_label_spec_pin(spec_b)
    result_a = orchestrate(fixtures, requests=[request()], feature_specs=[spec_a])
    result_b = orchestrate(fixtures, requests=[request()], feature_specs=[spec_b])
    assert result_b.dataset_id == result_a.dataset_id
    assert result_b.rows == result_a.rows


def test_e2e_spec_drift_spec_order_irrelevant(fixtures):
    """Feature and Label spec input order never changes identity."""
    sr = feature_spec("sr")
    cb = feature_spec("cb", transform_ref=(
        "market_vault.dataset.feature_transforms.candle_body:candle_body"
    ), input_fields=("open", "close"))
    base = orchestrate(fixtures, requests=[request()], feature_specs=[sr, cb])
    swapped = orchestrate(fixtures, requests=[request()], feature_specs=[cb, sr])
    assert swapped.dataset_id == base.dataset_id
    assert swapped.rows == base.rows


def test_e2e_spec_drift_semantic_param_changes_id(fixtures):
    """A Feature semantic parameter change flows SpecPin -> identity input
    -> dataset_id."""
    base = orchestrate(fixtures, requests=[request()])
    drifted = replace(base.feature_specs[0], parameters=(SpecParameter("window_bars", 3),))
    result = orchestrate(fixtures, requests=[request()], feature_specs=[drifted])
    assert feature_label_spec_pin(base.feature_specs[0]) != feature_label_spec_pin(drifted)
    assert result.identity_input.feature_specs != base.identity_input.feature_specs
    assert result.dataset_id != base.dataset_id
    assert result.status == STATUS_COMPLETE


def test_e2e_spec_drift_label_horizon_changes_id(fixtures):
    """A Label horizon change flows through the same chain."""
    base = orchestrate(fixtures, requests=[request()])
    drifted = label_spec(horizon=3, observation=(2, 2))
    result = orchestrate(fixtures, requests=[request()], label_specs=[drifted])
    assert feature_label_spec_pin(base.label_specs[0]) != feature_label_spec_pin(drifted)
    assert result.identity_input.label_specs != base.identity_input.label_specs
    assert result.dataset_id != base.dataset_id
    assert result.label_result.samples[0].status == LABEL_STATUS_COMPLETE


def test_e2e_spec_drift_transform_ref_changes_id(fixtures):
    """A transform_ref change is a semantic spec change that changes
    dataset_id even when the output column and data are compatible."""
    base = orchestrate(fixtures, requests=[request()])
    drifted = feature_spec(transform_ref=REF_LOG)
    result = orchestrate(fixtures, requests=[request()], feature_specs=[drifted])
    assert feature_label_spec_pin(base.feature_specs[0]) != feature_label_spec_pin(drifted)
    assert result.dataset_id != base.dataset_id
    assert result.feature_result.samples[0].status == FEATURE_VALUE_STATUS_COMPLETE


# ---------------------------------------------------------------------------
# 12. E2E_SOURCE_SNAPSHOT_SUBSTITUTION.
# ---------------------------------------------------------------------------


def make_substitute_build(tmp_path):
    """A second verified Canonical build with the same logical bars as
    ``a`` but a different physical snapshot (different run id), so the
    SourceSnapshotPin / CanonicalBuildPin differ while the bar values are
    identical."""
    cfg = settings(tmp_path)
    calendar(cfg)
    keys = minute_keys("2026-07-01 09:30:00", 6)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=keys, closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
                   run_finished_at=utc(2026, 7, 1, 14, 0))
    original = verified(materialize(cfg))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-sub",
                   time_keys=keys, closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
                   run_finished_at=utc(2026, 7, 1, 14, 0))
    substitute = verified(materialize(cfg))
    return original, substitute


def test_e2e_source_substitution_clean_builds_same_logical_bars(tmp_path):
    """Both verified builds read cleanly and carry identical logical bar
    values with different source provenance."""
    original, substitute = make_substitute_build(tmp_path)
    assert original.canonical_build_id != substitute.canonical_build_id
    assert [bar.close for bar in original.bars] == [bar.close for bar in substitute.bars]
    assert [bar.event_time for bar in original.bars] == [bar.event_time for bar in substitute.bars]
    assert (
        original.source_snapshot_provenance[0].physical_snapshot_hash
        != substitute.source_snapshot_provenance[0].physical_snapshot_hash
    )
    assert (
        original.canonical_row_version_ids != substitute.canonical_row_version_ids
    )


def test_e2e_source_substitution_relocation_keeps_identity(fixtures, tmp_path):
    """Relocating a Canonical build directory does not change its identity
    or the derived dataset_id: paths never enter pins."""
    relocated = tmp_path / "relocated"
    shutil.copytree(fixtures.a.build_path, relocated / fixtures.a.build_path.name)
    moved = load_verified_canonical_build(relocated / fixtures.a.build_path.name)
    assert moved.canonical_build_id == fixtures.a.canonical_build_id
    base = orchestrate(fixtures, requests=[request()])
    result = orchestrate(fixtures, requests=[request()], builds=[moved, fixtures.f])
    assert result.dataset_id == base.dataset_id
    assert result.rows == base.rows


def test_e2e_source_substitution_different_run_changes_dataset_id(tmp_path):
    """A substituted source (identical bars, different physical snapshot)
    changes the Dataset provenance and dataset_id."""
    original, substitute = make_substitute_build(tmp_path)
    scope = SimpleNamespace(a=original, f=None, fmin=None, c=None, cf=None,
                            d=None, df=None, e=None)
    base = orchestrate(scope, requests=[request()], builds=[original])
    sub = orchestrate(scope, requests=[request()], builds=[substitute])
    assert sub.dataset_id != base.dataset_id
    assert sub.identity_input.canonical_builds != base.identity_input.canonical_builds
    assert (
        sub.identity_input.canonical_row_version_ids
        != base.identity_input.canonical_row_version_ids
    )


def test_e2e_source_substitution_mixed_manifest_rejected(fixtures, tmp_path):
    """Mixing a different source's pins into an existing Dataset manifest is
    rejected by the verified reader (the manifest dataset_id binding breaks)."""
    result, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda payload: payload["canonical_builds"][0].update(
        canonical_build_id=sha("other-build"), canonical_content_id=sha("other-content")
    ))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


# ---------------------------------------------------------------------------
# 13. E2E_ROW_COLUMN_ORDER.
# ---------------------------------------------------------------------------


def test_e2e_row_column_order_permutations_same_identity(fixtures):
    """Semantically identical permutations of builds, requests, spec order,
    and scope symbol order produce identical logical rows and dataset_id."""
    cb = feature_spec("cb", transform_ref=(
        "market_vault.dataset.feature_transforms.candle_body:candle_body"
    ), input_fields=("open", "close"))
    req_mu = request()
    req_nvda = request(
        code="US.NVDA",
        anchor=date(2026, 7, 2),
        f_start=datetime(2026, 7, 2, 13, 30, tzinfo=UTC),
        f_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
        l_start=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
        l_close=datetime(2026, 7, 2, 13, 38, tzinfo=UTC),
    )
    scope = dataset_scope(
        symbols=("US.MU", "US.NVDA"),
        trade_dates=(date(2026, 7, 1), date(2026, 7, 2)),
    )
    kwargs = dict(
        requests=[req_mu, req_nvda],
        feature_specs=[feature_spec(), cb],
        label_specs=[label_spec()],
        split_spec=chronological_spec(),
        scope=scope,
        builds=[fixtures.a, fixtures.f, fixtures.d, fixtures.df],
    )
    base = orchestrate(fixtures, **kwargs)
    permuted = orchestrate(
        fixtures,
        requests=[req_nvda, req_mu],
        feature_specs=[cb, feature_spec()],
        scope=dataset_scope(
            symbols=("US.NVDA", "US.MU"),
            trade_dates=(date(2026, 7, 2), date(2026, 7, 1)),
        ),
        builds=[fixtures.df, fixtures.d, fixtures.f, fixtures.a],
        label_specs=[label_spec()],
        split_spec=chronological_spec(),
    )
    assert permuted.rows == base.rows
    assert permuted.logical_dataset_content_id == base.logical_dataset_content_id
    assert permuted.dataset_id == base.dataset_id


def two_row_dataset(fixtures, tmp_path):
    """A two-symbol, two-row Dataset through the full chain (US.MU
    VALIDATION and US.NVDA TEST)."""
    req_mu = request()
    req_nvda = request(
        code="US.NVDA",
        anchor=date(2026, 7, 2),
        f_start=datetime(2026, 7, 2, 13, 30, tzinfo=UTC),
        f_close=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
        l_start=datetime(2026, 7, 2, 13, 32, tzinfo=UTC),
        l_close=datetime(2026, 7, 2, 13, 38, tzinfo=UTC),
    )
    return materialize_once(
        fixtures, tmp_path, requests=[req_mu, req_nvda],
        builds=[fixtures.a, fixtures.f, fixtures.d, fixtures.df],
        scope=dataset_scope(
            symbols=("US.MU", "US.NVDA"),
            trade_dates=(date(2026, 7, 1), date(2026, 7, 2)),
        ),
    )


def test_e2e_row_column_order_physical_sort_and_schema(fixtures, tmp_path):
    """The physical Parquet output keeps code ASC, feature_window_close ASC,
    sample_key ASC (code-first), and the exact authoritative column order."""
    result, mresult = two_row_dataset(fixtures, tmp_path)
    assert len(result.rows) == 2
    table = pq.read_table(mresult.build_path / DATASET_PARQUET_FILENAME)
    assert [f.name for f in table.schema] == [
        field.name for field in result.schema.fields
    ]
    frame = table.to_pandas()
    keys = list(
        zip(
            frame["code"].tolist(),
            frame["feature_window_close"].tolist(),
            frame["sample_key"].tolist(),
        )
    )
    assert keys == sorted(keys)
    # The fixed sort is code-first: US.MU (VALIDATION) before US.NVDA (TEST).
    assert frame["code"].iloc[0] == "US.MU"
    assert frame["final_split"].tolist() == [SPLIT_VALIDATION, SPLIT_TEST]
    verified_build = read_verified(mresult)
    assert verified_build.rows == result.rows


def test_e2e_row_column_order_reordered_rows_rejected(fixtures, tmp_path):
    """Manually reversing the physical Parquet rows is rejected by the
    verified reader."""
    _, mresult = two_row_dataset(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    assert table.num_rows >= 2
    reversed_rows = table.take(list(range(table.num_rows - 1, -1, -1)))
    write_parquet_back(parquet, reversed_rows)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_row_column_order_reordered_columns_rejected(fixtures, tmp_path):
    """Manually reordering the Parquet columns is rejected."""
    result, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    names = list(table.schema.names)
    reordered = table.select(names[::-1])
    write_parquet_back(parquet, reordered)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_row_column_order_dtype_change_rejected(fixtures, tmp_path):
    """Changing a field dtype in the Parquet is rejected."""
    result, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    index = table.schema.get_field_index("sr")
    column = table.column("sr").cast(pa.float32())
    table = table.set_column(index, "sr", column)
    write_parquet_back(parquet, table)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


# ---------------------------------------------------------------------------
# 14. E2E_STAGING_RESIDUE.
# ---------------------------------------------------------------------------


def _residue_root(tmp_path, result) -> Path:
    return tmp_path / "out"


def test_e2e_staging_residue_foreign_staging_ignored(fixtures, tmp_path):
    """A staging directory of a different dataset_id never blocks the
    materializer: it only ever looks at its own staging path."""
    result, mresult = materialize_once(fixtures, tmp_path)
    root = datasets_root(tmp_path)
    (root / f".staging-{sha('other')}").mkdir(parents=True, exist_ok=True)
    again = materialize_dataset_artifacts(result, output_root=root, built_at=BUILT_AT)
    assert again.created_new_build is False
    assert again.dataset_id == result.dataset_id


def test_e2e_staging_residue_empty_dir_fails_closed(fixtures, tmp_path):
    """An empty staging directory fails closed; it is neither adopted nor
    deleted."""
    result = orchestrate(fixtures, requests=[request()])
    root = _residue_root(tmp_path, result)
    staging = root / f".staging-{result.dataset_id}"
    staging.mkdir(parents=True, exist_ok=True)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=root, built_at=BUILT_AT)
    assert staging.is_dir()
    assert not (root / result.dataset_id).exists()


def test_e2e_staging_residue_partial_artifacts_fails_closed(fixtures, tmp_path):
    """A staging directory with partial artifacts fails closed."""
    result = orchestrate(fixtures, requests=[request()])
    root = _residue_root(tmp_path, result)
    staging = root / f".staging-{result.dataset_id}"
    (staging / DATASET_PARQUET_FILENAME).parent.mkdir(parents=True, exist_ok=True)
    (staging / DATASET_PARQUET_FILENAME).write_bytes(b"partial")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=root, built_at=BUILT_AT)
    assert (staging / DATASET_PARQUET_FILENAME).read_bytes() == b"partial"
    assert not (root / result.dataset_id).exists()


def test_e2e_staging_residue_missing_success_fails_closed(fixtures, tmp_path):
    """A staging directory that looks complete but lacks _SUCCESS is never
    adopted."""
    result = orchestrate(fixtures, requests=[request()])
    root = _residue_root(tmp_path, result)
    staging = root / f".staging-{result.dataset_id}"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=root, built_at=BUILT_AT)
    assert staging.is_dir()
    assert not (root / result.dataset_id).exists()


def test_e2e_staging_residue_corrupt_success_fails_closed(fixtures, tmp_path):
    """A staging directory with a corrupt _SUCCESS fails closed."""
    result = orchestrate(fixtures, requests=[request()])
    root = _residue_root(tmp_path, result)
    staging = root / f".staging-{result.dataset_id}"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / DATASET_SUCCESS_FILENAME).write_bytes(b"not empty")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=root, built_at=BUILT_AT)
    assert (staging / DATASET_SUCCESS_FILENAME).read_bytes() == b"not empty"
    assert not (root / result.dataset_id).exists()


def test_e2e_staging_residue_complete_uncommitted_fails_closed(fixtures, tmp_path):
    """A staging directory that is a full copy of a valid final build (even
    including _SUCCESS) is never adopted: it was never atomically
    committed."""
    result = orchestrate(fixtures, requests=[request()])
    root = _residue_root(tmp_path, result)
    staging = root / f".staging-{result.dataset_id}"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / DATASET_SUCCESS_FILENAME).write_bytes(b"")
    (staging / "manifest.json").write_bytes(b"{}")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=root, built_at=BUILT_AT)
    assert staging.is_dir()
    assert not (root / result.dataset_id).exists()


# ---------------------------------------------------------------------------
# 15. E2E_IMMUTABLE_CONFLICT.
# ---------------------------------------------------------------------------


def _snapshot_state(build: Path) -> tuple:
    hashes = file_hashes(build)
    sizes = {
        rel: (build / rel).stat().st_size for rel in hashes
    }
    mtimes = {
        rel: (build / rel).stat().st_mtime_ns for rel in hashes
    }
    entries = {
        rel for rel in hashes
    } | {
        rel.as_posix() + "/"
        for rel in (
            (build / DATASET_FEATURE_SPECS_DIRNAME),
            (build / DATASET_LABEL_SPECS_DIRNAME),
        )
    }
    return hashes, sizes, mtimes, entries


def test_e2e_immutable_conflict_identical_rebuild_idempotent(fixtures, tmp_path):
    """An identical rebuild is idempotent, never a conflict."""
    result, mresult = materialize_once(fixtures, tmp_path)
    again = materialize_dataset_artifacts(result, output_root=datasets_root(tmp_path),
                                          built_at=BUILT_AT)
    assert again.created_new_build is False
    assert again.build_path == mresult.build_path
    assert file_hashes(again.build_path) == file_hashes(mresult.build_path)


def test_e2e_immutable_conflict_tampered_file_not_rewritten(fixtures, tmp_path):
    """A tampered final artifact fails closed and is never rewritten:
    hashes, sizes, mtimes, and the entry set are untouched."""
    result, mresult = materialize_once(fixtures, tmp_path)
    build = mresult.build_path
    parquet = build / DATASET_PARQUET_FILENAME
    parquet.write_bytes(b"tampered")
    before = _snapshot_state(build)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=build.parent, built_at=BUILT_AT)
    after = _snapshot_state(build)
    assert after == before
    assert (build / DATASET_PARQUET_FILENAME).read_bytes() == b"tampered"


def test_e2e_immutable_conflict_missing_file_fails_closed(fixtures, tmp_path):
    """A missing final artifact fails closed and is never recreated."""
    result, mresult = materialize_once(fixtures, tmp_path)
    build = mresult.build_path
    (build / DATASET_PARQUET_FILENAME).unlink()
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=build.parent, built_at=BUILT_AT)
    assert not (build / DATASET_PARQUET_FILENAME).exists()


def test_e2e_immutable_conflict_extra_file_fails_closed(fixtures, tmp_path):
    """An unexpected file in the final directory fails closed and is never
    removed."""
    result, mresult = materialize_once(fixtures, tmp_path)
    build = mresult.build_path
    extra = build / "unexpected.bin"
    extra.write_bytes(b"extra")
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=build.parent, built_at=BUILT_AT)
    assert extra.read_bytes() == b"extra"


def test_e2e_immutable_conflict_manifest_mismatch_fails_closed(fixtures, tmp_path):
    """A manifest that no longer matches its artifacts fails closed; the
    conflicting artifact is preserved."""
    result, mresult = materialize_once(fixtures, tmp_path)
    build = mresult.build_path
    parquet = build / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    values = table.column("sr").to_pylist()
    values[0] = values[0] + 1.0
    table = replace_column_preserving_schema(table, "sr", values)
    write_parquet_back(parquet, table)
    before = _snapshot_state(build)
    with pytest.raises(DatasetMaterializationError):
        materialize_dataset_artifacts(result, output_root=build.parent, built_at=BUILT_AT)
    after = _snapshot_state(build)
    assert after == before


# ---------------------------------------------------------------------------
# 16. E2E_REBUILD_EQUIVALENCE.
# ---------------------------------------------------------------------------


def test_e2e_rebuild_equivalence_identical_inputs(fixtures, tmp_path):
    """Rebuilding from identical pinned inputs reproduces the identical
    Dataset: same dataset_id, same logical content, same verified rows,
    same build path, byte-identical artifacts, and idempotent second
    build."""
    result, mresult = materialize_once(fixtures, tmp_path)
    assert mresult.created_new_build is True
    first_hashes = file_hashes(mresult.build_path)
    first_state = _snapshot_state(mresult.build_path)

    again = materialize_dataset_artifacts(result, output_root=datasets_root(tmp_path),
                                          built_at=BUILT_AT)
    assert again.created_new_build is False
    assert again.dataset_id == mresult.dataset_id
    assert again.build_path == mresult.build_path
    assert file_hashes(again.build_path) == first_hashes
    assert _snapshot_state(again.build_path) == first_state

    verified_first = read_verified(mresult)
    verified_again = read_verified(again)
    assert verified_again.dataset_id == verified_first.dataset_id
    assert verified_again.rows == verified_first.rows
    assert verified_again.manifest == verified_first.manifest


def test_e2e_rebuild_equivalence_output_root_relocation(fixtures, tmp_path):
    """A different output_root never enters dataset_id: the same result
    materializes the same dataset_id and logical content elsewhere."""
    result, mresult = materialize_once(fixtures, tmp_path)
    other_root = tmp_path / "other-datasets"
    relocated = materialize_dataset_artifacts(result, output_root=other_root,
                                              built_at=BUILT_AT)
    assert relocated.dataset_id == mresult.dataset_id
    assert relocated.build_path != mresult.build_path
    assert read_verified(relocated).rows == read_verified(mresult).rows
    assert read_verified(relocated).manifest.logical_dataset_content_id == (
        read_verified(mresult).manifest.logical_dataset_content_id
    )


def test_e2e_rebuild_equivalence_different_built_at_no_conflict(fixtures, tmp_path):
    """A different built_at on the second build never creates a conflict:
    built_at is a recorded fact, not identity, and the verified result
    reports the existing build's built_at."""
    result, mresult = materialize_once(fixtures, tmp_path)
    later = BUILT_AT + timedelta(hours=6)
    again = materialize_dataset_artifacts(result, output_root=datasets_root(tmp_path),
                                          built_at=later)
    assert again.created_new_build is False
    assert again.dataset_id == mresult.dataset_id
    verified_build = read_verified(again)
    assert verified_build.built_at == BUILT_AT
    assert verified_build.manifest.built_at == BUILT_AT
    assert verified_build.rows == read_verified(mresult).rows


# ---------------------------------------------------------------------------
# 17. E2E_CORRUPTED_PARQUET.
# ---------------------------------------------------------------------------


def test_e2e_corrupted_parquet_pristine_reads_cleanly(fixtures, tmp_path):
    """Control: the pristine Dataset Parquet verifies."""
    _, mresult = materialize_once(fixtures, tmp_path)
    verified_build = read_verified(mresult)
    assert verified_build.dataset_id == mresult.dataset_id


def _rewrite_with_coordinated_records(mresult, path: Path, new_bytes: bytes) -> None:
    """Overwrite one artifact and update the manifest output-file record so
    the byte facts still match; the reader then reaches the artifact read
    itself (where the original exception is preserved as __cause__)."""
    path.write_bytes(new_bytes)
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    new_size = len(new_bytes)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME

    def mutate(payload):
        record = next(
            r for r in payload["output_files"]
            if r["relative_path"] == path.name
        )
        record.update(sha256=new_sha, byte_size=new_size)

    tamper_json(manifest_path, mutate)


def test_e2e_corrupted_parquet_arbitrary_bytes_rejected(fixtures, tmp_path):
    """Arbitrary byte corruption is rejected with the original Arrow
    exception preserved as __cause__ (the reader reaches the Parquet read
    itself and wraps the underlying failure)."""
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    _rewrite_with_coordinated_records(
        mresult, parquet, b"not a parquet file at all"
    )
    with pytest.raises(DatasetArtifactValidationError) as exc_info:
        load_verified_dataset(mresult.build_path)
    # The original Arrow failure is preserved through the documented error
    # chain: DatasetArtifactValidationError <- DatasetMaterializationError
    # <- pa.ArrowException.
    cause = exc_info.value.__cause__
    assert cause is not None
    assert isinstance(cause, dataset_pkg.DatasetMaterializationError)
    assert isinstance(cause.__cause__, pa.ArrowException)


def test_e2e_corrupted_parquet_value_change_rejected(fixtures, tmp_path):
    """A legal Parquet file whose logical values were changed is rejected
    by the logical content identity."""
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    values = table.column("fr").to_pylist()
    values[0] = values[0] + 1.0 if values[0] is not None else 1.0
    table = replace_column_preserving_schema(table, "fr", values)
    write_parquet_back(parquet, table)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_parquet_row_order_rejected(fixtures, tmp_path):
    """Changing the physical row order is rejected even though the logical
    content id is order-independent."""
    _, mresult = two_row_dataset(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    n = table.num_rows
    table = table.take(list(range(n - 1, -1, -1)))
    write_parquet_back(parquet, table)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_parquet_column_order_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    table = table.select(list(reversed(table.schema.names)))
    write_parquet_back(parquet, table)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_parquet_dtype_change_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    index = table.schema.get_field_index("sample_version_id")
    table = table.set_column(index, "sample_version_id",
                             table.column("sample_version_id").cast(pa.large_string()))
    write_parquet_back(parquet, table)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_parquet_metadata_change_rejected(fixtures, tmp_path):
    """Changing the Parquet metadata key set is rejected."""
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    metadata = dict(table.schema.metadata)
    key = b"market_vault.dataset_id"
    assert key in metadata
    del metadata[key]
    table = table.replace_schema_metadata(metadata)
    write_parquet_back(parquet, table)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_parquet_no_write_repair(fixtures, tmp_path):
    """A rejected Dataset is never written, repaired, or regenerated by the
    reader: bytes and entries stay exactly as found."""
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    values = table.column("sr").to_pylist()
    values[0] = values[0] + 1.0
    table = replace_column_preserving_schema(table, "sr", values)
    write_parquet_back(parquet, table)
    before = file_hashes(mresult.build_path)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)
    assert file_hashes(mresult.build_path) == before


# ---------------------------------------------------------------------------
# 18. E2E_CORRUPTED_MANIFEST.
# ---------------------------------------------------------------------------


def test_e2e_corrupted_manifest_pristine_reads_cleanly(fixtures, tmp_path):
    """Control: the pristine manifest verifies."""
    _, mresult = materialize_once(fixtures, tmp_path)
    verified_build = read_verified(mresult)
    assert verified_build.manifest.dataset_id == mresult.dataset_id


def test_e2e_corrupted_manifest_non_canonical_json_rejected(fixtures, tmp_path):
    """Any formatting difference (here: spaces) breaks the canonical-bytes
    contract."""
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline=""
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_schema_version_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p.update(manifest_schema_version="market-vault-dataset-manifest-v9"))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_dataset_id_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p.update(dataset_id="0" * 64))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_content_id_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p.update(logical_dataset_content_id="1" * 64))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_output_hash_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p["output_files"][0].update(
        sha256="f" * 64, byte_size=p["output_files"][0]["byte_size"] + 1
    ))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_spec_pin_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p["feature_specs"][0].update(
        content_sha256="2" * 64
    ))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_canonical_pin_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p["canonical_builds"][0].update(
        canonical_build_id="3" * 64
    ))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_unknown_field_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p.update(unexpected_field=1))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


def test_e2e_corrupted_manifest_required_field_rejected(fixtures, tmp_path):
    _, mresult = materialize_once(fixtures, tmp_path)
    manifest_path = mresult.build_path / DATASET_MANIFEST_FILENAME
    tamper_json(manifest_path, lambda p: p.pop("scope"))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(mresult.build_path)


# ---------------------------------------------------------------------------
# 19. E2E_NON_FINITE.
# ---------------------------------------------------------------------------

#: Test-registry implementations that violate the finite-value output
#: contract. They are plain module-level functions registered through the
#: public TransformRegistration model and executed by the production
#: executor, which must fail the build before anything is published.


def _nan_feature_impl(input_: FeatureTransformInput) -> float:
    return float("nan")


def _pos_inf_feature_impl(input_: FeatureTransformInput) -> float:
    return float("inf")


def _neg_inf_feature_impl(input_: FeatureTransformInput) -> float:
    return float("-inf")


def _nan_label_impl(input_: LabelTransformInput) -> float:
    return float("nan")


def _non_finite_feature_registration(impl) -> TransformRegistration:
    return TransformRegistration(
        transform_ref=impl.__module__ + ":" + impl.__name__,
        kind=SPEC_KIND_FEATURE,
        implementation_version="v1",
        implementation=impl,
        input_canonical_fields=("close",),
        supported_canonical_schema_versions=("market-bars-canonical-schema-v1",),
        supported_source_schema_versions=("10.9",),
        output_logical_type="float64",
        output_nullable=False,
        parameters=(),
        lookback=TransformWindowRequirement(
            source=WINDOW_SOURCE_FIXED, unit=WINDOW_UNIT_BARS, value=1,
            parameter_name=None, boundary=WINDOW_BOUNDARY_INCLUSIVE,
        ),
        lookforward=TransformWindowRequirement(
            source=WINDOW_SOURCE_NONE, unit=WINDOW_UNIT_NONE
        ),
        boundary_policy=BOUNDARY_POLICY_SAME_MARKET_CALENDAR_DATE,
        missing_policy=MISSING_POLICY_EXCLUDE_SAMPLE,
        display_name="test non-finite feature",
    )


def _non_finite_label_registration(impl) -> TransformRegistration:
    return TransformRegistration(
        transform_ref=impl.__module__ + ":" + impl.__name__,
        kind=SPEC_KIND_LABEL,
        implementation_version="v1",
        implementation=impl,
        input_canonical_fields=("close",),
        supported_canonical_schema_versions=("market-bars-canonical-schema-v1",),
        supported_source_schema_versions=("10.9",),
        output_logical_type="float64",
        output_nullable=False,
        parameters=(),
        lookback=TransformWindowRequirement(
            source=WINDOW_SOURCE_FIXED, unit=WINDOW_UNIT_BARS, value=1,
            parameter_name=None, boundary=WINDOW_BOUNDARY_INCLUSIVE,
        ),
        lookforward=TransformWindowRequirement(
            source=WINDOW_SOURCE_LABEL_HORIZON, unit=WINDOW_UNIT_BARS,
            value=None, parameter_name=None, boundary=WINDOW_BOUNDARY_INCLUSIVE,
        ),
        boundary_policy=BOUNDARY_POLICY_NO_CROSS_TRADING_DAY,
        missing_policy=MISSING_POLICY_LABEL_INCOMPLETE,
        display_name="test non-finite label",
    )


def test_e2e_non_finite_control_finite_values_pass(fixtures, tmp_path):
    """Control: finite built-in outputs pass the full chain."""
    _, mresult = materialize_once(fixtures, tmp_path)
    assert mresult.status == STATUS_COMPLETE
    verified_build = read_verified(mresult)
    assert verified_build.status == STATUS_COMPLETE


@pytest.mark.parametrize("impl", [_nan_feature_impl, _pos_inf_feature_impl, _neg_inf_feature_impl])
def test_e2e_non_finite_feature_nan_inf_fails_closed(fixtures, tmp_path, monkeypatch, impl):
    """A Feature transform returning NaN or +/-Infinity fails the build
    before any Dataset directory or _SUCCESS exists."""
    registration = _non_finite_feature_registration(impl)
    spec = FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="sr",
        version="v1",
        output=DatasetField("sr", "float64", False),
        input_canonical_fields=("close",),
        transform_ref=registration.transform_ref,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )
    monkeypatch.setattr(
        fe_mod, "built_in_feature_registry", lambda: TransformRegistry((registration,))
    )
    with pytest.raises(DatasetOrchestrationError) as exc_info:
        orchestrate(fixtures, requests=[request()], feature_specs=[spec])
    assert "NaN" in str(exc_info.value) or "infinity" in str(exc_info.value)
    assert not datasets_root(tmp_path).exists()


def test_e2e_non_finite_label_impl_cannot_enter_chain(fixtures, tmp_path, monkeypatch):
    """A non-finite-producing Label implementation cannot enter the v0.5
    execution chain at all: Label execution structurally refuses any
    registration outside the four fixed built-in transforms, so a
    NaN/Infinity Label output is unreachable by construction (fail closed
    at build configuration, nothing published)."""
    registration = _non_finite_label_registration(_nan_label_impl)
    spec = LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name="fr",
        version="v1",
        output=DatasetField("fr", "float64", False),
        input_canonical_fields=("close",),
        transform_ref=registration.transform_ref,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow("BARS", 1, 1),
        horizon=LabelHorizon("BARS", 2),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )
    monkeypatch.setattr(
        le_mod, "built_in_label_registry", lambda: TransformRegistry((registration,))
    )
    with pytest.raises(DatasetOrchestrationError) as exc_info:
        orchestrate(fixtures, requests=[request()], label_specs=[spec])
    assert "not a supported built-in Label transform" in str(exc_info.value)
    assert not datasets_root(tmp_path).exists()


def test_e2e_non_finite_tampered_nan_rejected(fixtures, tmp_path):
    """A tampered Parquet carrying NaN is rejected by the verified reader:
    NaN is never silently converted to null and never admitted into the
    logical content."""
    _, mresult = materialize_once(fixtures, tmp_path)
    parquet = mresult.build_path / DATASET_PARQUET_FILENAME
    table = pq.read_table(parquet)
    values = table.column("sr").to_pylist()
    values[0] = float("nan")
    table = replace_column_preserving_schema(table, "sr", values)
    write_parquet_back(parquet, table)
    new_bytes = parquet.read_bytes()
    _rewrite_with_coordinated_records(mresult, parquet, new_bytes)
    with pytest.raises(DatasetArtifactValidationError) as exc_info:
        load_verified_dataset(mresult.build_path)
    assert "NaN" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 20. E2E_TIMEZONE_DST.
# ---------------------------------------------------------------------------


def test_e2e_timezone_equivalent_representations_same_identity(fixtures, tmp_path):
    """The same absolute instant expressed in UTC or New York produces the
    same sample key and the same dataset_id."""
    req_utc = request()
    req_ny = request(
        f_start=datetime(2026, 7, 1, 9, 30, tzinfo=NY_ZONE),
        f_close=datetime(2026, 7, 1, 9, 36, tzinfo=NY_ZONE),
        l_start=datetime(2026, 7, 1, 9, 36, tzinfo=NY_ZONE),
        l_close=datetime(2026, 7, 1, 9, 42, tzinfo=NY_ZONE),
    )
    assert req_utc.feature_window_close == req_ny.feature_window_close
    assert dataset_pkg.pit_sample_key(req_utc) == dataset_pkg.pit_sample_key(req_ny)
    base = orchestrate(fixtures, requests=[req_utc])
    ny = orchestrate(fixtures, requests=[req_ny])
    assert ny.dataset_id == base.dataset_id
    assert ny.rows == base.rows


def test_e2e_timezone_tz_env_no_effect(fixtures, tmp_path, monkeypatch):
    """Setting a process TZ environment variable never changes the built
    Dataset: no code path consults the local timezone."""
    base, base_m = materialize_once(fixtures, tmp_path)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    other_root = tmp_path / "tz-out"
    again = materialize_dataset_artifacts(
        orchestrate(fixtures, requests=[request()]),
        output_root=other_root, built_at=BUILT_AT,
    )
    assert again.dataset_id == base.dataset_id
    assert read_verified(again).rows == read_verified(base_m).rows


def test_e2e_timezone_utc_microsecond_output(fixtures, tmp_path):
    """The final Dataset timing columns are exact UTC microseconds."""
    result, mresult = materialize_once(fixtures, tmp_path)
    verified_build = read_verified(mresult)
    facts = row_by_name(verified_build.schema, verified_build.rows[0])
    assert facts["feature_window_close"] == utc(2026, 7, 1, 13, 36)
    assert facts["feature_window_close"].tzinfo is not None
    assert facts["feature_window_close"].utcoffset() == timedelta(0)
    assert facts["actual_label_end_time"] == utc(2026, 7, 1, 13, 38)
    assert result.identity_input.dataset_as_of is None


def test_e2e_timezone_naive_datetime_rejected(fixtures):
    """Naive datetimes fail closed at the PIT request contract."""
    with pytest.raises(PITAssemblyError):
        request(f_start=datetime(2026, 7, 1, 13, 30))
    with pytest.raises(PITAssemblyError):
        PITSampleRequest(
            code="US.MU", interval="1m", adjustment="NONE",
            requested_session="ALL", anchor_market_calendar_date=date(2026, 7, 1),
            feature_window_start=datetime(2026, 7, 1, 13, 30),
            feature_window_close=datetime(2026, 7, 1, 13, 36),
        )


def test_e2e_timezone_dst_spring_forward_boundary():
    """Spring-forward: the next local midnight after 2026-03-08 is
    2026-03-09T00:00 EDT == 04:00Z, not 05:00Z (a fixed +24h addition would
    produce 05:00Z)."""
    spec = chronological_spec(
        train_end=date(2026, 3, 8), validation_end=date(2026, 3, 9),
        test_end=date(2026, 3, 10),
    )
    sample = split_sample(
        "spring",
        close=datetime(2026, 3, 8, 9, 30, tzinfo=NY_ZONE),
        actual_end=utc(2026, 3, 9, 4, 30),
    )
    result = assign_chronological_splits([sample], spec)
    assignment = result.assignments[0]
    assert assignment.purge_boundary == utc(2026, 3, 9, 4, 0)
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.reason_code == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY


def test_e2e_timezone_dst_fall_back_boundary():
    """Fall-back: the next local midnight after 2026-11-01 is
    2026-11-02T00:00 EST == 05:00Z. An actual end at 04:30Z stays below the
    real 05:00Z boundary and is ASSIGNED; a fixed +24h (04:00Z) boundary
    would have purged it."""
    spec = chronological_spec(
        train_end=date(2026, 11, 1), validation_end=date(2026, 11, 2),
        test_end=date(2026, 11, 3),
    )
    sample = split_sample(
        "fall",
        close=datetime(2026, 11, 1, 9, 30, tzinfo=NY_ZONE),
        actual_end=utc(2026, 11, 2, 4, 30),
    )
    result = assign_chronological_splits([sample], spec)
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TRAIN
    assert assignment.purge_boundary is None
    # And the true 05:00Z boundary purges an end exactly at it, carrying the
    # DST-safe boundary as the purge_boundary fact.
    crossing = split_sample(
        "fall-cross",
        close=datetime(2026, 11, 1, 9, 30, tzinfo=NY_ZONE),
        actual_end=utc(2026, 11, 2, 5, 0),
    )
    result = assign_chronological_splits([crossing], spec)
    assert result.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert result.assignments[0].purge_boundary == utc(2026, 11, 2, 5, 0)


def test_e2e_timezone_split_uses_declared_local_date():
    """Nominal split assignment uses the declared boundary timezone's local
    date: 03:59Z on 2026-07-01 is still 2026-06-30 in New York (TRAIN),
    while 04:00Z is already 2026-07-01 (VALIDATION)."""
    spec = chronological_spec()
    before = split_sample(
        "before-midnight",
        close=utc(2026, 7, 1, 3, 59),
        actual_end=utc(2026, 7, 1, 3, 59, 59, 999999),
    )
    after = split_sample(
        "after-midnight",
        close=utc(2026, 7, 1, 4, 0),
        actual_end=utc(2026, 7, 1, 5, 0),
    )
    result = assign_chronological_splits([before, after], spec)
    by_key = {assignment.sample_key: assignment for assignment in result.assignments}
    assert by_key[sha("before-midnight")].final_split == SPLIT_TRAIN
    assert by_key[sha("after-midnight")].final_split == SPLIT_VALIDATION


def test_e2e_timezone_invalid_iana_fails_closed():
    """An invalid IANA timezone fails closed with no system-local fallback."""
    with pytest.raises(SplitValidationError):
        chronological_spec(boundary_timezone="Not/AZone")
