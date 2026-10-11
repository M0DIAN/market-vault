"""Fixed offline cases and changes between explicitly supplied observations.

Every statistic describes declared inputs, never complete vendor revision
history, event authenticity, first publication, or market accuracy.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from .market_data_comparison import (
    COMPARISON_SCHEMA_VERSION, NY, SOURCE_FIELDS, VALUE_FIELDS,
    compare_snapshot_files, expected_grid, json_bytes, normalize_scope,
    normalize_tolerances, parse_utc, read_json_file, require_fields,
)
from ..normalization.rth_calendar import resolve_exchange_rth_session

SUITE_SCHEMA_VERSION = "market-vault-market-data-suite-v1"
ACCEPTANCE_SCHEMA_VERSION = "market-vault-market-data-acceptance-v1"
CASE_CATEGORIES = ("NORMAL", "EARLY_CLOSE", "DST_BEFORE", "DST_AFTER",
                   "CORPORATE_ACTION", "HALT_OR_LOW_ACTIVITY")
CASE_STATUSES = ("MATCH", "DIFFERENT", "INCOMPLETE", "INVALID_INPUT", "NOT_COMPARABLE", "NOT_RUN")
BAR_CHANGE_STATUSES = ("ADDED", "REMOVED", "CHANGED", "UNCHANGED", "BOTH_MISSING", "UNASSESSABLE")
FIELD_CHANGE_STATUSES = ("NEW", "PERSISTENT", "RESOLVED", "STABLE_MATCH", "UNASSESSABLE")


def _text(value, label: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{label} must be a nonempty string without surrounding whitespace or controls")
    return value


def _paths(pair: dict, parent: Path) -> tuple[Path | None, Path | None]:
    require_fields(pair, ("left", "right"), label="observation paths")
    return tuple(None if pair[side] is None else (parent / _text(pair[side], side)).absolute()
                 for side in ("left", "right"))


def _empty_history(status: str, code: str | None = None) -> dict:
    return {"status": status, "previous_comparison": None,
            "previous_comparison_recomputed_under_current_rules": False,
            "issues": [] if code is None else [{"code": code}],
            "bar_changes": None, "discrepancy_changes": None}


def _prepare_case(definition: dict, parent: Path) -> dict:
    case = {"category": definition["category"], "definition": definition,
            "scope": None, "declared_expected_slots": None, "category_evidence": None,
            "status": "INVALID_INPUT", "current_comparison": None,
            "history": _empty_history("NO_BASELINE"), "errors": []}
    # A bad path declaration must not erase an otherwise valid scope denominator.
    try:
        case["scope"] = normalize_scope(definition.get("scope"))
        case["declared_expected_slots"] = len(expected_grid(case["scope"]))
    except (ValueError, TypeError) as exc:
        case["errors"].append(str(exc))
    try:
        require_fields(definition, ("category", "scope", "current"),
                       optional=("previous", "event_evidence"), label="case")
        _paths(definition["current"], parent)
        if definition.get("event_evidence") is not None:
            _text(definition["event_evidence"], "event_evidence")
    except (ValueError, TypeError) as exc:
        case["errors"].append(str(exc))
    if case["errors"] and definition.get("previous") is not None:
        case["history"] = _empty_history("UNASSESSABLE", "INVALID_CASE_DEFINITION")
    return case


def _category_evidence(case: dict, cases: dict[str, dict]) -> dict:
    category, scope = case["category"], case["scope"]
    if scope is None:
        return {"status": "UNAVAILABLE", "evidence_scope": "CASE_DEFINITION",
                "reason": "invalid declared scope"}
    if category in {"CORPORATE_ACTION", "HALT_OR_LOW_ACTIVITY"}:
        reference = case["definition"].get("event_evidence")
        try:
            if reference is not None:
                _text(reference, "event_evidence")
        except ValueError:
            return {"status": "UNAVAILABLE", "evidence_scope": "EVENT_DECLARATION_ONLY",
                    "reference": None, "reason": "invalid event evidence declaration"}
        return {"status": "DECLARED" if reference is not None else "UNAVAILABLE",
                "evidence_scope": "EVENT_DECLARATION_ONLY",
                "reference": reference}
    local = parse_utc(scope["window_start"]).astimezone(NY)
    calendar = resolve_exchange_rth_session(local.date())
    result = {"status": "CONFIRMED", "evidence_scope": "BUNDLED_CALENDAR_AND_TIMEZONE",
              "trade_date": local.date().isoformat(), "classification": calendar.classification,
              "authority_version": calendar.authority_version,
              "authority_reference": calendar.authority_reference,
              "utc_offset_seconds": int(local.utcoffset().total_seconds())}
    if category in {"NORMAL", "EARLY_CLOSE"}:
        if calendar.classification != category:
            result.update(status="MISMATCH", reason="category differs from exchange session classification")
        return result
    before, after = (cases[name]["scope"] for name in ("DST_BEFORE", "DST_AFTER"))
    if before is None or after is None:
        result.update(status="MISMATCH", reason="DST pair requires two valid declared scopes")
        return result
    first, last = (parse_utc(item["window_start"]).astimezone(NY) for item in (before, after))
    consecutive = first.date() < last.date()
    day = first.date() + timedelta(days=1)
    while consecutive and day < last.date():
        if resolve_exchange_rth_session(day).classification != "CLOSED":
            consecutive = False
        day += timedelta(days=1)
    if not consecutive or abs((last.utcoffset() - first.utcoffset()).total_seconds()) != 3600:
        result.update(status="MISMATCH", reason="DST pair must straddle a one-hour offset change on consecutive trading dates")
    result["pair_dates"] = [first.date().isoformat(), last.date().isoformat()]
    return result


def _bar_changes(previous: dict, current: dict, side: str) -> dict:
    counts = dict.fromkeys((status.lower() for status in BAR_CHANGE_STATUSES), 0)
    rows = []
    for old, new in zip(previous["rows"], current["rows"], strict=True):
        a, b = old[side], new[side]
        before = {field: a["bar"][field] for field in VALUE_FIELDS} if a["state"] == "VALID_UNIQUE" else None
        after = {field: b["bar"][field] for field in VALUE_FIELDS} if b["state"] == "VALID_UNIQUE" else None
        changed = []
        if a["state"] not in {"MISSING", "VALID_UNIQUE"} or b["state"] not in {"MISSING", "VALID_UNIQUE"}:
            status = "UNASSESSABLE"
        elif before is None and after is None:
            status = "BOTH_MISSING"
        elif before is None:
            status = "ADDED"
        elif after is None:
            status = "REMOVED"
        else:
            changed = [field for field in VALUE_FIELDS if before[field] != after[field]]
            status = "CHANGED" if changed else "UNCHANGED"
        counts[status.lower()] += 1
        rows.append({"start": new["start"], "end": new["end"], "status": status,
                     "changed_fields": changed, "previous": before, "current": after})
    return {"expected_slots": current["expected_slots"], "counts": counts, "rows": rows}


def _discrepancy_changes(previous: dict, current: dict) -> dict:
    counts = dict.fromkeys((status.lower() for status in FIELD_CHANGE_STATUSES), 0)
    rows = []
    for old, new in zip(previous["rows"], current["rows"], strict=True):
        fields = {}
        for field in VALUE_FIELDS:
            # A disappearing value cannot establish that its former discrepancy resolved.
            if field not in old["differences"] or field not in new["differences"]:
                status = "UNASSESSABLE"
            else:
                old_match = old["differences"][field]["within_tolerance"]
                new_match = new["differences"][field]["within_tolerance"]
                status = (("STABLE_MATCH" if new_match else "NEW") if old_match
                          else ("RESOLVED" if new_match else "PERSISTENT"))
            fields[field] = status
            counts[status.lower()] += 1
        rows.append({"start": new["start"], "end": new["end"], "previous_status": old["status"],
                     "current_status": new["status"], "fields": fields})
    return {"expected_fields": current["expected_slots"] * len(VALUE_FIELDS),
            "counts": counts, "rows": rows}


def _history(definition: dict, current: dict, scope: dict, tolerances: dict,
             parent: Path, *, case_comparable: bool) -> dict:
    if definition.get("previous") is None:
        return _empty_history("NO_BASELINE")
    history = _empty_history("UNASSESSABLE")
    try:
        paths = _paths(definition["previous"], parent)
    except (ValueError, TypeError) as exc:
        history.update(status="INVALID_INPUT", issues=[{"code": "INVALID_PREVIOUS_LOCATORS", "error": str(exc)}])
        return history
    previous = compare_snapshot_files(*paths, tolerances=tolerances)
    history.update(previous_comparison=previous, previous_comparison_recomputed_under_current_rules=True)
    if not case_comparable:
        history.update(status="NOT_COMPARABLE", issues=[{"code": "CASE_DEFINITION_NOT_COMPARABLE"}])
        return history
    if any(report["status"] == "NOT_RUN" for report in (previous, current)):
        history.update(status="NOT_RUN", issues=[{"code": "MISSING_OBSERVATION"}])
        return history
    if any(report["scope"] != scope for report in (previous, current)):
        mismatch = any(report["status"] == "NOT_COMPARABLE" or
                       (report["scope"] is not None and report["scope"] != scope)
                       for report in (previous, current))
        history.update(status="NOT_COMPARABLE" if mismatch else "UNASSESSABLE",
                       issues=[{"code": "NO_COMMON_DECLARED_CASE_GRID"}])
        return history
    source_changes, observations, wrong_order = [], {}, []
    for side in ("left", "right"):
        old, new = previous["inputs"][side]["source"], current["inputs"][side]["source"]
        changed = {field: {"previous": old[field], "current": new[field]} for field in SOURCE_FIELDS
                   if field != "captured_at" and old[field] != new[field]}
        if changed:
            source_changes.append({"side": side, "fields": changed})
        observations[side] = {"previous_captured_at": old["captured_at"], "current_captured_at": new["captured_at"]}
        if parse_utc(old["captured_at"]) >= parse_utc(new["captured_at"]):
            wrong_order.append(side)
    history.update(observations=observations, source_declaration_changes=source_changes)
    if source_changes:
        history.update(status="NOT_COMPARABLE", issues=[{"code": "SOURCE_DECLARATION_CHANGED"}])
        return history
    if wrong_order:
        history.update(issues=[{"code": "BASELINE_NOT_EARLIER", "sides": wrong_order}])
        return history
    history.update(status="REPORTED", bar_changes={side: _bar_changes(previous, current, side)
                                                  for side in ("left", "right")},
                   discrepancy_changes=_discrepancy_changes(previous, current),
                   input_diagnostics_present=any(item["status"] == "INVALID_INPUT"
                       for report in (previous, current) for item in report["inputs"].values()))
    return history


def run_market_data_acceptance(manifest_path: str | Path) -> dict:
    """Run six fixed cases from one explicit manifest; structural errors raise.

    Each comparison captures its explicit input occurrences once. History uses
    those same reports and hashes, not later reads of potentially changed files.
    No atomic capture across different files or case occurrences is promised.
    """
    path = Path(manifest_path).absolute()
    manifest = read_json_file(path)
    digest = hashlib.sha256(json_bytes(manifest)).hexdigest()
    require_fields(manifest, ("schema_version", "cases"), optional=("tolerances",), label="suite")
    if manifest["schema_version"] != SUITE_SCHEMA_VERSION:
        raise ValueError("unsupported suite schema_version")
    definitions = manifest["cases"]
    if type(definitions) is not list or any(type(item) is not dict for item in definitions):
        raise ValueError("suite cases must be an array of case objects")
    categories = [item.get("category") for item in definitions]
    if (len(categories) != len(CASE_CATEGORIES) or any(type(item) is not str for item in categories)
            or set(categories) != set(CASE_CATEGORIES)):
        raise ValueError("suite must contain exactly one case for each of the six fixed categories")
    tolerances = normalize_tolerances(manifest.get("tolerances"))
    cases = {item["category"]: _prepare_case(item, path.parent) for item in definitions}
    for category in CASE_CATEGORIES:
        case = cases[category]
        case["category_evidence"] = _category_evidence(case, cases)
        if case["errors"]:
            continue
        current = compare_snapshot_files(*_paths(case["definition"]["current"], path.parent), tolerances=tolerances)
        case.update(current_comparison=current, status=current["status"])
        mismatch = any(item.get("scope") is not None and item["scope"] != case["scope"]
                       for item in current["inputs"].values())
        case["comparison_scope_matches_case"] = (False if mismatch else True
                                                 if current["scope"] == case["scope"] else None)
        comparable = not mismatch and case["category_evidence"]["status"] != "MISMATCH"
        if not comparable:
            case.update(status="NOT_COMPARABLE")
            case["errors"].append("input scope or calendar category differs from the declared case")
        case["history"] = _history(case["definition"], current, case["scope"], tolerances,
                                    path.parent, case_comparable=comparable)
    ordered = [cases[category] for category in CASE_CATEGORIES]
    counts = dict.fromkeys(CASE_STATUSES, 0)
    for case in ordered:
        counts[case["status"]] += 1
    return {"report_schema_version": ACCEPTANCE_SCHEMA_VERSION,
            "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
            "status": "NOT_RUN" if counts["NOT_RUN"] == len(CASE_CATEGORIES) else "REPORTED",
            "validation_scope": "FIXED_CASE_DECLARED_GRID_COMPARISON", "market_accuracy_certified": False,
            "manifest": {"locator": str(path), "content_sha256": digest}, "tolerances": tolerances,
            "summary": {"case_count": len(CASE_CATEGORIES), "status_counts": counts,
                        "declared_grid_slots": sum(case["declared_expected_slots"] or 0 for case in ordered),
                        "case_scopes_unavailable": sum(case["scope"] is None for case in ordered)},
            "cases": ordered,
            "limitations": ["Results describe the fixed declared cases; MATCH is not market accuracy certification.",
                            "Source lineage and corporate-action/halt evidence are declarations, not verified events.",
                            "History compares only supplied observations under the current comparison rules.",
                            "Capture times do not establish first publication, revision-publication time, or complete vendor history.",
                            "Missing rows have unknown cause; no values are filled, repaired or deduplicated."]}
