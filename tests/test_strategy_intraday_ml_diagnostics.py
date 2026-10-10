"""Discriminating score intervals and the real fixed/Q25/Q31 source paths."""

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_vault.research import intraday_ml_diagnostics as diagnostics
from market_vault.research import intraday_research as research
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_prediction_quality import analyze_intraday_prediction_quality
from market_vault.research.strategy_experiment import write_strategy_experiment
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401
from test_strategy_intraday_inner_selection import inner_case  # noqa: F401
from test_strategy_intraday_threshold_selection import threshold_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def test_fixed_score_edges_paired_means_empty_bins_and_tail_coverage():
    scores = [-.001, 0, .0001, .0005, .0006, .001, .0011, .002, .003]
    expected_bins = [0, 0, 1, 1, 2, 2, 3, 3, 4]
    assert [diagnostics._bin_index(value) for value in scores] == expected_bins
    rows = [{"bin_index": index, "target_status": "COMPLETE", "target_value": score * 2,
             "scores": {"SELECTED": score}, "trading_day": "2025-01-02"}
            for score, index in zip(scores, expected_bins, strict=True)]
    # A high unscored READY tail changes the READY mean, not the paired mean.
    rows.append({"bin_index": 4, "target_status": "INCOMPLETE", "target_value": None,
                 "scores": {"SELECTED": .1}, "trading_day": "2025-01-03"})
    bins = diagnostics._score_bins(rows)
    assert sum(row["sample"]["prediction_count"] for row in bins) == 10
    assert sum(row["sample"]["complete_target_count"] for row in bins) == 9
    assert bins[4]["ready_mean_prediction"]["value"] == pytest.approx(.0515)
    assert bins[4]["metrics"]["mean_pred"]["value"] == .003
    assert bins[4]["metrics"]["mean_target"]["value"] == .006
    assert bins[4]["metrics"]["bias"]["value"] == -.003
    assert bins[0]["target_sign_counts"] == {"positive": 0, "zero": 1, "negative": 1}
    empty = diagnostics._score_bins([])
    assert len(empty) == 5 and all(row["sample"]["prediction_count"] == 0 for row in empty)
    assert all(row["ready_mean_prediction"]["value"] is None for row in empty)
    assert all(row["metrics"]["mean_target"]["value"] is None for row in empty)


def _quality_oracle(report, data):
    targets = {row["observation_key"]: row for row in data.as_dict()["report"]["targets"]}
    observations = {row["observation_key"]: row for row in data.as_dict()["report"]["observations"]}
    paired = [row for row in report["predictions"] if targets[row["observation_key"]]["status"] == "COMPLETE"]
    assert [row["observation_key"] for row in report["predictions"]] == report["context"]["validation_keys"]
    for fold in report["folds"]:
        training = [targets[key]["value"] for key in fold["training_keys"]]
        expected_mean = math.fsum(training) / len(training)
        assert fold["training_target_mean"] == expected_mean
        assert fold["model"]["training_keys"] == fold["training_keys"]
        assert all(targets[key]["actual_label_end_time"] < fold["training_boundary"] for key in fold["training_keys"])
        assert all(observations[key]["status"] == "READY" for key in fold["training_keys"])
        for row in report["predictions"]:
            if row["fold_id"] == fold["fold_id"]:
                assert row["scores"]["TRAIN_MEAN"] == expected_mean
                assert row["decision"] == ("LONG" if row["scores"]["SELECTED"] > fold["strategy"]["threshold"] else "FLAT")
    for forecast in report["forecasts"]:
        name, metrics = forecast["forecast"], forecast["metrics"]
        errors = [row["scores"][name] - targets[row["observation_key"]]["value"] for row in paired]
        mse = math.fsum(value * value for value in errors) / len(errors)
        assert metrics["mse"]["value"] == pytest.approx(mse, abs=1e-18)
        assert metrics["mae"]["value"] == pytest.approx(math.fsum(abs(value) for value in errors) / len(errors))
        assert metrics["bias"]["value"] == pytest.approx(math.fsum(errors) / len(errors), abs=1e-18)
    assert report["sample"]["complete_target_count"] == len(paired) < report["sample"]["prediction_count"]
    assert sum(row["sample"]["prediction_count"] for row in report["bins"]) == len(report["predictions"])
    assert all(row["trading_day"] not in report["context"]["split"]["TEST"] for row in report["predictions"])


def test_real_fixed_and_selected_procedures_one_q5_training_oracle_and_q31_score_invariance(
        quadratic_dev_case, inner_case, threshold_case, monkeypatch):
    data, _, _, ordinary, ordinary_path, _ = quadratic_dev_case
    _, _, inner_source_path, _, inner, inner_path = inner_case
    _, _, _, _, threshold, threshold_path = threshold_case
    paths = [ordinary_path, inner_source_path, inner_path, threshold_path]
    original = {path: path.read_bytes() for path in paths}
    cases = [(ordinary, 0, "ORDINARY"), (ordinary, 1, "ORDINARY"),
             (inner, 0, "INNER_MODEL_SELECTION"), (threshold, 0, "ECONOMIC_THRESHOLD_SELECTION")]
    outputs = []
    load = research.load_intraday_dataset
    for source, candidate, kind in cases:
        calls = []
        def loaded(*args, **kwargs):
            calls.append(1)
            return load(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(research, "load_intraday_dataset", loaded)
            report = diagnostics.analyze_intraday_ml_prediction_quality(source, candidate_index=candidate)
        assert calls == [1] and report["source_kind"] == kind
        assert report["evidence"]["execution_replayed"] == (kind != "ORDINARY")
        _quality_oracle(report, data)
        outputs.append(report)
    assert outputs[2]["source_selection"]["cost_index"] == 1
    assert outputs[2]["source_selection"]["candidate_index"] == 1
    assert outputs[3]["forecasts"] == outputs[1]["forecasts"]
    assert outputs[3]["bins"] == outputs[1]["bins"]
    assert [row["decision"] for row in outputs[3]["predictions"]] != [row["decision"] for row in outputs[1]["predictions"]]
    for fold, saved in zip(outputs[2]["folds"], inner.as_dict()["report"]["outer_folds"], strict=True):
        assert fold["model"] == saved["refit"]["model"]
        assert fold["strategy"] == saved["refit"]["strategy"]
    # The old Q21 schema and numerical metrics remain intact.
    old = analyze_intraday_prediction_quality(ordinary)
    assert old["version"] == "market-vault-intraday-prediction-quality-v1"
    assert old["forecasts"][0]["metrics"] == outputs[0]["forecasts"][0]["metrics"]
    assert all(path.read_bytes() == original[path] for path in paths)


def test_real_cli_relocation_and_failed_source_recovery(threshold_case, tmp_path):
    data, _, _, _, _, path = threshold_case
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(data.path.read_bytes())
    before = path.read_bytes()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    cli = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    command = [cli, "research-intraday-ml-prediction-quality",
               "--experiment", str(path), "--intraday-data"]
    failed = subprocess.run([*command, str(tmp_path / "missing.json")], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert failed.returncode == 1 and json.loads(failed.stderr)["status"] == "FAILED"
    result = subprocess.run([*command, str(relocated)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)["report"]
    assert report["status"] == "AVAILABLE" and report["source_locator"]["used"] == str(relocated)
    assert report["source_locator"]["override_used"]
    assert report["sample"]["prediction_count"] > report["sample"]["complete_target_count"]
    assert path.read_bytes() == before


def test_reconstruction_rejects_wrong_source_before_fitting_and_complete_procedure_mismatch(
        threshold_case, monkeypatch):
    _, _, _, _, snapshot, _ = threshold_case
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("invalid indices must fail before Q5"))
        for ci, si in ((True, 0), (0, -1), (1, 0)):
            with pytest.raises(ValueError):
                diagnostics.analyze_intraday_ml_prediction_quality(snapshot, cost_index=ci, candidate_index=si)
    evaluate = diagnostics.threshold._evaluate
    def changed(*args, **kwargs):
        report = deepcopy(evaluate(*args, **kwargs))
        report["final_dev"]["selected_index"] = (report["final_dev"]["selected_index"] + 1) % 4
        return report
    monkeypatch.setattr(diagnostics.threshold, "_evaluate", changed)
    with pytest.raises(ValueError, match="complete saved selection procedure"):
        diagnostics.analyze_intraday_ml_prediction_quality(snapshot)


def test_unavailable_study_preserves_reasons_without_partial_scores_or_source_read(quadratic_dev_case, tmp_path, monkeypatch):
    _, plan, _, _, _, _ = quadratic_dev_case
    plan = deepcopy(plan)
    plan["walk_forward"]["minimum_train_days"] = 14
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    study = diagnostics.inner.run_intraday_inner_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    assert study.as_dict()["report"]["status"] == "UNAVAILABLE"
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **k: pytest.fail("unavailable analysis read Q5"))
    monkeypatch.setattr(research, "_fit", lambda *a, **k: pytest.fail("unavailable analysis fitted a model"))
    report = diagnostics.analyze_intraday_ml_prediction_quality(study)
    assert report["status"] == "UNAVAILABLE" and report["unavailable_reason"] == "SOURCE_STUDY_UNAVAILABLE"
    assert report["unavailable_reasons"] == study.as_dict()["report"]["unavailable_reasons"]
    assert report["predictions"] == report["folds"] == report["bins"] == report["forecasts"] == []
    assert report["sample"] is None
