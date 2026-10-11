"""External bar evidence for the exact prices used by one verified Q5 dataset.

All declared Q5 sessions and slots remain in the report. Comparison results
describe the supplied observations; they do not certify a provider, repair
prices, select samples, fit a model, or establish an effect on strategy returns.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from ..quality import market_data_comparison as comparison
from .intraday_data import IntradayDataset, digest, load_intraday_dataset, verify_intraday_dataset


INTRADAY_MARKET_EVIDENCE_PLAN_VERSION = "market-vault-intraday-market-evidence-plan-v1"
INTRADAY_MARKET_EVIDENCE_VERSION = "market-vault-intraday-market-evidence-v1"
BASIS_FIELDS = ("asset_class", "currency", "aggregation", "volume_basis")
SLOT_STATUSES = ("MATCH", "DIFFERENT", "LEFT_ONLY", "RIGHT_ONLY", "BOTH_MISSING", "BLOCKED",
                 "UNASSESSED", "NOT_RUN", "INVALID_INPUT")
INDEPENDENCE_STATUSES = ("SYNTHETIC", "UNKNOWN", "SHARED_UPSTREAM", "CLAIMED_DISTINCT")


def _text(value, label):
    if (type(value) is not str or not value or value != value.strip()
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{label} must be a nonempty string without surrounding whitespace or controls")
    return value


def parse_intraday_market_evidence_plan(value: dict, *, base: str | Path | None = None) -> dict:
    """Normalize an explicit source declaration and finite reference list.

    References declare their scope independently of file availability. At most
    one reference window may name a trading day; no latest selection occurs.
    """
    comparison.require_fields(value, ("schema_version", "source", "basis", "references"),
                              optional=("tolerances",), label="intraday market-evidence plan")
    if value["schema_version"] != INTRADAY_MARKET_EVIDENCE_PLAN_VERSION:
        raise ValueError("unsupported intraday market-evidence plan version")
    source = comparison.normalize_source(value["source"])
    comparison.require_fields(value["basis"], BASIS_FIELDS, label="declared Q5 economic basis")
    basis = {key: _text(value["basis"][key], f"basis.{key}") for key in BASIS_FIELDS}
    if basis["asset_class"] not in {"EQUITY", "ETF"}:
        raise ValueError("basis.asset_class must be EQUITY or ETF")
    references = value["references"]
    if type(references) is not list:
        raise ValueError("references must be an explicit array, including [] when none are supplied")
    parent = Path.cwd() if base is None else Path(base).absolute()
    normalized, days = [], set()
    for item in references:
        comparison.require_fields(item, ("scope", "snapshot"), label="reference")
        scope = comparison.normalize_scope(item["scope"])
        day = comparison.parse_utc(scope["window_start"]).astimezone(comparison.NY).date().isoformat()
        if day in days:
            raise ValueError(f"multiple reference snapshots for trading day {day} are not supported")
        days.add(day)
        locator = item["snapshot"]
        if locator is not None:
            locator = str((parent / _text(locator, "reference.snapshot")).absolute())
        normalized.append({"scope": scope, "snapshot": locator})
    return {"schema_version": INTRADAY_MARKET_EVIDENCE_PLAN_VERSION, "source": source,
            "basis": basis, "references": normalized,
            "tolerances": comparison.normalize_tolerances(value.get("tolerances"))}


def _reference_scopes(root, plan):
    report = root["report"]
    sessions = {item["trading_day"]: item for item in report["sessions"]}
    expected = {"symbol": report["symbol"], "interval": report["interval"],
                "adjustment": "NONE", "session": "RTH", **plan["basis"]}
    result = {}
    for index, item in enumerate(plan["references"]):
        scope = item["scope"]
        changed = [key for key, value in expected.items() if scope[key] != value]
        if changed:
            raise ValueError("reference scope differs from Q5 symbol/interval/economic basis: " + ", ".join(changed))
        start, end = (comparison.parse_utc(scope[key]) for key in ("window_start", "window_end"))
        day = start.astimezone(comparison.NY).date().isoformat()
        if day not in sessions:
            raise ValueError(f"reference trading day {day} is outside the Q5 trading sessions")
        session = sessions[day]
        if not comparison.parse_utc(session["open_time"]) <= start < end <= comparison.parse_utc(session["close_time"]):
            raise ValueError("reference window is outside the verified Q5 session")
        result[day] = (index, item)
    return result


def _left_snapshot(root, plan, scope, prices):
    start, end = (comparison.parse_utc(scope[key]) for key in ("window_start", "window_end"))
    bars = []
    for price in prices:
        event = comparison.parse_utc(price["event_time"])
        if start <= event < end:
            bars.append({"start": comparison.utc_text(event),
                         "end": comparison.utc_text(comparison.parse_utc(price["available_at"])),
                         **{field: price[field] for field in comparison.VALUE_FIELDS},
                         "origin": {"data_id": root["data_id"],
                                    "canonical_row_version_id": price["row_version_id"]}})
    return {"schema_version": comparison.SNAPSHOT_SCHEMA_VERSION, "source": plan["source"],
            "scope": scope, "bars": bars,
            "origin": {"kind": "VERIFIED_INTRADAY_DATA_PRICE_VIEW", "data_id": root["data_id"],
                       "source_build_ids": root["source_build_ids"],
                       "source_evidence": "STRICT_Q5_SOURCE_RECONSTRUCTION"}}


def _compare_reference(root, plan, index, item, prices):
    left = _left_snapshot(root, plan, item["scope"], prices)
    # Q44's public entry points separately support two values or two files.
    # Reuse their common kernel for this memory/file pair: the file is captured
    # once and keeps Q44's missing-file, invalid-JSON and original-byte evidence.
    right = comparison._file_input(item["snapshot"])
    actual_scope = right[1].get("scope")
    if actual_scope is not None and actual_scope != item["scope"]:
        changed = [key for key in comparison.SCOPE_FIELDS if actual_scope[key] != item["scope"][key]]
        raise ValueError("reference snapshot scope differs from its explicit declaration: " + ", ".join(changed))
    report = comparison._compare(comparison._input(left), right, plan["tolerances"])
    independence = report["independence"]["status"]
    if independence == "DECLARED_DISTINCT_UPSTREAM":
        independence = "CLAIMED_DISTINCT"
    return {"reference_index": index, "scope": item["scope"], "snapshot_locator": item["snapshot"],
            "independence": {"status": independence, "evidence_scope": "SOURCE_DECLARATIONS_ONLY"},
            "comparison": report}


def _summary(rows):
    counts = {status: sum(row["status"] == status for row in rows) for status in SLOT_STATUSES}
    compared = counts["MATCH"] + counts["DIFFERENT"]
    return {"expected_slots": len(rows),
            "local_price_rows": sum(row["local_state"] == "PRESENT" for row in rows),
            "local_missing_slots": sum(row["local_state"] == "MISSING" for row in rows),
            "reference_declared_slots": sum(row["reference_index"] is not None for row in rows),
            "numerically_compared_slots": compared, "counts": counts,
            "numerical_comparison_coverage": {"numerator": compared, "denominator": len(rows),
                                              "ratio": compared / len(rows) if rows else None},
            "independence_counts": {status: sum(row["independence"] == status for row in rows)
                                    for status in INDEPENDENCE_STATUSES}}


def _analyze_verified(snapshot: IntradayDataset, plan: dict) -> dict:
    """Compose only after the public entry point has verified Q5 once."""
    root = snapshot.as_dict()
    refs_by_day = _reference_scopes(root, plan)
    prices_by_day = {session["trading_day"]: {} for session in root["report"]["sessions"]}
    for price in root["report"]["prices"]:
        prices_by_day[price["trading_day"]][price["slot"]] = price
    references, sessions, rows = [], [], []
    step = timedelta(minutes=comparison.INTERVAL_MINUTES[root["report"]["interval"]])
    for session in root["report"]["sessions"]:
        day, prices = session["trading_day"], prices_by_day[session["trading_day"]]
        reference, compared_rows, declared_grid = None, {}, set()
        if day in refs_by_day:
            index, item = refs_by_day[day]
            reference = _compare_reference(root, plan, index, item, prices.values())
            references.append(reference)
            compared_rows = {row["start"]: row for row in reference["comparison"]["rows"]}
            declared_grid = {start for start, _ in comparison.expected_grid(item["scope"])}
        opening = comparison.parse_utc(session["open_time"])
        session_rows = []
        for slot in range(session["bar_count"]):
            price = prices.get(slot)
            start, end = comparison.utc_text(opening + slot * step), comparison.utc_text(opening + (slot + 1) * step)
            row = {"trading_day": day, "slot": slot, "start": start, "end": end,
                   "row_version_id": None if price is None else price["row_version_id"],
                   "local_state": "MISSING" if price is None else "PRESENT",
                   "comparison_local_state": "UNASSESSED",
                   "local_values": None if price is None else {field: price[field] for field in comparison.VALUE_FIELDS},
                   "reference_index": None, "reference_state": "UNASSESSED", "reference_row_indices": [],
                   "status": "UNASSESSED", "independence": "UNKNOWN", "differences": {}}
            if start in declared_grid:
                row.update(reference_index=reference["reference_index"],
                           independence=reference["independence"]["status"])
                compared = compared_rows.get(start)
                if compared is None:
                    status = reference["comparison"]["status"]
                    if status not in {"NOT_RUN", "INVALID_INPUT"}:
                        raise ValueError("Q44 comparison lacks its declared common slot grid")
                    row.update(status=status, comparison_local_state=status, reference_state=status)
                else:
                    row.update(status=compared["status"], comparison_local_state=compared["left"]["state"],
                               reference_state=compared["right"]["state"],
                               reference_row_indices=compared["right"]["row_indices"],
                               differences=compared["differences"])
            session_rows.append(row)
        rows.extend(session_rows)
        sessions.append({"session": session, "reference_index": None if reference is None else reference["reference_index"],
                         "comparison_status": "UNASSESSED" if reference is None else reference["comparison"]["status"],
                         "summary": _summary(session_rows)})
    summary = _summary(rows)
    # Invalid rows without a usable on-grid key cannot be attached to one Q5
    # slot. Keep their reference-level failure visible beside grid coverage.
    reference_statuses = ("MATCH", "DIFFERENT", "INCOMPLETE", "INVALID_INPUT", "NOT_RUN")
    summary.update(reference_count=len(references),
                   reference_status_counts={status: sum(ref["comparison"]["status"] == status for ref in references)
                                            for status in reference_statuses},
                   input_diagnostics_present=any(item["status"] == "INVALID_INPUT"
                                                 for ref in references
                                                 for item in ref["comparison"]["inputs"].values()))
    compared, expected = summary["numerically_compared_slots"], summary["expected_slots"]
    result = {"version": INTRADAY_MARKET_EVIDENCE_VERSION,
              "status": "AVAILABLE" if compared == expected else "PARTIAL" if compared else "UNAVAILABLE",
              "unavailable_reason": ("NO_REFERENCE_SNAPSHOTS" if not plan["references"] else
                                     "NO_NUMERICALLY_COMPARABLE_SLOTS") if not compared else None,
              "evaluation_scope": "EXPLICIT_Q5_PRICE_EVIDENCE_ONLY", "market_accuracy_certified": False,
              "data_id": root["data_id"],
              "data": {"artifact_schema_version": root["artifact_schema_version"],
                       "content_sha256": sha256(snapshot.content).hexdigest(),
                       "locator": None if snapshot.path is None else str(snapshot.path),
                       "source_build_ids": root["source_build_ids"],
                       "canonical_build_dirs": root["plan"]["canonical_build_dirs"],
                       "algorithm_versions": root["algorithm_versions"],
                       "symbol": root["report"]["symbol"], "interval": root["report"]["interval"],
                       "dataset_as_of": root["plan"]["dataset_as_of"],
                       "source_evidence": "STRICT_Q5_SOURCE_RECONSTRUCTION"},
              "plan": plan, "plan_id": digest(plan), "comparison_version": comparison.COMPARISON_SCHEMA_VERSION,
              "summary": summary, "sessions": sessions, "rows": rows,
              "references": sorted(references, key=lambda item: item["reference_index"]),
              "limitations": ["AVAILABLE describes numerical coverage, including disagreements; it is not a quality PASS.",
                              "Local PRESENT means admitted to Q5; Q44 comparison validity is a separate state.",
                              "Input diagnostics can remain outside the Q5 slot grid and are retained in each original comparison.",
                              "Source nature, independence and economic basis are caller declarations, not provider certification.",
                              "Q5 verification binds these actual prices and row versions, not external market accuracy.",
                              "Unreferenced sessions and slots remain unassessed; missing bars have unknown cause.",
                              "Observation times are not first publication or revision-publication times.",
                              "This report does not change data, choose samples, fit models or measure strategy-return effects."]}
    return {**result, "market_evidence_id": digest(result)}


def analyze_intraday_market_evidence(data: IntradayDataset | str | Path, plan: dict, *,
                                     base: str | Path | None = None) -> dict:
    """Verify the explicit Q5 source once and assess its full declared grid."""
    plan = parse_intraday_market_evidence_plan(plan, base=base)
    snapshot = verify_intraday_dataset(data) if type(data) is IntradayDataset else load_intraday_dataset(data)
    return _analyze_verified(snapshot, plan)


def run_intraday_market_evidence(data_path: str | Path, manifest_path: str | Path) -> dict:
    """Read a plan whose relative snapshot locators resolve beside that plan."""
    path = Path(manifest_path).absolute()
    return analyze_intraday_market_evidence(data_path, comparison.read_json_file(path), base=path.parent)
