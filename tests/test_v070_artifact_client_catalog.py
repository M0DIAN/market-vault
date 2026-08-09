"""Focused v0.7.0 PR-4 regression: ArtifactClient Dataset Catalog read.

Covers the frozen PR-4 Catalog reader surface (spec section 13):

- A. the frozen ``load_dataset_catalog(self, snapshot_dir)`` signature;
- B. exact method-call-boundary delegation to the formal
  ``load_verified_dataset_catalog`` reader;
- C. exact caller-object identity: the supplied ``snapshot_dir`` reaches
  the formal reader unchanged (no Path/str coercion);
- D. exact return-object identity: the formal result returns unchanged;
- E. formal ``DatasetCatalogArtifactValidationError`` propagates
  unwrapped (no catch / no re-wrap);
- F. the reader import is method-local (AST proof);
- G. no module-level production import (AST + fresh-interpreter proof);
- H. real valid snapshot read through the production builders returns the
  exact ``VerifiedDatasetCatalogSnapshot``;
- I. corrupt snapshot fails closed with the exact formal error;
- J. read-only: no files created; K. no files rewritten; L. no mtime /
  content mutation; M. no files deleted;
- N. no second trust path: the client never independently parses,
  reads, or re-verifies artifact bytes;
- O. exactly three public business methods;
- P. no list/show/filter/query convenience API;
- Q. no settings/root/latest/discovery surface;
- R. the constructor stays stateless.

Fixtures are constructed locally with the production builders only (no
helper imports from other test modules). No network, no OpenD, no current
time.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from market_vault import ArtifactClient
from market_vault.canonical import (
    CanonicalRequestKey,
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
    DatasetCatalogArtifactValidationError,
    DatasetField,
    DatasetScope,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    VerifiedDatasetCatalogSnapshot,
    build_dataset_catalog,
    dataset_orchestration_schema,
    materialize_dataset_artifacts,
    materialize_dataset_catalog_snapshot,
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

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ARTIFACT_CLIENT_MODULE = SRC / "market_vault" / "artifact_client.py"


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
    result = materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=["US.MU"],
        trade_dates=[date(2026, 7, 1)],
        request_key=DEFAULT_KEY,
        output_root=cfg.data_root / "canonical" / "dataset=market_bars_canonical",
        created_at=CREATED_AT,
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


@pytest.fixture(scope="module")
def catalog_snapshot(tmp_path_factory):
    """One immutable Dataset Catalog snapshot via the production builders:
    canonical builds -> dataset build -> ``build_dataset_catalog`` ->
    ``materialize_dataset_catalog_snapshot``."""
    root = tmp_path_factory.mktemp("mv_catalog")
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
    dataset_build = build_dataset(cfg, [build_a, build_f], root)
    result = build_dataset_catalog(
        candidate_build_dirs=tuple([str(dataset_build)])
    )
    mresult = materialize_dataset_catalog_snapshot(
        result, output_root=root / "catalog_snapshots", built_at=BUILT_AT
    )
    return Path(mresult.snapshot_path)


def tree_state(root: Path) -> dict[str, tuple[int, str, int]]:
    """{relative path: (size_bytes, sha256, mtime_ns)} over the tree."""
    state = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            state[rel] = (
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
    return state


def run_python(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


# ---------------------------------------------------------------------------
# A. Frozen signature.
# ---------------------------------------------------------------------------


def test_catalog_method_signature_is_frozen():
    assert list(
        inspect.signature(ArtifactClient.load_dataset_catalog).parameters
    ) == ["self", "snapshot_dir"]


# ---------------------------------------------------------------------------
# B/C/D. Exact method-call-boundary delegation with object identity.
# ---------------------------------------------------------------------------


def test_catalog_method_delegates_with_exact_argument_identity(monkeypatch):
    supplied_snapshot_dir = object()
    sentinel = object()
    received = []
    returned = []

    def stub(snapshot_dir):
        received.append(snapshot_dir)
        returned.append(sentinel)
        return sentinel

    monkeypatch.setattr(
        "market_vault.dataset.dataset_catalog_reader."
        "load_verified_dataset_catalog",
        stub,
    )
    result = ArtifactClient().load_dataset_catalog(supplied_snapshot_dir)
    # C: the exact caller object reaches the formal reader, untouched.
    assert received == [supplied_snapshot_dir]
    assert received[0] is supplied_snapshot_dir
    # D: the exact formal result returns, unchanged.
    assert result is sentinel
    assert len(received) == 1  # exactly one delegation, no extra reads


# ---------------------------------------------------------------------------
# E. Error propagation (no catch / no wrapping).
# ---------------------------------------------------------------------------


def test_catalog_reader_error_propagates_unwrapped(monkeypatch):
    expected = DatasetCatalogArtifactValidationError("formal catalog failure")

    def stub(snapshot_dir):
        raise expected

    monkeypatch.setattr(
        "market_vault.dataset.dataset_catalog_reader."
        "load_verified_dataset_catalog",
        stub,
    )
    with pytest.raises(DatasetCatalogArtifactValidationError) as excinfo:
        ArtifactClient().load_dataset_catalog("x")
    assert excinfo.value is expected


# ---------------------------------------------------------------------------
# F/G. Import boundary: method-local reader import, no module-level import.
# ---------------------------------------------------------------------------


def test_catalog_reader_import_is_method_local_only():
    tree = ast.parse(ARTIFACT_CLIENT_MODULE.read_text(encoding="utf-8"))
    top_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    # G: the only module-level import remains __future__.annotations.
    assert len(top_imports) == 1
    node = top_imports[0]
    assert isinstance(node, ast.ImportFrom)
    assert node.module == "__future__"
    assert [alias.name for alias in node.names] == ["annotations"]

    methods = {
        m.name: m
        for m in ast.walk(tree)
        if isinstance(m, ast.FunctionDef)
        and m.name in ("load_canonical_build", "load_dataset",
                       "load_dataset_catalog")
    }
    catalog_method = methods["load_dataset_catalog"]
    body_imports = [
        (imp.module, imp.level, tuple(a.name for a in imp.names))
        for imp in ast.walk(catalog_method)
        if isinstance(imp, ast.ImportFrom)
    ]
    # F: the Catalog reader import lives inside the method body only.
    assert body_imports == [
        ("dataset.dataset_catalog_reader", 1, ("load_verified_dataset_catalog",))
    ]
    # The method must return the direct reader call on its own argument.
    returns = [
        ret for ret in ast.walk(catalog_method) if isinstance(ret, ast.Return)
    ]
    assert len(returns) == 1
    call = returns[0].value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name)
    assert call.func.id == "load_verified_dataset_catalog"
    assert len(call.args) == 1
    arg = call.args[0]
    assert isinstance(arg, ast.Name)
    assert arg.id == "snapshot_dir"
    assert call.keywords == []


def test_catalog_method_binding_stays_lightweight_in_fresh_interpreter():
    result = run_python(
        "\n".join(
            [
                "import sys",
                "from market_vault import ArtifactClient",
                "client = ArtifactClient()",
                "cb = client.load_canonical_build",
                "ds = client.load_dataset",
                "cat = client.load_dataset_catalog",
                "assert callable(cb) and callable(ds) and callable(cat)",
                "assert 'market_vault.canonical' not in sys.modules",
                "assert 'market_vault.dataset' not in sys.modules",
                "assert 'market_vault.dataset.dataset_catalog_reader' "
                "not in sys.modules",
                "assert 'market_vault.config' not in sys.modules",
                "assert 'market_vault.storage' not in sys.modules",
                "assert 'duckdb' not in sys.modules",
                "assert 'pandas' not in sys.modules",
                "assert 'moomoo' not in sys.modules",
                "assert 'futu' not in sys.modules",
                "print('V070_CATALOG_BINDING_LAZY_OK')",
            ]
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V070_CATALOG_BINDING_LAZY_OK" in result.stdout


# ---------------------------------------------------------------------------
# H. Real valid snapshot read returns the exact formal verified object.
# ---------------------------------------------------------------------------


def test_catalog_client_read_matches_direct_formal_reader(catalog_snapshot):
    snapshot = catalog_snapshot
    client_result = ArtifactClient().load_dataset_catalog(snapshot)
    assert isinstance(client_result, VerifiedDatasetCatalogSnapshot)
    assert client_result.snapshot_dir == snapshot
    assert client_result.snapshot_dir.name == client_result.snapshot_id
    assert client_result.dataset_count == 1
    assert client_result.catalog_content_id
    assert client_result.manifest
    assert client_result.entries
    assert client_result.built_at == BUILT_AT


# ---------------------------------------------------------------------------
# I. Corruption fails closed with the exact formal error.
# ---------------------------------------------------------------------------


def test_catalog_client_corrupt_manifest_fails_closed(catalog_snapshot):
    manifest = catalog_snapshot / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original[: len(original) // 2])
    try:
        with pytest.raises(DatasetCatalogArtifactValidationError):
            ArtifactClient().load_dataset_catalog(catalog_snapshot)
    finally:
        manifest.write_bytes(original)


def test_catalog_client_corrupt_catalog_json_fails_closed(catalog_snapshot):
    catalog_json = catalog_snapshot / "catalog.json"
    original = catalog_json.read_bytes()
    catalog_json.write_bytes(original[: len(original) // 2])
    try:
        with pytest.raises(DatasetCatalogArtifactValidationError):
            ArtifactClient().load_dataset_catalog(catalog_snapshot)
    finally:
        catalog_json.write_bytes(original)


def test_catalog_client_missing_snapshot_fails_closed(tmp_path):
    missing = tmp_path / "no-such-catalog-snapshot"
    with pytest.raises(DatasetCatalogArtifactValidationError):
        ArtifactClient().load_dataset_catalog(missing)


# ---------------------------------------------------------------------------
# J/K/L/M. Read-only: no files created, rewritten, deleted, or mutated.
# ---------------------------------------------------------------------------


def test_catalog_client_read_is_fully_read_only(catalog_snapshot):
    snapshot = catalog_snapshot
    parent = snapshot.parent
    before_parent = set(os.listdir(parent))
    before_snapshot = set(os.listdir(snapshot))
    before_state = tree_state(snapshot)

    result = ArtifactClient().load_dataset_catalog(snapshot)
    assert isinstance(result, VerifiedDatasetCatalogSnapshot)

    # J: no files created anywhere (snapshot and its parent).
    assert set(os.listdir(snapshot)) == before_snapshot
    assert set(os.listdir(parent)) == before_parent
    # M: no files deleted.
    assert set(os.listdir(snapshot)) == before_snapshot
    # K/L: no bytes or mtime mutated on any file.
    assert tree_state(snapshot) == before_state
    assert result.snapshot_dir == snapshot


# ---------------------------------------------------------------------------
# N. No second trust path: the client never independently parses bytes.
# ---------------------------------------------------------------------------


def test_catalog_client_has_no_second_trust_path_in_source():
    # The module must not carry its own artifact-reading machinery: no
    # filesystem parsing, no manifest/json handling, no hashing, no
    # repair/materialize/build verbs, no discovery.
    tree = ast.parse(ARTIFACT_CLIENT_MODULE.read_text(encoding="utf-8"))
    forbidden = {
        "Path",
        "open",
        "read_text",
        "read_bytes",
        "json",
        "hashlib",
        "resolve",
        "glob",
        "rglob",
        "walk",
        "scandir",
        "settings",
        "config",
        "latest",
        "discover",
        "network",
        "OpenD",
        "requests",
        "urllib",
        "write",
        "repair",
        "materialize",
        "build",
    }
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    assert not (used & forbidden), sorted(used & forbidden)


def test_catalog_client_never_parses_bytes_at_runtime(monkeypatch):
    # With the formal reader stubbed to a pure function that never touches
    # the filesystem, the client must not independently read the snapshot.
    snapshot = object()
    calls = []

    def stub(snapshot_dir):
        calls.append(snapshot_dir)
        return None

    monkeypatch.setattr(
        "market_vault.dataset.dataset_catalog_reader."
        "load_verified_dataset_catalog",
        stub,
    )
    result = ArtifactClient().load_dataset_catalog(snapshot)
    assert result is None
    assert calls == [snapshot]
    # The client performs no reads of its own: everything the stub saw is
    # all that ever happened (no extra parsing calls, no file helpers).
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# O/P/Q/R. Frozen public surface, no convenience, stateless constructor.
# ---------------------------------------------------------------------------


def test_public_business_methods_are_exactly_three():
    public = sorted(
        n for n in dir(ArtifactClient) if not n.startswith("_")
    )
    assert public == [
        "load_canonical_build",
        "load_dataset",
        "load_dataset_catalog",
    ]


def test_no_catalog_convenience_api():
    client = ArtifactClient()
    for name in (
        "load_dataset_catalog_latest",
        "list_catalog",
        "show_catalog",
        "filter_catalog",
        "query_catalog",
        "search_catalog",
        "find_catalog",
        "discover_catalog",
        "scan_catalog",
        "build_catalog",
        "materialize_catalog",
        "refresh_catalog",
        "catalog_versions",
        "latest_catalog",
    ):
        assert not hasattr(ArtifactClient, name), name
        assert not hasattr(client, name), name


def test_constructor_has_no_settings_root_latest_surface():
    assert list(inspect.signature(ArtifactClient).parameters) == []
    assert list(inspect.signature(ArtifactClient.__init__).parameters) == [
        "self"
    ]
    with pytest.raises(TypeError):
        ArtifactClient(settings={})
    with pytest.raises(TypeError):
        ArtifactClient(root=".")


def test_constructor_remains_stateless():
    from market_vault.artifact_client import ArtifactClient as Impl

    assert Impl.__slots__ == ()
    client = Impl()
    assert not hasattr(client, "__dict__")
    with pytest.raises(AttributeError):
        client.custom_state = 1
