"""Offline deterministic tests for the verified Dataset reader (v0.5.0
PR-7).

Covers the public API and reader contract version, the explicit
build-directory input contract (single ``build_dir`` argument, absolute /
relative, no expected result, no strict / skip / repair / latest modes),
the frozen deeply immutable result model and its self-validation, path and
symlink / junction safety (Python 3.11 Windows reparse-point detection),
``_SUCCESS``, canonical manifest validation and directory-name binding,
the exact artifact whitelist, the full DatasetOutputFile records with
sizes and SHA-256s, Feature / Label / Split artifact parse / pin /
canonical-bytes verification, authoritative schema re-derivation, Parquet
schema / metadata / row / content-identity verification, physical row
order, sample uniqueness, scope and ``dataset_as_of`` binding, split
re-derivation (including DST, INCOMPLETE exclusion, and purge cases), the
typed build report record with canonical bytes and observable-fact
bindings, the fixed diagnostics matrix, the no-write guarantee, the
unified error boundary, relocation / determinism, EMPTY Dataset reading,
and the two-phase final verification. All fixtures are micro synthetic
canonical builds produced through the verified reader; no network, no
OpenD, no current time, and no real market data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import market_vault.dataset as dataset_pkg
import market_vault.dataset.materialization as mat_mod
import market_vault.dataset.orchestration as orch_mod
import market_vault.dataset.reader as reader_mod
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    DATASET_BUILD_REPORT_FILENAME,
    DATASET_BUILD_REPORT_SCHEMA_VERSION,
    DATASET_CONTENT_ROLE_BUILD_REPORT,
    DATASET_CONTENT_ROLE_FEATURE_SPEC,
    DATASET_CONTENT_ROLE_LABEL_SPEC,
    DATASET_CONTENT_ROLE_LOGICAL_ROWS,
    DATASET_CONTENT_ROLE_SPLIT_SPEC,
    DATASET_FEATURE_SPECS_DIRNAME,
    DATASET_KIND_SUPERVISED,
    DATASET_LABEL_SPECS_DIRNAME,
    DATASET_MANIFEST_FILENAME,
    DATASET_MANIFEST_SCHEMA_VERSION,
    DATASET_MATERIALIZER_VERSION,
    DATASET_ORCHESTRATION_CONTRACT_VERSION,
    DATASET_OUTPUT_ROLE_BUILD_REPORT,
    DATASET_OUTPUT_ROLE_DATASET,
    DATASET_OUTPUT_ROLE_FEATURE_SPEC,
    DATASET_OUTPUT_ROLE_LABEL_SPEC,
    DATASET_OUTPUT_ROLE_SPLIT_SPEC,
    DATASET_PARQUET_FILENAME,
    DATASET_READER_CONTRACT_VERSION,
    DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    DATASET_SPEC_ARTIFACT_VERSION,
    DATASET_SPLIT_SPEC_FILENAME,
    DATASET_SUCCESS_FILENAME,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_EXECUTION_CONTRACT_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_INCOMPLETE_LABEL,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    ChronologicalSplitResult,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetArtifactValidationError,
    DatasetBuildReportRecord,
    DatasetError,
    DatasetField,
    DatasetMaterializationError,
    DatasetOrchestrationDiagnostics,
    DatasetOrchestrationError,
    DatasetOutputFile,
    DatasetOutputLayoutRecord,
    DatasetOrchestrationResult,
    DatasetSchema,
    DatasetScope,
    FeatureExecutionDiagnostics,
    FeatureExecutionResult,
    FeatureSampleResult,
    FeatureSpec,
    FeatureValueResult,
    ImplementationPin,
    LabelExecutionDiagnostics,
    LabelExecutionResult,
    LabelHorizon,
    LabelObservationWindow,
    LabelSampleResult,
    LabelSpec,
    LabelValueResult,
    PITSampleRequest,
    SpecParameter,
    SpecValidationError,
    SpecVersionRequirements,
    SplitValidationError,
    VerifiedDatasetBuild,
    assemble_point_in_time_samples,
    assign_chronological_splits,
    chronological_split_spec_pin,
    dataset_orchestration_schema,
    execute_builtin_features,
    execute_builtin_labels,
    feature_label_spec_pin,
    load_verified_dataset,
    materialize_dataset_artifacts,
    orchestrate_dataset_build,
    parse_feature_spec,
    parse_label_spec,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"

SHA_A = "a" * 64
SHA_B = "b" * 64

BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

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
# Offline canonical-build fixtures (mirrors the orchestration tests; every
# fixture goes through the verified reader).
# ---------------------------------------------------------------------------


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
        (base + pd.Timedelta(int(i), unit="m")).strftime("%Y-%m-%d %H:%M:%S")
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
    root = tmp_path_factory.mktemp("mv_reader")
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
        run_finished_at=datetime(2026, 6, 30, 14, 0, tzinfo=UTC),
    )
    d = build(
        "US.NVDA", date(2026, 7, 2), "run-d",
        minute_keys("2026-07-02 09:30:00", 2),
        run_finished_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC),
    )
    e = build(
        "US.MU", date(2026, 7, 3), "run-e",
        minute_keys("2026-07-03 09:30:00", 2),
        run_finished_at=datetime(2026, 7, 3, 14, 0, tzinfo=UTC),
    )
    return SimpleNamespace(root=root, a=a, f=f, fmin=fmin, c=c, d=d, e=e)


# ---------------------------------------------------------------------------
# Spec / request / scope / orchestration helpers.
# ---------------------------------------------------------------------------


def feature_spec(name: str = "sr", *, window_bars: int = 2) -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(SpecParameter("window_bars", window_bars),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec(name: str = "fr", *, horizon: int = 2) -> LabelSpec:
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_FORWARD,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow(
            "BARS", horizon - 1, horizon - 1
        ),
        horizon=LabelHorizon("BARS", horizon),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def chronological_spec(
    *,
    train_end_date: date = date(2026, 6, 30),
    validation_end_date: date = date(2026, 7, 1),
    test_end_date: date = date(2026, 7, 2),
) -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version="market-vault-chronological-split-spec-v1",
        name="chrono",
        version="v1",
        boundary_timezone=NY,
        train_end_date=train_end_date,
        validation_end_date=validation_end_date,
        test_end_date=test_end_date,
        assignment_rule="FEATURE_WINDOW_CLOSE_DATE",
        purge_rule="ACTUAL_LABEL_END",
        incomplete_label_policy="EXCLUDE",
        out_of_range_policy="EXCLUDE",
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


def excluded_request() -> PITSampleRequest:
    """Feature window [13:30, 13:31): one row < window_bars=2 -> EXCLUDED."""
    return request(
        f_close=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
        l_start=datetime(2026, 7, 1, 13, 31, tzinfo=UTC),
        l_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
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


def inputs(fixtures, *, requests, **overrides) -> dict:
    builds = overrides.pop("builds", [fixtures.a, fixtures.f])
    feature_specs = overrides.pop("feature_specs", [feature_spec()])
    label_specs = overrides.pop("label_specs", [label_spec()])
    split_spec = overrides.pop("split_spec", chronological_spec())
    scope = overrides.pop("scope", dataset_scope())
    dataset_as_of = overrides.pop("dataset_as_of", None)
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
    kwargs.update(overrides)
    return kwargs


def orchestrate(fixtures, *, requests, **overrides) -> DatasetOrchestrationResult:
    kwargs = inputs(fixtures, requests=requests, **overrides)
    return orchestrate_dataset_build(**kwargs)


def real_label_pins(fixtures, spec: LabelSpec) -> tuple[ImplementationPin, ...]:
    pit = assemble_point_in_time_samples([fixtures.a, fixtures.f], [request()])
    return execute_builtin_labels([fixtures.a, fixtures.f], pit, [spec]).implementation_pins


def stub_label_result(samples, spec: LabelSpec, impl_pins) -> LabelExecutionResult:
    complete = sum(
        1 for sample in samples if sample.status == LABEL_STATUS_COMPLETE
    )
    return LabelExecutionResult(
        samples=tuple(samples),
        label_spec_pins=(feature_label_spec_pin(spec),),
        implementation_pins=tuple(impl_pins),
        diagnostics=LabelExecutionDiagnostics(
            sample_count=len(samples),
            label_spec_count=1,
            complete_sample_count=complete,
            incomplete_sample_count=len(samples) - complete,
            complete_value_count=complete,
            incomplete_value_count=len(samples) - complete,
            transform_invocation_count=complete,
        ),
        execution_contract_version=LABEL_EXECUTION_CONTRACT_VERSION,
    )


def hand_label_sample(
    pit_sample,
    spec: LabelSpec,
    impl_pin: ImplementationPin,
    *,
    status: str,
    actual_end=None,
    value=None,
    reason_code=None,
) -> LabelSampleResult:
    value_result = LabelValueResult(
        label_name=spec.name,
        spec_pin=feature_label_spec_pin(spec),
        implementation_pin=impl_pin,
        status=status,
        value=value,
        reason_code=reason_code,
        anchor_canonical_row_version_id=SHA_A,
        consumed_label_canonical_row_version_ids=(SHA_B,),
        actual_label_end_time=actual_end,
    )
    return LabelSampleResult(
        sample_key=pit_sample.sample_key,
        sample_version_id=pit_sample.sample_version_id,
        code=pit_sample.request.code,
        feature_window_close=pit_sample.request.feature_window_close,
        values=(value_result,),
        status=status,
        actual_label_end_time=actual_end,
    )


# ---------------------------------------------------------------------------
# Materialization and tamper helpers.
# ---------------------------------------------------------------------------


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
    return result, materialize_dataset_artifacts(
        result, output_root=root, built_at=built_at
    )


def build_path(mresult: DatasetMaterializationResult) -> Path:
    return mresult.build_path


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


def refresh_artifact_facts(build: Path, rel: str) -> None:
    """Update the manifest's byte facts of one artifact after a rewrite so
    the artifact-level verification checks are reached."""
    path = build / rel

    def mutate(payload):
        for record in payload["output_files"]:
            if record["relative_path"] == rel:
                record["byte_size"] = path.stat().st_size
                record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    tamper_json(build / DATASET_MANIFEST_FILENAME, mutate)


def refresh_parquet_facts(build: Path) -> None:
    refresh_artifact_facts(build, DATASET_PARQUET_FILENAME)


def rewrite_parquet(build: Path, writer) -> None:
    path = build / DATASET_PARQUET_FILENAME
    table = pq.read_table(path)
    pq.write_table(writer(table), path, **PARQUET_OPTS)
    refresh_parquet_facts(build)


def permute_rows(build: Path, indices) -> None:
    rewrite_parquet(build, lambda table: table.take(pa.array(indices)))


def rewrite_from_pylist(build: Path, mutator) -> None:
    def writer(table):
        rows = table.to_pylist()
        mutator(rows)
        return pa.Table.from_pylist(rows, schema=table.schema)

    rewrite_parquet(build, writer)


def replace_column(build: Path, field_name: str, values) -> None:
    def writer(table):
        idx = table.schema.get_field_index(field_name)
        arrays = [table.column(i) for i in range(table.num_columns)]
        arrays[idx] = pa.array(values, type=table.schema.field(idx).type)
        return pa.Table.from_arrays(arrays, schema=table.schema)

    rewrite_parquet(build, writer)


def cast_column(build: Path, field_name: str, arrow_type) -> None:
    def writer(table):
        idx = table.schema.get_field_index(field_name)
        old = table.schema.field(idx)
        new_field = pa.field(old.name, arrow_type, nullable=old.nullable)
        fields = [new_field if i == idx else table.schema.field(i) for i in range(table.num_columns)]
        new_schema = pa.schema(fields, metadata=table.schema.metadata)
        arrays = [
            table.column(i).cast(arrow_type, safe=False) if i == idx else table.column(i)
            for i in range(table.num_columns)
        ]
        return pa.Table.from_arrays(arrays, schema=new_schema)

    rewrite_parquet(build, writer)


def with_metadata(build: Path, mutate_metadata) -> None:
    def writer(table):
        metadata = dict(table.schema.metadata or {})
        mutate_metadata(metadata)
        return table.replace_schema_metadata(metadata)

    rewrite_parquet(build, writer)


def rewrite_report(build: Path, mutate) -> None:
    """Rewrite build_report.json canonically (byte hash changes with the
    content); tampered observable facts must still be rejected."""
    path = build / DATASET_BUILD_REPORT_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(canonical_dump(payload), encoding="utf-8", newline="")


def schema_names(schema: DatasetSchema) -> list[str]:
    return [field.name for field in schema.fields]


def row_map(schema: DatasetSchema, row) -> dict:
    return dict(zip(schema_names(schema), row))


def _make_symlink_or_skip(target: Path, link: Path) -> None:
    """Create a symlink, falling back to a Windows junction (junctions need
    no elevated privileges); skip when neither is available."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt" and target.is_dir():
        try:
            import _winapi

            _winapi.CreateJunction(str(target.absolute()), str(link.absolute()))
            return
        except (OSError, TypeError, ImportError):
            pass
    pytest.skip(
        f"cannot create a symlink or junction in this environment: {link}"
    )


@pytest.fixture
def built(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path)
    build = build_path(mresult)
    manifest = dataset_pkg.validate_dataset_manifest(
        (build / DATASET_MANIFEST_FILENAME).read_bytes()
    )
    return SimpleNamespace(
        result=result, mresult=mresult, build=build, manifest=manifest
    )


@pytest.fixture
def built_multi(fixtures, tmp_path):
    """A build with two rows of the same code at different feature window
    closes (exercise the fixed physical order on a multi-row Dataset)."""
    requests = [
        request(f_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC)),
        request(f_close=datetime(2026, 7, 1, 13, 38, tzinfo=UTC)),
    ]
    result, mresult = materialize_once(fixtures, tmp_path, requests=requests)
    build = build_path(mresult)
    manifest = dataset_pkg.validate_dataset_manifest(
        (build / DATASET_MANIFEST_FILENAME).read_bytes()
    )
    return SimpleNamespace(
        result=result, mresult=mresult, build=build, manifest=manifest
    )


def read_verified(built) -> VerifiedDatasetBuild:
    return load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# A. Public API / input contract.
# ---------------------------------------------------------------------------


def test_public_api_exports():
    for name in (
        "DATASET_READER_CONTRACT_VERSION",
        "DatasetArtifactValidationError",
        "DatasetOutputLayoutRecord",
        "DatasetBuildReportRecord",
        "VerifiedDatasetBuild",
        "load_verified_dataset",
    ):
        assert hasattr(dataset_pkg, name)
    # The private validator and low-level helpers are not public.
    assert not hasattr(dataset_pkg, "_verify_build_directory")
    assert not hasattr(dataset_pkg, "_verify_build_dir_safety")
    assert not hasattr(dataset_pkg, "_expected_build_entries")


def test_reader_contract_version_exact():
    assert DATASET_READER_CONTRACT_VERSION == (
        "market-vault-verified-dataset-reader-v1"
    )


def test_load_signature_single_build_dir_argument():
    import inspect

    parameters = list(inspect.signature(load_verified_dataset).parameters)
    assert parameters == ["build_dir"]


def test_dataset_artifact_validation_error_hierarchy():
    assert issubclass(DatasetArtifactValidationError, DatasetError)


def test_load_verified_dataset_success(built):
    verified_build = read_verified(built)
    assert verified_build.dataset_id == built.result.dataset_id
    assert verified_build.status == STATUS_COMPLETE


def test_invalid_input_types():
    for bad in (12345, None, [], {}, object()):
        with pytest.raises(DatasetArtifactValidationError):
            load_verified_dataset(bad)


def test_missing_path(tmp_path):
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(tmp_path / ("0" * 64))


def test_file_path_rejected(tmp_path):
    path = tmp_path / ("a" * 64)
    path.write_text("x", encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(path)


def test_parent_output_root_is_not_a_build_directory(built):
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build.parent)


def test_staging_directory_name_rejected(built, tmp_path):
    staging = tmp_path / f".staging-{built.result.dataset_id}"
    staging.mkdir()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(staging)


def test_wrong_directory_name_rejected(built, tmp_path):
    other = tmp_path / ("b" * 64)
    other.mkdir()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(other)


def test_relative_input_returns_absolute_build_path(built, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    verified_build = load_verified_dataset(
        Path("datasets") / built.result.dataset_id
    )
    assert verified_build.build_path.is_absolute()
    assert verified_build.build_path == built.build
    assert verified_build.build_path.name == built.result.dataset_id


def test_no_latest_scan(built, tmp_path):
    # A sibling "latest" directory and a second Dataset directory in the
    # output root are never consulted; the explicit directory is read.
    (built.build.parent / "latest").mkdir()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build.parent / "latest")
    verified_build = read_verified(built)
    assert verified_build.dataset_id == built.result.dataset_id


# ---------------------------------------------------------------------------
# B. Result model.
# ---------------------------------------------------------------------------


def test_result_model_fields(built):
    verified_build = read_verified(built)
    assert verified_build.reader_contract_version == DATASET_READER_CONTRACT_VERSION
    assert verified_build.dataset_id == built.result.dataset_id
    assert verified_build.dataset_kind == DATASET_KIND_SUPERVISED
    assert verified_build.status == STATUS_COMPLETE
    assert verified_build.built_at == BUILT_AT
    assert verified_build.dataset_as_of is None
    assert verified_build.schema == built.result.schema
    assert verified_build.rows == built.result.rows
    assert isinstance(verified_build.manifest, dataset_pkg.DatasetManifest)
    assert isinstance(verified_build.feature_specs, tuple)
    assert isinstance(verified_build.label_specs, tuple)
    assert isinstance(verified_build.split_spec, ChronologicalSplitSpec)
    assert isinstance(verified_build.split_result, ChronologicalSplitResult)
    assert isinstance(verified_build.build_report, DatasetBuildReportRecord)
    assert isinstance(verified_build.manifest_payload, bytes)
    assert isinstance(verified_build.build_report_payload, bytes)
    assert isinstance(verified_build.build_path, Path)
    assert verified_build.build_path.is_absolute()
    assert verified_build.build_path.name == verified_build.dataset_id


def test_rows_are_strict_tuples(built):
    verified_build = read_verified(built)
    for row in verified_build.rows:
        assert isinstance(row, tuple)
    assert verified_build.rows == built.result.rows


def test_specs_return_in_manifest_pin_order(built):
    verified_build = read_verified(built)
    assert tuple(
        feature_label_spec_pin(spec) for spec in verified_build.feature_specs
    ) == built.manifest.feature_specs
    assert tuple(
        feature_label_spec_pin(spec) for spec in verified_build.label_specs
    ) == built.manifest.label_specs


def test_split_result_rederived_from_rows(built):
    verified_build = read_verified(built)
    assert verified_build.split_result == built.result.split_result


def test_result_frozen(built):
    verified_build = read_verified(built)
    with pytest.raises(FrozenInstanceError):
        verified_build.dataset_id = "0" * 64


def test_manifest_payload_is_canonical(built):
    from market_vault.dataset.manifest import serialize_dataset_manifest

    verified_build = read_verified(built)
    assert verified_build.manifest_payload == serialize_dataset_manifest(
        verified_build.manifest
    )
    assert verified_build.manifest_payload == (
        built.build / DATASET_MANIFEST_FILENAME
    ).read_bytes()


def test_build_report_payload_is_canonical(built):
    from market_vault.dataset.reader_models import _report_payload_from_record
    from market_vault.dataset.artifact_serialization import _canonical_json_bytes

    verified_build = read_verified(built)
    assert verified_build.build_report_payload == _canonical_json_bytes(
        _report_payload_from_record(verified_build.build_report)
    )
    assert verified_build.build_report_payload == (
        built.build / DATASET_BUILD_REPORT_FILENAME
    ).read_bytes()


def test_replace_tamper_rejected(built):
    verified_build = read_verified(built)
    tampered = [
        lambda: replace(verified_build, reader_contract_version="x"),
        lambda: replace(verified_build, dataset_id="0" * 64),
        lambda: replace(verified_build, status=STATUS_EMPTY),
        lambda: replace(verified_build, rows=()),
        lambda: replace(verified_build, rows=verified_build.rows + verified_build.rows[:1]),
        lambda: replace(verified_build, rows=[row for row in verified_build.rows]),
        lambda: replace(verified_build, manifest_payload=b""),
        lambda: replace(verified_build, build_report_payload=b""),
        lambda: replace(
            verified_build,
            manifest=replace(
                verified_build.manifest, built_at=BUILT_AT + timedelta(seconds=1)
            ),
        ),
        lambda: replace(verified_build, feature_specs=(feature_spec(name="other"),)),
        lambda: replace(verified_build, label_specs=(label_spec(name="other"),)),
        lambda: replace(verified_build, build_path=Path("C:/elsewhere")),
        lambda: replace(verified_build, build_path=Path("relative")),
    ]
    for tamper in tampered:
        with pytest.raises(DatasetArtifactValidationError):
            tamper()


def test_replace_wrong_split_result_rejected(built):
    verified_build = read_verified(built)
    other_spec = chronological_spec(
        train_end_date=date(2026, 6, 1),
        validation_end_date=date(2026, 6, 2),
        test_end_date=date(2026, 6, 3),
    )
    from market_vault.dataset.reader_models import _split_samples_from_rows

    samples = _split_samples_from_rows(verified_build.rows, verified_build.schema)
    other_result = assign_chronological_splits(samples, other_spec)
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, split_result=other_result)


def test_replace_wrong_build_report_rejected(built):
    verified_build = read_verified(built)
    other_report = replace(
        verified_build.build_report, split_result_id="0" * 64
    )
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, build_report=other_report)


def test_no_mutable_containers_in_result(built):
    verified_build = read_verified(built)

    def assert_immutable(value, path):
        if isinstance(value, (dict, list, pa.Table, pd.DataFrame)):
            raise AssertionError(f"mutable container at {path}: {type(value)}")
        if isinstance(value, tuple):
            for index, item in enumerate(value):
                assert_immutable(item, f"{path}[{index}]")
        elif hasattr(value, "__dataclass_fields__"):
            for field in fields(value):
                if field.name == "assignment_rows":
                    # ChronologicalSplitResult.assignment_rows is the
                    # existing split layer's immutable tuple of mapping
                    # rows; it is a carried PR-4 model contract, not a
                    # mutable container of the reader result.
                    continue
                assert_immutable(getattr(value, field.name), f"{path}.{field.name}")

    assert_immutable(verified_build, "verified")


def test_model_valid_multi_row_rows_pass(built_multi):
    verified_build = read_verified(built_multi)
    assert len(verified_build.rows) == 2
    assert replace(verified_build, rows=verified_build.rows) == verified_build


def test_model_reversed_rows_rejected_despite_unchanged_content_id(built_multi):
    verified_build = read_verified(built_multi)
    reversed_rows = tuple(reversed(verified_build.rows))
    names = schema_names(verified_build.schema)
    mappings = tuple(dict(zip(names, row)) for row in reversed_rows)
    # logical_dataset_content_id is row-order-irrelevant by contract, so a
    # reversed row set keeps the exact same content ID...
    assert dataset_pkg.logical_dataset_content_id(
        verified_build.schema, mappings
    ) == verified_build.manifest.logical_dataset_content_id
    # ...and only the model's independent fixed-physical-order
    # self-validation can catch the tamper.
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, rows=reversed_rows)


def test_model_duplicate_sample_key_rejected(built_multi):
    verified_build = read_verified(built_multi)
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, rows=verified_build.rows + verified_build.rows[:1])


def test_model_scope_outer_code_rejected(built_multi):
    verified_build = read_verified(built_multi)
    names = schema_names(verified_build.schema)
    row = list(verified_build.rows[0])
    row[names.index("code")] = "US.XXX"
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, rows=(tuple(row), verified_build.rows[1]))


def test_model_dataset_as_of_value_tamper_rejected(built_as_of):
    verified_build = read_verified(built_as_of)
    names = schema_names(verified_build.schema)
    row = list(verified_build.rows[0])
    row[names.index("dataset_as_of")] = datetime(2000, 1, 1, tzinfo=UTC)
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, rows=(tuple(row),))


def test_model_built_at_normalized_equivalent_representation(built):
    verified_build = read_verified(built)
    equivalent = BUILT_AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    replaced = replace(verified_build, built_at=equivalent)
    assert replaced.built_at == verified_build.built_at == BUILT_AT


def test_model_naive_built_at_rejected(built):
    verified_build = read_verified(built)
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, built_at=datetime(2026, 8, 5, 12, 0))


def test_model_naive_dataset_as_of_rejected(built_as_of):
    verified_build = read_verified(built_as_of)
    with pytest.raises(DatasetArtifactValidationError):
        replace(verified_build, dataset_as_of=datetime(2026, 8, 1, 12, 0))


# ---------------------------------------------------------------------------
# C. Path safety.
# ---------------------------------------------------------------------------


def test_build_dir_symlink_rejected(built, tmp_path):
    link = tmp_path / built.result.dataset_id
    _make_symlink_or_skip(built.build, link)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(link)


def test_parent_symlink_rejected(built, tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    shutil.move(str(built.build), str(real_parent / built.result.dataset_id))
    link_parent = tmp_path / "linkparent"
    _make_symlink_or_skip(real_parent, link_parent)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(link_parent / built.result.dataset_id)


def test_nested_ancestor_symlink_rejected(built, tmp_path):
    real = tmp_path / "real" / "nested"
    real.mkdir(parents=True)
    shutil.move(str(built.build), str(real / built.result.dataset_id))
    link = tmp_path / "link"
    _make_symlink_or_skip(tmp_path / "real", link)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(link / "nested" / built.result.dataset_id)


def test_dot_dot_path_rejected(built, tmp_path, monkeypatch):
    monkeypatch.chdir(built.build.parent)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(Path("..") / built.build.parent.name / built.build.name)


def test_dot_path_rejected(built, tmp_path, monkeypatch):
    monkeypatch.chdir(built.build.parent)
    # The raw string form keeps the lexical "." component (pathlib would
    # strip it during joining); the reader must reject it.
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset("./" + built.build.name)


def test_uppercase_directory_name_rejected(built):
    renamed = built.build.with_name(built.build.name.upper())
    built.build.rename(renamed)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(renamed)


def test_ordinary_valid_path_passes(built):
    assert read_verified(built).dataset_id == built.result.dataset_id


def test_no_resolve_masking(built, tmp_path):
    # A symlinked ancestor that resolve() would hide is still rejected.
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    shutil.move(str(built.build), str(real_parent / built.result.dataset_id))
    link_parent = tmp_path / "masked"
    _make_symlink_or_skip(real_parent, link_parent)
    assert (link_parent / built.result.dataset_id).resolve() == (
        real_parent / built.result.dataset_id
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(link_parent / built.result.dataset_id)


def test_fifo_path_rejected(built, tmp_path):
    if os.name == "nt":
        pytest.skip("FIFO creation is not supported on Windows")
    path = tmp_path / ("f" * 64)
    os.mkfifo(path)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(path)


# ---------------------------------------------------------------------------
# D. _SUCCESS.
# ---------------------------------------------------------------------------


def test_success_valid_empty(built):
    assert read_verified(built).status == STATUS_COMPLETE


def test_success_missing(built):
    (built.build / DATASET_SUCCESS_FILENAME).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_success_newline_rejected(built):
    (built.build / DATASET_SUCCESS_FILENAME).write_bytes(b"\n")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_success_space_rejected(built):
    (built.build / DATASET_SUCCESS_FILENAME).write_bytes(b" ")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_success_bom_rejected(built):
    (built.build / DATASET_SUCCESS_FILENAME).write_bytes(b"\xef\xbb\xbf")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_success_directory_rejected(built):
    path = built.build / DATASET_SUCCESS_FILENAME
    path.unlink()
    path.mkdir()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_success_symlink_rejected(built, tmp_path):
    target = tmp_path / "empty"
    target.write_bytes(b"")
    link = built.build / DATASET_SUCCESS_FILENAME
    link.unlink()
    _make_symlink_or_skip(target, link)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_success_junction_rejected(built, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction required")
    import _winapi

    link = built.build / DATASET_SUCCESS_FILENAME
    link.unlink()
    target = tmp_path / "empty_dir"
    target.mkdir()
    _winapi.CreateJunction(str(target.absolute()), str(link.absolute()))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# E. Manifest.
# ---------------------------------------------------------------------------


def test_manifest_valid(built):
    assert read_verified(built).manifest == built.manifest


def test_manifest_corrupt_json(built):
    (built.build / DATASET_MANIFEST_FILENAME).write_text(
        "{not json", encoding="utf-8"
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_unknown_field(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__("extra", 1),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_missing_field(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.pop("output_files"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_unsupported_version(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__(
            "manifest_schema_version", "market-vault-dataset-manifest-v99"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_dataset_id_mismatch(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__("dataset_id", "0" * 64),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_directory_name_mismatch(built):
    renamed = built.build.with_name("c" * 64)
    built.build.rename(renamed)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(renamed)


def test_manifest_schema_id_mismatch(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__("dataset_schema_id", "0" * 64),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_identity_mismatch(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["scope"].__setitem__("symbols", ["US.XXX"]),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_status_row_count_mismatch(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__("status", STATUS_EMPTY),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_wrong_spec_kind(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["feature_specs"][0].__setitem__(
            "kind", "LABEL"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_wrong_serialization(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__("serialization_format", "csv"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_noncanonical_whitespace(built):
    path = built.build / DATASET_MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_pretty_print_rejected(built):
    path = built.build / DATASET_MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": ")),
        encoding="utf-8",
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_key_order_change_rejected(built):
    path = built.build / DATASET_MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    reordered = dict(reversed(list(payload.items())))
    path.write_text(
        json.dumps(reordered, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_trailing_whitespace_rejected(built):
    path = built.build / DATASET_MANIFEST_FILENAME
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_bom_rejected(built):
    path = built.build / DATASET_MANIFEST_FILENAME
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# F. Whitelist.
# ---------------------------------------------------------------------------


def test_valid_exact_layout(built):
    verified_build = read_verified(built)
    assert len(verified_build.rows) == built.manifest.logical_row_count


def test_missing_dataset(built):
    (built.build / DATASET_PARQUET_FILENAME).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_missing_report(built):
    (built.build / DATASET_BUILD_REPORT_FILENAME).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_missing_split(built):
    (built.build / DATASET_SPLIT_SPEC_FILENAME).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_missing_feature_spec(built):
    rel = built.manifest.feature_specs[0]
    filename = f"{rel.name}--{rel.version}--{rel.content_sha256}.yaml"
    (built.build / DATASET_FEATURE_SPECS_DIRNAME / filename).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_missing_label_spec(built):
    rel = built.manifest.label_specs[0]
    filename = f"{rel.name}--{rel.version}--{rel.content_sha256}.yaml"
    (built.build / DATASET_LABEL_SPECS_DIRNAME / filename).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_extra_file(built):
    (built.build / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_extra_directory(built):
    (built.build / "extra_dir").mkdir()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_second_parquet(built):
    shutil.copy(
        built.build / DATASET_PARQUET_FILENAME,
        built.build / "dataset2.parquet",
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


@pytest.mark.parametrize(
    "name",
    ["scratch.tmp", "backup.bak", "run.log", ".lock", "._SUCCESS.swp"],
)
def test_temp_backup_log_lock_files_rejected(built, name):
    (built.build / name).write_text("x", encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_ds_store_rejected(built):
    (built.build / ".DS_Store").write_bytes(b"x")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_thumbs_db_rejected(built):
    (built.build / "Thumbs.db").write_bytes(b"x")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_pycache_rejected(built):
    (built.build / "__pycache__").mkdir()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_nested_dataset_directory_rejected(built):
    nested = built.build / "nested"
    nested.mkdir()
    (nested / DATASET_PARQUET_FILENAME).write_bytes(b"x")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_symlink_entry_rejected(built, tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("x", encoding="utf-8")
    _make_symlink_or_skip(target, built.build / "outside.txt")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_junction_entry_rejected(built, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction required")
    import _winapi

    target = tmp_path / "outside_dir"
    target.mkdir()
    _winapi.CreateJunction(
        str(target.absolute()),
        str((built.build / "outside_dir").absolute()),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def _move_out_and_link(built, tmp_path, dirname: str, link_target) -> None:
    """Move a spec directory out of the build and place a link at its
    former path."""
    moved = tmp_path / f"moved_{dirname}"
    (built.build / dirname).rename(moved)
    _make_symlink_or_skip(link_target, built.build / dirname)


def test_feature_specs_symlink_rejected_before_descent(built, tmp_path, monkeypatch):
    """A feature_specs symlink pointing at an external directory with
    nested files must be rejected before any descent, and the link target
    must never be enumerated or read."""
    external = tmp_path / "external_feature_specs"
    (external / "nested").mkdir(parents=True)
    (external / "nested" / "deep.yaml").write_text("x")
    _move_out_and_link(built, tmp_path, DATASET_FEATURE_SPECS_DIRNAME, external)

    scanned = []
    real_scandir = os.scandir

    def spy_scandir(path, *args, **kwargs):
        scanned.append(os.fspath(path))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", spy_scandir)
    read_paths = []
    real_read = reader_mod._read_artifact_bytes

    def spy_read(path, *args, **kwargs):
        read_paths.append(os.fspath(path))
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(reader_mod, "_read_artifact_bytes", spy_read)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)
    assert str(external) not in scanned
    assert not any(str(external) in path for path in read_paths)


def test_label_specs_symlink_rejected_before_descent(built, tmp_path, monkeypatch):
    external = tmp_path / "external_label_specs"
    (external / "nested").mkdir(parents=True)
    (external / "nested" / "deep.yaml").write_text("x")
    _move_out_and_link(built, tmp_path, DATASET_LABEL_SPECS_DIRNAME, external)

    scanned = []
    real_scandir = os.scandir

    def spy_scandir(path, *args, **kwargs):
        scanned.append(os.fspath(path))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", spy_scandir)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)
    assert str(external) not in scanned


def test_feature_specs_junction_rejected_before_descent(built, tmp_path):
    """A real Windows junction at feature_specs must be rejected before
    any descent (Python 3.11 reparse-point path included)."""
    if os.name != "nt":
        pytest.skip("Windows junction required")
    import _winapi

    external = tmp_path / "external_feature_specs"
    external.mkdir()
    (external / "nested").mkdir()
    moved = tmp_path / "moved_feature_specs"
    (built.build / DATASET_FEATURE_SPECS_DIRNAME).rename(moved)
    _winapi.CreateJunction(
        str(external.absolute()),
        str((built.build / DATASET_FEATURE_SPECS_DIRNAME).absolute()),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_label_specs_junction_rejected_before_descent(built, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction required")
    import _winapi

    external = tmp_path / "external_label_specs"
    external.mkdir()
    (external / "nested").mkdir()
    moved = tmp_path / "moved_label_specs"
    (built.build / DATASET_LABEL_SPECS_DIRNAME).rename(moved)
    _winapi.CreateJunction(
        str(external.absolute()),
        str((built.build / DATASET_LABEL_SPECS_DIRNAME).absolute()),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_spec_directory_nested_subdirectory_rejected(built):
    nested = built.build / DATASET_FEATURE_SPECS_DIRNAME / "nested"
    nested.mkdir()
    (nested / "x.yaml").write_text("x")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_safe_enumerator_normal_two_level_layout(built):
    entries = reader_mod._list_verified_dataset_entries_safely(built.build)
    assert set(entries) == set(reader_mod._expected_build_entries(built.manifest))


# ---------------------------------------------------------------------------
# G. DatasetOutputFile records.
# ---------------------------------------------------------------------------


def test_output_records_six_field_equality(built):
    verified_build = read_verified(built)
    assert verified_build.manifest.output_files == built.manifest.output_files


def test_output_records_correct_hashes_sizes(built):
    verified_build = read_verified(built)
    for record in verified_build.manifest.output_files:
        path = built.build / record.relative_path
        assert path.stat().st_size == record.byte_size
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record.sha256


def test_output_record_wrong_relative_path(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"][0].__setitem__(
            "relative_path", "wrong.parquet"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_wrong_file_role(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"][0].__setitem__(
            "file_role", "wrong_role"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_wrong_content_role(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"][0].__setitem__(
            "content_role", "wrong_role"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_wrong_row_count(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"][0].__setitem__("row_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_wrong_byte_size(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"][0].__setitem__("byte_size", 1),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_wrong_sha256(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"][0].__setitem__(
            "sha256", "0" * 64
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_missing_record(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"].pop(0),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_output_record_extra_record(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["output_files"].append(
            {
                "relative_path": "manifest.json",
                "file_role": "manifest",
                "row_count": 1,
                "byte_size": 1,
                "sha256": "0" * 64,
                "content_role": "manifest",
            }
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_manifest_itself_not_recorded(built):
    payload = read_json(built.build / DATASET_MANIFEST_FILENAME)
    paths = [record["relative_path"] for record in payload["output_files"]]
    assert DATASET_MANIFEST_FILENAME not in paths
    assert DATASET_SUCCESS_FILENAME not in paths


def test_success_not_recorded(built):
    payload = read_json(built.build / DATASET_MANIFEST_FILENAME)
    paths = [record["relative_path"] for record in payload["output_files"]]
    assert DATASET_SUCCESS_FILENAME not in paths


# ---------------------------------------------------------------------------
# H. Spec artifacts.
# ---------------------------------------------------------------------------


def feature_artifact_path(build, pin) -> Path:
    return (
        build
        / DATASET_FEATURE_SPECS_DIRNAME
        / f"{pin.name}--{pin.version}--{pin.content_sha256}.yaml"
    )


def label_artifact_path(build, pin) -> Path:
    return (
        build
        / DATASET_LABEL_SPECS_DIRNAME
        / f"{pin.name}--{pin.version}--{pin.content_sha256}.yaml"
    )


def test_feature_artifact_parse_pin_canonical_filename(built):
    verified_build = read_verified(built)
    pin = built.manifest.feature_specs[0]
    assert feature_label_spec_pin(verified_build.feature_specs[0]) == pin
    assert feature_artifact_path(built.build, pin).is_file()
    from market_vault.dataset.artifact_serialization import feature_spec_artifact

    assert feature_artifact_path(built.build, pin).read_bytes() == (
        feature_spec_artifact(verified_build.feature_specs[0])
    )
    assert parse_feature_spec(
        feature_artifact_path(built.build, pin).read_text(encoding="utf-8")
    ) == verified_build.feature_specs[0]


def test_label_artifact_parse_pin_canonical_filename(built):
    verified_build = read_verified(built)
    pin = built.manifest.label_specs[0]
    assert feature_label_spec_pin(verified_build.label_specs[0]) == pin
    assert label_artifact_path(built.build, pin).is_file()
    from market_vault.dataset.artifact_serialization import label_spec_artifact

    assert label_artifact_path(built.build, pin).read_bytes() == (
        label_spec_artifact(verified_build.label_specs[0])
    )
    assert parse_label_spec(
        label_artifact_path(built.build, pin).read_text(encoding="utf-8")
    ) == verified_build.label_specs[0]


def test_split_artifact_parse_pin_canonical_kind(built):
    verified_build = read_verified(built)
    assert chronological_split_spec_pin(
        verified_build.split_spec
    ) == built.manifest.split_spec
    assert verified_build.split_spec.kind == "SPLIT"
    from market_vault.dataset.artifact_serialization import split_spec_artifact

    assert (built.build / DATASET_SPLIT_SPEC_FILENAME).read_bytes() == (
        split_spec_artifact(verified_build.split_spec)
    )


def test_feature_artifact_semantic_same_formatting_different_rejected(built):
    path = feature_artifact_path(built.build, built.manifest.feature_specs[0])
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_feature_artifact_comment_or_extra_newline_rejected(built):
    path = feature_artifact_path(built.build, built.manifest.feature_specs[0])
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_feature_label_swap_rejected(built):
    feature_pin = built.manifest.feature_specs[0]
    feature_file = feature_artifact_path(built.build, feature_pin)
    label_dir = built.build / DATASET_LABEL_SPECS_DIRNAME
    feature_file.rename(label_dir / feature_file.name)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_duplicate_semantic_artifact_rejected(built):
    feature_file = feature_artifact_path(
        built.build, built.manifest.feature_specs[0]
    )
    shutil.copy(feature_file, feature_file.parent / "copy.yaml")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_wrong_spec_filename_rejected(built):
    feature_file = feature_artifact_path(
        built.build, built.manifest.feature_specs[0]
    )
    feature_file.rename(feature_file.parent / "renamed.yaml")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# I. Schema derivation.
# ---------------------------------------------------------------------------


def test_rederived_schema_exact(built):
    verified_build = read_verified(built)
    rederived = dataset_orchestration_schema(
        verified_build.feature_specs,
        verified_build.label_specs,
        include_dataset_as_of=verified_build.dataset_as_of is not None,
    )
    assert rederived == verified_build.schema == built.result.schema
    assert verified_build.manifest.dataset_schema_id == (
        dataset_pkg.dataset_schema_id(verified_build.schema)
    )


def test_schema_field_order_and_types(built):
    verified_build = read_verified(built)
    expected_names = [
        "code",
        "sample_key",
        "sample_version_id",
        "feature_window_close",
        "actual_label_end_time",
        "label_status",
        "sr",
        "fr",
        "feature_window_close_date",
        "nominal_split",
        "final_split",
        "assignment_status",
        "reason_code",
        "purge_boundary",
    ]
    assert schema_names(verified_build.schema) == expected_names
    types = {field.name: field for field in verified_build.schema.fields}
    assert types["code"].logical_type == "string"
    assert types["feature_window_close"].logical_type == "timestamp_us_utc"
    assert types["fr"].logical_type == "float64"
    assert types["feature_window_close_date"].logical_type == "date32"
    assert types["sr"].nullable is False
    assert types["fr"].nullable is True
    assert types["actual_label_end_time"].nullable is True


def test_dataset_as_of_field_present(built_as_of):
    verified_build = read_verified(built_as_of)
    names = schema_names(verified_build.schema)
    assert "dataset_as_of" in names
    for row in verified_build.rows:
        assert row[names.index("dataset_as_of")] == built_as_of.result.dataset_as_of


def test_dataset_as_of_field_absent(built):
    verified_build = read_verified(built)
    assert "dataset_as_of" not in schema_names(verified_build.schema)


def test_feature_field_drift_rejected(built):
    path = feature_artifact_path(built.build, built.manifest.feature_specs[0])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["output"]["logical_type"] = "int64"
    path.write_text(canonical_dump(payload), encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_label_field_drift_rejected(built):
    path = label_artifact_path(built.build, built.manifest.label_specs[0])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["output"]["logical_type"] = "int64"
    path.write_text(canonical_dump(payload), encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_fixed_field_missing_rejected(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["schema"]["fields"].__delitem__(0),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_extra_schema_field_rejected(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload["schema"]["fields"].append(
            {"name": "extra", "logical_type": "string", "nullable": True}
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# J. Parquet.
# ---------------------------------------------------------------------------


def test_parquet_exact_arrow_schema_and_rows(built):
    verified_build = read_verified(built)
    table = pq.read_table(built.build / DATASET_PARQUET_FILENAME)
    from market_vault.dataset.artifact_serialization import (
        _dataset_schema_to_arrow,
    )

    expected = _dataset_schema_to_arrow(
        verified_build.schema,
        dataset_id=verified_build.dataset_id,
        dataset_schema_id_value=verified_build.manifest.dataset_schema_id,
        logical_dataset_content_id_value=verified_build.manifest.logical_dataset_content_id,
        serialization_format_version=verified_build.manifest.serialization_format_version,
        row_order=DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
    )
    assert table.schema == expected
    assert table.num_rows == verified_build.manifest.logical_row_count
    assert verified_build.rows == built.result.rows


def test_parquet_metadata_exact(built):
    table = pq.read_table(built.build / DATASET_PARQUET_FILENAME)
    metadata = {
        key.decode("utf-8"): value.decode("utf-8")
        for key, value in (table.schema.metadata or {}).items()
    }
    assert metadata == {
        "market_vault.dataset_id": built.result.dataset_id,
        "market_vault.dataset_schema_id": built.result.dataset_schema_id,
        "market_vault.logical_dataset_content_id": built.result.logical_dataset_content_id,
        "market_vault.serialization_format_version": SERIALIZATION_FORMAT_VERSION_PARQUET,
        "market_vault.row_order": DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY,
        "market_vault.materializer_version": DATASET_MATERIALIZER_VERSION,
    }


def test_parquet_metadata_extra_rejected(built):
    with_metadata(built.build, lambda metadata: metadata.__setitem__(b"extra.key", b"x"))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_metadata_missing_rejected(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.pop(b"market_vault.dataset_id"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_dataset_id_metadata_mismatch(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.__setitem__(
            b"market_vault.dataset_id", b"0" * 64
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_schema_id_metadata_mismatch(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.__setitem__(
            b"market_vault.dataset_schema_id", b"0" * 64
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_content_id_metadata_mismatch(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.__setitem__(
            b"market_vault.logical_dataset_content_id", b"0" * 64
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_materializer_version_metadata_mismatch(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.__setitem__(
            b"market_vault.materializer_version", b"other"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_row_order_metadata_mismatch(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.__setitem__(
            b"market_vault.row_order", b"OTHER_ORDER"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_row_count_mismatch(built):
    rewrite_parquet(
        built.build,
        lambda table: table.take(pa.array([], type=pa.int64())),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_wrong_column_order(built):
    def writer(table):
        order = list(range(table.num_columns))
        order[0], order[1] = order[1], order[0]
        return pa.Table.from_arrays(
            [table.column(i) for i in order],
            schema=pa.schema(
                [table.schema.field(i) for i in order],
                metadata=table.schema.metadata,
            ),
        )

    rewrite_parquet(built.build, writer)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_wrong_dtype(built):
    cast_column(built.build, "sr", pa.int64())
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_wrong_nullability(built):
    def writer(table):
        idx = table.schema.get_field_index("sr")
        old = table.schema.field(idx)
        new_field = pa.field(old.name, old.type, nullable=True)
        new_schema = pa.schema(
            [new_field if i == idx else table.schema.field(i) for i in range(table.num_columns)],
            metadata=table.schema.metadata,
        )
        return pa.Table.from_arrays(
            [table.column(i) for i in range(table.num_columns)], schema=new_schema
        )

    rewrite_parquet(built.build, writer)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_pandas_metadata_rejected(built):
    with_metadata(
        built.build,
        lambda metadata: metadata.__setitem__(
            b"pandas", json.dumps({"pandas_version": "2.2.0"}).encode("utf-8")
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_dictionary_string_rejected(built):
    def writer(table):
        idx = table.schema.get_field_index("code")
        dict_type = pa.dictionary(pa.int32(), pa.string())
        new_field = pa.field("code", dict_type, nullable=False)
        new_schema = pa.schema(
            [new_field if i == idx else table.schema.field(i) for i in range(table.num_columns)],
            metadata=table.schema.metadata,
        )
        arrays = [
            table.column(i).cast(dict_type) if i == idx else table.column(i)
            for i in range(table.num_columns)
        ]
        return pa.Table.from_arrays(arrays, schema=new_schema)

    rewrite_parquet(built.build, writer)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_corrupt(built):
    path = built.build / DATASET_PARQUET_FILENAME
    path.write_bytes(b"not a parquet file")
    refresh_parquet_facts(built.build)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_nan_rejected(built):
    rewrite_from_pylist(
        built.build, lambda rows: rows.__setitem__(0, {**rows[0], "sr": float("nan")})
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_positive_infinity_rejected(built):
    rewrite_from_pylist(
        built.build, lambda rows: rows.__setitem__(0, {**rows[0], "sr": float("inf")})
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_negative_infinity_rejected(built):
    rewrite_from_pylist(
        built.build, lambda rows: rows.__setitem__(0, {**rows[0], "sr": float("-inf")})
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_parquet_scalar_types_readback(built):
    verified_build = read_verified(built)
    names = schema_names(verified_build.schema)
    row = verified_build.rows[0]
    mapping = dict(zip(names, row))
    assert isinstance(mapping["code"], str)
    assert isinstance(mapping["sample_key"], str)
    assert isinstance(mapping["feature_window_close"], datetime)
    assert mapping["feature_window_close"].tzinfo is not None
    assert mapping["actual_label_end_time"].tzinfo is not None
    assert isinstance(mapping["feature_window_close_date"], date)
    assert type(mapping["feature_window_close_date"]) is not datetime
    assert isinstance(mapping["sr"], float)
    assert isinstance(mapping["fr"], float)
    assert isinstance(mapping["label_status"], str)
    assert isinstance(mapping["assignment_status"], str)
    assert mapping["fr"] == built.result.rows[0][names.index("fr")]


def test_parquet_null_contract(built):
    verified_build = read_verified(built)
    names = schema_names(verified_build.schema)
    for row in verified_build.rows:
        mapping = dict(zip(names, row))
        assert mapping["fr"] is not None  # COMPLETE label row
        assert mapping["actual_label_end_time"] is not None


def test_parquet_feature_null_rejected(built):
    # A null in a non-nullable Feature column cannot be written by the
    # pyarrow writer at all (both table and parquet writers fail closed),
    # so no such artifact can exist. The reader's rejection boundary is
    # the content identity validation it re-runs on every row: a null in
    # a non-nullable field fails closed.
    verified_build = read_verified(built)
    names = schema_names(verified_build.schema)
    row = list(verified_build.rows[0])
    row[names.index("sr")] = None
    mappings = tuple(dict(zip(names, row)) for _ in (0,))
    with pytest.raises(DatasetError):
        dataset_pkg.logical_dataset_content_id(verified_build.schema, mappings)


def test_parquet_logical_content_recomputed(built):
    verified_build = read_verified(built)
    mappings = tuple(
        dict(zip(schema_names(verified_build.schema), row))
        for row in verified_build.rows
    )
    assert (
        dataset_pkg.logical_dataset_content_id(verified_build.schema, mappings)
        == verified_build.manifest.logical_dataset_content_id
    )


# ---------------------------------------------------------------------------
# K. Physical rows and sample contract.
# ---------------------------------------------------------------------------


def test_correct_physical_sort(built_multi):
    verified_build = read_verified(built_multi)
    names = schema_names(verified_build.schema)
    rows = verified_build.rows
    assert len(rows) == 2
    assert rows == tuple(
        sorted(
            rows,
            key=lambda row: (
                row[names.index("code")],
                row[names.index("feature_window_close")],
                row[names.index("sample_key")],
            ),
        )
    )


def test_code_out_of_order_rejected(built_multi):
    permute_rows(built_multi.build, [1, 0])
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built_multi.build)


def test_close_out_of_order_rejected(built_multi):
    permute_rows(built_multi.build, [1, 0])
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built_multi.build)


def test_sample_key_out_of_order_rejected(built_multi):
    permute_rows(built_multi.build, [1, 0])
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built_multi.build)


def test_duplicate_sample_key_rejected(built_multi):
    permute_rows(built_multi.build, [0, 0])
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built_multi.build)


def test_scope_outer_code_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(0, {**rows[0], "code": "US.XXX"}),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


@pytest.fixture
def built_as_of(fixtures, tmp_path):
    # The archive clock cutoff must be after the canonical build archives
    # (created_at 2026-08-04 12:00 UTC); 2026-08-01 keeps every sample.
    dataset_as_of = datetime(2026, 8, 1, tzinfo=UTC)
    result, mresult = materialize_once(
        fixtures, tmp_path, dataset_as_of=dataset_as_of
    )
    build = build_path(mresult)
    manifest = dataset_pkg.validate_dataset_manifest(
        (build / DATASET_MANIFEST_FILENAME).read_bytes()
    )
    return SimpleNamespace(
        result=result, mresult=mresult, build=build, manifest=manifest
    )


def test_dataset_as_of_row_mismatch_rejected(built_as_of):
    rewrite_from_pylist(
        built_as_of.build,
        lambda rows: rows.__setitem__(
            0, {**rows[0], "dataset_as_of": datetime(2000, 1, 1, tzinfo=UTC)}
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built_as_of.build)


def test_dataset_as_of_field_wrong_presence_rejected(built):
    tamper_json(
        built.build / DATASET_MANIFEST_FILENAME,
        lambda payload: payload.__setitem__(
            "dataset_as_of", "2026-07-01T13:40:00+00:00"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_physical_rows_match_orchestration_rows(built):
    verified_build = read_verified(built)
    assert verified_build.rows == built.result.rows


# ---------------------------------------------------------------------------
# L. Split re-derivation.
# ---------------------------------------------------------------------------


def test_split_samples_reconstructed_from_rows(built):
    from market_vault.dataset.split_models import ChronologicalSplitSample

    verified_build = read_verified(built)
    names = schema_names(verified_build.schema)
    samples = tuple(
        ChronologicalSplitSample(
            sample_key=row[names.index("sample_key")],
            sample_version_id=row[names.index("sample_version_id")],
            feature_window_close=row[names.index("feature_window_close")],
            label_status=row[names.index("label_status")],
            actual_label_end_time=row[names.index("actual_label_end_time")],
        )
        for row in verified_build.rows
    )
    rederived = assign_chronological_splits(samples, verified_build.split_spec)
    assert rederived == verified_build.split_result


def test_split_assignments_correct(built):
    verified_build = read_verified(built)
    names = schema_names(verified_build.schema)
    for row, assignment in zip(verified_build.rows, verified_build.split_result.assignments):
        mapping = dict(zip(names, row))
        assert mapping["sample_key"] == assignment.sample_key
        assert mapping["feature_window_close_date"] == assignment.feature_window_close_date
        assert mapping["nominal_split"] == assignment.nominal_split
        assert mapping["final_split"] == assignment.final_split
        assert mapping["assignment_status"] == assignment.assignment_status
        assert mapping["reason_code"] == assignment.reason_code
        assert mapping["purge_boundary"] == assignment.purge_boundary
        assert assignment.assignment_status == SPLIT_STATUS_ASSIGNED


def test_nominal_split_tamper_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(
            0, {**rows[0], "nominal_split": SPLIT_STATUS_PURGED}
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_final_split_tamper_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(0, {**rows[0], "final_split": "TEST"}),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_assignment_status_tamper_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(
            0, {**rows[0], "assignment_status": SPLIT_STATUS_EXCLUDED}
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_reason_code_tamper_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(
            0,
            {
                **rows[0],
                "reason_code": REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
            },
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_purge_boundary_tamper_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(
            0,
            {
                **rows[0],
                "purge_boundary": datetime(2026, 7, 1, 4, 0, tzinfo=UTC),
            },
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_feature_close_date_tamper_rejected(built):
    rewrite_from_pylist(
        built.build,
        lambda rows: rows.__setitem__(
            0,
            {
                **rows[0],
                "feature_window_close_date": date(2026, 6, 30),
            },
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_split_result_id_tamper_rejected(built):
    rewrite_report(
        built.build, lambda payload: payload.__setitem__("split_result_id", "0" * 64)
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_assigned_count_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("assigned_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_purged_count_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("purged_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_excluded_count_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("excluded_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_split_sample_count_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("split_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_split_spec_content_id_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("split_spec_content_id", "0" * 64),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_incomplete_label_exclusion_case(fixtures, tmp_path):
    result = orchestrate(
        fixtures,
        requests=[request()],
        builds=[fixtures.a, fixtures.fmin],
    )
    assignment = result.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_EXCLUDED
    assert assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    verified_build = load_verified_dataset(mresult.build_path)
    names = schema_names(verified_build.schema)
    mapping = dict(zip(names, verified_build.rows[0]))
    assert mapping["label_status"] == LABEL_STATUS_INCOMPLETE
    assert mapping["fr"] is None
    assert mapping["assignment_status"] == SPLIT_STATUS_EXCLUDED
    assert mapping["reason_code"] == REASON_CODE_INCOMPLETE_LABEL
    assert verified_build.split_result.diagnostics.excluded_count == 1
    assert verified_build.build_report.excluded_sample_count == 1


def test_purge_case(fixtures, tmp_path, monkeypatch):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [fixtures.c],
        [request(
            anchor=date(2026, 6, 30),
            f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC),
            f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC),
        )],
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=datetime(2026, 7, 1, 5, 0, tzinfo=UTC),
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    result = orchestrate(
        fixtures,
        requests=[request(
            anchor=date(2026, 6, 30),
            f_start=datetime(2026, 6, 30, 13, 30, tzinfo=UTC),
            f_close=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_start=datetime(2026, 6, 30, 13, 35, tzinfo=UTC),
            l_close=datetime(2026, 6, 30, 13, 36, tzinfo=UTC),
        )],
        builds=[fixtures.c],
        scope=dataset_scope(trade_dates=(date(2026, 6, 30),)),
    )
    assignment = result.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.purge_boundary == datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    verified_build = load_verified_dataset(mresult.build_path)
    names = schema_names(verified_build.schema)
    mapping = dict(zip(names, verified_build.rows[0]))
    assert mapping["assignment_status"] == SPLIT_STATUS_PURGED
    assert mapping["purge_boundary"] == datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    assert verified_build.split_result.assignments[0].assignment_status == (
        SPLIT_STATUS_PURGED
    )
    assert verified_build.build_report.purged_sample_count == 1


def _dst_fixture_build(fixtures, *, trade_date: date, run_id: str) -> None:
    cfg = settings(Path(fixtures.root))
    calendar(cfg, trade_date=trade_date)
    # 12 minutes (09:30-09:41 local) cover the feature window and the
    # BARS-horizon label window of the DST requests.
    write_snapshot(
        cfg,
        code="US.MU",
        trade_date=trade_date,
        run_id=run_id,
        time_keys=minute_keys(f"{trade_date.isoformat()} 09:30:00", 12),
        closes=[100.0, 110.0, 112.0, 118.0, 120.0, 110.0] * 2,
        run_finished_at=datetime(trade_date.year, trade_date.month, trade_date.day, 14, 0, tzinfo=UTC),
    )
    return verified(materialize(cfg, symbols=["US.MU"], trade_dates=[trade_date]))


def _dst_request(*, anchor: date) -> PITSampleRequest:
    # The US session opens 09:30 local; the feature window is
    # [09:30, 09:36) and the label window [09:36, 09:42) converted to UTC
    # through the declared boundary timezone (the UTC offset differs per
    # DST date: EST on the spring date, EDT on the fall date).
    ny = ZoneInfo(NY)
    local_open = datetime(anchor.year, anchor.month, anchor.day, 9, 30, tzinfo=ny)
    f_start = local_open.astimezone(UTC)
    f_close = f_start + timedelta(minutes=6)
    return request(
        anchor=anchor,
        f_start=f_start,
        f_close=f_close,
        l_start=f_close,
        l_close=f_close + timedelta(minutes=6),
    )


def _dst_orchestrate(
    fixtures, dst_build, monkeypatch, *, anchor, split_spec, actual_end
):
    spec = label_spec()
    pins = real_label_pins(fixtures, spec)
    pit = assemble_point_in_time_samples(
        [dst_build], [_dst_request(anchor=anchor)]
    )
    stub = stub_label_result(
        [
            hand_label_sample(
                pit.samples[0],
                spec,
                pins[0],
                status=LABEL_STATUS_COMPLETE,
                actual_end=actual_end,
                value=1.0,
            )
        ],
        spec,
        pins,
    )
    monkeypatch.setattr(
        orch_mod, "execute_builtin_labels", lambda *a, **k: stub
    )
    return orchestrate(
        fixtures,
        requests=[_dst_request(anchor=anchor)],
        builds=[dst_build],
        split_spec=split_spec,
        scope=dataset_scope(trade_dates=(anchor,)),
    )


def test_dst_spring_forward_boundary_case(fixtures, tmp_path, monkeypatch):
    # America/New_York springs forward 2026-03-08 02:00 -> 03:00. The next
    # local midnight after 2026-03-07 is 2026-03-08 00:00 EST = 05:00 UTC,
    # never the +24h instant 04:00 UTC.
    dst_build = _dst_fixture_build(
        fixtures, trade_date=date(2026, 3, 6), run_id="run-spring"
    )
    spec = chronological_spec(
        train_end_date=date(2026, 3, 7),
        validation_end_date=date(2026, 3, 30),
        test_end_date=date(2026, 4, 30),
    )
    anchor = date(2026, 3, 6)

    def build_and_read(actual_end):
        result = _dst_orchestrate(
            fixtures, dst_build, monkeypatch,
            anchor=anchor, split_spec=spec,
            actual_end=actual_end,
        )
        mresult = materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
        return load_verified_dataset(mresult.build_path)

    # 2026-03-08 04:30 UTC is 2026-03-07 23:30 EST: still before the next
    # local midnight, so the TRAIN sample is kept.
    kept = build_and_read(datetime(2026, 3, 8, 4, 30, tzinfo=UTC))
    assert kept.split_result.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED
    assert kept.split_result.assignments[0].purge_boundary is None
    assert kept.build_report.assigned_sample_count == 1

    # Exactly at 2026-03-08 00:00 EST = 05:00 UTC: purged.
    purged = build_and_read(datetime(2026, 3, 8, 5, 0, tzinfo=UTC))
    assignment = purged.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.purge_boundary == datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
    assert (
        assignment.reason_code
        == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
    )
    assert purged.build_report.purged_sample_count == 1


def test_dst_fall_back_boundary_case(fixtures, tmp_path, monkeypatch):
    # America/New_York falls back 2026-11-01 02:00 -> 01:00. The next local
    # midnight after 2026-10-31 is the first occurrence 2026-11-01 00:00 EDT
    # = 04:00 UTC, never the +24h instant 05:00 UTC.
    dst_build = _dst_fixture_build(
        fixtures, trade_date=date(2026, 10, 30), run_id="run-fall"
    )
    spec = chronological_spec(
        train_end_date=date(2026, 10, 31),
        validation_end_date=date(2026, 11, 29),
        test_end_date=date(2026, 12, 31),
    )
    anchor = date(2026, 10, 30)

    def build_and_read(actual_end):
        result = _dst_orchestrate(
            fixtures, dst_build, monkeypatch,
            anchor=anchor, split_spec=spec,
            actual_end=actual_end,
        )
        mresult = materialize_dataset_artifacts(
            result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
        )
        return load_verified_dataset(mresult.build_path)

    # 2026-11-01 04:30 UTC is 2026-11-01 00:30 EST: after the first-occurrence
    # local midnight, so the TRAIN sample is purged at 04:00 UTC.
    purged = build_and_read(datetime(2026, 11, 1, 4, 30, tzinfo=UTC))
    assignment = purged.split_result.assignments[0]
    assert assignment.assignment_status == SPLIT_STATUS_PURGED
    assert assignment.purge_boundary == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)

    # One microsecond before: 2026-10-31 23:59:59.999999 EDT, kept.
    kept = build_and_read(
        datetime(2026, 11, 1, 3, 59, 59, 999999, tzinfo=UTC)
    )
    assert kept.split_result.assignments[0].assignment_status == SPLIT_STATUS_ASSIGNED


def test_no_feature_or_label_reexecution(fixtures, tmp_path, monkeypatch):
    result = orchestrate(fixtures, requests=[request()])
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )

    def fail(*args, **kwargs):
        raise AssertionError("layer must not be re-executed by the reader")

    for module, name in (
        (mat_mod, "materialize_dataset_artifacts"),
        (orch_mod, "orchestrate_dataset_build"),
        (orch_mod, "assemble_point_in_time_samples"),
        (orch_mod, "execute_builtin_features"),
        (orch_mod, "execute_builtin_labels"),
    ):
        monkeypatch.setattr(module, name, fail)
    verified_build = load_verified_dataset(mresult.build_path)
    assert verified_build.dataset_id == result.dataset_id


# ---------------------------------------------------------------------------
# M. Build report.
# ---------------------------------------------------------------------------


def test_build_report_typed_record_fields(built):
    verified_build = read_verified(built)
    report = verified_build.build_report
    assert report.report_schema_version == DATASET_BUILD_REPORT_SCHEMA_VERSION
    assert report.materializer_version == DATASET_MATERIALIZER_VERSION
    assert report.dataset_id == verified_build.dataset_id
    assert report.dataset_kind == DATASET_KIND_SUPERVISED
    assert report.status == STATUS_COMPLETE
    assert report.built_at == BUILT_AT
    assert report.dataset_as_of is None
    assert report.dataset_schema_id == verified_build.manifest.dataset_schema_id
    assert (
        report.logical_dataset_content_id
        == verified_build.manifest.logical_dataset_content_id
    )
    assert report.logical_row_count == len(verified_build.rows)
    assert report.orchestration_contract_version == (
        DATASET_ORCHESTRATION_CONTRACT_VERSION
    )
    assert report.row_order == DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY
    assert report.manifest_schema_version == DATASET_MANIFEST_SCHEMA_VERSION
    assert report.serialization_format == SERIALIZATION_FORMAT_PARQUET
    assert report.serialization_format_version == (
        SERIALIZATION_FORMAT_VERSION_PARQUET
    )
    assert report.feature_spec_count == 1
    assert report.label_spec_count == 1
    assert report.canonical_build_pin_count == len(
        verified_build.manifest.canonical_builds
    )
    assert report.canonical_row_version_count == len(
        verified_build.manifest.canonical_row_version_ids
    )
    assert report.split_spec_content_id == (
        chronological_split_spec_pin(verified_build.split_spec).content_sha256
    )
    assert report.split_result_id == verified_build.split_result.split_result_id
    assert report.split_sample_count == len(verified_build.rows)
    layout = report.output_layout
    assert layout.dataset_parquet_filename == DATASET_PARQUET_FILENAME
    assert layout.manifest_filename == DATASET_MANIFEST_FILENAME
    assert layout.build_report_filename == DATASET_BUILD_REPORT_FILENAME
    assert layout.split_spec_filename == DATASET_SPLIT_SPEC_FILENAME
    assert layout.success_filename == DATASET_SUCCESS_FILENAME
    assert layout.feature_specs_dirname == DATASET_FEATURE_SPECS_DIRNAME
    assert layout.label_specs_dirname == DATASET_LABEL_SPECS_DIRNAME


def test_build_report_canonical_bytes(built):
    path = built.build / DATASET_BUILD_REPORT_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_bytes() == canonical_dump(payload).encode("utf-8")


def test_build_report_schema_version_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("report_schema_version", "v2"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_materializer_version_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("materializer_version", "v2"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_dataset_id_tamper_rejected(built):
    rewrite_report(
        built.build, lambda payload: payload.__setitem__("dataset_id", "0" * 64)
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_dataset_kind_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("dataset_kind", "UNSUPERVISED"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_status_tamper_rejected(built):
    rewrite_report(
        built.build, lambda payload: payload.__setitem__("status", STATUS_EMPTY)
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_built_at_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__(
            "built_at", "2026-08-05T12:00:01+00:00"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_dataset_as_of_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__(
            "dataset_as_of", "2026-07-01T13:40:00+00:00"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_schema_id_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("dataset_schema_id", "0" * 64),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_content_id_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("logical_dataset_content_id", "0" * 64),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_row_count_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("logical_row_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_orchestration_version_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__(
            "orchestration_contract_version", "v2"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_row_order_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("row_order", "OTHER"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_manifest_version_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("manifest_schema_version", "v2"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_serialization_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("serialization_format", "csv"),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_spec_counts_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("feature_spec_count", 99),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_canonical_counts_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("canonical_build_pin_count", 99),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_completion_counts_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("completion_complete_key_count", 99),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_output_layout_tamper_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload["output_layout"].__setitem__(
            "success_filename", "OTHER"
        ),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_extra_field_rejected(built):
    rewrite_report(
        built.build, lambda payload: payload.__setitem__("extra", 1)
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_missing_field_rejected(built):
    rewrite_report(
        built.build, lambda payload: payload.pop("output_layout")
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_negative_count_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("logical_row_count", -1),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_bool_count_rejected(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("logical_row_count", True),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_noncanonical_whitespace_rejected(built):
    path = built.build / DATASET_BUILD_REPORT_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_bom_rejected(built):
    path = built.build / DATASET_BUILD_REPORT_FILENAME
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_build_report_corrupt_json_rejected(built):
    (built.build / DATASET_BUILD_REPORT_FILENAME).write_text(
        "{not json", encoding="utf-8"
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_report_observable_facts_still_bound_after_canonical_rewrite(built):
    # A canonically rewritten report with a wrong observable fact is still
    # rejected even though every byte-hash and shape check passes.
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("assigned_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# N. Diagnostics boundary.
# ---------------------------------------------------------------------------


def test_diagnostics_matrix_reconstructed(built):
    verified_build = read_verified(built)
    report = verified_build.build_report
    diagnostics = DatasetOrchestrationDiagnostics(
        scope=verified_build.manifest.scope,
        request_count=report.request_count,
        pit_sample_count=report.pit_sample_count,
        feature_complete_sample_count=report.feature_complete_sample_count,
        feature_excluded_sample_count=report.feature_excluded_sample_count,
        label_complete_sample_count=report.label_complete_sample_count,
        label_incomplete_sample_count=report.label_incomplete_sample_count,
        split_sample_count=report.split_sample_count,
        assigned_sample_count=report.assigned_sample_count,
        purged_sample_count=report.purged_sample_count,
        excluded_sample_count=report.excluded_sample_count,
        logical_row_count=report.logical_row_count,
        completion_complete_key_count=report.completion_complete_key_count,
        completion_incomplete_key_count=report.completion_incomplete_key_count,
        completion_missing_key_count=report.completion_missing_key_count,
    )
    assert diagnostics.pit_sample_count == (
        report.feature_complete_sample_count + report.feature_excluded_sample_count
    )
    assert diagnostics.pit_sample_count == (
        report.label_complete_sample_count + report.label_incomplete_sample_count
    )
    assert diagnostics.split_sample_count == report.feature_complete_sample_count
    assert diagnostics.split_sample_count == (
        report.assigned_sample_count
        + report.purged_sample_count
        + report.excluded_sample_count
    )
    assert diagnostics.logical_row_count == report.split_sample_count
    assert (
        report.completion_complete_key_count
        + report.completion_incomplete_key_count
        + report.completion_missing_key_count
        == len(verified_build.manifest.scope.symbols)
        * len(verified_build.manifest.scope.trade_dates)
    )


def test_pit_equals_feature_complete_plus_excluded(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("feature_excluded_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_split_equals_assigned_plus_purged_plus_excluded(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("assigned_sample_count", 999),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_completion_key_counts_sum_to_scope(built):
    rewrite_report(
        built.build,
        lambda payload: payload.__setitem__("completion_missing_key_count", 99),
    )
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# O. No-write guarantee.
# ---------------------------------------------------------------------------


def build_snapshot(build: Path) -> dict:
    hashes = file_hashes(build)
    mtimes = {}
    entries = set()
    for root, dirs, files in os.walk(build):
        for name in dirs + files:
            path = Path(root) / name
            rel = path.relative_to(build).as_posix()
            entries.add(rel)
            mtimes[rel] = path.stat().st_mtime_ns
    return {"hashes": hashes, "mtimes": mtimes, "entries": entries}


def assert_build_unchanged(before: dict, build: Path) -> None:
    after = build_snapshot(build)
    assert after == before


def test_successful_read_no_write(built):
    before = build_snapshot(built.build)
    read_verified(built)
    assert_build_unchanged(before, built.build)


def test_failed_read_no_write(built):
    before = build_snapshot(built.build)
    (built.build / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)
    # The extra file is still there (never deleted); nothing else changed.
    after = build_snapshot(built.build)
    assert set(after["entries"]) - set(before["entries"]) == {"extra.txt"}
    for rel, digest in before["hashes"].items():
        assert after["hashes"][rel] == digest
    for rel, mtime in before["mtimes"].items():
        assert after["mtimes"][rel] == mtime


def test_no_filesystem_mutators_called(built, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("filesystem mutator must not be called")

    for module, name in (
        (os, "mkdir"),
        (os, "makedirs"),
        (os, "unlink"),
        (os, "rmdir"),
        (os, "rename"),
        (os, "replace"),
        (os, "utime"),
        (shutil, "rmtree"),
        (shutil, "copy"),
        (shutil, "move"),
    ):
        monkeypatch.setattr(module, name, fail)
    read_verified(built)


def test_cwd_unchanged(built):
    before = Path.cwd()
    read_verified(built)
    assert Path.cwd() == before


def test_environment_does_not_affect_result(built, monkeypatch):
    baseline = read_verified(built)
    monkeypatch.setenv("MARKET_VAULT_READER_OVERRIDE", "1")
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    again = read_verified(built)
    assert again == baseline


def test_repeated_read_deterministic(built):
    first = read_verified(built)
    second = read_verified(built)
    assert second == first


# ---------------------------------------------------------------------------
# P. Error boundary.
# ---------------------------------------------------------------------------


def test_dataset_error_wrapped_with_cause(built):
    (built.build / DATASET_MANIFEST_FILENAME).write_text(
        "{not json", encoding="utf-8"
    )
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    assert excinfo.value.__cause__ is not None
    assert isinstance(excinfo.value.__cause__, DatasetError)


def test_materialization_error_wrapped(built):
    (built.build / DATASET_PARQUET_FILENAME).write_bytes(b"junk")
    refresh_parquet_facts(built.build)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    cause = excinfo.value.__cause__
    while cause is not None and not isinstance(
        cause, DatasetMaterializationError
    ):
        cause = cause.__cause__
    assert isinstance(cause, DatasetMaterializationError)


def test_spec_error_wrapped(built):
    rel = f"{DATASET_FEATURE_SPECS_DIRNAME}/sr--v1--{built.manifest.feature_specs[0].content_sha256}.yaml"
    path = feature_artifact_path(built.build, built.manifest.feature_specs[0])
    path.write_text("kind: FEATURE\n  bad_indent: [", encoding="utf-8")
    refresh_artifact_facts(built.build, rel)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    assert isinstance(excinfo.value.__cause__, SpecValidationError)


def test_split_error_wrapped(built, monkeypatch):
    def fail(*args, **kwargs):
        raise SplitValidationError("boom")

    monkeypatch.setattr(reader_mod, "assign_chronological_splits", fail)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    assert isinstance(excinfo.value.__cause__, SplitValidationError)


def test_os_error_wrapped(built, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(reader_mod, "_read_artifact_bytes", fail)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_unicode_error_wrapped(built):
    rel = f"{DATASET_FEATURE_SPECS_DIRNAME}/sr--v1--{built.manifest.feature_specs[0].content_sha256}.yaml"
    path = feature_artifact_path(built.build, built.manifest.feature_specs[0])
    path.write_bytes(b"\xff\xfe\x00bad")
    refresh_artifact_facts(built.build, rel)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    cause = excinfo.value.__cause__
    while cause is not None and not isinstance(cause, UnicodeError):
        cause = cause.__cause__
    assert isinstance(cause, UnicodeError)


def test_json_error_wrapped(built):
    (built.build / DATASET_BUILD_REPORT_FILENAME).write_text(
        "{not json", encoding="utf-8"
    )
    refresh_artifact_facts(built.build, DATASET_BUILD_REPORT_FILENAME)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    cause = excinfo.value.__cause__
    while cause is not None and not isinstance(cause, json.JSONDecodeError):
        cause = cause.__cause__
    assert isinstance(cause, json.JSONDecodeError)


def test_arrow_error_wrapped(built, monkeypatch):
    def fail(*args, **kwargs):
        raise pa.ArrowInvalid("boom")

    monkeypatch.setattr(reader_mod, "read_dataset_parquet", fail)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    assert isinstance(excinfo.value.__cause__, pa.ArrowException)


def test_already_wrapped_not_double_wrapped(built, monkeypatch):
    expected = DatasetArtifactValidationError("already wrapped")

    def fail(*args, **kwargs):
        raise expected

    monkeypatch.setattr(reader_mod, "_read_artifact_bytes", fail)
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        load_verified_dataset(built.build)
    assert excinfo.value is expected


def test_programming_error_not_swallowed(built, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr(
        reader_mod, "_list_verified_dataset_entries_safely", fail
    )
    with pytest.raises(RuntimeError):
        load_verified_dataset(built.build)


def test_no_partial_result(built):
    before = build_snapshot(built.build)
    (built.build / DATASET_PARQUET_FILENAME).unlink()
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)
    after = build_snapshot(built.build)
    # Only the intentionally removed parquet is gone; nothing new exists.
    assert set(before["entries"]) - set(after["entries"]) == {
        DATASET_PARQUET_FILENAME
    }
    assert set(after["entries"]) - set(before["entries"]) == set()


def test_second_pass_detects_mid_read_tamper(built, monkeypatch):
    """A file modified after the first verification pass but before the
    final pass must be caught; no mixed-instant partial result is ever
    returned."""
    real_verify_split = reader_mod._verify_split_rows

    def tamper_and_continue(*args, **kwargs):
        (built.build / DATASET_PARQUET_FILENAME).write_bytes(b"tampered")
        return real_verify_split(*args, **kwargs)

    monkeypatch.setattr(reader_mod, "_verify_split_rows", tamper_and_continue)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_second_pass_detects_whitelist_change(built, monkeypatch):
    real_verify_split = reader_mod._verify_split_rows

    def tamper_and_continue(*args, **kwargs):
        (built.build / "sneaky.txt").write_text("x", encoding="utf-8")
        return real_verify_split(*args, **kwargs)

    monkeypatch.setattr(reader_mod, "_verify_split_rows", tamper_and_continue)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# P2. Second-pass manifest re-verification.
# ---------------------------------------------------------------------------


def test_second_pass_manifest_content_replace_rejected(built, monkeypatch):
    """The manifest is not a member of output_files, so the second pass
    must re-read and re-validate it: a mid-read content replacement fails
    closed without writing or repairing anything."""
    real_verify_split = reader_mod._verify_split_rows

    def tamper_and_continue(*args, **kwargs):
        (built.build / DATASET_MANIFEST_FILENAME).write_bytes(b"{}")
        return real_verify_split(*args, **kwargs)

    monkeypatch.setattr(reader_mod, "_verify_split_rows", tamper_and_continue)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)
    # Nothing was repaired or rewritten by the reader.
    assert (built.build / DATASET_MANIFEST_FILENAME).read_bytes() == b"{}"


def test_second_pass_manifest_canonical_replace_rejected(
    fixtures, tmp_path, monkeypatch
):
    """Replacing the manifest with another canonical, fully
    validate_dataset_manifest-passing manifest fails closed because the
    bytes differ from the initially verified payload — even when every
    output-file record is unchanged."""
    _, mresult_a = materialize_once(fixtures, tmp_path)
    build_a = build_path(mresult_a)
    _, mresult_b = materialize_once(
        fixtures, tmp_path / "other_root", built_at=BUILT_AT + timedelta(seconds=1)
    )
    other_payload = mresult_b.manifest_path.read_bytes()
    # The other manifest is canonical and validates against its own build.
    dataset_pkg.validate_dataset_manifest(other_payload)

    real_verify_split = reader_mod._verify_split_rows

    def tamper_and_continue(*args, **kwargs):
        (build_a / DATASET_MANIFEST_FILENAME).write_bytes(other_payload)
        return real_verify_split(*args, **kwargs)

    monkeypatch.setattr(reader_mod, "_verify_split_rows", tamper_and_continue)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(build_a)


def test_second_pass_manifest_whitespace_change_rejected(built, monkeypatch):
    original = (built.build / DATASET_MANIFEST_FILENAME).read_bytes()
    real_verify_split = reader_mod._verify_split_rows

    def tamper_and_continue(*args, **kwargs):
        (built.build / DATASET_MANIFEST_FILENAME).write_bytes(original + b" ")
        return real_verify_split(*args, **kwargs)

    monkeypatch.setattr(reader_mod, "_verify_split_rows", tamper_and_continue)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


def test_second_pass_manifest_unchanged_passes(built):
    verified_build = read_verified(built)
    assert verified_build.dataset_id == built.result.dataset_id


def test_second_pass_manifest_symlink_race_rejected(built, tmp_path, monkeypatch):
    """A manifest.json that becomes a symlink between the passes fails
    closed on the final pass and the link target is never entered."""
    target = tmp_path / "manifest_backup.json"
    target.write_bytes((built.build / DATASET_MANIFEST_FILENAME).read_bytes())
    real_verify_split = reader_mod._verify_split_rows

    def tamper_and_continue(*args, **kwargs):
        manifest_path = built.build / DATASET_MANIFEST_FILENAME
        manifest_path.unlink()
        _make_symlink_or_skip(target, manifest_path)
        return real_verify_split(*args, **kwargs)

    monkeypatch.setattr(reader_mod, "_verify_split_rows", tamper_and_continue)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(built.build)


# ---------------------------------------------------------------------------
# Q. Relocation / determinism.
# ---------------------------------------------------------------------------


def test_repeated_reads_equal(built):
    assert read_verified(built) == read_verified(built)


def test_relocation_passes_and_identity_stable(built, tmp_path):
    moved_root = tmp_path / "moved" / "parent"
    moved_root.mkdir(parents=True)
    shutil.copytree(
        built.build, moved_root / built.result.dataset_id
    )
    relocated = load_verified_dataset(moved_root / built.result.dataset_id)
    assert relocated.dataset_id == built.result.dataset_id
    assert relocated.build_path == moved_root / built.result.dataset_id
    assert relocated.rows == built.result.rows
    assert relocated.manifest == built.manifest


def test_mtime_change_does_not_affect_identity(built):
    original = read_verified(built)
    for root, _, files in os.walk(built.build):
        for name in files:
            path = Path(root) / name
            os.utime(path, (1_500_000_000, 1_500_000_000))
    again = read_verified(built)
    assert again.dataset_id == original.dataset_id
    assert again.manifest == original.manifest
    assert again.rows == original.rows


def test_cwd_change_does_not_affect_result(built, tmp_path, monkeypatch):
    first = read_verified(built)
    monkeypatch.chdir(tmp_path.parent)
    second = read_verified(built)
    assert second == first


def test_directory_name_must_still_be_dataset_id_after_relocation(built, tmp_path):
    moved_root = tmp_path / "moved"
    moved_root.mkdir()
    shutil.copytree(built.build, moved_root / ("d" * 64))
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(moved_root / ("d" * 64))


def test_symlink_relocation_rejected(built, tmp_path):
    moved_root = tmp_path / "moved"
    moved_root.mkdir()
    shutil.copytree(built.build, moved_root / built.result.dataset_id)
    link = tmp_path / ("e" * 64)
    _make_symlink_or_skip(moved_root / built.result.dataset_id, link)
    with pytest.raises(DatasetArtifactValidationError):
        load_verified_dataset(link)


def test_local_timezone_change_does_not_affect_result(built, monkeypatch):
    if not hasattr(__import__("time"), "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    import time

    baseline = read_verified(built)
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    time.tzset()
    try:
        again = read_verified(built)
    finally:
        time.tzset()
    assert again == baseline


# ---------------------------------------------------------------------------
# R. EMPTY Dataset.
# ---------------------------------------------------------------------------


def test_empty_dataset_read(fixtures, tmp_path):
    result = orchestrate(fixtures, requests=[])
    assert result.status == STATUS_EMPTY
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=BUILT_AT
    )
    verified_build = load_verified_dataset(mresult.build_path)
    assert verified_build.status == STATUS_EMPTY
    assert verified_build.rows == ()
    assert verified_build.dataset_id == result.dataset_id
    assert len(verified_build.schema.fields) == len(result.schema.fields)
    assert verified_build.manifest.logical_row_count == 0
    assert verified_build.split_result.assignments == ()
    assert verified_build.split_result.diagnostics.sample_count == 0
    report = verified_build.build_report
    assert report.logical_row_count == 0
    assert report.split_sample_count == 0
    assert report.assigned_sample_count == 0
    assert report.purged_sample_count == 0
    assert report.excluded_sample_count == 0
    assert report.feature_complete_sample_count == 0
    # Full schema and metadata are present.
    table = pq.read_table(mresult.dataset_path)
    assert table.num_rows == 0
    assert table.schema.metadata
    # All spec artifacts exist.
    assert len(verified_build.feature_specs) == 1
    assert len(verified_build.label_specs) == 1
    # Idempotent read.
    assert load_verified_dataset(mresult.build_path) == verified_build
