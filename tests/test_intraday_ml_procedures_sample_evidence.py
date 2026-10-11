"""Recorded ML sample uses bound to real synthetic Q5 and external snapshots."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_vault import cli
from market_vault.backtest import intraday as execution
from market_vault.quality import market_data_comparison as comparison
from market_vault.research import intraday_data as q5
from market_vault.research import intraday_inner_selection as inner
from market_vault.research import intraday_joint_selection as joint
from market_vault.research import intraday_market_dependencies as dependencies
from market_vault.research import intraday_market_evidence as market
from market_vault.research import intraday_research as research
from market_vault.research import intraday_sample_usage as usage
from market_vault.research import intraday_threshold_selection as threshold
from market_vault.research.strategy_experiment import StrategyExperiment, write_strategy_experiment
from test_intraday_experiment import signed
from test_intraday_ml_procedures_stress import _short_study
from test_strategy_intraday_inner_selection import resigned as inner_resigned
from test_strategy_intraday_market_evidence import _plan, _reference, _write
from test_strategy_intraday_threshold_selection import resigned as threshold_resigned


def _no_recomputation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("sample-use evidence fitted, selected or executed an account")

    for module, names in (
        (research, ("_fit", "fit_ridge_rows", "fit_quadratic_rows", "_evaluate_intraday_research",
                    "run_intraday_research", "run_intraday_execution")),
        (inner, ("_fit", "_select", "_evaluate", "run_intraday_inner_selection", "run_intraday_execution")),
        (threshold, ("_fit", "_select", "_evaluate", "run_intraday_threshold_selection", "run_intraday_execution")),
        (joint, ("_fit", "_select", "_evaluate", "run_intraday_joint_selection", "run_intraday_execution")),
        (execution, ("run_intraday_execution",)),
        (dependencies, ("analyze_intraday_market_dependencies", "run_intraday_market_dependencies")),
        (market, ("analyze_intraday_market_evidence", "run_intraday_market_evidence")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def _market_plan(data, directory):
    report = data.as_dict()["report"]
    directory.mkdir(parents=True, exist_ok=True)
    items = []
    for day_index in (0, 15, 16, 17):
        session = report["sessions"][day_index]
        start = comparison.parse_utc(session["open_time"])
        step = timedelta(minutes=comparison.INTERVAL_MINUTES[report["interval"]])
        first, count = (5, 1) if day_index == 15 else (0, session["bar_count"])
        scope = {"symbol": report["symbol"], "interval": report["interval"], "adjustment": "NONE", "session": "RTH",
                 "asset_class": "ETF", "currency": "USD", "aggregation": "TRADE_OHLCV", "volume_basis": "SHARES",
                 "window_start": comparison.utc_text(start + first * step),
                 "window_end": comparison.utc_text(start + (first + count) * step)}
        path = None
        if day_index != 16:
            reference = _reference(data, scope=scope)
            if day_index == 15:
                bar = reference["bars"][0]
                original = bar["open"]
                bar["open"] = (original + bar["high"]) / 2 if bar["high"] > original else (original + bar["low"]) / 2
                assert bar["open"] != original
            else:
                reference["bars"][6]["volume"] += 10
            path = _write(directory / f"day-{day_index}.json", reference)
        items.append({"scope": scope, "snapshot": None if path is None else str(path)})
    plan = _plan(*items)
    plan["basis"]["asset_class"] = "ETF"
    return plan


def _stage(report, kind, *, index=0, scope="OUTER_FOLD"):
    return next(row for row in report["stages"] if row["stage_kind"] == kind and row["scope"] == scope
                and row["fold_index"] == (None if scope == "FINAL_DEV" else index))


def _keys(report, stage):
    observations = report["dependency_evidence"]["observations"]
    return [observations[index]["observation_key"] for index in stage["sample_refs"]]


def _identity_and_denominators(report):
    assert report["sample_usage_id"] == q5.digest({key: value for key, value in report.items() if key != "sample_usage_id"})
    dependency = report["dependency_evidence"]
    assert report["binding"]["dependency_evidence_id"] == dependency["market_dependencies_id"]
    assert report["binding"]["market_evidence_id"] == dependency["market_evidence"]["market_evidence_id"]
    assert all(report["binding"][key] for key in ("context_matches", "window_inputs_match", "all_recorded_keys_resolved"))
    assert report["analysis_actions"] == {"q5_strict_verification_count": 1, "context_reconstructed": True,
        "window_input_facts_reconstructed": True, "models_refitted": False, "selection_rerun": False,
        "execution_replayed": False, "full_research_replay": False, "source_or_data_written": False}
    assert len(dependency["observations"]) == 1170 and len(dependency["market_evidence"]["rows"]) == 1690
    for index, stage in enumerate(report["stages"]):
        assert stage["stage_index"] == index
        assert stage["recorded_sample_count"] == len(stage["sample_refs"])
        assert stage["recorded_price_slot_count"] == len(stage["price_row_refs"])
        assert stage["actual_used_count"] == (len(stage["sample_refs"]) if stage["usage"] == "ACTUAL" else 0)
        assert stage["actual_used_price_slot_count"] == (len(stage["price_row_refs"]) if stage["usage"] == "ACTUAL" else 0)
        assert len(set(stage["sample_refs"])) == len(stage["sample_refs"])
        for count in stage["support_counts"].values():
            assert count["recorded_sample_count"] == stage["recorded_sample_count"]
            assert count["applicable_sample_count"] + count["not_applicable_sample_count"] == count["recorded_sample_count"]
        assert not any(dependency["observations"][i]["trading_day"] in report["context"]["split"]["TEST"]
                       for i in stage["sample_refs"])


def test_real_four_sources_exact_stage_keys_single_capture_and_no_recomputation(procedure_comparison_case, tmp_path, monkeypatch):
    case = procedure_comparison_case
    plan = _market_plan(case.data, tmp_path / "references")
    before_plan = deepcopy(plan)
    paths = [case.path, case.data.path, *(path for _, path in case.studies.values()),
             *(Path(item["snapshot"]) for item in plan["references"] if item["snapshot"] is not None)]
    before = {path: sha256(path.read_bytes()).digest() for path in paths}
    original = case.source.as_dict()
    context = original["report"]["context"]
    targets = {row["observation_key"]: row for row in case.data.as_dict()["report"]["targets"]}
    _no_recomputation(monkeypatch)
    calls = {key: [] for key in ("read", "verify", "prepare", "dependency", "market", "reference")}
    for module, name, key in ((q5, "_read", "read"), (q5, "verify_intraday_dataset", "verify"),
                              (research, "_prepare_intraday_research", "prepare"),
                              (dependencies, "_analyze_verified", "dependency"), (market, "_analyze_verified", "market"),
                              (comparison, "_file_input", "reference")):
        original_function = getattr(module, name)

        def recorded(*args, _function=original_function, _key=key, **kwargs):
            calls[_key].append(kwargs["data"] if _key == "prepare" else args[0])
            return _function(*args, **kwargs)

        monkeypatch.setattr(module, name, recorded)
    dependency_ids = []
    for kind, (snapshot, _) in {"ordinary": (case.source, case.path), **case.studies}.items():
        for values in calls.values():
            values.clear()
        report = usage.analyze_intraday_sample_usage(snapshot, plan)
        assert calls["read"] == [case.data.path]
        assert len(calls["verify"]) == len(calls["prepare"]) == len(calls["dependency"]) == len(calls["market"]) == 1
        assert calls["prepare"][0] is calls["dependency"][0] is calls["market"][0]
        assert calls["reference"] == [item["snapshot"] for item in plan["references"]]
        _identity_and_denominators(report)
        dependency_ids.append(report["binding"]["dependency_evidence_id"])
        assert report["status"] == report["source"]["study_status"] == "AVAILABLE"
        assert report["source"]["experiment_id"] == snapshot.experiment_id
        assert report["source"]["content_sha256"] == sha256(snapshot.content).hexdigest()
        assert report["context"] == context
        assert report["summary"]["stage_count"] == {"ordinary": 16, "q25": 38, "q31": 33, "q36": 33}[kind]
        assert report["summary"]["unique_actual_used_sample_count"] == (1040 if kind == "ordinary" else 1050)
        saved = snapshot.as_dict()["report"]
        for index, fold in enumerate(context["folds"]):
            packet = (original["report"]["groups"][0]["results"][0]["fold_models"][index] if kind == "ordinary" else
                      saved["outer_folds"][index]["application" if kind == "q31" else "refit"])
            training = _stage(report, "OUTER_MODEL_TRAINING", index=index)
            prediction = _stage(report, "OUTER_PREDICTION", index=index)
            score = _stage(report, "OUTER_TARGET_SCORE", index=index)
            assert _keys(report, training) == packet["model"]["training_keys"] == fold["training_keys"]
            assert _keys(report, prediction) == fold["validation_keys"]
            assert _keys(report, score) == [key for key in fold["validation_keys"] if targets[key]["status"] == "COMPLETE"]
            assert training["models"][0]["model_id"] == packet["model"]["model_id"]
            assert training["recorded_fit_executed"] is (kind != "q31")
            assert training["feature_usage"] == training["label_usage"] == "USED"
            assert prediction["feature_usage"] == "USED" and prediction["label_usage"] == "ASSOCIATED_ONLY"
            assert score["feature_usage"] == "VIA_RECORDED_PREDICTION" and score["label_usage"] == "USED"
            purged = _stage(report, "OUTER_TRAIN_PURGED", index=index)
            assert _keys(report, purged) == fold["purged_keys"] == []
            assert purged["usage"] == "PURGED" and not purged["recorded_fit_executed"]
            if kind != "ordinary":
                window = saved["outer_folds"][index]["inner"]
                assert _keys(report, _stage(report, "INNER_MODEL_TRAINING", index=index)) == window["training_keys"]
                assert _keys(report, _stage(report, "INNER_TRAIN_PURGED", index=index)) == window["purged_keys"]
                holdout_kind = "INNER_HOLDOUT_PREDICTION" if kind == "q25" else "INNER_ECONOMIC_HOLDOUT"
                assert _keys(report, _stage(report, holdout_kind, index=index)) == window["validation_keys"]
                if kind == "q25":
                    assert _keys(report, _stage(report, "INNER_TARGET_SCORE", index=index)) == [
                        row["observation_key"] for row in window["scored_targets"]]
        first = _stage(report, "OUTER_MODEL_TRAINING")
        assert first["recorded_sample_count"] == 140
        assert context["folds"][0]["training_days"][0] not in context["evaluated_days"]
        for name, different in (("feature_window", 15), ("target_endpoints", 1), ("target_completeness", 5)):
            assert first["support_counts"][name] == {"recorded_sample_count": 140, "applicable_sample_count": 140,
                "different_sample_count": different, "incomplete_evidence_sample_count": 126, "not_applicable_sample_count": 0}
        if kind == "q31":
            assert first["fit_origin"] == "REUSED_FIXED_SOURCE_MODEL" and first["actual_used_count"] == 140
        if kind != "ordinary":
            training = _stage(report, "INNER_MODEL_TRAINING")
            assert training["recorded_sample_count"] == 105 and training["recorded_fit_executed"]
            assert len(training["models"]) == (1 if kind == "q31" else 6)
            final = _stage(report, "FINAL_DEV_REFIT_ELIGIBLE_HISTORY", scope="FINAL_DEV")
            assert _keys(report, final) == saved["final_dev"]["history_training_keys"]
            assert final["recorded_sample_count"] == 840 and final["actual_used_count"] == 0
            assert final["usage"] == "ELIGIBLE_FOR_LATER_FIT" and not final["recorded_fit_executed"]
            assert _stage(report, "INNER_MODEL_TRAINING", scope="FINAL_DEV")["recorded_sample_count"] == 805
        if kind == "q25":
            assert _stage(report, "INNER_HOLDOUT_PREDICTION")["recorded_sample_count"] == 45
            assert _stage(report, "INNER_TARGET_SCORE")["recorded_sample_count"] == 35
        if kind in ("q31", "q36"):
            holdout = _stage(report, "INNER_ECONOMIC_HOLDOUT")
            assert holdout["recorded_sample_count"] == 45 and holdout["recorded_price_slot_count"] == 65
            assert holdout["label_usage"] == "NOT_USED_BY_OBJECTIVE" and holdout["feature_usage"] == "VIA_RECORDED_DECISION"
            price = holdout["price_support_counts"]
            assert price["comparison_status_counts"] == {**dict.fromkeys(market.SLOT_STATUSES, 0),
                "MATCH": 12, "DIFFERENT": 2, "NOT_RUN": 13, "UNASSESSED": 38}
            assert price["field_comparison_counts"] == {"open": {"matched_links": 13, "different_links": 1, "unassessable_links": 51},
                "close": {"matched_links": 14, "different_links": 0, "unassessable_links": 51}}
            observations = report["dependency_evidence"]["observations"]
            covered_day = case.data.as_dict()["report"]["sessions"][17]["trading_day"]
            tail = next(row for row in observations if row["trading_day"] == covered_day and row["slot"] == 12)
            assert tail["target"]["status"] == "INCOMPLETE" and tail["target"]["reason"] == "SESSION_END"
            assert tail["target"]["completeness_support"]["session_end_shortfall"] == 2
            assert tail["target"]["completeness_support"]["bar_indices"] == []
            assert holdout["support_counts"]["target_completeness"]["incomplete_evidence_sample_count"] == 32
    assert len(set(dependency_ids)) == 1
    assert plan == before_plan and all(sha256(path.read_bytes()).digest() == value for path, value in before.items())


@pytest.fixture(scope="module")
def unavailable_sources(procedure_comparison_case, tmp_path_factory):
    case = procedure_comparison_case
    directory = tmp_path_factory.mktemp("sample-use-short")
    with pytest.MonkeyPatch.context() as setup:
        first, first_path, source = _short_study(case, directory, setup, kind="q25", minimum=10, nonfirst=True)
        source_path = directory / "source.json"
        setup.setattr(research, "load_intraday_dataset", lambda path: case.data)
        reference = source.as_dict()["report"]["groups"][1]["results"][1]
        args = {"expected_experiment_id": source.experiment_id, "cost_index": 1, "candidate_index": 1,
                "expected_candidate_id": reference["candidate_id"]}
        studies = {"q25": (first, first_path)}
        for kind, run in (("q31", threshold.run_intraday_threshold_selection), ("q36", joint.run_intraday_joint_selection)):
            snapshot = run(source_path, **args)
            studies[kind] = snapshot, write_strategy_experiment(snapshot, path=directory / f"{kind}.json").path
    return SimpleNamespace(data=case.data, source=source, path=source_path, studies=studies)


def test_real_unavailable_keeps_all_declared_windows_and_selected_cost_child(unavailable_sources, monkeypatch):
    case = unavailable_sources
    _no_recomputation(monkeypatch)
    prepare, costs = research._prepare_intraday_research, []

    def selected_cost(plan, **kwargs):
        costs.append(plan["execution"]["commission_bps"])
        return prepare(plan, **kwargs)

    monkeypatch.setattr(research, "_prepare_intraday_research", selected_cost)
    for snapshot, _ in case.studies.values():
        saved = snapshot.as_dict()["report"]
        assert saved["status"] == "UNAVAILABLE" and saved["final_dev"]["unavailable_reason"] is None
        report = usage.analyze_intraday_sample_usage(snapshot, _plan())
        assert report["status"] == "DECLARED_ONLY" and report["source"]["study_status"] == "UNAVAILABLE"
        assert report["source"]["source_selection"]["cost_index"] == report["source"]["source_selection"]["candidate_index"] == 1
        assert report["summary"]["recorded_sample_memberships"] > 0
        assert report["summary"]["actual_used_sample_memberships"] == report["summary"]["unique_actual_used_sample_count"] == 0
        assert report["summary"]["declared_only_stage_count"] == len(report["stages"])
        for stage in report["stages"]:
            assert stage["usage"] == "DECLARED_NOT_EXECUTED"
            assert stage["feature_usage"] == stage["label_usage"] == "NOT_EXECUTED"
            assert not stage["recorded_fit_executed"] and stage["fit_origin"] == "STUDY_NOT_EXECUTED"
            assert stage["actual_used_count"] == stage["actual_used_price_slot_count"] == 0
            assert stage["models"] == [] and stage["selected_recipe"] is None and stage["unavailable_reason"]
        assert _keys(report, _stage(report, "INNER_MODEL_TRAINING", scope="FINAL_DEV")) == saved["final_dev"]["training_keys"]
        _identity_and_denominators(report)
    ordinary = usage.analyze_intraday_sample_usage(case.source, _plan(), cost_index=1, candidate_index=1)
    assert ordinary["source"]["study_status"] == ordinary["status"] == "AVAILABLE"
    assert ordinary["source"]["source_selection"]["candidate_index"] == 1
    assert costs == [3, 3, 3, 3]


def test_valid_saved_grammar_cannot_hide_context_target_or_unknown_key_binding(unavailable_sources, monkeypatch):
    case = unavailable_sources
    altered = case.source.as_dict()
    altered["report"]["context"]["held_out_test_observation_count"] += 1
    wrong_context = StrategyExperiment(signed(altered))
    altered = case.studies["q31"][0].as_dict()
    altered["report"]["outer_folds"][0]["inner"]["history_targets"][0]["value"] += .001
    wrong_target = StrategyExperiment(threshold_resigned(altered))
    altered = case.studies["q25"][0].as_dict()
    altered["report"]["outer_folds"][0]["inner"]["validation_keys"].append("f" * 64)
    unknown = StrategyExperiment(inner_resigned(altered))
    _no_recomputation(monkeypatch)
    monkeypatch.setattr(dependencies, "_analyze_verified", lambda *a, **kw: pytest.fail("invalid binding captured market evidence"))
    for snapshot, indices, message in ((wrong_context, {"cost_index": 1, "candidate_index": 1}, "complete ordinary context"),
                                      (wrong_target, {}, "non-fitted inputs"), (unknown, {}, "non-fitted inputs")):
        with pytest.raises(ValueError, match=message):
            usage.analyze_intraday_sample_usage(snapshot, _plan(), **indices)
    with pytest.raises(ValueError, match="both indices must be zero"):
        usage.analyze_intraday_sample_usage(case.studies["q31"][0], _plan(), cost_index=1)


def test_cli_real_relocated_q5_relative_manifest_capture_and_exclusive_output(procedure_comparison_case, tmp_path, monkeypatch, capsys):
    case = procedure_comparison_case
    directory = tmp_path / "manifest"
    plan = _market_plan(case.data, directory)
    for item in plan["references"]:
        if item["snapshot"] is not None:
            item["snapshot"] = Path(item["snapshot"]).name
    manifest = _write(directory / "plan.json", plan)
    relocated = tmp_path / "relocated-q5.json"
    relocated.write_bytes(case.data.content)
    before = {path: path.read_bytes() for path in (case.path, case.data.path, manifest, relocated)}
    output = tmp_path / "sample-usage.json"
    _no_recomputation(monkeypatch)
    monkeypatch.chdir(tmp_path)
    command = ["--settings", str(tmp_path / "absent.yaml"), "research-intraday-sample-usage",
               "--experiment", str(case.path), "--manifest", str(manifest), "--intraday-data", str(relocated), "--output", str(output)]
    assert cli.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    report = result["report"]
    assert result["status"] == "SUCCESS" and report["status"] == "AVAILABLE"
    assert json.loads(output.read_bytes()) == report
    assert report["binding"]["data_id"] == case.data.data_id
    assert report["binding"]["data_content_sha256"] == sha256(case.data.content).hexdigest()
    evidence = report["dependency_evidence"]["market_evidence"]
    assert evidence["data"]["locator"] == str(relocated)
    assert evidence["references"][0]["snapshot_locator"] == str(directory / "day-0.json")
    published = output.read_bytes()
    assert cli.main(command) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED" and output.read_bytes() == published
    failed = tmp_path / "bad-index.json"
    assert cli.main([*command[:-1], str(failed), "--candidate-index", "999"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "FAILED" and not failed.exists()
    assert all(path.read_bytes() == content for path, content in before.items())
