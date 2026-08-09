"""Focused v0.7.0 PR-3 regression: ArtifactClient verified reader access.

Covers the frozen PR-3 reader surface:

- the exact two public business methods and their frozen signatures;
- direct verbatim delegation: the exact ``build_dir`` value reaches the
  formal reader and the exact formal result returns unchanged;
- error preservation: formal ``CanonicalArtifactValidationError`` /
  ``DatasetArtifactValidationError`` propagate unwrapped;
- the method-call import boundary: reader imports happen only at actual
  invocation and load nothing beyond the formal reader chain;
- read-only behavior against real minimal committed-style artifact
  fixtures (built through the production materializers): the client
  result is the exact formal verified object, no files are created or
  modified;
- fail-closed corruption: a corrupt artifact produces the exact formal
  validation error, never a partial client success;
- no Dataset Catalog capability.

Fixtures are constructed locally with the production builders only (no
helper imports from other test modules), mirroring the deterministic
patterns of the formal reader tests. No network, no OpenD, no current
time.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault import ArtifactClient
from market_vault.canonical import (
    CanonicalArtifactValidationError,
    CanonicalRequestKey,
    VerifiedCanonicalBuild,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    DATASET_KIND_SUPERVISED,
    DATASET_MANIFEST_SCHEMA_VERSION,
    FEATURE_SPEC_SCHEMA_VERSION,
    LABEL_SPEC_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    ChronologicalSplitSpec,
    CrossTradingDayPolicy,
    DatasetArtifactValidationError,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    VerifiedDatasetBuild,
    dataset_orchestration_schema,
    load_verified_dataset,
    materialize_dataset_artifacts,
    orchestrate_dataset_build,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

NY = "America/New_York"
UTC = timezone.utc
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m",
    requested_session="ALL",
    adjustment="NONE",
    source_schema_version="10.9",
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"


# ---------------------------------------------------------------------------
# Minimal deterministic artifact fixtures (production builders only).
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
            "close": [100.5] * len(time_keys),
            "volume": [100] * len(time_keys),
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
    run.finished_at = datetime(
        trade_date.year, trade_date.month, trade_date.day, 14, 0, tzinfo=UTC
    )
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def canonical_output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize_canonical(cfg: Settings, *, symbols=None, trade_dates=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=DEFAULT_KEY,
        output_root=canonical_output_root(cfg),
        created_at=CREATED_AT,
    )


def build_canonical(
    cfg: Settings,
    *,
    run_id: str,
    time_keys: list[str],
) -> Path:
    """One real canonical build directory via the production materializer."""
    write_snapshot(
        cfg, code="US.MU", trade_date=date(2026, 7, 1), run_id=run_id,
        time_keys=time_keys,
    )
    result = materialize_canonical(
        cfg, symbols=["US.MU"], trade_dates=[date(2026, 7, 1)]
    )
    return Path(result.build_path)


def feature_spec() -> FeatureSpec:
    return FeatureSpec(
        spec_schema_version=FEATURE_SPEC_SCHEMA_VERSION,
        name="sr",
        version="v1",
        output=DatasetField(name="sr", logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_SIMPLE,
        parameters=(SpecParameter("window_bars", 2),),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
    )


def label_spec() -> LabelSpec:
    return LabelSpec(
        spec_schema_version=LABEL_SPEC_SCHEMA_VERSION,
        name="fr",
        version="v1",
        output=DatasetField(name="fr", logical_type="float64", nullable=False),
        input_canonical_fields=("close",),
        transform_ref=REF_FORWARD,
        parameters=(),
        requirements=SpecVersionRequirements(
            canonical_schema_versions=("market-bars-canonical-schema-v1",),
            source_schema_versions=("10.9",),
        ),
        observation_window=LabelObservationWindow("BARS", 1, 1),
        horizon=LabelHorizon("BARS", 2),
        alignment_rule="FEATURE_CLOSE_ALIGNED",
        missing_data_policy="INCOMPLETE",
        cross_trading_day=CrossTradingDayPolicy(False, None),
    )


def split_spec() -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version="market-vault-chronological-split-spec-v1",
        name="chrono",
        version="v1",
        boundary_timezone=NY,
        train_end_date=date(2026, 6, 30),
        validation_end_date=date(2026, 7, 1),
        test_end_date=date(2026, 7, 2),
        assignment_rule="FEATURE_WINDOW_CLOSE_DATE",
        purge_rule="ACTUAL_LABEL_END",
        incomplete_label_policy="EXCLUDE",
        out_of_range_policy="EXCLUDE",
    )


def dataset_request() -> PITSampleRequest:
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


def build_dataset(cfg: Settings, canonical_builds: list[Path], tmp_path: Path) -> Path:
    """One real Dataset build directory via the production orchestration
    and materialization pipeline."""
    feature_specs = (feature_spec(),)
    label_specs = (label_spec(),)
    scope = DatasetScope(
        symbols=("US.MU",),
        trade_dates=(date(2026, 7, 1),),
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )
    schema = dataset_orchestration_schema(
        feature_specs, label_specs, include_dataset_as_of=False
    )
    result = orchestrate_dataset_build(
        builds=tuple(
            load_verified_canonical_build(b) for b in canonical_builds
        ),
        requests=(dataset_request(),),
        feature_specs=feature_specs,
        label_specs=label_specs,
        split_spec=split_spec(),
        scope=scope,
        schema=schema,
        dataset_as_of=None,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )
    mresult = materialize_dataset_artifacts(
        result, output_root=tmp_path / "datasets", built_at=BUILT_AT
    )
    return Path(mresult.build_path)


def artifact_snapshot(build: Path) -> dict[str, str]:
    """{relative path: sha256} over every file under the build."""
    snap = {}
    for root, _, files in os.walk(build):
        for name in files:
            path = Path(root) / name
            rel = path.relative_to(build).as_posix()
            snap[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snap


@pytest.fixture(scope="module")
def canonical_build(tmp_path_factory):
    cfg = settings(tmp_path_factory.mktemp("mv_canonical"))
    calendar(cfg)
    build = build_canonical(
        cfg,
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 6),
    )
    return build


@pytest.fixture(scope="module")
def dataset_build(tmp_path_factory):
    root = tmp_path_factory.mktemp("mv_dataset")
    cfg = settings(root)
    calendar(cfg)
    build_a = build_canonical(
        cfg,
        run_id="run-a",
        time_keys=minute_keys("2026-07-01 09:30:00", 6),
    )
    build_f = build_canonical(
        cfg,
        run_id="run-f",
        time_keys=minute_keys("2026-07-01 09:36:00", 6),
    )
    return build_dataset(cfg, [build_a, build_f], root)


# ---------------------------------------------------------------------------
# 1. API shape.
# ---------------------------------------------------------------------------


def test_exactly_two_public_read_methods():
    public = sorted(
        n for n in dir(ArtifactClient) if not n.startswith("_")
    )
    assert public == ["load_canonical_build", "load_dataset"]


def test_reader_signatures_are_exactly_self_build_dir():
    import inspect

    assert list(inspect.signature(ArtifactClient.load_canonical_build).parameters) == [
        "self",
        "build_dir",
    ]
    assert list(inspect.signature(ArtifactClient.load_dataset).parameters) == [
        "self",
        "build_dir",
    ]


# ---------------------------------------------------------------------------
# 2. Direct delegation.
# ---------------------------------------------------------------------------


def test_canonical_method_delegates_verbatim(monkeypatch):
    sentinel_build_dir = object()
    sentinel_result = object()
    calls = []

    def stub(build_dir):
        calls.append(build_dir)
        return sentinel_result

    monkeypatch.setattr(
        "market_vault.canonical.reader.load_verified_canonical_build", stub
    )
    result = ArtifactClient().load_canonical_build(sentinel_build_dir)
    assert calls == [sentinel_build_dir]
    assert result is sentinel_result


def test_dataset_method_delegates_verbatim(monkeypatch):
    sentinel_build_dir = object()
    sentinel_result = object()
    calls = []

    def stub(build_dir):
        calls.append(build_dir)
        return sentinel_result

    monkeypatch.setattr(
        "market_vault.dataset.reader.load_verified_dataset", stub
    )
    result = ArtifactClient().load_dataset(sentinel_build_dir)
    assert calls == [sentinel_build_dir]
    assert result is sentinel_result


def test_canonical_reader_called_exactly_once(monkeypatch):
    sentinel_result = object()
    calls = []

    def stub(build_dir):
        calls.append(build_dir)
        return sentinel_result

    monkeypatch.setattr(
        "market_vault.canonical.reader.load_verified_canonical_build", stub
    )
    result = ArtifactClient().load_canonical_build("x")
    assert result is sentinel_result
    assert calls == ["x"]


def test_dataset_reader_called_exactly_once(monkeypatch):
    sentinel_result = object()
    calls = []

    def stub(build_dir):
        calls.append(build_dir)
        return sentinel_result

    monkeypatch.setattr(
        "market_vault.dataset.reader.load_verified_dataset", stub
    )
    result = ArtifactClient().load_dataset("x")
    assert result is sentinel_result
    assert calls == ["x"]


# ---------------------------------------------------------------------------
# 3. Error preservation (no wrapping).
# ---------------------------------------------------------------------------


def test_canonical_reader_error_propagates_unwrapped(monkeypatch):
    expected = CanonicalArtifactValidationError("formal canonical failure")

    def stub(build_dir):
        raise expected

    monkeypatch.setattr(
        "market_vault.canonical.reader.load_verified_canonical_build", stub
    )
    with pytest.raises(CanonicalArtifactValidationError) as excinfo:
        ArtifactClient().load_canonical_build("x")
    assert excinfo.value is expected


def test_dataset_reader_error_propagates_unwrapped(monkeypatch):
    expected = DatasetArtifactValidationError("formal dataset failure")

    def stub(build_dir):
        raise expected

    monkeypatch.setattr(
        "market_vault.dataset.reader.load_verified_dataset", stub
    )
    with pytest.raises(DatasetArtifactValidationError) as excinfo:
        ArtifactClient().load_dataset("x")
    assert excinfo.value is expected


# ---------------------------------------------------------------------------
# 4. Lazy method-call boundary (fresh interpreters).
# ---------------------------------------------------------------------------

LAZY_BOUNDARY_PROBE = """
import sys
from market_vault import ArtifactClient
client = ArtifactClient()

# Before any invocation: neither the reader packages nor any heavy module
# may be loaded merely because ArtifactClient exists.
assert 'market_vault.canonical' not in sys.modules, sorted(m for m in sys.modules if m.startswith('market_vault.canonical'))
assert 'market_vault.dataset' not in sys.modules, sorted(m for m in sys.modules if m.startswith('market_vault.dataset'))
assert 'market_vault.config' not in sys.modules
assert 'market_vault.storage' not in sys.modules
assert 'duckdb' not in sys.modules
assert 'pandas' not in sys.modules
assert 'moomoo' not in sys.modules
assert 'futu' not in sys.modules

def loaded_reader_modules():
    return sorted(
        m
        for m in sys.modules
        if m.startswith('market_vault.canonical')
        or m.startswith('market_vault.dataset')
        or m in ('market_vault.config', 'market_vault.storage',
                 'duckdb', 'pandas', 'moomoo', 'futu')
    )

%METHOD_CALL%

after_client = loaded_reader_modules()

# The same failing invocation through the formal reader directly must load
# exactly the same module set: ArtifactClient adds nothing of its own.
import importlib
%DIRECT_IMPORT%
try:
    %DIRECT_CALL%
    raise SystemExit('direct reader call did not fail')
except Exception:
    pass

after_direct = loaded_reader_modules()
assert after_client == after_direct, (
    'client-loaded modules differ from direct reader modules\\n'
    f'client: {after_client}\\n'
    f'direct: {after_direct}'
)
print('V070_LAZY_BOUNDARY_OK')
"""


def run_python(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(
        Path(__file__).resolve().parents[1] / "src"
    )
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_canonical_method_call_boundary_loads_only_reader_chain():
    code = LAZY_BOUNDARY_PROBE.replace(
        "%METHOD_CALL%",
        "try:\n"
        "    client.load_canonical_build('definitely-missing-build')\n"
        "    raise SystemExit('canonical client call did not fail')\n"
        "except Exception as exc:\n"
        "    assert type(exc).__name__ == 'CanonicalArtifactValidationError', type(exc)",
    )
    code = code.replace(
        "%EXC_NAME%", "CanonicalArtifactValidationError"
    ).replace(
        "%DIRECT_IMPORT%",
        "from market_vault.canonical.reader import load_verified_canonical_build",
    ).replace(
        "%DIRECT_CALL%",
        "load_verified_canonical_build('definitely-missing-build')",
    )
    result = run_python(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V070_LAZY_BOUNDARY_OK" in result.stdout


def test_dataset_method_call_boundary_loads_only_reader_chain():
    code = LAZY_BOUNDARY_PROBE.replace(
        "%METHOD_CALL%",
        "try:\n"
        "    client.load_dataset('definitely-missing-build')\n"
        "    raise SystemExit('dataset client call did not fail')\n"
        "except Exception as exc:\n"
        "    assert type(exc).__name__ == 'DatasetArtifactValidationError', type(exc)",
    )
    code = code.replace(
        "%EXC_NAME%", "DatasetArtifactValidationError"
    ).replace(
        "%DIRECT_IMPORT%",
        "from market_vault.dataset.reader import load_verified_dataset",
    ).replace(
        "%DIRECT_CALL%",
        "load_verified_dataset('definitely-missing-build')",
    )
    result = run_python(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V070_LAZY_BOUNDARY_OK" in result.stdout


# ---------------------------------------------------------------------------
# 5. Read-only behavior on real fixtures.
# ---------------------------------------------------------------------------


def test_canonical_client_read_matches_direct_reader(canonical_build, tmp_path):
    build = canonical_build
    before_files = set(os.listdir(build))
    before_snapshot = artifact_snapshot(build)

    direct = load_verified_canonical_build(build)
    client_result = ArtifactClient().load_canonical_build(build)

    # Exact formal result type and identical verified facts.
    assert type(client_result) is type(direct)
    assert isinstance(client_result, VerifiedCanonicalBuild)
    assert client_result.canonical_build_id == direct.canonical_build_id
    assert client_result.canonical_content_id == direct.canonical_content_id
    assert client_result.resolution_content_id == direct.resolution_content_id
    assert client_result.gap_content_id == direct.gap_content_id
    assert client_result.manifest_payload == direct.manifest_payload
    assert client_result.bars == direct.bars
    assert client_result.canonical_row_version_ids == (
        direct.canonical_row_version_ids
    )

    # Read-only: no files created, no bytes changed.
    assert set(os.listdir(build)) == before_files
    assert artifact_snapshot(build) == before_snapshot


def test_dataset_client_read_matches_direct_reader(dataset_build, tmp_path):
    build = dataset_build
    before_files = set(os.listdir(build))
    before_snapshot = artifact_snapshot(build)

    direct = load_verified_dataset(build)
    client_result = ArtifactClient().load_dataset(build)

    # Exact formal result type and identical verified facts.
    assert type(client_result) is type(direct)
    assert isinstance(client_result, VerifiedDatasetBuild)
    assert client_result.dataset_id == direct.dataset_id
    assert client_result.dataset_kind == direct.dataset_kind
    assert client_result.status == direct.status
    assert client_result.schema == direct.schema
    assert client_result.rows == direct.rows
    assert client_result.split_result == direct.split_result
    assert client_result.manifest_payload == direct.manifest_payload
    assert client_result.build_report_payload == direct.build_report_payload

    # Read-only: no files created, no bytes changed.
    assert set(os.listdir(build)) == before_files
    assert artifact_snapshot(build) == before_snapshot


def test_canonical_client_read_no_parent_side_effects(canonical_build, tmp_path):
    parent = canonical_build.parent
    before = set(os.listdir(parent))
    ArtifactClient().load_canonical_build(canonical_build)
    assert set(os.listdir(parent)) == before


def test_dataset_client_read_no_parent_side_effects(dataset_build, tmp_path):
    parent = dataset_build.parent
    before = set(os.listdir(parent))
    ArtifactClient().load_dataset(dataset_build)
    assert set(os.listdir(parent)) == before


# ---------------------------------------------------------------------------
# 6. Invalid / corrupt artifact fails closed.
# ---------------------------------------------------------------------------


def test_canonical_client_corrupt_artifact_fails_closed(canonical_build):
    manifest = canonical_build / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original[: len(original) // 2])
    try:
        with pytest.raises(CanonicalArtifactValidationError):
            ArtifactClient().load_canonical_build(canonical_build)
    finally:
        manifest.write_bytes(original)


def test_canonical_client_missing_path_fails_closed(tmp_path):
    missing = tmp_path / "no-such-canonical-build"
    with pytest.raises(CanonicalArtifactValidationError):
        ArtifactClient().load_canonical_build(missing)


def test_dataset_client_corrupt_artifact_fails_closed(dataset_build):
    manifest = dataset_build / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original[: len(original) // 2])
    try:
        with pytest.raises(DatasetArtifactValidationError):
            ArtifactClient().load_dataset(dataset_build)
    finally:
        manifest.write_bytes(original)


def test_dataset_client_missing_path_fails_closed(tmp_path):
    missing = tmp_path / "no-such-dataset-build"
    with pytest.raises(DatasetArtifactValidationError):
        ArtifactClient().load_dataset(missing)


# ---------------------------------------------------------------------------
# 7. No Dataset Catalog capability.
# ---------------------------------------------------------------------------


def test_no_dataset_catalog_capability():
    assert not hasattr(ArtifactClient, "load_dataset_catalog")
    assert not hasattr(ArtifactClient(), "load_dataset_catalog")
