"""Cost sensitivity of saved Q31/Q36 inner economic choices.

The original models, forecasts, family and full inner price grids stay fixed.
Only Q6 reexecutes. These descriptive inner choices do not form new outer
accounts, source replay, fitted recipes or candidates eligible for Freeze.
"""

from __future__ import annotations

from copy import deepcopy

from ..backtest.intraday import (
    INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION, IntradayExecutionPolicy, run_intraday_execution,
)
from .intraday_data import canonical_json, digest
from .intraday_ml_diagnostics import _saved_ml_source
from .intraday_threshold_selection import threshold_predictions
from .strategy_experiment import StrategyExperiment


INTRADAY_INNER_COST_SENSITIVITY_VERSION = "market-vault-intraday-inner-cost-sensitivity-v1"
ADDITIONAL_SLIPPAGE_BPS = (0, 5, 10)


def _choice(members, reason=None, detail=None):
    failed = [row for row in members if row["status"] != "AVAILABLE"]
    if reason is None and (failed or not members):
        reason = "INCOMPLETE_INNER_FAMILY"
        detail = "; ".join(f"member {row['candidate_index']}: {row['unavailable_reason']}: {row['detail']}"
                           for row in failed) or "The saved window has no executed family."
    result = {"status": "UNAVAILABLE" if reason else "AVAILABLE", "unavailable_reason": reason, "detail": detail,
        "selected_index": None, "selected_recipe": None, "runner_up_index": None,
        "best_runner_up_gap": None, "tied_best_indices": []}
    if reason is None:
        # Stable ordering preserves FIRST_DECLARED, including an exact tie
        # for second place. The gap does not skip equally best members.
        ranked = sorted(members, key=lambda row: row["metrics"]["total_return"], reverse=True)
        best, runner = ranked[:2]
        value = best["metrics"]["total_return"]
        result.update(selected_index=best["candidate_index"], selected_recipe=deepcopy(best["recipe"]),
            runner_up_index=runner["candidate_index"], best_runner_up_gap=value - runner["metrics"]["total_return"],
            tied_best_indices=[row["candidate_index"] for row in members if row["metrics"]["total_return"] == value])
    return result


def _execute_members(window, recipes, streams, policy_record, interval, *, reason=None, detail=None):
    policy = None
    if reason is None:
        try:
            policy = IntradayExecutionPolicy(**policy_record)
        except (ValueError, ArithmeticError) as exc:
            reason, detail = "SCENARIO_POLICY_UNAVAILABLE", str(exc)
    members = []
    for saved, recipe, decisions in zip(window["family_results"], recipes, streams, strict=True):
        execution, failure, explanation = None, reason, detail
        if failure is None:
            try:
                # Full saved sessions are identity-bearing inputs. Projecting
                # them to clock geometry would change price_evidence_id.
                execution = run_intraday_execution(sessions=tuple(window["sessions"]), prices=tuple(window["prices"]),
                    decisions=decisions, interval=interval, policy=policy)
            except (ValueError, ArithmeticError) as exc:
                failure = "NUMERIC_OVERFLOW" if isinstance(exc, ArithmeticError) else "INNER_REEXECUTION_FAILED"
                explanation = str(exc)
        members.append({"candidate_index": saved["candidate_index"], "recipe": deepcopy(recipe),
            "source_execution_id": saved["execution"]["execution_id"],
            "status": "UNAVAILABLE" if failure else "AVAILABLE", "unavailable_reason": failure, "detail": explanation,
            "execution": execution, "metrics": None if execution is None else deepcopy(execution["metrics"])})
    return members, reason, detail


def _baseline(window, members, *, source_unavailable):
    checks = []
    for saved, member in zip(window["family_results"], members, strict=True):
        original, execution = saved["execution"], member["execution"]
        matches = None if execution is None else canonical_json(original) == canonical_json(execution)
        fields = ([] if matches or execution is None else [key for key in sorted(original.keys() | execution.keys())
            if canonical_json(original.get(key)) != canonical_json(execution.get(key))])
        checks.append({"candidate_index": saved["candidate_index"], "source_execution_id": original["execution_id"],
            "reexecuted_execution_id": None if execution is None else execution["execution_id"], "matches": matches,
            "different_fields": fields, "unavailable_reason": member["unavailable_reason"] if execution is None
                else None if matches else "COMPLETE_ACCOUNT_MISMATCH", "detail": member["detail"]})
    choice = _choice(members)
    checked = choice["status"] == "AVAILABLE"
    index_matches = choice["selected_index"] == window["selected_index"] if checked else None
    recipe_matches = (canonical_json(choice["selected_recipe"]) == canonical_json(window["selected_recipe"])
                      if checked else None)
    reason = ("SOURCE_STUDY_UNAVAILABLE" if source_unavailable else "ZERO_ADDED_COST_REPRODUCTION_FAILED"
              if any(row["matches"] is not True for row in checks) or not index_matches or not recipe_matches else None)
    detail = ("The saved study did not execute its inner families." if source_unavailable else
              "Every complete original Q6 account, selected index and full recipe must reproduce." if reason else None)
    return {"status": "UNAVAILABLE" if reason else "AVAILABLE", "unavailable_reason": reason, "detail": detail,
        "excluded_identity_fields": [], "member_checks": checks, "selected_index_matches": index_matches,
        "selected_recipe_matches": recipe_matches, "reexecuted_selected_index": choice["selected_index"],
        "reexecuted_selected_recipe": choice["selected_recipe"]}


def _window_sensitivity(window, *, source_strategy, source_policy, source_status, interval, joint_family,
                        declared_family_size, window_index, fold_index=None, fold_id=None):
    family = window["family_results"]
    recipes = [row["strategy"] if joint_family else {**source_strategy, "threshold": row["threshold"]} for row in family]
    streams = [tuple(threshold_predictions(window["models"][row["model_index"]]["predictions"] if joint_family
                    else window["predictions"], recipe["threshold"])) for row, recipe in zip(family, recipes, strict=True)]
    source_unavailable = source_status != "AVAILABLE"
    reason = "SOURCE_STUDY_UNAVAILABLE" if source_unavailable else None
    detail = "The saved study did not execute its inner families." if source_unavailable else None
    zero, _, _ = _execute_members(window, recipes, streams, source_policy, interval, reason=reason, detail=detail)
    baseline = _baseline(window, zero, source_unavailable=source_unavailable)
    scenarios = []
    for additional in ADDITIONAL_SLIPPAGE_BPS:
        policy = {**source_policy, "slippage_bps": source_policy["slippage_bps"] + additional}
        failure, explanation = baseline["unavailable_reason"], baseline["detail"]
        if additional == 0:
            members = zero  # Reuse all verified baseline executions; do not run Q6 twice.
        else:
            members, failure, explanation = _execute_members(window, recipes, streams, policy, interval,
                                                             reason=failure, detail=explanation)
        choice = _choice(members, failure, explanation)
        scenarios.append({"additional_slippage_bps": additional, "execution_policy": policy, **choice,
            "changed_choice": choice["selected_index"] != window["selected_index"] if choice["status"] == "AVAILABLE" else None,
            "member_counts": {"declared": declared_family_size, "recorded": len(family),
                "executed": sum(row["execution"] is not None for row in members),
                "available": sum(row["status"] == "AVAILABLE" for row in members)}, "members": members})
    available = sum(row["status"] == "AVAILABLE" for row in scenarios)
    return {"window_index": window_index, "scope": "FINAL_DEV" if fold_index is None else "OUTER_FOLD",
        "fold_index": fold_index, "fold_id": fold_id, "validation_days": list(window["validation_days"]),
        "source_unavailable_reason": window["unavailable_reason"],
        "status": "AVAILABLE" if available == len(scenarios) else "PARTIAL" if available else "UNAVAILABLE",
        "original": {"selected_index": window["selected_index"], "selected_recipe": deepcopy(window["selected_recipe"])},
        "baseline": baseline, "scenarios": scenarios, "fixed_evidence": deepcopy(window)}


def _choice_changes(windows):
    counts = []
    for scope in ("OUTER_FOLD", "FINAL_DEV"):
        scoped = [row for row in windows if row["scope"] == scope]
        for index, additional in enumerate(ADDITIONAL_SLIPPAGE_BPS):
            scenarios = [row["scenarios"][index] for row in scoped]
            available = [row for row in scenarios if row["status"] == "AVAILABLE"]
            changed = sum(row["changed_choice"] for row in available) if available else None
            reason = ("NO_ELIGIBLE_WINDOWS" if not available else
                      "INCOMPLETE_WINDOW_COVERAGE" if len(available) < len(scoped) else None)
            counts.append({"scope": scope, "additional_slippage_bps": additional,
                "status": "UNAVAILABLE" if not available else "PARTIAL" if reason else "AVAILABLE",
                "unavailable_reason": reason, "declared_window_count": len(scoped),
                "eligible_window_count": len(available), "unavailable_window_count": len(scoped) - len(available),
                "changed_choice_count": changed, "changed_choice_rate": changed / len(available) if available else None})
    return counts


def analyze_intraday_inner_cost_sensitivity(snapshot: StrategyExperiment) -> dict:
    """Reexecute the complete saved inner family at exactly +0/+5/+10 bp."""
    selected = _saved_ml_source(snapshot)
    if selected["kind"] not in ("ECONOMIC_THRESHOLD_SELECTION", "JOINT_ECONOMIC_SELECTION"):
        raise ValueError("inner cost sensitivity requires an explicit saved Q31 or Q36 economic selection study")
    root, source, context = selected["root"], selected["source"], selected["context"]
    report = root["report"]
    joint_family = selected["kind"] == "JOINT_ECONOMIC_SELECTION"
    family_size = len(report["method"]["family" if joint_family else "thresholds"])
    options = {"source_strategy": selected["reference"]["strategy"], "source_policy": selected["group"]["execution_policy"],
        "source_status": report["status"], "interval": context["interval"], "joint_family": joint_family,
        "declared_family_size": family_size}
    windows = [_window_sensitivity(record["inner"], window_index=index, fold_index=index, fold_id=record["fold_id"], **options)
               for index, record in enumerate(report["outer_folds"])]
    windows.append(_window_sensitivity(report["final_dev"], window_index=len(windows), **options))
    failures = [{"window_index": window["window_index"], "scope": window["scope"], "fold_index": window["fold_index"],
        "additional_slippage_bps": scenario["additional_slippage_bps"], "reason": scenario["unavailable_reason"],
        "detail": scenario["detail"]} for window in windows for scenario in window["scenarios"] if scenario["status"] != "AVAILABLE"]
    scenario_count = len(windows) * len(ADDITIONAL_SLIPPAGE_BPS)
    reason = ("SOURCE_STUDY_UNAVAILABLE" if report["status"] != "AVAILABLE" else
              "INNER_SCENARIOS_UNAVAILABLE" if failures else None)
    result = {"version": INTRADAY_INNER_COST_SENSITIVITY_VERSION,
        "status": "AVAILABLE" if not failures else "UNAVAILABLE" if len(failures) == scenario_count else "PARTIAL",
        "evaluation_scope": "DEVELOPMENT_INNER_COST_SENSITIVITY_ONLY", "experiment_id": root["experiment_id"],
        "data_id": root["dataset_id"], "ordinary_source_id": source["experiment_id"], "source_kind": selected["kind"],
        "source_schema_version": root["artifact_schema_version"], "algorithm_versions": deepcopy(root["algorithm_versions"]),
        "selection_id": report[selected["report_key"]], "source_selection": deepcopy(selected["selection"]),
        "source_evaluation_scope": report["evaluation_scope"], "source_status": report["status"],
        "source_unavailable_reasons": deepcopy(report["unavailable_reasons"]), "source_method": deepcopy(report["method"]),
        "context": deepcopy(context), "return_basis": deepcopy(report["return_basis"]),
        "evidence": {"scope": "RECORDED_INNER_FIXED_FORECAST_REEXECUTION", "source_reconstructed": False,
            "models_refitted": False, "forecasts_changed": False, "execution_replayed": report["status"] == "AVAILABLE",
            "outer_execution_replayed": False, "test_evaluated": False},
        "method": {"additional_slippage_bps": list(ADDITIONAL_SLIPPAGE_BPS), "cost_application": "ADDITIONAL_PER_FILL_SLIPPAGE",
            "fixed_inputs": "ORIGINAL_MODELS_FORECASTS_SUPPORT_PRICES_FAMILY_AND_OTHER_POLICY_FIELDS",
            "execution_version": INTRADAY_EXECUTION_VERSION, "cost_version": INTRADAY_COST_VERSION,
            "zero_baseline": "COMPLETE_CANONICAL_ACCOUNTS_AND_ORIGINAL_INDEX_AND_RECIPE",
            "failed_member": "WHOLE_WINDOW_SCENARIO_UNAVAILABLE_NO_REDUCED_FAMILY",
            "selection_metric": "MAXIMUM_INNER_NET_COMPOUNDED_RETURN", "tie_break": "FIRST_DECLARED",
            "objective_and_gap_unit": "RATIO", "cost_unit": "NORMALIZED_CASH",
            "counts": "AVAILABLE_COMPLETE_WINDOWS_ONLY_OUTER_FOLD_AND_FINAL_DEV_SEPARATE",
            "inference": "DESCRIPTIVE_INNER_GAP_NO_OUTER_EFFECT_CONFIDENCE_OR_PROMOTION",
            "scope": "ORIGINAL_INNER_WINDOWS_AND_FINAL_DEV_DIAGNOSTIC_ONLY_NO_FREEZE_OR_TEST"},
        "sample": {"outer_window_count": len(windows) - 1, "final_dev_window_count": 1, "family_size": family_size,
            "scenario_count": scenario_count, "available_scenario_count": scenario_count - len(failures)},
        "unavailable_reason": reason, "unavailable_reasons": failures, "windows": windows,
        "choice_changes": _choice_changes(windows)}
    result["sensitivity_id"] = digest(result)
    return result
