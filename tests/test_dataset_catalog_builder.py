"""Offline deterministic tests of the Dataset Catalog builder (v0.6.0
PR-6).

Covers the public API and version constants, the exactly-one-mode input
contract, bounded direct-child root discovery (non-candidates ignored
without descent, nested valid Datasets never discovered), the explicit
candidate-set mode (boundary freeze, order independence, identical
lexical deduplication), the fail-closed link / special / corrupt
candidate matrix, the ambiguous duplicate Dataset location policy, the
conflicting-facts policy, the empty Catalog, determinism (candidate
order, cwd, relocation), the COMPLETE + EMPTY indexing, the frozen
self-validating result model, and the no-side-effect / no-settings /
no-current-time boundary. All Dataset builds are produced through the
public chain (verified Canonical reader -> orchestrator -> materializer
-> verified Dataset reader); no network, no OpenD, no current time, and
no real market data.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
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
    DATASET_CATALOG_BUILDER_VERSION,
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
    STATUS_COMPLETE,
    STATUS_EMPTY,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetCatalogBuildError,
    DatasetCatalogBuildResult,
    DatasetCatalogEntry,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    build_dataset_catalog,
    dataset_catalog_content_id,
    dataset_orchestration_schema,
    load_verified_dataset,
    materialize_dataset_artifacts,
    orchestrate_dataset_build,
    project_dataset_catalog_entry,
)
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
    root = tmp_path_factory.mktemp("mv_catalog_builder")
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
def complete_build(fixtures, tmp_path_factory):
    """One real verified COMPLETE Dataset build (module scope)."""
    tmp = Path(tmp_path_factory.mktemp("mv_builder_complete"))
    result, mresult = materialize_once(fixtures, tmp, requests=[request()])
    assert result.status == STATUS_COMPLETE
    return read_verified(mresult)


@pytest.fixture(scope="module")
def empty_build(fixtures, tmp_path_factory):
    """One real verified EMPTY Dataset build (module scope)."""
    tmp = Path(tmp_path_factory.mktemp("mv_builder_empty"))
    result, mresult = materialize_once(fixtures, tmp, requests=[])
    assert result.status == STATUS_EMPTY
    return read_verified(mresult)


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


def tree_snapshot(root: Path) -> set[str]:
    return {
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
    }


# ---------------------------------------------------------------------------
# A. Public API / input contract.
# ---------------------------------------------------------------------------


def test_builder_version_constant_exact():
    assert DATASET_CATALOG_BUILDER_VERSION == "market-vault-dataset-catalog-builder-v1"


def test_public_api_exports():
    import market_vault.dataset as dataset_pkg

    for name in (
        "build_dataset_catalog",
        "DatasetCatalogBuildResult",
        "DatasetCatalogBuildError",
    ):
        assert name in dataset_pkg.__all__
        assert hasattr(dataset_pkg, name)


def test_requires_exactly_one_mode(complete_build):
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog()
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(
            dataset_root=complete_build.build_path.parent,
            candidate_build_dirs=(complete_build.build_path,),
        )


def test_candidate_mode_accepts_explicit_empty_set(tmp_path):
    result = build_dataset_catalog(candidate_build_dirs=())
    assert result.dataset_count == 0
    assert result.entries == ()
    assert len(result.catalog_content_id) == 64


def test_root_mode_without_candidates_produces_empty_catalog(tmp_path):
    root = tmp_path / "empty-root"
    root.mkdir()
    result = build_dataset_catalog(dataset_root=root)
    assert result.dataset_count == 0
    assert result.entries == ()


# ---------------------------------------------------------------------------
# B. Root-mode bounded discovery.
# ---------------------------------------------------------------------------


def test_root_mode_discovers_direct_64hex_children(complete_build):
    result = build_dataset_catalog(dataset_root=complete_build.build_path.parent)
    assert result.dataset_count == 1
    assert result.entries[0].dataset_facts.dataset_id == complete_build.dataset_id


def test_root_mode_ignores_noncandidate_children_without_descent(
    complete_build, tmp_path
):
    root = tmp_path / "root"
    root.mkdir()
    # A valid Dataset nested inside a non-candidate directory must NOT be
    # discovered.
    nested = root / "not-a-candidate" / complete_build.build_path.name
    nested.parent.mkdir()
    shutil.copytree(complete_build.build_path, nested)
    (root / "README.txt").write_text("docs", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "journal.txt").write_text("x", encoding="utf-8")
    (root / f".staging-{'a' * 64}").mkdir()
    (root / f".staging-{'a' * 64}" / "partial.json").write_text("{}", encoding="utf-8")
    result = build_dataset_catalog(dataset_root=root)
    assert result.dataset_count == 0
    assert result.entries == ()
    # Nothing was entered or followed: the nested valid Dataset and the
    # staging residue stay untouched.
    assert nested.is_dir()
    assert (root / "notes" / "journal.txt").read_text(encoding="utf-8") == "x"


def test_root_mode_rejects_64hex_regular_file(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / ("f" * 64)).write_text("not a dataset", encoding="utf-8")
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=root)


def test_root_mode_rejects_64hex_symlink(complete_build, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _make_symlink_or_skip(complete_build.build_path, root / complete_build.dataset_id)
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=root)


def test_root_mode_rejects_corrupt_dataset_candidate(complete_build, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(complete_build.build_path, copy)
    (copy / "_SUCCESS").unlink()
    root = tmp_path / "root"
    root.mkdir()
    shutil.move(str(copy), str(root / complete_build.dataset_id))
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=root)


def test_root_is_symlink_fails(complete_build, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link-root"
    _make_symlink_or_skip(real, link)
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=link)


def test_root_ancestor_symlink_fails(complete_build, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "ancestor-link"
    _make_symlink_or_skip(real, link)
    root = link / "nested" / "root"
    root.mkdir(parents=True)
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=root)


def test_root_missing_fails(tmp_path):
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=tmp_path / "missing")


def test_root_relative_path_fails_dot_component(tmp_path):
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(dataset_root=tmp_path / ".." / "elsewhere")


# ---------------------------------------------------------------------------
# C. Candidate-set mode.
# ---------------------------------------------------------------------------


def test_candidate_mode_builds_from_verified_build(complete_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    assert result.dataset_count == 1
    assert result.entries[0].dataset_facts.dataset_id == complete_build.dataset_id


def test_candidate_order_does_not_affect_result(complete_build, empty_build):
    a = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path, empty_build.build_path)
    )
    b = build_dataset_catalog(
        candidate_build_dirs=(empty_build.build_path, complete_build.build_path)
    )
    assert a.entries == b.entries
    assert a.catalog_content_id == b.catalog_content_id
    assert a.dataset_count == b.dataset_count == 2


def test_identical_lexical_candidate_deduplicated(complete_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(
            complete_build.build_path,
            complete_build.build_path,
            complete_build.build_path,
        )
    )
    assert result.dataset_count == 1


def test_ambiguous_duplicate_location_fails(complete_build, tmp_path):
    # The same dataset_id under two different physical parents: the same
    # content facts, but the observed location is ambiguous.
    other_parent = tmp_path / "other-parent"
    shutil.copytree(complete_build.build_path, other_parent / complete_build.dataset_id)
    with pytest.raises(DatasetCatalogBuildError) as excinfo:
        build_dataset_catalog(
            candidate_build_dirs=(
                complete_build.build_path,
                other_parent / complete_build.dataset_id,
            )
        )
    assert "ambiguous duplicate Dataset location" in str(excinfo.value)


def test_same_dataset_id_conflicting_facts_fail(complete_build, tmp_path):
    # A manually tampered manifest directory (identical dataset_id with
    # different facts) must fail closed; the builder never trusts the
    # directory name.
    other_parent = tmp_path / "other-parent"
    shutil.copytree(complete_build.build_path, other_parent / complete_build.dataset_id)
    tampered = other_parent / complete_build.dataset_id
    manifest_path = tampered / "manifest.json"
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "EMPTY"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(
            candidate_build_dirs=(
                complete_build.build_path,
                tampered,
            )
        )


def test_explicit_bad_candidate_fails(tmp_path):
    bad = tmp_path / "not-a-dataset"
    bad.mkdir()
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(candidate_build_dirs=(bad,))


def test_candidate_non_iterable_fails(tmp_path):
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(candidate_build_dirs=42)


def test_candidate_relative_input_fails(complete_build, monkeypatch):
    """A relative candidate fails closed even when the current working
    directory makes it resolvable: the builder never reads cwd to
    complete a formal input."""
    monkeypatch.chdir(complete_build.build_path.parent)
    with pytest.raises(DatasetCatalogBuildError) as excinfo:
        build_dataset_catalog(
            candidate_build_dirs=(complete_build.build_path.name,)
        )
    assert "lexically absolute" in str(excinfo.value)


def test_dataset_root_relative_input_fails(complete_build, tmp_path, monkeypatch):
    """A relative dataset_root fails closed even when it resolves under
    the current working directory."""
    root = tmp_path / "datasets"
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DatasetCatalogBuildError) as excinfo:
        build_dataset_catalog(dataset_root="datasets")
    assert "lexically absolute" in str(excinfo.value)


# ---------------------------------------------------------------------------
# D. Determinism.
# ---------------------------------------------------------------------------


def test_cwd_does_not_affect_result(complete_build, empty_build, tmp_path):
    paths = (complete_build.build_path, empty_build.build_path)
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path)
    first = build_dataset_catalog(candidate_build_dirs=paths)
    monkeypatch.chdir(other_cwd)
    second = build_dataset_catalog(candidate_build_dirs=paths)
    assert first.entries == second.entries
    assert first.catalog_content_id == second.catalog_content_id


def test_root_enumeration_order_does_not_affect_result(
    complete_build, empty_build, tmp_path
):
    parent = tmp_path / "root"
    parent.mkdir()
    # Copies of the COMPLETE and EMPTY builds in one fresh root become the
    # two candidates; the entries must be dataset_id-sorted regardless of
    # the enumeration order.
    shutil.copytree(complete_build.build_path, parent / complete_build.dataset_id)
    shutil.copytree(empty_build.build_path, parent / empty_build.dataset_id)
    result = build_dataset_catalog(dataset_root=parent)
    assert result.dataset_count == 2
    assert [e.dataset_facts.dataset_id for e in result.entries] == sorted(
        e.dataset_facts.dataset_id for e in result.entries
    )


def test_repeated_build_is_identical(complete_build, empty_build):
    paths = (complete_build.build_path, empty_build.build_path)
    first = build_dataset_catalog(candidate_build_dirs=paths)
    second = build_dataset_catalog(candidate_build_dirs=paths)
    assert first == second
    assert first.catalog_content_id == second.catalog_content_id


def test_relocated_dataset_keeps_content_identity(complete_build, tmp_path):
    """The same verified Dataset moved to another parent: facts and the
    Catalog content identity are unchanged; only the observed location
    changes."""
    other_parent = tmp_path / "other-parent"
    shutil.copytree(complete_build.build_path, other_parent / complete_build.dataset_id)
    original = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    relocated = build_dataset_catalog(
        candidate_build_dirs=(other_parent / complete_build.dataset_id,)
    )
    assert (
        relocated.entries[0].dataset_facts == original.entries[0].dataset_facts
    )
    assert relocated.entries[0].content_id == original.entries[0].content_id
    assert relocated.catalog_content_id == original.catalog_content_id
    assert (
        relocated.entries[0].observed_metadata.build_path.as_posix()
        != original.entries[0].observed_metadata.build_path.as_posix()
    )


def test_same_facts_same_catalog_identity_across_input_modes(
    complete_build, tmp_path
):
    """Root mode and candidate mode must produce the same logical result
    for the same verified Datasets."""
    from_root = build_dataset_catalog(dataset_root=complete_build.build_path.parent)
    from_candidates = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    assert from_root.entries == from_candidates.entries
    assert from_root.catalog_content_id == from_candidates.catalog_content_id


# ---------------------------------------------------------------------------
# E. Result model self-validation.
# ---------------------------------------------------------------------------


def test_result_entries_frozen(complete_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    with pytest.raises(FrozenInstanceError):
        result.entries = ()
    with pytest.raises(FrozenInstanceError):
        result.catalog_content_id = "f" * 64


def test_result_tampered_content_id_fails(complete_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    wrong = ("0" if result.catalog_content_id[0] != "0" else "1") + (
        result.catalog_content_id[1:]
    )
    with pytest.raises(DatasetCatalogBuildError):
        replace(result, catalog_content_id=wrong)


def test_result_tampered_dataset_count_fails(complete_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    with pytest.raises(DatasetCatalogBuildError):
        replace(result, dataset_count=result.dataset_count + 1)


def test_result_tampered_entries_order_fails(complete_build, empty_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path, empty_build.build_path)
    )
    with pytest.raises(DatasetCatalogBuildError):
        replace(result, entries=tuple(reversed(result.entries)))


def test_result_tampered_builder_version_fails(complete_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path,)
    )
    with pytest.raises(DatasetCatalogBuildError):
        replace(result, builder_version="market-vault-dataset-catalog-builder-v9")


def test_result_rejects_untyped_entries(complete_build):
    entry = project_dataset_catalog_entry(complete_build)
    with pytest.raises(DatasetCatalogBuildError):
        DatasetCatalogBuildResult(
            entries=(entry.dataset_facts,),  # facts are not entries
            catalog_content_id=dataset_catalog_content_id((entry,)),
            dataset_count=1,
            builder_version=DATASET_CATALOG_BUILDER_VERSION,
        )
    with pytest.raises(DatasetCatalogBuildError):
        DatasetCatalogBuildResult(
            entries=[entry],  # a list is never accepted
            catalog_content_id=dataset_catalog_content_id((entry,)),
            dataset_count=1,
            builder_version=DATASET_CATALOG_BUILDER_VERSION,
        )


# ---------------------------------------------------------------------------
# F. COMPLETE + EMPTY and the trust boundary.
# ---------------------------------------------------------------------------


def test_catalog_indexes_complete_and_empty(complete_build, empty_build):
    result = build_dataset_catalog(
        candidate_build_dirs=(complete_build.build_path, empty_build.build_path)
    )
    assert result.dataset_count == 2
    statuses = {
        entry.dataset_facts.status
        for entry in result.entries
    }
    assert statuses == {STATUS_COMPLETE, STATUS_EMPTY}
    assert len(result.catalog_content_id) == 64


def test_builder_never_accepts_raw_manifest_dir(tmp_path):
    """A directory that is not a verified Dataset (no manifest) fails
    closed before any projection."""
    bogus = tmp_path / ("e" * 64)
    bogus.mkdir()
    (bogus / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DatasetCatalogBuildError):
        build_dataset_catalog(candidate_build_dirs=(bogus,))


def test_builder_is_side_effect_free(complete_build, tmp_path):
    """The builder must not write, delete, repair, or touch any file."""
    before = tree_snapshot(complete_build.build_path)
    before_parent = tree_snapshot(complete_build.build_path.parent)
    build_dataset_catalog(candidate_build_dirs=(complete_build.build_path,))
    build_dataset_catalog(dataset_root=complete_build.build_path.parent)
    assert tree_snapshot(complete_build.build_path) == before
    assert tree_snapshot(complete_build.build_path.parent) == before_parent


def test_builder_needs_no_settings_file(tmp_path):
    """Building from an explicit candidate set in a directory without any
    settings.yaml must succeed (no settings are ever loaded)."""
    from market_vault.dataset import dataset_catalog_builder as builder_mod

    empty_dir = tmp_path / "no-settings"
    empty_dir.mkdir()
    assert not (empty_dir / "settings.yaml").exists()
    result = builder_mod.build_dataset_catalog(candidate_build_dirs=())
    assert result.dataset_count == 0
