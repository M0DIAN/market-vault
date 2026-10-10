"""Discriminating fixed-fit objectives and real immutable study admission."""

from copy import deepcopy
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.backtest import intraday as execution
from market_vault.research import intraday_inner_objective_sensitivity as sensitivity
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_research as research
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
DAYS = [f"2025-01-0{index}" for index in range(1, 6)]
RECIPE = {"kind": "RIDGE", "name": "fixed", "alpha": 1., "threshold": 0.}


def loss_window(*, only_first_day=False):
    targets = [{"observation_key": str(index), "trading_day": DAYS[0 if index < 5 else 1], "value": 0.}
               for index in range(5 if only_first_day else 6)]
    scores = [[0.] * 5 + [2.], [1.] * 5 + [0.], [1.] * 5 + [0.]] + [[3.] * 6] * 3
    family = []
    for index, values in enumerate(scores):
        predictions = [{"observation_key": str(i), "score": value} for i, value in enumerate(values)]
        # An unlabelled READY score is retained as evidence, never scored.
        predictions.append({"observation_key": "tail", "score": 999.})
        family.append({"candidate_index": index, "strategy": {**RECIPE, "alpha": float(index + 1)},
                       "predictions": predictions, "mse": math.fsum(values[int(row["observation_key"])] ** 2 / len(targets)
                           for row in targets), "model": {"model_id": str(index)}})
    return {"validation_days": DAYS, "scored_targets": targets, "family_results": family, "selected_index": 0}


def test_mse_day_removal_preserves_row_weights_exact_ties_and_zero_target_days():
    window = loss_window()
    before = deepcopy(window)
    report = sensitivity._window_sensitivity(window, maximize=False, source_strategy=RECIPE, window_index=0, fold_index=0)
    original, omissions = report["original"], report["omissions"]
    assert original["selected_index"] == 0
    assert original["objectives"][0]["value"] == pytest.approx(float(Fraction(2, 3)))
    assert original["objectives"][1]["value"] == pytest.approx(float(Fraction(5, 6)))
    # Equal-day weighting would choose member 1: (0 + 4)/2 > (1 + 0)/2.
    assert omissions[0]["selected_index"] == 1 and omissions[0]["runner_up_index"] == 2
    assert omissions[0]["margin"] == {"value": 0., "unit": "SQUARED_RATIO", "unavailable_reason": None}
    assert omissions[0]["changed_choice"] is True and omissions[0]["remaining_complete_target_count"] == 1
    assert [row["value"] for row in omissions[0]["objectives"]] == [4., 0., 0., 9., 9., 9.]
    assert omissions[1]["remaining_complete_target_count"] == 5 and omissions[1]["selected_index"] == 0
    assert all(row["unchanged_reason"] == "NO_SCORED_TARGETS_ON_OMITTED_DAY" for row in omissions[2:])
    assert all(row["objectives"] == original["objectives"] for row in omissions[2:])
    assert report["selection_counts"] == [{"candidate_index": i, "count": count} for i, count in enumerate([4, 1, 0, 0, 0, 0])]
    assert report["changed_choice_count"] == 1 and report["available_omission_count"] == 5
    assert report["fixed_evidence"] == window == before


def test_removing_only_scored_day_is_explicitly_unavailable_not_a_partial_family():
    report = sensitivity._window_sensitivity(loss_window(only_first_day=True), maximize=False,
                                             source_strategy=RECIPE, window_index=0)
    row = report["omissions"][0]
    assert row["status"] == "UNAVAILABLE" and row["unavailable_reason"] == "NO_REMAINING_COMPLETE_TARGETS"
    assert row["selected_index"] is row["changed_choice"] is row["margin"]["value"] is None
    assert row["remaining_complete_target_count"] == 0 and len(row["objectives"]) == 6
    assert all(value["value"] is None for value in row["objectives"])
    assert report["available_omission_count"] == sum(value["count"] for value in report["selection_counts"]) == 4


def cash_window():
    returns = [[.5, -.4, 0., 0., 0.], [.04, .04, 0., 0., 0.], [.04, .04, 0., 0., 0.], [0.] * 5]
    family = [{"candidate_index": index, "threshold": threshold.THRESHOLDS[index],
               "execution": {"daily": [{"trading_day": day, "return": value, "trade_count": int(value != 0)}
                                        for day, value in zip(DAYS, values, strict=True)],
                             "metrics": {"total_return": math.prod(1 + value for value in values) - 1}}}
              for index, values in enumerate(returns)]
    return {"validation_days": DAYS, "family_results": family, "selected_index": 1}


def test_cash_ratio_compounding_day_reversal_cash_days_and_numeric_family_gate():
    window = cash_window()
    report = sensitivity._window_sensitivity(window, maximize=True, source_strategy=RECIPE, window_index=0)
    assert report["original"]["selected_index"] == 1  # Sum of daily returns incorrectly favors 0.
    assert [row["value"] for row in report["original"]["objectives"]] == pytest.approx([-.1, .0816, .0816, 0.])
    assert [row["selected_index"] for row in report["omissions"]] == [1, 0, 1, 1, 1]
    assert report["omissions"][0]["objectives"][0]["value"] == pytest.approx(-.4)
    assert report["omissions"][1]["objectives"][0]["value"] == .5
    assert report["omissions"][1]["margin"]["value"] == pytest.approx(.46)
    assert all(len(row["remaining_days"]) == 4 and row["remaining_complete_target_count"] is None
               for row in report["omissions"])
    assert report["selection_counts"] == [{"candidate_index": i, "count": count} for i, count in enumerate([1, 4, 0, 0])]
    # One nonfinite member must not silently turn into a smaller competition.
    member = window["family_results"][0]
    for row, value in zip(member["execution"]["daily"], [1e200, -1., 1e200, 0., 0.], strict=True):
        row["return"] = value
    member["execution"]["metrics"]["total_return"] = 1e200
    window["selected_index"] = 0
    failed = sensitivity._window_sensitivity(window, maximize=True, source_strategy=RECIPE, window_index=0)["omissions"][1]
    assert failed["status"] == "UNAVAILABLE" and failed["selected_index"] is None
    assert failed["objectives"][0]["unavailable_reason"] == "NUMERIC_OVERFLOW" and len(failed["objectives"]) == 4


def prohibit_recomputation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("recorded-only sensitivity accessed sources, fitted or replayed execution")
    for module, names in ((research, ("load_intraday_dataset", "_prepare_intraday_research", "_fit", "run_intraday_execution")),
                          (inner, ("_fit", "_evaluate", "run_intraday_execution")),
                          (threshold, ("_fit", "_evaluate", "run_intraday_execution")),
                          (execution, ("run_intraday_execution",))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def test_real_studies_all_original_windows_independent_objectives_without_sources_or_execution(
        inner_case, threshold_case, monkeypatch):
    prohibit_recomputation(monkeypatch)
    for snapshot, path, maximize, expected_reference in ((inner_case[4], inner_case[5], False, (1, 1)),
                                                       (threshold_case[4], threshold_case[5], True, (0, 1))):
        before, saved = path.read_bytes(), snapshot.as_dict()["report"]
        report = sensitivity.analyze_intraday_inner_objective_sensitivity(snapshot)
        assert report["status"] == "AVAILABLE" and report["evidence"]["scope"] == "RECORDED_FIXED_FIT_OBJECTIVE_DERIVATION"
        assert not any(report["evidence"][key] for key in ("source_reconstructed", "models_refitted", "execution_replayed"))
        assert tuple(report["source_selection"][key] for key in ("cost_index", "candidate_index")) == expected_reference
        assert [row["scope"] for row in report["windows"]] == ["OUTER_INNER"] * len(saved["outer_folds"]) + ["FINAL_DEV"]
        assert report["windows"][-1]["fold_index"] is report["windows"][-1]["fold_id"] is None
        originals = [row["inner"] for row in saved["outer_folds"]] + [saved["final_dev"]]
        for actual, original in zip(report["windows"], originals, strict=True):
            assert actual["fixed_evidence"] == original and actual["original"]["selected_index"] == original["selected_index"]
            assert [row["omitted_day"] for row in actual["omissions"]] == original["validation_days"]
            for row in actual["omissions"]:
                expected = []
                for member in original["family_results"]:
                    if maximize:
                        factors = [Fraction(1) + Fraction(value["return"]) for value in member["execution"]["daily"]
                                   if value["trading_day"] != row["omitted_day"]]
                        value = float(math.prod(factors) - 1)
                    else:
                        scores = {value["observation_key"]: value["score"] for value in member["predictions"]}
                        targets = [value for value in original["scored_targets"] if value["trading_day"] != row["omitted_day"]]
                        value = math.fsum((scores[value["observation_key"]] - value["value"]) ** 2 for value in targets) / len(targets)
                    expected.append(value)
                assert [value["value"] for value in row["objectives"]] == pytest.approx(expected, abs=1e-14)
                chooser = max if maximize else min
                assert row["selected_index"] == chooser(range(len(expected)), key=lambda i: expected[i])
            assert sum(row["count"] for row in actual["selection_counts"]) == 5
        assert path.read_bytes() == before
    with pytest.raises(ValueError, match="Q25 or Q31"):
        sensitivity.analyze_intraday_inner_objective_sensitivity(inner_case[1])


def test_installed_cli_needs_only_saved_study_and_recovers_after_missing_file(threshold_case, tmp_path):
    data, _, source_path, _, snapshot, path = threshold_case
    before = path.read_bytes()
    cli = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    command = [cli, "research-intraday-inner-objective-sensitivity", "--experiment"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    missing = subprocess.run([*command, str(tmp_path / "missing.json")], cwd=tmp_path, env=env,
                             text=True, capture_output=True, timeout=120)
    assert missing.returncode == 1 and json.loads(missing.stderr)["status"] == "FAILED"
    # These are this test session's synthetic files, restored immediately after
    # the process: only the immutable study is present during the CLI action.
    moved = []
    try:
        for original in (data.path, source_path):
            temporary = original.with_name(original.name + ".temporarily-away")
            original.rename(temporary)
            moved.append((original, temporary))
        result = subprocess.run([*command, str(path)], cwd=tmp_path, env=env,
                                text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)["report"]
        assert report["experiment_id"] == snapshot.experiment_id and report["status"] == "AVAILABLE"
        assert report["version"] == sensitivity.INTRADAY_INNER_OBJECTIVE_SENSITIVITY_VERSION
    finally:
        for original, temporary in reversed(moved):
            temporary.rename(original)
    assert path.read_bytes() == before


def test_unavailable_whole_source_cannot_expose_uncomputed_final_window(quadratic_dev_case, tmp_path, monkeypatch):
    _, plan, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(plan)
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = inner.run_intraday_inner_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    saved = study.as_dict()["report"]
    assert saved["status"] == "UNAVAILABLE" and saved["final_dev"]["unavailable_reason"] is None
    prohibit_recomputation(monkeypatch)
    report = sensitivity.analyze_intraday_inner_objective_sensitivity(study)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert report["unavailable_reasons"] == saved["unavailable_reasons"]
    assert report["windows"] == [] and report["sample"] is None
