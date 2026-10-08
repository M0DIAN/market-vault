"""Complete experiment records and explicit authoritative replay boundaries."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_vault import cli, cross_day_dataset
from market_vault.research import strategy_experiment as artifacts
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, create_strategy_experiment,
    load_strategy_experiment, replay_strategy_experiment, write_strategy_experiment,
)
from market_vault.strategy_comparison_io import evaluate_comparison_payload, normalized_comparison_plan
from test_strategy_comparison import _plan, _real_config, verified_workspace_dataset  # noqa: F401
from test_strategy_configuration import _verified_composite_config


@pytest.fixture(scope="module")
def experiment_snapshots(verified_workspace_dataset):
    dataset = verified_workspace_dataset
    config = _verified_composite_config()
    config["strategies"] = config["strategies"][:-1] + (replace(config["strategies"][-1], match="ANY"),)
    plan = normalized_comparison_plan(config, dataset_build_dir=str(dataset.build_path))
    return {mode: create_strategy_experiment(
        plan=plan, report=evaluate_comparison_payload(dataset, config, mode), mode=mode,
        name="Composite research", notes="Explicit development validation; keep TEST held out.",
    ) for mode in ("COMPARISON", "EQUITY", "RISK")}


def resign(root):
    root = {key: value for key, value in root.items() if key != "experiment_id"}
    root["experiment_id"] = sha256(canonical_json(root)).hexdigest()
    return canonical_json(root)


@pytest.mark.parametrize("mode", ["COMPARISON", "EQUITY", "RISK"])
def test_complete_roundtrip_is_immutable_and_replays(experiment_snapshots, mode):
    snapshot = experiment_snapshots[mode]
    restored = StrategyExperiment(snapshot.content)
    assert restored == snapshot
    detached = restored.as_dict()
    detached["plan"]["strategies"][0]["threshold"] = 9876
    assert restored == snapshot and restored.as_dict()["plan"]["strategies"][0]["threshold"] == 0
    report = snapshot.as_dict()["report"]
    assert len(report["results"]) == 4
    assert report["results"][-1]["trades"]
    if mode != "COMPARISON":
        assert len(report["equity"]["results"][0]["points"]) > 100
        assert report["equity"]["results"][0]["points"] == restored.as_dict()["report"]["equity"]["results"][0]["points"]
    replay = replay_strategy_experiment(restored)
    assert replay["report_matches"] is True
    assert replay["expected_report_sha256"] == replay["actual_report_sha256"] == sha256(canonical_json(report)).hexdigest()


def test_exclusive_write_reuse_and_conflict_preserve_existing_file(experiment_snapshots, tmp_path):
    snapshot = experiment_snapshots["RISK"]
    path = tmp_path / "experiment.json"
    assert write_strategy_experiment(snapshot, path=path).created_new_file is True
    before, stat = path.read_bytes(), path.stat().st_mtime_ns
    assert load_strategy_experiment(path) == snapshot
    assert write_strategy_experiment(snapshot, path=path).created_new_file is False
    assert path.stat().st_mtime_ns == stat
    changed = snapshot.as_dict()
    changed["notes"] += "changed"
    with pytest.raises(ValueError, match="existing experiment differs"):
        write_strategy_experiment(StrategyExperiment(resign(changed)), path=path)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="existing regular directory"):
        write_strategy_experiment(snapshot, path=tmp_path / "missing" / "experiment.json")
    assert not (tmp_path / "missing").exists()
    with pytest.raises(ValueError, match="regular file"):
        write_strategy_experiment(snapshot, path=tmp_path)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular file"):
        write_strategy_experiment(snapshot, path=link)
    assert path.read_bytes() == before


def test_concurrent_identical_creation_and_failed_flush_never_replace_or_delete(experiment_snapshots, tmp_path, monkeypatch):
    snapshot = experiment_snapshots["COMPARISON"]
    race_path = tmp_path / "race.json"
    original = Path.open

    def race(path, mode="r", *args, **kwargs):
        if path == race_path and mode == "xb":
            with original(path, "wb") as handle:
                handle.write(snapshot.content)
            raise FileExistsError("simulated concurrent create")
        return original(path, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", race)
        assert not write_strategy_experiment(snapshot, path=race_path).created_new_file
    flush_path = tmp_path / "flush.json"
    with monkeypatch.context() as patch:
        patch.setattr(artifacts.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("flush failed")))
        with pytest.raises(OSError, match="flush failed"):
            write_strategy_experiment(snapshot, path=flush_path)
    assert flush_path.read_bytes() == snapshot.content
    assert not write_strategy_experiment(snapshot, path=flush_path).created_new_file


@pytest.mark.parametrize("case", ["bom", "duplicate_root", "duplicate_nested", "nan", "overflow", "unknown", "nonbytes"])
def test_strict_json_rejects_ambiguous_or_nonfinite_records(experiment_snapshots, case):
    snapshot = experiment_snapshots["RISK"]
    data = snapshot.content
    if case == "bom":
        data = b"\xef\xbb\xbf" + data
    elif case == "duplicate_root":
        data = data.replace(b'{"algorithm_versions":', b'{"name":"extra","algorithm_versions":', 1)
    elif case == "duplicate_nested":
        data = data.replace(b'"commission_bps":', b'"commission_bps":1,"commission_bps":', 1)
    elif case in ("nan", "overflow"):
        data = data.replace(b'"commission_bps":10.0', b'"commission_bps":' + (b"NaN" if case == "nan" else b"1e999"), 1)
    elif case == "unknown":
        root = snapshot.as_dict()
        root["extra"] = 1
        data = resign(root)
    else:
        data = data.decode()
    with pytest.raises((TypeError, ValueError)):
        StrategyExperiment(data)


@pytest.mark.parametrize("case", ["cost", "condition", "label", "dataset", "unknown_metric", "curve_type", "risk_type",
                                  "risk_null_rate", "risk_zero_factor", "risk_negative_vol", "risk_false_ok"])
def test_rehashed_records_still_require_internal_schema_and_plan_bindings(experiment_snapshots, case):
    root = experiment_snapshots["RISK"].as_dict()
    if case == "cost":
        root["plan"]["commission_bps"] += 1
    elif case == "condition":
        root["plan"]["strategies"][-1]["conditions"][0]["threshold"] += 1
    elif case == "label":
        root["plan"]["return_label"] = "different"
    elif case == "dataset":
        root["dataset_id"] = "f" * 64
    elif case == "unknown_metric":
        root["report"]["results"][0]["metrics"]["invented"] = 0
    elif case == "curve_type":
        root["report"]["equity"]["results"][0] = []
    elif case == "risk_type":
        root["report"]["risk"]["results"][0] = []
    else:
        daily = root["report"]["risk"]["benchmark"]["daily_risk"]
        if case == "risk_null_rate":
            daily["risk_free_rate"] = None
        elif case == "risk_zero_factor":
            daily["annualization_factor"] = 0
        elif case == "risk_negative_vol":
            daily["annualized_volatility"] = -1
        else:
            daily.update(observation_count=0, return_count=0, observations=[], returns=[],
                         start_time=None, end_time=None, mean_daily_return=None,
                         annualized_volatility=None, sharpe_ratio=None, unavailable_reason=None)
    with pytest.raises((TypeError, ValueError)):
        StrategyExperiment(resign(root))


def test_corruption_in_unpaged_or_unselected_raw_values_changes_identity(experiment_snapshots):
    root = experiment_snapshots["RISK"].as_dict()
    root["report"]["equity"]["results"][-1]["points"][101]["equity"] += 1e-12
    with pytest.raises(ValueError, match="digest"):
        StrategyExperiment(canonical_json(root))


@pytest.mark.parametrize("command", ["research-experiment-open", "research-experiment-replay"])
@pytest.mark.parametrize("field", ["commission_bps", "slippage_bps"])
@pytest.mark.parametrize("value", [True, "bad", None, [], {}])
def test_malformed_costs_return_structured_cli_failure_before_dataset_io(
    experiment_snapshots, tmp_path, monkeypatch, capsys, command, field, value,
):
    root = experiment_snapshots["COMPARISON"].as_dict()
    root["plan"][field] = value
    path = tmp_path / "malformed-cost.json"
    path.write_bytes(resign(root))
    monkeypatch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset",
                        lambda *a, **k: pytest.fail("malformed snapshot loaded a Dataset"))
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("experiment loaded settings"))
    with pytest.raises(ValueError, match=field + " must be a JSON number"):
        load_strategy_experiment(path)
    assert cli.main([command, "--experiment", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["result_schema_version"] == "market-vault-strategy-experiment-cli-result-v1"
    assert error["status"] == "FAILED" and field + " must be a JSON number" in error["error"]


def test_open_needs_no_dataset_and_replay_accepts_explicit_relocation(experiment_snapshots, tmp_path, monkeypatch):
    original = experiment_snapshots["RISK"]
    root = original.as_dict()
    original_locator = root["plan"]["dataset_build_dir"]
    root["plan"]["dataset_build_dir"] = str(tmp_path / "removed-dataset")
    moved = StrategyExperiment(resign(root))
    path = tmp_path / "archive.json"
    write_strategy_experiment(moved, path=path)
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset", lambda *a, **k: pytest.fail("Open loaded Dataset"))
        patch.setattr(artifacts, "evaluate_comparison_payload", lambda *a, **k: pytest.fail("Open computed strategies"))
        assert load_strategy_experiment(path) == moved
    assert replay_strategy_experiment(moved, dataset_build_dir=original_locator)["report_matches"]
    assert path.read_bytes() == before
    assert moved.as_dict()["plan"]["dataset_build_dir"] == str(tmp_path / "removed-dataset")


def test_versions_and_dataset_identity_fail_before_strategy_execution(experiment_snapshots, monkeypatch):
    snapshot = experiment_snapshots["COMPARISON"]
    root = snapshot.as_dict()
    root["algorithm_versions"]["comparison"] = root["report"]["version"] = "historical-implementation"
    historical = StrategyExperiment(resign(root))  # Known file schema remains viewable.
    monkeypatch.setattr(artifacts, "evaluate_comparison_payload", lambda *a, **k: pytest.fail("fit before gates"))
    with monkeypatch.context() as patch:
        patch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset", lambda *a, **k: pytest.fail("version gate must precede Dataset I/O"))
        with pytest.raises(ValueError, match="algorithm versions differ"):
            replay_strategy_experiment(historical)
    monkeypatch.setattr(cross_day_dataset, "load_verified_multi_source_cross_day_dataset", lambda *a, **k: SimpleNamespace(dataset_id="f" * 64))
    with pytest.raises(ValueError, match="Dataset ID differs"):
        replay_strategy_experiment(snapshot)


@pytest.mark.parametrize("location", ["metric", "ledger", "daily", "trade"])
def test_replay_compares_complete_payload_even_when_ids_and_display_values_match(experiment_snapshots, monkeypatch, location):
    original = experiment_snapshots["RISK"]
    root = original.as_dict()
    report = root["report"]
    if location == "metric":
        report["results"][-1]["metrics"]["average_trade_return"] += 1e-12
    elif location == "ledger":
        report["equity"]["results"][-1]["points"][101]["equity"] += 1e-12
    elif location == "daily":
        report["risk"]["results"][-1]["daily_risk"]["returns"][0]["value"] += 1e-12
    else:
        report["results"][-1]["trades"][0]["signal_value"] += 1e-12
    forged = StrategyExperiment(resign(root))
    assert forged.as_dict()["report"]["comparison_id"] == original.as_dict()["report"]["comparison_id"]
    # Isolate the full-result comparison; real strict replay is exercised above.
    monkeypatch.setattr(artifacts, "evaluate_comparison_payload", lambda *a, **k: original.as_dict()["report"])
    with pytest.raises(ValueError, match="complete report mismatch"):
        replay_strategy_experiment(forged)


def test_cli_default_payload_is_unchanged_save_computes_once_and_open_skips_settings(
    verified_workspace_dataset, tmp_path, monkeypatch, capsys,
):
    from market_vault import strategy_comparison_cli
    expected = evaluate_comparison_payload(verified_workspace_dataset, _real_config(), "COMPARISON")
    calls = []
    evaluate = strategy_comparison_cli.evaluate_comparison_payload

    def counted(*args):
        calls.append(args)
        return evaluate(*args)

    monkeypatch.setattr(strategy_comparison_cli, "evaluate_comparison_payload", counted)
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("experiment loaded settings"))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_plan(verified_workspace_dataset.build_path)), encoding="utf-8")
    output = tmp_path / "run.json"
    assert cli.main(["research-compare-strategies", "--plan", str(plan), "--output", str(output), "--name", "baseline"]) == 0
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out) == expected
    saved = load_strategy_experiment(output)
    assert saved.as_dict()["report"] == expected and saved.as_dict()["name"] == "baseline"
    assert cli.main(["research-experiment-open", "--experiment", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["experiment"] == saved.as_dict()
    assert cli.main(["research-experiment-replay", "--experiment", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["report_matches"] is True
    assert cli.main(["research-experiment-open", "--experiment", str(tmp_path / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
