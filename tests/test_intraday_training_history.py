"""Fixed history windows, independent linear oracle and actual saved-source flow."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import subprocess
import sysconfig
from types import SimpleNamespace

import pytest

from market_vault.backtest.intraday import IntradayExecutionPolicy
from market_vault.research import intraday_research as research
from market_vault.research import intraday_training_history as history
from market_vault.research.intraday_models import QuadraticRidgeStrategy
from market_vault.research.strategy_comparison import RidgeStrategy
from market_vault.research.strategy_experiment import StrategyExperiment, canonical_json
from test_intraday_experiment import signed
from test_strategy_intraday_ml import quadratic_dev_case


ROOT = Path(__file__).resolve().parents[1]
POLICY = IntradayExecutionPolicy(10, 5, entry_delay_minutes=0, stop_new_minutes=5, flatten_minutes=5)


def _history_case(*, starts=(25,), old_shift=0.0, future_shift=0.0, no_recent_targets=False):
    """25 historical sessions with a slope reversal, one strict boundary purge.

    This small computation-level case uses a complete execution grid; real Q5
    authority is tested independently with the existing immutable source fixture.
    """
    origin = datetime.fromisoformat("2025-04-01T14:30:00+00:00")
    sessions, prices, observations, targets = [], [], [], []
    for index in range(28):
        opened = origin + timedelta(days=index)
        day = opened.date().isoformat()
        sessions.append({"trading_day": day, "open_time": opened.isoformat(),
                         "close_time": (opened + timedelta(minutes=30)).isoformat(), "bar_count": 6})
        for slot, price in enumerate((100, 100, 110, 100, 120, 120)):
            prices.append({"trading_day": day, "slot": slot, "event_time": (opened + timedelta(minutes=5 * slot)).isoformat(),
                "available_at": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "open": price, "close": price,
                "row_version_id": f"price-{index}-{slot}"})
        for slot, value in enumerate((-2., -1., 1., 2., 3.)):
            key = f"row-{index}-{slot}"
            observations.append({"observation_key": key, "trading_day": day, "slot": slot,
                "decision_time": (opened + timedelta(minutes=5 * (slot + 1))).isoformat(), "status": "READY",
                "features": {"x": value + (future_shift if index >= 25 else 0), "constant": 5.}})
            complete = slot < 4 and not (no_recent_targets and 15 <= index < 25)
            beta = -.03 if index < 15 else .01
            targets.append({"observation_key": key, "status": "COMPLETE" if complete else "INCOMPLETE",
                "reason": None if complete else "TAIL", "actual_label_end_time": (opened + timedelta(minutes=5 * (slot + 2))).isoformat(),
                "value": beta * value + (old_shift * value if index < 5 else 0) + (future_shift if index >= 25 else 0) if complete else None})
    # Equality at the original boundary is purged, even though its observation
    # is in the last training day. Its extreme x must not enter either scaler.
    boundary = sessions[starts[0]]["open_time"]
    day = sessions[starts[0] - 1]["trading_day"]
    observations.append({"observation_key": "boundary-purged", "trading_day": day, "slot": 4,
        "decision_time": (datetime.fromisoformat(boundary) - timedelta(hours=1)).isoformat(),
        "status": "READY", "features": {"x": 1000., "constant": 5.}})
    targets.append({"observation_key": "boundary-purged", "status": "COMPLETE", "reason": None,
                    "actual_label_end_time": boundary, "value": 999.})
    days = [row["trading_day"] for row in sessions]
    report = {"sessions": sessions, "prices": prices, "observations": observations, "targets": targets}
    folds, evaluated = [], []
    for index, start in enumerate(starts):
        validation = [row for row in observations if row["trading_day"] == days[start]]
        evaluated.append(days[start])
        folds.append({"fold_index": index, "fold_id": f"fold-{index}", "training_days": days[:start],
            "validation_days": [days[start]], "training_boundary": sessions[start]["open_time"],
            "validation_keys": [row["observation_key"] for row in validation]})
    context = {"feature_fields": ["x", "constant"], "folds": folds, "evaluated_days": evaluated, "interval": "5m",
               "validation_keys": [key for fold in folds for key in fold["validation_keys"]]}
    return SimpleNamespace(report=report, context=context,
        observations=tuple(row for row in observations if row["trading_day"] in evaluated))


def _variants(prepared, strategy):
    cache = {}
    return [history._history_variant(prepared, strategy, POLICY, variant=name, window_days=days, cache=cache)
            for name, days in history.HISTORY_VARIANTS], cache


@pytest.mark.parametrize("strategy_type", [RidgeStrategy, QuadraticRidgeStrategy])
def test_history_slope_reversal_exact_window_scaling_purge_and_future_isolation(strategy_type):
    prepared = _history_case()
    strategy = strategy_type("Fixed", 1., 0.)
    variants, cache = _variants(prepared, strategy)
    assert len(cache) == 3
    # Balanced x gives sum(x²)=10 per day, population variance=2.5. The
    # standardized Ridge penalty gives b = sum(x*y)/(sum(x²)+alpha*2.5).
    slopes = [(-.03 * 15 * 10 + .01 * 10 * 10) / (25 * 10 + 2.5),
              (.01 * 10 * 10) / (10 * 10 + 2.5),
              (-.03 * 10 * 10 + .01 * 10 * 10) / (20 * 10 + 2.5)]
    for variant, day_count, slope in zip(variants, (25, 10, 20), slopes, strict=True):
        fold, account = variant["folds"][0], variant["account"]
        assert variant["status"] == "AVAILABLE" and len(fold["training_days"]) == day_count
        assert len(fold["training_keys"]) == day_count * 4 and fold["purged_keys"] == ["boundary-purged"]
        assert fold["model"]["training_keys"] == fold["training_keys"]
        assert fold["model"]["training_boundary"] == prepared.context["folds"][0]["training_boundary"]
        stats = fold["model"].get("input_transform", fold["model"])
        assert stats["means"] == [0., 5.]
        assert stats["scales"][0] == pytest.approx(math.sqrt(2.5))
        assert [row["score"] for row in account["predictions"]] == pytest.approx([slope * x for x in (-2, -1, 1, 2, 3)])
        assert account["prediction_metrics"]["complete_target_count"] == 4
        assert len(account["predictions"]) == 5 and len(account["execution"]["decisions"]) == 5
        assert account["prediction_quality"]["mse"]["value"] == pytest.approx((slope - .01) ** 2 * 2.5)
        assert [row["trading_day"] for row in account["execution"]["daily"]] == prepared.context["evaluated_days"]
        assert account["execution"]["metrics"]["commission_total"] > 0
    assert variants[1]["account"]["prediction_quality"]["mse"]["value"] < variants[0]["account"]["prediction_quality"]["mse"]["value"]
    assert variants[0]["account"]["predictions"][0]["target"] != variants[1]["account"]["predictions"][0]["target"]
    future, _ = _variants(_history_case(future_shift=100), strategy)
    past, _ = _variants(_history_case(old_shift=1), strategy)
    assert [row["folds"][0]["model"] for row in future] == [row["folds"][0]["model"] for row in variants]
    assert past[0]["folds"][0]["model"] != variants[0]["folds"][0]["model"]
    assert [row["folds"][0]["model"] for row in past[1:]] == [row["folds"][0]["model"] for row in variants[1:]]


def test_history_unavailable_does_not_discard_folds_or_fabricate_partial_accounts():
    variants, _ = _variants(_history_case(starts=(15, 25)), RidgeStrategy("Fixed", 1., 0.))
    assert [row["status"] for row in variants] == ["AVAILABLE", "AVAILABLE", "UNAVAILABLE"]
    recent = variants[2]
    assert len(recent["folds"]) == 2 and recent["account"] is None
    assert [row["fold_index"] for row in recent["unavailable_reasons"]] == [0]
    assert recent["unavailable_reasons"][0]["reason"] == "INSUFFICIENT_TRAINING_DAYS"
    assert all(row["model"] is None for row in recent["folds"])
    variants, _ = _variants(_history_case(no_recent_targets=True), RidgeStrategy("Fixed", 1., 0.))
    assert [row["status"] for row in variants] == ["AVAILABLE", "UNAVAILABLE", "AVAILABLE"]
    assert variants[1]["unavailable_reasons"][0]["reason"] == "NO_TRAINING_ROWS"
    assert len(variants[1]["folds"][0]["training_days"]) == 10
    assert variants[1]["account"] is None and variants[1]["folds"][0]["training_keys"] == []


@pytest.fixture(scope="session")
def history_case(quadratic_dev_case):
    data, plan, report, snapshot, path, _ = quadratic_dev_case
    results = {}
    for index in (0, 1):
        loads, original = [], research.load_intraday_dataset
        def load(*args, **kwargs):
            loads.append(args)
            return original(*args, **kwargs)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(research, "load_intraday_dataset", load)
            results[index] = history.analyze_intraday_training_history(snapshot, candidate_index=index)
        assert len(loads) == 1
    return data, plan, report, snapshot, path, results


def test_saved_linear_and_quadratic_reproduce_complete_source_and_common_account(history_case):
    _, _, report, snapshot, path, results = history_case
    before = path.read_bytes()
    for index, result in results.items():
        original = report["groups"][0]["results"][index]
        expanding = result["variants"][0]
        assert result["status"] == "AVAILABLE"
        assert result["strategy"]["kind"] == ("RIDGE", "QUADRATIC_RIDGE")[index]
        assert result["candidate_id"] == original["candidate_id"]
        for key in ("predictions", "prediction_metrics", "execution", "risk", "fold_contributions"):
            assert expanding["account"][key] == original[key]
        assert result["benchmark"] == report["groups"][0]["benchmark"]
        assert 1 + sum(row["cash_contribution"] for row in result["benchmark_fold_contributions"]) == pytest.approx(
            result["benchmark"]["execution"]["metrics"]["final_cash"])
        assert result["sample"]["incomplete_target_count"] > 0
        assert result["return_basis"]["total_return_semantics"] == "SIMULATED_ACCOUNT_CHANGE"
        assert result["method"]["automatic_selection"] is False
        for variant in result["variants"]:
            assert [row["observation_key"] for row in variant["account"]["predictions"]] == result["context"]["validation_keys"]
            assert [row["trading_day"] for row in variant["account"]["execution"]["daily"]] == result["context"]["evaluated_days"]
            assert variant["account"]["execution"]["policy"] == result["execution_policy"]
            assert variant["account"]["execution"]["price_evidence_id"] == original["execution"]["price_evidence_id"]
        # At the first original fold there are exactly 20 historical days.
        assert result["variants"][2]["folds"][0]["model"] == expanding["folds"][0]["model"]
        assert result["variants"][1]["folds"][0]["model"] != expanding["folds"][0]["model"]
        assert not result["evidence"]["complete_experiment_replayed"]
        canonical_json(result)  # No non-finite or non-JSON result escapes.
    assert path.read_bytes() == before == snapshot.content


def test_source_refusals_precede_q5_and_wrong_saved_fit_cannot_be_blessed(history_case, monkeypatch):
    _, _, _, snapshot, _, _ = history_case
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("invalid selection read Q5"))
        for options in ({"candidate_index": True}, {"cost_index": -1}, {"candidate_index": 100}):
            with pytest.raises(ValueError):
                history.analyze_intraday_training_history(snapshot, **options)
        root = snapshot.as_dict()
        root["algorithm_versions"]["research"] = "historical-research"
        root["report"]["version"] = "historical-research"
        with pytest.raises(ValueError, match="algorithms differ"):
            history.analyze_intraday_training_history(StrategyExperiment(signed(root)))
    root = snapshot.as_dict()
    model = root["report"]["groups"][0]["results"][0]["fold_models"][0]["model"]
    model["intercept"] += .25
    model["model_id"] = research.digest({key: value for key, value in model.items() if key != "model_id"})
    with pytest.raises(ValueError, match="fold models"):
        history.analyze_intraday_training_history(StrategyExperiment(signed(root)))


def test_real_installed_cli_deterministic_json_and_relocated_source(history_case, tmp_path, monkeypatch, capsys):
    from market_vault import cli
    data, _, _, _, path, results = history_case
    monkeypatch.setattr(cli, "load_settings", lambda *a, **kw: pytest.fail("analysis loaded settings"))
    command = ["research-intraday-training-history", "--experiment", str(path), "--candidate-index", "1"]
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out)["report"] == results[1]
    console = Path(sysconfig.get_path("scripts")) / ("market-vault.exe" if os.name == "nt" else "market-vault")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "cp1252:strict"}
    result = subprocess.run([str(console), *command], cwd=ROOT, env=env, capture_output=True)
    assert result.returncode == 0 and not result.stderr
    assert result.stdout.isascii() and json.loads(result.stdout)["report"] == results[1]
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(data.path.read_bytes())
    changed = history.analyze_intraday_training_history(history_case[3], candidate_index=1, intraday_data_file=relocated)
    assert changed["source_locator"]["override_used"]
    assert changed["variants"] == results[1]["variants"]
    invalid = subprocess.run([str(console), *command, "--cost-index", "-1"], cwd=ROOT, env=env, capture_output=True)
    assert invalid.returncode == 1 and not invalid.stdout and json.loads(invalid.stderr)["status"] == "FAILED"
    assert cli.main([*command, "--intraday-data", str(tmp_path / "missing.json")]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED"
    assert cli.main(command) == 0  # Ordinary retry uses the unchanged saved source.
    assert json.loads(capsys.readouterr().out)["report"] == results[1]
