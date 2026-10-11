"""Fixed-fit single-day objective sensitivity of saved Q25/Q31/Q36 choices.

Only the contribution to the original five-day inner objective is removed.
Saved models, predictions and daily accounts stay fixed; no source is read,
model refitted or execution replayed. Counts are descriptive, not probabilities.
"""

from __future__ import annotations

from copy import deepcopy
import math

from . import intraday_inner_selection as inner
from . import intraday_joint_selection as joint
from .intraday_data import digest
from .intraday_ml_diagnostics import _saved_ml_source
from .intraday_risk_diagnostics import _metric
from .strategy_experiment import StrategyExperiment


INTRADAY_INNER_OBJECTIVE_SENSITIVITY_VERSION = "market-vault-intraday-inner-objective-sensitivity-v1"


def _choice(objectives, *, maximize, unit, selected_index=None):
    failed = next((row["unavailable_reason"] for row in objectives if row["value"] is None), None)
    result = {"status": "UNAVAILABLE" if failed else "AVAILABLE", "unavailable_reason": failed,
              "objectives": objectives, "selected_index": None, "selected_recipe": None,
              "runner_up_index": None, "margin": _metric(None, unit, failed)}
    if failed:
        return result
    # Stable ordering gives exact ties to the first declared family member.
    ranked = sorted(range(len(objectives)), key=lambda index: objectives[index]["value"], reverse=maximize)
    chosen = ranked[0] if selected_index is None else selected_index
    runner = next(index for index in ranked if index != chosen)
    margin = (objectives[chosen]["value"] - objectives[runner]["value"] if maximize
              else objectives[runner]["value"] - objectives[chosen]["value"])
    result.update(selected_index=chosen, selected_recipe=deepcopy(objectives[chosen]["recipe"]), runner_up_index=runner,
                  margin=_metric(margin, unit) if math.isfinite(margin) else _metric(None, unit, "NUMERIC_OVERFLOW"))
    return result


def _member_objective(member, recipe, unit, *, targets=None, omitted_day=None, maximize=False):
    reason, value = None, None
    if not maximize and targets == []:
        reason = "NO_REMAINING_COMPLETE_TARGETS"
    else:
        try:
            value = (math.prod(1 + row["return"] for row in member["execution"]["daily"]
                               if row["trading_day"] != omitted_day) - 1 if maximize
                     else inner.pooled_mse(member["predictions"], targets))
            if not math.isfinite(value):
                raise OverflowError("the remaining fixed objective is not finite")
        except (ArithmeticError, ValueError):
            # Inputs have already passed the immutable study grammar. Q25's
            # pooled_mse reports nonfinite arithmetic as ValueError as well.
            value, reason = None, "NUMERIC_OVERFLOW"
    return {"candidate_index": member["candidate_index"], "recipe": deepcopy(recipe),
            "value": value, "unit": unit, "unavailable_reason": reason}


def _window_sensitivity(window, *, maximize, source_strategy, window_index, fold_index=None, fold_id=None,
                        joint_family=False):
    unit = "RATIO" if maximize else "SQUARED_RATIO"
    family = window["family_results"]
    recipes = [{**source_strategy, "threshold": member["threshold"]} if maximize and not joint_family else member["strategy"]
               for member in family]
    objective = {"name": "NET_COMPOUNDED_RETURN" if maximize else "POOLED_COMPLETE_MSE", "unit": unit,
                 "direction": "MAXIMIZE" if maximize else "MINIMIZE",
                 "aggregation": "ORDERED_PRODUCT_OF_REMAINING_DAILY_GROSS_RETURNS" if maximize
                                else "REMAINING_COMPLETE_TARGET_ROW_WEIGHTED"}
    original = [{"candidate_index": member["candidate_index"], "recipe": deepcopy(recipe),
                 "value": member["execution"]["metrics"]["total_return"] if maximize else member["mse"],
                 "unit": unit, "unavailable_reason": None}
                for member, recipe in zip(family, recipes, strict=True)]
    # Preserve the recorded winner and its original arithmetic. Recompounding
    # Q31's daily ratios can differ in the last bit from saved final cash.
    original = _choice(original, maximize=maximize, unit=unit, selected_index=window["selected_index"])
    omissions = []
    for day in window["validation_days"]:
        targets = None if maximize else [row for row in window["scored_targets"] if row["trading_day"] != day]
        removed = None if maximize else len(window["scored_targets"]) - len(targets)
        objectives = [_member_objective(member, recipe, unit, targets=targets, omitted_day=day, maximize=maximize)
                      for member, recipe in zip(family, recipes, strict=True)]
        row = _choice(objectives, maximize=maximize, unit=unit)
        row.update(omitted_day=day, remaining_days=[value for value in window["validation_days"] if value != day],
                   removed_complete_target_count=removed, remaining_complete_target_count=None if maximize else len(targets),
                   unchanged_reason="NO_SCORED_TARGETS_ON_OMITTED_DAY" if removed == 0 else None,
                   changed_choice=(row["selected_index"] != original["selected_index"]
                                   if row["status"] == "AVAILABLE" else None))
        omissions.append(row)
    return {"window_index": window_index, "scope": "FINAL_DEV" if fold_index is None else "OUTER_INNER",
            "fold_index": fold_index, "fold_id": fold_id, "validation_days": list(window["validation_days"]),
            "status": "AVAILABLE", "unavailable_reason": None, "objective": objective,
            "original": original, "omissions": omissions,
            "available_omission_count": sum(row["status"] == "AVAILABLE" for row in omissions),
            "changed_choice_count": sum(row["changed_choice"] is True for row in omissions),
            "selection_counts": [{"candidate_index": member["candidate_index"],
                                  "count": sum(row["selected_index"] == member["candidate_index"] for row in omissions)}
                                 for member in family],
            "fixed_evidence": deepcopy(window)}


def analyze_intraday_inner_objective_sensitivity(snapshot: StrategyExperiment) -> dict:
    """Remove each original inner day from its objective, with all fits fixed."""
    selected = _saved_ml_source(snapshot)
    root, source, module = selected["root"], selected["source"], selected["module"]
    if module is None:
        raise ValueError("inner objective sensitivity requires a saved Q25 or Q31 or Q36 selection study")
    report = root["report"]
    maximize = module is not inner
    key = selected["report_key"]
    result = {"version": INTRADAY_INNER_OBJECTIVE_SENSITIVITY_VERSION, "status": report["status"],
        "evaluation_scope": "DEVELOPMENT_INNER_OBJECTIVE_SENSITIVITY_ONLY",
        "experiment_id": root["experiment_id"], "data_id": root["dataset_id"], "source_kind": selected["kind"],
        "source_schema_version": root["artifact_schema_version"], "algorithm_versions": deepcopy(root["algorithm_versions"]),
        "ordinary_source_id": source["experiment_id"], "source_selection": selected["selection"],
        "selection_id": report[key], "source_evaluation_scope": report["evaluation_scope"],
        "evidence": {"scope": "RECORDED_FIXED_FIT_OBJECTIVE_DERIVATION", "source_reconstructed": False,
                     "models_refitted": False, "execution_replayed": False},
        "method": {"holdout_days": 5, "perturbation": "OMIT_EACH_DECLARED_INNER_DAY_ONCE",
                   "fixed_inputs": "ORIGINAL_MODELS_PREDICTIONS_AND_DAILY_ACCOUNTS",
                   "original_winner": "UNCHANGED_RECORDED_VALIDATED_OBJECTIVE", "tie_break": "FIRST_DECLARED",
                   "counts": "AVAILABLE_OMISSIONS_ONLY_DESCRIPTIVE_NOT_PROBABILITIES",
                   "inference": "NO_RETRAINING_JACKKNIFE_OR_SELECTION_PROBABILITY",
                   "scope": "OUTER_INNER_WINDOWS_AND_SEPARATELY_FINAL_DEV_NO_TEST"},
        "unavailable_reason": None, "unavailable_reasons": [], "windows": [], "sample": None}
    if report["status"] != "AVAILABLE":
        result.update(unavailable_reason="SOURCE_STUDY_UNAVAILABLE",
                      unavailable_reasons=deepcopy(report["unavailable_reasons"]))
    else:
        windows = [_window_sensitivity(record["inner"], maximize=maximize, source_strategy=selected["reference"]["strategy"],
                       window_index=index, fold_index=index, fold_id=record["fold_id"], joint_family=module is joint)
                   for index, record in enumerate(report["outer_folds"])]
        windows.append(_window_sensitivity(report["final_dev"], maximize=maximize,
                       source_strategy=selected["reference"]["strategy"], window_index=len(windows), joint_family=module is joint))
        result.update(windows=windows, sample={"outer_window_count": len(windows) - 1,
                      "final_dev_window_count": 1, "omission_count": sum(len(row["omissions"]) for row in windows)})
    result["sensitivity_id"] = digest(result)
    return result
