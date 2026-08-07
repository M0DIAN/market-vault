"""Offline deterministic tests of the v0.6.0 Dataset Catalog contract
foundation (PR-5).

Covers the version constants, the frozen / deeply immutable models, the
construction-time self-validation and tamper rejection, the trust boundary
(projection accepts only a verified ``VerifiedDatasetBuild``), the
COMPLETE / EMPTY projections, path-move and ``built_at`` identity
stability, input-order and nested-pin normalization, real semantic-change
identity sensitivity, exact-duplicate normalization, conflicting-duplicate
failure, the full fail-closed matrix, the version-constant identity
binding, and the no-side-effect / no-current-time / no-filesystem-scan
boundary. All Dataset builds are produced through the public chain
(verified Canonical reader -> orchestrator -> materializer -> verified
Dataset reader); no network, no OpenD, no current time, and no real market
data.
"""

from __future__ import annotations

import dataclasses
import shutil
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
    DATASET_CATALOG_CONTRACT_VERSION,
    DATASET_CATALOG_CONTENT_ID_VERSION,
    DATASET_CATALOG_ENTRY_SCHEMA_VERSION,
    DATASET_KIND_SUPERVISED,
    DATASET_MANIFEST_SCHEMA_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
    LABEL_SPEC_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
    SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
    SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    SPEC_KIND_SPLIT,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    CanonicalBuildPin,
    ChronologicalSplitSpec,
    CompletionSummary,
    CrossTradingDayPolicy,
    DatasetCatalogDatasetFacts,
    DatasetCatalogEntry,
    DatasetCatalogError,
    DatasetCatalogObservedMetadata,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecPin,
    SpecVersionRequirements,
    catalog_dataset_content_id,
    dataset_catalog_content_id,
    dataset_orchestration_schema,
    load_verified_dataset,
    materialize_dataset_artifacts,
    orchestrate_dataset_build,
    project_dataset_catalog_entry,
)
from market_vault.dataset import dataset_catalog_identity as identity_mod
from market_vault.dataset import dataset_catalog_projection as projection_mod
from market_vault.dataset import reader_models as reader_models_mod
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

UTC = timezone.utc
NY = "America/New_York"
BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"

# ---------------------------------------------------------------------------
# Real verified-Dataset-build fixtures (public chain only).
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


def default_key() -> CanonicalRequestKey:
    return CanonicalRequestKey(
        interval="1m", requested_session="ALL", adjustment="NONE",
        source_schema_version="10.9",
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
    store.write_curated(curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id)
    run = RunManifest(
        requested_trade_date=trade_date, requested_symbols=[code],
        interval="1m", session="ALL", adjustment="NONE", run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


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


def feature_spec(name: str = "sr") -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name=name,
        version="v1",
        output=DatasetField(name=name, logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(SpecParameter("window_bars", 2),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec(name: str = "fr") -> LabelSpec:
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
        observation_window=LabelObservationWindow("BARS", 1, 1),
        horizon=LabelHorizon("BARS", 2),
        alignment_rule=LABEL_ALIGNMENT_FEATURE_CLOSE_ALIGNED,
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def chronological_spec() -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version=CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
        name="catalog_split",
        version="v1",
        boundary_timezone=NY,
        train_end_date=date(2026, 6, 30),
        validation_end_date=date(2026, 7, 1),
        test_end_date=date(2026, 7, 2),
        assignment_rule=SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,
        purge_rule=SPLIT_PURGE_RULE_ACTUAL_LABEL_END,
        incomplete_label_policy=SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,
        out_of_range_policy=SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,
    )


def request() -> PITSampleRequest:
    return PITSampleRequest(
        code="US.MU",
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor_market_calendar_date=date(2026, 7, 1),
        feature_window_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
        feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_window_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_window_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
    )


def dataset_scope() -> DatasetScope:
    return DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )


def orchestrate(fixtures, *, requests):
    feature_specs = [feature_spec()]
    label_specs = [label_spec()]
    split_spec = chronological_spec()
    scope = dataset_scope()
    schema = dataset_orchestration_schema(
        feature_specs, label_specs, include_dataset_as_of=False
    )
    return orchestrate_dataset_build(
        builds=tuple(fixtures.builds),
        requests=tuple(requests),
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=split_spec,
        scope=scope,
        schema=schema,
        dataset_as_of=None,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )


def datasets_root(tmp_path) -> Path:
    return tmp_path / "datasets"


def materialize_once(fixtures, tmp_path, *, requests, built_at=BUILT_AT):
    result = orchestrate(fixtures, requests=requests)
    mresult = materialize_dataset_artifacts(
        result, output_root=datasets_root(tmp_path), built_at=built_at
    )
    return result, mresult


def read_verified(mresult):
    return load_verified_dataset(mresult.build_path)


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    """One shared offline catalog with the micro canonical builds ``a``
    (feature-window rows) and ``f`` (future label rows), produced through
    the public builder -> materializer -> verified reader chain."""
    root = tmp_path_factory.mktemp("mv_catalog")
    cfg = settings(root)
    calendar(cfg)

    def build(code, trade_date, run_id, time_keys, closes):
        write_snapshot(
            cfg, code=code, trade_date=trade_date, run_id=run_id,
            time_keys=time_keys, closes=closes,
        )
        return verified(
            materialize(cfg, symbols=[code], trade_dates=[trade_date])
        )

    a = build(
        "US.MU", date(2026, 7, 1), "run-a",
        minute_keys("2026-07-01 09:30:00", 6),
        [100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
    )
    f = build(
        "US.MU", date(2026, 7, 1), "run-f",
        minute_keys("2026-07-01 09:36:00", 6),
        [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
    )
    return SimpleNamespace(builds=[a, f])


@pytest.fixture(scope="module")
def dataset_build(fixtures, tmp_path_factory):
    """One real verified COMPLETE Dataset build."""
    tmp = Path(tmp_path_factory.mktemp("mv_catalog_dataset"))
    result, mresult = materialize_once(fixtures, tmp, requests=[request()])
    assert result.status == STATUS_COMPLETE
    return read_verified(mresult)


@pytest.fixture(scope="module")
def empty_build(fixtures, tmp_path_factory):
    """One real verified EMPTY Dataset build (no sample requests)."""
    tmp = Path(tmp_path_factory.mktemp("mv_catalog_empty"))
    result, mresult = materialize_once(fixtures, tmp, requests=[])
    assert result.status == STATUS_EMPTY
    return read_verified(mresult)


def project(build) -> DatasetCatalogEntry:
    return project_dataset_catalog_entry(build)


# ---------------------------------------------------------------------------
# A. Version constants and exports.
# ---------------------------------------------------------------------------


def test_version_constants_exact():
    assert DATASET_CATALOG_CONTRACT_VERSION == "market-vault-dataset-catalog-contract-v1"
    assert DATASET_CATALOG_ENTRY_SCHEMA_VERSION == "market-vault-dataset-catalog-entry-v1"
    assert DATASET_CATALOG_CONTENT_ID_VERSION == "market-vault-dataset-catalog-content-v1"


def test_content_id_is_lowercase_sha256(dataset_build):
    entry = project(dataset_build)
    assert len(entry.content_id) == 64
    assert entry.content_id == entry.content_id.lower()
    int(entry.content_id, 16)


# ---------------------------------------------------------------------------
# B. Frozen / deep immutability.
# ---------------------------------------------------------------------------


def test_facts_are_frozen(dataset_build):
    facts = project(dataset_build).dataset_facts
    with pytest.raises(FrozenInstanceError):
        facts.dataset_id = "f" * 64
    with pytest.raises(FrozenInstanceError):
        facts.scope = None


def test_metadata_is_frozen(dataset_build):
    metadata = project(dataset_build).observed_metadata
    with pytest.raises(FrozenInstanceError):
        metadata.built_at = datetime(2000, 1, 1, tzinfo=UTC)
    with pytest.raises(FrozenInstanceError):
        metadata.build_path = Path("/elsewhere")


def test_entry_is_frozen(dataset_build):
    entry = project(dataset_build)
    with pytest.raises(FrozenInstanceError):
        entry.content_id = "f" * 64


def test_nested_models_are_frozen_and_typed(dataset_build):
    facts = project(dataset_build).dataset_facts
    assert isinstance(facts.scope, DatasetScope)
    assert all(isinstance(pin, SpecPin) for pin in facts.feature_spec_pins)
    assert all(isinstance(pin, SpecPin) for pin in facts.label_spec_pins)
    assert isinstance(facts.split_spec_pin, SpecPin) or facts.split_spec_pin is None
    assert all(isinstance(pin, CanonicalBuildPin) for pin in facts.canonical_build_pins)
    assert isinstance(facts.completion, CompletionSummary)
    assert all(isinstance(pin, SpecPin) for pin in facts.feature_spec_pins)


def test_nested_models_are_immutable(dataset_build):
    facts = project(dataset_build).dataset_facts
    with pytest.raises(FrozenInstanceError):
        facts.scope.symbols = ()
    with pytest.raises(FrozenInstanceError):
        facts.completion.entries = ()


def test_entry_holds_the_same_facts_object(dataset_build):
    entry = project(dataset_build)
    assert entry.dataset_facts is entry.dataset_facts
    assert isinstance(entry.dataset_facts, DatasetCatalogDatasetFacts)


# ---------------------------------------------------------------------------
# C. Construction-time self-validation and tamper rejection.
# ---------------------------------------------------------------------------


def test_entry_tampered_content_id_fails(dataset_build):
    entry = project(dataset_build)
    with pytest.raises(DatasetCatalogError):
        replace(entry, content_id="f" * 64)
    wrong_digest = ("0" if entry.content_id[0] != "0" else "1") + entry.content_id[1:]
    with pytest.raises(DatasetCatalogError):
        replace(entry, content_id=wrong_digest)


def test_entry_tampered_facts_fails(dataset_build):
    entry = project(dataset_build)
    other = replace(entry.dataset_facts, dataset_kind="other-kind")
    with pytest.raises(DatasetCatalogError):
        replace(entry, dataset_facts=other)


def test_entry_metadata_tamper_keeps_content_id(dataset_build, tmp_path):
    """Metadata is non-content: substituting it must not change content_id."""
    entry = project(dataset_build)
    moved = replace(
        entry,
        observed_metadata=DatasetCatalogObservedMetadata(
            built_at=entry.observed_metadata.built_at,
            build_path=tmp_path / "other" / "parent" / entry.dataset_facts.dataset_id,
        ),
    )
    assert moved.content_id == entry.content_id


def test_metadata_requires_absolute_path(dataset_build):
    entry = project(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogObservedMetadata(
            built_at=entry.observed_metadata.built_at, build_path=Path("relative")
        )


def test_metadata_requires_clean_path(dataset_build, tmp_path):
    entry = project(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogObservedMetadata(
            built_at=entry.observed_metadata.built_at,
            build_path=tmp_path / "a" / ".." / "b",
        )


def test_metadata_rejects_naive_built_at(dataset_build):
    entry = project(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogObservedMetadata(
            built_at=datetime(2026, 8, 5, 12, 0), build_path=entry.observed_metadata.build_path
        )


# ---------------------------------------------------------------------------
# D. Trust boundary: projection accepts only VerifiedDatasetBuild.
# ---------------------------------------------------------------------------


def test_projection_rejects_none():
    with pytest.raises(DatasetCatalogError):
        project_dataset_catalog_entry(None)


def test_projection_rejects_manifest_dict(dataset_build):
    with pytest.raises(DatasetCatalogError):
        project_dataset_catalog_entry(dataset_build.manifest.__dict__)


def test_projection_rejects_manifest_path(dataset_build):
    with pytest.raises(DatasetCatalogError):
        project_dataset_catalog_entry(dataset_build.build_path / "manifest.json")


def test_projection_rejects_build_directory_path(dataset_build):
    with pytest.raises(DatasetCatalogError):
        project_dataset_catalog_entry(dataset_build.build_path)


def test_projection_rejects_arbitrary_objects():
    with pytest.raises(DatasetCatalogError):
        project_dataset_catalog_entry(object())


def test_projection_accepts_verified_build(dataset_build):
    entry = project(dataset_build)
    assert entry.dataset_facts.dataset_id == dataset_build.dataset_id
    assert entry.observed_metadata.build_path == dataset_build.build_path


def test_projection_recomputes_manifest_consistency(dataset_build):
    """A tampered VerifiedDatasetBuild cannot even be constructed (the
    reader model re-validates), so projection input is trustworthy by
    construction."""
    other_built_at = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
    assert other_built_at != dataset_build.built_at
    with pytest.raises(Exception):
        replace(
            dataset_build,
            manifest=replace(dataset_build.manifest, built_at=other_built_at),
        )
    # The reader model rejects the tamper, so the projection never sees it.
    assert project(dataset_build).dataset_facts.dataset_id == dataset_build.dataset_id


def test_projection_never_reads_the_build_directory(dataset_build, tmp_path):
    """Projection is a pure in-memory function: after the build directory
    is deleted, projection still succeeds with the same content ID."""
    copied = tmp_path / dataset_build.dataset_id
    shutil.copytree(dataset_build.build_path, copied)
    relocated = load_verified_dataset(copied)
    before = project(relocated)
    shutil.rmtree(copied)
    after = project(relocated)
    assert after.content_id == before.content_id
    assert after.dataset_facts == before.dataset_facts


def test_projection_never_uses_current_time(dataset_build, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("current time must never be read")

    monkeypatch.setattr(pd.Timestamp, "now", classmethod(explode))
    entry = project(dataset_build)
    assert entry.content_id == project(dataset_build).content_id


def test_projection_module_has_no_forbidden_dependencies():
    """Static guard: the projection module never references the legacy
    Catalog, settings, OpenD, network, or the current time."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(projection_mod))
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    for forbidden in ("Catalog", "Settings", "OpenD", "network", "now"):
        assert forbidden not in names


# ---------------------------------------------------------------------------
# E. COMPLETE and EMPTY projections.
# ---------------------------------------------------------------------------


def test_complete_projection_facts(dataset_build):
    entry = project(dataset_build)
    facts = entry.dataset_facts
    assert facts.status == STATUS_COMPLETE
    assert facts.logical_row_count > 0
    assert facts.dataset_kind == DATASET_KIND_SUPERVISED
    assert len(facts.feature_spec_pins) == 1
    assert facts.feature_spec_pins[0].kind == SPEC_KIND_FEATURE
    assert len(facts.label_spec_pins) == 1
    assert facts.label_spec_pins[0].kind == SPEC_KIND_LABEL
    assert facts.split_spec_pin.kind == SPEC_KIND_SPLIT
    assert len(facts.canonical_build_pins) == 2
    assert facts.completion.complete_count >= 1


def test_empty_projection_facts(empty_build):
    entry = project(empty_build)
    facts = entry.dataset_facts
    assert facts.status == STATUS_EMPTY
    assert facts.logical_row_count == 0
    assert facts.completion.complete_count == 0


def test_empty_projection_identity_stable(empty_build):
    first = project(empty_build)
    second = project(empty_build)
    assert second.content_id == first.content_id


# ---------------------------------------------------------------------------
# F. Path move and built_at do not change the content ID.
# ---------------------------------------------------------------------------


def test_relocated_dataset_keeps_content_id(dataset_build, tmp_path):
    """Moving the same verified Dataset to another parent directory keeps
    the content facts and the content ID; only the observed build_path
    changes."""
    moved = tmp_path / "moved-parent"
    moved.mkdir()
    shutil.copytree(dataset_build.build_path, moved / dataset_build.dataset_id)
    relocated = load_verified_dataset(moved / dataset_build.dataset_id)
    original = project(dataset_build)
    moved_entry = project(relocated)
    assert moved_entry.content_id == original.content_id
    assert moved_entry.dataset_facts == original.dataset_facts
    assert moved_entry.observed_metadata.build_path != original.observed_metadata.build_path


def test_different_built_at_keeps_content_id(fixtures, tmp_path):
    """Two materializations of the same orchestration result with different
    built_at values produce the same Catalog content ID (built_at is
    non-content)."""
    result, mresult = materialize_once(
        fixtures, tmp_path, requests=[request()], built_at=BUILT_AT
    )
    other_root = tmp_path / "other-datasets"
    again = materialize_dataset_artifacts(
        result, output_root=other_root, built_at=datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
    )
    first = project(load_verified_dataset(mresult.build_path))
    second = project(load_verified_dataset(again.build_path))
    assert second.content_id == first.content_id
    assert second.observed_metadata.built_at != first.observed_metadata.built_at


# ---------------------------------------------------------------------------
# G. Input order and nested-pin normalization.
# ---------------------------------------------------------------------------


def test_catalog_identity_is_order_independent(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path, requests=[request()])
    entry = project(load_verified_dataset(mresult.build_path))
    twin = project(load_verified_dataset(mresult.build_path))
    assert (
        dataset_catalog_content_id((entry, twin))
        == dataset_catalog_content_id((twin, entry))
    )


def test_facts_pin_order_normalization(fixtures, tmp_path):
    result, mresult = materialize_once(fixtures, tmp_path, requests=[request()])
    build = load_verified_dataset(mresult.build_path)
    facts = project(build).dataset_facts

    reversed_pins = replace(facts, feature_spec_pins=tuple(reversed(facts.feature_spec_pins)))
    assert reversed_pins.feature_spec_pins == facts.feature_spec_pins

    reversed_builds = replace(
        facts, canonical_build_pins=tuple(reversed(facts.canonical_build_pins))
    )
    assert reversed_builds.canonical_build_pins == facts.canonical_build_pins

    assert catalog_dataset_content_id(reversed_pins) == catalog_dataset_content_id(facts)
    assert catalog_dataset_content_id(reversed_builds) == catalog_dataset_content_id(facts)


def test_completion_entry_order_normalization(dataset_build):
    facts = project(dataset_build).dataset_facts
    reversed_entries = replace(
        facts, completion=replace(
            facts.completion, entries=tuple(reversed(facts.completion.entries))
        )
    )
    assert reversed_entries.completion.entries == facts.completion.entries
    assert catalog_dataset_content_id(reversed_entries) == catalog_dataset_content_id(facts)


def test_row_version_order_normalization(dataset_build):
    facts = project(dataset_build).dataset_facts
    reversed_ids = replace(
        facts, canonical_row_version_ids=tuple(reversed(facts.canonical_row_version_ids))
    )
    assert reversed_ids.canonical_row_version_ids == facts.canonical_row_version_ids
    assert catalog_dataset_content_id(reversed_ids) == catalog_dataset_content_id(facts)


def test_timezone_equivalent_datetime_same_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    with_tz = replace(facts, dataset_as_of=datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    equivalent = replace(
        facts, dataset_as_of=datetime(2026, 7, 1, 6, 0, tzinfo=timezone(-timedelta(hours=4)))
    )
    assert with_tz.dataset_as_of == equivalent.dataset_as_of
    assert (
        catalog_dataset_content_id(with_tz)
        == catalog_dataset_content_id(equivalent)
    )


# ---------------------------------------------------------------------------
# H. Real semantic changes change the identity.
# ---------------------------------------------------------------------------


def test_scope_change_changes_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    changed = replace(
        facts, scope=replace(facts.scope, interval="5m")
    )
    assert catalog_dataset_content_id(changed) != catalog_dataset_content_id(facts)


def test_status_change_changes_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    changed = replace(facts, status=STATUS_EMPTY, logical_row_count=0)
    assert catalog_dataset_content_id(changed) != catalog_dataset_content_id(facts)


def test_dataset_as_of_change_changes_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    changed = replace(facts, dataset_as_of=datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    assert catalog_dataset_content_id(changed) != catalog_dataset_content_id(facts)


def test_spec_pin_change_changes_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    pin = facts.feature_spec_pins[0]
    changed_pin = SpecPin(
        kind=pin.kind, name=pin.name, version=pin.version,
        content_sha256="0" + pin.content_sha256[1:],
    )
    changed = replace(facts, feature_spec_pins=(changed_pin,))
    assert catalog_dataset_content_id(changed) != catalog_dataset_content_id(facts)


def test_logical_row_count_change_changes_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    changed = replace(facts, logical_row_count=facts.logical_row_count + 1)
    assert catalog_dataset_content_id(changed) != catalog_dataset_content_id(facts)


def _flip_completion(completion: CompletionSummary) -> CompletionSummary:
    """A semantically different but internally consistent completion: every
    entry status flips (COMPLETE -> INCOMPLETE -> MISSING -> COMPLETE) and
    the counts are recomputed to match, so the CompletionSummary model
    itself still validates."""
    counts = {"COMPLETE": 0, "INCOMPLETE": 0, "MISSING": 0}
    flip = {"COMPLETE": "INCOMPLETE", "INCOMPLETE": "MISSING", "MISSING": "COMPLETE"}
    entries = []
    for entry in completion.entries:
        new_status = flip[entry.status]
        counts[new_status] += 1
        entries.append(replace(entry, status=new_status, reason_code=None))
    return CompletionSummary(
        complete_count=counts["COMPLETE"],
        incomplete_count=counts["INCOMPLETE"],
        missing_count=counts["MISSING"],
        entries=tuple(entries),
    )


def test_completion_change_changes_identity(dataset_build):
    facts = project(dataset_build).dataset_facts
    flipped = _flip_completion(facts.completion)
    assert flipped != facts.completion
    changed = replace(facts, completion=flipped)
    assert catalog_dataset_content_id(changed) != catalog_dataset_content_id(facts)


def test_contract_version_binding(monkeypatch, dataset_build):
    facts = project(dataset_build).dataset_facts
    base = dataset_catalog_content_id((project(dataset_build),))
    monkeypatch.setattr(
        identity_mod, "DATASET_CATALOG_CONTRACT_VERSION", "market-vault-dataset-catalog-contract-v9"
    )
    assert dataset_catalog_content_id((project(dataset_build),)) != base


def test_entry_schema_version_binding(monkeypatch, dataset_build):
    facts = project(dataset_build).dataset_facts
    base = catalog_dataset_content_id(facts)
    monkeypatch.setattr(
        identity_mod, "DATASET_CATALOG_ENTRY_SCHEMA_VERSION", "market-vault-dataset-catalog-entry-v9"
    )
    assert catalog_dataset_content_id(facts) != base


# ---------------------------------------------------------------------------
# I. Duplicate and conflict policy.
# ---------------------------------------------------------------------------


def test_exact_duplicate_normalization(dataset_build):
    entry = project(dataset_build)
    twin = project(dataset_build)
    assert dataset_catalog_content_id((entry,)) == dataset_catalog_content_id((entry, twin))


def _conflicting_entry(entry: DatasetCatalogEntry, conflicting_facts) -> DatasetCatalogEntry:
    """An entry whose facts conflict with the original but whose content ID
    is self-consistent (the conflict is only visible to the Catalog-level
    identity)."""
    return DatasetCatalogEntry(
        dataset_facts=conflicting_facts,
        observed_metadata=entry.observed_metadata,
        content_id=catalog_dataset_content_id(conflicting_facts),
    )


def test_conflicting_duplicate_fails_closed(dataset_build):
    entry = project(dataset_build)
    conflicting = replace(entry.dataset_facts, dataset_kind="other-kind")
    with pytest.raises(DatasetCatalogError):
        dataset_catalog_content_id(
            (entry, _conflicting_entry(entry, conflicting))
        )


def test_conflicting_duplicate_pins_fail_closed(dataset_build):
    entry = project(dataset_build)
    pin = entry.dataset_facts.feature_spec_pins[0]
    changed_pin = SpecPin(
        kind=pin.kind, name=pin.name, version=pin.version,
        content_sha256="1" + pin.content_sha256[1:],
    )
    conflicting = replace(
        entry.dataset_facts, feature_spec_pins=(changed_pin,)
    )
    with pytest.raises(DatasetCatalogError):
        dataset_catalog_content_id(
            (entry, _conflicting_entry(entry, conflicting))
        )


def test_catalog_identity_requires_entries_tuple(dataset_build):
    with pytest.raises(DatasetCatalogError):
        dataset_catalog_content_id([project(dataset_build)])


def test_catalog_identity_rejects_non_entry(dataset_build):
    with pytest.raises(DatasetCatalogError):
        dataset_catalog_content_id((project(dataset_build), object()))


# ---------------------------------------------------------------------------
# J. Fail-closed construction matrix.
# ---------------------------------------------------------------------------


def facts_kwargs(dataset_build) -> dict:
    facts = project(dataset_build).dataset_facts
    return dict(
        dataset_id=facts.dataset_id,
        dataset_kind=facts.dataset_kind,
        status=facts.status,
        logical_row_count=facts.logical_row_count,
        dataset_schema_id=facts.dataset_schema_id,
        logical_dataset_content_id=facts.logical_dataset_content_id,
        dataset_as_of=facts.dataset_as_of,
        scope=facts.scope,
        feature_spec_pins=facts.feature_spec_pins,
        label_spec_pins=facts.label_spec_pins,
        split_spec_pin=facts.split_spec_pin,
        canonical_build_pins=facts.canonical_build_pins,
        canonical_row_version_ids=facts.canonical_row_version_ids,
        completion=facts.completion,
    )


def test_invalid_dataset_id_fails(dataset_build):
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "dataset_id": "not-hex"})
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "dataset_id": "f" * 63})


def test_unsupported_status_fails(dataset_build):
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "status": "PARTIAL"})


def test_negative_count_fails(dataset_build):
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "logical_row_count": -1})


def test_bool_count_fails(dataset_build):
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "logical_row_count": True})


def test_float_count_fails(dataset_build):
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "logical_row_count": 1.0})


def test_status_row_count_consistency_fails(dataset_build):
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "status": STATUS_EMPTY})
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts_kwargs(dataset_build), "logical_row_count": 0})


def test_wrong_pin_kind_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    label_pin = facts["label_spec_pins"][0]
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(
            **{**facts, "feature_spec_pins": (label_pin,)}
        )


def test_duplicate_pins_fail(dataset_build):
    facts = facts_kwargs(dataset_build)
    pin = facts["feature_spec_pins"][0]
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(
            **{**facts, "feature_spec_pins": (pin, pin)}
        )


def test_split_pin_wrong_kind_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts, "split_spec_pin": facts["feature_spec_pins"][0]})


def test_untyped_scope_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts, "scope": {"symbols": ("US.MU",)}})


def test_iterable_payload_normalized_to_tuple(dataset_build):
    """A list input is normalized to an immutable tuple at construction;
    the model never keeps a mutable payload internally."""
    facts = facts_kwargs(dataset_build)
    constructed = DatasetCatalogDatasetFacts(
        **{**facts, "feature_spec_pins": list(facts["feature_spec_pins"])}
    )
    assert isinstance(constructed.feature_spec_pins, tuple)
    assert constructed.feature_spec_pins == facts["feature_spec_pins"]


def test_untyped_dict_payload_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(
            **{**facts, "feature_spec_pins": ({"kind": "FEATURE"},)}
        )
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(
            **{**facts, "canonical_build_pins": ({"canonical_build_id": "f" * 64},)}
        )


def test_naive_datetime_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(
            **{**facts, "dataset_as_of": datetime(2026, 7, 1, 10, 0)}
        )


def test_untyped_completion_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts, "completion": {"complete_count": 1}})


def test_scope_inconsistency_fails(dataset_build):
    """A completion entry outside the scope must fail closed."""
    facts = facts_kwargs(dataset_build)
    completion = facts["completion"]
    out_of_scope = replace(
        completion,
        entries=tuple(
            replace(entry, code="US.NOTIN") for entry in completion.entries
        ),
    )
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(**{**facts, "completion": out_of_scope})


def test_row_version_coverage_loss_fails(dataset_build):
    facts = facts_kwargs(dataset_build)
    covered = facts["canonical_row_version_ids"]
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogDatasetFacts(
            **{**facts, "canonical_row_version_ids": covered[:1]}
        )


def test_identity_rejects_non_facts(dataset_build):
    with pytest.raises(DatasetCatalogError):
        catalog_dataset_content_id(object())
    with pytest.raises(DatasetCatalogError):
        catalog_dataset_content_id(project(dataset_build))


def test_entry_requires_typed_parts(dataset_build):
    entry = project(dataset_build)
    wrong_digest = ("0" if entry.content_id[0] != "0" else "1") + entry.content_id[1:]
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogEntry(
            dataset_facts=entry.dataset_facts,
            observed_metadata=entry.observed_metadata,
            content_id=wrong_digest,
        )
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogEntry(
            dataset_facts=None,
            observed_metadata=entry.observed_metadata,
            content_id=entry.content_id,
        )
    with pytest.raises(DatasetCatalogError):
        DatasetCatalogEntry(
            dataset_facts=entry.dataset_facts,
            observed_metadata=None,
            content_id=entry.content_id,
        )


def test_entry_uppercase_content_id_normalized(dataset_build):
    """An uppercase hex content ID is a normalized-equivalent input and is
    accepted (normalization happens at the formal boundary)."""
    entry = project(dataset_build)
    accepted = DatasetCatalogEntry(
        dataset_facts=entry.dataset_facts,
        observed_metadata=entry.observed_metadata,
        content_id=entry.content_id.upper(),
    )
    assert accepted.content_id == entry.content_id


# ---------------------------------------------------------------------------
# K. No side effects / no forbidden behavior.
# ---------------------------------------------------------------------------


def test_projection_is_pure_and_deterministic(dataset_build):
    first = project(dataset_build)
    second = project(dataset_build)
    assert second == first
    assert second.content_id == first.content_id


def test_projection_tree_unchanged(dataset_build, tmp_path):
    """Projection never writes: the build directory tree is unchanged."""
    before = sorted(
        (path.relative_to(dataset_build.build_path).as_posix(), path.stat().st_size)
        for path in dataset_build.build_path.rglob("*")
        if path.is_file()
    )
    project(dataset_build)
    after = sorted(
        (path.relative_to(dataset_build.build_path).as_posix(), path.stat().st_size)
        for path in dataset_build.build_path.rglob("*")
        if path.is_file()
    )
    assert after == before


def test_metadata_never_enters_identity(dataset_build, tmp_path):
    """The two structurally disjoint types: metadata fields never appear on
    the facts type."""
    facts_fields = {field.name for field in dataclasses.fields(DatasetCatalogDatasetFacts)}
    metadata_fields = {
        field.name for field in dataclasses.fields(DatasetCatalogObservedMetadata)
    }
    assert metadata_fields.isdisjoint(facts_fields)


def test_catalog_identity_never_flows_into_dataset_identity(dataset_build):
    """Projection is additive and read-only: the Dataset identity carried
    by the verified build is unchanged, and the Catalog content ID is a
    distinct digest, never a rewrite of the Dataset ID."""
    entry = project(dataset_build)
    assert entry.dataset_facts.dataset_id == dataset_build.dataset_id
    assert entry.dataset_facts.dataset_id == dataset_build.manifest.dataset_id
    assert len(entry.content_id) == 64
    assert entry.content_id != entry.dataset_facts.dataset_id
