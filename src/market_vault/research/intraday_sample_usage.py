"""External bar evidence for sample uses recorded by an immutable DEV study.

The original Q5 and non-fitted research inputs are reconstructed once. Saved
models, selections and accounts are never rerun. Stages only reference one Q47
observation array and its one Q46 price grid.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from ..quality import market_data_comparison as comparison
from . import intraday_data as q5
from . import intraday_inner_selection as inner
from . import intraday_joint_selection as joint
from . import intraday_market_dependencies as dependencies
from . import intraday_market_evidence as market
from . import intraday_research as research
from . import intraday_threshold_selection as threshold
from .intraday_backtest import intraday_data_path, parse_execution_policy
from .intraday_ml_diagnostics import _saved_ml_source
from .strategy_experiment import StrategyExperiment, canonical_json, load_strategy_experiment


INTRADAY_SAMPLE_USAGE_VERSION = "market-vault-intraday-sample-usage-v1"
_FITTED_WINDOW_FIELDS = frozenset({"family_results", "model", "models", "predictions",
                                   "selected_index", "selected_recipe"})
_ASSESSED = frozenset({"MATCH", "DIFFERENT"})


def _equal(actual, expected, label):
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError("sample-use binding differs: " + label)


def _prediction_keys(predictions, keys, observations, label):
    _equal([row["observation_key"] for row in predictions], keys, label + " keys")
    for prediction in predictions:
        key = prediction["observation_key"]
        if key not in observations:
            raise ValueError("sample-use binding contains an unknown observation key")
        fields = ("observation_key", "trading_day", "slot", "decision_time")
        _equal({field: prediction[field] for field in fields},
               {field: observations[key][field] for field in fields}, label + " observation identity")


def _model_inputs(model, keys, boundary, label):
    _equal(model["training_keys"], keys, label + " training keys")
    _equal(model["training_boundary"], boundary, label + " training boundary")


def _inner_models(window, selected):
    if selected["module"] is inner:
        return [{"model_index": row["candidate_index"], "model": row["model"], "recipe": row["strategy"],
                 "predictions": row["predictions"]} for row in window["family_results"]]
    if selected["module"] is joint:
        return [{"model_index": row["model_index"], "model": row["model"], "recipe": row["strategy"],
                 "predictions": row["predictions"]} for row in window["models"]]
    return [{"model_index": None, "model": window["model"], "recipe": selected["reference"]["strategy"],
             "predictions": window["predictions"]}]


def _bound_inputs(selected, data_file):
    """Bind recorded inputs, without using any fit/evaluation/replay entry."""
    root, source, module = selected["root"], selected["source"], selected["module"]
    if source["algorithm_versions"] != research.research_algorithm_versions(source["plan"]):
        raise ValueError("recorded source algorithms differ; no Q5 was read or model fitted")
    if module is not None:
        versions = (inner.inner_selection_versions(source) if module is inner else
                    threshold.threshold_selection_versions(source) if module is threshold else
                    joint.joint_selection_versions(source))
        if root["algorithm_versions"] != versions:
            raise ValueError("recorded procedure algorithms differ; no Q5 was read or model fitted")
    _, children, _ = research.expand_intraday_plan(source["plan"], recorded=True)
    child = children[selected["selection"]["cost_index"]]
    locator = data_file if data_file is not None else (
        root["plan"]["intraday_data_path"] if module is not None else child["intraday_data_path"])
    snapshot = q5.load_intraday_dataset(intraday_data_path(str(locator)))
    prepared = research._prepare_intraday_research(child, data=snapshot)
    _equal(prepared.context, selected["context"], "complete ordinary context")
    _equal(snapshot.data_id, root["dataset_id"], "source data identity")
    context, reference = prepared.context, selected["reference"]
    observations = {row["observation_key"]: row for row in prepared.report["observations"]}
    _prediction_keys(reference["predictions"], context["validation_keys"], observations, "ordinary predictions")
    _equal(research.prediction_metrics(reference["predictions"], prepared.report),
           reference["prediction_metrics"], "ordinary scored targets")
    ordinary = []
    for fold, record in zip(context["folds"], reference["fold_models"], strict=True):
        _model_inputs(record["model"], fold["training_keys"], fold["training_boundary"], "ordinary fold")
        values = [row for row in reference["predictions"] if row["trading_day"] in fold["validation_days"]]
        _prediction_keys(values, fold["validation_keys"], observations, "ordinary fold predictions")
        ordinary.append({"model": record["model"], "strategy": reference["strategy"], "predictions": values})
    if module is None:
        return prepared, ordinary, []
    policy = () if module is inner else (parse_execution_policy(selected["group"]["execution_policy"]),)
    expected = [module._window(prepared, fold["training_days"], rows, fold["purged_keys"],
                               fold["training_boundary"], *policy)[0]
                for fold, rows in zip(context["folds"], prepared.fold_rows, strict=True)]
    dev_days = context["split"]["TRAIN"] + context["split"]["VALIDATION"]
    boundary = next(row["open_time"] for row in prepared.report["sessions"]
                    if row["trading_day"] == context["split"]["TEST"][0])
    rows, purged = research.training_rows(prepared.report, tuple(dev_days), boundary)
    expected.append(module._window(prepared, dev_days, rows, purged, boundary, *policy)[0])
    report = root["report"]
    windows = [row["inner"] for row in report["outer_folds"]] + [report["final_dev"]]
    available = report["status"] == "AVAILABLE"
    for index, (actual, saved) in enumerate(zip(expected, windows, strict=True)):
        _equal({key: value for key, value in actual.items() if key not in _FITTED_WINDOW_FIELDS},
               {key: value for key, value in saved.items() if key not in _FITTED_WINDOW_FIELDS},
               f"window {index} non-fitted inputs")
        if available:
            for member in _inner_models(saved, selected):
                _model_inputs(member["model"], saved["training_keys"], saved["training_boundary"], "inner model")
                _prediction_keys(member["predictions"], saved["validation_keys"], observations, "inner predictions")
    outer = []
    for fold, record in zip(context["folds"], report["outer_folds"], strict=True):
        packet = record["application" if module is threshold else "refit"]
        outer.append(packet)
        if available:
            _model_inputs(packet["model"], fold["training_keys"], fold["training_boundary"], "outer model")
            _prediction_keys(packet["predictions"], fold["validation_keys"], observations, "outer predictions")
            _equal(research.prediction_metrics(packet["predictions"], prepared.report),
                   packet["prediction_metrics"], "outer scored targets")
    return prepared, outer, windows


def _references(keys, by_key, label):
    if len(set(keys)) != len(keys):
        raise ValueError("sample-use binding contains duplicate " + label)
    if any(key not in by_key for key in keys):
        raise ValueError("sample-use binding contains unknown " + label)
    return [by_key[key] for key in keys]


def _sample_support(records, refs, bars):
    result = {name: {"recorded_sample_count": len(refs), "applicable_sample_count": 0,
                     "different_sample_count": 0, "incomplete_evidence_sample_count": 0,
                     "not_applicable_sample_count": 0}
              for name in ("feature_window", "target_endpoints", "target_completeness")}
    for index in refs:
        row = records[index]
        target = row["target"]
        statuses = {"feature_window": [bars[i]["status"] for i in row["feature_support"]["bar_indices"]],
                    "target_endpoints": None, "target_completeness": None}
        if target is not None:
            statuses["target_completeness"] = [bars[i]["status"] for i in target["completeness_support"]["bar_indices"]]
            if target["status"] == "COMPLETE":
                statuses["target_endpoints"] = [endpoint["evidence_status"] for endpoint in target["endpoints"].values()]
        for name, values in statuses.items():
            counts = result[name]
            if values is None:
                counts["not_applicable_sample_count"] += 1
            else:
                counts["applicable_sample_count"] += 1
                counts["different_sample_count"] += any(status == "DIFFERENT" for status in values)
                counts["incomplete_evidence_sample_count"] += any(status not in _ASSESSED for status in values)
    return result


def _model_metadata(members):
    return [{"model_index": row["model_index"], "model_id": row["model"]["model_id"],
             "recipe": deepcopy(row["recipe"])} for row in members]


def _stages(selected, prepared, outer, windows, evidence):
    records, bars = evidence["observations"], evidence["market_evidence"]["rows"]
    by_key = {row["observation_key"]: index for index, row in enumerate(records)}
    by_slot = {(row["trading_day"], row["slot"]): index for index, row in enumerate(bars)}
    available = selected["module"] is None or selected["root"]["report"]["status"] == "AVAILABLE"
    module, stages = selected["module"], []

    def add(kind, keys, *, scope, fold, boundary, usage="ACTUAL", feature="USED", label="USED",
            fit=False, origin="NOT_A_FIT_STAGE", models=(), recipe=None, prices=(), reason=None):
        refs = _references(keys, by_key, "sample keys")
        if not available:
            usage, feature, label, fit, origin = "DECLARED_NOT_EXECUTED", "NOT_EXECUTED", "NOT_EXECUTED", False, "STUDY_NOT_EXECUTED"
            models, recipe, reason = (), None, reason or "SOURCE_STUDY_UNAVAILABLE"
        price_refs = list(prices)
        support = None
        if kind == "INNER_ECONOMIC_HOLDOUT":
            support = dependencies._support_counts(bars, price_refs)
            support["field_comparison_counts"] = {field: support["field_comparison_counts"][field] for field in ("open", "close")}
        stages.append({"stage_index": len(stages), "stage_kind": kind, "scope": scope,
            "fold_index": None if fold is None else fold["fold_index"], "fold_id": None if fold is None else fold["fold_id"],
            "boundary": boundary, "usage": usage, "feature_usage": feature, "label_usage": label,
            "recorded_fit_executed": fit, "fit_origin": origin, "sample_refs": refs, "price_row_refs": price_refs,
            "recorded_sample_count": len(refs), "actual_used_count": len(refs) if usage == "ACTUAL" else 0,
            "recorded_price_slot_count": len(price_refs), "actual_used_price_slot_count": len(price_refs) if usage == "ACTUAL" else 0,
            "models": _model_metadata(models), "selected_recipe": deepcopy(recipe),
            "support_counts": _sample_support(records, refs, bars), "price_support_counts": support,
            "unavailable_reason": reason})

    def inner_stages(window, fold):
        scope = "FINAL_DEV" if fold is None else "OUTER_FOLD"
        common = {"scope": scope, "fold": fold, "boundary": window["training_boundary"], "reason": window["unavailable_reason"]}
        members = _inner_models(window, selected) if available else []
        recipe = window["selected_recipe"]
        add("INNER_MODEL_TRAINING", window["training_keys"], **common, fit=True,
            origin="INNER_FIXED_MODEL_FIT" if module is threshold else "INNER_FAMILY_FITS", models=members, recipe=recipe)
        add("INNER_TRAIN_PURGED", window["purged_keys"], **common,
            usage="PURGED", feature="EXCLUDED", label="EXCLUDED", origin="NOT_FITTED")
        if module is inner:
            add("INNER_HOLDOUT_PREDICTION", window["validation_keys"], **common,
                label="ASSOCIATED_ONLY", models=members, recipe=recipe)
            add("INNER_TARGET_SCORE", [row["observation_key"] for row in window["scored_targets"]], **common,
                feature="VIA_RECORDED_PREDICTION", models=members, recipe=recipe)
        else:
            prices = _references([(session["trading_day"], slot) for session in window["sessions"]
                                  for slot in range(session["bar_count"])], by_slot, "economic price slots")
            add("INNER_ECONOMIC_HOLDOUT", window["validation_keys"], **common, feature="VIA_RECORDED_DECISION",
                label="NOT_USED_BY_OBJECTIVE", models=members, recipe=recipe, prices=prices)

    for index, (fold, packet) in enumerate(zip(prepared.context["folds"], outer, strict=True)):
        common = {"scope": "OUTER_FOLD", "fold": fold, "boundary": fold["training_boundary"]}
        models, recipe = [], None
        if available:
            recipe = packet["strategy"]
            model_recipe = selected["reference"]["strategy"] if module is threshold else recipe
            models = [{"model_index": None, "model": packet["model"], "recipe": model_recipe}]
        origin = ("ORDINARY_FOLD_FIT" if module is None else
                  "REUSED_FIXED_SOURCE_MODEL" if module is threshold else "SELECTED_OUTER_REFIT")
        add("OUTER_MODEL_TRAINING", fold["training_keys"], **common,
            fit=module is not threshold, origin=origin, models=models, recipe=recipe)
        add("OUTER_TRAIN_PURGED", fold["purged_keys"], **common,
            usage="PURGED", feature="EXCLUDED", label="EXCLUDED", origin="NOT_FITTED")
        add("OUTER_PREDICTION", fold["validation_keys"], **common, label="ASSOCIATED_ONLY", models=models, recipe=recipe)
        scored = [key for key in fold["validation_keys"] if records[by_key[key]]["target"] is not None
                  and records[by_key[key]]["target"]["status"] == "COMPLETE"]
        add("OUTER_TARGET_SCORE", scored, **common, feature="VIA_RECORDED_PREDICTION", models=models, recipe=recipe)
        if module is not None:
            inner_stages(windows[index], fold)
    if module is not None:
        final = windows[-1]
        common = {"scope": "FINAL_DEV", "fold": None, "boundary": final["history_boundary"], "reason": final["unavailable_reason"]}
        add("FINAL_DEV_REFIT_ELIGIBLE_HISTORY", final["history_training_keys"], **common,
            usage="ELIGIBLE_FOR_LATER_FIT", feature="ELIGIBLE_ONLY", label="ELIGIBLE_ONLY",
            origin="LATER_FIT_NOT_PERFORMED", recipe=final["selected_recipe"])
        add("FINAL_DEV_HISTORY_PURGED", final["history_purged_keys"], **common,
            usage="PURGED", feature="EXCLUDED", label="EXCLUDED", origin="NOT_FITTED")
        inner_stages(final, None)
    return stages


def analyze_intraday_sample_usage(snapshot: StrategyExperiment, plan: dict, *, cost_index: int = 0,
                                 candidate_index: int = 0, intraday_data_file: str | Path | None = None,
                                 base: str | Path | None = None) -> dict:
    """Bind one saved DEV source to one strictly verified Q5 and Q47 capture."""
    selected = _saved_ml_source(snapshot, cost_index=cost_index, candidate_index=candidate_index)
    normalized = market.parse_intraday_market_evidence_plan(plan, base=base)
    prepared, outer, windows = _bound_inputs(selected, intraday_data_file)
    evidence = dependencies._analyze_verified(prepared.data, normalized)
    stages = _stages(selected, prepared, outer, windows, evidence)
    root, source = selected["root"], selected["source"]
    captured = evidence["market_evidence"]
    available = selected["module"] is None or root["report"]["status"] == "AVAILABLE"
    actual = [stage for stage in stages if stage["usage"] == "ACTUAL"]
    result = {"version": INTRADAY_SAMPLE_USAGE_VERSION, "status": "AVAILABLE" if available else "DECLARED_ONLY",
        "source": {"source_kind": selected["kind"], "source_schema_version": root["artifact_schema_version"],
            "experiment_id": root["experiment_id"], "content_sha256": sha256(snapshot.content).hexdigest(),
            "ordinary_source_id": source["experiment_id"], "source_report_id": root["report"][selected["report_key"]],
            "study_status": "AVAILABLE" if available else "UNAVAILABLE", "source_selection": deepcopy(selected["selection"]),
            "algorithm_versions": deepcopy(root["algorithm_versions"])},
        "binding": {"data_id": prepared.data.data_id, "data_content_sha256": captured["data"]["content_sha256"],
            "context_id": prepared.context["context_id"], "plan_id": captured["plan_id"],
            "market_evidence_id": captured["market_evidence_id"], "dependency_evidence_id": evidence["market_dependencies_id"],
            "context_matches": True, "window_inputs_match": True, "all_recorded_keys_resolved": True},
        "analysis_actions": {"q5_strict_verification_count": 1, "context_reconstructed": True,
            "window_input_facts_reconstructed": True, "models_refitted": False, "selection_rerun": False,
            "execution_replayed": False, "full_research_replay": False, "source_or_data_written": False},
        "context": prepared.context,
        "summary": {"stage_count": len(stages),
            "recorded_sample_memberships": sum(row["recorded_sample_count"] for row in stages),
            "actual_used_sample_memberships": sum(row["actual_used_count"] for row in stages),
            "unique_recorded_sample_count": len({index for row in stages for index in row["sample_refs"]}),
            "unique_actual_used_sample_count": len({index for row in actual for index in row["sample_refs"]}),
            "declared_only_stage_count": sum(row["usage"] == "DECLARED_NOT_EXECUTED" for row in stages)},
        "stages": stages, "dependency_evidence": evidence,
        "limitations": ["This binds recorded sample uses and non-fitted inputs; it does not prove saved fitted coefficients by replay.",
            "Sample memberships across stages or shared model families are not independent samples.",
            "Feature windows and target-completeness intervals are conservative support exposure, not numerical sensitivity.",
            "Endpoint disagreement and incomplete evidence can overlap; known session-end target shortfalls are preserved separately.",
            "Economic price-field disagreement uses open/close comparisons; other bar differences do not imply changed execution or returns.",
            "Stage usage distinguishes consumed inputs, associated target evidence, exclusions and eligibility for a later fit.",
            "No samples, Features, targets, models, decisions or accounts are changed; no TEST performance is computed."]}
    return {**result, "sample_usage_id": q5.digest(result)}


def run_intraday_sample_usage(source_path: str | Path, manifest_path: str | Path, *, cost_index: int = 0,
                             candidate_index: int = 0, intraday_data_file: str | Path | None = None) -> dict:
    """Read an explicit saved source and Q46 manifest, retaining captured IDs."""
    path = Path(manifest_path).absolute()
    snapshot = load_strategy_experiment(source_path)
    return analyze_intraday_sample_usage(snapshot, comparison.read_json_file(path), cost_index=cost_index,
        candidate_index=candidate_index, intraday_data_file=intraday_data_file, base=path.parent)
