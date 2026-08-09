"""Offline deterministic tests for the Dataset CLI (v0.5.0 PR-8).

Covers the three formal commands (``dataset-build --plan``,
``dataset-verify --build-dir``, ``dataset-inspect --build-dir``), the
strict versioned build-plan JSON contract (duplicate keys, unknown /
missing fields, type strictness, naive datetimes, BOM), path and symlink /
junction safety (Python 3.11 Windows reparse-point detection), the fixed
build chain through the existing public entries (verified Canonical
reader, spec parsers, typed request / scope / split construction,
authoritative schema, orchestrator, materializer, verified Dataset reader),
the three-way ``dataset_id`` binding, idempotent rebuilds, COMPLETE and
EMPTY builds, deterministic JSON success / failure output, exit codes,
settings isolation, the unified ``DatasetCLIError`` boundary with
``__cause__`` preservation, no-write verify / inspect, the CLI identity
boundary (plan key order, whitespace, relocation, ``output_root``,
``built_at``, paths never enter ``dataset_id``), and no network / OpenD /
current-time dependence. All fixtures are micro synthetic canonical builds
produced through the verified Canonical reader; no network, no OpenD, no
real market data, and no current time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import market_vault.cli as cli_module
import market_vault.dataset.cli as dcli
from market_vault.canonical import (
    CanonicalRequestKey,
    load_verified_canonical_build,
    materialize_canonical_market_bars,
)
from market_vault.dataset.cli_models import (
    DATASET_BUILD_PLAN_SCHEMA_VERSION,
    DATASET_CLI_CONTRACT_VERSION,
    DATASET_CLI_RESULT_SCHEMA_VERSION,
    BuildPlan,
    DatasetCLIError,
)
from market_vault.dataset.encoding import DatasetError
from market_vault.dataset.feature_registry import built_in_feature_registrations
from market_vault.dataset.label_registry import built_in_label_registrations
from market_vault.dataset.specs import parse_feature_spec, parse_label_spec
from market_vault.dataset.split_models import ChronologicalSplitSpec
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
NY = "America/New_York"

BUILT_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
BUILT_AT_ISO = "2026-08-05T12:00:00.000000+00:00"

_BUILD_OUTPUT_FIELDS = frozenset(
    {
        "result_schema_version",
        "cli_contract_version",
        "command",
        "result",
        "plan_schema_version",
        "created_new_build",
        "dataset_id",
        "dataset_kind",
        "dataset_status",
        "build_path",
        "built_at",
        "dataset_as_of",
        "dataset_schema_id",
        "logical_dataset_content_id",
        "logical_row_count",
        "feature_spec_count",
        "label_spec_count",
        "split_result_id",
        "reader_contract_version",
    }
)

_VERIFY_OUTPUT_FIELDS = _BUILD_OUTPUT_FIELDS - {
    "plan_schema_version",
    "created_new_build",
}

_UTC_MICROS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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


# ---------------------------------------------------------------------------
# Offline canonical-build fixtures (mirrors the reader / orchestration
# tests; every fixture goes through the verified Canonical reader).
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
    run.finished_at = datetime(
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
    root = tmp_path_factory.mktemp("mv_cli")
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
    return SimpleNamespace(root=root, cfg=cfg, a=a, f=f)


# ---------------------------------------------------------------------------
# Build-plan and bundle helpers.
# ---------------------------------------------------------------------------


def default_request() -> dict:
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


def default_scope() -> dict:
    return {
        "symbols": ["US.MU"],
        "trade_dates": ["2026-07-01"],
        "interval": "1m",
        "adjustment": "NONE",
        "requested_session": "ALL",
    }


def default_split_spec() -> dict:
    return {
        "spec_schema_version": "market-vault-chronological-split-spec-v1",
        "name": "chrono",
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


def default_plan_dict(
    *,
    canonical_dirs,
    requests=None,
    scope=None,
    split_spec=None,
    dataset_as_of=None,
    output_root="out",
    built_at=BUILT_AT_ISO,
) -> dict:
    """One build-plan payload; Python dict order is the JSON key order, so
    key-order variants are produced by reordering the literal."""
    return {
        "plan_schema_version": DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "canonical_build_dirs": list(canonical_dirs),
        "feature_spec_files": ["specs/feature_sr.yaml"],
        "label_spec_files": ["specs/label_fr.yaml"],
        "requests": requests if requests is not None else [default_request()],
        "scope": scope if scope is not None else default_scope(),
        "split_spec": split_spec if split_spec is not None else default_split_spec(),
        "dataset_as_of": dataset_as_of,
        "output_root": output_root,
        "built_at": built_at,
    }


def reordered_plan_dict(plan: dict) -> dict:
    """Same payload with the root keys in the reverse order."""
    return {key: plan[key] for key in reversed(list(plan))}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_bundle(
    tmp_path: Path,
    fixtures,
    *,
    plan_overrides: dict | None = None,
    bundle_name: str = "bundle",
) -> Path:
    """Write the feature / label spec YAML files and one build-plan JSON
    into ``tmp_path/<bundle_name>/`` and return the plan path. Inner paths
    are relative to the plan file's parent (the bundle)."""
    bundle = tmp_path / bundle_name
    specs = bundle / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "feature_sr.yaml").write_text(FEATURE_YAML, encoding="utf-8")
    (specs / "label_fr.yaml").write_text(LABEL_YAML, encoding="utf-8")
    plan = default_plan_dict(
        canonical_dirs=[
            fixtures.a.build_path.as_posix(),
            fixtures.f.build_path.as_posix(),
        ],
    )
    if plan_overrides:
        plan.update(plan_overrides)
    plan_path = bundle / "plan.json"
    write_json(plan_path, plan)
    return plan_path


def run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli_module.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def build_dataset(tmp_path, fixtures, capsys, *, plan_overrides=None) -> dict:
    plan_path = make_bundle(tmp_path, fixtures, plan_overrides=plan_overrides)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 0, err
    assert err == ""
    return json.loads(out)


def parse_plan(payload: dict) -> BuildPlan:
    return dcli.parse_build_plan_bytes(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )


def snapshot(directory: Path) -> dict:
    """Per-entry (size, mtime_ns, sha256) map proving no-write.

    Only regular files are hashed (directories cannot be opened as files on
    Windows); directory entries contribute their lstat facts so entry-set
    and mtime changes are still detected.
    """
    result = {}
    for root, dirs, files in os.walk(directory):
        for name in sorted(dirs) + sorted(files):
            path = Path(root) / name
            rel = path.relative_to(directory).as_posix()
            st = path.lstat()
            if path.is_file():
                result[rel] = (
                    st.st_size,
                    st.st_mtime_ns,
                    _file_sha256(path),
                )
            else:
                result[rel + "/"] = (st.st_size, st.st_mtime_ns, None)
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_failure(monkeypatch) -> dict:
    """Capture the DatasetCLIError handed to ``_write_failure``."""
    captured = {}
    real = dcli._write_failure

    def spy(command, exc):
        captured["command"] = command
        captured["exc"] = exc
        real(command, exc)

    monkeypatch.setattr(dcli, "_write_failure", spy)
    return captured


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


def _make_junction_or_skip(target: Path, link: Path) -> None:
    """Create a real Windows junction; skip on non-Windows or failure."""
    if os.name != "nt":
        pytest.skip("junctions exist only on Windows")
    try:
        import _winapi

        _winapi.CreateJunction(str(target.absolute()), str(link.absolute()))
    except (OSError, TypeError, ImportError) as exc:
        pytest.skip(f"cannot create a junction in this environment: {exc}")


def corrupt_parquet(build_dir: Path) -> None:
    dataset_path = build_dir / "dataset.parquet"
    with dataset_path.open("ab") as handle:
        handle.write(b"CORRUPTED-FOOTER")


# ---------------------------------------------------------------------------
# A. Parser and help.
# ---------------------------------------------------------------------------


def test_help_lists_three_dataset_commands(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "dataset-build" in out
    assert "dataset-verify" in out
    assert "dataset-inspect" in out


def test_dataset_build_help_shows_plan_only(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["dataset-build", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--plan" in out
    assert "--output-root" not in out
    assert "--force" not in out


def test_dataset_verify_help_shows_build_dir_only(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["dataset-verify", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--build-dir" in out
    assert "--offset" not in out


def test_dataset_inspect_help_shows_build_dir_offset_limit(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["dataset-inspect", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--build-dir" in out
    assert "--offset" in out
    assert "--limit" in out


def test_dataset_build_rejects_any_option_beyond_plan():
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(
            ["dataset-build", "--plan", "p.json", "--output-root", "out"]
        )
    assert excinfo.value.code == 2


def test_dataset_verify_rejects_unknown_options():
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(
            ["dataset-verify", "--build-dir", "b", "--offset", "1"]
        )
    assert excinfo.value.code == 2


def test_inspect_accepts_build_dir_offset_limit():
    args = cli_module.build_parser().parse_args(
        ["dataset-inspect", "--build-dir", "b", "--offset", "3", "--limit", "5"]
    )
    assert args.command == "dataset-inspect"
    assert args.build_dir == "b"
    assert args.offset == 3
    assert args.limit == 5


def test_inspect_defaults():
    args = cli_module.build_parser().parse_args(
        ["dataset-inspect", "--build-dir", "b"]
    )
    assert args.offset == 0
    assert args.limit == 20


def test_missing_required_arguments_exit_two():
    for argv in (
        ["dataset-build"],
        ["dataset-build", "--plan"],
        ["dataset-verify"],
        ["dataset-verify", "--build-dir"],
        ["dataset-inspect"],
        ["dataset-inspect", "--build-dir"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            cli_module.build_parser().parse_args(argv)
        assert excinfo.value.code == 2


def test_negative_offset_and_limit_exit_two():
    for argv in (
        ["dataset-inspect", "--build-dir", "b", "--offset", "-1"],
        ["dataset-inspect", "--build-dir", "b", "--limit", "-1"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            cli_module.build_parser().parse_args(argv)
        assert excinfo.value.code == 2


def test_limit_over_one_thousand_exits_two():
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(
            ["dataset-inspect", "--build-dir", "b", "--limit", "1001"]
        )
    assert excinfo.value.code == 2


def test_limit_one_thousand_accepted():
    args = cli_module.build_parser().parse_args(
        ["dataset-inspect", "--build-dir", "b", "--limit", "1000"]
    )
    assert args.limit == 1000


def test_version_is_market_vault_070(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["--version"])
    assert excinfo.value.code == 0
    assert "market-vault 0.7.0" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# B. Settings isolation.
# ---------------------------------------------------------------------------


def test_dataset_commands_never_call_load_settings(
    fixtures, tmp_path, monkeypatch, capsys
):
    def boom(path):
        raise RuntimeError("load_settings must not be called for Dataset commands")

    monkeypatch.setattr(cli_module, "load_settings", boom)
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 0
    payload = json.loads(out)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0


def test_dataset_commands_work_without_settings_file(
    fixtures, tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(
        [
            "--settings",
            "no/such/settings.yaml",
            "dataset-build",
            "--plan",
            str(plan_path),
        ],
        capsys,
    )
    assert code == 0
    payload = json.loads(out)
    code, out, err = run_cli(
        [
            "--settings",
            "no/such/settings.yaml",
            "dataset-verify",
            "--build-dir",
            payload["build_path"],
        ],
        capsys,
    )
    assert code == 0


def test_old_commands_still_call_load_settings(monkeypatch):
    def boom(path):
        raise RuntimeError("load_settings called for an old command")

    monkeypatch.setattr(cli_module, "load_settings", boom)
    with pytest.raises(RuntimeError):
        cli_module.main(["inventory"])


# ---------------------------------------------------------------------------
# C. Build-plan parse (strict contract).
# ---------------------------------------------------------------------------


def test_parse_valid_plan(fixtures):
    plan = parse_plan(default_plan_dict(canonical_dirs=["/a", "/b"]))
    assert isinstance(plan, BuildPlan)
    assert plan.plan_schema_version == DATASET_BUILD_PLAN_SCHEMA_VERSION
    assert plan.canonical_build_dirs == ("/a", "/b")
    assert plan.feature_spec_files == ("specs/feature_sr.yaml",)
    assert plan.label_spec_files == ("specs/label_fr.yaml",)
    assert len(plan.requests) == 1
    assert plan.requests[0].code == "US.MU"
    assert plan.requests[0].feature_window_close == datetime(
        2026, 7, 1, 13, 36, tzinfo=UTC
    )
    assert plan.requests[0].label_window_start == datetime(
        2026, 7, 1, 13, 36, tzinfo=UTC
    )
    assert plan.requests[0].label_window_close == datetime(
        2026, 7, 1, 13, 42, tzinfo=UTC
    )
    assert plan.scope.symbols == ("US.MU",)
    assert plan.scope.trade_dates == ("2026-07-01",)
    assert plan.split_spec.boundary_timezone == NY
    assert plan.dataset_as_of is None
    assert plan.output_root == "out"
    assert plan.built_at == BUILT_AT


def test_parse_plan_utf8_roundtrip(fixtures):
    payload = json.dumps(
        default_plan_dict(canonical_dirs=["/a"]), ensure_ascii=False
    ).encode("utf-8")
    plan = dcli.parse_build_plan_bytes(payload)
    assert plan.plan_schema_version == DATASET_BUILD_PLAN_SCHEMA_VERSION


def test_parse_plan_rejects_bom(fixtures):
    payload = json.dumps(default_plan_dict(canonical_dirs=["/a"]))
    with pytest.raises(DatasetCLIError, match="UTF-8 BOM"):
        dcli.parse_build_plan_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))


def test_parse_plan_rejects_invalid_json():
    with pytest.raises(DatasetCLIError, match="not valid JSON"):
        dcli.parse_build_plan_bytes(b"{not json")


def test_parse_plan_rejects_duplicate_key(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    duplicated = '{"plan_schema_version": "' + plan["plan_schema_version"] + '", "plan_schema_version": "' + plan["plan_schema_version"] + '"}'
    with pytest.raises(DatasetCLIError, match="duplicate JSON key"):
        dcli.parse_build_plan_bytes(duplicated.encode("utf-8"))


def test_parse_plan_rejects_non_object_root(fixtures):
    with pytest.raises(DatasetCLIError, match="JSON object"):
        dcli.parse_build_plan_bytes(b'["a", "b"]')


def test_parse_plan_rejects_unknown_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["surprise"] = 1
    with pytest.raises(DatasetCLIError, match="unknown field.*surprise"):
        parse_plan(plan)


def test_parse_plan_rejects_missing_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    del plan["built_at"]
    with pytest.raises(DatasetCLIError, match="missing required field.*built_at"):
        parse_plan(plan)


def test_parse_plan_rejects_wrong_schema_version(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["plan_schema_version"] = "market-vault-dataset-build-plan-v9"
    with pytest.raises(DatasetCLIError, match="unsupported plan_schema_version"):
        parse_plan(plan)


def test_parse_plan_rejects_string_as_array(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["canonical_build_dirs"] = "/a"
    with pytest.raises(DatasetCLIError, match="JSON array"):
        parse_plan(plan)


def test_parse_plan_rejects_bool_where_array_expected(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["requests"] = True
    with pytest.raises(DatasetCLIError, match="JSON array"):
        parse_plan(plan)


def test_parse_plan_rejects_null_in_disallowed_fields(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["feature_spec_files"] = None
    with pytest.raises(DatasetCLIError, match="JSON array"):
        parse_plan(plan)


def test_parse_plan_rejects_duplicate_canonical_path(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a", "/a"])
    with pytest.raises(DatasetCLIError, match="duplicates"):
        parse_plan(plan)


def test_parse_plan_rejects_duplicate_feature_path(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["feature_spec_files"] = ["specs/a.yaml", "specs/a.yaml"]
    with pytest.raises(DatasetCLIError, match="duplicates"):
        parse_plan(plan)


def test_parse_plan_rejects_duplicate_label_path(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["label_spec_files"] = ["specs/b.yaml", "specs/b.yaml"]
    with pytest.raises(DatasetCLIError, match="duplicates"):
        parse_plan(plan)


def test_parse_plan_rejects_empty_canonical_list(fixtures):
    plan = default_plan_dict(canonical_dirs=[])
    with pytest.raises(DatasetCLIError, match="must not be empty"):
        parse_plan(plan)


def test_parse_plan_rejects_empty_feature_list(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["feature_spec_files"] = []
    with pytest.raises(DatasetCLIError, match="must not be empty"):
        parse_plan(plan)


def test_parse_plan_rejects_empty_label_list(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["label_spec_files"] = []
    with pytest.raises(DatasetCLIError, match="must not be empty"):
        parse_plan(plan)


def test_parse_plan_allows_empty_requests(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"], requests=[])
    parsed = parse_plan(plan)
    assert parsed.requests == ()


def test_parse_plan_rejects_invalid_request_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["requests"] = [default_request() | {"code": 123}]
    with pytest.raises(DatasetCLIError, match="request code must be a string"):
        parse_plan(plan)


def test_parse_plan_rejects_request_extra_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["requests"] = [default_request() | {"extra": 1}]
    with pytest.raises(DatasetCLIError, match="unknown field.*extra"):
        parse_plan(plan)


def test_parse_plan_rejects_request_missing_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    request = default_request()
    del request["feature_window_close"]
    plan["requests"] = [request]
    with pytest.raises(DatasetCLIError, match="missing required field.*feature_window_close"):
        parse_plan(plan)


def test_parse_plan_rejects_half_label_window(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["requests"] = [default_request() | {"label_window_close": None}]
    with pytest.raises(DatasetCLIError, match="label_window_start and label_window_close"):
        parse_plan(plan)


def test_parse_plan_rejects_naive_request_datetime(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["requests"] = [
        default_request()
        | {"feature_window_start": "2026-07-01T13:30:00"}
    ]
    with pytest.raises(DatasetCLIError, match="timezone-aware"):
        parse_plan(plan)


def test_parse_plan_rejects_invalid_request_window_order_format(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["requests"] = [
        default_request() | {"feature_window_close": "not-a-datetime"}
    ]
    with pytest.raises(DatasetCLIError, match="ISO 8601"):
        parse_plan(plan)


def test_parse_plan_rejects_invalid_scope(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["scope"] = default_scope() | {"symbols": []}
    with pytest.raises(DatasetCLIError, match="must not be empty"):
        parse_plan(plan)


def test_parse_plan_rejects_invalid_scope_trade_date_format(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["scope"] = default_scope() | {"trade_dates": ["2026-7-1"]}
    with pytest.raises(DatasetCLIError, match="strict ISO"):
        parse_plan(plan)


def test_parse_plan_rejects_split_extra_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["split_spec"] = default_split_spec() | {"extra": 1}
    with pytest.raises(DatasetCLIError, match="unknown field.*extra"):
        parse_plan(plan)


def test_parse_plan_rejects_split_missing_field(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    split_spec = default_split_spec()
    del split_spec["boundary_timezone"]
    plan["split_spec"] = split_spec
    with pytest.raises(DatasetCLIError, match="missing required field.*boundary_timezone"):
        parse_plan(plan)


def test_parse_plan_rejects_invalid_split_date(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"])
    plan["split_spec"] = default_split_spec() | {"train_end_date": "2026-13-45"}
    with pytest.raises(DatasetCLIError):
        parse_plan(plan)


def test_parse_plan_rejects_naive_dataset_as_of(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"], dataset_as_of="2026-08-01T00:00:00")
    with pytest.raises(DatasetCLIError, match="timezone-aware"):
        parse_plan(plan)


def test_parse_plan_accepts_timezone_aware_dataset_as_of(fixtures):
    plan = default_plan_dict(
        canonical_dirs=["/a"],
        dataset_as_of="2026-08-01T00:00:00+08:00",
    )
    parsed = parse_plan(plan)
    assert parsed.dataset_as_of == datetime(2026, 7, 31, 16, 0, tzinfo=UTC)


def test_parse_plan_rejects_null_built_at(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"], built_at=None)
    with pytest.raises(DatasetCLIError):
        parse_plan(plan)


def test_parse_plan_rejects_naive_built_at(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"], built_at="2026-08-05T12:00:00")
    with pytest.raises(DatasetCLIError, match="timezone-aware"):
        parse_plan(plan)


def test_parse_plan_rejects_output_root_type(fixtures):
    plan = default_plan_dict(canonical_dirs=["/a"], output_root=123)
    with pytest.raises(DatasetCLIError, match="output_root must be a string"):
        parse_plan(plan)


def test_parse_plan_whitespace_and_key_order_are_semantically_irrelevant(fixtures):
    base = parse_plan(default_plan_dict(canonical_dirs=["/a", "/b"]))
    reordered = parse_plan(reordered_plan_dict(default_plan_dict(canonical_dirs=["/a", "/b"])))
    assert reordered == base


# ---------------------------------------------------------------------------
# D. Path safety.
# ---------------------------------------------------------------------------


def test_build_accepts_absolute_plan_path(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 0, err
    assert json.loads(out)["result"] == "SUCCESS"


def test_build_accepts_relative_plan_path_from_cwd(
    fixtures, tmp_path, capsys, monkeypatch
):
    bundle = tmp_path / "bundle"
    plan_path = make_bundle(tmp_path, fixtures)
    assert plan_path.parent == bundle
    monkeypatch.chdir(bundle)
    code, out, err = run_cli(["dataset-build", "--plan", "plan.json"], capsys)
    assert code == 0, err
    assert json.loads(out)["result"] == "SUCCESS"


def test_build_rejects_dot_and_dotdot_plan_components(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    for argv in (
        ["dataset-build", "--plan", str(plan_path.parent) + "/./plan.json"],
        ["dataset-build", "--plan", str(plan_path.parent) + "/../bundle/plan.json"],
    ):
        code, out, err = run_cli(argv, capsys)
        assert code == 1
        assert out == ""
        failure = json.loads(err)
        assert failure["result"] == "FAILED"
        assert "'.' or '..'" in failure["error"]


def test_build_rejects_symlinked_plan(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    link = tmp_path / "plan-link.json"
    _make_symlink_or_skip(plan_path, link)
    code, out, err = run_cli(["dataset-build", "--plan", str(link)], capsys)
    assert code == 1
    assert json.loads(err)["result"] == "FAILED"
    assert "symlink or junction" in json.loads(err)["error"]


def test_build_rejects_junction_plan(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    junction = tmp_path / "plan-junction.json"
    _make_junction_or_skip(plan_path, junction)
    code, out, err = run_cli(["dataset-build", "--plan", str(junction)], capsys)
    assert code == 1
    assert json.loads(err)["result"] == "FAILED"
    assert "symlink or junction" in json.loads(err)["error"]


def test_build_rejects_symlinked_plan_parent(fixtures, tmp_path, capsys):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link-dir"
    _make_symlink_or_skip(real_dir, link_dir)
    plan_path = make_bundle(tmp_path, fixtures)
    shutil.copy(plan_path, link_dir / "plan.json")
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(link_dir / "plan.json")], capsys
    )
    assert code == 1
    assert json.loads(err)["result"] == "FAILED"
    assert "symlink or junction" in json.loads(err)["error"]


def test_relative_inner_paths_anchor_to_plan_parent(
    fixtures, tmp_path, capsys, monkeypatch
):
    """Inner paths are relative to the plan file's parent directory, never
    to the current working directory."""
    bundle = tmp_path / "bundle"
    make_bundle(tmp_path, fixtures)
    monkeypatch.chdir(tmp_path)  # cwd has no specs/ directory
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(bundle / "plan.json")], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "SUCCESS"


def test_inner_dotdot_path_rejected(fixtures, tmp_path, capsys):
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={
            "feature_spec_files": ["../bundle/specs/feature_sr.yaml"],
        },
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert "'.' or '..'" in json.loads(err)["error"]


def test_feature_spec_symlink_rejected(fixtures, tmp_path, capsys):
    # The plan must actually reference the symlink: the CLI rejects a
    # symlinked Feature file before reading it, and a plan pointing at the
    # real target would (correctly) succeed.
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"feature_spec_files": ["specs/feature-linked.yaml"]},
    )
    real_spec = plan_path.parent / "specs" / "feature_sr.yaml"
    link = plan_path.parent / "specs" / "feature-linked.yaml"
    _make_symlink_or_skip(real_spec, link)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert out == ""
    failure = json.loads(err)  # a single valid FAILED JSON object
    assert failure["result"] == "FAILED"
    assert failure["command"] == "dataset-build"
    assert failure["error_type"] == "DatasetCLIError"
    assert "symlink or junction" in failure["error"]
    assert "feature-linked.yaml" in failure["error"]


def test_label_spec_symlink_rejected(fixtures, tmp_path, capsys):
    # The plan must actually reference the symlink (see the Feature
    # symlink test above).
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"label_spec_files": ["specs/label-linked.yaml"]},
    )
    real_spec = plan_path.parent / "specs" / "label_fr.yaml"
    link = plan_path.parent / "specs" / "label-linked.yaml"
    _make_symlink_or_skip(real_spec, link)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert out == ""
    failure = json.loads(err)  # a single valid FAILED JSON object
    assert failure["result"] == "FAILED"
    assert failure["command"] == "dataset-build"
    assert failure["error_type"] == "DatasetCLIError"
    assert "symlink or junction" in failure["error"]
    assert "label-linked.yaml" in failure["error"]


def test_spec_parent_junction_rejected(fixtures, tmp_path, capsys):
    real_specs = tmp_path / "real-specs"
    real_specs.mkdir()
    (real_specs / "feature_sr.yaml").write_text(FEATURE_YAML, encoding="utf-8")
    (real_specs / "label_fr.yaml").write_text(LABEL_YAML, encoding="utf-8")
    junction = tmp_path / "bundle" / "specs"
    junction.parent.mkdir(parents=True)
    _make_junction_or_skip(real_specs, junction)
    plan = default_plan_dict(
        canonical_dirs=[fixtures.a.build_path.as_posix()],
    )
    plan_path = tmp_path / "bundle" / "plan.json"
    write_json(plan_path, plan)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert "symlink or junction" in json.loads(err)["error"]


def test_tilde_is_never_expanded(fixtures, tmp_path, capsys):
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"feature_spec_files": ["~/no-such-spec.yaml"]},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    failure = json.loads(err)
    assert "regular file" in failure["error"]
    # The literal "~" path component appears in the reported path: the
    # input was never expanded against the user's home directory.
    assert "~" in failure["error"]
    assert "no-such-spec.yaml" in failure["error"]


def test_environment_variables_are_never_expanded(fixtures, tmp_path, capsys):
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"feature_spec_files": ["$HOME/no-such-spec.yaml"]},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    failure = json.loads(err)
    assert "regular file" in failure["error"]
    # The literal "$HOME" path component is reported: no environment
    # variable substitution happened.
    assert "$HOME" in failure["error"]
    assert "no-such-spec.yaml" in failure["error"]


def test_glob_is_never_expanded(fixtures, tmp_path, capsys):
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"feature_spec_files": ["specs/*.yaml"]},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    failure = json.loads(err)
    assert "regular file" in failure["error"]
    # The literal glob pattern is reported: no filesystem glob expansion
    # happened and no directory was scanned.
    assert "*" in failure["error"]
    assert "specs" in failure["error"]


def test_directories_are_never_scanned_for_specs(fixtures, tmp_path, capsys):
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"feature_spec_files": ["specs"]},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert "regular file" in json.loads(err)["error"]


# ---------------------------------------------------------------------------
# E. dataset-build chain.
# ---------------------------------------------------------------------------


def test_build_chain_calls_each_public_entry(fixtures, tmp_path, capsys, monkeypatch):
    plan_path = make_bundle(tmp_path, fixtures)
    names = (
        "load_verified_canonical_build",
        "parse_feature_spec",
        "parse_label_spec",
        "dataset_orchestration_schema",
        "orchestrate_dataset_build",
        "materialize_dataset_artifacts",
        "load_verified_dataset",
    )
    real = {name: getattr(dcli, name) for name in names}
    calls = {name: [] for name in names}
    results = {}

    def spy(name):
        def wrapper(*args, **kwargs):
            calls[name].append((args, kwargs))
            result = real[name](*args, **kwargs)
            results[name] = result
            return result

        return wrapper

    for name in names:
        monkeypatch.setattr(dcli, name, spy(name))

    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 0, err
    assert len(calls["load_verified_canonical_build"]) == 2  # one per dir
    assert len(calls["parse_feature_spec"]) == 1
    assert len(calls["parse_label_spec"]) == 1
    assert len(calls["dataset_orchestration_schema"]) == 1
    assert len(calls["orchestrate_dataset_build"]) == 1
    assert len(calls["materialize_dataset_artifacts"]) == 1
    assert len(calls["load_verified_dataset"]) == 1

    orch_kwargs = calls["orchestrate_dataset_build"][0][1]
    assert orch_kwargs["dataset_kind"] == "SUPERVISED"
    schema_kwargs = calls["dataset_orchestration_schema"][0][1]
    assert schema_kwargs["include_dataset_as_of"] is False
    mat_kwargs = calls["materialize_dataset_artifacts"][0][1]
    assert mat_kwargs["built_at"] == BUILT_AT

    # Three-way dataset_id binding.
    orch = results["orchestrate_dataset_build"]
    mat = results["materialize_dataset_artifacts"]
    verified = results["load_verified_dataset"]
    assert orch.dataset_id == mat.dataset_id == verified.dataset_id
    assert mat.build_path == verified.build_path


def test_build_scope_is_not_silently_narrowed(fixtures, tmp_path, capsys):
    """A scope key without a request records MISSING completion; the scope
    is never narrowed to the request set."""
    plan = default_plan_dict(
        canonical_dirs=[
            fixtures.a.build_path.as_posix(),
            fixtures.f.build_path.as_posix(),
        ],
        scope=default_scope() | {"trade_dates": ["2026-07-01", "2026-07-02"]},
    )
    plan_path = tmp_path / "bundle" / "plan.json"
    plan_path.parent.mkdir(parents=True)
    (plan_path.parent / "specs").mkdir()
    (plan_path.parent / "specs" / "feature_sr.yaml").write_text(
        FEATURE_YAML, encoding="utf-8"
    )
    (plan_path.parent / "specs" / "label_fr.yaml").write_text(
        LABEL_YAML, encoding="utf-8"
    )
    write_json(plan_path, plan)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 0, err
    payload = json.loads(out)
    assert payload["dataset_status"] == "COMPLETE"


def test_build_complete_dataset(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    assert payload["dataset_status"] == "COMPLETE"
    # One request -> one PIT sample -> one feature-anchored logical row
    # (the fixed feature value is computed once at the window close anchor).
    assert payload["logical_row_count"] == 1
    assert payload["feature_spec_count"] == 1
    assert payload["label_spec_count"] == 1


def test_build_empty_dataset(fixtures, tmp_path, capsys):
    payload = build_dataset(
        tmp_path, fixtures, capsys, plan_overrides={"requests": []}
    )
    assert payload["dataset_status"] == "EMPTY"
    assert payload["logical_row_count"] == 0


def test_build_created_new_true_then_idempotent_false(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    first = json.loads(out)
    assert first["created_new_build"] is True
    before = snapshot(Path(first["build_path"]))
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert code == 0, err
    assert second["created_new_build"] is False
    assert second["dataset_id"] == first["dataset_id"]
    after = snapshot(Path(second["build_path"]))
    assert after == before  # nothing was rewritten


def test_build_writes_no_latest_pointer(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    assert build_path.parent.name == "out"
    assert not (build_path.parent / "latest").exists()
    assert sorted(entry.name for entry in build_path.parent.iterdir()) == [
        payload["dataset_id"]
    ]


def test_build_uses_no_current_time(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    assert payload["built_at"] == BUILT_AT_ISO


def test_build_makes_no_network_connection(fixtures, tmp_path, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network connection attempted by a Dataset command")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    payload = build_dataset(tmp_path, fixtures, capsys)
    assert payload["result"] == "SUCCESS"


# ---------------------------------------------------------------------------
# F. dataset-build output.
# ---------------------------------------------------------------------------


def test_build_output_contract(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    assert set(payload) == _BUILD_OUTPUT_FIELDS
    assert payload["result_schema_version"] == DATASET_CLI_RESULT_SCHEMA_VERSION
    assert payload["cli_contract_version"] == DATASET_CLI_CONTRACT_VERSION
    assert payload["command"] == "dataset-build"
    assert payload["result"] == "SUCCESS"
    assert payload["plan_schema_version"] == DATASET_BUILD_PLAN_SCHEMA_VERSION
    assert payload["dataset_kind"] == "SUPERVISED"
    assert payload["reader_contract_version"] == "market-vault-verified-dataset-reader-v1"
    assert _UTC_MICROS_RE.fullmatch(payload["built_at"])
    assert payload["dataset_as_of"] is None
    assert payload["dataset_id"] == payload["dataset_id"].lower()
    assert len(payload["dataset_id"]) == 64
    assert len(payload["dataset_schema_id"]) == 64
    assert len(payload["logical_dataset_content_id"]) == 64
    assert len(payload["split_result_id"]) == 64


def test_build_output_stdout_stderr_boundary(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 0
    assert err == ""
    assert out.endswith("\n")
    payload = json.loads(out)  # a single JSON object, nothing else
    assert payload["result"] == "SUCCESS"


def test_build_output_absolute_posix_build_path(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    assert "\\" not in payload["build_path"]
    assert Path(payload["build_path"]).is_absolute()
    assert Path(payload["build_path"]).name == payload["dataset_id"]


def test_build_repeat_output_deterministic_except_created_new(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    first = json.loads(out)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert {k: v for k, v in first.items() if k != "created_new_build"} == {
        k: v for k, v in second.items() if k != "created_new_build"
    }
    assert first["created_new_build"] is True
    assert second["created_new_build"] is False


def test_build_output_facts_come_from_verified_build(
    fixtures, tmp_path, capsys, monkeypatch
):
    plan_path = make_bundle(tmp_path, fixtures)
    real_reader = dcli.load_verified_dataset
    captured = {}

    def spy(build_dir):
        captured["verified"] = real_reader(build_dir)
        return captured["verified"]

    monkeypatch.setattr(dcli, "load_verified_dataset", spy)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    payload = json.loads(out)
    verified = captured["verified"]
    assert payload["built_at"] == verified.built_at.isoformat(
        timespec="microseconds"
    )
    assert payload["dataset_id"] == verified.dataset_id
    assert payload["logical_row_count"] == len(verified.rows)
    assert payload["build_path"] == verified.build_path.as_posix()


# ---------------------------------------------------------------------------
# G. dataset-verify.
# ---------------------------------------------------------------------------


def test_verify_valid_dataset(fixtures, tmp_path, capsys, monkeypatch):
    payload = build_dataset(tmp_path, fixtures, capsys)
    calls = []
    real_reader = dcli.load_verified_dataset

    def spy(build_dir):
        calls.append(build_dir)
        return real_reader(build_dir)

    monkeypatch.setattr(dcli, "load_verified_dataset", spy)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    assert err == ""
    assert len(calls) == 1
    verified = json.loads(out)
    assert set(verified) == _VERIFY_OUTPUT_FIELDS
    assert verified["result"] == "VERIFIED"
    assert verified["dataset_id"] == payload["dataset_id"]
    assert verified["dataset_status"] == payload["dataset_status"]
    assert "rows" not in verified


def test_verify_does_not_call_builder_layers(
    fixtures, tmp_path, capsys, monkeypatch
):
    payload = build_dataset(tmp_path, fixtures, capsys)
    for name in (
        "materialize_dataset_artifacts",
        "orchestrate_dataset_build",
        "load_verified_canonical_build",
        "parse_feature_spec",
        "parse_label_spec",
    ):
        def boom(*args, **kwargs):
            raise AssertionError(
                f"{name} must not be called by dataset-verify"
            )

        monkeypatch.setattr(dcli, name, boom)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    assert json.loads(out)["result"] == "VERIFIED"


def test_verify_corrupt_dataset_fails_without_repair(
    fixtures, tmp_path, capsys
):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    before = snapshot(build_path)
    corrupt_parquet(build_path)
    after_corrupt = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", str(build_path)], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["result"] == "FAILED"
    assert failure["error_type"] == "DatasetCLIError"
    assert failure["command"] == "dataset-verify"
    # No repair: the corrupt artifact is byte-identical after the failed
    # verification.
    assert snapshot(build_path) == after_corrupt
    assert snapshot(build_path) != before


def test_verify_no_write_on_success(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    before = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", str(build_path)], capsys
    )
    assert code == 0
    assert snapshot(build_path) == before


# ---------------------------------------------------------------------------
# H. dataset-inspect.
# ---------------------------------------------------------------------------


def test_inspect_calls_reader_once(fixtures, tmp_path, capsys, monkeypatch):
    payload = build_dataset(tmp_path, fixtures, capsys)
    calls = []
    real_reader = dcli.load_verified_dataset

    def spy(build_dir):
        calls.append(build_dir)
        return real_reader(build_dir)

    monkeypatch.setattr(dcli, "load_verified_dataset", spy)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    assert len(calls) == 1


def test_inspect_summary_and_structure(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    assert err == ""
    inspected = json.loads(out)
    assert inspected["result"] == "INSPECTED"
    for field in _VERIFY_OUTPUT_FIELDS:
        assert field in inspected
    assert set(inspected["scope"]) == {
        "symbols",
        "trade_dates",
        "interval",
        "adjustment",
        "requested_session",
    }
    assert inspected["scope"]["symbols"] == ["US.MU"]
    assert inspected["scope"]["trade_dates"] == ["2026-07-01"]
    assert inspected["scope"]["interval"] == "1m"
    assert inspected["scope"]["adjustment"] == "NONE"
    assert inspected["scope"]["requested_session"] == "ALL"
    for field in inspected["schema_fields"]:
        assert set(field) == {"name", "logical_type", "nullable"}
    assert inspected["feature_specs"] == [
        {
            "kind": "FEATURE",
            "name": "sr",
            "version": "v1",
            "content_sha256": inspected["feature_specs"][0]["content_sha256"],
        }
    ]
    assert inspected["feature_specs"][0]["content_sha256"].startswith(
        inspected["feature_specs"][0]["content_sha256"][0]
    )
    assert inspected["label_specs"] == [
        {
            "kind": "LABEL",
            "name": "fr",
            "version": "v1",
            "content_sha256": inspected["label_specs"][0]["content_sha256"],
        }
    ]
    split_spec = inspected["split_spec"]
    assert split_spec["boundary_timezone"] == NY
    assert _DATE_RE.fullmatch(split_spec["train_end_date"])
    assert len(split_spec["content_sha256"]) == 64
    assert set(inspected["split_diagnostics"]) == {
        "sample_count",
        "assigned_count",
        "purged_count",
        "excluded_count",
    }
    report = inspected["build_report"]
    assert report["dataset_id"] == payload["dataset_id"]
    assert _UTC_MICROS_RE.fullmatch(report["built_at"])
    assert report["output_layout"]["dataset_parquet_filename"] == "dataset.parquet"


def test_inspect_default_offset_limit(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    inspected = json.loads(out)
    assert inspected["row_offset"] == 0
    assert inspected["row_limit"] == 20
    assert inspected["rows_returned"] == payload["logical_row_count"]
    assert len(inspected["rows"]) == payload["logical_row_count"]


def test_inspect_custom_offset_limit(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    code, out, err = run_cli(
        [
            "dataset-inspect",
            "--build-dir",
            payload["build_path"],
            "--offset",
            "0",
            "--limit",
            "1",
        ],
        capsys,
    )
    inspected = json.loads(out)
    assert inspected["row_offset"] == 0
    assert inspected["row_limit"] == 1
    assert inspected["rows_returned"] == 1
    full = json.loads(
        run_cli(
            ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
        )[1]
    )
    assert inspected["rows"] == full["rows"][0:1]


def test_inspect_limit_zero_returns_no_rows(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    code, out, err = run_cli(
        [
            "dataset-inspect",
            "--build-dir",
            payload["build_path"],
            "--limit",
            "0",
        ],
        capsys,
    )
    inspected = json.loads(out)
    assert inspected["row_limit"] == 0
    assert inspected["rows_returned"] == 0
    assert inspected["rows"] == []


def test_inspect_offset_beyond_end_returns_no_rows(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    code, out, err = run_cli(
        [
            "dataset-inspect",
            "--build-dir",
            payload["build_path"],
            "--offset",
            "999",
        ],
        capsys,
    )
    inspected = json.loads(out)
    assert inspected["row_offset"] == 999
    assert inspected["rows_returned"] == 0
    assert inspected["rows"] == []


def test_inspect_rows_use_schema_order_and_scalar_serialization(
    fixtures, tmp_path, capsys
):
    payload = build_dataset(tmp_path, fixtures, capsys)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    inspected = json.loads(out)
    field_names = [field["name"] for field in inspected["schema_fields"]]
    for row in inspected["rows"]:
        assert list(row) == field_names  # exact schema field order
        assert _UTC_MICROS_RE.fullmatch(row["feature_window_close"])
        assert _DATE_RE.fullmatch(row["feature_window_close_date"])
        assert row["code"] == "US.MU"
        assert isinstance(row["label_status"], str)
        assert row["reason_code"] is None  # ASSIGNED rows carry null reason
        assert row["purge_boundary"] is None
        assert _UTC_MICROS_RE.fullmatch(row["actual_label_end_time"])
        assert isinstance(row["sr"], float)
        assert isinstance(row["fr"], float)


def test_inspect_empty_dataset(fixtures, tmp_path, capsys):
    payload = build_dataset(
        tmp_path, fixtures, capsys, plan_overrides={"requests": []}
    )
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    inspected = json.loads(out)
    assert inspected["dataset_status"] == "EMPTY"
    assert inspected["rows_returned"] == 0
    assert inspected["rows"] == []


def test_inspect_no_write(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    before = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", str(build_path)], capsys
    )
    assert code == 0
    assert snapshot(build_path) == before


def test_inspect_failure_leaves_no_trace(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    corrupt_parquet(build_path)
    before = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", str(build_path)], capsys
    )
    assert code == 1
    assert out == ""
    assert snapshot(build_path) == before


def test_inspect_does_not_reparse_manifest_or_parquet(
    fixtures, tmp_path, capsys, monkeypatch
):
    """The CLI consumes only the VerifiedDatasetBuild; it never opens the
    build directory's own artifacts directly."""
    payload = build_dataset(tmp_path, fixtures, capsys)
    calls = []
    real_reader = dcli.load_verified_dataset

    def spy(build_dir):
        calls.append(build_dir)
        return real_reader(build_dir)

    monkeypatch.setattr(dcli, "load_verified_dataset", spy)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# I. Error boundary.
# ---------------------------------------------------------------------------


def _plan_with_feature_spec_text(tmp_path, fixtures, feature_text: str) -> Path:
    bundle = tmp_path / "bundle"
    specs = bundle / "specs"
    specs.mkdir(parents=True)
    (specs / "feature_sr.yaml").write_text(feature_text, encoding="utf-8")
    (specs / "label_fr.yaml").write_text(LABEL_YAML, encoding="utf-8")
    plan = default_plan_dict(
        canonical_dirs=[
            fixtures.a.build_path.as_posix(),
            fixtures.f.build_path.as_posix(),
        ],
    )
    plan_path = bundle / "plan.json"
    write_json(plan_path, plan)
    return plan_path


def test_error_boundary_spec_error_wrapped(fixtures, tmp_path, capsys, monkeypatch):
    captured = capture_failure(monkeypatch)
    plan_path = _plan_with_feature_spec_text(
        tmp_path, fixtures, "kind: FEATURE\nnot: a spec\n"
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert out == ""
    assert isinstance(captured["exc"], DatasetCLIError)
    assert isinstance(captured["exc"].__cause__, DatasetError)


def test_error_boundary_canonical_error_wrapped(
    fixtures, tmp_path, capsys, monkeypatch
):
    captured = capture_failure(monkeypatch)
    not_canonical = tmp_path / "not-canonical"
    not_canonical.mkdir()
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"canonical_build_dirs": [str(not_canonical)]},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert captured["exc"].__cause__ is not None


def test_error_boundary_orchestration_error_wrapped(
    fixtures, tmp_path, capsys, monkeypatch
):
    captured = capture_failure(monkeypatch)
    request = default_request() | {"code": "US.AAA"}  # outside the scope
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"requests": [request]},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert captured["exc"].__cause__ is not None


def test_error_boundary_materialization_error_wrapped(
    fixtures, tmp_path, capsys, monkeypatch
):
    captured = capture_failure(monkeypatch)
    blocker = tmp_path / "blocker-file"
    blocker.write_text("x", encoding="utf-8")
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"output_root": str(blocker)},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert captured["exc"].__cause__ is not None


def test_error_boundary_split_error_wrapped(fixtures, tmp_path, capsys, monkeypatch):
    captured = capture_failure(monkeypatch)
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={
            "split_spec": default_split_spec() | {"boundary_timezone": "Mars/Olympus"}
        },
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert captured["exc"].__cause__ is not None


def test_error_boundary_reader_error_wrapped(fixtures, tmp_path, capsys, monkeypatch):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    corrupt_parquet(build_path)
    captured = capture_failure(monkeypatch)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", str(build_path)], capsys
    )
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert isinstance(captured["exc"].__cause__, DatasetError)


def test_error_boundary_json_error_wrapped(fixtures, tmp_path, capsys, monkeypatch):
    captured = capture_failure(monkeypatch)
    plan_path = make_bundle(tmp_path, fixtures)
    plan_path.write_text("{broken", encoding="utf-8")
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert isinstance(captured["exc"].__cause__, ValueError)  # JSONDecodeError


def test_error_boundary_oserror_wrapped(fixtures, tmp_path, capsys, monkeypatch):
    captured = capture_failure(monkeypatch)
    real = dcli.load_verified_canonical_build

    def boom(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(dcli, "load_verified_canonical_build", boom)
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert isinstance(captured["exc"].__cause__, OSError)


def test_error_boundary_unicode_error_wrapped(fixtures, tmp_path, capsys, monkeypatch):
    captured = capture_failure(monkeypatch)
    real = dcli.parse_feature_spec

    def boom(text):
        raise UnicodeError("synthetic decode failure")

    monkeypatch.setattr(dcli, "parse_feature_spec", boom)
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert isinstance(captured["exc"].__cause__, UnicodeError)


def test_error_boundary_already_wrapped_not_double_wrapped(
    fixtures, tmp_path, capsys, monkeypatch
):
    captured = capture_failure(monkeypatch)
    plan_path = make_bundle(tmp_path, fixtures)
    text = plan_path.read_text(encoding="utf-8").replace(
        '"plan_schema_version"',
        '"plan_schema_version", "plan_schema_version"',
        1,
    )
    plan_path.write_text(text, encoding="utf-8")
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert isinstance(captured["exc"], DatasetCLIError)
    assert "dataset-build failed" not in str(captured["exc"])


def test_error_boundary_runtime_error_not_swallowed(fixtures, tmp_path, monkeypatch):
    def boom(build_dir):
        raise RuntimeError("programming error")

    monkeypatch.setattr(dcli, "load_verified_dataset", boom)
    with pytest.raises(RuntimeError):
        cli_module.main(["dataset-verify", "--build-dir", "x"])


def test_error_boundary_assertion_error_not_swallowed(fixtures, tmp_path, monkeypatch):
    def boom(build_dir):
        raise AssertionError("programming error")

    monkeypatch.setattr(dcli, "load_verified_dataset", boom)
    with pytest.raises(AssertionError):
        cli_module.main(["dataset-verify", "--build-dir", "x"])


def test_error_boundary_failure_stdout_stays_empty(fixtures, tmp_path, capsys):
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", str(tmp_path / "missing")], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["result"] == "FAILED"
    assert failure["error_type"] == "DatasetCLIError"
    assert set(failure) == {
        "result_schema_version",
        "cli_contract_version",
        "command",
        "result",
        "error_type",
        "error",
    }
    assert failure["result_schema_version"] == DATASET_CLI_RESULT_SCHEMA_VERSION
    assert failure["cli_contract_version"] == DATASET_CLI_CONTRACT_VERSION


# ---------------------------------------------------------------------------
# J. No-write and side-effect contract.
# ---------------------------------------------------------------------------


def test_verify_failure_is_read_only(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    corrupt_parquet(build_path)
    before = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", str(build_path)], capsys
    )
    assert code == 1
    assert snapshot(build_path) == before


def test_inspect_failure_is_read_only(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(payload["build_path"])
    corrupt_parquet(build_path)
    before = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", str(build_path)], capsys
    )
    assert code == 1
    assert snapshot(build_path) == before


def test_verify_and_inspect_perform_no_filesystem_mutation(
    fixtures, tmp_path, capsys, monkeypatch
):
    payload = build_dataset(tmp_path, fixtures, capsys)
    for name in ("mkdir", "rename", "replace", "remove", "unlink", "rmdir",
                 "chmod", "utime"):
        def boom(*args, **kwargs):
            raise AssertionError(f"os.{name} must not be called by read-only commands")

        monkeypatch.setattr(os, name, boom)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0


def test_verify_does_not_change_cwd(fixtures, tmp_path, capsys):
    payload = build_dataset(tmp_path, fixtures, capsys)
    cwd_before = os.getcwd()
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0
    assert os.getcwd() == cwd_before


def test_environment_does_not_affect_commands(fixtures, tmp_path, capsys, monkeypatch):
    payload = build_dataset(tmp_path, fixtures, capsys)
    monkeypatch.setenv("MARKET_VAULT_BOGUS", "bogus-value")
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", payload["build_path"]], capsys
    )
    assert code == 0


# ---------------------------------------------------------------------------
# K. CLI identity boundary.
# ---------------------------------------------------------------------------


def test_plan_key_order_does_not_change_dataset_id(
    fixtures, tmp_path, capsys
):
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    first = json.loads(out)
    reordered = reordered_plan_dict(
        json.loads(plan_path.read_text(encoding="utf-8"))
    )
    write_json(plan_path, reordered)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert second["dataset_id"] == first["dataset_id"]
    assert second["created_new_build"] is False


def test_plan_whitespace_does_not_change_dataset_id(fixtures, tmp_path, capsys):
    plan_path = make_bundle(tmp_path, fixtures)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    first = json.loads(out)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert second["dataset_id"] == first["dataset_id"]
    assert second["created_new_build"] is False


def test_bundle_relocation_does_not_change_dataset_id(
    fixtures, tmp_path, capsys
):
    first = build_dataset(tmp_path, fixtures, capsys)

    # Move the whole input bundle (plan, specs, canonical builds) into a
    # different parent directory; the typed inputs are identical.
    relocated = tmp_path / "relocated"
    canonical_root = relocated / "canonical"
    canonical_root.mkdir(parents=True)
    for build in (fixtures.a, fixtures.f):
        shutil.copytree(
            build.build_path, canonical_root / build.build_path.name
        )
    plan = default_plan_dict(
        canonical_dirs=[
            str(canonical_root / fixtures.a.build_path.name),
            str(canonical_root / fixtures.f.build_path.name),
        ],
        output_root=str(relocated / "out"),
    )
    bundle = relocated / "bundle"
    specs = bundle / "specs"
    specs.mkdir(parents=True)
    (specs / "feature_sr.yaml").write_text(FEATURE_YAML, encoding="utf-8")
    (specs / "label_fr.yaml").write_text(LABEL_YAML, encoding="utf-8")
    plan_path = bundle / "plan.json"
    write_json(plan_path, plan)
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert second["result"] == "SUCCESS"
    assert second["dataset_id"] == first["dataset_id"]


def test_output_root_does_not_enter_dataset_id(fixtures, tmp_path, capsys):
    first = build_dataset(tmp_path, fixtures, capsys)
    plan_path = make_bundle(
        tmp_path, fixtures, plan_overrides={"output_root": "out-elsewhere"}
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert second["dataset_id"] == first["dataset_id"]
    assert second["created_new_build"] is True  # new location, same identity


def test_built_at_does_not_enter_dataset_id(fixtures, tmp_path, capsys):
    first = build_dataset(tmp_path, fixtures, capsys)
    build_path = Path(first["build_path"])
    before = snapshot(build_path)
    plan_path = make_bundle(
        tmp_path,
        fixtures,
        plan_overrides={"built_at": "2026-08-05T18:30:00.000000+00:00"},
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert code == 0, err
    assert second["dataset_id"] == first["dataset_id"]
    assert second["created_new_build"] is False
    # The existing artifacts are untouched; the output built_at comes from
    # the verified existing build, never from the new plan.
    assert second["built_at"] == first["built_at"]
    assert snapshot(build_path) == before


def test_semantic_feature_change_changes_dataset_id(fixtures, tmp_path, capsys):
    first = build_dataset(tmp_path, fixtures, capsys)
    plan_path = make_bundle(tmp_path, fixtures)
    spec_path = plan_path.parent / "specs" / "feature_sr.yaml"
    spec_path.write_text(
        FEATURE_YAML.replace("window_bars: 2", "window_bars: 3"),
        encoding="utf-8",
    )
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert code == 0, err
    assert second["dataset_id"] != first["dataset_id"]
    assert second["created_new_build"] is True


# ---------------------------------------------------------------------------
# I. Verified Dataset CLI examples (v0.5.1 PR-3).
#
# The examples directory is documentation material for the current formal
# CLI and schema. These tests prove every example file passes the real
# parser / registry / plan parser, that the renderer is deterministic and
# conservative, and that a bundle rendered from the templates drives the
# real dataset-build -> dataset-verify -> dataset-inspect chain to COMPLETE
# and EMPTY results.
# ---------------------------------------------------------------------------

EXAMPLES_DIR = ROOT / "examples" / "dataset_cli"

#: Every ``--flag`` token the example README may legitimately mention.
#: The CLI-only flags are real commands; ``--settings`` is the real
#: top-level option mentioned only as "ignored by Dataset commands"; the
#: negated flags and ``--split-spec`` appear only as "not supported"
#: statements, never as usable options.
_KNOWN_EXAMPLE_FLAGS = frozenset(
    {
        "--plan",
        "--build-dir",
        "--offset",
        "--limit",
        "--canonical-build-dir",
        "--output-root",
        "--built-at",
        "--dataset-as-of",
        "--destination",
        "--help",
        "--version",
        "--split-spec",
        "--latest",
        "--force",
        "--repair",
        "--discover",
        "--now",
        "--settings",
    }
)


def run_renderer(
    tmp_path: Path,
    *,
    canonical_dirs: list,
    output_root,
    built_at,
    destination,
    dataset_as_of=None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(EXAMPLES_DIR / "render_plans.py")]
    for directory in canonical_dirs:
        cmd += ["--canonical-build-dir", str(directory)]
    cmd += [
        "--output-root",
        str(output_root),
        "--built-at",
        built_at,
        "--destination",
        str(destination),
    ]
    if dataset_as_of is not None:
        cmd += ["--dataset-as-of", dataset_as_of]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        # The renderer writes UTF-8; locale codecs (e.g. gbk) cannot decode
        # localized Windows OSError texts.
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )


def render_bundle(tmp_path: Path, fixtures, *, dataset_as_of=None) -> Path:
    destination = tmp_path / "example-bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=[
            fixtures.a.build_path.as_posix(),
            fixtures.f.build_path.as_posix(),
        ],
        output_root=str(tmp_path / "out"),
        built_at=BUILT_AT_ISO,
        destination=destination,
        dataset_as_of=dataset_as_of,
    )
    assert result.returncode == 0, result.stderr
    return destination


# --- Static example files ---------------------------------------------------


def test_examples_directory_structure():
    assert (EXAMPLES_DIR / "README.md").is_file()
    assert (EXAMPLES_DIR / "render_plans.py").is_file()
    assert (EXAMPLES_DIR / "plans" / "complete.plan.template.json").is_file()
    assert (EXAMPLES_DIR / "plans" / "empty.plan.template.json").is_file()
    assert (EXAMPLES_DIR / "specs" / "feature_simple_return_v1.yaml").is_file()
    assert (EXAMPLES_DIR / "specs" / "label_forward_return_v1.yaml").is_file()
    assert (EXAMPLES_DIR / "split_specs" / "chronological_v1.json").is_file()


def test_example_feature_spec_parses_by_formal_parser():
    text = (EXAMPLES_DIR / "specs" / "feature_simple_return_v1.yaml").read_text(
        encoding="utf-8"
    )
    spec = parse_feature_spec(text)
    assert spec.name == "simple_return_2"
    assert spec.version == "v1"
    assert spec.output.logical_type == "float64"
    assert spec.output.nullable is False
    assert spec.input_canonical_fields == ("close",)
    assert (
        spec.transform_ref
        == "market_vault.dataset.feature_transforms.simple_return:simple_return"
    )
    assert {p.name: p.value for p in spec.parameters} == {"window_bars": 2}


def test_example_label_spec_parses_by_formal_parser():
    text = (EXAMPLES_DIR / "specs" / "label_forward_return_v1.yaml").read_text(
        encoding="utf-8"
    )
    spec = parse_label_spec(text)
    assert spec.name == "forward_return_2"
    assert spec.version == "v1"
    assert spec.output.logical_type == "float64"
    assert spec.output.nullable is False
    assert spec.input_canonical_fields == ("close",)
    assert (
        spec.transform_ref
        == "market_vault.dataset.label_transforms.forward_return:forward_return"
    )
    assert spec.observation_window.unit == "BARS"
    assert spec.observation_window.start_offset == 1
    assert spec.observation_window.end_offset == 1
    assert spec.horizon.unit == "BARS"
    assert spec.horizon.value == 2
    assert spec.alignment_rule == "FEATURE_CLOSE_ALIGNED"
    assert spec.missing_data_policy == "INCOMPLETE"
    assert spec.cross_trading_day.allow is False
    assert spec.cross_trading_day.boundary_rule is None


def test_example_specs_use_builtin_registered_transforms():
    feature_text = (EXAMPLES_DIR / "specs" / "feature_simple_return_v1.yaml").read_text(
        encoding="utf-8"
    )
    label_text = (EXAMPLES_DIR / "specs" / "label_forward_return_v1.yaml").read_text(
        encoding="utf-8"
    )
    feature = parse_feature_spec(feature_text)
    label = parse_label_spec(label_text)
    feature_refs = {r.transform_ref for r in built_in_feature_registrations()}
    label_refs = {r.transform_ref for r in built_in_label_registrations()}
    assert feature.transform_ref in feature_refs
    assert label.transform_ref in label_refs
    assert feature.requirements.canonical_schema_versions == (
        "market-bars-canonical-schema-v1",
    )
    assert feature.requirements.source_schema_versions == ("10.9",)
    assert label.requirements.canonical_schema_versions == (
        "market-bars-canonical-schema-v1",
    )
    assert label.requirements.source_schema_versions == ("10.9",)


def test_example_split_spec_constructs_formal_split_spec():
    payload = json.loads(
        (EXAMPLES_DIR / "split_specs" / "chronological_v1.json").read_text(
            encoding="utf-8"
        )
    )
    split = ChronologicalSplitSpec(
        spec_schema_version=payload["spec_schema_version"],
        name=payload["name"],
        version=payload["version"],
        boundary_timezone=payload["boundary_timezone"],
        train_end_date=date.fromisoformat(payload["train_end_date"]),
        validation_end_date=date.fromisoformat(payload["validation_end_date"]),
        test_end_date=date.fromisoformat(payload["test_end_date"]),
        assignment_rule=payload["assignment_rule"],
        purge_rule=payload["purge_rule"],
        incomplete_label_policy=payload["incomplete_label_policy"],
        out_of_range_policy=payload["out_of_range_policy"],
    )
    assert split.boundary_timezone == NY
    assert split.assignment_rule == "FEATURE_WINDOW_CLOSE_DATE"
    assert split.purge_rule == "ACTUAL_LABEL_END"


def test_example_plan_templates_have_exact_root_fields():
    for name in ("complete.plan.template.json", "empty.plan.template.json"):
        payload = json.loads(
            (EXAMPLES_DIR / "plans" / name).read_text(encoding="utf-8")
        )
        assert set(payload) == {
            "plan_schema_version",
            "canonical_build_dirs",
            "feature_spec_files",
            "label_spec_files",
            "requests",
            "scope",
            "split_spec",
            "dataset_as_of",
            "output_root",
            "built_at",
        }
        assert payload["plan_schema_version"] == DATASET_BUILD_PLAN_SCHEMA_VERSION
        assert payload["feature_spec_files"] == [
            "specs/feature_simple_return_v1.yaml"
        ]
        assert payload["label_spec_files"] == ["specs/label_forward_return_v1.yaml"]


def test_example_readme_documents_three_formal_commands():
    text = (EXAMPLES_DIR / "README.md").read_text(encoding="utf-8")
    assert "market-vault dataset-build --plan <PATH>" in text
    assert "market-vault dataset-verify --build-dir <PATH>" in text
    assert "market-vault dataset-inspect --build-dir <PATH>" in text


def test_example_readme_mentions_no_fake_cli_flags():
    text = (EXAMPLES_DIR / "README.md").read_text(encoding="utf-8")
    flags = set(re.findall(r"--[a-z][a-z0-9-]*", text))
    assert flags <= _KNOWN_EXAMPLE_FLAGS, sorted(flags - _KNOWN_EXAMPLE_FLAGS)


# --- Renderer ---------------------------------------------------------------


def test_renderer_renders_complete_bundle(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    assert (destination / "complete.plan.json").is_file()
    assert (destination / "empty.plan.json").is_file()
    assert (destination / "specs" / "feature_simple_return_v1.yaml").is_file()
    assert (destination / "specs" / "label_forward_return_v1.yaml").is_file()
    assert (destination / "split_specs" / "chronological_v1.json").is_file()


def test_renderer_rendered_plan_keeps_explicit_facts(tmp_path):
    canonical = [
        "D:/data/canonical/dataset=market_bars_canonical/build-one",
        "D:/data/canonical/dataset=market_bars_canonical/build-two",
    ]
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=canonical,
        output_root="D:/data/datasets",
        built_at="2026-08-05T15:00:00+00:00",
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((destination / "complete.plan.json").read_text(encoding="utf-8"))
    assert plan["canonical_build_dirs"] == canonical
    assert plan["output_root"] == "D:/data/datasets"
    assert plan["built_at"] == "2026-08-05T15:00:00.000000+00:00"
    assert plan["feature_spec_files"] == ["specs/feature_simple_return_v1.yaml"]
    assert plan["label_spec_files"] == ["specs/label_forward_return_v1.yaml"]
    assert plan["dataset_as_of"] is None
    split = json.loads(
        (EXAMPLES_DIR / "split_specs" / "chronological_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert plan["split_spec"] == split
    empty = json.loads((destination / "empty.plan.json").read_text(encoding="utf-8"))
    assert empty["requests"] == []
    assert empty["canonical_build_dirs"] == canonical
    assert empty["split_spec"] == split


def test_renderer_rendered_plan_contains_no_placeholders(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    for name in ("complete.plan.json", "empty.plan.json"):
        text = (destination / name).read_text(encoding="utf-8")
        assert "<" not in text and ">" not in text


def test_renderer_normalizes_built_at_to_utc(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at="2026-08-05T15:00:00+08:00",
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((destination / "complete.plan.json").read_text(encoding="utf-8"))
    # UTC with a fixed six-digit microsecond field.
    assert plan["built_at"] == "2026-08-05T07:00:00.000000+00:00"


def test_renderer_fixed_six_digit_microseconds(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at="2026-08-05T15:00:00.123456+08:00",
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((destination / "complete.plan.json").read_text(encoding="utf-8"))
    assert plan["built_at"] == "2026-08-05T07:00:00.123456+00:00"


def test_renderer_accepts_timezone_aware_dataset_as_of(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        dataset_as_of="2026-08-04T16:00:00-04:00",
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((destination / "complete.plan.json").read_text(encoding="utf-8"))
    assert plan["dataset_as_of"] == "2026-08-04T20:00:00.000000+00:00"


def test_renderer_rejects_naive_built_at(tmp_path):
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at="2026-08-05T15:00:00",
        destination=tmp_path / "bundle",
    )
    assert result.returncode == 1
    assert "timezone-aware" in result.stderr


def test_renderer_rejects_naive_dataset_as_of(tmp_path):
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        dataset_as_of="2026-08-04T16:00:00",
        destination=tmp_path / "bundle",
    )
    assert result.returncode == 1
    assert "timezone-aware" in result.stderr


def test_renderer_refuses_existing_non_empty_destination(tmp_path):
    destination = tmp_path / "bundle"
    destination.mkdir()
    (destination / "leftover.txt").write_text("x", encoding="utf-8")
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 1
    assert "refusing to overwrite" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert (destination / "leftover.txt").read_text(encoding="utf-8") == "x"


def test_renderer_destination_is_regular_file(tmp_path):
    destination = tmp_path / "bundle"
    destination.write_text("fixed bytes", encoding="utf-8")
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 1
    assert "destination exists and is not a directory" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert destination.read_text(encoding="utf-8") == "fixed bytes"


def test_renderer_existing_empty_directory_renders(tmp_path):
    destination = tmp_path / "bundle"
    destination.mkdir()
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    assert (destination / "complete.plan.json").is_file()
    assert (destination / "empty.plan.json").is_file()
    assert (destination / "specs" / "feature_simple_return_v1.yaml").is_file()


def test_renderer_rejects_blank_arguments(tmp_path):
    cases = [
        ["--canonical-build-dir", "", "--output-root", "D:/data/datasets",
         "--built-at", BUILT_AT_ISO, "--destination", str(tmp_path / "b1")],
        ["--canonical-build-dir", "   ", "--output-root", "D:/data/datasets",
         "--built-at", BUILT_AT_ISO, "--destination", str(tmp_path / "b2")],
        ["--canonical-build-dir", "D:/data/canonical/build", "--output-root", "",
         "--built-at", BUILT_AT_ISO, "--destination", str(tmp_path / "b3")],
        ["--canonical-build-dir", "D:/data/canonical/build", "--output-root", "   ",
         "--built-at", BUILT_AT_ISO, "--destination", str(tmp_path / "b4")],
        ["--canonical-build-dir", "D:/data/canonical/build", "--output-root",
         "D:/data/datasets", "--built-at", BUILT_AT_ISO, "--destination", ""],
        ["--canonical-build-dir", "D:/data/canonical/build", "--output-root",
         "D:/data/datasets", "--built-at", BUILT_AT_ISO, "--destination", "   "],
    ]
    for argv in cases:
        result = subprocess.run(
            [sys.executable, str(EXAMPLES_DIR / "render_plans.py"), *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )
        assert result.returncode == 1, argv
        assert "render_plans: error:" in result.stderr, argv
        assert "Traceback" not in result.stderr, argv
        assert result.stdout == "", argv


def test_renderer_filesystem_error_reports_cleanly(tmp_path):
    # A regular file as the destination's parent forces mkdir to fail with
    # a platform-independent OSError; no chmod-based permission tricks.
    parent = tmp_path / "not-a-directory"
    parent.write_text("x", encoding="utf-8")
    destination = parent / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("render_plans: error:")
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_renderer_parser_datetime_semantics_unchanged(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at="2026-08-05T15:00:00.123456+08:00",
        dataset_as_of="2026-08-04T16:00:00-04:00",
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    plan = dcli.parse_build_plan_bytes(
        (destination / "complete.plan.json").read_bytes()
    )
    # The parsed datetimes represent exactly the input instants; only the
    # JSON text is normalized to UTC with six-digit microseconds.
    assert plan.built_at == datetime(2026, 8, 5, 7, 0, 0, 123456, tzinfo=UTC)
    assert plan.dataset_as_of == datetime(2026, 8, 4, 20, 0, 0, tzinfo=UTC)
    text = (destination / "complete.plan.json").read_text(encoding="utf-8")
    assert '"built_at": "2026-08-05T07:00:00.123456+00:00"' in text
    assert '"dataset_as_of": "2026-08-04T20:00:00.000000+00:00"' in text


def test_renderer_is_deterministic(tmp_path):
    canonical = [
        "D:/data/canonical/dataset=market_bars_canonical/build-one",
        "D:/data/canonical/dataset=market_bars_canonical/build-two",
    ]
    first = tmp_path / "bundle-1"
    result = run_renderer(
        tmp_path,
        canonical_dirs=canonical,
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=first,
    )
    assert result.returncode == 0, result.stderr
    second = tmp_path / "bundle-2"
    result = run_renderer(
        tmp_path,
        canonical_dirs=canonical,
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=second,
    )
    assert result.returncode == 0, result.stderr
    first_files = sorted(p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file())
    second_files = sorted(p.relative_to(second).as_posix() for p in second.rglob("*") if p.is_file())
    assert first_files == second_files
    for rel in first_files:
        assert (first / rel).read_bytes() == (second / rel).read_bytes()


def test_renderer_uses_explicit_built_at_only(tmp_path):
    destination = tmp_path / "bundle"
    result = run_renderer(
        tmp_path,
        canonical_dirs=["D:/data/canonical/build"],
        output_root="D:/data/datasets",
        built_at=BUILT_AT_ISO,
        destination=destination,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((destination / "complete.plan.json").read_text(encoding="utf-8"))
    # The renderer normalizes to UTC with a fixed six-digit microsecond
    # field, which the formal plan parser accepts.
    assert plan["built_at"] == "2026-08-05T12:00:00.000000+00:00"


def test_renderer_rendered_plan_parses_by_formal_parser(tmp_path, fixtures):
    destination = render_bundle(tmp_path, fixtures)
    payload = (destination / "complete.plan.json").read_bytes()
    plan = dcli.parse_build_plan_bytes(payload)
    assert plan.plan_schema_version == DATASET_BUILD_PLAN_SCHEMA_VERSION
    assert len(plan.canonical_build_dirs) == 2
    assert len(plan.requests) == 1
    assert plan.built_at == BUILT_AT


def test_renderer_requires_arguments(tmp_path):
    result = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "render_plans.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    assert result.returncode == 2


# --- Example canaries through the real CLI ----------------------------------


def test_example_complete_canary(fixtures, tmp_path, capsys):
    destination = render_bundle(tmp_path, fixtures)
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(destination / "complete.plan.json")], capsys
    )
    assert code == 0, err
    built = json.loads(out)
    assert built["dataset_status"] == "COMPLETE"
    assert built["logical_row_count"] == 1
    assert built["result"] == "SUCCESS"
    assert built["created_new_build"] is True

    build_path = Path(built["build_path"])
    before = snapshot(build_path)
    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", built["build_path"]], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "VERIFIED"
    assert snapshot(build_path) == before

    code, out, err = run_cli(
        [
            "dataset-inspect",
            "--build-dir",
            built["build_path"],
            "--offset",
            "0",
            "--limit",
            "20",
        ],
        capsys,
    )
    assert code == 0, err
    inspected = json.loads(out)
    assert inspected["result"] == "INSPECTED"
    assert inspected["dataset_id"] == built["dataset_id"]
    assert snapshot(build_path) == before


def test_example_complete_canary_idempotent_rebuild(fixtures, tmp_path, capsys):
    destination = render_bundle(tmp_path, fixtures)
    plan_path = destination / "complete.plan.json"
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    first = json.loads(out)
    assert first["created_new_build"] is True
    before = snapshot(Path(first["build_path"]))
    code, out, err = run_cli(["dataset-build", "--plan", str(plan_path)], capsys)
    second = json.loads(out)
    assert code == 0, err
    assert second["created_new_build"] is False
    assert second["dataset_id"] == first["dataset_id"]
    assert snapshot(Path(second["build_path"])) == before


def test_example_empty_canary(fixtures, tmp_path, capsys):
    destination = render_bundle(tmp_path, fixtures)
    code, out, err = run_cli(
        ["dataset-build", "--plan", str(destination / "empty.plan.json")], capsys
    )
    assert code == 0, err
    built = json.loads(out)
    assert built["dataset_status"] == "EMPTY"
    assert built["logical_row_count"] == 0
    assert built["result"] == "SUCCESS"

    code, out, err = run_cli(
        ["dataset-verify", "--build-dir", built["build_path"]], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "VERIFIED"

    code, out, err = run_cli(
        ["dataset-inspect", "--build-dir", built["build_path"]], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "INSPECTED"
