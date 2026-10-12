"""One real shared-source run, exact legacy oracles and individual save recovery."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from market_vault import cli
from market_vault import intraday_procedure_suite_cli as suite_cli
from market_vault.research import intraday_data as q5
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_procedure_suite as suite
from market_vault.research import intraday_research as research
from market_vault.research import intraday_selection_fit as fit_reuse
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research import strategy_experiment as experiments
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.intraday_selection_source import _PreparedSelectionSource
from market_vault.research.strategy_experiment import StrategyExperiment, canonical_json, write_strategy_experiment
from test_intraday_experiment import signed
from test_strategy_intraday_ml import quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
RUNS = (inner.run_intraday_inner_selection, threshold.run_intraday_threshold_selection,
        joint.run_intraday_joint_selection)


def _arguments(source, *, cost=0, candidate=0):
    return {"expected_experiment_id": source.experiment_id, "cost_index": cost, "candidate_index": candidate,
        "expected_candidate_id": source.as_dict()["report"]["groups"][cost]["results"][candidate]["candidate_id"]}


def _physical_fit_counts(monkeypatch):
    """One solver call for either representation, with ordinary work separate."""
    counts, requests, depth = {"ordinary_fits": 0, "procedure_fits": 0}, [], 0
    solve, evaluate = research._fit, research._evaluate_intraday_research
    def solved(X, y, alpha, **kwargs):
        counts["ordinary_fits" if depth else "procedure_fits"] += 1
        if not depth:
            requests.append((len(X), len(X[0]), alpha))
        return solve(X, y, alpha, **kwargs)
    def ordinary(*args, **kwargs):
        nonlocal depth
        depth += 1
        try:
            return evaluate(*args, **kwargs)
        finally:
            depth -= 1
    monkeypatch.setattr(research, "_fit", solved)
    monkeypatch.setattr(research, "_evaluate_intraday_research", ordinary)
    return counts, requests


def _ridge_work_counts(monkeypatch):
    from market_vault.research import intraday_models as models, ridge_baseline as ridge

    counts = {"preparations": 0, "solves": 0, "quadratic_expansions": 0}
    for module, name, key in ((ridge, "_standardize", "preparations"),
            (ridge, "_solve", "solves"), (models, "input_stats", "quadratic_expansions")):
        original = getattr(module, name)
        def recorded(*args, _key=key, _original=original, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, recorded)
    return counts


def _cache_costs(monkeypatch):
    costs = {"key_seconds": 0., "model_copy_seconds": 0., "requests": 0}
    key, copy = fit_reuse._fit_key, fit_reuse.deepcopy
    def keyed(*args, **kwargs):
        start = time.perf_counter()
        try:
            return key(*args, **kwargs)
        finally:
            costs["key_seconds"] += time.perf_counter() - start
            costs["requests"] += 1
    def copied(value):
        start = time.perf_counter()
        try:
            return copy(value)
        finally:
            costs["model_copy_seconds"] += time.perf_counter() - start
    monkeypatch.setattr(fit_reuse, "_fit_key", keyed)
    monkeypatch.setattr(fit_reuse, "deepcopy", copied)
    return costs


@pytest.fixture(scope="session")
def suite_source(quadratic_dev_case, tmp_path_factory):
    data, comparison, _, _, _, _ = quadratic_dev_case
    plan = {"plan_schema_version": research.INTRADAY_DIAGNOSTICS_PLAN_V2_VERSION,
        "comparison_plan": comparison, "strategy_name": "Quadratic",
        "parameter_axes": [{"parameter": "alpha", "values": [.5, 2.]}],
        "cost_scenarios": [{"commission_bps": 0, "slippage_bps": 0}, {"commission_bps": 10, "slippage_bps": 5}]}
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path_factory.mktemp("procedure-suite") / "source.json").path
    return SimpleNamespace(data=data, source=source, path=path, args=_arguments(source, cost=1, candidate=1))


def test_real_three_run_canonical_equivalence_and_single_strict_preparation(suite_source, monkeypatch):
    case = suite_source
    before = {path: path.read_bytes() for path in (case.path, case.data.path)}
    fits, _ = _physical_fit_counts(monkeypatch)
    overhead = _cache_costs(monkeypatch)
    work = _ridge_work_counts(monkeypatch)
    calls = {key: 0 for key in ("source_read", "q5_read", "q5_verify", "prepare", "reconstruct")}
    for module, name, key in ((experiments, "_read_file", "source_read"), (q5, "_read", "q5_read"),
            (q5, "verify_intraday_dataset", "q5_verify"), (research, "_prepare_intraday_research", "prepare"),
            (research, "_evaluate_intraday_research", "reconstruct")):
        original = getattr(module, name)
        def recorded(*args, _key=key, _original=original, **kwargs):
            calls[_key] += 1
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, recorded)
    metadata = {"name": "Same captured study", "notes": "Fixed three procedures"}
    start = time.perf_counter()
    independent = tuple(run(case.path, **case.args, **metadata) for run in RUNS)
    independent_seconds = time.perf_counter() - start
    independent_calls = dict(calls)
    independent_fits = dict(fits)
    independent_work = dict(work)
    folds = len(case.source.as_dict()["report"]["context"]["folds"])
    assert independent_fits["procedure_fits"] == 13 * (folds + 1) + 2 * folds
    assert independent_work["preparations"] == independent_work["solves"] == sum(independent_fits.values())
    assert independent_calls == dict.fromkeys(calls, 3)
    calls.update(dict.fromkeys(calls, 0))
    fits.update(dict.fromkeys(fits, 0))
    work.update(dict.fromkeys(work, 0))
    # This private injection is Q49's identical single-preparation path. No
    # public option can turn source verification or fit reuse on/off.
    with monkeypatch.context() as patch:
        patch.setattr(suite, "_SelectionFitCache", lambda prepared: None)
        start = time.perf_counter()
        uncached = suite.run_intraday_procedure_suite(case.path, **case.args, **metadata)
        uncached_seconds = time.perf_counter() - start
    uncached_fits = dict(fits)
    uncached_work = dict(work)
    assert calls == dict.fromkeys(calls, 1)
    assert uncached_fits["procedure_fits"] == independent_fits["procedure_fits"]
    assert uncached_fits["ordinary_fits"] * 3 == independent_fits["ordinary_fits"]
    assert uncached_work["preparations"] == uncached_work["solves"] == sum(uncached_fits.values())
    assert [value.content for value in uncached] == [value.content for value in independent]
    calls.update(dict.fromkeys(calls, 0))
    fits.update(dict.fromkeys(fits, 0))
    work.update(dict.fromkeys(work, 0))
    owners, caches = [], []
    def created(prepared):
        owners.append(prepared)
        cache = fit_reuse._SelectionFitCache(prepared)
        caches.append(cache)
        return cache
    monkeypatch.setattr(suite, "_SelectionFitCache", created)
    start = time.perf_counter()
    combined = suite.run_intraday_procedure_suite(case.path, **case.args, **metadata)
    suite_seconds = time.perf_counter() - start
    combined_fits = dict(fits)
    combined_work = dict(work)
    assert type(combined) is tuple and len(combined) == 3
    assert calls == dict.fromkeys(calls, 1)
    assert combined_fits["ordinary_fits"] == uncached_fits["ordinary_fits"]
    assert combined_fits["procedure_fits"] <= uncached_fits["procedure_fits"] - 6 * (folds + 1)
    assert combined_work == {
        "preparations": combined_fits["ordinary_fits"] + 2 * (folds + 1),
        "solves": sum(combined_fits.values()),
        "quadratic_expansions": combined_fits["ordinary_fits"] + 4 * (folds + 1),
    }
    assert [value.content for value in combined] == [value.content for value in independent]
    assert [value.experiment_id for value in combined] == [value.experiment_id for value in independent]
    for snapshot, family_size in zip(combined, (6, 4, 24), strict=True):
        report = snapshot.as_dict()["report"]
        assert report["status"] == "AVAILABLE"
        assert all(len(window["family_results"]) == family_size
                   for window in [*(row["inner"] for row in report["outer_folds"]), report["final_dev"]])
    calls.update(dict.fromkeys(calls, 0))
    fits.update(dict.fromkeys(fits, 0))
    work.update(dict.fromkeys(work, 0))
    start = time.perf_counter()
    repeated = suite.run_intraday_procedure_suite(case.path, **case.args, **metadata)
    repeated_seconds = time.perf_counter() - start
    assert calls == dict.fromkeys(calls, 1) and fits == combined_fits
    assert work == combined_work
    assert owners[0] is not owners[1] and caches[0] is not caches[1]
    assert [value.content for value in repeated] == [value.content for value in combined]
    # Equal source bytes do not make another action's cache admissible.
    for (module, *_), snapshot in zip(suite._MEMBERS, combined, strict=True):
        with pytest.raises(ValueError, match="another prepared selection action"):
            module._evaluate(case.source.as_dict(), snapshot.as_dict()["plan"],
                prepared_source=owners[0], fit_cache=caches[1])
    assert calls == dict.fromkeys(calls, 1) and fits == combined_fits
    assert all(path.read_bytes() == content for path, content in before.items())
    print(json.dumps({"folds": folds, "source_kind": "QUADRATIC_RIDGE", "source_alpha": 2.,
        "independent_seconds": round(independent_seconds, 3), "q49_seconds": round(uncached_seconds, 3),
        "suite_seconds": round(suite_seconds, 3), "repeated_suite_seconds": round(repeated_seconds, 3),
        "independent_calls": independent_calls, "suite_calls": calls,
        "independent_fits": independent_fits, "q49_fits": uncached_fits, "suite_fits": combined_fits,
        "independent_ridge_work": independent_work, "q49_ridge_work": uncached_work,
        "suite_ridge_work": combined_work,
        "two_suite_cache_costs": overhead,
        "canonical_bytes_equal": True, "experiment_ids": [value.experiment_id for value in combined]}))


def test_real_linear_outside_family_reuses_inner_models_without_changing_q49(quadratic_dev_case, tmp_path, monkeypatch):
    data, original = quadratic_dev_case[:2]
    plan = deepcopy(original)
    plan["strategies"] = [{"kind": "RIDGE", "name": "Outside family", "alpha": 1000., "threshold": -.0005}]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "linear-source.json").path
    args = _arguments(source)
    fits, requests = _physical_fit_counts(monkeypatch)
    overhead = _cache_costs(monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(suite, "_SelectionFitCache", lambda prepared: None)
        start = time.perf_counter()
        baseline = suite.run_intraday_procedure_suite(path, **args)
        baseline_seconds = time.perf_counter() - start
    baseline_fits = dict(fits)
    fits.update(dict.fromkeys(fits, 0))
    requests.clear()
    start = time.perf_counter()
    reused = suite.run_intraday_procedure_suite(path, **args)
    reused_seconds = time.perf_counter() - start
    folds = len(source.as_dict()["report"]["context"]["folds"])
    assert baseline_fits["procedure_fits"] == 13 * (folds + 1) + 2 * folds
    assert fits["ordinary_fits"] == baseline_fits["ordinary_fits"]
    assert fits["procedure_fits"] <= 7 * (folds + 1) + 2 * folds
    assert fits["procedure_fits"] < baseline_fits["procedure_fits"]
    assert sum(alpha == 1000. for _, _, alpha in requests) == folds + 1
    assert {width for _, width, _ in requests} == {2, 5}  # Real linear and quadratic solves.
    assert [value.content for value in reused] == [value.content for value in baseline]
    assert [value.experiment_id for value in reused] == [value.experiment_id for value in baseline]
    print(json.dumps({"folds": folds, "source_kind": "RIDGE", "source_alpha": 1000.,
        "q49_seconds": round(baseline_seconds, 3), "suite_seconds": round(reused_seconds, 3),
        "q49_fits": baseline_fits, "suite_fits": fits, "cache_costs": overhead,
        "canonical_bytes_equal": True}))


def _numeric_cache_case():
    # This small private owner is only for raw-fit discrimination; the tests
    # above exercise actual strict Q5/source admission and action ownership.
    owner = _PreparedSelectionSource(b"{}", b"{}", research._PreparedIntradayResearch(None, {}, {}, (), ()))
    rows = tuple(({"observation_key": f"train-{index}", "features": {"x": float(index), "y": float(index % 3)}},
                  {"value": (index + 1) * .001}) for index in range(6))
    observations = tuple({"observation_key": f"predict-{index}", "trading_day": "2025-01-03", "slot": index,
        "decision_time": f"2025-01-03T14:{35 + 5 * index}:00+00:00", "features": {"x": float(index + 3), "y": .5}}
        for index in range(2))
    return owner, {"rows": rows, "observations": observations, "features": ["x", "y"],
        "recipe": {"kind": "RIDGE", "name": "Fixed", "alpha": 1., "threshold": 0.},
        "boundary": "2025-01-03T14:30:00+00:00"}


@pytest.mark.parametrize("kind", ["RIDGE", "QUADRATIC_RIDGE"])
def test_alpha_family_prepares_once_and_solves_each_alpha_with_fresh_action_state(kind, monkeypatch):
    owner, inputs = _numeric_cache_case()
    cases = [{**inputs, "recipe": {**inputs["recipe"], "kind": kind, "alpha": alpha}}
             for alpha in (.1, 1., 10.)]
    expected = [canonical_json(inner._fit(**case)) for case in cases]
    work = _ridge_work_counts(monkeypatch)
    cache = fit_reuse._SelectionFitCache(owner)
    fitter = cache.fitter(owner, inner._fit)
    actual = [canonical_json(fitter(**case)) for case in cases]
    assert actual == expected
    assert work == {"preparations": 1, "solves": 3,
                    "quadratic_expansions": 3 if kind == "QUADRATIC_RIDGE" else 0}
    assert canonical_json(fitter(**cases[0])) == expected[0]
    assert work["solves"] == 3  # Existing alpha-specific complete-fit reuse.
    another_owner, _ = _numeric_cache_case()
    another = fit_reuse._SelectionFitCache(another_owner).fitter(another_owner, inner._fit)
    assert canonical_json(another(**cases[0])) == expected[0]
    assert work["preparations"] == 2 and work["solves"] == 4


def test_failed_solver_does_not_publish_a_cached_model(monkeypatch):
    from market_vault.research.ridge_baseline import RidgeBaselineError

    owner, inputs = _numeric_cache_case()
    inputs["recipe"]["alpha"] = 1e-20
    for row, _ in inputs["rows"]:
        row["features"]["y"] = .1
    cache = fit_reuse._SelectionFitCache(owner)
    fitter = cache.fitter(owner, inner._fit)
    work = _ridge_work_counts(monkeypatch)
    for attempt in (1, 2):
        with pytest.raises(RidgeBaselineError, match="singular"):
            fitter(**inputs)
        assert cache._fits == {}
        assert work["solves"] == attempt
    inputs["recipe"]["alpha"] = 1.
    assert canonical_json(fitter(**inputs)) == canonical_json(inner._fit(**inputs))


def test_fit_identity_uses_actual_ordered_values_cutoff_and_numeric_encoding(monkeypatch):
    owner, inputs = _numeric_cache_case()
    cache = fit_reuse._SelectionFitCache(owner)
    fitter = cache.fitter(owner, inner._fit)
    fits, _ = _physical_fit_counts(monkeypatch)
    work = _ridge_work_counts(monkeypatch)
    original = fitter(**inputs)
    assert fits["procedure_fits"] == 1
    assert canonical_json(fitter(**deepcopy(inputs))) == canonical_json(original)
    assert fits["procedure_fits"] == 1
    for change in ("training_value", "training_encoding", "target_value", "training_key", "training_order", "features_order",
                   "cutoff", "prediction_value", "prediction_key", "prediction_order", "prediction_support",
                   "alpha_encoding", "representation"):
        altered = deepcopy(inputs)
        if change == "training_value":
            altered["rows"][0][0]["features"]["x"] += .25
        elif change == "training_encoding":
            altered["rows"][0][0]["features"]["x"] = 0
        elif change == "target_value":
            altered["rows"][0][1]["value"] += .01
        elif change == "training_key":
            altered["rows"][0][0]["observation_key"] += "-changed"
        elif change == "training_order":
            altered["rows"] = altered["rows"][::-1]
        elif change == "features_order":
            altered["features"].reverse()
        elif change == "cutoff":
            altered["boundary"] = "2025-01-04T14:30:00+00:00"
        elif change == "prediction_value":
            altered["observations"][0]["features"]["x"] += .25
        elif change == "prediction_key":
            altered["observations"][0]["observation_key"] += "-changed"
        elif change == "prediction_order":
            altered["observations"] = altered["observations"][::-1]
        elif change == "prediction_support":
            altered["observations"] = altered["observations"][:1]
        elif change == "alpha_encoding":
            altered["recipe"]["alpha"] = 1
        else:
            altered["recipe"]["kind"] = "QUADRATIC_RIDGE"
        before = fits["procedure_fits"]
        before_preparations = work["preparations"]
        actual = fitter(**altered)
        assert fits["procedure_fits"] == before + 1, change
        assert work["preparations"] == before_preparations + (change != "alpha_encoding"), change
        expected = inner._fit(**altered)
        assert canonical_json(actual) == canonical_json(expected), change
        if change == "alpha_encoding":
            assert actual[0]["alpha"] == original[0]["alpha"]
            assert type(actual[0]["alpha"]) is int and type(original[0]["alpha"]) is float
            assert actual[0]["model_id"] != original[0]["model_id"]


@pytest.mark.parametrize("kind", ["RIDGE", "QUADRATIC_RIDGE"])
def test_shared_raw_scores_keep_fresh_threshold_actions_metadata_and_model_isolation(kind, monkeypatch):
    owner, inputs = _numeric_cache_case()
    inputs["recipe"]["kind"] = kind
    cache = fit_reuse._SelectionFitCache(owner)
    fitter = cache.fitter(owner, inner._fit)
    fits, _ = _physical_fit_counts(monkeypatch)
    first_model, first_predictions = fitter(**inputs)
    saved = canonical_json((first_model, first_predictions))
    other = deepcopy(inputs)
    other["recipe"].update(name="Another threshold", threshold=1.)
    other["observations"][0]["decision_time"] = "2025-01-03T14:36:00+00:00"
    second_model, second_predictions = fitter(**other)
    assert fits["procedure_fits"] == 1
    assert [row["score"] for row in first_predictions] == [row["score"] for row in second_predictions]
    assert all(row["target"] == "LONG" for row in first_predictions)
    assert all(row["target"] == "FLAT" for row in second_predictions)
    assert second_predictions[0]["decision_time"] == other["observations"][0]["decision_time"]
    assert first_model == second_model and first_model is not second_model
    first_model.get("ridge_model", first_model)["coefficients"][0] = 999
    first_model.get("ridge_model", first_model)["standardized_coefficients"][0] = 999
    first_model.get("ridge_model", first_model)["target_mean"] = 999
    first_model["training_keys"].append("mutated")
    first_predictions[0].update(score=999, target="FLAT")
    assert canonical_json(fitter(**inputs)) == saved
    assert fits["procedure_fits"] == 1
    assert second_model.get("ridge_model", second_model)["coefficients"][0] != 999
    assert second_model.get("ridge_model", second_model)["standardized_coefficients"][0] != 999
    assert second_model.get("ridge_model", second_model)["target_mean"] != 999
    assert "mutated" not in second_model["training_keys"]


def test_captured_identity_and_complete_source_mismatch_fail_before_selection(suite_source, monkeypatch):
    case = suite_source
    def forbidden(*args, **kwargs):
        pytest.fail("invalid captured source reached Q5 or procedure selection")
    with monkeypatch.context() as patch:
        patch.setattr(research, "load_intraday_dataset", forbidden)
        for field in ("expected_experiment_id", "expected_candidate_id"):
            with pytest.raises(ValueError, match="captured identity"):
                suite.evaluate_intraday_procedure_suite(case.source, source_experiment_path=case.path,
                    **{**case.args, field: "a" * 64})
        with pytest.raises(ValueError, match="immutable"):
            suite.evaluate_intraday_procedure_suite(case.source.as_dict(), source_experiment_path=case.path, **case.args)
    # An unselected candidate's hidden price is part of the complete replay.
    root = case.source.as_dict()
    root["report"]["groups"][0]["results"][0]["execution"]["ledger"][0]["mark_price"] += .25
    changed = StrategyExperiment(signed(root))
    for module in (inner, threshold, joint):
        monkeypatch.setattr(module, "_select", forbidden)
    with pytest.raises(ValueError, match="complete ordinary source reconstruction"):
        suite.evaluate_intraday_procedure_suite(changed, source_experiment_path=case.path,
            **{**case.args, "expected_experiment_id": changed.experiment_id})


@pytest.fixture(scope="session")
def unavailable_suite_source(quadratic_dev_case, tmp_path_factory):
    """A real Q5 source with an explicitly insufficient first inner history."""
    data, original = quadratic_dev_case[:2]
    root = tmp_path_factory.mktemp("procedure-suite-short-history")
    plan = deepcopy(original)
    plan["walk_forward"]["minimum_train_days"] = 10
    plan["strategies"] = [plan["strategies"][0]]
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=root / "source.json").path
    return SimpleNamespace(data=data, source=source, path=path, args=_arguments(source))


def test_captured_source_not_reopened_and_independent_unavailability(unavailable_suite_source, monkeypatch):
    case = unavailable_suite_source
    monkeypatch.setattr(experiments, "_read_file", lambda *a, **k: pytest.fail("reopened captured ordinary source"))
    studies = suite.evaluate_intraday_procedure_suite(case.source, source_experiment_path=case.path, **case.args)
    reports = [snapshot.as_dict()["report"] for snapshot in studies]
    assert len(reports) == 3
    for report in reports:
        assert report["status"] == "UNAVAILABLE"
        assert report["unavailable_reasons"] == [
            {"scope": "OUTER_FOLD", "fold_index": 0, "reason": "INSUFFICIENT_INNER_HISTORY"}]
        assert report["selected_account"] is None
        assert len(report["outer_folds"]) == len(case.source.as_dict()["report"]["context"]["folds"])
        assert all(record["application" if "application" in record else "refit"] is None
                   and record["inner"]["family_results"] == [] for record in report["outer_folds"])
        assert report["final_dev"]["family_results"] == []
    assert all(report["source_experiment"] == case.source.as_dict() for report in reports)


def _cli_arguments(case):
    return ["research-intraday-procedure-suite", "--source-experiment", str(case.path),
        "--expected-experiment-id", case.args["expected_experiment_id"], "--cost-index", str(case.args["cost_index"]),
        "--candidate-index", str(case.args["candidate_index"]), "--expected-candidate-id", case.args["expected_candidate_id"]]


def test_actual_cli_partial_save_reports_successful_files_and_retry_reuses_bytes(
        unavailable_suite_source, tmp_path, monkeypatch, capsys):
    case = unavailable_suite_source
    paths = [tmp_path / f"{name}.json" for name in suite.PROCEDURE_ORDER]
    # A different valid existing artifact is a real no-overwrite conflict.
    write_strategy_experiment(case.source, path=paths[1])
    conflict = paths[1].read_bytes()
    arguments = _cli_arguments(case)
    for name, path in zip(suite.PROCEDURE_ORDER, paths, strict=True):
        arguments.extend([f"--{name.lower()}-experiment", str(path)])
    console = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    process = subprocess.run([console, "--settings", str(tmp_path / "absent-settings.yaml"), *arguments],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=120)
    assert process.returncode == 1 and process.stdout == "", process.stderr
    result = json.loads(process.stderr)
    assert result["status"] == "FAILED" and "existing experiment differs" in result["error"]
    assert [row["procedure"] for row in result["studies"]] == list(suite.PROCEDURE_ORDER)
    assert [row["procedure"] for row in result["saved_experiments"]] == ["Q25"]
    assert result["saved_experiments"][0]["created_new_file"]
    assert result["failed_save"] == {"procedure": "Q31", "path": str(paths[1])}
    assert result["unattempted_saves"] == [{"procedure": "Q36", "path": str(paths[2])}]
    assert paths[1].read_bytes() == conflict and not paths[2].exists()
    first_bytes = paths[0].read_bytes()
    studies = tuple(StrategyExperiment(canonical_json(row["study"])) for row in result["studies"])
    assert studies[0].content == first_bytes
    # The real run above proves CLI evaluation. Reuse its immutable outputs to
    # isolate retry/save behavior without fitting the same three studies again.
    monkeypatch.setattr(suite_cli, "run_intraday_procedure_suite", lambda *a, **k: studies)
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: pytest.fail("loaded settings"))
    replacement = tmp_path / "q31-new.json"
    arguments[arguments.index("--q31-experiment") + 1] = str(replacement)
    assert cli.main(arguments) == 0
    retried = json.loads(capsys.readouterr().out)
    assert retried["status"] == "SUCCESS"
    assert [row["created_new_file"] for row in retried["saved_experiments"]] == [False, True, True]
    assert paths[0].read_bytes() == first_bytes and paths[1].read_bytes() == conflict
    assert [experiments.load_strategy_experiment(path).content for path in (paths[0], replacement, paths[2])] == [
        snapshot.content for snapshot in studies]

    # A completed calculation can still fail while publishing stdout. Its
    # error envelope must agree with the nonzero exit code.
    def unavailable_stdout(*values, **options):
        if options.get("file") is not sys.stderr:
            raise OSError("stdout unavailable")
        print(*values, **options)
    monkeypatch.setattr(suite_cli, "print", unavailable_stdout, raising=False)
    assert cli.main(_cli_arguments(case)) == 1
    output_error = json.loads(capsys.readouterr().err)
    assert output_error["status"] == "FAILED" and output_error["error"] == "stdout unavailable"
    assert len(output_error["studies"]) == 3
