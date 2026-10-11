"""Q38 full-recipe Freeze, one independent TEST fit and saved-source boundaries."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, timedelta
from fractions import Fraction
import json
from math import fsum, sqrt
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import cross_day_helpers as cd
from market_vault.research import intraday_final_test as final
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_research as research
from market_vault.research.intraday_data import (
    build_intraday_dataset, digest, json_values, write_intraday_dataset,
)
from market_vault.research.intraday_experiment import create_intraday_experiment
from market_vault.research.strategy_experiment import (
    StrategyExperiment, canonical_json, load_strategy_experiment,
    replay_strategy_experiment, write_strategy_experiment,
)
from test_strategy_intraday_joint_selection import joint_case, quadratic_dev_case  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]


def bind(value, key):
    value[key] = digest({name: item for name, item in value.items() if name != key})


def signed_selection(root):
    root["report"]["plan_sha256"] = digest(root["plan"])
    bind(root["report"], "selection_id")
    bind(root, "experiment_id")
    return canonical_json(root)


@pytest.fixture(scope="session")
def joint_quadratic_case(tmp_path_factory):
    """Public Q5 -> Q36: a genuine quadratic economic winner, with 30 fit rows.

    The complete observations have x=-.02, 0, .02 in equal proportions and
    y=50*x*x-.005. Linear models buy every complete row; quadratic models
    avoid the losing zero-x days. Fees and all READY session tails are real.
    """
    root = tmp_path_factory.mktemp("joint-quadratic")
    entries, days, bars = [], [], []
    day = date(2025, 2, 3)
    while len(days) < 33:
        closed = day.weekday() >= 5 or day == date(2025, 2, 17)
        entries.append((day.isoformat(), "C" if closed else "N"))
        if not closed:
            days.append(day.isoformat())
        day += timedelta(days=1)
    for index, day in enumerate(days):
        x = (-.02, 0., .02)[index % 3]
        y = 50 * x * x - .005
        for slot in range(13):
            price = 100 * (1 + x) if slot == 4 else 100 * (1 + y) if slot == 7 else 100.
            bars.append(cd.bar(day, slot, interval="30m", code="US.SPY", open=price, close=price))
    canonical = cd.build(root, bars, interval="30m")
    data = build_intraday_dataset({"plan_schema_version": "market-vault-intraday-data-plan-v1",
        "canonical_build_dirs": [str(canonical.build_path)], "schedule": json_values(asdict(cd.schedule(entries))),
        "symbol": "US.SPY", "interval": "30m", "preset": "LIGHT_TECHNICAL", "stride_bars": 8,
        "target_horizon_bars": 3, "dataset_as_of": cd.AS_OF.isoformat()})
    data = replace(data, path=write_intraday_dataset(data, path=root / "intraday.json"))
    plan = research.default_intraday_research_plan(data, commission_bps=10, slippage_bps=5)
    plan["feature_fields"] = ["return_2"]
    plan["strategies"] = [{"kind": "RIDGE", "name": "Fixed linear reference", "alpha": 2., "threshold": -1.}]
    plan["split"] = {"train_end_day": days[19], "validation_end_day": days[29], "test_end_day": days[32]}
    plan["execution"]["max_hold_bars"] = 2
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    source_path = write_strategy_experiment(source, path=root / "source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    args = {"expected_experiment_id": source.experiment_id, "cost_index": 0, "candidate_index": 0,
            "expected_candidate_id": candidate["candidate_id"]}
    study = joint.run_intraday_joint_selection(source_path, **args)
    study_path = write_strategy_experiment(study, path=root / "joint.json").path
    return data, source, source_path, args, study, study_path, {}


@pytest.fixture(scope="session")
def joint_final_case(joint_case, joint_quadratic_case, tmp_path_factory):
    root = tmp_path_factory.mktemp("joint-final")
    cases = {}
    blocked = lambda *a, **kw: pytest.fail("Freeze/Open or normal TEST rebuilt development evidence")
    for name, case in (("ridge", joint_case), ("quadratic", joint_quadratic_case)):
        data, source, source_path, args, study, study_path, _ = case
        before = source_path.read_bytes(), study_path.read_bytes()
        with pytest.MonkeyPatch.context() as patch:
            for module, attribute in ((final, "load_intraday_dataset"), (final, "run_intraday_execution"),
                    (final, "fit_quadratic_rows"), (research, "load_intraday_dataset"), (research, "_fit"),
                    (research, "run_intraday_execution"), (joint, "_fit"), (joint, "_evaluate"),
                    (joint, "_select"), (joint, "run_intraday_execution")):
                patch.setattr(module, attribute, blocked)
            selection = final.freeze_intraday_joint_selection(study_path, expected_experiment_id=study.experiment_id)
            selection_path = write_strategy_experiment(selection, path=root / f"{name}-selection.json").path
            assert load_strategy_experiment(selection_path).content == selection.content
        calls = {"loads": 0, "fits": []}
        loader, fitter = final.load_intraday_dataset, research._fit
        def load(value):
            calls["loads"] += 1
            return loader(value)
        def fit(X, y, alpha):
            calls["fits"].append((len(X), len(X[0]), alpha))
            return fitter(X, y, alpha)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(final, "load_intraday_dataset", load)
            patch.setattr(research, "_fit", fit)
            for module, attribute in ((research, "load_intraday_dataset"), (research, "_evaluate_intraday_research"),
                    (joint, "_fit"), (joint, "_evaluate"), (joint, "_select"), (joint, "run_intraday_execution")):
                patch.setattr(module, attribute, blocked)
            report = final.run_intraday_final_test(selection)
        tested = final.create_intraday_test_experiment(selection, report)
        test_path = write_strategy_experiment(tested, path=root / f"{name}-test.json").path
        assert load_strategy_experiment(test_path).content == tested.content
        assert (source_path.read_bytes(), study_path.read_bytes()) == before
        cases[name] = SimpleNamespace(data=data, source=source, source_path=source_path, args=args, study=study,
            study_path=study_path, selection=selection, selection_path=selection_path, tested=tested,
            test_path=test_path, calls=calls)
    return cases


def test_freeze_complete_saved_family_and_both_genuine_economic_winners(joint_final_case):
    for name, case in joint_final_case.items():
        selected, source, study = case.selection.as_dict(), case.source.as_dict(), case.study.as_dict()
        report, evidence = selected["report"], selected["report"]["dev_selection"]
        window, reference = study["report"]["final_dev"], study["plan"]["selection"]
        group = source["report"]["groups"][reference["cost_index"]]
        candidate = group["results"][reference["candidate_index"]]
        assert selected["artifact_schema_version"] == final.INTRADAY_SELECTION_V4_VERSION
        assert selected["plan"]["source_experiment"] == {"path": str(case.study_path), "experiment_id": case.study.experiment_id,
            "artifact_schema_version": joint.INTRADAY_JOINT_SELECTION_VERSION,
            "report_id": study["report"]["joint_selection_id"]}
        assert report["evaluation_scope"] == "DEVELOPMENT_INNER_JOINT_ECONOMIC_FINAL_RECIPE"
        assert evidence["joint_selection_id"] == study["report"]["joint_selection_id"]
        assert evidence["method"] == joint.METHOD and evidence["final_dev"] == window
        assert evidence["source_selection"] == reference
        assert evidence["source_experiment"] == {"path": str(case.source_path), "experiment_id": case.source.experiment_id,
                                                "research_id": source["report"]["research_id"]}
        assert evidence["fixed_reference"] == {key: candidate[key] for key in ("strategy", "axis_values")}
        assert report["candidate"] == {"strategy": window["selected_recipe"], "axis_values": [],
                                         "execution_policy": group["execution_policy"]}
        assert report["context"]["feature_fields"] == source["report"]["context"]["feature_fields"]
        assert selected["algorithm_versions"] == {**study["algorithm_versions"], "selection": final.INTRADAY_SELECTION_V4_VERSION}
        assert report["return_basis"] == case.tested.as_dict()["report"]["return_basis"] == joint.RETURN_BASIS
        assert len(window["models"]) == 6 and len(window["family_results"]) == 24
        returns = [row["execution"]["metrics"]["total_return"] for row in window["family_results"]]
        assert window["selected_index"] == max(range(24), key=returns.__getitem__)
        assert (window["selected_index"], window["selected_recipe"]["kind"], window["selected_recipe"]["alpha"]) == (
            (8, "RIDGE", 10.) if name == "ridge" else (12, "QUADRATIC_RIDGE", .1))
        if name == "quadratic":
            assert max(returns[:12]) < min(returns[12:])
        root = case.tested.as_dict()
        assert root["artifact_schema_version"] == final.INTRADAY_TEST_EXPERIMENT_V4_VERSION
        assert root["plan"]["selection"] == selected
        assert ("quadratic" in root["algorithm_versions"]) == (name == "quadratic")
        assert "joint_selection" not in root["algorithm_versions"]


def test_one_final_fit_training_scores_tails_and_independent_cash_oracle(joint_final_case):
    for name, case in joint_final_case.items():
        report, raw = case.tested.as_dict()["report"], case.data.as_dict()["report"]
        context, model = report["context"], report["model"]
        window = case.study.as_dict()["report"]["final_dev"]
        assert case.calls == {"loads": 1, "fits": [(180, 2, 10.)] if name == "ridge" else [(30, 2, .1)]}
        assert context["training_keys"] == window["history_training_keys"] == model["training_keys"]
        assert context["purged_keys"] == window["history_purged_keys"]
        assert context["training_boundary"] == window["history_boundary"] == model["training_boundary"]
        assert set(window["training_keys"]) < set(model["training_keys"])
        inner_model = window["models"][window["selected_index"] // 4]["model"]
        assert model["model_id"] != inner_model["model_id"]
        observations = {row["observation_key"]: row for row in raw["observations"]}
        targets = {row["observation_key"]: row for row in raw["targets"]}
        independent_keys = [row["observation_key"] for row in raw["observations"]
            if row["trading_day"] in context["split"]["TRAIN"] + context["split"]["VALIDATION"]
            and targets[row["observation_key"]]["status"] == "COMPLETE"
            and targets[row["observation_key"]]["actual_label_end_time"] < context["training_boundary"]]
        assert model["training_keys"] == independent_keys
        assert any(targets[row["observation_key"]]["status"] != "COMPLETE" for row in report["predictions"])
        errors = []
        for row in report["predictions"]:
            features = observations[row["observation_key"]]["features"]
            if name == "ridge":
                score = model["intercept"] + fsum(coefficient * features[field]
                    for field, coefficient in zip(model["feature_fields"], model["coefficients"], strict=True))
            else:
                z = (features["return_2"] - model["input_transform"]["means"][0]) / model["input_transform"]["scales"][0]
                ridge = model["ridge_model"]
                score = ridge["intercept"] + ridge["coefficients"][0] * z + ridge["coefficients"][1] * z * z
            assert row["score"] == pytest.approx(score, abs=1e-14)
            assert row["target"] == ("LONG" if score > report["strategy"]["threshold"] else "FLAT")
            target = targets[row["observation_key"]]
            if target["status"] == "COMPLETE":
                errors.append(score - target["value"])
        assert report["prediction_metrics"]["mae"] == pytest.approx(fsum(abs(e) for e in errors) / len(errors))
        assert report["prediction_metrics"]["rmse"] == pytest.approx(sqrt(fsum(e * e for e in errors) / len(errors)))
        prices = {(row["trading_day"], row["slot"]): row["open"] for row in raw["prices"]}
        cost_factor = Fraction(665667, 667667)
        for account in (report["execution"], report["benchmark"]["execution"]):
            cash = 1.
            for trade in account["trades"]:
                entry, exit_ = prices[(trade["trading_day"], trade["entry_slot"])], prices[(trade["trading_day"], trade["exit_slot"])]
                assert (trade["entry_raw_open"], trade["exit_raw_open"]) == (entry, exit_)
                cash *= exit_ / entry * float(cost_factor)
            assert account["metrics"]["final_cash"] == pytest.approx(cash, abs=1e-13)
            assert [row["trading_day"] for row in account["daily"]] == context["split"]["TEST"]
            assert all(day["cash_open"] == previous["cash_close"] for previous, day in zip(account["daily"], account["daily"][1:]))
        if name == "quadratic":
            assert model["input_transform"]["means"] == pytest.approx([0.])
            assert model["input_transform"]["scales"] == pytest.approx([sqrt(2 * .02 ** 2 / 3)])
            assert model["ridge_model"]["coefficients"] == pytest.approx([0., float(Fraction(4, 301))])
            assert model["ridge_model"]["intercept"] == pytest.approx(float(Fraction(-179, 36120)))
            assert [row["target"] for row in report["predictions"]] == ["LONG", "FLAT", "FLAT", "FLAT", "LONG", "FLAT"]
            assert report["prediction_metrics"]["prediction_count"] == 6
            assert report["prediction_metrics"]["complete_target_count"] == 3
            assert [(row["entry_slot"], row["exit_slot"]) for row in report["execution"]["trades"]] == [(5, 7), (5, 7)]
            assert report["execution"]["metrics"]["final_cash"] == pytest.approx(float((Fraction(203, 200) * cost_factor) ** 2))
            assert report["benchmark"]["execution"]["metrics"]["final_cash"] == pytest.approx(float(cost_factor ** 3))


def test_full_replay_reconstructs_complete_joint_source_with_one_q5_admission(joint_final_case, monkeypatch):
    case = joint_final_case["quadratic"]
    loader, loaded = final.load_intraday_dataset, []
    def load(path):
        loaded.append(path)
        return loader(path)
    monkeypatch.setattr(final, "load_intraday_dataset", load)
    monkeypatch.setattr(research, "load_intraday_dataset", lambda *a, **kw: pytest.fail("Replay admitted Q5 twice"))
    monkeypatch.setattr(joint, "load_strategy_experiment", lambda *a, **kw: pytest.fail("Replay requested embedded ordinary file"))
    proof = replay_strategy_experiment(case.tested)
    assert len(loaded) == 1
    assert proof["source_report_matches"] and proof["selection_report_matches"] and proof["final_report_matches"]
    assert proof["expected_report_sha256"] == proof["actual_report_sha256"]


def test_strict_history_boundary_and_future_interventions_before_any_reselection(joint_final_case, monkeypatch):
    case = joint_final_case["quadratic"]
    frozen, baseline = case.selection.as_dict(), case.tested.as_dict()["report"]
    # Q5 labels are constrained to their own session. These deliberate private
    # admitted-row counterfactuals exercise the strict < boundary; none is a
    # fabricated saved Q5 or a public verified-source bypass.
    def evaluate(selected, raw):
        return final._evaluate_final_test(selected, SimpleNamespace(data_id=case.data.data_id, as_dict=lambda: raw))
    monkeypatch.setattr(joint, "_select", lambda *a, **kw: pytest.fail("TEST reselected DEV"))
    first = baseline["context"]["training_keys"][0]
    boundary = baseline["context"]["training_boundary"]
    counterfactual = case.data.as_dict()
    next(row for row in counterfactual["report"]["targets"] if row["observation_key"] == first)["actual_label_end_time"] = boundary
    with monkeypatch.context() as patch:
        patch.setattr(research, "_fit", lambda *a, **kw: pytest.fail("history mismatch reached fitter"))
        for key in ("history_boundary", "history_training_keys", "history_purged_keys"):
            changed = case.selection.as_dict()
            window = changed["report"]["dev_selection"]["final_dev"]
            window[key] = (window["training_boundary"] if key == "history_boundary" else
                           window[key][1:] if key == "history_training_keys" else [first])
            with pytest.raises(ValueError, match="frozen final DEV history"):
                evaluate(changed, case.data.as_dict())
        with pytest.raises(ValueError, match="frozen final DEV history"):
            evaluate(frozen, counterfactual)
    private_frozen = deepcopy(frozen)
    private_window = private_frozen["report"]["dev_selection"]["final_dev"]
    private_window["history_training_keys"].remove(first)
    private_window["history_purged_keys"] = [first]
    actual = evaluate(private_frozen, counterfactual)
    assert len(actual["model"]["training_keys"]) == 29 and actual["context"]["purged_keys"] == [first]
    poisoned = deepcopy(counterfactual)
    next(row for row in poisoned["report"]["observations"] if row["observation_key"] == first)["features"]["return_2"] = 1e9
    next(row for row in poisoned["report"]["targets"] if row["observation_key"] == first)["value"] = 1e9
    unaffected = evaluate(private_frozen, poisoned)
    for key in ("model", "context", "strategy", "predictions", "execution", "benchmark"):
        assert unaffected[key] == actual[key]
    test_keys = set(baseline["context"]["test_keys"])
    last_day = baseline["context"]["split"]["TEST"][-1]
    for kind in ("targets", "features", "prices"):
        raw = case.data.as_dict()
        if kind == "targets":
            for row in raw["report"]["targets"]:
                if row["observation_key"] in test_keys and row["status"] == "COMPLETE":
                    row["value"] += 1
        elif kind == "features":
            for row in raw["report"]["observations"]:
                if row["trading_day"] == last_day:
                    row["features"]["return_2"] += .1
        else:
            for row in raw["report"]["prices"]:
                if row["trading_day"] == last_day:
                    row["open"] *= 1.2
                    row["close"] *= 1.2
        actual = evaluate(frozen, raw)
        assert actual["model"] == baseline["model"] and actual["context"] == baseline["context"]
        assert actual["strategy"] == baseline["strategy"] and actual["execution_policy"] == baseline["execution_policy"]
        assert [row for row in actual["predictions"] if row["trading_day"] != last_day] == [
            row for row in baseline["predictions"] if row["trading_day"] != last_day]
        if kind == "targets":
            assert actual["predictions"] == baseline["predictions"] and actual["execution"] == baseline["execution"]
            assert actual["prediction_metrics"] != baseline["prediction_metrics"]
        elif kind == "features":
            assert actual["predictions"] != baseline["predictions"]
        else:
            assert actual["predictions"] == baseline["predictions"] and actual["execution"] != baseline["execution"]


def test_resealed_v4_full_recipe_grammar_and_source_binding_precede_data(joint_final_case, monkeypatch):
    case = joint_final_case["ridge"]
    blocked = lambda *a, **kw: pytest.fail("saved admission or binding read Q5 or fitted")
    for module, attribute in ((final, "load_intraday_dataset"), (research, "load_intraday_dataset"),
                              (research, "_fit"), (joint, "_fit"), (joint, "_select"), (joint, "run_intraday_execution")):
        monkeypatch.setattr(module, attribute, blocked)
    for mutation in ("missing_account", "missing_model", "wrong_winner", "method", "kind", "alpha", "threshold",
                     "model_binding", "model_alpha", "feature_order", "seven_features", "missing_quad", "return_basis", "v3_source"):
        root = case.selection.as_dict()
        evidence, candidate = root["report"]["dev_selection"], root["report"]["candidate"]["strategy"]
        window = evidence["final_dev"]
        if mutation == "missing_account":
            window["family_results"].pop()
        elif mutation == "missing_model":
            window["models"].pop()
        elif mutation == "wrong_winner":
            window["selected_index"] = (window["selected_index"] + 1) % 24
        elif mutation == "method":
            evidence["method"]["tie_break"] = "HIGHER_THRESHOLD"
        elif mutation in ("kind", "alpha", "threshold"):
            candidate[mutation] = {"kind": "QUADRATIC_RIDGE", "alpha": .1, "threshold": .002}[mutation]
        elif mutation == "model_binding":
            # These recipes share threshold zero, but not the fitted model.
            window["family_results"][0]["model_index"] = 1
        elif mutation == "model_alpha":
            model = window["models"][0]["model"]
            model["alpha"] = 10.
            bind(model, "model_id")
        elif mutation == "feature_order":
            root["report"]["context"]["feature_fields"].reverse()
        elif mutation == "seven_features":
            root["report"]["context"]["feature_fields"] = [f"x{index}" for index in range(7)]
        elif mutation == "missing_quad":
            del root["algorithm_versions"]["quadratic"]
        elif mutation == "return_basis":
            root["report"]["return_basis"]["price_basis"] = "ADJUSTED"
        else:
            root["plan"]["source_experiment"]["artifact_schema_version"] = "market-vault-intraday-threshold-selection-v1"
        with pytest.raises(ValueError):
            StrategyExperiment(signed_selection(root))
    for mutation in ("history_keys", "history_purged", "history_boundary", "selection_pair", "result_version", "return_basis"):
        root = case.tested.as_dict()
        context = root["report"]["context"]
        if mutation == "history_keys":
            context["training_keys"] = context["training_keys"][1:]
        elif mutation == "history_purged":
            context["purged_keys"] = ["a" * 64]
        elif mutation == "history_boundary":
            context["training_boundary"] = case.selection.as_dict()["report"]["dev_selection"]["final_dev"]["training_boundary"]
        elif mutation == "selection_pair":
            root["plan"]["selection"]["artifact_schema_version"] = final.INTRADAY_SELECTION_V3_VERSION
        elif mutation == "result_version":
            root["report"]["result_schema_version"] = final.INTRADAY_FINAL_RESULT_V3_VERSION
        else:
            root["report"]["return_basis"]["price_basis"] = "ADJUSTED"
        bind(context, "context_id")
        bind(root["report"], "final_test_id")
        bind(root, "experiment_id")
        with pytest.raises(ValueError):
            StrategyExperiment(canonical_json(root))
    # A well-shaped reference index is admitted offline, but the complete
    # frozen evidence must still match the direct saved Q36 before Q5 access.
    root = case.selection.as_dict()
    root["report"]["dev_selection"]["source_selection"]["cost_index"] = 0
    altered = StrategyExperiment(signed_selection(root))
    with pytest.raises(ValueError, match="complete frozen selection report differs"):
        final.run_intraday_final_test(altered)


def test_unavailable_and_historical_saved_versions_do_not_admit_execution(joint_final_case, tmp_path, monkeypatch):
    case = joint_final_case["quadratic"]
    # One genuine unavailable source on the existing small Q5: 14 history
    # days cannot leave ten fit days before the fixed five-day holdout.
    plan = deepcopy(case.source.as_dict()["plan"])
    plan["walk_forward"]["minimum_train_days"] = 14
    source = create_intraday_experiment(plan=plan, report=research.run_intraday_research(plan))
    path = write_strategy_experiment(source, path=tmp_path / "short-source.json").path
    candidate = source.as_dict()["report"]["groups"][0]["results"][0]
    unavailable = joint.run_intraday_joint_selection(path, expected_experiment_id=source.experiment_id,
        cost_index=0, candidate_index=0, expected_candidate_id=candidate["candidate_id"])
    unavailable_path = write_strategy_experiment(unavailable, path=tmp_path / "unavailable.json").path
    assert unavailable.as_dict()["report"]["status"] == "UNAVAILABLE"
    blocked = lambda *a, **kw: pytest.fail("unavailable/version guard read Q5, fitted or selected")
    for module, attribute in ((final, "load_intraday_dataset"), (research, "load_intraday_dataset"),
                             (research, "_fit"), (joint, "_fit"), (joint, "_select"), (joint, "run_intraday_execution")):
        monkeypatch.setattr(module, attribute, blocked)
    with pytest.raises(ValueError, match="only an AVAILABLE"):
        final.freeze_intraday_joint_selection(unavailable_path, expected_experiment_id=unavailable.experiment_id)
    with pytest.raises(ValueError, match="identity differs"):
        final.freeze_intraday_joint_selection(case.study_path, expected_experiment_id="a" * 64)
    with pytest.raises(ValueError, match="saved joint-selection"):
        final.freeze_intraday_joint_selection(case.source_path, expected_experiment_id=case.source.experiment_id)
    historical = case.study.as_dict()
    historical["algorithm_versions"]["joint_selection"] = historical["report"]["version"] = "historical-joint"
    bind(historical["report"], "joint_selection_id")
    bind(historical, "experiment_id")
    old = StrategyExperiment(canonical_json(historical))
    old_path = write_strategy_experiment(old, path=tmp_path / "historical-joint.json").path
    with pytest.raises(ValueError, match="source algorithms differ"):
        final.freeze_intraday_joint_selection(old_path, expected_experiment_id=old.experiment_id)
    monkeypatch.setattr(final, "load_strategy_experiment", blocked)
    historical = case.selection.as_dict()
    historical["algorithm_versions"]["selection"] = historical["report"]["version"] = "historical-selection"
    old = StrategyExperiment(signed_selection(historical))
    with pytest.raises(ValueError, match="selection algorithms differ"):
        final.run_intraday_final_test(old)
    historical = case.tested.as_dict()
    historical["algorithm_versions"]["final_test"] = historical["report"]["version"] = "historical-final-test"
    bind(historical["report"], "final_test_id")
    bind(historical, "experiment_id")
    old = StrategyExperiment(canonical_json(historical))
    with pytest.raises(ValueError, match="final TEST algorithms differ"):
        replay_strategy_experiment(old)


def test_full_replay_detects_unselected_ordinary_member_while_normal_test_uses_frozen_recipe(joint_final_case, tmp_path, monkeypatch):
    case = joint_final_case["ridge"]
    altered = case.study.as_dict()
    ordinary = altered["report"]["source_experiment"]
    # The reference is cost 1 / candidate 1. Corrupt only candidate 0's first
    # fit, consistently across costs as ordinary saved grammar requires.
    # No selected reference, recipe, score or account is changed.
    for group in ordinary["report"]["groups"]:
        candidate = group["results"][0]
        model = candidate["fold_models"][0]["model"]
        model["ridge_model"]["coefficients"][0] += 1e-6
        bind(model["ridge_model"], "model_id")
        bind(model, "model_id")
        bind(candidate, "candidate_id")
    bind(ordinary["report"], "research_id")
    bind(ordinary, "experiment_id")
    altered["plan"]["source_experiment"]["experiment_id"] = ordinary["experiment_id"]
    altered["report"]["plan_sha256"] = digest(altered["plan"])
    bind(altered["report"], "joint_selection_id")
    bind(altered, "experiment_id")
    false_fit = StrategyExperiment(canonical_json(altered))
    path = write_strategy_experiment(false_fit, path=tmp_path / "unselected-false-fit.json").path
    frozen = final.freeze_intraday_joint_selection(path, expected_experiment_id=false_fit.experiment_id)
    actual = final.run_intraday_final_test(frozen)
    baseline = case.tested.as_dict()["report"]
    for key in ("model", "strategy", "predictions", "execution", "benchmark"):
        assert actual[key] == baseline[key]
    monkeypatch.setattr(joint, "_select", lambda *a, **kw: pytest.fail("bad ordinary source reached joint selection"))
    monkeypatch.setattr(final, "_evaluate_final_test", lambda *a, **kw: pytest.fail("bad ordinary source reached TEST"))
    with pytest.raises(ValueError, match="complete ordinary source reconstruction"):
        replay_strategy_experiment(frozen)


def test_real_cli_joint_freeze_test_relocation_and_immutable_failure_recovery(joint_final_case, tmp_path):
    case = joint_final_case["quadratic"]
    cli = str(Path(sys.executable).with_name("market-vault.exe" if os.name == "nt" else "market-vault"))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    prefix = [cli, "--settings", str(tmp_path / "absent-settings.yaml")]
    def command(*args, ok=True):
        result = subprocess.run([*prefix, *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True)
        assert result.returncode == (0 if ok else 1), result.stderr
        return json.loads(result.stdout if ok else result.stderr)
    source_copy, q5_copy = tmp_path / "source.json", tmp_path / "q5.json"
    source_copy.write_bytes(case.study_path.read_bytes())
    q5_copy.write_bytes(case.data.path.read_bytes())
    selected_path, test_path = tmp_path / "selection.json", tmp_path / "test.json"
    freeze = ("research-intraday-freeze-joint-selection", "--source-experiment", source_copy,
              "--expected-experiment-id", case.study.experiment_id, "--experiment", selected_path)
    result = command(*freeze)
    assert result["selection"]["artifact_schema_version"] == final.INTRADAY_SELECTION_V4_VERSION
    before = selected_path.read_bytes()
    assert not command(*freeze)["experiment"]["created_new_file"]
    assert command(*freeze, "--name", "Different", ok=False)["status"] == "FAILED"
    assert selected_path.read_bytes() == before
    relocated = tmp_path / "relocated-joint.json"
    source_copy.rename(relocated)
    assert command("research-intraday-test", "--selection", selected_path, "--experiment", test_path, ok=False)["status"] == "FAILED"
    assert not test_path.exists()
    assert command("research-intraday-test", "--selection", selected_path, "--source-experiment-file", case.source_path,
                   "--intraday-data-file", q5_copy, "--experiment", test_path, ok=False)["status"] == "FAILED"
    assert not test_path.exists()
    assert command("research-intraday-test", "--selection", selected_path, "--source-experiment-file", relocated,
                   "--intraday-data-file", joint_final_case["ridge"].data.path,
                   "--experiment", test_path, ok=False)["status"] == "FAILED"
    assert not test_path.exists()
    command("research-intraday-test", "--selection", selected_path, "--source-experiment-file", relocated,
            "--intraday-data-file", q5_copy, "--experiment", test_path)
    tested = load_strategy_experiment(test_path)
    assert tested.as_dict()["report"]["model"] == case.tested.as_dict()["report"]["model"]
    for path in (selected_path, test_path):
        command("research-experiment-open", "--experiment", path)
    proof = command("research-experiment-replay", "--experiment", test_path,
                    "--source-experiment-file", relocated, "--intraday-data-file", q5_copy)
    assert proof["source_report_matches"] and proof["selection_report_matches"] and proof["final_report_matches"]
    assert selected_path.read_bytes() == before and relocated.read_bytes() == case.study.content
    assert case.source_path.read_bytes() == case.source.content


def test_v4_saved_test_readers_retain_single_candidate_boundaries(joint_final_case, monkeypatch):
    from market_vault.research.intraday_performance import analyze_intraday_experiment, summarize_intraday_execution
    from market_vault.research.intraday_risk_diagnostics import analyze_intraday_risk_diagnostics
    from market_vault.research.intraday_saved_comparison import compare_saved_intraday_experiments
    from market_vault.research.return_assessment import ReturnAssessmentError, assess_saved_experiment
    case = joint_final_case["quadratic"]
    blocked = lambda *a, **kw: pytest.fail("saved reader read source data or fitted")
    for module, attribute in ((final, "load_intraday_dataset"), (final, "load_strategy_experiment"),
                              (research, "load_intraday_dataset"), (research, "_fit"), (joint, "_fit"),
                              (joint, "_select"), (joint, "run_intraday_execution")):
        monkeypatch.setattr(module, attribute, blocked)
    risk = analyze_intraday_risk_diagnostics(case.tested)
    assert risk["status"] == "SUCCESS"
    assert risk["strategy_diagnostics"]["report"]["fold_diagnostics"]["status"] == "NOT_APPLICABLE"
    performance = summarize_intraday_execution(case.tested.as_dict()["report"]["execution"])
    assert performance["summary"]["trade_count"]["value"] == 2
    for args in ({"candidate_index": 1}, {"cost_index": 1}):
        with pytest.raises(ValueError, match="both indices must be zero"):
            analyze_intraday_risk_diagnostics(case.tested, **args)
    with pytest.raises(ValueError):
        analyze_intraday_risk_diagnostics(case.selection)
    with pytest.raises(ValueError, match="performance requires"):
        analyze_intraday_experiment(case.tested)
    with pytest.raises(ValueError, match="saved comparison requires"):
        compare_saved_intraday_experiments(case.tested, case.tested)
    with pytest.raises(ReturnAssessmentError) as exc:
        assess_saved_experiment(case.test_path)
    assert exc.value.reason_code == "UNSUPPORTED_SOURCE"
