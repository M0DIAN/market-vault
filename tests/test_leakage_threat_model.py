"""Offline cross-contract leakage threat-model regression suite (v0.4.0
PR-9).

The eight stable leakage threats of the V0.4.0 threat model are tested as a
regression matrix across the implemented contracts: canonical materialization
and the verified reader, point-in-time sample assembly, Feature/Label spec
identity, chronological splits with actual-label-end purging, and the derived
dataset identity layer.

Every test is offline and deterministic: fixed dates, fixed run IDs, fixed
hashes, tmp_path-isolated files, no current time, no randomness, no mtime
dependence, no input-order dependence, no local-timezone dependence, no OpenD,
no network, no real market data, no repo-directory writes, no model training,
and no trading signals. Contracts are exercised through the public APIs;
minimal local fixtures build only the smallest Canonical / PIT / Split /
Identity scenarios each threat needs. Private test helpers are never imported
from other test modules.

Each threat has at least one positive control test and one defense test,
tracked by the fixed threat matrix below. The threat IDs are stable machine
identifiers used by tests and the contract documentation; they introduce no
production API.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_vault.canonical.bars import build_canonical_market_bars
from market_vault.canonical.materialization import (
    load_canonical_snapshot_inputs,
    materialize_canonical_market_bars,
)
from market_vault.canonical.models import (
    CanonicalConflictError,
    CanonicalRequestKey,
    CanonicalSnapshotInput,
)
from market_vault.canonical.reader import (
    CanonicalArtifactValidationError,
    load_verified_canonical_build,
)
from market_vault.dataset import (
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
    CanonicalBuildPin,
    ChronologicalSplitAssignment,
    ChronologicalSplitResult,
    ChronologicalSplitSample,
    ChronologicalSplitSpec,
    CompletionEntry,
    CompletionSummary,
    CrossTradingDayPolicy,
    DatasetError,
    DatasetField,
    DatasetIdentityInput,
    DatasetScope,
    DatasetSchema,
    FeatureSpec,
    GapReference,
    ImplementationPin,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITAssemblyError,
    PITDiagnostics,
    PITObservationWindow,
    PITSample,
    PITSampleRequest,
    SourceSnapshotPin,
    SpecParameter,
    SpecPin,
    SpecValidationError,
    SpecVersionRequirements,
    SplitValidationError,
    assign_chronological_splits,
    assemble_point_in_time_samples,
    chronological_split_result_id,
    chronological_split_spec_content_id,
    chronological_split_spec_pin,
    dataset_id,
    dataset_schema_id,
    feature_label_spec_content_id,
    feature_label_spec_pin,
    logical_dataset_content_id,
    parse_feature_spec,
    parse_label_spec,
    pit_sample_key,
    pit_sample_version_id,
    split_assignment_schema,
    split_assignment_schema_id,
)
from market_vault.dataset.split_models import (
    _assignment_rows,
    _derive_diagnostics,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore
from market_vault.storage.catalog import CompleteSnapshotRef

UTC = timezone.utc
NY = "America/New_York"
NY_ZONE = ZoneInfo(NY)
SHA_HEX = re.compile(r"^[0-9a-f]{64}$")

# ---------------------------------------------------------------------------
# 1. Fixed threat IDs and the coverage matrix.
# ---------------------------------------------------------------------------

THREAT_IDS = (
    "LEAKAGE_FUTURE_BAR",
    "LEAKAGE_ARCHIVE_TIME",
    "LEAKAGE_LABEL_CROSS_SPLIT",
    "LEAKAGE_ADJUSTMENT_CORPORATE_ACTION",
    "LEAKAGE_SNAPSHOT_SUBSTITUTION",
    "LEAKAGE_SPEC_DRIFT",
    "LEAKAGE_COMPLETION_AMBIGUITY",
    "LEAKAGE_TIMEZONE_MISATTRIBUTION",
)

#: Every threat must keep at least one positive control and one defense test;
#: the matrix guard below fails the suite if a whole category is ever deleted.
THREAT_COVERAGE = {
    "LEAKAGE_FUTURE_BAR": {
        "control": [
            "test_future_bar_market_available_before_close_selected",
            "test_future_bar_market_available_equal_close_selected",
            "test_future_bar_label_rows_never_enter_feature_role",
        ],
        "defense": [
            "test_future_bar_market_available_after_close_excluded_and_counted",
            "test_future_bar_event_time_equal_close_excluded_by_half_open_window",
            "test_future_bar_every_feature_association_row_is_pit_visible",
            "test_future_bar_market_clock_counted_before_archive_clock",
            "test_future_bar_sample_key_stable_but_version_tracks_physical_rows",
            "test_future_bar_same_row_version_never_in_both_roles",
        ],
    },
    "LEAKAGE_ARCHIVE_TIME": {
        "control": [
            "test_archive_time_no_cutoff_without_dataset_as_of",
            "test_archive_time_before_cutoff_selected",
            "test_archive_time_equal_cutoff_selected",
        ],
        "defense": [
            "test_archive_time_after_cutoff_excluded_and_counted",
            "test_archive_time_every_selected_row_satisfies_cutoff",
            "test_archive_time_as_of_binds_version_not_key_and_rejects_naive",
            "test_archive_time_gap_known_only_when_boundary_rows_archived",
            "test_archive_time_late_rows_cannot_jump_cutoff_by_input_order",
        ],
    },
    "LEAKAGE_LABEL_CROSS_SPLIT": {
        "control": [
            "test_label_cross_split_incomplete_excluded_by_default",
            "test_label_cross_split_train_below_boundary_assigned",
            "test_label_cross_split_validation_boundary_assigned",
            "test_label_cross_split_test_assigned_without_fourth_purge",
        ],
        "defense": [
            "test_label_cross_split_cross_day_candidate_fails_closed",
            "test_label_cross_split_no_allow_cross_day_parameter",
            "test_label_cross_split_incomplete_with_partial_end_still_excluded",
            "test_label_cross_split_train_at_boundary_purged",
            "test_label_cross_split_validation_crossing_purged",
            "test_label_cross_split_purge_uses_only_actual_label_end",
            "test_label_cross_split_same_close_different_end_different_outcome",
            "test_label_cross_split_forged_assignment_fails_closed",
        ],
    },
    "LEAKAGE_ADJUSTMENT_CORPORATE_ACTION": {
        "control": [
            "test_adjustment_policy_none_accepted_and_normalized",
        ],
        "defense": [
            "test_adjustment_policy_adjusted_modes_fail_closed",
            "test_adjustment_policy_no_temporary_override_parameters",
            "test_adjustment_policy_no_corporate_action_asof_implementation",
            "test_adjustment_policy_scope_adjustment_is_identity_bearing",
            "test_adjustment_policy_request_mismatch_produces_no_rows",
            "test_adjustment_policy_specs_carry_no_adjustment_field",
        ],
    },
    "LEAKAGE_SNAPSHOT_SUBSTITUTION": {
        "control": [
            "test_snapshot_substitution_verified_build_reads_cleanly",
            "test_snapshot_substitution_build_input_order_irrelevant",
            "test_snapshot_substitution_relocated_build_keeps_identity",
        ],
        "defense": [
            "test_snapshot_substitution_bars_byte_tamper_rejected",
            "test_snapshot_substitution_manifest_identity_tamper_rejected",
            "test_snapshot_substitution_manifest_provenance_tamper_rejected",
            "test_snapshot_substitution_conflicting_rows_fail_closed",
            "test_snapshot_substitution_source_pin_change_changes_dataset_id",
            "test_snapshot_substitution_uncovered_row_version_fails_closed",
            "test_snapshot_substitution_bad_gap_reference_fails_closed",
            "test_snapshot_substitution_renamed_build_dir_rejected",
        ],
    },
    "LEAKAGE_SPEC_DRIFT": {
        "control": [
            "test_spec_drift_equivalent_yaml_same_identity",
        ],
        "defense": [
            "test_spec_drift_semantic_change_changes_identity",
            "test_spec_drift_duplicate_pin_key_fails_closed",
            "test_spec_drift_pins_reject_wrong_containers",
            "test_spec_drift_implementation_change_changes_dataset_id",
            "test_spec_drift_transform_ref_is_never_executed",
            "test_spec_drift_unknown_schema_version_fails_closed",
        ],
    },
    "LEAKAGE_COMPLETION_AMBIGUITY": {
        "control": [
            "test_completion_ambiguity_complete_snapshot_produces_rows",
            "test_completion_ambiguity_observed_rows_only_with_gap",
        ],
        "defense": [
            "test_completion_ambiguity_quality_fail_snapshot_excluded",
            "test_completion_ambiguity_missing_key_produces_empty_build",
            "test_completion_ambiguity_gap_is_sidecar_not_placeholder_row",
            "test_completion_ambiguity_no_known_gap_never_implies_complete",
            "test_completion_ambiguity_pit_carries_no_label_status",
            "test_completion_ambiguity_split_requires_explicit_label_facts",
            "test_completion_ambiguity_explicit_incomplete_excluded",
            "test_completion_ambiguity_completion_and_gap_semantics_identity_bearing",
            "test_completion_ambiguity_forged_counts_fail_closed",
        ],
    },
    "LEAKAGE_TIMEZONE_MISATTRIBUTION": {
        "control": [
            "test_timezone_equivalent_instants_identical_identities",
            "test_timezone_equivalent_as_of_same_version_id",
        ],
        "defense": [
            "test_timezone_naive_instants_fail_closed",
            "test_timezone_split_uses_declared_local_date_not_utc_date",
            "test_timezone_invalid_iana_fails_closed",
            "test_timezone_no_system_local_fallback",
            "test_timezone_dst_spring_forward_boundary_local_calendar",
            "test_timezone_dst_fall_back_boundary_local_calendar",
            "test_timezone_microsecond_truncation_is_consistent",
        ],
    },
}


def test_threat_matrix_keeps_control_and_defense_per_threat():
    for threat in THREAT_IDS:
        coverage = THREAT_COVERAGE[threat]
        assert coverage["control"], f"{threat}: no positive control test"
        assert coverage["defense"], f"{threat}: no defense test"
        for name in coverage["control"] + coverage["defense"]:
            assert name in globals(), f"{threat}: missing test function {name}"


# ---------------------------------------------------------------------------
# 2. Minimal deterministic synthetic-storage and Canonical fixtures.
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
    frame = pd.DataFrame({"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]})
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
    close: float = 100.5,
    run_finished_at: datetime | None = None,
    quality: str = "PASS",
) -> None:
    store = ParquetStore(cfg)
    catalog = Catalog(cfg)
    raw = pd.DataFrame(
        {
            "code": [code] * len(time_keys),
            "name": [code] * len(time_keys),
            "time_key": time_keys,
            "open": [100.0] * len(time_keys),
            "high": [101.0] * len(time_keys),
            "low": [99.0] * len(time_keys),
            "close": [close] * len(time_keys),
            "volume": [100] * len(time_keys),
        }
    )
    curated = normalize_bars(
        raw, requested_trade_date=trade_date, interval="1m",
        requested_session="ALL", adjustment="NONE", source=cfg.source,
        source_schema_version=cfg.source_schema_version, run_id=run_id,
    )
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = run_finished_at or datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", quality)])


def output_root(cfg: Settings):
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE",
    source_schema_version="10.9",
)


def materialize(cfg: Settings, *, symbols=None, trade_dates=None, root=None,
                created_at=None, request_key=DEFAULT_KEY):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=request_key,
        output_root=root or output_root(cfg),
        created_at=created_at or datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def verified(build_result):
    return load_verified_canonical_build(build_result.build_path)


def make_primary_build(tmp_path):
    """One canonical build: US.MU 2026-07-01 rows 09:30..09:33 NY
    (event times 13:30..13:33 UTC), archived 14:00 UTC."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    return cfg, verified(materialize(cfg))


def make_two_run_builds(tmp_path):
    """The same bars from two runs with different archive instants:
    run-a archived 14:00 UTC, run-a2 archived 15:00 UTC."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    build_a = materialize(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a2",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 15, 0, tzinfo=UTC))
    build_a2 = materialize(cfg)
    return cfg, verified(build_a), verified(build_a2)


def make_gap_build(tmp_path):
    """Build with one internal gap: rows 09:30 and 09:32 (09:31 missing)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1)
                   + minute_keys("2026-07-01 09:32:00", 1),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    return cfg, verified(materialize(cfg))


def make_multi_day_builds(tmp_path):
    """US.MU 2026-07-01 (run-a) and US.NVDA 2026-07-02 (run-d)."""
    cfg = settings(tmp_path)
    calendar(cfg)
    calendar(cfg, trade_date=date(2026, 7, 2))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 4),
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    build_a = materialize(cfg)
    write_snapshot(cfg, code="US.NVDA", trade_date=date(2026, 7, 2), run_id="run-d",
                   time_keys=minute_keys("2026-07-02 09:30:00", 2),
                   run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC))
    build_d = materialize(cfg, symbols=["US.NVDA"], trade_dates=[date(2026, 7, 2)])
    return cfg, verified(build_a), verified(build_d)


def _run_input(cfg: Settings, run_id: str) -> CanonicalSnapshotInput:
    """Wrap one specific run's physical curated file as a builder input.

    The V0.3 latest-complete selector returns only the newest run per key, so
    a two-run conflict must be constructed from each run's own file, mirroring
    the canonical builder tests.
    """
    root = cfg.data_root / "curated" / f"source={cfg.source}" / "dataset=market_bars"
    for path in sorted(root.rglob("*.parquet")):
        frame = pd.read_parquet(path)
        if run_id not in set(frame["ingestion_run_id"]):
            continue
        trade_date = frame["requested_trade_date"].iloc[0]
        if isinstance(trade_date, pd.Timestamp):
            trade_date = trade_date.date()
        with Catalog(cfg).connect() as con:
            row = con.execute(
                "SELECT finished_at FROM ingestion_runs WHERE run_id = ?",
                [run_id],
            ).fetchone()
        finished = pd.Timestamp(row[0]) if row and row[0] is not None else None
        ref = CompleteSnapshotRef(
            code=str(frame["code"].iloc[0]),
            requested_trade_date=trade_date,
            ingestion_run_id=run_id,
            snapshot_file=path.relative_to(cfg.data_root).as_posix(),
            snapshot_ingested_at=None,
            run_finished_at=finished,
            eligible_row_count=len(frame),
        )
        return CanonicalSnapshotInput(
            snapshot=ref,
            rows=frame,
            physical_snapshot_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            request_key=DEFAULT_KEY,
        )
    raise AssertionError(f"no physical file found for run {run_id}")


def make_conflict_inputs(tmp_path):
    """Two audited complete snapshots with the same bars but different close
    values: the canonical builder must fail closed instead of choosing a
    winner."""
    cfg = settings(tmp_path)
    calendar(cfg)
    keys = minute_keys("2026-07-01 09:30:00", 4)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=keys, close=100.5,
                   run_finished_at=datetime(2026, 7, 1, 14, 0, tzinfo=UTC))
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a2",
                   time_keys=keys, close=101.5,
                   run_finished_at=datetime(2026, 7, 1, 15, 0, tzinfo=UTC))
    return cfg, (_run_input(cfg, "run-a"), _run_input(cfg, "run-a2"))


def pit_request(**overrides) -> PITSampleRequest:
    values = dict(
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor=date(2026, 7, 1),
        feature_start=utc(2026, 7, 1, 13, 30),
        feature_close=utc(2026, 7, 1, 13, 33),
        label_start=None,
        label_close=None,
    )
    values.update(overrides)
    return PITSampleRequest(
        code=values["code"],
        interval=values["interval"],
        adjustment=values["adjustment"],
        requested_session=values["requested_session"],
        anchor_market_calendar_date=values["anchor"],
        feature_window_start=values["feature_start"],
        feature_window_close=values["feature_close"],
        label_window_start=values["label_start"],
        label_window_close=values["label_close"],
    )


def feature_spec() -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version="market-vault-feature-spec-v1",
        name="close_return",
        version="v1",
        output=DatasetField("close_return", "float64", True),
        input_canonical_fields=("close",),
        transform_ref="market_vault.features.transforms:close_return",
        parameters=(SpecParameter("lookback", 5),),
        requirements=SpecVersionRequirements(
            ("market-bars-canonical-schema-v1",), ("10.9",)
        ),
    )


def label_spec() -> LabelSpec:
    return LabelSpec(
        spec_schema_version="market-vault-label-spec-v1",
        name="next_day_ret",
        version="v1",
        output=DatasetField("next_day_ret", "float64", True),
        input_canonical_fields=("close",),
        transform_ref="market_vault.labels.transforms:next_day_ret",
        parameters=(),
        requirements=SpecVersionRequirements(
            ("market-bars-canonical-schema-v1",), ("10.9",)
        ),
        observation_window=LabelObservationWindow("TRADING_DAYS", 0, 1),
        horizon=LabelHorizon("TRADING_DAYS", 1),
        alignment_rule="ALIGN_CLOSE",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(True, "END_OF_TRADING_DAY"),
    )


def split_spec(**overrides) -> ChronologicalSplitSpec:
    values = dict(
        spec_schema_version=CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
        name="leakage_split",
        version="v1",
        boundary_timezone="America/New_York",
        train_end_date=date(2026, 6, 30),
        validation_end_date=date(2026, 7, 31),
        test_end_date=date(2026, 8, 31),
        assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        purge_rule=SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
        incomplete_label_policy=SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
        out_of_range_policy=SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    )
    values.update(overrides)
    return ChronologicalSplitSpec(**values)


def split_sample(key_text: str, *, close=None, status=LABEL_STATUS_COMPLETE,
                 actual_end=None, version_text=None) -> ChronologicalSplitSample:
    """Split fact sample; COMPLETE defaults its actual end to close + 1h."""
    close = close if close is not None else datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE)
    if actual_end is None and status == LABEL_STATUS_COMPLETE:
        actual_end = close + pd.Timedelta(hours=1)
    return ChronologicalSplitSample(
        sample_key=sha(key_text),
        sample_version_id=sha(version_text if version_text is not None else key_text + "#v1"),
        feature_window_close=close,
        label_status=status,
        actual_label_end_time=actual_end,
    )


def identity_input(*, split_pin=None, feature_pins=(), label_pins=(),
                   implementations=(), schema=None, rows=None, completion=None,
                   gap_refs=(), builds=(), row_versions=(),
                   adjustment="NONE") -> DatasetIdentityInput:
    schema = schema or DatasetSchema((DatasetField("x", "int64", False),))
    rows = rows if rows is not None else []
    scope = DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        adjustment=adjustment,
        interval="1m",
        requested_session="ALL",
    )
    return DatasetIdentityInput(
        dataset_kind="market-samples-dataset",
        scope=scope,
        dataset_as_of=None,
        schema=schema,
        dataset_schema_id=dataset_schema_id(schema),
        logical_dataset_content_id=logical_dataset_content_id(schema, rows),
        canonical_builds=builds,
        canonical_row_version_ids=row_versions,
        feature_specs=feature_pins,
        label_specs=label_pins,
        split_spec=split_pin,
        implementations=implementations,
        completion=completion or CompletionSummary(0, 0, 0, ()),
        gap_references=gap_refs,
    )


def feature_yaml(**overrides) -> str:
    text = """\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: close_return
version: v1
output:
  name: close_return
  logical_type: float64
  nullable: true
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.features.transforms:close_return
parameters:
  lookback: 5
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
"""
    for key, value in overrides.items():
        text = text.replace(key, value)
    return text


def label_yaml(**overrides) -> str:
    text = """\
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: next_day_ret
version: v1
output:
  name: next_day_ret
  logical_type: float64
  nullable: true
inputs:
  canonical_fields:
    - close
transform:
  ref: market_vault.labels.transforms:next_day_ret
parameters: {}
requirements:
  canonical_schema_versions:
    - market-bars-canonical-schema-v1
  source_schema_versions:
    - "10.9"
observation_window:
  unit: TRADING_DAYS
  start_offset: 0
  end_offset: 1
horizon:
  unit: TRADING_DAYS
  value: 1
alignment_rule: ALIGN_CLOSE
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: true
  boundary_rule: END_OF_TRADING_DAY
"""
    for key, value in overrides.items():
        text = text.replace(key, value)
    return text


# ---------------------------------------------------------------------------
# 3. LEAKAGE_FUTURE_BAR: market clock and window boundaries.
# ---------------------------------------------------------------------------


def test_future_bar_market_available_before_close_selected(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 32))
    result = assemble_point_in_time_samples([build], [request])
    sample = result.samples[0]
    # Row 13:30 (market_available_at 13:31 < 13:32) is selectable.
    assert sample.diagnostics.feature_selected_count == 2
    assert sample.diagnostics.feature_market_future_excluded_count == 0
    selected_events = {
        row["event_time"]
        for row in result.association_rows
        if row["role"] == "FEATURE"
    }
    assert utc(2026, 7, 1, 13, 30) in selected_events


def test_future_bar_market_available_equal_close_selected(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 31))
    result = assemble_point_in_time_samples([build], [request])
    sample = result.samples[0]
    # Row 13:30 has market_available_at 13:31 == close: allowed.
    assert sample.diagnostics.feature_selected_count == 1
    selected_events = {
        row["event_time"]
        for row in result.association_rows
        if row["role"] == "FEATURE"
    }
    assert utc(2026, 7, 1, 13, 30) in selected_events


def test_future_bar_market_available_after_close_excluded_and_counted(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 31, 30))
    result = assemble_point_in_time_samples([build], [request])
    sample = result.samples[0]
    # Row 13:31 has market_available_at 13:32 > close: excluded and counted.
    assert sample.diagnostics.feature_candidate_count == 2
    assert sample.diagnostics.feature_selected_count == 1
    assert sample.diagnostics.feature_market_future_excluded_count == 1
    excluded_version = build.bars[1].canonical_row_version_id
    feature_versions = {
        row["canonical_row_version_id"]
        for row in result.association_rows
        if row["role"] == "FEATURE"
    }
    assert excluded_version not in feature_versions


def test_future_bar_event_time_equal_close_excluded_by_half_open_window(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 31))
    result = assemble_point_in_time_samples([build], [request])
    sample = result.samples[0]
    # The 13:31 row has event_time == close: excluded by the half-open
    # window before any clock check, so it is not even a candidate and is
    # never counted as a market exclusion.
    assert sample.diagnostics.feature_candidate_count == 1
    assert sample.diagnostics.feature_market_future_excluded_count == 0
    equal_close_version = build.bars[1].canonical_row_version_id
    feature_versions = {
        row["canonical_row_version_id"]
        for row in result.association_rows
        if row["role"] == "FEATURE"
    }
    assert equal_close_version not in feature_versions


def test_future_bar_every_feature_association_row_is_pit_visible(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    result = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 14, 0)
    )
    for row in result.association_rows:
        assert row["archive_available_at"] <= utc(2026, 7, 1, 14, 0)
        if row["role"] == "FEATURE":
            assert row["event_time"] < request.feature_window_close
            assert row["market_available_at"] <= request.feature_window_close


def test_future_bar_label_rows_never_enter_feature_role(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(
        feature_close=utc(2026, 7, 1, 13, 33),
        label_start=utc(2026, 7, 1, 13, 33),
        label_close=utc(2026, 7, 1, 13, 35),
    )
    result = assemble_point_in_time_samples([build], [request])
    feature_versions = {
        row["canonical_row_version_id"]
        for row in result.association_rows
        if row["role"] == "FEATURE"
    }
    label_versions = {
        row["canonical_row_version_id"]
        for row in result.association_rows
        if row["role"] == "LABEL"
    }
    # Row 13:33 (after the feature close) appears only under the LABEL role.
    assert label_versions
    assert feature_versions.isdisjoint(label_versions)
    later_row_version = build.bars[3].canonical_row_version_id
    assert later_row_version in label_versions
    assert later_row_version not in feature_versions


def test_future_bar_market_clock_counted_before_archive_clock(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 31, 30))
    # Row 13:31 is both after the market close and after the archive cutoff;
    # it must be counted once as a market-clock exclusion only.
    result = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 13, 59, 59, 999999)
    )
    sample = result.samples[0]
    assert sample.diagnostics.feature_market_future_excluded_count == 1
    assert sample.diagnostics.feature_archive_future_excluded_count == 1
    # Row 13:30 passes the market clock and is then archive-excluded.
    assert sample.diagnostics.feature_selected_count == 0


def test_future_bar_sample_key_stable_but_version_tracks_physical_rows(tmp_path):
    cfg, first, second = make_two_run_builds(tmp_path)
    request = pit_request()
    result_a = assemble_point_in_time_samples([first], [request])
    result_a2 = assemble_point_in_time_samples([second], [request])
    # The logical sample definition never changes with the physical rows.
    assert result_a.samples[0].sample_key == result_a2.samples[0].sample_key
    # The physical binding must change.
    assert result_a.samples[0].sample_version_id != result_a2.samples[0].sample_version_id
    assert result_a.association_content_id != result_a2.association_content_id


def test_future_bar_same_row_version_never_in_both_roles():
    # Identity-level contract: a canonical row version appearing in both the
    # feature and label lists of one sample fails closed.
    version = sha("row-version")
    with pytest.raises(PITAssemblyError):
        pit_sample_version_id(
            sample_key=sha("sample"),
            dataset_as_of=None,
            feature_canonical_row_version_ids=(version,),
            label_canonical_row_version_ids=(version,),
            considered_canonical_build_ids=(sha("build"),),
        )


# ---------------------------------------------------------------------------
# 4. LEAKAGE_ARCHIVE_TIME: archive-as-of filtering.
# ---------------------------------------------------------------------------


def test_archive_time_no_cutoff_without_dataset_as_of(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    result = assemble_point_in_time_samples([build], [request])
    sample = result.samples[0]
    # Without dataset_as_of no archive cutoff is applied.
    assert sample.diagnostics.feature_archive_future_excluded_count == 0
    assert sample.diagnostics.feature_selected_count == 3


def test_archive_time_before_cutoff_selected(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    result = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 14, 0, 0, 1)
    )
    assert result.samples[0].diagnostics.feature_selected_count == 3


def test_archive_time_equal_cutoff_selected(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    result = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 14, 0)
    )
    assert result.samples[0].diagnostics.feature_selected_count == 3


def test_archive_time_after_cutoff_excluded_and_counted(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    result = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 13, 59, 59, 999999)
    )
    sample = result.samples[0]
    # Every row passed the market clock and is then archive-excluded.
    assert sample.diagnostics.feature_archive_future_excluded_count == 3
    assert sample.diagnostics.feature_selected_count == 0


def test_archive_time_every_selected_row_satisfies_cutoff(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    cutoff = utc(2026, 7, 1, 14, 0)
    result = assemble_point_in_time_samples([build], [request], dataset_as_of=cutoff)
    for row in result.association_rows:
        assert row["archive_available_at"] <= cutoff


def test_archive_time_as_of_binds_version_not_key_and_rejects_naive(tmp_path):
    _, build = make_primary_build(tmp_path)
    request = pit_request()
    plain = assemble_point_in_time_samples([build], [request])
    cut = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 14, 0)
    )
    # dataset_as_of never enters sample_key but binds sample_version_id.
    assert plain.samples[0].sample_key == cut.samples[0].sample_key
    assert plain.samples[0].sample_version_id != cut.samples[0].sample_version_id
    # Equivalent timezone representations produce the same physical binding.
    equivalent = assemble_point_in_time_samples(
        [build], [request],
        dataset_as_of=datetime(2026, 7, 1, 10, 0, tzinfo=NY_ZONE),
    )
    assert equivalent.samples[0].sample_version_id == cut.samples[0].sample_version_id
    # Naive dataset_as_of fails closed.
    with pytest.raises(PITAssemblyError):
        assemble_point_in_time_samples(
            [build], [request], dataset_as_of=datetime(2026, 7, 1, 14, 0)
        )


def test_archive_time_gap_known_only_when_boundary_rows_archived(tmp_path):
    _, build = make_gap_build(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    after = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 14, 0)
    )
    assert after.samples[0].diagnostics.known_feature_gap_ids
    before = assemble_point_in_time_samples(
        [build], [request], dataset_as_of=utc(2026, 7, 1, 13, 59, 59, 999999)
    )
    # The next boundary bar is not archived yet, so the gap is not known.
    assert before.samples[0].diagnostics.known_feature_gap_ids == ()


def test_archive_time_late_rows_cannot_jump_cutoff_by_input_order(tmp_path):
    cfg, first, second = make_two_run_builds(tmp_path)
    request = pit_request(feature_close=utc(2026, 7, 1, 13, 33))
    cutoff = utc(2026, 7, 1, 14, 30)
    # The same bars from two runs share canonical_bar_key but differ in row
    # version: assembling both fails closed in either input order instead of
    # silently choosing the "newest" or last-archived row.
    with pytest.raises(PITAssemblyError):
        assemble_point_in_time_samples([first, second], [request], dataset_as_of=cutoff)
    with pytest.raises(PITAssemblyError):
        assemble_point_in_time_samples([second, first], [request], dataset_as_of=cutoff)
    # The later-archived run's rows never pass the cutoff on their own: they
    # are archive-excluded and counted, never admitted by an input-order or
    # archive-order trick.
    late = assemble_point_in_time_samples([second], [request], dataset_as_of=cutoff)
    assert late.samples[0].diagnostics.feature_archive_future_excluded_count == 3
    assert late.samples[0].diagnostics.feature_selected_count == 0


# ---------------------------------------------------------------------------
# 5. LEAKAGE_LABEL_CROSS_SPLIT: label windows and split boundaries.
# ---------------------------------------------------------------------------

TRAIN_BOUNDARY_UTC = utc(2026, 7, 1, 4, 0)
VALIDATION_BOUNDARY_UTC = utc(2026, 8, 1, 4, 0)


def test_label_cross_split_cross_day_candidate_fails_closed(tmp_path):
    cfg, build_a, build_d = make_multi_day_builds(tmp_path)
    # US.NVDA rows exist only on 2026-07-02; a request anchored to
    # 2026-07-01 with a label window reaching into 07-02 must fail closed:
    # the label candidate's market_calendar_date differs from the anchor and
    # there is no hidden override.
    request = pit_request(
        code="US.NVDA",
        anchor=date(2026, 7, 1),
        feature_start=utc(2026, 7, 1, 13, 0),
        feature_close=utc(2026, 7, 1, 13, 2),
        label_start=utc(2026, 7, 1, 13, 2),
        label_close=utc(2026, 7, 2, 13, 32),
    )
    with pytest.raises(PITAssemblyError):
        assemble_point_in_time_samples([build_a, build_d], [request])


def test_label_cross_split_no_allow_cross_day_parameter():
    names = {f.name for f in fields(PITSampleRequest)}
    for forbidden in ("allow_cross_day", "allow_cross_trading_day", "cross_day"):
        assert forbidden not in names


def test_label_cross_split_incomplete_excluded_by_default():
    result = assign_chronological_splits(
        [
            split_sample(
                "incomplete",
                close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
                status=LABEL_STATUS_INCOMPLETE,
                actual_end=None,
            )
        ],
        split_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL
    assert assignment.final_split is None


def test_label_cross_split_incomplete_with_partial_end_still_excluded():
    result = assign_chronological_splits(
        [
            split_sample(
                "partial",
                close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
                status=LABEL_STATUS_INCOMPLETE,
                actual_end=utc(2026, 7, 2, 0, 0),
            )
        ],
        split_spec(),
    )
    assignment = result.assignments[0]
    # Even a partial actual label end never turns INCOMPLETE into PURGED or
    # ASSIGNED; the v1 policy excludes it.
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL
    assert assignment.purge_boundary is None


def test_label_cross_split_train_below_boundary_assigned():
    result = assign_chronological_splits(
        [
            split_sample(
                "train-ok",
                close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
                actual_end=TRAIN_BOUNDARY_UTC - pd.Timedelta(microseconds=1),
            )
        ],
        split_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TRAIN


def test_label_cross_split_train_at_boundary_purged():
    result = assign_chronological_splits(
        [
            split_sample(
                "train-boundary",
                close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
                actual_end=TRAIN_BOUNDARY_UTC,
            )
        ],
        split_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.reason_code == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
    assert assignment.purge_boundary == TRAIN_BOUNDARY_UTC


def test_label_cross_split_validation_boundary_assigned():
    result = assign_chronological_splits(
        [
            split_sample(
                "val-ok",
                close=datetime(2026, 7, 31, 16, 0, tzinfo=NY_ZONE),
                actual_end=VALIDATION_BOUNDARY_UTC - pd.Timedelta(microseconds=1),
            )
        ],
        split_spec(),
    )
    assert result.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED
    assert result.assignments[0].final_split == SPLIT_VALIDATION


def test_label_cross_split_validation_crossing_purged():
    result = assign_chronological_splits(
        [
            split_sample(
                "val-cross",
                close=datetime(2026, 7, 31, 16, 0, tzinfo=NY_ZONE),
                actual_end=VALIDATION_BOUNDARY_UTC,
            )
        ],
        split_spec(),
    )
    assignment = result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.reason_code == REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
    assert assignment.purge_boundary == VALIDATION_BOUNDARY_UTC


def test_label_cross_split_test_assigned_without_fourth_purge():
    result = assign_chronological_splits(
        [
            split_sample(
                "test",
                close=datetime(2026, 8, 31, 16, 0, tzinfo=NY_ZONE),
                actual_end=utc(2026, 9, 30, 0, 0),
            )
        ],
        split_spec(),
    )
    assignment = result.assignments[0]
    # TEST is never purged for an actual label end past test_end_date: there
    # is no fourth split.
    assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED
    assert assignment.final_split == SPLIT_TEST


def test_label_cross_split_purge_uses_only_actual_label_end():
    # The split sample and spec carry no nominal horizon, no fixed purge
    # length, no embargo, and no label-window-close substitute.
    sample_names = {f.name for f in fields(ChronologicalSplitSample)}
    spec_names = {f.name for f in fields(ChronologicalSplitSpec)}
    for forbidden in ("horizon", "label_window_close", "purge_minutes",
                      "purge_bars", "embargo", "purge_length"):
        assert forbidden not in sample_names
        assert forbidden not in spec_names


def test_label_cross_split_same_close_different_end_different_outcome():
    close = datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE)
    result = assign_chronological_splits(
        [
            split_sample("kept", close=close, actual_end=TRAIN_BOUNDARY_UTC - pd.Timedelta(microseconds=1)),
            split_sample("purged", close=close, actual_end=TRAIN_BOUNDARY_UTC),
        ],
        split_spec(),
    )
    by_key = {a.sample_key: a for a in result.assignments}
    assert by_key[sha("kept")].assignment_status == SPLIT_STATUS_ASSIGNED
    assert by_key[sha("purged")].assignment_status == SPLIT_STATUS_PURGED
    assert by_key[sha("kept")].feature_window_close_date == by_key[sha("purged")].feature_window_close_date


def test_label_cross_split_forged_assignment_fails_closed():
    # A hand-built assignment with a wrong purge state still fails closed
    # even when every identity, row, and diagnostic count is recomputed.
    spec = split_spec()
    sample = split_sample("s", actual_end=TRAIN_BOUNDARY_UTC - pd.Timedelta(microseconds=1))
    base = assign_chronological_splits([sample], spec)
    forged = replace(
        base.assignments[0],
        assignment_status=SPLIT_STATUS_PURGED,
        final_split=None,
        reason_code=REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
        purge_boundary=TRAIN_BOUNDARY_UTC,
    )
    rows = _assignment_rows((forged,))
    pin = chronological_split_spec_pin(spec)
    schema_id = split_assignment_schema_id()
    content_id = logical_dataset_content_id(split_assignment_schema(), rows)
    with pytest.raises(SplitValidationError):
        ChronologicalSplitResult(
            split_spec=spec,
            split_spec_pin=pin,
            splitter_version=CHRONOLOGICAL_SPLITTER_VERSION,
            assignments=(forged,),
            assignment_schema=split_assignment_schema(),
            assignment_rows=rows,
            assignment_schema_id=schema_id,
            assignment_content_id=content_id,
            split_result_id=chronological_split_result_id(
                splitter_version=CHRONOLOGICAL_SPLITTER_VERSION,
                split_spec_content_id=pin.content_sha256,
                assignment_schema_version=SPLIT_ASSIGNMENT_SCHEMA_VERSION,
                assignment_schema_id=schema_id,
                assignment_content_id=content_id,
                sample_count=1,
            ),
            diagnostics=_derive_diagnostics((forged,)),
        )


# ---------------------------------------------------------------------------
# 6. LEAKAGE_ADJUSTMENT_CORPORATE_ACTION: the fail-closed NONE policy.
# ---------------------------------------------------------------------------


def test_adjustment_policy_none_accepted_and_normalized():
    request = pit_request(adjustment=" none ")
    assert request.adjustment == "NONE"
    assert pit_request(adjustment="NONE").adjustment == "NONE"


@pytest.mark.parametrize("mode", ["QFQ", "HFQ", "FORWARD", "BACKWARD", "SPLIT_ADJUSTED"])
def test_adjustment_policy_adjusted_modes_fail_closed(mode):
    with pytest.raises(PITAssemblyError):
        pit_request(adjustment=mode)


def test_adjustment_policy_no_temporary_override_parameters():
    names = {f.name for f in fields(PITSampleRequest)}
    for forbidden in ("allow_adjusted", "ignore_adjustment_policy",
                      "unsafe_adjusted_override"):
        assert forbidden not in names


def test_adjustment_policy_no_corporate_action_asof_implementation():
    names = {f.name for f in fields(PITSampleRequest)}
    for forbidden in ("corporate_action_asof", "adjustment_asof_policy"):
        assert forbidden not in names


def test_adjustment_policy_scope_adjustment_is_identity_bearing():
    base = dataset_id(identity_input(adjustment="NONE"))
    adjusted = dataset_id(identity_input(adjustment="QFQ"))
    # Different adjustment scope values can never collide in dataset_id.
    assert adjusted != base


def test_adjustment_policy_request_mismatch_produces_no_rows(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    result = materialize(
        cfg,
        request_key=CanonicalRequestKey(
            interval="1m", requested_session="ALL", adjustment="QFQ",
            source_schema_version="10.9",
        ),
    )
    # The NONE snapshot never matches a QFQ request: EMPTY, never a wrong row.
    assert result.status == "EMPTY"
    assert result.row_count == 0


def test_adjustment_policy_specs_carry_no_adjustment_field():
    for model in (FeatureSpec, LabelSpec, ChronologicalSplitSpec):
        names = {f.name for f in fields(model)}
        assert "adjustment" not in names


# ---------------------------------------------------------------------------
# 7. LEAKAGE_SNAPSHOT_SUBSTITUTION: physical sources and provenance pins.
# ---------------------------------------------------------------------------


def _tamper_manifest(build_result, mutate) -> None:
    manifest_path = build_result.build_path / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(payload)
    manifest_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def test_snapshot_substitution_verified_build_reads_cleanly(tmp_path):
    _, build = make_primary_build(tmp_path)
    assert build.status == "COMPLETE"
    assert len(build.bars) == 4
    assert build.canonical_row_version_ids == tuple(
        sorted(bar.canonical_row_version_id for bar in build.bars)
    )


def test_snapshot_substitution_bars_byte_tamper_rejected(tmp_path):
    _, build = make_primary_build(tmp_path)
    bar_file = next(build.build_path.rglob("bars/**/*.parquet"))
    # Flip one byte in place so the byte size stays identical: the reader's
    # SHA-256 validation must reject the substituted bytes.
    payload = bytearray(bar_file.read_bytes())
    payload[100] ^= 0xFF
    bar_file.write_bytes(bytes(payload))
    with pytest.raises(CanonicalArtifactValidationError) as excinfo:
        load_verified_canonical_build(build.build_path)
    assert "sha256 mismatch" in str(excinfo.value)


@pytest.mark.parametrize(
    "mutate, marker",
    [
        (lambda p: p.__setitem__("canonical_build_id", "0" * 64),
         "does not match manifest canonical_build_id"),
        (lambda p: p.__setitem__("canonical_content_id", "0" * 64),
         "canonical_content_id"),
        (lambda p: p["output_files"][0].__setitem__("sha256", "0" * 64),
         "sha256 mismatch"),
    ],
)
def test_snapshot_substitution_manifest_identity_tamper_rejected(tmp_path, mutate, marker):
    _, build = make_primary_build(tmp_path)
    _tamper_manifest(build, mutate)
    with pytest.raises(CanonicalArtifactValidationError) as excinfo:
        load_verified_canonical_build(build.build_path)
    assert marker in str(excinfo.value)


def test_snapshot_substitution_manifest_provenance_tamper_rejected(tmp_path):
    _, build = make_primary_build(tmp_path)

    def mutate(payload):
        record = payload["source_snapshot_provenance"][0]
        record["ingestion_run_id"] = "forged-run"

    _tamper_manifest(build, mutate)
    with pytest.raises(CanonicalArtifactValidationError) as excinfo:
        load_verified_canonical_build(build.build_path)
    assert "source_snapshot_provenance" in str(excinfo.value)


def test_snapshot_substitution_conflicting_rows_fail_closed(tmp_path):
    cfg, inputs = make_conflict_inputs(tmp_path)
    # The builder must never pick the "newest" or last input: conflicting
    # market values for one canonical_bar_key fail closed.
    with pytest.raises(CanonicalConflictError):
        build_canonical_market_bars(list(inputs))


def test_snapshot_substitution_build_input_order_irrelevant(tmp_path):
    # Two legal builds with disjoint canonical_bar_keys: input order never
    # changes the assembled content or identities.
    cfg, build_a, build_d = make_multi_day_builds(tmp_path)
    request = pit_request()
    forward = assemble_point_in_time_samples([build_a, build_d], [request])
    reversed_input = assemble_point_in_time_samples([build_d, build_a], [request])
    assert forward.samples == reversed_input.samples
    assert forward.association_rows == reversed_input.association_rows
    assert forward.association_content_id == reversed_input.association_content_id


def test_snapshot_substitution_source_pin_change_changes_dataset_id():
    base = {
        "canonical_build_id": sha("build"),
        "canonical_content_id": sha("content"),
        "canonical_builder_version": "builder-v1",
        "canonical_schema_version": "market-bars-canonical-schema-v1",
        "materializer_version": "market-bars-materializer-v1",
        "gap_policy_version": "gap-v1",
        "gap_content_id": sha("gap"),
        "status": "COMPLETE",
        "canonical_row_version_ids": (sha("row"),),
    }
    snapshot = {
        "ingestion_run_id": "run-a",
        "physical_snapshot_hash": sha("physical"),
        "logical_source_rows_hash": sha("logical"),
        "source_schema_version": "10.9",
        "requested_trade_date": date(2026, 7, 1),
        "requested_session": "ALL",
    }

    def make_pin(**snapshot_overrides):
        return CanonicalBuildPin(
            **base,
            source_snapshots=(SourceSnapshotPin(**{**snapshot, **snapshot_overrides}),),
        )

    original = dataset_id(identity_input(builds=(make_pin(),),
                                         row_versions=(sha("row"),)))
    assert dataset_id(identity_input(
        builds=(make_pin(physical_snapshot_hash=sha("other")),),
        row_versions=(sha("row"),),
    )) != original
    assert dataset_id(identity_input(
        builds=(make_pin(logical_source_rows_hash=sha("other")),),
        row_versions=(sha("row"),),
    )) != original
    assert dataset_id(identity_input(
        builds=(make_pin(ingestion_run_id="run-b"),),
        row_versions=(sha("row"),),
    )) != original


def test_snapshot_substitution_relocated_build_keeps_identity(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    first = materialize(cfg, root=output_root(cfg) / "root-one",
                         created_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC))
    second = materialize(cfg, root=output_root(cfg) / "root-two",
                         created_at=datetime(2026, 8, 5, 0, 0, tzinfo=UTC))
    # Build path relocation and created_at are never identity-bearing.
    assert second.canonical_build_id == first.canonical_build_id
    assert second.canonical_content_id == first.canonical_content_id


def test_snapshot_substitution_renamed_build_dir_rejected(tmp_path):
    _, build = make_primary_build(tmp_path)
    moved = build.build_path.parent / "build_id=renamed"
    build.build_path.rename(moved)
    with pytest.raises(CanonicalArtifactValidationError) as excinfo:
        load_verified_canonical_build(moved)
    assert "does not match manifest" in str(excinfo.value)


def test_snapshot_substitution_uncovered_row_version_fails_closed():
    pin = CanonicalBuildPin(
        canonical_build_id=sha("build"),
        canonical_content_id=sha("content"),
        canonical_builder_version="builder-v1",
        canonical_schema_version="market-bars-canonical-schema-v1",
        materializer_version="market-bars-materializer-v1",
        gap_policy_version="gap-v1",
        gap_content_id=sha("gap"),
        status="COMPLETE",
        canonical_row_version_ids=(sha("covered"),),
        source_snapshots=(),
    )
    with pytest.raises(DatasetError):
        dataset_id(
            identity_input(builds=(pin,), row_versions=(sha("uncovered"),))
        )


def test_snapshot_substitution_bad_gap_reference_fails_closed():
    pin = CanonicalBuildPin(
        canonical_build_id=sha("build"),
        canonical_content_id=sha("content"),
        canonical_builder_version="builder-v1",
        canonical_schema_version="market-bars-canonical-schema-v1",
        materializer_version="market-bars-materializer-v1",
        gap_policy_version="gap-v1",
        gap_content_id=sha("gap"),
        status="COMPLETE",
        canonical_row_version_ids=(),
        source_snapshots=(),
    )
    # A gap reference to an unpinned build fails closed.
    with pytest.raises(DatasetError):
        dataset_id(identity_input(
            builds=(pin,),
            gap_refs=(GapReference(sha("other-build"), sha("gap"), 1),),
        ))
    # A gap reference whose content disagrees with the pinned build fails.
    with pytest.raises(DatasetError):
        dataset_id(identity_input(
            builds=(pin,),
            gap_refs=(GapReference(sha("build"), sha("different-gap"), 1),),
        ))


# ---------------------------------------------------------------------------
# 8. LEAKAGE_SPEC_DRIFT: Feature / Label / implementation identity.
# ---------------------------------------------------------------------------

FEATURE_YAML_REORDERED = (
    "# comment moved\n"
    "requirements:\r\n"
    "  source_schema_versions:\r\n"
    "    - \"10.9\"\r\n"
    "  canonical_schema_versions:\r\n"
    "    - market-bars-canonical-schema-v1\r\n"
    "\r\n"
    "parameters:\r\n"
    "  lookback: 5\r\n"
    "transform:\r\n"
    "  ref: market_vault.features.transforms:close_return\r\n"
    "inputs:\r\n"
    "  canonical_fields:\r\n"
    "    - close\r\n"
    "output:\r\n"
    "  name: close_return\r\n"
    "  logical_type: float64\r\n"
    "  nullable: true\r\n"
    "version: v1\r\n"
    "name: close_return\r\n"
    "kind: FEATURE\r\n"
    "spec_schema_version: market-vault-feature-spec-v1\r\n"
)


def test_spec_drift_equivalent_yaml_same_identity():
    base = parse_feature_spec(feature_yaml())
    reordered = parse_feature_spec(FEATURE_YAML_REORDERED)
    assert feature_label_spec_content_id(base) == feature_label_spec_content_id(reordered)
    assert feature_label_spec_pin(base) == feature_label_spec_pin(reordered)


def test_spec_drift_semantic_change_changes_identity():
    base = feature_label_spec_content_id(parse_feature_spec(feature_yaml()))
    # Adding an input canonical field changes the identity.
    added_field = parse_feature_spec(feature_yaml().replace(
        "    - close\n", "    - close\n    - open\n"
    ))
    assert feature_label_spec_content_id(added_field) != base
    # The authoritative input order is semantic: (close, open) != (open, close).
    two_fields = feature_yaml().replace("    - close\n", "    - close\n    - open\n")
    forward = parse_feature_spec(two_fields)
    backward = parse_feature_spec(
        two_fields.replace("    - close\n    - open\n", "    - open\n    - close\n")
    )
    assert feature_label_spec_content_id(forward) != (
        feature_label_spec_content_id(backward)
    )
    # A requirements list in a different non-semantic order is equivalent
    # (same set, two input orderings; construction sorts them).
    requirements_first = parse_feature_spec(feature_yaml().replace(
        "  canonical_schema_versions:\n    - market-bars-canonical-schema-v1\n",
        "  canonical_schema_versions:\n    - market-bars-canonical-schema-v0\n"
        "    - market-bars-canonical-schema-v1\n",
    ))
    requirements_second = parse_feature_spec(feature_yaml().replace(
        "  canonical_schema_versions:\n    - market-bars-canonical-schema-v1\n",
        "  canonical_schema_versions:\n    - market-bars-canonical-schema-v1\n"
        "    - market-bars-canonical-schema-v0\n",
    ))
    assert feature_label_spec_content_id(requirements_first) == (
        feature_label_spec_content_id(requirements_second)
    )


def test_spec_drift_semantic_changes_feature_and_label(tmp_path):
    base_feature = feature_label_spec_content_id(feature_spec())
    assert feature_label_spec_content_id(
        replace(feature_spec(), transform_ref="market_vault.features.transforms:other")
    ) != base_feature
    assert feature_label_spec_content_id(
        replace(feature_spec(), parameters=(SpecParameter("lookback", 10),))
    ) != base_feature
    assert feature_label_spec_content_id(
        replace(feature_spec(), output=DatasetField("close_return", "float64", False))
    ) != base_feature
    base_label = feature_label_spec_content_id(label_spec())
    assert feature_label_spec_content_id(
        replace(label_spec(), horizon=LabelHorizon("TRADING_DAYS", 2))
    ) != base_label
    assert feature_label_spec_content_id(
        replace(label_spec(), observation_window=LabelObservationWindow("TRADING_DAYS", 0, 2))
    ) != base_label
    assert feature_label_spec_content_id(
        replace(label_spec(), alignment_rule="ALIGN_OPEN")
    ) != base_label
    assert feature_label_spec_content_id(
        replace(label_spec(), cross_trading_day=CrossTradingDayPolicy(True, "OTHER_RULE"))
    ) != base_label
    # The pin and dataset_id follow the content change.
    pin = feature_label_spec_pin(feature_spec())
    changed_pin = feature_label_spec_pin(
        replace(feature_spec(), version="v2")
    )
    assert dataset_id(identity_input(feature_pins=(pin,))) != dataset_id(
        identity_input(feature_pins=(changed_pin,))
    )


def test_spec_drift_duplicate_pin_key_fails_closed():
    pin = feature_label_spec_pin(feature_spec())
    drifted = SpecPin(
        kind="FEATURE", name=pin.name, version=pin.version,
        content_sha256=sha("different-content"),
    )
    with pytest.raises(DatasetError):
        dataset_id(identity_input(feature_pins=(pin, drifted)))


def test_spec_drift_pins_reject_wrong_containers():
    feature_pin = feature_label_spec_pin(feature_spec())
    label_pin = feature_label_spec_pin(label_spec())
    split_pin = chronological_split_spec_pin(split_spec())
    with pytest.raises(DatasetError):
        identity_input(label_pins=(feature_pin,))
    with pytest.raises(DatasetError):
        identity_input(feature_pins=(label_pin,))
    with pytest.raises(DatasetError):
        identity_input(split_pin=feature_pin)


def test_spec_drift_implementation_change_changes_dataset_id():
    base = ImplementationPin(name="transform-impl", version="v1", content_sha256=sha("impl"))
    changed_hash = ImplementationPin(name="transform-impl", version="v1", content_sha256=sha("other"))
    changed_version = ImplementationPin(name="transform-impl", version="v2", content_sha256=sha("impl"))
    original = dataset_id(identity_input(implementations=(base,)))
    assert dataset_id(identity_input(implementations=(changed_hash,))) != original
    assert dataset_id(identity_input(implementations=(changed_version,))) != original


def test_spec_drift_transform_ref_is_never_executed():
    # A transform_ref naming a module that cannot exist still parses: the
    # reference is a declaration, never imported, executed, or network-fetched.
    spec = parse_feature_spec(feature_yaml().replace(
        "market_vault.features.transforms:close_return",
        "no.such.module:no_such_function",
    ))
    assert spec.transform_ref == "no.such.module:no_such_function"


@pytest.mark.parametrize(
    "parse, schema_version",
    [
        (parse_feature_spec, "market-vault-feature-spec-v2"),
        (parse_feature_spec, "market-vault-feature-spec-v0"),
        (parse_label_spec, "market-vault-label-spec-v9"),
        (parse_label_spec, "future-unknown-version"),
    ],
)
def test_spec_drift_unknown_schema_version_fails_closed(parse, schema_version):
    yaml_text = (
        feature_yaml()
        if parse is parse_feature_spec
        else label_yaml()
    )
    with pytest.raises(SpecValidationError):
        parse(yaml_text.replace(
            "market-vault-feature-spec-v1" if parse is parse_feature_spec
            else "market-vault-label-spec-v1",
            schema_version,
        ))


# ---------------------------------------------------------------------------
# 9. LEAKAGE_COMPLETION_AMBIGUITY: incomplete data must never masquerade.
# ---------------------------------------------------------------------------


def test_completion_ambiguity_complete_snapshot_produces_rows(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    result = materialize(cfg)
    assert result.status == "COMPLETE"
    assert result.row_count == 2


def test_completion_ambiguity_quality_fail_snapshot_excluded(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-fail",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2),
                   quality="FAIL")
    refs = Catalog(cfg).latest_complete_market_bar_snapshots(
        symbols=["US.MU"], trade_dates=[date(2026, 7, 1)],
        interval="1m", requested_session="ALL", adjustment="NONE",
        source_schema_version="10.9",
    )
    assert refs == {}
    result = materialize(cfg)
    assert result.status == "EMPTY"
    assert result.row_count == 0


def test_completion_ambiguity_missing_key_produces_empty_build(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                   time_keys=minute_keys("2026-07-01 09:30:00", 2))
    result = materialize(cfg, symbols=["US.NVDA"])
    # A fully MISSING key never produces a complete snapshot reference and
    # never produces canonical rows.
    assert result.status == "EMPTY"
    assert result.row_count == 0


def test_completion_ambiguity_observed_rows_only_with_gap(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1)
                   + minute_keys("2026-07-01 09:32:00", 1))
    result = materialize(cfg)
    # Only the two observed rows exist: no synthetic OHLCV, no interpolation,
    # no forward/zero fill, no placeholder bar at 09:31.
    assert result.row_count == 2


def test_completion_ambiguity_gap_is_sidecar_not_placeholder_row(tmp_path):
    cfg = settings(tmp_path)
    calendar(cfg)
    write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-gap",
                   time_keys=minute_keys("2026-07-01 09:30:00", 1)
                   + minute_keys("2026-07-01 09:32:00", 1))
    result = materialize(cfg)
    assert result.gap_count == 1
    gap_file = next(result.build_path.rglob("gaps/**/*.parquet"))
    frame = pd.read_parquet(gap_file)
    assert int(frame["missing_bar_count"].iloc[0]) == 1


def test_completion_ambiguity_no_known_gap_never_implies_complete():
    # Absence of known gaps is never a completeness claim: the assembly
    # diagnostics carry only observed rows, known gaps, and exclusion counts.
    diagnostics_names = {f.name for f in fields(PITDiagnostics)}
    for forbidden in ("label_status", "horizon_complete", "session_complete"):
        assert forbidden not in diagnostics_names


def test_completion_ambiguity_pit_carries_no_label_status():
    sample_names = {f.name for f in fields(PITSample)}
    assert "label_status" not in sample_names
    assert "actual_label_end_time" not in sample_names


def test_completion_ambiguity_split_requires_explicit_label_facts():
    # Even when PIT observed label rows, the split layer requires the caller
    # to declare label_status and actual_label_end_time explicitly: a sample
    # with no actual label end cannot be COMPLETE.
    with pytest.raises(SplitValidationError):
        ChronologicalSplitSample(
            sample_key=sha("s"),
            sample_version_id=sha("s#v1"),
            feature_window_close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
            label_status=LABEL_STATUS_COMPLETE,
            actual_label_end_time=None,
        )


def test_completion_ambiguity_explicit_incomplete_excluded():
    result = assign_chronological_splits(
        [
            split_sample(
                "inc",
                close=datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE),
                status=LABEL_STATUS_INCOMPLETE,
                actual_end=None,
            )
        ],
        split_spec(),
    )
    assert result.assignments[0].assignment_status == SPLIT_STATUS_EXCLUDED
    assert result.assignments[0].reason_code == REASON_CODE_INCOMPLETE_LABEL


def test_completion_ambiguity_completion_and_gap_semantics_identity_bearing():
    pin = CanonicalBuildPin(
        canonical_build_id=sha("build"),
        canonical_content_id=sha("content"),
        canonical_builder_version="builder-v1",
        canonical_schema_version="market-bars-canonical-schema-v1",
        materializer_version="market-bars-materializer-v1",
        gap_policy_version="gap-v1",
        gap_content_id=sha("gap"),
        status="COMPLETE",
        canonical_row_version_ids=(),
        source_snapshots=(),
    )
    base = dataset_id(identity_input(builds=(pin,)))
    different_completion = dataset_id(identity_input(
        builds=(pin,),
        completion=CompletionSummary(
            complete_count=1, incomplete_count=0, missing_count=0,
            entries=(CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),),
        ),
    ))
    assert different_completion != base
    with_gap = dataset_id(identity_input(
        builds=(pin,),
        gap_refs=(GapReference(sha("build"), sha("gap"), 1),),
    ))
    assert with_gap != base


def test_completion_ambiguity_forged_counts_fail_closed():
    # Forged completion counts that do not match the actual entries fail.
    with pytest.raises(DatasetError):
        CompletionSummary(
            complete_count=1, incomplete_count=0, missing_count=0, entries=()
        )
    with pytest.raises(DatasetError):
        CompletionSummary(
            complete_count=0, incomplete_count=0, missing_count=0,
            entries=(CompletionEntry("US.MU", date(2026, 7, 1), "COMPLETE"),),
        )


# ---------------------------------------------------------------------------
# 10. LEAKAGE_TIMEZONE_MISATTRIBUTION.
# ---------------------------------------------------------------------------


def test_timezone_naive_instants_fail_closed():
    with pytest.raises(PITAssemblyError):
        pit_request(feature_start=datetime(2026, 7, 1, 13, 30))
    with pytest.raises(PITAssemblyError):
        PITObservationWindow(
            start=datetime(2026, 7, 1, 13, 0),
            close=utc(2026, 7, 1, 13, 30),
        )
    with pytest.raises(SplitValidationError):
        split_sample("s", close=datetime(2026, 6, 30, 16, 0))


def test_timezone_equivalent_instants_identical_identities():
    request_ny = pit_request(feature_start=datetime(2026, 7, 1, 9, 30, tzinfo=NY_ZONE))
    request_utc = pit_request(feature_start=utc(2026, 7, 1, 13, 30))
    request_offset = pit_request(
        feature_start=datetime(2026, 7, 1, 22, 30, tzinfo=timezone(timedelta(hours=9)))
    )
    assert pit_sample_key(request_ny) == pit_sample_key(request_utc)
    assert pit_sample_key(request_ny) == pit_sample_key(request_offset)
    # Split identities behave the same way for equivalent closes.
    close_ny = datetime(2026, 6, 30, 16, 0, tzinfo=NY_ZONE)
    close_utc = utc(2026, 6, 30, 20, 0)
    result_ny = assign_chronological_splits(
        [split_sample("s", close=close_ny, actual_end=utc(2026, 6, 30, 21, 0))],
        split_spec(),
    )
    result_utc = assign_chronological_splits(
        [split_sample("s", close=close_utc, actual_end=utc(2026, 6, 30, 21, 0))],
        split_spec(),
    )
    assert result_ny.assignment_rows == result_utc.assignment_rows
    assert result_ny.split_result_id == result_utc.split_result_id


def test_timezone_split_uses_declared_local_date_not_utc_date():
    # 2026-07-02 02:30 UTC is 2026-07-01 22:30 EDT. The UTC date (07-02)
    # would fall into VALIDATION; the declared timezone's local date (07-01)
    # keeps the sample in TRAIN.
    spec = split_spec(train_end_date=date(2026, 7, 1))
    result = assign_chronological_splits(
        [
            split_sample(
                "s",
                close=utc(2026, 7, 2, 2, 30),
                actual_end=utc(2026, 7, 2, 3, 30),
            )
        ],
        spec,
    )
    assignment = result.assignments[0]
    assert assignment.feature_window_close_date == date(2026, 7, 1)
    assert assignment.nominal_split == SPLIT_TRAIN
    assert assignment.final_split == SPLIT_TRAIN


def test_timezone_equivalent_as_of_same_version_id():
    version_utc = pit_sample_version_id(
        sample_key=sha("sample"),
        dataset_as_of=utc(2026, 7, 1, 14, 0),
        feature_canonical_row_version_ids=(sha("row"),),
        label_canonical_row_version_ids=(),
        considered_canonical_build_ids=(sha("build"),),
    )
    version_ny = pit_sample_version_id(
        sample_key=sha("sample"),
        dataset_as_of=datetime(2026, 7, 1, 10, 0, tzinfo=NY_ZONE),
        feature_canonical_row_version_ids=(sha("row"),),
        label_canonical_row_version_ids=(),
        considered_canonical_build_ids=(sha("build"),),
    )
    assert version_utc == version_ny


def test_timezone_invalid_iana_fails_closed():
    with pytest.raises(SplitValidationError):
        split_spec(boundary_timezone="America/New_York2")
    with pytest.raises(SplitValidationError):
        split_spec(boundary_timezone="Not/AZone")


def test_timezone_no_system_local_fallback():
    with pytest.raises(SplitValidationError):
        split_spec(boundary_timezone="")


def test_timezone_dst_spring_forward_boundary_local_calendar():
    # America/New_York springs forward 2024-03-10 02:00 -> 03:00. The next
    # local midnight after 2024-03-09 is 00:00 EST = 05:00 UTC, never the
    # fixed +24h instant 00:00 EDT = 04:00 UTC.
    spec = split_spec(
        train_end_date=date(2024, 3, 9),
        validation_end_date=date(2024, 3, 30),
        test_end_date=date(2024, 4, 30),
    )
    kept = assign_chronological_splits(
        [
            split_sample(
                "s",
                close=datetime(2024, 3, 8, 16, 0, tzinfo=NY_ZONE),
                actual_end=utc(2024, 3, 10, 4, 30),
            )
        ],
        spec,
    )
    assert kept.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED
    purged = assign_chronological_splits(
        [
            split_sample(
                "s",
                close=datetime(2024, 3, 8, 16, 0, tzinfo=NY_ZONE),
                actual_end=utc(2024, 3, 10, 5, 0),
            )
        ],
        spec,
    )
    assert purged.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert purged.assignments[0].purge_boundary == utc(2024, 3, 10, 5, 0)


def test_timezone_dst_fall_back_boundary_local_calendar():
    # America/New_York falls back 2024-11-03 02:00 -> 01:00. The next local
    # midnight after 2024-11-02 is the first occurrence 00:00 EDT = 04:00
    # UTC, never the fixed +24h instant 00:00 EST = 05:00 UTC.
    spec = split_spec(
        train_end_date=date(2024, 11, 2),
        validation_end_date=date(2024, 11, 29),
        test_end_date=date(2024, 12, 31),
    )
    purged = assign_chronological_splits(
        [
            split_sample(
                "s",
                close=datetime(2024, 11, 1, 16, 0, tzinfo=NY_ZONE),
                actual_end=utc(2024, 11, 3, 4, 30),
            )
        ],
        spec,
    )
    assert purged.assignments[0].assignment_status == SPLIT_STATUS_PURGED
    assert purged.assignments[0].purge_boundary == utc(2024, 11, 3, 4, 0)
    kept = assign_chronological_splits(
        [
            split_sample(
                "s",
                close=datetime(2024, 11, 1, 16, 0, tzinfo=NY_ZONE),
                actual_end=utc(2024, 11, 3, 3, 59, 59, 999999),
            )
        ],
        spec,
    )
    assert kept.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED


def test_timezone_microsecond_truncation_is_consistent():
    # Nanosecond input is truncated to the contract's microsecond precision;
    # the truncated instant produces the identical identity.
    fine = split_sample(
        "s",
        close=pd.Timestamp("2026-06-30T20:00:00.123456789Z"),
        actual_end=pd.Timestamp("2026-06-30T21:00:00.123456789Z"),
    )
    truncated = split_sample(
        "s",
        close=utc(2026, 6, 30, 20, 0, 0, 123456),
        actual_end=utc(2026, 6, 30, 21, 0, 0, 123456),
    )
    result_fine = assign_chronological_splits([fine], split_spec())
    result_truncated = assign_chronological_splits([truncated], split_spec())
    assert result_fine.assignment_rows == result_truncated.assignment_rows
    assert result_fine.split_result_id == result_truncated.split_result_id


# ---------------------------------------------------------------------------
# 11. Cross-layer canary.
# ---------------------------------------------------------------------------


def test_cross_layer_canary_full_offline_chain(tmp_path):
    """COMPLETE synthetic snapshot -> Canonical materialization -> verified
    reader -> PIT assembly -> Feature/Label SpecPin -> explicit split facts ->
    chronological split assignment -> DatasetIdentityInput -> dataset_id.

    This is an offline combination check of existing contracts, not the final
    Dataset builder and not a DatasetManifest/Parquet writer.
    """
    _, build = make_primary_build(tmp_path)
    as_of = utc(2026, 7, 1, 14, 0)
    request = pit_request(
        feature_close=utc(2026, 7, 1, 13, 33),
        label_start=utc(2026, 7, 1, 13, 33),
        label_close=utc(2026, 7, 1, 13, 35),
    )
    assembly = assemble_point_in_time_samples([build], [request], dataset_as_of=as_of)

    # Feature association rows are exactly the PIT-visible rows.
    for row in assembly.association_rows:
        assert row["archive_available_at"] <= as_of
        if row["role"] == "FEATURE":
            assert row["event_time"] < request.feature_window_close
            assert row["market_available_at"] <= request.feature_window_close
    # Label rows are separated from Feature rows.
    feature_versions = {
        row["canonical_row_version_id"]
        for row in assembly.association_rows
        if row["role"] == "FEATURE"
    }
    label_versions = {
        row["canonical_row_version_id"]
        for row in assembly.association_rows
        if row["role"] == "LABEL"
    }
    assert feature_versions.isdisjoint(label_versions)
    # Every selected canonical row version is covered by a build pin.
    covered = set()
    for pin in assembly.canonical_build_pins:
        covered.update(pin.canonical_row_version_ids)
    assert set(assembly.canonical_row_version_ids) <= covered
    # The default adjustment policy is NONE end to end.
    assert request.adjustment == "NONE"

    # Explicit split facts derived from the assembled sample: label status and
    # the actual label end are always caller-provided.
    pit_sample = assembly.samples[0]
    spec = split_spec()
    kept = assign_chronological_splits(
        [
            ChronologicalSplitSample(
                sample_key=pit_sample.sample_key,
                sample_version_id=pit_sample.sample_version_id,
                feature_window_close=request.feature_window_close,
                label_status=LABEL_STATUS_COMPLETE,
                actual_label_end_time=utc(2026, 7, 1, 15, 0),
            )
        ],
        spec,
    )
    assert kept.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED
    # The actual label end decides the purge.
    purged = assign_chronological_splits(
        [
            ChronologicalSplitSample(
                sample_key=pit_sample.sample_key,
                sample_version_id=pit_sample.sample_version_id,
                feature_window_close=request.feature_window_close,
                label_status=LABEL_STATUS_COMPLETE,
                actual_label_end_time=utc(2026, 8, 1, 5, 0),
            )
        ],
        spec,
    )
    assert purged.assignments[0].assignment_status == SPLIT_STATUS_PURGED

    # Feature/Label/Split pins enter the correct identity containers.
    feature_pin = feature_label_spec_pin(feature_spec())
    label_pin = feature_label_spec_pin(label_spec())
    split_pin = chronological_split_spec_pin(spec)

    def canary_identity(result):
        return identity_input(
            split_pin=split_pin,
            feature_pins=(feature_pin,),
            label_pins=(label_pin,),
            schema=result.assignment_schema,
            rows=result.assignment_rows,
        )

    dataset_id_kept = dataset_id(canary_identity(kept))
    assert SHA_HEX.fullmatch(dataset_id_kept)
    # Identical inputs, including a different input order, give the same ID.
    assert dataset_id(canary_identity(kept)) == dataset_id_kept
    assert dataset_id(identity_input(
        split_pin=split_pin,
        feature_pins=(feature_pin,),
        label_pins=(label_pin,),
        schema=kept.assignment_schema,
        rows=list(kept.assignment_rows),
    )) == dataset_id_kept
    # Any identity-bearing threat mutation changes the ID: the purge decision
    # changed the assignment content.
    assert dataset_id(canary_identity(purged)) != dataset_id_kept


# ---------------------------------------------------------------------------
# 12. Offline / no-network / no-write boundary assertions.
# ---------------------------------------------------------------------------


def test_suite_imports_never_touch_network_or_opend():
    import sys

    import market_vault.canonical.reader as reader_module
    import market_vault.canonical.materialization as materialization_module
    import market_vault.dataset as dataset_module

    assert not any("opend" in name.lower() for name in sys.modules)
    assert "requests" not in sys.modules
    for module in (reader_module, materialization_module, dataset_module):
        for attribute in ("requests", "urllib", "socket", "opend", "moomoo_sdk"):
            assert not hasattr(module, attribute)


def test_suite_writes_only_under_tmp_path(tmp_path):
    import os

    previous_cwd = os.getcwd()
    repo_entries_before = sorted(os.listdir(previous_cwd))
    os.chdir(tmp_path)
    try:
        cfg = settings(tmp_path)
        calendar(cfg)
        write_snapshot(cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id="run-a",
                       time_keys=minute_keys("2026-07-01 09:30:00", 2))
        result = materialize(cfg)
        assert result.row_count == 2
        assign_chronological_splits([split_sample("s")], split_spec())
    finally:
        os.chdir(previous_cwd)
    # The repository working directory receives no build artifacts; every
    # fixture write stays under the tmp_path the test was given.
    assert sorted(os.listdir(previous_cwd)) == repo_entries_before
