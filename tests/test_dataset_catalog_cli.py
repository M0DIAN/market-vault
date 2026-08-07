"""Offline deterministic tests of the Dataset Catalog CLI (v0.6.0 PR-7).

Covers the four commands (dataset-catalog-build / -verify / -list /
-show), the settings-independent dispatch, the exact build parameter
contract (exactly one candidate mode, explicit output_root / built_at,
CLI path boundary), the real Builder -> Materializer -> Reader build
chain E2E (root mode, explicit repeated candidate mode, empty root,
idempotency, timezone-equivalent built_at), the read-only verify / list /
show contract (tree + mtimes untouched, no Dataset reload, no raw
catalog.json / manifest.json re-read), the pure in-memory list filters
with AND semantics and fixed pagination, the exact dataset_id show lookup
with the full lossless 14-field facts record and the historical recorded
build path, the unified exit 0 / 1 / 2 failure contract, the corruption
matrix (missing _SUCCESS, modified catalog.json, modified manifest.json,
extra file, wrong dirname) across verify / list / show, and the
deterministic byte-identical output. All Datasets are produced through
the public chain (verified Canonical reader -> orchestrator ->
materializer -> verified Dataset reader); no network, no OpenD, no
settings, no current time, and no real market data.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import cli as cli_module
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset import (
    CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION,
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
    DatasetScope,
    DatasetField,
    FeatureSpec,
    LabelHorizon,
    LabelObservationWindow,
    LabelSpec,
    PITSampleRequest,
    SpecParameter,
    SpecVersionRequirements,
    build_dataset_catalog,
    dataset_orchestration_schema,
    load_verified_dataset,
    materialize_dataset_artifacts,
    materialize_dataset_catalog_snapshot,
    load_verified_dataset_catalog,
    orchestrate_dataset_build,
)
from market_vault.dataset.dataset_catalog_cli import DATASET_CATALOG_COMMANDS
from market_vault.dataset.dataset_catalog_cli_models import (
    DATASET_CATALOG_CLI_CONTRACT_VERSION,
    DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UTC = timezone.utc
NY = "America/New_York"
BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
SNAPSHOT_BUILT_AT = datetime(2026, 8, 6, 1, 2, 3, 456789, tzinfo=UTC)
SNAPSHOT_BUILT_AT_STR = "2026-08-06T01:02:03.456789+00:00"
# The same instant in another explicit timezone (timezone-equivalence).
SNAPSHOT_BUILT_AT_JST = "2026-08-06T10:02:03.456789+09:00"
# A different instant.
SNAPSHOT_BUILT_AT_OTHER = "2026-08-06T02:02:03.456789+00:00"

REF_SIMPLE = "market_vault.dataset.feature_transforms.simple_return:simple_return"
REF_FORWARD = "market_vault.dataset.label_transforms.forward_return:forward_return"

FACTS_FIELDS = (
    "dataset_id",
    "dataset_kind",
    "status",
    "logical_row_count",
    "dataset_schema_id",
    "logical_dataset_content_id",
    "dataset_as_of",
    "scope",
    "feature_spec_pins",
    "label_spec_pins",
    "split_spec_pin",
    "canonical_build_pins",
    "canonical_row_version_ids",
    "completion",
)
LIST_FILTER_KEYS = (
    "status",
    "dataset_kind",
    "symbol",
    "trade_date",
    "interval",
    "adjustment",
    "requested_session",
)


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
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source_schema_version="10.9",
    )


def calendar(cfg: Settings, *, trade_date: date) -> None:
    frame = pd.DataFrame(
        {"time": [trade_date.isoformat()], "trade_date_type": ["WHOLE"]}
    )
    curated = normalize_trading_calendar(
        frame,
        market="US",
        code=None,
        requested_start_date=trade_date,
        requested_end_date=trade_date,
        captured_at=pd.Timestamp("2026-08-01T01:00:00Z"),
        source="moomoo",
        source_schema_version=cfg.source_schema_version,
        run_id="cal",
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
        raw,
        requested_trade_date=trade_date,
        interval="1m",
        requested_session="ALL",
        adjustment="NONE",
        source=cfg.source,
        source_schema_version=cfg.source_schema_version,
        run_id=run_id,
    )
    store.write_curated(
        curated, trade_date, "1m", [code], "ALL", "NONE", run_id=run_id
    )
    run = RunManifest(
        requested_trade_date=trade_date,
        requested_symbols=[code],
        interval="1m",
        session="ALL",
        adjustment="NONE",
        run_id=run_id,
    )
    run.successful_symbols = [code]
    run.status = "SUCCESS"
    run.finished_at = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def canonical_output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize_canonical(
    cfg: Settings, *, symbols=None, trade_dates=None
):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols or ["US.MU"],
        trade_dates=trade_dates or [date(2026, 7, 1)],
        request_key=default_key(),
        output_root=canonical_output_root(cfg),
        created_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def verified_canonical(build_result):
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


def request(code: str, trade_date: date) -> PITSampleRequest:
    return PITSampleRequest(
        code=code,
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
        anchor_market_calendar_date=trade_date,
        feature_window_start=datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
        feature_window_close=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_window_start=datetime(2026, 7, 1, 13, 36, tzinfo=UTC),
        label_window_close=datetime(2026, 7, 1, 13, 42, tzinfo=UTC),
    )


def scope(
    symbols=("US.MU",), trade_dates=(date(2026, 7, 1),)
) -> DatasetScope:
    return DatasetScope(
        symbols=symbols,
        trade_dates=trade_dates,
        interval="1m",
        adjustment="NONE",
        requested_session="ALL",
    )


def orchestrate(fixtures, *, requests, ds_scope):
    feature_specs = [feature_spec()]
    label_specs = [label_spec()]
    split_spec = chronological_spec()
    schema = dataset_orchestration_schema(
        feature_specs, label_specs, include_dataset_as_of=False
    )
    return orchestrate_dataset_build(
        builds=tuple(fixtures.builds),
        requests=tuple(requests),
        feature_specs=tuple(feature_specs),
        label_specs=tuple(label_specs),
        split_spec=split_spec,
        scope=ds_scope,
        schema=schema,
        dataset_as_of=None,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory):
    root = tmp_path_factory.mktemp("mv_catalog_cli")
    cfg = settings(root)
    calendar(cfg, trade_date=date(2026, 7, 1))
    calendar(cfg, trade_date=date(2026, 7, 2))

    def build(code, trade_date, run_id, time_keys, closes):
        write_snapshot(
            cfg,
            code=code,
            trade_date=trade_date,
            run_id=run_id,
            time_keys=time_keys,
            closes=closes,
        )
        return verified_canonical(
            materialize_canonical(
                cfg, symbols=[code], trade_dates=[trade_date]
            )
        )

    mu1 = build(
        "US.MU", date(2026, 7, 1), "run-mu1",
        minute_keys("2026-07-01 09:30:00", 6),
        [100.0, 110.0, 112.0, 118.0, 120.0, 110.0],
    )
    mu2 = build(
        "US.MU", date(2026, 7, 2), "run-mu2",
        minute_keys("2026-07-02 09:30:00", 6),
        [90.0, 95.0, 97.0, 99.0, 101.0, 100.0],
    )
    aapl = build(
        "US.AAPL", date(2026, 7, 1), "run-aapl",
        minute_keys("2026-07-01 09:30:00", 6),
        [200.0, 205.0, 210.0, 208.0, 212.0, 215.0],
    )
    return SimpleNamespace(builds=[mu1, mu2, aapl], cfg=cfg)


@pytest.fixture(scope="module")
def datasets(fixtures, tmp_path_factory):
    """Three real verified Datasets with distinct dataset_ids sharing one
    output root: two COMPLETE (US.MU and US.AAPL on 2026-07-01) and one
    EMPTY (US.MU on 2026-07-02)."""
    root = Path(tmp_path_factory.mktemp("mv_catalog_cli_datasets"))
    out = root / "output"

    def build_one(requests, ds_scope):
        result = orchestrate(fixtures, requests=requests, ds_scope=ds_scope)
        assert result.status in (STATUS_COMPLETE, STATUS_EMPTY)
        mresult = materialize_dataset_artifacts(
            result, output_root=out, built_at=BUILT_AT
        )
        return load_verified_dataset(mresult.build_path)

    a = build_one(
        [request("US.MU", date(2026, 7, 1))],
        scope(symbols=("US.MU",), trade_dates=(date(2026, 7, 1),)),
    )
    b = build_one(
        [request("US.AAPL", date(2026, 7, 1))],
        scope(symbols=("US.AAPL",), trade_dates=(date(2026, 7, 1),)),
    )
    c = build_one(
        [],
        scope(symbols=("US.MU",), trade_dates=(date(2026, 7, 2),)),
    )
    assert len({a.dataset_id, b.dataset_id, c.dataset_id}) == 3
    return SimpleNamespace(a=a, b=b, c=c, root=out)


@pytest.fixture(scope="module")
def catalog_snapshot(datasets, tmp_path_factory):
    """One real verified snapshot of all three Datasets (built through the
    public API; the CLI E2E build is covered separately)."""
    root = Path(tmp_path_factory.mktemp("mv_catalog_cli_snapshot"))
    build_result = build_dataset_catalog(dataset_root=datasets.root)
    mresult = materialize_dataset_catalog_snapshot(
        build_result, output_root=root, built_at=SNAPSHOT_BUILT_AT
    )
    assert mresult.created_new_snapshot
    verified = load_verified_dataset_catalog(mresult.snapshot_path)
    assert verified.dataset_count == 3
    return SimpleNamespace(
        verified=verified,
        materialization=mresult,
        snapshot_dir=mresult.snapshot_path,
        snapshot_id=mresult.snapshot_id,
    )


# ---------------------------------------------------------------------------
# CLI runner helpers.
# ---------------------------------------------------------------------------


def run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    try:
        code = cli_module.main(argv)
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_cli_subprocess(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "market_vault", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def load_json(text: str) -> dict:
    return json.loads(text)


def assert_failure(code: int, out: str, err: str, command: str) -> dict:
    assert code == 1
    assert out == ""
    payload = json.loads(err)
    assert payload["result_schema_version"] == DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION
    assert payload["cli_contract_version"] == DATASET_CATALOG_CLI_CONTRACT_VERSION
    assert payload["command"] == command
    assert payload["result"] == "FAILED"
    assert payload["error_type"] == "DatasetCatalogCLIError"
    assert payload["error"]
    return payload


def tree_snapshot(directory: Path) -> dict:
    """Per-entry (size, mtime_ns, sha256) map proving no-write."""
    result = {}
    for root, dirs, files in os.walk(directory):
        for name in sorted(dirs) + sorted(files):
            path = Path(root) / name
            rel = path.relative_to(directory).as_posix()
            st = path.lstat()
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1 << 16), b""):
                        digest.update(chunk)
                result[rel] = (st.st_size, st.st_mtime_ns, digest.hexdigest())
            else:
                result[rel + "/"] = (st.st_size, st.st_mtime_ns, None)
    return result


def copy_snapshot(snapshot_dir: Path, target: Path) -> Path:
    return Path(shutil.copytree(snapshot_dir, target))


def _make_symlink_or_skip(target: Path, link: Path) -> None:
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


# ---------------------------------------------------------------------------
# A. Registration and help.
# ---------------------------------------------------------------------------


def test_four_catalog_commands_registered(capsys):
    code, out, err = run_cli(["--help"], capsys)
    assert code == 0, err
    for command in DATASET_CATALOG_COMMANDS:
        assert command in out


def test_legacy_and_dataset_and_sample_commands_still_registered(capsys):
    code, out, err = run_cli(["--help"], capsys)
    assert code == 0, err
    for command in (
        "dataset-build",
        "dataset-verify",
        "dataset-inspect",
        "sample-generate",
        "init-catalog",
    ):
        assert command in out


@pytest.mark.parametrize(
    "command",
    sorted(DATASET_CATALOG_COMMANDS),
)
def test_catalog_command_help_exits_zero(command, capsys):
    code, out, err = run_cli([command, "--help"], capsys)
    assert code == 0, err
    assert out


def test_build_help_shows_mutually_exclusive_modes_and_required_options(
    capsys,
):
    code, out, err = run_cli(["dataset-catalog-build", "--help"], capsys)
    assert code == 0, err
    assert "--dataset-root PATH" in out
    assert "--candidate-build-dir PATH" in out
    assert "--output-root PATH" in out
    assert "--built-at ISO8601" in out


def test_verify_help_shows_snapshot_dir_only(capsys):
    code, out, err = run_cli(["dataset-catalog-verify", "--help"], capsys)
    assert code == 0, err
    assert "--snapshot-dir PATH" in out
    for forbidden in ("--root", "--latest", "--repair", "--force", "--dataset-root"):
        assert forbidden not in out


def test_list_help_shows_filters_and_pagination(capsys):
    code, out, err = run_cli(["dataset-catalog-list", "--help"], capsys)
    assert code == 0, err
    for option in (
        "--status",
        "--dataset-kind",
        "--symbol",
        "--trade-date",
        "--interval",
        "--adjustment",
        "--requested-session",
        "--offset",
        "--limit",
    ):
        assert option in out


def test_show_help_shows_snapshot_dir_and_dataset_id(capsys):
    code, out, err = run_cli(["dataset-catalog-show", "--help"], capsys)
    assert code == 0, err
    assert "--snapshot-dir PATH" in out
    assert "--dataset-id HEX" in out


# ---------------------------------------------------------------------------
# B. Build parameter contract (argparse stage).
# ---------------------------------------------------------------------------


def test_build_requires_exactly_one_candidate_mode(capsys):
    code, out, err = run_cli(
        ["dataset-catalog-build", "--output-root", "C:/x", "--built-at", SNAPSHOT_BUILT_AT_STR],
        capsys,
    )
    assert code == 2
    assert out == ""
    assert "one of the arguments --dataset-root --candidate-build-dir is required" in err
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", "C:/x",
            "--candidate-build-dir", "C:/y",
            "--output-root", "C:/z",
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert code == 2
    assert "not allowed with argument" in err


def test_build_requires_output_root_and_built_at(capsys):
    code, out, err = run_cli(
        ["dataset-catalog-build", "--dataset-root", "C:/x"], capsys
    )
    assert code == 2
    assert "--output-root" in err
    assert "--built-at" in err


def test_build_rejects_naive_built_at(capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", "C:/x",
            "--output-root", "C:/y",
            "--built-at", "2026-08-06T01:02:03.456789",
        ],
        capsys,
    )
    assert code == 2
    assert "timezone-aware" in err


def test_build_rejects_invalid_built_at_text(capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", "C:/x",
            "--output-root", "C:/y",
            "--built-at", "not-a-datetime",
        ],
        capsys,
    )
    assert code == 2
    assert "ISO 8601" in err
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", "C:/x",
            "--output-root", "C:/y",
            "--built-at", "",
        ],
        capsys,
    )
    assert code == 2


def test_build_rejects_forbidden_options(capsys):
    for option in ("--latest", "--force", "--overwrite", "--repair"):
        code, out, err = run_cli(
            [
                "dataset-catalog-build",
                "--dataset-root", "C:/x",
                "--output-root", "C:/y",
                "--built-at", SNAPSHOT_BUILT_AT_STR,
                option,
            ],
            capsys,
        )
        assert code == 2
        assert out == ""


def test_build_rejects_dot_components(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(catalog_snapshot.snapshot_dir.parent) + "/../x",
            "--output-root", "C:/y",
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert_failure(code, out, err, "dataset-catalog-build")
    assert "'..'" in err or ".." in err


# ---------------------------------------------------------------------------
# C. Build E2E (real chain; never mocked).
# ---------------------------------------------------------------------------


def build_snapshot(
    capsys,
    *,
    mode_args: list[str],
    built_at: str = SNAPSHOT_BUILT_AT_STR,
    output_root,
) -> dict:
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            *mode_args,
            "--output-root", str(output_root),
            "--built-at", built_at,
        ],
        capsys,
    )
    assert code == 0, err
    assert err == ""
    return json.loads(out)


def test_build_root_mode_e2e(datasets, tmp_path, capsys):
    """A: verified Datasets -> dataset-catalog-build --dataset-root ->
    immutable snapshot -> verify -> list -> show (full real CLI chain)."""
    out_root = tmp_path / "snapshots"
    payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=out_root,
    )
    assert payload["result"] == "SUCCESS"
    assert payload["created_new_snapshot"] is True
    assert payload["dataset_count"] == 3
    assert payload["snapshot_path"].startswith(str(out_root).replace("\\", "/"))
    assert payload["built_at"] == SNAPSHOT_BUILT_AT_STR
    assert payload["result_schema_version"] == DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION
    assert payload["cli_contract_version"] == DATASET_CATALOG_CLI_CONTRACT_VERSION
    assert payload["command"] == "dataset-catalog-build"
    assert payload["builder_version"]
    assert payload["materializer_version"]
    assert payload["reader_contract_version"]

    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", payload["snapshot_path"]],
        capsys,
    )
    assert code == 0, err
    verify = json.loads(out)
    assert verify["result"] == "VERIFIED"
    assert verify["snapshot_id"] == payload["snapshot_id"]
    assert verify["dataset_count"] == 3

    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", payload["snapshot_path"]],
        capsys,
    )
    assert code == 0, err
    listing = json.loads(out)
    assert listing["result"] == "LISTED"
    assert listing["matched_count"] == 3
    ids = [item["dataset_id"] for item in listing["datasets"]]
    assert ids == sorted(ids)

    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", payload["snapshot_path"],
            "--dataset-id", ids[0],
        ],
        capsys,
    )
    assert code == 0, err
    shown = json.loads(out)
    assert shown["result"] == "SHOWN"
    assert shown["dataset"]["dataset_facts"]["dataset_id"] == ids[0]


def test_build_candidate_mode_repeated(datasets, tmp_path, capsys):
    """B: --candidate-build-dir repeated; the explicit candidate set is
    order-independent and produces exactly the root-mode snapshot of the
    same three Datasets."""
    root_payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=tmp_path / "by-root",
    )
    reversed_candidates = [
        datasets.c.build_path.as_posix(),
        datasets.b.build_path.as_posix(),
        datasets.a.build_path.as_posix(),
    ]
    candidate_payload = build_snapshot(
        capsys,
        mode_args=sum(
            (["--candidate-build-dir", c] for c in reversed_candidates), []
        ),
        output_root=tmp_path / "by-candidate",
    )
    assert candidate_payload["dataset_count"] == 3
    assert candidate_payload["created_new_snapshot"] is True
    assert (
        candidate_payload["catalog_content_id"]
        == root_payload["catalog_content_id"]
    )
    assert (
        candidate_payload["snapshot_id"] == root_payload["snapshot_id"]
    )


def test_build_empty_root(tmp_path, capsys):
    """C: a root without any 64-hex candidate is a legal empty snapshot."""
    empty_root = tmp_path / "empty-root"
    empty_root.mkdir()
    (empty_root / "README.txt").write_text("not a candidate", encoding="utf-8")
    payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(empty_root)],
        output_root=tmp_path / "snapshots",
    )
    assert payload["dataset_count"] == 0
    assert payload["created_new_snapshot"] is True
    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", payload["snapshot_path"]],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["dataset_count"] == 0
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", payload["snapshot_path"]],
        capsys,
    )
    assert code == 0, err
    listing = json.loads(out)
    assert listing["matched_count"] == 0
    assert listing["datasets"] == []


def test_build_second_identical_is_idempotent(datasets, tmp_path, capsys):
    """D: same inputs + same built_at -> identical snapshot_id and
    created_new_snapshot == False with zero rewrites / mtime touches."""
    out_root = tmp_path / "snapshots"
    first = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=out_root,
    )
    before = tree_snapshot(Path(first["snapshot_path"]))
    second = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=out_root,
    )
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["created_new_snapshot"] is False
    after = tree_snapshot(Path(first["snapshot_path"]))
    assert after == before


def test_build_timezone_equivalent_built_at_same_snapshot(
    datasets, tmp_path, capsys
):
    """The same instant expressed in different timezones must produce the
    same snapshot; a different instant a different snapshot."""
    out_root = tmp_path / "snapshots"
    utc_payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=out_root,
        built_at=SNAPSHOT_BUILT_AT_STR,
    )
    jst_payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=out_root,
        built_at=SNAPSHOT_BUILT_AT_JST,
    )
    assert jst_payload["snapshot_id"] == utc_payload["snapshot_id"]
    assert jst_payload["built_at"] == SNAPSHOT_BUILT_AT_STR
    other_payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=out_root,
        built_at=SNAPSHOT_BUILT_AT_OTHER,
    )
    assert other_payload["snapshot_id"] != utc_payload["snapshot_id"]


def test_build_accepts_relative_cli_paths_from_cwd(
    datasets, monkeypatch, capsys
):
    """Explicit relative CLI paths are lexical-absolutized against cwd and
    never contain '.' / '..' components."""
    base = datasets.root.parent
    monkeypatch.chdir(base)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", "output",
            "--output-root", "rel-snapshots",
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["dataset_count"] == 3
    assert Path(payload["snapshot_path"]).is_absolute()
    assert payload["snapshot_path"].startswith(
        (base / "rel-snapshots").as_posix()
    )


# ---------------------------------------------------------------------------
# D. Build trust-boundary tests (through the CLI).
# ---------------------------------------------------------------------------


def test_build_rejects_corrupt_candidate(datasets, tmp_path, capsys):
    corrupt = tmp_path / datasets.a.dataset_id
    shutil.copytree(datasets.a.build_path, corrupt)
    manifest = corrupt / "manifest.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--candidate-build-dir", str(corrupt),
            "--output-root", str(tmp_path / "snapshots"),
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert_failure(code, out, err, "dataset-catalog-build")


def test_build_rejects_symlink_candidate(datasets, tmp_path, capsys):
    link = tmp_path / datasets.a.dataset_id
    _make_symlink_or_skip(datasets.a.build_path, link)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--candidate-build-dir", str(link),
            "--output-root", str(tmp_path / "snapshots"),
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert_failure(code, out, err, "dataset-catalog-build")
    assert "symlink" in err.lower() or "junction" in err.lower()


def test_build_rejects_ambiguous_duplicate_location(
    datasets, tmp_path, capsys
):
    """The same dataset_id observed at two different physical paths fails
    closed."""
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    shutil.copytree(datasets.a.build_path, relocated / datasets.a.dataset_id)
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--candidate-build-dir", datasets.a.build_path.as_posix(),
            "--candidate-build-dir", (relocated / datasets.a.dataset_id).as_posix(),
            "--output-root", str(tmp_path / "snapshots"),
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert_failure(code, out, err, "dataset-catalog-build")
    assert "duplicate" in err.lower()


def test_build_rejects_nonexistent_root(tmp_path, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root", str(tmp_path / "missing"),
            "--output-root", str(tmp_path / "snapshots"),
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert_failure(code, out, err, "dataset-catalog-build")


# ---------------------------------------------------------------------------
# E. dataset-catalog-verify.
# ---------------------------------------------------------------------------


def test_verify_summary_only(catalog_snapshot, capsys):
    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", str(catalog_snapshot.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    assert err == ""
    payload = json.loads(out)
    assert payload["result"] == "VERIFIED"
    assert payload["snapshot_id"] == catalog_snapshot.snapshot_id
    assert payload["dataset_count"] == 3
    assert payload["built_at"] == SNAPSHOT_BUILT_AT_STR
    assert payload["snapshot_path"] == catalog_snapshot.snapshot_dir.as_posix()
    assert "datasets" not in payload


def test_verify_rejects_unknown_options(capsys):
    for option in ("--root", "--latest", "--repair", "--force", "--dataset-root"):
        code, out, err = run_cli(
            ["dataset-catalog-verify", "--snapshot-dir", "C:/x", option],
            capsys,
        )
        assert code == 2
        assert out == ""


def test_verify_missing_snapshot_dir_exit_two(capsys):
    code, out, err = run_cli(["dataset-catalog-verify"], capsys)
    assert code == 2
    assert "--snapshot-dir" in err


def test_verify_wrong_dirname_fails(catalog_snapshot, tmp_path, capsys):
    wrong = copy_snapshot(catalog_snapshot.snapshot_dir, tmp_path / "not-hex")
    code, out, err = run_cli(
        ["dataset-catalog-verify", "--snapshot-dir", str(wrong)], capsys
    )
    assert_failure(code, out, err, "dataset-catalog-verify")


# ---------------------------------------------------------------------------
# F. Corruption matrix across verify / list / show (§25).
# ---------------------------------------------------------------------------


def _corrupt(snapshot: Path, kind: str) -> None:
    if kind == "missing-success":
        (snapshot / "_SUCCESS").unlink()
    elif kind == "modified-catalog":
        path = snapshot / "catalog.json"
        path.write_text(
            path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
    elif kind == "modified-manifest":
        path = snapshot / "manifest.json"
        path.write_text(
            path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
    elif kind == "extra-file":
        (snapshot / "notes.txt").write_text("extra", encoding="utf-8")
    elif kind == "wrong-dirname":
        (snapshot / "catalog.json").unlink()
    else:  # pragma: no cover
        raise AssertionError(kind)


CORRUPTION_KINDS = (
    "missing-success",
    "modified-catalog",
    "modified-manifest",
    "extra-file",
    "wrong-dirname",
)


@pytest.mark.parametrize("kind", CORRUPTION_KINDS)
@pytest.mark.parametrize(
    "command", ["dataset-catalog-verify", "dataset-catalog-list", "dataset-catalog-show"]
)
def test_corruption_fails_closed_on_all_read_commands(
    catalog_snapshot, tmp_path, capsys, kind, command
):
    broken = copy_snapshot(catalog_snapshot.snapshot_dir, tmp_path / "broken")
    _corrupt(broken, kind)
    argv = [command, "--snapshot-dir", str(broken)]
    if command == "dataset-catalog-show":
        argv += ["--dataset-id", catalog_snapshot.verified.entries[0].dataset_id]
    code, out, err = run_cli(argv, capsys)
    assert code == 1
    assert out == ""
    payload = json.loads(err)
    assert payload["result"] == "FAILED"
    assert payload["error_type"] == "DatasetCatalogCLIError"
    assert payload["command"] == command


# ---------------------------------------------------------------------------
# G. dataset-catalog-list: filters, AND semantics, pagination.
# ---------------------------------------------------------------------------


def test_list_no_filters_returns_all(catalog_snapshot, capsys):
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", str(catalog_snapshot.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["result"] == "LISTED"
    assert payload["dataset_count"] == 3
    assert payload["matched_count"] == 3
    assert payload["offset"] == 0
    assert payload["limit"] == 20
    assert payload["returned_count"] == 3
    assert payload["filters"] == {key: None for key in LIST_FILTER_KEYS}
    ids = [item["dataset_id"] for item in payload["datasets"]]
    assert ids == sorted(ids)
    assert ids == [entry.dataset_id for entry in catalog_snapshot.verified.entries]


def test_list_each_single_filter(catalog_snapshot, capsys):
    """Every filter applied alone returns exactly the entries that match
    it, and the filter's own target entry is always among the matches."""
    entries = catalog_snapshot.verified.entries
    by_id = {entry.dataset_id: entry for entry in entries}
    first = entries[0]
    facts = first.dataset_facts
    cases = (
        ["--status", facts.status],
        ["--dataset-kind", facts.dataset_kind],
        ["--symbol", facts.scope.symbols[0]],
        ["--trade-date", facts.scope.trade_dates[0].isoformat()],
        ["--interval", facts.scope.interval],
        ["--adjustment", facts.scope.adjustment],
        ["--requested-session", facts.scope.requested_session],
    )
    for args in cases:
        code, out, err = run_cli(
            [
                "dataset-catalog-list",
                "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
                *args,
            ],
            capsys,
        )
        assert code == 0, err
        payload = json.loads(out)
        assert payload["matched_count"] >= 1
        ids = [item["dataset_id"] for item in payload["datasets"]]
        assert first.dataset_id in ids
        for item in payload["datasets"]:
            matched = by_id[item["dataset_id"]].dataset_facts
            if "--status" in args:
                assert matched.status == facts.status
            if "--dataset-kind" in args:
                assert matched.dataset_kind == facts.dataset_kind
            if "--symbol" in args:
                assert facts.scope.symbols[0] in matched.scope.symbols
            if "--trade-date" in args:
                assert (
                    facts.scope.trade_dates[0] in matched.scope.trade_dates
                )
            if "--interval" in args:
                assert matched.scope.interval == facts.scope.interval
            if "--adjustment" in args:
                assert matched.scope.adjustment == facts.scope.adjustment
            if "--requested-session" in args:
                assert (
                    matched.scope.requested_session
                    == facts.scope.requested_session
                )


def test_list_multiple_and_filters(catalog_snapshot, capsys):
    """--status COMPLETE AND US.MU in scope.symbols AND 2026-07-01 in
    scope.trade_dates."""
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--status", "COMPLETE",
            "--symbol", "US.MU",
            "--trade-date", "2026-07-01",
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["matched_count"] == 1
    item = payload["datasets"][0]
    assert item["status"] == "COMPLETE"
    assert item["scope"]["symbols"] == ["US.MU"]
    assert item["scope"]["trade_dates"] == ["2026-07-01"]


def test_list_and_semantics_conflicting_filters_zero_match(
    catalog_snapshot, capsys
):
    """US.MU is COMPLETE on 2026-07-01; combining COMPLETE with the
    2026-07-02 EMPTY dataset's date must produce zero matches."""
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--status", "COMPLETE",
            "--symbol", "US.MU",
            "--trade-date", "2026-07-02",
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["result"] == "LISTED"
    assert payload["matched_count"] == 0
    assert payload["returned_count"] == 0
    assert payload["datasets"] == []


def test_list_zero_match_exit_zero(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--symbol", "US.NO_SUCH",
        ],
        capsys,
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["matched_count"] == 0
    assert payload["datasets"] == []


def test_list_empty_catalog_exit_zero(tmp_path, capsys):
    empty_root = tmp_path / "empty-root"
    empty_root.mkdir()
    build_result = build_dataset_catalog(dataset_root=empty_root)
    mresult = materialize_dataset_catalog_snapshot(
        build_result, output_root=tmp_path, built_at=SNAPSHOT_BUILT_AT
    )
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", str(mresult.snapshot_path)],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["matched_count"] == 0
    assert payload["returned_count"] == 0
    assert payload["datasets"] == []


def test_list_offset_beyond_end(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--offset", "100",
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["matched_count"] == 3
    assert payload["returned_count"] == 0
    assert payload["datasets"] == []


def test_list_offset_zero_is_default(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--offset", "0",
        ],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["returned_count"] == 3


@pytest.mark.parametrize("limit", ["0", "1", "1000"])
def test_list_limit_values(catalog_snapshot, capsys, limit):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--limit", limit,
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["limit"] == int(limit)
    assert payload["returned_count"] == min(3, int(limit))
    assert payload["datasets"] == payload["datasets"][: int(limit)]


def test_list_limit_over_one_thousand_exits_two(capsys):
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", "C:/x", "--limit", "1001"],
        capsys,
    )
    assert code == 2
    assert out == ""


@pytest.mark.parametrize("flag", ["--limit", "--offset"])
def test_list_negative_values_exit_two(capsys, flag):
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", "C:/x", flag, "-1"],
        capsys,
    )
    assert code == 2
    assert out == ""


def test_list_invalid_status_choice_exits_two(capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", "C:/x",
            "--status", "PARTIAL",
        ],
        capsys,
    )
    assert code == 2


def test_list_invalid_trade_date_exits_two(capsys):
    for bad in ("2026-7-1", "2026/07/01", "not-a-date", "2026-07-32"):
        code, out, err = run_cli(
            [
                "dataset-catalog-list",
                "--snapshot-dir", "C:/x",
                "--trade-date", bad,
            ],
            capsys,
        )
        assert code == 2, bad


def test_list_no_implicit_case_folding(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--symbol", "us.mu",
        ],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["matched_count"] == 0


def test_list_exact_matches_only_not_substring(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-kind", "supervise",
        ],
        capsys,
    )
    assert code == 0, err
    assert json.loads(out)["matched_count"] == 0


def test_list_summary_shape(catalog_snapshot, capsys):
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", str(catalog_snapshot.snapshot_dir)],
        capsys,
    )
    assert code == 0, err
    item = json.loads(out)["datasets"][0]
    assert set(item) == {
        "dataset_id",
        "content_id",
        "dataset_kind",
        "status",
        "logical_row_count",
        "dataset_as_of",
        "scope",
        "recorded_built_at",
        "recorded_build_path",
    }
    assert set(item["scope"]) == {
        "symbols",
        "trade_dates",
        "interval",
        "adjustment",
        "requested_session",
    }
    # Discovery summary only: full pins and completion belong to show.
    for forbidden in ("feature_spec_pins", "label_spec_pins", "split_spec_pin", "canonical_build_pins", "canonical_row_version_ids", "completion"):
        assert forbidden not in item


def test_list_candidate_order_does_not_change_output(
    datasets, tmp_path, capsys
):
    """list only reads the verified sorted snapshot, so candidate/file
    order never affects its output."""
    forward = build_snapshot(
        capsys,
        mode_args=[
            "--candidate-build-dir", datasets.a.build_path.as_posix(),
            "--candidate-build-dir", datasets.b.build_path.as_posix(),
            "--candidate-build-dir", datasets.c.build_path.as_posix(),
        ],
        output_root=tmp_path / "forward",
    )
    reverse = build_snapshot(
        capsys,
        mode_args=[
            "--candidate-build-dir", datasets.c.build_path.as_posix(),
            "--candidate-build-dir", datasets.b.build_path.as_posix(),
            "--candidate-build-dir", datasets.a.build_path.as_posix(),
        ],
        output_root=tmp_path / "reverse",
    )
    assert forward["snapshot_id"] == reverse["snapshot_id"]
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", forward["snapshot_path"]],
        capsys,
    )
    assert code == 0, err
    f_ids = [item["dataset_id"] for item in json.loads(out)["datasets"]]
    code, out, err = run_cli(
        ["dataset-catalog-list", "--snapshot-dir", reverse["snapshot_path"]],
        capsys,
    )
    assert code == 0, err
    r_ids = [item["dataset_id"] for item in json.loads(out)["datasets"]]
    assert f_ids == r_ids == sorted(f_ids)


def test_list_filters_json_echoes_exact_inputs(catalog_snapshot, capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-list",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--status", "EMPTY",
            "--symbol", "US.MU",
            "--trade-date", "2026-07-02",
            "--interval", "1m",
            "--adjustment", "NONE",
            "--requested-session", "ALL",
            "--dataset-kind", "SUPERVISED",
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["filters"] == {
        "status": "EMPTY",
        "dataset_kind": "SUPERVISED",
        "symbol": "US.MU",
        "trade_date": "2026-07-02",
        "interval": "1m",
        "adjustment": "NONE",
        "requested_session": "ALL",
    }
    assert payload["matched_count"] == 1
    assert payload["datasets"][0]["status"] == "EMPTY"


# ---------------------------------------------------------------------------
# H. dataset-catalog-show.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", [0, 1, 2])
def test_show_first_middle_last_dataset(
    catalog_snapshot, capsys, index
):
    entry = catalog_snapshot.verified.entries[index]
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-id", entry.dataset_id,
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["result"] == "SHOWN"
    assert payload["dataset"]["dataset_facts"]["dataset_id"] == entry.dataset_id


def test_show_full_facts_record(catalog_snapshot, capsys):
    entry = catalog_snapshot.verified.entries[0]
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-id", entry.dataset_id,
        ],
        capsys,
    )
    assert code == 0, err
    dataset = json.loads(out)["dataset"]
    assert set(dataset) == {"content_id", "dataset_facts", "observed_metadata"}
    facts = dataset["dataset_facts"]
    assert list(facts) == list(FACTS_FIELDS)
    assert facts["dataset_id"] == entry.dataset_id
    assert facts["dataset_kind"] == entry.dataset_facts.dataset_kind
    assert facts["status"] in (STATUS_COMPLETE, STATUS_EMPTY)
    assert type(facts["logical_row_count"]) is int
    assert facts["dataset_schema_id"] == entry.dataset_facts.dataset_schema_id
    assert (
        facts["logical_dataset_content_id"]
        == entry.dataset_facts.logical_dataset_content_id
    )
    assert set(facts["scope"]) == {
        "symbols", "trade_dates", "interval", "adjustment", "requested_session",
    }
    assert dataset["content_id"] == entry.content_id


def test_show_nested_pins_present(catalog_snapshot, capsys):
    """Every nested pin record of a COMPLETE entry is emitted with its full
    formal field set (a COMPLETE entry carries canonical row versions and
    source snapshots)."""
    entry = next(
        e
        for e in catalog_snapshot.verified.entries
        if e.dataset_facts.status == STATUS_COMPLETE
    )
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-id", entry.dataset_id,
        ],
        capsys,
    )
    assert code == 0, err
    facts = json.loads(out)["dataset"]["dataset_facts"]
    feature_pins = facts["feature_spec_pins"]
    assert feature_pins
    assert set(feature_pins[0]) == {"kind", "name", "version", "content_sha256"}
    label_pins = facts["label_spec_pins"]
    assert label_pins
    assert set(label_pins[0]) == {"kind", "name", "version", "content_sha256"}
    split_pin = facts["split_spec_pin"]
    assert split_pin is None or set(split_pin) == {"kind", "name", "version", "content_sha256"}
    build_pins = facts["canonical_build_pins"]
    assert build_pins
    first_pin = build_pins[0]
    assert set(first_pin) == {
        "canonical_build_id", "canonical_content_id",
        "canonical_builder_version", "canonical_schema_version",
        "materializer_version", "gap_policy_version", "gap_content_id",
        "status", "canonical_row_version_ids", "source_snapshots",
    }
    if first_pin["source_snapshots"]:
        assert set(first_pin["source_snapshots"][0]) == {
            "ingestion_run_id", "physical_snapshot_hash",
            "logical_source_rows_hash", "source_schema_version",
            "requested_trade_date", "requested_session",
        }
    assert facts["canonical_row_version_ids"]
    completion = facts["completion"]
    assert set(completion) == {
        "complete_count", "incomplete_count", "missing_count", "entries",
    }
    if completion["entries"]:
        assert set(completion["entries"][0]) == {
            "code", "trade_date", "status", "reason_code",
        }


def test_show_historical_path_exact_text(catalog_snapshot, capsys):
    """The recorded build location is emitted as exact historical text,
    never resolved or re-derived."""
    entry = catalog_snapshot.verified.entries[0]
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-id", entry.dataset_id,
        ],
        capsys,
    )
    assert code == 0, err
    observed = json.loads(out)["dataset"]["observed_metadata"]
    assert observed["built_at"] == entry.recorded_built_at.astimezone(
        timezone.utc
    ).isoformat(timespec="microseconds")
    assert observed["build_path"] == entry.recorded_build_path
    assert "\\" not in observed["build_path"]
    assert observed["build_path"].endswith(entry.dataset_id)


def test_show_missing_dataset_id_exit_one(catalog_snapshot, capsys):
    missing = "0" * 64
    assert missing not in [e.dataset_id for e in catalog_snapshot.verified.entries]
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-id", missing,
        ],
        capsys,
    )
    assert_failure(code, out, err, "dataset-catalog-show")


def test_show_invalid_dataset_id_exit_two(capsys):
    for bad in ("abc", "0" * 63, "0" * 65, "zz" + "0" * 62):
        code, out, err = run_cli(
            [
                "dataset-catalog-show",
                "--snapshot-dir", "C:/x",
                "--dataset-id", bad,
            ],
            capsys,
        )
        assert code == 2, bad
        assert out == ""


def test_show_uppercase_dataset_id_exit_two(capsys):
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", "C:/x",
            "--dataset-id", "A" * 64,
        ],
        capsys,
    )
    assert code == 2
    assert out == ""


def test_show_survives_deleted_original_dataset(
    datasets, tmp_path, capsys
):
    """PR-6 historical-location contract E2E through the CLI: after the
    original Dataset directory is deleted, show still succeeds from the
    snapshot alone."""
    relocated_root = tmp_path / "moved"
    relocated_root.mkdir()
    moved = relocated_root / datasets.a.dataset_id
    shutil.copytree(datasets.a.build_path, moved)
    payload = build_snapshot(
        capsys,
        mode_args=["--candidate-build-dir", moved.as_posix()],
        output_root=tmp_path / "snapshots",
    )
    shutil.rmtree(relocated_root)
    assert not moved.exists()
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir", payload["snapshot_path"],
            "--dataset-id", datasets.a.dataset_id,
        ],
        capsys,
    )
    assert code == 0, err
    shown = json.loads(out)
    assert shown["dataset"]["dataset_facts"]["dataset_id"] == datasets.a.dataset_id


# ---------------------------------------------------------------------------
# I. Settings-independent proof (§23).
# ---------------------------------------------------------------------------


def test_catalog_commands_never_call_load_settings(
    catalog_snapshot, datasets, tmp_path, monkeypatch, capsys
):
    def boom(*args, **kwargs):
        raise AssertionError("load_settings must never be called")

    monkeypatch.setattr(cli_module, "load_settings", boom)
    entry = catalog_snapshot.verified.entries[0]

    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--candidate-build-dir", datasets.a.build_path.as_posix(),
            "--output-root", str(tmp_path / "snapshots"),
            "--built-at", SNAPSHOT_BUILT_AT_STR,
        ],
        capsys,
    )
    assert code == 0, err
    snapshot_path = json.loads(out)["snapshot_path"]

    for argv in (
        ["dataset-catalog-verify", "--snapshot-dir", snapshot_path],
        ["dataset-catalog-list", "--snapshot-dir", str(catalog_snapshot.snapshot_dir)],
        [
            "dataset-catalog-show",
            "--snapshot-dir", str(catalog_snapshot.snapshot_dir),
            "--dataset-id", entry.dataset_id,
        ],
    ):
        code, out, err = run_cli(argv, capsys)
        assert code == 0, err


def test_catalog_commands_work_without_settings_file(
    catalog_snapshot, tmp_path
):
    """Even an explicit --settings missing-file.yaml never blocks the four
    commands (subprocess proof: no monkeypatch, no settings file, no OpenD,
    no network)."""
    entry = catalog_snapshot.verified.entries[0]
    snapshot_dir = str(catalog_snapshot.snapshot_dir)
    for argv in (
        (
            "--settings", "missing.yaml",
            "dataset-catalog-verify",
            "--snapshot-dir", snapshot_dir,
        ),
        (
            "--settings", "missing.yaml",
            "dataset-catalog-list",
            "--snapshot-dir", snapshot_dir,
        ),
        (
            "--settings", "missing.yaml",
            "dataset-catalog-show",
            "--snapshot-dir", snapshot_dir,
            "--dataset-id", entry.dataset_id,
        ),
    ):
        result = run_cli_subprocess(tmp_path, *argv)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert "Traceback" not in result.stderr
    # build also succeeds with a missing settings file (real E2E subprocess).
    build_result = run_cli_subprocess(
        tmp_path,
        "--settings", "missing.yaml",
        "dataset-catalog-build",
        "--candidate-build-dir", entry.recorded_build_path,
        "--output-root", str(tmp_path / "snapshots"),
        "--built-at", SNAPSHOT_BUILT_AT_STR,
    )
    assert build_result.returncode == 0, build_result.stderr


# ---------------------------------------------------------------------------
# J. Read-only proof (§24).
# ---------------------------------------------------------------------------


def _read_only_proof(catalog_snapshot, capsys, argv_factory):
    before = tree_snapshot(catalog_snapshot.snapshot_dir)
    for argv in argv_factory():
        code, out, err = run_cli(argv, capsys)
        assert code == 0, err
    after = tree_snapshot(catalog_snapshot.snapshot_dir)
    assert after == before


def test_verify_list_show_read_only(catalog_snapshot, capsys):
    entry = catalog_snapshot.verified.entries[0]
    snapshot_dir = str(catalog_snapshot.snapshot_dir)

    def argv_factory():
        yield ["dataset-catalog-verify", "--snapshot-dir", snapshot_dir]
        yield ["dataset-catalog-list", "--snapshot-dir", snapshot_dir]
        yield [
            "dataset-catalog-show",
            "--snapshot-dir", snapshot_dir,
            "--dataset-id", entry.dataset_id,
        ]

    _read_only_proof(catalog_snapshot, capsys, argv_factory)


def test_list_show_never_reload_datasets(
    catalog_snapshot, monkeypatch, capsys
):
    """list / show must never call load_verified_dataset (the verified
    snapshot alone is the trust boundary)."""
    import market_vault.dataset.reader as reader_module

    def boom(*args, **kwargs):
        raise AssertionError("load_verified_dataset must never be called")

    monkeypatch.setattr(reader_module, "load_verified_dataset", boom)
    entry = catalog_snapshot.verified.entries[0]
    snapshot_dir = str(catalog_snapshot.snapshot_dir)
    for argv in (
        ["dataset-catalog-list", "--snapshot-dir", snapshot_dir],
        [
            "dataset-catalog-show",
            "--snapshot-dir", snapshot_dir,
            "--dataset-id", entry.dataset_id,
        ],
    ):
        code, out, err = run_cli(argv, capsys)
        assert code == 0, err


# ---------------------------------------------------------------------------
# K. Deterministic output (§26).
# ---------------------------------------------------------------------------


def test_verify_list_show_deterministic_bytes(catalog_snapshot, capsys):
    entry = catalog_snapshot.verified.entries[0]
    snapshot_dir = str(catalog_snapshot.snapshot_dir)
    argv_sets = (
        ["dataset-catalog-verify", "--snapshot-dir", snapshot_dir],
        ["dataset-catalog-list", "--snapshot-dir", snapshot_dir],
        [
            "dataset-catalog-show",
            "--snapshot-dir", snapshot_dir,
            "--dataset-id", entry.dataset_id,
        ],
    )
    for argv in argv_sets:
        code, out_a, err_a = run_cli(argv, capsys)
        assert code == 0, err_a
        code, out_b, err_b = run_cli(argv, capsys)
        assert code == 0, err_b
        assert out_a == out_b
        assert err_a == "" and err_b == ""


def test_build_success_json_has_no_forbidden_facts(datasets, tmp_path, capsys):
    payload = build_snapshot(
        capsys,
        mode_args=["--dataset-root", str(datasets.root)],
        output_root=tmp_path / "snapshots",
    )
    text = json.dumps(payload)
    for forbidden in (
        "elapsed",
        "pid",
        "machine",
        "hostname",
        "cwd",
        "staging",
        "settings",
        "current time",
    ):
        assert forbidden.lower() not in text.lower()


# ---------------------------------------------------------------------------
# L. Contract version constants.
# ---------------------------------------------------------------------------


def test_cli_contract_version_constants_exact():
    assert DATASET_CATALOG_CLI_CONTRACT_VERSION == "market-vault-dataset-catalog-cli-v1"
    assert (
        DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION
        == "market-vault-dataset-catalog-cli-result-v1"
    )
    assert DATASET_CATALOG_COMMANDS == frozenset(
        {
            "dataset-catalog-build",
            "dataset-catalog-verify",
            "dataset-catalog-list",
            "dataset-catalog-show",
        }
    )
    assert len(DATASET_CATALOG_COMMANDS) == 4


def test_cli_error_is_dataset_catalog_error():
    from market_vault.dataset.dataset_catalog_cli_models import DatasetCatalogCLIError
    from market_vault.dataset.dataset_catalog_models import DatasetCatalogError

    assert issubclass(DatasetCatalogCLIError, DatasetCatalogError)


def test_cli_never_imports_legacy_catalog_or_duckdb():
    import market_vault.dataset.dataset_catalog_cli as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "storage.catalog" not in source
    assert "duckdb" not in source
    assert "import pandas" not in source
    assert "load_verified_dataset(" not in source
    assert "load_settings(" not in source
    assert '"catalog.json"' not in source
    assert '"manifest.json"' not in source
    assert "import datetime" not in source
    assert "import time" not in source
