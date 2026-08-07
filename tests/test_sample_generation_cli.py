"""Offline deterministic tests of the v0.6.0 Sample Generation CLI (PR-4).

Covers the exact ``sample-generate --plan`` syntax, the two CLI version
constants, the settings-independent dispatch, the fixed execution chain
(parse -> core exactly once -> shared split loader -> pure renderer ->
``parse_build_plan_bytes`` acceptance -> safe / idempotent materialization
-> deterministic result JSON), the relative-path / output-parent policy,
the exact-byte idempotent no-overwrite behavior, success / failure JSON,
the COMPLETE and EMPTY end-to-end proof (``sample-generate`` followed by a
separate real ``dataset-build``), the byte determinism matrix, the
no-side-effect guarantees (no current time, no settings / OpenD / network,
no Dataset build), and the static audit of the production sources. No
network, no OpenD, no stored market data beyond offline synthetic fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_vault import cli as cli_module
from market_vault.canonical import (
    materialize_canonical_market_bars,
    load_verified_canonical_build,
)
from market_vault.canonical.models import CanonicalRequestKey
from market_vault.dataset import (
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
    SAMPLE_GENERATOR_CORE_VERSION,
    DatasetScope,
    SampleGenerationError,
    SampleGenerationPlan,
    SampleGenerationRule,
    SplitValidationError,
    generate_sample_requests,
    load_verified_dataset,
    parse_sample_generation_plan_bytes,
)
from market_vault.dataset.cli_models import (
    DATASET_BUILD_PLAN_SCHEMA_VERSION,
    DATASET_CLI_CONTRACT_VERSION,
    DATASET_CLI_RESULT_SCHEMA_VERSION,
)
from market_vault.dataset import sample_generation_cli as sg_cli
from market_vault.dataset import sample_generation_cli_models as sg_cli_models
from market_vault.dataset import sample_generation_output as sg_output
from market_vault.dataset import sample_generation_split as sg_split
from market_vault.dataset.cli import parse_build_plan_bytes
from market_vault.dataset.sample_generation_cli_models import (
    SAMPLE_GENERATION_CLI_CONTRACT_VERSION,
    SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION,
)
from market_vault.models import QualityResult, RunManifest, Settings
from market_vault.normalization import normalize_bars, normalize_trading_calendar
from market_vault.storage import Catalog, ParquetStore

from v060_acceptance_helpers import decode_canonical_fixture

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UTC = timezone.utc
NY = "America/New_York"
DEFAULT_KEY = CanonicalRequestKey(
    interval="1m", requested_session="ALL", adjustment="NONE", source_schema_version="10.9"
)
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
CANONICAL_SCHEMA_VERSION = "market-bars-canonical-schema-v1"
SOURCE_SCHEMA_VERSION = "10.9"
BUILT_AT = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
BUILT_AT_ISO = "2026-08-05T01:00:00+00:00"
#: A split window that assigns every 2026-07-01 sample (feature close
#: 09:33-09:37 NY) to VALIDATION without purging (label end 13:38 UTC is
#: before the 2026-07-02T04:00:00Z validation boundary), mirroring the
#: existing Dataset CLI fixtures.
SPLIT_SPEC_PAYLOAD = {
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

#: The exact root field set of the CLI success JSON.
SUCCESS_FIELDS = frozenset(
    {
        "result_schema_version",
        "cli_contract_version",
        "command",
        "result",
        "generation_plan_schema_version",
        "generator_core_version",
        "generation_content_id",
        "dataset_build_plan_schema_version",
        "output_plan_path",
        "created_new_plan",
        "generated_request_count",
        "canonical_build_count",
        "feature_spec_count",
        "label_spec_count",
        "split_spec_pin",
        "dataset_as_of",
        "diagnostics",
    }
)
FAILURE_FIELDS = frozenset(
    {
        "result_schema_version",
        "cli_contract_version",
        "command",
        "result",
        "error_type",
        "error",
    }
)
_UTC_MICROS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _deterministic_wall_clock(monkeypatch):
    """The existing ``normalize_bars`` fills the legacy ``ingested_at``
    column from ``pd.Timestamp.now``; pinning it makes every offline
    Canonical build in this file byte-deterministic."""
    monkeypatch.setattr(
        pd.Timestamp,
        "now",
        classmethod(lambda *args, **kwargs: pd.Timestamp("2026-08-01T01:00:00Z")),
    )


def utc(hour: int, minute: int, day: int = 1) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Real canonical-build fixtures (mirrors the PIT / Dataset CLI tests).
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
    close: float = 100.5,
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
    run.finished_at = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    catalog.record_run(run)
    catalog.record_quality(run.run_id, [QualityResult("bars_complete", "PASS")])


def output_root(cfg: Settings) -> Path:
    return cfg.data_root / "canonical" / "dataset=market_bars_canonical"


def materialize(cfg: Settings, *, symbols, trade_dates, root=None):
    return materialize_canonical_market_bars(
        Catalog(cfg),
        symbols=symbols,
        trade_dates=trade_dates,
        request_key=DEFAULT_KEY,
        output_root=root or output_root(cfg),
        created_at=CREATED_AT,
    )


def make_build(
    tmp_path,
    *,
    code: str = "US.MU",
    trade_date: date = date(2026, 7, 1),
    start: str = "2026-07-01 09:30:00",
    count: int = 10,
    run_id: str = "run-a",
    cfg=None,
):
    """One real verified Canonical build with ``count`` 1m bars starting at
    ``start`` (NY market time)."""
    cfg = cfg or settings(tmp_path)
    calendar(cfg, trade_date=trade_date)
    write_snapshot(
        cfg, code=code, trade_date=trade_date, run_id=run_id,
        time_keys=minute_keys(start, count),
    )
    return load_verified_canonical_build(
        materialize(cfg, symbols=[code], trade_dates=[trade_date]).build_path
    )


def make_empty_build(tmp_path):
    """A legal EMPTY Canonical build: the scope key has no bars at all."""
    cfg = settings(tmp_path)
    calendar(cfg)
    return load_verified_canonical_build(
        materialize(cfg, symbols=["US.XYZ"], trade_dates=[date(2026, 7, 1)]).build_path
    )


# ---------------------------------------------------------------------------
# Real spec-file fixtures (built-in registry resolvable).
# ---------------------------------------------------------------------------


def feature_spec_yaml(
    name: str = "simple_return",
    window_bars: int = 2,
    inputs: tuple = ("close",),
    parameters: dict | None = None,
) -> str:
    parameters = parameters if parameters is not None else {"window_bars": window_bars}
    inputs_yaml = "\n".join(f"    - {field}" for field in inputs)
    parameters_yaml = (
        "\n".join(f"  {key}: {value}" for key, value in parameters.items())
        if parameters
        else "  {}"
    )
    return f"""\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: {name}
version: v1
output:
  name: {name}
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
{inputs_yaml}
transform:
  ref: market_vault.dataset.feature_transforms.{name}:{name}
parameters:
{parameters_yaml}
requirements:
  canonical_schema_versions:
    - {CANONICAL_SCHEMA_VERSION}
  source_schema_versions:
    - "{SOURCE_SCHEMA_VERSION}"
"""


def label_spec_yaml(
    name: str = "forward_return",
    horizon: int = 2,
    output_type: str = "float64",
    inputs: tuple = ("close",),
) -> str:
    inputs_yaml = "\n".join(f"    - {field}" for field in inputs)
    return f"""\
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: {name}
version: v1
output:
  name: {name}
  logical_type: {output_type}
  nullable: false
inputs:
  canonical_fields:
{inputs_yaml}
transform:
  ref: market_vault.dataset.label_transforms.{name}:{name}
parameters: {{}}
requirements:
  canonical_schema_versions:
    - {CANONICAL_SCHEMA_VERSION}
  source_schema_versions:
    - "{SOURCE_SCHEMA_VERSION}"
observation_window:
  unit: BARS
  start_offset: {horizon - 1}
  end_offset: {horizon - 1}
horizon:
  unit: BARS
  value: {horizon}
alignment_rule: FEATURE_CLOSE_ALIGNED
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: false
  boundary_rule: null
"""


def write_fixture_files(
    tmp_path,
    *,
    feature_specs=("simple_return",),
    label_specs=("forward_return",),
    horizon: int = 2,
    window_bars: int = 2,
) -> tuple:
    """Real Feature / Label YAML files and a split-spec JSON file; returns
    their absolute paths."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    feature_paths = []
    for name in feature_specs:
        path = spec_dir / f"{name}.yaml"
        path.write_text(feature_spec_yaml(name=name, window_bars=window_bars), encoding="utf-8")
        feature_paths.append(str(path))
    label_paths = []
    for name in label_specs:
        path = spec_dir / f"{name}.yaml"
        path.write_text(label_spec_yaml(name=name, horizon=horizon), encoding="utf-8")
        label_paths.append(str(path))
    split_path = spec_dir / "chronological_split.json"
    split_path.write_text(
        json.dumps(SPLIT_SPEC_PAYLOAD, ensure_ascii=False), encoding="utf-8"
    )
    return tuple(feature_paths), tuple(label_paths), str(split_path)


# ---------------------------------------------------------------------------
# Generation-plan file helpers.
# ---------------------------------------------------------------------------


def generation_plan_dict(
    *,
    build_dirs,
    feature_paths,
    label_paths,
    split_path,
    symbols=("US.MU",),
    trade_dates=("2026-07-01",),
    feature_window_bars: int = 3,
    label_window_bars: int = 2,
    stride_bars: int = 2,
    dataset_as_of=None,
    output_root="datasets",
    built_at=BUILT_AT_ISO,
    output_plan_path="generated-plan.json",
) -> dict:
    """One generation-plan payload; Python dict order is the JSON key
    order, so key-order variants are produced by reordering the literal."""
    return {
        "generation_plan_schema_version": SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        "canonical_build_dirs": list(build_dirs),
        "feature_spec_files": list(feature_paths),
        "label_spec_files": list(label_paths),
        "split_spec_file": split_path,
        "scope": {
            "symbols": list(symbols),
            "trade_dates": list(trade_dates),
            "interval": "1m",
            "adjustment": "NONE",
            "requested_session": "ALL",
        },
        "generation_rule": {
            "rule_schema_version": SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
            "feature_window_bars": feature_window_bars,
            "label_window_bars": label_window_bars,
            "stride_bars": stride_bars,
            "anchor_source": "VERIFIED_CANONICAL_BARS",
            "anchor_rule": "FEATURE_WINDOW_CLOSE",
            "cross_day_policy": "REJECT",
        },
        "dataset_as_of": dataset_as_of,
        "output_root": output_root,
        "built_at": built_at,
        "output_plan_path": output_plan_path,
    }


def write_generation_plan(
    path: Path, payload: dict, *, sort_keys: bool = False, indent=None
) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=sort_keys, indent=indent),
        encoding="utf-8",
    )
    return path


def make_plan_model(
    *,
    build_paths,
    feature_paths,
    label_paths,
    split_path,
    symbols=("US.MU",),
    trade_dates=(date(2026, 7, 1),),
    feature_window_bars: int = 3,
    label_window_bars: int = 2,
    stride_bars: int = 2,
    dataset_as_of=None,
    output_root: str = "datasets",
    built_at=BUILT_AT,
    output_plan_path: str = "generated-plan.json",
) -> SampleGenerationPlan:
    return SampleGenerationPlan(
        generation_plan_schema_version=SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        canonical_build_dirs=tuple(build_paths),
        feature_spec_files=tuple(feature_paths),
        label_spec_files=tuple(label_paths),
        split_spec_file=split_path,
        scope=DatasetScope(
            symbols=symbols,
            trade_dates=trade_dates,
            interval="1m",
            adjustment="NONE",
            requested_session="ALL",
        ),
        generation_rule=SampleGenerationRule(
            rule_schema_version=SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
            feature_window_bars=feature_window_bars,
            label_window_bars=label_window_bars,
            stride_bars=stride_bars,
            anchor_source="VERIFIED_CANONICAL_BARS",
            anchor_rule="FEATURE_WINDOW_CLOSE",
            cross_day_policy="REJECT",
        ),
        dataset_as_of=dataset_as_of,
        output_root=output_root,
        built_at=built_at,
        output_plan_path=output_plan_path,
    )


@pytest.fixture()
def std_fixture(tmp_path):
    """The standard fixture: one 10-bar build, one Feature spec
    (window_bars=2), one Label spec (horizon=2), one split spec; the plan
    uses feature_window_bars=3, label_window_bars=2, stride_bars=2 and
    absolute input paths with a nested output plan directory."""
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    plans_dir = tmp_path / "plans" / "generated"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(build.build_path),),
            feature_paths=feature_paths,
            label_paths=label_paths,
            split_path=split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(plans_dir / "plan-1.json"),
        ),
    )
    return {
        "tmp_path": tmp_path,
        "build": build,
        "feature_paths": feature_paths,
        "label_paths": label_paths,
        "split_path": split_path,
        "plan_path": plan_path,
        "output_plan_path": plans_dir / "plan-1.json",
    }


@pytest.fixture(scope="module")
def e2e_fixtures(tmp_path_factory):
    root = tmp_path_factory.mktemp("mv_sg_cli")
    build = make_build(root, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(root)
    return SimpleNamespace(
        root=root,
        build=build,
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )


# ---------------------------------------------------------------------------
# CLI runners.
# ---------------------------------------------------------------------------


def run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli_module.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_cli_subprocess(*args: str, cwd=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "market_vault", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def capture_failure(monkeypatch) -> dict:
    """Capture the SampleGenerationCLIError handed to ``_write_failure``."""
    captured = {}
    real = sg_cli._write_failure

    def spy(exc):
        captured["exc"] = exc
        real(exc)

    monkeypatch.setattr(sg_cli, "_write_failure", spy)
    return captured


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
    pytest.skip(f"cannot create a symlink or junction in this environment: {link}")


# ---------------------------------------------------------------------------
# A. Registration and contract surface.
# ---------------------------------------------------------------------------


def test_cli_version_constants_exact():
    assert (
        SAMPLE_GENERATION_CLI_CONTRACT_VERSION
        == "market-vault-sample-generation-cli-v1"
    )
    assert (
        SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION
        == "market-vault-sample-generation-cli-result-v1"
    )
    assert sg_cli_models.SAMPLE_GENERATION_CLI_CONTRACT_VERSION is (
        SAMPLE_GENERATION_CLI_CONTRACT_VERSION
    )
    assert sg_cli_models.SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION is (
        SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION
    )


def test_cli_versions_independent_of_dataset_cli_versions():
    assert SAMPLE_GENERATION_CLI_CONTRACT_VERSION != DATASET_CLI_CONTRACT_VERSION
    assert (
        SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION
        != DATASET_CLI_RESULT_SCHEMA_VERSION
    )


def test_help_lists_sample_generate(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "sample-generate" in out


def test_sample_generate_help_shows_plan_only(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["sample-generate", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--plan PATH" in out
    for forbidden in (
        "--output",
        "--output-root",
        "--built-at",
        "--dataset-as-of",
        "--canonical-build",
        "--feature-spec",
        "--label-spec",
        "--split-spec",
        "--symbol",
        "--date",
        "--force",
        "--overwrite",
        "--latest",
    ):
        assert forbidden not in out, f"business option {forbidden!r} must not exist"


def test_sample_generate_rejects_any_option_beyond_plan():
    for argv in (
        ["sample-generate", "--plan", "p.json", "--output", "out"],
        ["sample-generate", "--plan", "p.json", "--force"],
        ["sample-generate", "--plan", "p.json", "--latest"],
        ["sample-generate", "--symbol", "US.MU"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            cli_module.build_parser().parse_args(argv)
        assert excinfo.value.code == 2


def test_missing_required_plan_exits_two():
    for argv in (["sample-generate"], ["sample-generate", "--plan"]):
        with pytest.raises(SystemExit) as excinfo:
            cli_module.build_parser().parse_args(argv)
        assert excinfo.value.code == 2


def test_dataset_cli_never_registers_sample_generate():
    text = (ROOT / "src" / "market_vault" / "dataset" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "sample-generate" not in text
    assert "SAMPLE_GENERATION_COMMANDS" not in text


# ---------------------------------------------------------------------------
# B. Settings-independent dispatch and fixed chain.
# ---------------------------------------------------------------------------


def test_dispatch_happens_before_settings_loading(std_fixture, monkeypatch, capsys):
    import market_vault.config as config

    monkeypatch.setattr(
        config, "load_settings", lambda *a, **k: pytest.fail("settings must not load")
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert err == ""
    payload = json.loads(out)
    assert payload["result"] == "SUCCESS"


def test_sample_generate_core_called_exactly_once(std_fixture, monkeypatch, capsys):
    calls = []
    real = sg_cli.generate_sample_requests

    def spy(plan, *, path_base):
        calls.append(path_base)
        return real(plan, path_base=path_base)

    monkeypatch.setattr(sg_cli, "generate_sample_requests", spy)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert len(calls) == 1
    assert calls[0] == std_fixture["plan_path"].parent


def test_split_loader_is_the_single_shared_authority(std_fixture, monkeypatch, capsys):
    from market_vault.dataset import sample_generation_core as core

    # The generator core and the CLI writer bind the exact same function
    # object; there is no second split loader and no second split identity.
    assert core.load_sample_generation_split_spec is sg_split.load_sample_generation_split_spec
    assert sg_cli.load_sample_generation_split_spec is sg_split.load_sample_generation_split_spec

    # One successful run consumes the shared authority exactly once from the
    # generator core and exactly once from the CLI writer (the same split
    # document, through the same function object).
    core_calls = []
    writer_calls = []
    real = sg_split.load_sample_generation_split_spec

    def core_spy(path):
        core_calls.append(path)
        return real(path)

    def writer_spy(path):
        writer_calls.append(path)
        return real(path)

    monkeypatch.setattr(core, "load_sample_generation_split_spec", core_spy)
    monkeypatch.setattr(sg_cli, "load_sample_generation_split_spec", writer_spy)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert len(core_calls) == 1
    assert len(writer_calls) == 1
    assert Path(writer_calls[0]) == (
        std_fixture["tmp_path"] / "specs" / "chronological_split.json"
    )


def test_plan_file_path_never_enters_identity(std_fixture):
    """The generation-plan file path / cwd / path_base never enter the
    Generation content identity: the same plan relocated to another
    directory (with relative plan paths, so the copied path strings are
    identical) produces the same ID and the same build-plan bytes."""
    root_a = std_fixture["tmp_path"] / "root-a"
    root_b = std_fixture["tmp_path"] / "root-b"
    ids = []
    byte_sets = []
    for root in (root_a, root_b):
        build = make_build(root, count=10)
        feature_paths, label_paths, split_path = write_fixture_files(root)
        plan_path = write_generation_plan(
            root / "generation-plan.json",
            generation_plan_dict(
                build_dirs=(str(build.build_path.relative_to(root)),),
                feature_paths=tuple(
                    str(Path(path).relative_to(root)) for path in feature_paths
                ),
                label_paths=tuple(
                    str(Path(path).relative_to(root)) for path in label_paths
                ),
                split_path=str(Path(split_path).relative_to(root)),
                output_root="datasets",
                output_plan_path="generated-plan.json",
            ),
        )
        result = generate_sample_requests(
            parse_sample_generation_plan_bytes(plan_path.read_bytes()),
            path_base=plan_path.parent,
        )
        ids.append(result.generation_content_id)
        byte_sets.append(
            sg_output.serialize_generated_dataset_build_plan(
                parse_sample_generation_plan_bytes(plan_path.read_bytes()),
                result,
                split_spec=sg_split.load_sample_generation_split_spec(
                    root / "specs" / "chronological_split.json"
                ),
            )
        )
    assert ids[0] == ids[1]
    assert byte_sets[0] == byte_sets[1]


def test_sample_generate_works_without_settings_file(e2e_fixtures, tmp_path):
    """A subprocess run from an empty directory with no settings file
    succeeds (proves the settings-independent dispatch end to end)."""
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "plans" / "generated" / "plan.json"),
        ),
    )
    (tmp_path / "plans" / "generated").mkdir(parents=True, exist_ok=True)
    result = run_cli_subprocess("sample-generate", "--plan", str(plan_path), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["result"] == "SUCCESS"


# ---------------------------------------------------------------------------
# C. Generation-plan file path rules.
# ---------------------------------------------------------------------------


def test_plan_accepts_absolute_path(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert err == ""


def test_plan_accepts_relative_path_from_cwd(e2e_fixtures, tmp_path):
    """A relative ``--plan`` argument is located against the current working
    directory (the one place cwd is allowed) and works end to end."""
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "generated-plan.json"),
        ),
    )
    result = run_cli_subprocess(
        "sample-generate", "--plan", plan_path.name, cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["result"] == "SUCCESS"
    assert (tmp_path / "generated-plan.json").exists()


def test_plan_rejects_dot_and_dotdot_components(e2e_fixtures, tmp_path, capsys):
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "generated-plan.json"),
        ),
    )
    for raw in (f"{plan_path.parent}/./generation-plan.json",
                f"{plan_path.parent}/../generation-plan.json"):
        code, out, err = run_cli(["sample-generate", "--plan", raw], capsys)
        assert code == 1
        assert out == ""
        failure = json.loads(err)
        assert failure["result"] == "FAILED"
        assert "'.' or '..' path components" in failure["error"]


def test_plan_rejects_missing_file(e2e_fixtures, tmp_path, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(tmp_path / "missing-plan.json")], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["error_type"] == "SampleGenerationCLIError"
    assert "must be a regular file" in failure["error"]


def test_plan_rejects_directory(e2e_fixtures, tmp_path, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(tmp_path)], capsys
    )
    assert code == 1
    failure = json.loads(err)
    assert "must be a regular file" in failure["error"]


def test_plan_rejects_symlinked_plan(e2e_fixtures, tmp_path, capsys):
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "generated-plan.json"),
        ),
    )
    link = tmp_path / "plan-link.json"
    _make_symlink_or_skip(plan_path, link)
    code, out, err = run_cli(["sample-generate", "--plan", str(link)], capsys)
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert "must not be a symlink or junction" in failure["error"]


# ---------------------------------------------------------------------------
# D. Pure renderer contract.
# ---------------------------------------------------------------------------


def _serialize_via_models(std_fixture):
    plan = parse_sample_generation_plan_bytes(std_fixture["plan_path"].read_bytes())
    result = generate_sample_requests(plan, path_base=std_fixture["plan_path"].parent)
    split_spec = sg_split.load_sample_generation_split_spec(
        Path(std_fixture["split_path"])
    )
    return plan, result, split_spec, sg_output.serialize_generated_dataset_build_plan(
        plan, result, split_spec=split_spec
    )


def test_renderer_exact_root_fields(std_fixture):
    _, _, _, generated = _serialize_via_models(std_fixture)
    data = json.loads(generated)
    assert set(data) == {
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
    assert data["plan_schema_version"] == DATASET_BUILD_PLAN_SCHEMA_VERSION
    # Nothing from the Sample Generation contract may leak into the build plan.
    for forbidden in (
        "generation_content_id",
        "generator_core_version",
        "generation_rule",
        "generation_plan_schema_version",
        "output_plan_path",
        "cli_contract_version",
        "path_base",
        "cwd",
        "machine",
        "mtime",
        "diagnostics",
    ):
        assert forbidden not in json.loads(generated), forbidden


def test_renderer_byte_format(std_fixture):
    _, _, _, generated = _serialize_via_models(std_fixture)
    assert generated.startswith(b"{")
    assert generated.endswith(b"}\n")
    assert not generated.startswith(b"\xef\xbb\xbf")  # no BOM
    assert b"\n  " not in generated  # no indent
    assert b": " not in generated  # no extra spaces
    decoded = generated.decode("utf-8")
    assert "\n" not in decoded[:-1]  # exactly one trailing newline
    json.loads(decoded)  # valid JSON
    assert b'"plan_schema_version":"market-vault-dataset-build-plan-v1"' in generated


def test_renderer_requests_exact_fields_and_values(std_fixture):
    plan, result, _, generated = _serialize_via_models(std_fixture)
    data = json.loads(generated)
    assert len(data["requests"]) == len(result.requests)
    for item, request in zip(data["requests"], result.requests):
        assert set(item) == {
            "code",
            "interval",
            "adjustment",
            "requested_session",
            "anchor_market_calendar_date",
            "feature_window_start",
            "feature_window_close",
            "label_window_start",
            "label_window_close",
        }
        assert item["code"] == request.code
        assert item["interval"] == request.interval
        assert item["adjustment"] == request.adjustment
        assert item["requested_session"] == request.requested_session
        assert item["anchor_market_calendar_date"] == request.anchor_market_calendar_date.isoformat()
        assert item["feature_window_start"] == request.feature_window_start.isoformat(
            timespec="microseconds"
        )
        assert item["feature_window_close"] == request.feature_window_close.isoformat(
            timespec="microseconds"
        )
        assert item["label_window_start"] == request.label_window_start.isoformat(
            timespec="microseconds"
        )
        assert item["label_window_close"] == request.label_window_close.isoformat(
            timespec="microseconds"
        )
    # Canonical stable request order.
    closes = [item["feature_window_close"] for item in data["requests"]]
    assert closes == sorted(closes)


def test_renderer_times_are_utc_micros_with_explicit_offset(std_fixture):
    _, _, _, generated = _serialize_via_models(std_fixture)
    data = json.loads(generated)
    for item in data["requests"]:
        for field in (
            "feature_window_start",
            "feature_window_close",
            "label_window_start",
            "label_window_close",
        ):
            assert _UTC_MICROS_RE.fullmatch(item[field]), item[field]
            assert not item[field].endswith("Z")
    assert _UTC_MICROS_RE.fullmatch(data["built_at"])
    assert data["dataset_as_of"] is None


def test_renderer_scope_normalized(std_fixture):
    _, result, _, generated = _serialize_via_models(std_fixture)
    data = json.loads(generated)
    assert data["scope"] == {
        "symbols": list(result.scope.symbols),
        "trade_dates": [trade_date.isoformat() for trade_date in result.scope.trade_dates],
        "interval": result.scope.interval,
        "adjustment": result.scope.adjustment,
        "requested_session": result.scope.requested_session,
    }


def test_renderer_split_spec_full_object(std_fixture):
    _, result, split_spec, generated = _serialize_via_models(std_fixture)
    data = json.loads(generated)
    assert data["split_spec"] == {
        "spec_schema_version": split_spec.spec_schema_version,
        "name": split_spec.name,
        "version": split_spec.version,
        "boundary_timezone": split_spec.boundary_timezone,
        "train_end_date": split_spec.train_end_date.isoformat(),
        "validation_end_date": split_spec.validation_end_date.isoformat(),
        "test_end_date": split_spec.test_end_date.isoformat(),
        "assignment_rule": split_spec.assignment_rule,
        "purge_rule": split_spec.purge_rule,
        "incomplete_label_policy": split_spec.incomplete_label_policy,
        "out_of_range_policy": split_spec.out_of_range_policy,
    }
    from market_vault.dataset.split_models import chronological_split_spec_pin

    assert chronological_split_spec_pin(split_spec) == result.split_spec_pin


def test_renderer_paths_copied_verbatim(std_fixture):
    plan, _, _, generated = _serialize_via_models(std_fixture)
    data = json.loads(generated)
    assert data["canonical_build_dirs"] == list(plan.canonical_build_dirs)
    assert data["feature_spec_files"] == list(plan.feature_spec_files)
    assert data["label_spec_files"] == list(plan.label_spec_files)
    assert data["output_root"] == plan.output_root


def test_renderer_split_pin_mismatch_fails_closed(std_fixture):
    from market_vault.dataset.split_models import ChronologicalSplitSpec

    plan, result, split_spec, _ = _serialize_via_models(std_fixture)
    # A semantically different (but formally valid) split spec must never be
    # embedded silently: only the pinned one passes.
    other = ChronologicalSplitSpec(
        spec_schema_version=split_spec.spec_schema_version,
        name=split_spec.name,
        version=split_spec.version,
        boundary_timezone=split_spec.boundary_timezone,
        train_end_date=split_spec.train_end_date - timedelta(days=5),
        validation_end_date=split_spec.validation_end_date,
        test_end_date=split_spec.test_end_date,
        assignment_rule="FEATURE_WINDOW_CLOSE_DATE",
        purge_rule="ACTUAL_LABEL_END",
        incomplete_label_policy="EXCLUDE",
        out_of_range_policy="EXCLUDE",
    )
    with pytest.raises(sg_cli_models.SampleGenerationCLIError) as excinfo:
        sg_output.serialize_generated_dataset_build_plan(
            plan, result, split_spec=other
        )
    assert "split_spec_pin" in str(excinfo.value)
    # The pinned split spec still serializes.
    sg_output.serialize_generated_dataset_build_plan(
        plan, result, split_spec=split_spec
    )


def test_renderer_wrong_input_types_fail(std_fixture):
    plan, result, split_spec, _ = _serialize_via_models(std_fixture)
    with pytest.raises(sg_cli_models.SampleGenerationCLIError):
        sg_output.serialize_generated_dataset_build_plan(
            "not a plan", result, split_spec=split_spec  # type: ignore[arg-type]
        )
    with pytest.raises(sg_cli_models.SampleGenerationCLIError):
        sg_output.serialize_generated_dataset_build_plan(
            plan, "not a result", split_spec=split_spec  # type: ignore[arg-type]
        )
    with pytest.raises(sg_cli_models.SampleGenerationCLIError):
        sg_output.serialize_generated_dataset_build_plan(
            plan, result, split_spec="not a split spec"  # type: ignore[arg-type]
        )


def test_generated_plan_parses_by_existing_parser(std_fixture, capsys):
    """``parse_build_plan_bytes`` — the existing format authority — accepts
    the generated bytes, and every parsed field matches the expectation."""
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    payload = json.loads(out)
    output_plan_path = Path(payload["output_plan_path"])
    parsed = parse_build_plan_bytes(output_plan_path.read_bytes())
    plan = parse_sample_generation_plan_bytes(std_fixture["plan_path"].read_bytes())
    result = generate_sample_requests(plan, path_base=std_fixture["plan_path"].parent)
    assert parsed.plan_schema_version == DATASET_BUILD_PLAN_SCHEMA_VERSION
    assert parsed.canonical_build_dirs == plan.canonical_build_dirs
    assert parsed.feature_spec_files == plan.feature_spec_files
    assert parsed.label_spec_files == plan.label_spec_files
    assert len(parsed.requests) == len(result.requests)
    assert parsed.requests[0].code == result.requests[0].code
    assert (
        parsed.requests[0].feature_window_start
        == result.requests[0].feature_window_start
    )
    assert parsed.scope.symbols == result.scope.symbols
    assert parsed.split_spec.name == "chrono"
    assert parsed.dataset_as_of == result.dataset_as_of
    assert parsed.output_root == plan.output_root
    assert parsed.built_at == plan.built_at


# ---------------------------------------------------------------------------
# E. Relative-path / output-parent policy.
# ---------------------------------------------------------------------------


@pytest.fixture()
def relative_fixture(tmp_path):
    """A build whose artifacts all live under ``tmp_path`` so every copied
    plan path can be written relatively."""
    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    return SimpleNamespace(
        tmp_path=tmp_path,
        build=build,
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=split_path,
    )


def _relative_payload(relative_fixture, *, output_plan_path):
    """A generation plan whose copied paths are all relative to the fixture
    root (build dir under ``data/``, specs under ``specs/``, output_root
    ``datasets``).

    Every relative path is rendered in POSIX slash form (``as_posix()``) so
    the copied path strings — and therefore the generated build-plan bytes —
    are identical on every platform.
    """
    root = relative_fixture.tmp_path
    return generation_plan_dict(
        build_dirs=(relative_fixture.build.build_path.relative_to(root).as_posix(),),
        feature_paths=tuple(
            Path(path).relative_to(root).as_posix()
            for path in relative_fixture.feature_paths
        ),
        label_paths=tuple(
            Path(path).relative_to(root).as_posix()
            for path in relative_fixture.label_paths
        ),
        split_path=Path(relative_fixture.split_path).relative_to(root).as_posix(),
        output_root="datasets",
        output_plan_path=output_plan_path,
    )


def test_relative_inputs_same_parent_succeeds(relative_fixture, capsys):
    plan_path = write_generation_plan(
        relative_fixture.tmp_path / "generation-plan.json",
        _relative_payload(relative_fixture, output_plan_path="generated-plan.json"),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    assert code == 0, err
    assert (relative_fixture.tmp_path / "generated-plan.json").exists()


def test_relative_inputs_different_parent_fails_no_file_written(
    relative_fixture, capsys
):
    plan_path = write_generation_plan(
        relative_fixture.tmp_path / "generation-plan.json",
        _relative_payload(relative_fixture, output_plan_path="elsewhere/plan.json"),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert (
        "relative Dataset build-plan paths require output_plan_path to "
        "share the generation-plan parent directory"
    ) in failure["error"]
    assert not (relative_fixture.tmp_path / "elsewhere" / "plan.json").exists()


def test_absolute_inputs_different_parent_succeeds(e2e_fixtures, tmp_path, capsys):
    nested = tmp_path / "nested" / "plans"
    nested.mkdir(parents=True, exist_ok=True)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(nested / "plan.json"),
        ),
    )
    code, out, err = run_cli(["sample-generate", "--plan", str(plan_path)], capsys)
    assert code == 0, err
    assert (nested / "plan.json").exists()


def test_split_spec_file_does_not_participate_in_parent_policy(
    relative_fixture, capsys
):
    """Only the copied paths participate: ``split_spec_file`` is embedded as
    an object, so a relative split path with an absolute build root does not
    force the same-parent rule."""
    nested = relative_fixture.tmp_path / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    plan_path = write_generation_plan(
        relative_fixture.tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(relative_fixture.build.build_path),),
            feature_paths=relative_fixture.feature_paths,
            label_paths=relative_fixture.label_paths,
            split_path=str(Path(relative_fixture.split_path).relative_to(relative_fixture.tmp_path)),
            output_root=str(relative_fixture.tmp_path / "datasets"),
            output_plan_path=str(nested / "plan.json"),
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    assert code == 0, err


def test_output_plan_path_change_does_not_change_generation_id(std_fixture, capsys):
    first = write_generation_plan(
        std_fixture["tmp_path"] / "plan-a.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(
                std_fixture["tmp_path"] / "plans" / "generated" / "plan-a.json"
            ),
        ),
    )
    second = write_generation_plan(
        std_fixture["tmp_path"] / "plan-b.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(
                std_fixture["tmp_path"] / "plans" / "generated" / "plan-b.json"
            ),
        ),
    )
    code, out_a, err = run_cli(["sample-generate", "--plan", str(first)], capsys)
    assert code == 0, err
    code, out_b, err = run_cli(["sample-generate", "--plan", str(second)], capsys)
    assert code == 0, err
    payload_a = json.loads(out_a)
    payload_b = json.loads(out_b)
    assert payload_a["generation_content_id"] == payload_b["generation_content_id"]
    # ``output_plan_path`` never enters the generated build-plan content
    # (the exact JSON key can never be a path sub-string).
    bytes_a = (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-a.json"
    ).read_bytes()
    bytes_b = (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-b.json"
    ).read_bytes()
    assert bytes_a == bytes_b
    assert b'"output_plan_path":' not in bytes_a


# ---------------------------------------------------------------------------
# F. Safe / idempotent output materialization.
# ---------------------------------------------------------------------------


def test_output_missing_creates_new_plan(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["created_new_plan"] is True
    assert std_fixture["output_plan_path"].exists()


def test_output_parent_missing_fails(std_fixture, capsys):
    plan_path = write_generation_plan(
        std_fixture["tmp_path"] / "generation-plan-missing-parent.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(
                std_fixture["tmp_path"] / "does-not-exist" / "plan.json"
            ),
        ),
    )
    code, out, err = run_cli(["sample-generate", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert "parent directory does not exist" in failure["error"]
    assert not (std_fixture["tmp_path"] / "does-not-exist").exists()


def test_output_path_is_directory_fails(std_fixture, capsys):
    target_dir = std_fixture["tmp_path"] / "output-dir"
    target_dir.mkdir()
    plan_path = write_generation_plan(
        std_fixture["tmp_path"] / "generation-plan-dir-output.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(target_dir),
        ),
    )
    code, out, err = run_cli(["sample-generate", "--plan", str(plan_path)], capsys)
    assert code == 1
    failure = json.loads(err)
    assert "must be a regular file" in failure["error"]


def test_output_symlink_fails(std_fixture, capsys):
    target = std_fixture["tmp_path"] / "real-output.json"
    link = std_fixture["tmp_path"] / "output-link.json"
    _make_symlink_or_skip(target, link)
    plan_path = write_generation_plan(
        std_fixture["tmp_path"] / "generation-plan-symlink-output.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(link),
        ),
    )
    code, out, err = run_cli(["sample-generate", "--plan", str(plan_path)], capsys)
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert "must not be a symlink or junction" in failure["error"]
    assert not target.exists()


def test_existing_exact_bytes_idempotent_no_rewrite(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["created_new_plan"] is True
    path = std_fixture["output_plan_path"]
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    second = json.loads(out)
    assert second["created_new_plan"] is False
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime
    assert second["generation_content_id"] == payload["generation_content_id"]


def test_existing_different_bytes_fails_closed(std_fixture, capsys):
    path = std_fixture["output_plan_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"different": true}\n'
    path.write_bytes(original)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert "refusing to overwrite existing build plan with different content" in (
        failure["error"]
    )
    assert path.read_bytes() == original


def test_write_failure_converts_and_cleans_partial_file(std_fixture, monkeypatch, capsys):
    """A write failure becomes SampleGenerationCLIError, the partial file of
    this round is removed, and nothing else is touched."""

    class _FailingWriteFile:
        def __init__(self, real):
            self._real = real

        def write(self, data):
            raise OSError("simulated write failure")

        def close(self):
            self._real.close()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    # Every exclusive-create open of the run is intercepted; the file is
    # really created, but writing to it fails. ``Path.open`` is patched on
    # the class (the same pattern the existing tests use for
    # ``write_bytes`` / ``write_text``) so the behavior is identical on
    # every supported Python version.
    real_open = Path.open

    def _failing_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        if mode == "xb":
            return _FailingWriteFile(handle)
        return handle

    monkeypatch.setattr(Path, "open", _failing_open)
    captured = capture_failure(monkeypatch)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["result"] == "FAILED"
    assert "cannot write output plan" in failure["error"]
    assert isinstance(captured["exc"].__cause__, OSError)
    # The partial file of this round was cleaned up.
    assert not std_fixture["output_plan_path"].exists()


def test_sample_generate_writes_only_the_output_plan(std_fixture, capsys):
    def listing() -> set[str]:
        return {
            path.relative_to(std_fixture["tmp_path"]).as_posix()
            for path in std_fixture["tmp_path"].rglob("*")
        }

    before = listing()
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    after = listing()
    added = after - before
    assert added == {
        std_fixture["output_plan_path"].relative_to(std_fixture["tmp_path"]).as_posix()
    }


# ---------------------------------------------------------------------------
# G. Success / failure JSON contract.
# ---------------------------------------------------------------------------


def test_success_json_exact_fields_and_values(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert set(payload) == SUCCESS_FIELDS
    assert payload["result_schema_version"] == SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION
    assert payload["cli_contract_version"] == SAMPLE_GENERATION_CLI_CONTRACT_VERSION
    assert payload["command"] == "sample-generate"
    assert payload["result"] == "SUCCESS"
    assert payload["generation_plan_schema_version"] == SAMPLE_GENERATION_PLAN_SCHEMA_VERSION
    assert payload["generator_core_version"] == SAMPLE_GENERATOR_CORE_VERSION
    assert _SHA256_RE.fullmatch(payload["generation_content_id"])
    assert payload["dataset_build_plan_schema_version"] == DATASET_BUILD_PLAN_SCHEMA_VERSION
    assert Path(payload["output_plan_path"]).is_absolute()
    assert payload["output_plan_path"] == (
        std_fixture["output_plan_path"].as_posix()
    )
    assert payload["created_new_plan"] is True
    assert payload["generated_request_count"] == 3
    assert payload["canonical_build_count"] == 1
    assert payload["feature_spec_count"] == 1
    assert payload["label_spec_count"] == 1
    assert payload["split_spec_pin"]["kind"] == "SPLIT"
    assert _SHA256_RE.fullmatch(payload["split_spec_pin"]["content_sha256"])
    assert payload["dataset_as_of"] is None
    diagnostics = payload["diagnostics"]
    assert set(diagnostics) == {
        "canonical_build_count",
        "canonical_bar_count",
        "in_scope_bar_count",
        "contiguous_segment_count",
        "candidate_anchor_count",
        "generated_request_count",
        "insufficient_feature_history_count",
        "insufficient_label_future_count",
    }
    assert diagnostics["generated_request_count"] == 3
    assert diagnostics["canonical_bar_count"] == 10
    assert diagnostics["in_scope_bar_count"] == 10
    assert diagnostics["contiguous_segment_count"] == 1
    assert diagnostics["candidate_anchor_count"] == 4
    assert diagnostics["insufficient_label_future_count"] == 1
    # The CLI never claims a Dataset status.
    for forbidden in ("dataset_status", "dataset_id", "build_path", "COMPLETE"):
        assert forbidden not in out


def test_success_stdout_is_one_json_object_trailing_newline(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0
    assert err == ""
    assert out.endswith("\n")
    assert json.loads(out) == json.loads(out)  # exactly one object


def test_failure_json_exact_fields(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["tmp_path"] / "nope.json")], capsys
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert set(failure) == FAILURE_FIELDS
    assert failure["result_schema_version"] == SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION
    assert failure["cli_contract_version"] == SAMPLE_GENERATION_CLI_CONTRACT_VERSION
    assert failure["command"] == "sample-generate"
    assert failure["result"] == "FAILED"
    assert failure["error_type"] == "SampleGenerationCLIError"
    assert failure["error"]


def test_failure_leaves_no_new_output_file(std_fixture, capsys):
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["tmp_path"] / "nope.json")], capsys
    )
    assert code == 1
    assert not std_fixture["output_plan_path"].exists()


def test_already_wrapped_error_never_double_wrapped(std_fixture, monkeypatch, capsys):
    def boom(plan, *, path_base):
        raise sg_cli_models.SampleGenerationCLIError("boom")

    monkeypatch.setattr(sg_cli, "generate_sample_requests", boom)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 1
    failure = json.loads(err)
    assert failure["error"] == "boom"


def test_documented_errors_converted_with_cause(std_fixture, monkeypatch, capsys):
    from market_vault.dataset import SampleGenerationError

    captured = capture_failure(monkeypatch)

    def boom(plan, *, path_base):
        raise SampleGenerationError("boom")

    monkeypatch.setattr(sg_cli, "generate_sample_requests", boom)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 1
    failure = json.loads(err)
    assert failure["error"] == "sample-generate failed: boom"
    assert isinstance(captured["exc"].__cause__, SampleGenerationError)


def test_programming_errors_are_never_swallowed(std_fixture, monkeypatch):
    for error in (AssertionError("boom"), RuntimeError("boom"), TypeError("boom")):
        def boom(plan, *, path_base, error=error):
            raise error

        monkeypatch.setattr(sg_cli, "generate_sample_requests", boom)
        with pytest.raises(type(error)):
            cli_module.main(
                ["sample-generate", "--plan", str(std_fixture["plan_path"])]
            )


# ---------------------------------------------------------------------------
# H. COMPLETE end-to-end (two independent CLI steps).
# ---------------------------------------------------------------------------


def test_complete_e2e(e2e_fixtures, tmp_path):
    """Step 1: ``sample-generate`` writes an ordinary build plan; step 2: a
    separate ``dataset-build`` invocation consumes it and produces a
    COMPLETE verified Dataset."""
    plans_dir = tmp_path / "plans" / "generated"
    plans_dir.mkdir(parents=True, exist_ok=True)
    generation_plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(plans_dir / "plan-1.json"),
        ),
    )
    output_plan_path = plans_dir / "plan-1.json"

    # Step 1: sample-generate (its own process; it must not build anything).
    first = run_cli_subprocess(
        "sample-generate", "--plan", str(generation_plan_path), cwd=tmp_path
    )
    assert first.returncode == 0, first.stderr
    assert first.stderr == ""
    payload = json.loads(first.stdout)
    assert payload["result"] == "SUCCESS"
    assert payload["generated_request_count"] > 0
    assert output_plan_path.exists()

    # The generated plan is an ordinary build plan accepted by the existing
    # parser, and the Generation ID equals the core's direct call.
    generated_bytes = output_plan_path.read_bytes()
    parsed = parse_build_plan_bytes(generated_bytes)
    assert parsed.plan_schema_version == DATASET_BUILD_PLAN_SCHEMA_VERSION
    assert parsed.requests
    plan = parse_sample_generation_plan_bytes(generation_plan_path.read_bytes())
    expected = generate_sample_requests(plan, path_base=generation_plan_path.parent)
    assert payload["generation_content_id"] == expected.generation_content_id
    assert payload["generated_request_count"] == len(expected.requests)

    # Step 2: the existing dataset-build consumes the generated plan.
    second = run_cli_subprocess(
        "dataset-build", "--plan", str(output_plan_path), cwd=tmp_path
    )
    assert second.returncode == 0, second.stderr
    build_payload = json.loads(second.stdout)
    assert build_payload["dataset_status"] == "COMPLETE"
    assert build_payload["logical_row_count"] > 0
    verified = load_verified_dataset(build_payload["build_path"])
    assert verified.status == "COMPLETE"
    assert len(verified.rows) > 0


# ---------------------------------------------------------------------------
# I. EMPTY end-to-end (legal EMPTY Canonical; EMPTY is not a failure).
# ---------------------------------------------------------------------------


def test_empty_e2e(tmp_path):
    """A legal EMPTY Canonical build produces a plan with zero requests, and
    the subsequent ``dataset-build`` produces a verified EMPTY Dataset —
    EMPTY is a success, never a failure, and no bar is ever fabricated."""
    build = make_empty_build(tmp_path)
    feature_paths, label_paths, split_path = write_fixture_files(tmp_path)
    generation_plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(build.build_path),),
            feature_paths=feature_paths,
            label_paths=label_paths,
            split_path=split_path,
            symbols=("US.XYZ",),
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "plans" / "generated" / "plan-empty.json"),
        ),
    )
    (tmp_path / "plans" / "generated").mkdir(parents=True, exist_ok=True)
    output_plan_path = tmp_path / "plans" / "generated" / "plan-empty.json"

    first = run_cli_subprocess(
        "sample-generate", "--plan", str(generation_plan_path), cwd=tmp_path
    )
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    assert payload["result"] == "SUCCESS"
    assert payload["generated_request_count"] == 0
    parsed = parse_build_plan_bytes(output_plan_path.read_bytes())
    assert parsed.requests == ()

    second = run_cli_subprocess(
        "dataset-build", "--plan", str(output_plan_path), cwd=tmp_path
    )
    assert second.returncode == 0, second.stderr
    build_payload = json.loads(second.stdout)
    assert build_payload["dataset_status"] == "EMPTY"
    assert build_payload["logical_row_count"] == 0
    verified = load_verified_dataset(build_payload["build_path"])
    assert verified.status == "EMPTY"
    assert len(verified.rows) == 0


# ---------------------------------------------------------------------------
# J. Determinism matrix.
# ---------------------------------------------------------------------------


def test_two_output_paths_identical_bytes_and_results(std_fixture, capsys):
    """The same generation plan run to two different output paths produces
    byte-identical build plans, one Generation ID, one request order, and
    one diagnostics block."""
    plans_dir = std_fixture["tmp_path"] / "plans" / "generated"
    plan_a = write_generation_plan(
        std_fixture["tmp_path"] / "plan-a.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(plans_dir / "plan-a.json"),
        ),
    )
    plan_b = write_generation_plan(
        std_fixture["tmp_path"] / "plan-b.json",
        generation_plan_dict(
            build_dirs=(str(std_fixture["build"].build_path),),
            feature_paths=std_fixture["feature_paths"],
            label_paths=std_fixture["label_paths"],
            split_path=std_fixture["split_path"],
            output_root=str(std_fixture["tmp_path"] / "datasets"),
            output_plan_path=str(plans_dir / "plan-b.json"),
        ),
    )
    code, out_a, err = run_cli(["sample-generate", "--plan", str(plan_a)], capsys)
    assert code == 0, err
    code, out_b, err = run_cli(["sample-generate", "--plan", str(plan_b)], capsys)
    assert code == 0, err
    payload_a = json.loads(out_a)
    payload_b = json.loads(out_b)
    assert payload_a["generation_content_id"] == payload_b["generation_content_id"]
    assert payload_a["diagnostics"] == payload_b["diagnostics"]
    bytes_a = (plans_dir / "plan-a.json").read_bytes()
    bytes_b = (plans_dir / "plan-b.json").read_bytes()
    assert bytes_a == bytes_b
    parsed_a = parse_build_plan_bytes(bytes_a)
    parsed_b = parse_build_plan_bytes(bytes_b)
    assert [request.feature_window_close for request in parsed_a.requests] == [
        request.feature_window_close for request in parsed_b.requests
    ]


def test_generation_plan_key_order_and_whitespace_invariance(std_fixture, capsys):
    payload = generation_plan_dict(
        build_dirs=(str(std_fixture["build"].build_path),),
        feature_paths=std_fixture["feature_paths"],
        label_paths=std_fixture["label_paths"],
        split_path=std_fixture["split_path"],
        output_root=str(std_fixture["tmp_path"] / "datasets"),
        output_plan_path=str(
            std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
        ),
    )
    pretty_payload = dict(payload)
    pretty_payload["output_plan_path"] = str(
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    )
    compact = write_generation_plan(
        std_fixture["tmp_path"] / "compact.json",
        {key: payload[key] for key in reversed(list(payload))},
    )
    pretty = write_generation_plan(
        std_fixture["tmp_path"] / "pretty.json", pretty_payload, sort_keys=True, indent=4
    )
    for plan_path in (compact, pretty):
        code, out, err = run_cli(
            ["sample-generate", "--plan", str(plan_path)], capsys
        )
        assert code == 0, err
    compact_out = (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
    ).read_bytes()
    pretty_out = (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    ).read_bytes()
    assert compact_out == pretty_out


def test_input_array_order_reversal_identical_bytes(tmp_path, capsys):
    build_a = make_build(tmp_path, code="US.MU", count=10, run_id="run-a")
    build_b = make_build(
        tmp_path, code="US.NVDA", count=6, run_id="run-b", cfg=settings(tmp_path)
    )
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    rolling = spec_dir / "rolling_mean.yaml"
    rolling.write_text(
        feature_spec_yaml(name="rolling_mean", window_bars=2), encoding="utf-8"
    )
    direction = spec_dir / "forward_direction.yaml"
    direction.write_text(
        label_spec_yaml(name="forward_direction", horizon=2, output_type="int64"),
        encoding="utf-8",
    )
    base_feature, base_label, split_path = write_fixture_files(tmp_path)
    feature_ab = (str(rolling),) + base_feature
    feature_ba = base_feature + (str(rolling),)
    label_ab = (str(direction),) + base_label
    label_ba = base_label + (str(direction),)
    build_ab = (str(build_a.build_path), str(build_b.build_path))
    build_ba = (str(build_b.build_path), str(build_a.build_path))
    symbols = ("US.MU", "US.NVDA")
    plan_ab = write_generation_plan(
        tmp_path / "plan-ab.json",
        generation_plan_dict(
            build_dirs=build_ab,
            feature_paths=feature_ab,
            label_paths=label_ab,
            split_path=split_path,
            symbols=symbols,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "out-ab.json"),
        ),
    )
    plan_ba = write_generation_plan(
        tmp_path / "plan-ba.json",
        generation_plan_dict(
            build_dirs=build_ba,
            feature_paths=feature_ba,
            label_paths=label_ba,
            split_path=split_path,
            symbols=tuple(reversed(symbols)),
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(tmp_path / "out-ba.json"),
        ),
    )
    code, out_ab, err = run_cli(["sample-generate", "--plan", str(plan_ab)], capsys)
    assert code == 0, err
    code, out_ba, err = run_cli(["sample-generate", "--plan", str(plan_ba)], capsys)
    assert code == 0, err
    assert json.loads(out_ab)["generation_content_id"] == json.loads(out_ba)[
        "generation_content_id"
    ]
    assert (tmp_path / "out-ab.json").read_bytes() == (tmp_path / "out-ba.json").read_bytes()


def test_equivalent_timezone_representations_identical_bytes(std_fixture, capsys):
    base = generation_plan_dict(
        build_dirs=(str(std_fixture["build"].build_path),),
        feature_paths=std_fixture["feature_paths"],
        label_paths=std_fixture["label_paths"],
        split_path=std_fixture["split_path"],
        dataset_as_of="2026-08-01T00:00:00+00:00",
        built_at="2026-08-05T10:00:00+09:00",
        output_root=str(std_fixture["tmp_path"] / "datasets"),
        output_plan_path=str(
            std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
        ),
    )
    equivalent = dict(base)
    equivalent["dataset_as_of"] = "2026-08-01T09:00:00+09:00"
    equivalent["built_at"] = "2026-08-05T01:00:00+00:00"
    equivalent["output_plan_path"] = str(
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    )
    plan_one = write_generation_plan(std_fixture["tmp_path"] / "one.json", base)
    plan_two = write_generation_plan(
        std_fixture["tmp_path"] / "two.json", equivalent
    )
    for plan_path in (plan_one, plan_two):
        code, out, err = run_cli(
            ["sample-generate", "--plan", str(plan_path)], capsys
        )
        assert code == 0, err
    assert (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
    ).read_bytes() == (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    ).read_bytes()


def test_cwd_independence_subprocess(e2e_fixtures, tmp_path):
    """Different working directories with the same explicit absolute
    ``--plan`` path produce identical output bytes and result JSON (the
    output file is removed between runs so ``created_new_plan`` stays the
    only comparable fact)."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(str(e2e_fixtures.build.build_path),),
            feature_paths=e2e_fixtures.feature_paths,
            label_paths=e2e_fixtures.label_paths,
            split_path=e2e_fixtures.split_path,
            output_root=str(tmp_path / "datasets"),
            output_plan_path=str(plans_dir / "plan.json"),
        ),
    )
    other = tmp_path / "other-cwd"
    other.mkdir()
    first = run_cli_subprocess(
        "sample-generate", "--plan", str(plan_path), cwd=tmp_path
    )
    assert first.returncode == 0, first.stderr
    output_path = plans_dir / "plan.json"
    first_bytes = output_path.read_bytes()
    output_path.unlink()
    second = run_cli_subprocess(
        "sample-generate", "--plan", str(plan_path), cwd=other
    )
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert output_path.read_bytes() == first_bytes


def test_built_at_semantic_change_does_not_change_identity_but_changes_bytes(
    std_fixture, capsys
):
    payload = generation_plan_dict(
        build_dirs=(str(std_fixture["build"].build_path),),
        feature_paths=std_fixture["feature_paths"],
        label_paths=std_fixture["label_paths"],
        split_path=std_fixture["split_path"],
        output_root=str(std_fixture["tmp_path"] / "datasets"),
        output_plan_path=str(
            std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
        ),
    )
    later = dict(payload)
    later["built_at"] = "2026-08-06T01:00:00+00:00"
    later["output_plan_path"] = str(
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    )
    plan_one = write_generation_plan(std_fixture["tmp_path"] / "one.json", payload)
    plan_two = write_generation_plan(std_fixture["tmp_path"] / "two.json", later)
    ids = []
    for plan_path in (plan_one, plan_two):
        code, out, err = run_cli(
            ["sample-generate", "--plan", str(plan_path)], capsys
        )
        assert code == 0, err
        ids.append(json.loads(out)["generation_content_id"])
    assert ids[0] == ids[1]
    bytes_one = (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
    ).read_bytes()
    bytes_two = (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    ).read_bytes()
    assert bytes_one != bytes_two


def test_generation_semantic_change_changes_identity_and_output(std_fixture, capsys):
    payload = generation_plan_dict(
        build_dirs=(str(std_fixture["build"].build_path),),
        feature_paths=std_fixture["feature_paths"],
        label_paths=std_fixture["label_paths"],
        split_path=std_fixture["split_path"],
        output_root=str(std_fixture["tmp_path"] / "datasets"),
        output_plan_path=str(
            std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
        ),
    )
    changed = dict(payload)
    changed["generation_rule"] = dict(payload["generation_rule"])
    changed["generation_rule"]["stride_bars"] = 1
    changed["output_plan_path"] = str(
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    )
    plan_one = write_generation_plan(std_fixture["tmp_path"] / "one.json", payload)
    plan_two = write_generation_plan(std_fixture["tmp_path"] / "two.json", changed)
    results = []
    for plan_path in (plan_one, plan_two):
        code, out, err = run_cli(
            ["sample-generate", "--plan", str(plan_path)], capsys
        )
        assert code == 0, err
        results.append(json.loads(out))
    assert results[0]["generation_content_id"] != results[1]["generation_content_id"]
    assert results[0]["generated_request_count"] != results[1][
        "generated_request_count"
    ]
    assert (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
    ).read_bytes() != (
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    ).read_bytes()


def test_dataset_as_of_enters_identity(std_fixture, capsys):
    payload = generation_plan_dict(
        build_dirs=(str(std_fixture["build"].build_path),),
        feature_paths=std_fixture["feature_paths"],
        label_paths=std_fixture["label_paths"],
        split_path=std_fixture["split_path"],
        dataset_as_of="2026-08-01T00:00:00+00:00",
        output_root=str(std_fixture["tmp_path"] / "datasets"),
        output_plan_path=str(
            std_fixture["tmp_path"] / "plans" / "generated" / "plan-1.json"
        ),
    )
    with_as_of = write_generation_plan(
        std_fixture["tmp_path"] / "with-as-of.json", payload
    )
    payload["dataset_as_of"] = None
    payload["output_plan_path"] = str(
        std_fixture["tmp_path"] / "plans" / "generated" / "plan-2.json"
    )
    without = write_generation_plan(std_fixture["tmp_path"] / "without.json", payload)
    ids = []
    for plan_path in (with_as_of, without):
        code, out, err = run_cli(
            ["sample-generate", "--plan", str(plan_path)], capsys
        )
        assert code == 0, err
        ids.append(json.loads(out)["generation_content_id"])
    assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# K. No side effects.
# ---------------------------------------------------------------------------


def test_no_current_time_anywhere(std_fixture, monkeypatch, capsys):
    from datetime import datetime as _real_datetime

    from market_vault.dataset import (
        sample_generation_cli as sg_cli_mod,
        sample_generation_core_models as core_models_mod,
        sample_generation_models as models_mod,
        sample_generation_output as output_mod,
    )

    class _NoNowDatetime(_real_datetime):
        @classmethod
        def now(cls, *args, **kwargs):
            pytest.fail("current time must never be read")

        @classmethod
        def utcnow(cls, *args, **kwargs):
            pytest.fail("current time must never be read")

    # Only modules that actually bind the ``datetime`` name are patched; the
    # generator core and the shared split loader do not bind it at all.
    for module in (sg_cli_mod, core_models_mod, models_mod, output_mod):
        monkeypatch.setattr(module, "datetime", _NoNowDatetime)
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "SUCCESS"


def test_no_settings_network_or_opend(std_fixture, monkeypatch, capsys):
    import socket

    import market_vault.config as config

    monkeypatch.setattr(
        config, "load_settings", lambda *a, **k: pytest.fail("settings must not load")
    )
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("no network"))
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "SUCCESS"


def test_no_dataset_build_or_pit_or_catalog(std_fixture, monkeypatch, capsys):
    from market_vault.dataset import (
        feature_execution,
        label_execution,
        materialization,
        orchestration,
        pit,
        reader,
    )
    from market_vault.storage import catalog as catalog_module

    for module, name in (
        (orchestration, "orchestrate_dataset_build"),
        (materialization, "materialize_dataset_artifacts"),
        (reader, "load_verified_dataset"),
        (pit, "assemble_point_in_time_samples"),
        (feature_execution, "execute_builtin_features"),
        (label_execution, "execute_builtin_labels"),
    ):
        monkeypatch.setattr(
            module, name, lambda *a, **k: pytest.fail(f"{name} must not be called")
        )
    monkeypatch.setattr(
        catalog_module, "Catalog", lambda *a, **k: pytest.fail("Catalog must not be used")
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert json.loads(out)["result"] == "SUCCESS"


def test_no_file_writes_beyond_output_plan(std_fixture, monkeypatch, capsys):
    monkeypatch.setattr(
        Path, "write_bytes", lambda self, *a, **k: pytest.fail("no write_bytes")
    )
    monkeypatch.setattr(
        Path, "write_text", lambda self, *a, **k: pytest.fail("no write_text")
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    assert std_fixture["output_plan_path"].exists()


def test_production_sources_have_no_forbidden_calls():
    """The four new PR-4 production modules must never call the current
    time, the filesystem scan / expansion machinery, settings, OpenD, the
    network, or any Dataset build / PIT / Feature / Label / Catalog entry.
    (The PR-3 core modules are audited by their own test with their own
    forbidden list.)"""
    rels = (
        "src/market_vault/dataset/sample_generation_cli.py",
        "src/market_vault/dataset/sample_generation_cli_models.py",
        "src/market_vault/dataset/sample_generation_output.py",
        "src/market_vault/dataset/sample_generation_split.py",
    )
    sources = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in rels}
    for rel, text in sources.items():
        for forbidden in (
            "datetime.now",
            "datetime.utcnow",
            "random",
            "uuid",
            "urllib",
            "socket",
            "requests.",
            "load_settings",
            "OpenD",
            "rglob",
            "glob(",
            "iterdir",
            ".resolve(",
            "orchestrate_dataset_build",
            "materialize_dataset_artifacts",
            "load_verified_dataset",
        ):
            assert forbidden not in text, f"forbidden token {forbidden!r} in {rel}"
    # ``Path.cwd`` is called exactly once, only in the CLI module, only to
    # locate the explicit relative ``--plan`` argument; it never enters a
    # model, an identity, the result, or the output build-plan bytes.
    cli_text = sources["src/market_vault/dataset/sample_generation_cli.py"]
    assert cli_text.count("Path.cwd()") == 1
    assert "_coerce_generation_plan_path" in cli_text.split("Path.cwd()")[0]
    for rel, text in sources.items():
        if rel != "src/market_vault/dataset/sample_generation_cli.py":
            assert "Path.cwd" not in text, f"Path.cwd must not appear in {rel}"


# ---------------------------------------------------------------------------
# L. Shared split loader authority behavior (unchanged after extraction).
# ---------------------------------------------------------------------------


def test_shared_split_loader_rejects_bom(tmp_path):
    split_path = tmp_path / "bom.json"
    split_path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps(SPLIT_SPEC_PAYLOAD).encode("utf-8")
    )
    with pytest.raises(SampleGenerationError) as excinfo:
        sg_split.load_sample_generation_split_spec(split_path)
    assert "split spec file must not carry a UTF-8 BOM" in str(excinfo.value)


def test_shared_split_loader_rejects_duplicate_keys(tmp_path):
    duplicate = (
        '{"spec_schema_version": "market-vault-chronological-split-spec-v1", '
        '"spec_schema_version": "x"}'
    )
    split_path = tmp_path / "duplicate.json"
    split_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(SampleGenerationError) as excinfo:
        sg_split.load_sample_generation_split_spec(split_path)
    assert "duplicate JSON key" in str(excinfo.value)


def test_shared_split_loader_rejects_unknown_and_missing_fields(tmp_path):
    split_path = tmp_path / "bad.json"
    split_path.write_text(
        json.dumps({**SPLIT_SPEC_PAYLOAD, "extra": 1}), encoding="utf-8"
    )
    with pytest.raises(SampleGenerationError) as excinfo:
        sg_split.load_sample_generation_split_spec(split_path)
    assert "unknown field(s) in split spec" in str(excinfo.value)
    missing = {key: value for key, value in SPLIT_SPEC_PAYLOAD.items() if key != "name"}
    split_path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(SampleGenerationError) as excinfo:
        sg_split.load_sample_generation_split_spec(split_path)
    assert "missing required field(s) in split spec" in str(excinfo.value)


def test_shared_split_loader_validates_formal_semantics(tmp_path):
    payload = dict(SPLIT_SPEC_PAYLOAD)
    payload["train_end_date"] = "2026-12-31"  # breaks ordering
    split_path = tmp_path / "bad-order.json"
    split_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SplitValidationError):
        sg_split.load_sample_generation_split_spec(split_path)


# ---------------------------------------------------------------------------
# M. Core behavior preserved after the shared-loader extraction.
# ---------------------------------------------------------------------------


def test_core_error_messages_unchanged_after_extraction(tmp_path):
    """The strict split-spec failures still surface from the core with the
    exact pre-PR-4 messages."""
    from market_vault.dataset import SampleGenerationError

    build = make_build(tmp_path, count=10)
    feature_paths, label_paths, _ = write_fixture_files(tmp_path)
    bad_split = tmp_path / "bad-split.json"
    bad_split.write_bytes(b"\xef\xbb\xbf{}")
    plan = make_plan_model(
        build_paths=(str(build.build_path),),
        feature_paths=feature_paths,
        label_paths=label_paths,
        split_path=str(bad_split),
    )
    with pytest.raises(SampleGenerationError) as excinfo:
        generate_sample_requests(plan, path_base=tmp_path)
    assert "split spec file must not carry a UTF-8 BOM" in str(excinfo.value)


# ---------------------------------------------------------------------------
# N. Independent-review hardening: transactional output writes.
# ---------------------------------------------------------------------------

#: Frozen SHA-256 of the relative-path fixture's generated build-plan
#: bytes, computed from the pre-hardening head ``5957d32``; the hardening
#: must never change the normal output bytes. The relative fixture is used
#: because its build-plan bytes contain no absolute path and are rendered
#: with POSIX separators, so they are identical on every machine, directory,
#: and platform (verified on Windows and Linux CI). The regression now
#: reproduces the bytes from the static reference Canonical artifact
#: (PyArrow25-produced base64 fixture), independent of the local
#: materializer and of the running PyArrow runtime/reader; see
#: tests/fixtures/v060_portability/.
OLD_HEAD_RELATIVE_FIXTURE_PLAN_SHA256 = (
    "78cd9e895ee966722c83db8d5388a49c635b8fd448fe8de796e2b56dcebf964b"
)


class _ShortWriteFile:
    """Real file wrapper whose ``write()`` returns a wrong byte count (or
    ``None``) without raising ``OSError``: the target file is really created
    through ``xb`` and really written, so the return-value check itself —
    not a proxy exception — must catch the short write."""

    def __init__(self, real, *, mode):
        self._real = real
        self._mode = mode

    def write(self, data):
        if self._mode == "truncate":
            written = len(data) // 2
            self._real.write(data[:written])
            return written
        if self._mode == "none":
            self._real.write(data)
            return None
        raise AssertionError(f"unknown short-write mode {self._mode!r}")

    def close(self):
        self._real.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class _FailingReadFile:
    """Real file wrapper whose ``read()`` raises an ``OSError`` or returns
    different bytes; used to simulate post-write read-back failures."""

    def __init__(self, real, *, error=None, mismatch_bytes=None):
        self._real = real
        self._error = error
        self._mismatch_bytes = mismatch_bytes

    def read(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return self._mismatch_bytes

    def close(self):
        self._real.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _install_short_write_proxy(monkeypatch, proxy_mode: str) -> None:
    real_open = Path.open

    def _proxy_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        if mode == "xb":
            return _ShortWriteFile(handle, mode=proxy_mode)
        return handle

    monkeypatch.setattr(Path, "open", _proxy_open)


def _install_read_back_proxy(
    monkeypatch,
    output_plan_path,
    *,
    error=None,
    mismatch_bytes=None,
) -> None:
    real_open = Path.open

    def _proxy_open(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        if mode == "rb" and str(self) == str(output_plan_path):
            return _FailingReadFile(
                handle, error=error, mismatch_bytes=mismatch_bytes
            )
        return handle

    monkeypatch.setattr(Path, "open", _proxy_open)


def _install_second_parse_failure(monkeypatch, error) -> list:
    """The first ``parse_build_plan_bytes`` call (pre-write) succeeds; the
    second call (inside the post-write read-back) raises ``error``."""
    calls = []
    real_parse = sg_cli.parse_build_plan_bytes

    def _spy_parse(payload):
        calls.append(len(calls))
        if len(calls) == 2:
            raise error
        return real_parse(payload)

    monkeypatch.setattr(sg_cli, "parse_build_plan_bytes", _spy_parse)
    return calls


def _assert_failed_json(code, out, err) -> dict:
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["result"] == "FAILED"
    assert failure["error_type"] == "SampleGenerationCLIError"
    return failure


def test_short_write_fails_and_removes_new_file(std_fixture, monkeypatch, capsys):
    """The exclusive create really happens and only half the bytes are
    written; the write-return check must fail closed and remove the partial
    file without waiting for the read-back."""
    _install_short_write_proxy(monkeypatch, proxy_mode="truncate")
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "short write while creating output plan" in failure["error"]
    assert "expected" in failure["error"]
    assert not std_fixture["output_plan_path"].exists()


def test_short_write_none_fails_and_removes_new_file(std_fixture, monkeypatch, capsys):
    """A ``None`` write return (the whole payload was written, but the count
    is untrustworthy) must still fail closed and remove the file."""
    _install_short_write_proxy(monkeypatch, proxy_mode="none")
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "short write while creating output plan" in failure["error"]
    assert "wrote None" in failure["error"]
    assert not std_fixture["output_plan_path"].exists()


def test_read_back_oserror_removes_new_file(std_fixture, monkeypatch, capsys):
    """The file is created and written successfully; the read-back raises an
    ``OSError``: the formal error is converted with its ``__cause__`` and
    the new file is removed."""
    captured = capture_failure(monkeypatch)
    _install_read_back_proxy(
        monkeypatch,
        std_fixture["output_plan_path"],
        error=OSError("simulated read-back failure"),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "cannot read back output plan" in failure["error"]
    assert isinstance(captured["exc"].__cause__, OSError)
    assert not std_fixture["output_plan_path"].exists()


def test_read_back_mismatch_removes_new_file(std_fixture, monkeypatch, capsys):
    """The file is created and written successfully; the read-back returns
    different bytes: fail closed with the read-back mismatch and remove the
    new file."""
    _install_read_back_proxy(
        monkeypatch,
        std_fixture["output_plan_path"],
        mismatch_bytes=b'{"different": true}\n',
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "output plan read-back mismatch" in failure["error"]
    assert not std_fixture["output_plan_path"].exists()


def test_second_parse_failure_removes_new_file(std_fixture, monkeypatch, capsys):
    """The pre-write parse succeeds; the second (read-back) parse raises a
    formal ``DatasetCLIError``: converted by the CLI boundary and the new
    file is removed."""
    from market_vault.dataset.cli_models import DatasetCLIError

    calls = _install_second_parse_failure(
        monkeypatch, DatasetCLIError("simulated second parse failure")
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "sample-generate failed: simulated second parse failure" in failure["error"]
    assert len(calls) == 2
    assert not std_fixture["output_plan_path"].exists()


def test_second_parse_runtime_error_propagates_and_removes_new_file(
    std_fixture, monkeypatch, capsys
):
    """A programming error in the second parse propagates unchanged (no
    FAILED JSON), and the new file is still removed."""
    calls = _install_second_parse_failure(
        monkeypatch, RuntimeError("simulated programming error")
    )
    with pytest.raises(RuntimeError) as excinfo:
        cli_module.main(
            ["sample-generate", "--plan", str(std_fixture["plan_path"])]
        )
    assert "simulated programming error" in str(excinfo.value)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert len(calls) == 2
    assert not std_fixture["output_plan_path"].exists()


def test_success_payload_runtime_error_propagates_and_removes_new_file(
    std_fixture, monkeypatch, capsys
):
    """A programming error while constructing the success payload (after
    write, read-back, and parse all succeeded) propagates unchanged and the
    new file is removed: the plan commits only once the full payload exists."""

    def _boom_payload(*args, **kwargs):
        raise RuntimeError("simulated payload failure")

    monkeypatch.setattr(sg_cli, "_success_payload", _boom_payload)
    with pytest.raises(RuntimeError) as excinfo:
        cli_module.main(
            ["sample-generate", "--plan", str(std_fixture["plan_path"])]
        )
    assert "simulated payload failure" in str(excinfo.value)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert not std_fixture["output_plan_path"].exists()


def test_post_write_failure_never_deletes_existing_exact_file(
    std_fixture, monkeypatch, capsys
):
    """A post-write failure on a second run (``created_new_plan == False``)
    must never delete or modify the existing exact-byte file; the error is
    converted by the CLI boundary as usual."""
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    path = std_fixture["output_plan_path"]
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    from market_vault.dataset.cli_models import DatasetCLIError

    _install_second_parse_failure(
        monkeypatch, DatasetCLIError("simulated second parse failure")
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "simulated second parse failure" in failure["error"]
    assert path.exists()
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_existing_different_bytes_never_touched_by_transaction(
    std_fixture, monkeypatch, capsys
):
    """An existing different-byte file is rejected before the transaction
    and stays byte- and mtime-identical."""
    path = std_fixture["output_plan_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"different": true}\n'
    path.write_bytes(original)
    before_mtime = path.stat().st_mtime_ns
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    failure = _assert_failed_json(code, out, err)
    assert "refusing to overwrite existing build plan with different content" in (
        failure["error"]
    )
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == before_mtime


def test_normal_fixture_build_plan_bytes_unchanged_from_old_head(
    std_fixture, capsys
):
    """Fixed regression: the standard fixture's generated build-plan bytes
    written by the CLI are byte-identical to the pure serializer output
    (the serializer is untouched by the hardening)."""
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(std_fixture["plan_path"])], capsys
    )
    assert code == 0, err
    generated = std_fixture["output_plan_path"].read_bytes()
    _, _, _, expected = _serialize_via_models(std_fixture)
    assert generated == expected


def test_relative_fixture_build_plan_bytes_unchanged_from_old_head(
    tmp_path, capsys
):
    """Fixed regression: the relative-path fixture's generated build-plan
    bytes (path-independent) are byte-identical to the pre-hardening head
    ``5957d32`` — reproduced from the static reference Canonical artifact
    (PyArrow25-produced base64 fixture), so the regression no longer depends
    on the local materializer or the running PyArrow runtime/reader."""
    build_dir = decode_canonical_fixture(tmp_path, under_dataset=True)
    write_fixture_files(tmp_path)
    plan_path = write_generation_plan(
        tmp_path / "generation-plan.json",
        generation_plan_dict(
            build_dirs=(build_dir.relative_to(tmp_path).as_posix(),),
            feature_paths=("specs/simple_return.yaml",),
            label_paths=("specs/forward_return.yaml",),
            split_path="specs/chronological_split.json",
            output_root="datasets",
            output_plan_path="generated-plan.json",
        ),
    )
    code, out, err = run_cli(
        ["sample-generate", "--plan", str(plan_path)], capsys
    )
    assert code == 0, err
    generated = (tmp_path / "generated-plan.json").read_bytes()
    assert (
        hashlib.sha256(generated).hexdigest()
        == OLD_HEAD_RELATIVE_FIXTURE_PLAN_SHA256
    )
