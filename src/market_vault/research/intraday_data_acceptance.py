"""Bounded policy judgment over freshly reconstructed Q5/Q44/Q46 evidence.

A satisfied policy is neither market-accuracy certification nor permission to
trade. This module never accepts a saved comparison as an admission shortcut.
"""

from __future__ import annotations

from pathlib import Path

from ..quality import market_data_comparison as comparison
from . import intraday_market_evidence as evidence
from . import intraday_market_dependencies as dependencies
from .intraday_data import IntradayDataset, digest, load_intraday_dataset, verify_intraday_dataset


INTRADAY_DATA_ACCEPTANCE_POLICY_VERSION = "market-vault-intraday-data-acceptance-policy-v1"
INTRADAY_DATA_ACCEPTANCE_VERSION = "market-vault-intraday-data-acceptance-v1"


def normalize_intraday_acceptance_policy(value: dict) -> dict:
    comparison.require_fields(value, ("schema_version",),
                              optional=("scope", "tolerances", "require_declared_distinct_observed"),
                              label="intraday data-acceptance policy")
    if value["schema_version"] != INTRADAY_DATA_ACCEPTANCE_POLICY_VERSION:
        raise ValueError("unsupported intraday data-acceptance policy version")
    if value.get("scope", "FULL_Q5_GRID") != "FULL_Q5_GRID":
        raise ValueError("acceptance scope must be FULL_Q5_GRID; no date intersection or sample removal")
    declared = value.get("require_declared_distinct_observed", True)
    if type(declared) is not bool:
        raise ValueError("require_declared_distinct_observed must be a boolean")
    return {"schema_version": INTRADAY_DATA_ACCEPTANCE_POLICY_VERSION,
            "scope": "FULL_Q5_GRID", "tolerances": comparison.normalize_tolerances(value.get("tolerances")),
            "require_declared_distinct_observed": declared}


def _local_inspections(root, plan):
    """Use Q44 validity over every Q5 session, even with no external reference.

    Q46 intentionally leaves unreferenced prices UNASSESSED. That is not enough
    for a policy that rejects invalid local OHLC regardless of reference access.
    Inspect the verified price view, not the saved Feature/sample projection.
    """
    prices = {session["trading_day"]: [] for session in root["report"]["sessions"]}
    for row in root["report"]["prices"]:
        prices[row["trading_day"]].append(row)
    result = []
    for session in root["report"]["sessions"]:
        scope = {"symbol": root["report"]["symbol"], "interval": root["report"]["interval"],
                 "adjustment": "NONE", "session": "RTH", **plan["basis"],
                 "window_start": comparison.utc_text(comparison.parse_utc(session["open_time"])),
                 "window_end": comparison.utc_text(comparison.parse_utc(session["close_time"]))}
        left = evidence._left_snapshot(root, plan, scope, prices[session["trading_day"]])
        _, inspection = comparison._input(left)
        result.append({"trading_day": session["trading_day"], "inspection": inspection})
    return result


def _decide(fresh_evidence, local_inspections, policy):
    """Internal reducer; public callers must first reconstruct source evidence."""
    rejected, missing = [], []
    summary = fresh_evidence["summary"]
    if summary["local_missing_slots"]:
        rejected.append({"reason": "MISSING_REQUIRED_LOCAL_PRICES", "count": summary["local_missing_slots"]})
    bad_days = [row["trading_day"] for row in local_inspections if row["inspection"]["status"] != "VALID"]
    if bad_days:
        rejected.append({"reason": "INVALID_LOCAL_INPUT", "trading_days": bad_days})
    bad_references = [ref["reference_index"] for ref in fresh_evidence["references"]
                      if ref["comparison"]["inputs"]["right"]["status"] == "INVALID_INPUT"]
    if bad_references:
        rejected.append({"reason": "INVALID_REFERENCE_INPUT", "reference_indices": bad_references})
    if summary["counts"]["DIFFERENT"]:
        rejected.append({"reason": "NUMERICAL_DISAGREEMENT", "count": summary["counts"]["DIFFERENT"]})
    gap = summary["expected_slots"] - summary["numerically_compared_slots"]
    if gap:
        missing.append({"reason": "INCOMPLETE_NUMERICAL_COVERAGE", "count": gap})
    if policy["require_declared_distinct_observed"]:
        local_kind = fresh_evidence["plan"]["source"]["data_kind"]
        if local_kind == "SYNTHETIC":
            rejected.append({"reason": "SYNTHETIC_LOCAL_SOURCE"})
        elif local_kind != "OBSERVED":
            missing.append({"reason": "LOCAL_SOURCE_NATURE_UNKNOWN"})
        for ref in fresh_evidence["references"]:
            right_source = ref["comparison"]["inputs"]["right"].get("source")
            # Missing/invalid files already have distinct coverage/input reasons.
            if right_source is None:
                continue
            state = ref["independence"]["status"]
            item = {"reference_index": ref["reference_index"]}
            if right_source["data_kind"] == "SYNTHETIC":
                rejected.append({"reason": "SYNTHETIC_REFERENCE_SOURCE", **item})
            elif state == "SHARED_UPSTREAM":
                rejected.append({"reason": "SHARED_DECLARED_UPSTREAM", **item})
            elif right_source["data_kind"] != "OBSERVED" or state != "CLAIMED_DISTINCT":
                missing.append({"reason": "DISTINCT_OBSERVED_SOURCE_DECLARATION_MISSING", **item})
    status = "REJECTED" if rejected else "NEEDS_EVIDENCE" if missing else "POLICY_SATISFIED"
    return status, rejected, missing


def analyze_intraday_data_acceptance(data: IntradayDataset | str | Path, manifest: dict,
                                    policy: dict, *, base: str | Path | None = None) -> dict:
    """Verify once and judge the complete declared Q5 grid against a policy.

    Defaults require full coverage, no invalid/missing/duplicate required input,
    zero tolerances and observed/distinct *declarations*. Nondefault tolerances
    must be explicit and equal in both the policy and Q46 manifest. Numerical
    and declared-source conditions never verify actual source independence.
    """
    policy = normalize_intraday_acceptance_policy(policy)
    plan = evidence.parse_intraday_market_evidence_plan(manifest, base=base)
    if plan["tolerances"] != policy["tolerances"]:
        raise ValueError("manifest tolerances differ from the explicit acceptance policy")
    snapshot = verify_intraday_dataset(data) if type(data) is IntradayDataset else load_intraday_dataset(data)
    root = snapshot.as_dict()
    support = dependencies._analyze_verified(snapshot, plan)
    checked = support["market_evidence"]
    local = _local_inspections(root, plan)
    status, rejected, missing = _decide(checked, local, policy)
    result = {"version": INTRADAY_DATA_ACCEPTANCE_VERSION, "status": status,
              "evaluation_scope": "EXPLICIT_FULL_Q5_GRID_POLICY_ONLY",
              "data_id": root["data_id"], "policy": policy, "policy_id": digest(policy),
              "market_evidence_id": checked["market_evidence_id"],
              "market_dependencies_id": support["market_dependencies_id"],
              "summary": checked["summary"], "rejections": rejected, "evidence_gaps": missing,
              "source_assurance": {"evidence_scope": "SOURCE_DECLARATIONS_ONLY", "independence_verified": False,
                                   "independence_counts": checked["summary"]["independence_counts"]},
              "market_accuracy_certified": False, "local_inspections": local, "dependencies": support,
              "limitations": [
                  "POLICY_SATISFIED means only the recorded numerical, coverage and optional declaration conditions hold.",
                  "Caller declarations do not independently establish observed provenance or source independence.",
                  "FULL_Q5_GRID includes all Q5 dates, prices and recorded dependencies, including any reserved TEST dates, not TEST performance.",
                  "Viewing full-grid evidence is not a certificate that TEST information has remained unseen.",
                  "Q47 whole-window support is conservative dependency exposure, not measured Feature or strategy sensitivity.",
                  "Partial, missing, invalid and disagreeing evidence is retained; no sample is removed or repaired.",
                  "No strategy is fitted, scored, promoted or authorized for trading; existing research and TEST gates are unchanged.",
                  "Policy identity binds canonical policy content, not a claim of prior registration or an external timestamp.",
              ]}
    return {**result, "acceptance_id": digest(result)}


def run_intraday_data_acceptance(data_path: str | Path, manifest_path: str | Path,
                                policy_path: str | Path) -> dict:
    manifest = comparison.read_json_file(manifest_path)
    policy = comparison.read_json_file(policy_path)
    return analyze_intraday_data_acceptance(data_path, manifest, policy, base=Path(manifest_path).absolute().parent)
