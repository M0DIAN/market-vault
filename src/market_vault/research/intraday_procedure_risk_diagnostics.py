"""Descriptive outer risk paths of an explicitly saved selection procedure.

Each role keeps its actual recorded account. Independent account diagnostics
remain inspectable when their common basis cannot support a comparison.
No source data, fitted model, selection, execution or TEST is reconstructed.
"""

from __future__ import annotations

from copy import deepcopy

from .intraday_data import digest
from .intraday_procedure_comparison import _accounts, _member, _procedure
from .intraday_procedure_return_uncertainty import ACCOUNT_ORDER, _account_basis
from .intraday_return_uncertainty import _sample_coverage
from .intraday_risk_diagnostics import INTRADAY_RISK_DIAGNOSTICS_VERSION, _available
from .strategy_experiment import StrategyExperiment


INTRADAY_PROCEDURE_RISK_DIAGNOSTICS_VERSION = "market-vault-intraday-procedure-risk-diagnostics-v1"


def analyze_intraday_procedure_risk_diagnostics(snapshot: StrategyExperiment) -> dict:
    """Describe all three saved outer accounts without treating excess as cash."""
    selected = _procedure(snapshot)
    root, source, context = selected["root"], selected["source"], selected["context"]
    report, accounts = root["report"], _accounts(selected)
    member = _member(selected, "procedure")
    # The account is captured once below; this member retains its complete
    # outer recipe and application/refit evidence without a duplicate ledger.
    member.pop("selected_account")
    result = {"version": INTRADAY_PROCEDURE_RISK_DIAGNOSTICS_VERSION, "status": "AVAILABLE",
        "evaluation_scope": "DEVELOPMENT_OUTER_PROCEDURE_RISK_DIAGNOSTICS_ONLY",
        "experiment_id": root["experiment_id"], "data_id": root["dataset_id"],
        "ordinary_source_id": source["experiment_id"], "source_kind": selected["kind"],
        "source_schema_version": root["artifact_schema_version"],
        "algorithm_versions": deepcopy(root["algorithm_versions"]),
        "selection_id": report[selected["report_key"]], "source_selection": deepcopy(selected["selection"]),
        "source_evaluation_scope": report["evaluation_scope"], "source_status": report["status"],
        "source_unavailable_reasons": deepcopy(report["unavailable_reasons"]),
        "context": deepcopy(context), "procedure": member, "accounts": deepcopy(accounts),
        "evidence": {"scope": "RECORDED_LEDGER_DERIVATION", "source_reconstructed": False,
                     "models_refitted": False, "decisions_reselected": False, "execution_replayed": False},
        "method": {"account_order": list(ACCOUNT_ORDER), "numerical_engine": INTRADAY_RISK_DIAGNOSTICS_VERSION,
            "risk_basis": "EACH_ACTUAL_RECORDED_ACCOUNT",
            "comparability": "COMPLETE_COMMON_BASIS_AND_ALL_ACCOUNT_DIAGNOSTICS_REQUIRED",
            "risk_differences": "NOT_COMPUTED_NO_EXCESS_ACCOUNT_OR_SUBTRACTED_DRAWDOWNS",
            "inference": "DESCRIPTIVE_ONLY_NO_RESAMPLING_OR_PROMOTION",
            "scope": "OUTER_DEV_ONLY_NO_INNER_FINAL_DEV_OR_TEST_ACCOUNTS"},
        "basis": None, "sample": None, "diagnostics": {}, "account_availability": {},
        "comparability": {}, "unavailable_reason": None, "detail": None}
    if report["status"] != "AVAILABLE":
        reason, detail = "SOURCE_STUDY_UNAVAILABLE", "The saved study has no available selected outer account."
        result["diagnostics"] = {name: {"status": "UNAVAILABLE", "unavailable_reason": reason,
                                         "detail": detail, "report": None} for name in ACCOUNT_ORDER}
    else:
        basis = _account_basis(selected, accounts)
        diagnostics = {name: _available(account["execution"], context["folds"], account.get("fold_contributions"))
                       for name, account in accounts.items()}
        failed = [name for name, item in diagnostics.items() if item["status"] != "AVAILABLE"]
        reason = "BASIS_MISMATCH" if not basis["matches"] else "ACCOUNT_DIAGNOSTICS_UNAVAILABLE" if failed else None
        detail = ("Recorded common outer basis differs: " + ", ".join(basis["failed_checks"]) if not basis["matches"] else
                  "; ".join(name + ": " + diagnostics[name]["unavailable_reason"] + ": " +
                            diagnostics[name]["detail"] for name in failed) if failed else None)
        result.update(basis=basis, diagnostics=diagnostics, sample={**_sample_coverage(context),
            "account_counts": {name: {"evaluated_day_count": len(account["execution"]["daily"]),
                "trade_count": account["execution"]["metrics"]["trade_count"],
                "cash_only_day_count": sum(row["trade_count"] == 0 for row in account["execution"]["daily"])}
                for name, account in accounts.items()}})
    available = sum(item["status"] == "AVAILABLE" for item in result["diagnostics"].values())
    result.update(status="AVAILABLE" if reason is None else "PARTIAL" if available else "UNAVAILABLE",
        unavailable_reason=reason, detail=detail,
        account_availability={"declared": len(ACCOUNT_ORDER), "available": available,
                              "unavailable": len(ACCOUNT_ORDER) - available},
        comparability={"status": "AVAILABLE" if reason is None else "UNAVAILABLE", "comparable": reason is None,
                       "unavailable_reason": reason, "detail": detail})
    result["diagnostics_id"] = digest(result)
    return result
