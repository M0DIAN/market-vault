"""Fixed-suite and observed-change tests using explicitly synthetic snapshots."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from market_vault import cli
from market_vault.quality import market_data_acceptance as acceptance
from market_vault.quality import market_data_comparison as comparison


CATEGORIES = (
    "NORMAL", "EARLY_CLOSE", "DST_BEFORE", "DST_AFTER", "CORPORATE_ACTION", "HALT_OR_LOW_ACTIVITY",
)
DAYS = {
    "NORMAL": "2025-03-03", "EARLY_CLOSE": "2025-11-28", "DST_BEFORE": "2025-03-07",
    "DST_AFTER": "2025-03-10", "CORPORATE_ACTION": "2025-03-04", "HALT_OR_LOW_ACTIVITY": "2025-03-05",
}
VALUES = ("open", "high", "low", "close", "volume")
CAPTURE = {"previous": "2026-01-02T12:00:00Z", "current": "2026-01-03T12:00:00Z"}


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def scope(day, slots=2):
    start = datetime.fromisoformat(day + "T09:30:00").replace(tzinfo=ZoneInfo("America/New_York"))
    return {
        "symbol": "US.SPY", "asset_class": "ETF", "adjustment": "NONE", "session": "RTH",
        "interval": "1m", "currency": "USD", "aggregation": "TRADE_OHLCV", "volume_basis": "SHARES",
        "window_start": utc(start), "window_end": utc(start + timedelta(minutes=slots)),
    }


def bar(declared_scope, slot, **changes):
    start = datetime.fromisoformat(declared_scope["window_start"].replace("Z", "+00:00")) + timedelta(minutes=slot)
    return {"start": utc(start), "end": utc(start + timedelta(minutes=1)),
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 10, **changes}


def snapshot(declared_scope, side, period, slots=2):
    return {
        "schema_version": comparison.SNAPSHOT_SCHEMA_VERSION,
        "source": {"provider": "fixture-" + side, "version": "fixture-v1", "captured_at": CAPTURE[period],
                   "data_kind": "SYNTHETIC", "upstream_id": "fixture-feed-" + side,
                   "upstream_evidence": "fixture-declaration-" + side},
        "scope": deepcopy(declared_scope),
        "bars": [bar(declared_scope, slot) for slot in range(slots)],
    }


def write_json(path, payload):
    path.write_bytes(comparison.json_bytes(payload))
    return path


def read_json(path):
    return json.loads(path.read_bytes())


def add_previous(manifest_path, case, *, slots=2, empty=False):
    case["previous"] = {}
    for side in ("left", "right"):
        filename = f"{case['category']}-previous-{side}.json"
        payload = snapshot(case["scope"], side, "previous", slots)
        if empty:
            payload["bars"] = []
        write_json(manifest_path.parent / filename, payload)
        case["previous"][side] = filename


def suite(tmp_path, *, slots=2, previous=False):
    root = tmp_path / "suite-inputs"
    root.mkdir()
    manifest_path = root / "suite.json"
    cases = []
    for category in CATEGORIES:
        case = {"category": category, "scope": scope(DAYS[category], slots), "current": {}}
        for side in ("left", "right"):
            filename = f"{category}-current-{side}.json"
            write_json(root / filename, snapshot(case["scope"], side, "current", slots))
            case["current"][side] = filename
        if previous:
            add_previous(manifest_path, case, slots=slots)
        cases.append(case)
    payload = {"schema_version": "market-vault-market-data-suite-v1", "cases": cases}
    write_json(manifest_path, payload)
    return manifest_path, payload


def case_named(container, category="NORMAL"):
    return next(case for case in container["cases"] if case["category"] == category)


def input_path(manifest_path, case, side, period="current"):
    return manifest_path.parent / case[period][side]


def change_day(manifest_path, case, day):
    case["scope"] = scope(day)
    for period in ("current", "previous"):
        for side, filename in case.get(period, {}).items():
            write_json(manifest_path.parent / filename, snapshot(case["scope"], side, period))


def test_six_mixed_cases_keep_declared_denominators_and_actual_comparisons(tmp_path):
    manifest_path, manifest = suite(tmp_path)
    early = case_named(manifest, "EARLY_CLOSE")
    payload = read_json(input_path(manifest_path, early, "left"))
    payload["bars"][0]["close"] = 101
    write_json(input_path(manifest_path, early, "left"), payload)
    before = case_named(manifest, "DST_BEFORE")
    payload = read_json(input_path(manifest_path, before, "left"))
    payload["bars"] = []
    write_json(input_path(manifest_path, before, "left"), payload)
    after = case_named(manifest, "DST_AFTER")
    input_path(manifest_path, after, "left").unlink()
    corporate = case_named(manifest, "CORPORATE_ACTION")
    payload = read_json(input_path(manifest_path, corporate, "left"))
    payload["bars"][0]["close"] = 0
    write_json(input_path(manifest_path, corporate, "left"), payload)
    halt = case_named(manifest, "HALT_OR_LOW_ACTIVITY")
    for side in ("left", "right"):
        payload = read_json(input_path(manifest_path, halt, side))
        payload["scope"]["currency"] = "CAD"
        write_json(input_path(manifest_path, halt, side), payload)
    manifest["cases"].reverse()
    write_json(manifest_path, manifest)

    report = acceptance.run_market_data_acceptance(manifest_path)

    assert tuple(case["category"] for case in report["cases"]) == CATEGORIES
    assert report["status"] == "REPORTED"
    assert report["market_accuracy_certified"] is False
    assert report["summary"] == {
        "case_count": 6,
        "status_counts": {status: 1 for status in (
            "MATCH", "DIFFERENT", "INCOMPLETE", "INVALID_INPUT", "NOT_COMPARABLE", "NOT_RUN")},
        "declared_grid_slots": 12, "case_scopes_unavailable": 0,
    }
    assert [case["status"] for case in report["cases"]] == [
        "MATCH", "DIFFERENT", "INCOMPLETE", "NOT_RUN", "INVALID_INPUT", "NOT_COMPARABLE",
    ]
    assert all(case["declared_expected_slots"] == 2 for case in report["cases"])
    assert all(case["history"]["status"] == "NO_BASELINE" for case in report["cases"])
    assert case_named(report, "DST_BEFORE")["current_comparison"]["counts"]["right_only"] == 2
    assert case_named(report, "DST_AFTER")["current_comparison"]["expected_slots"] is None
    actual = case_named(report, "HALT_OR_LOW_ACTIVITY")["current_comparison"]
    assert actual == comparison.compare_snapshot_files(
        input_path(manifest_path, halt, "left"), input_path(manifest_path, halt, "right"))
    assert actual["status"] == "MATCH"
    assert actual["scope"]["currency"] == "CAD"
    assert case_named(report, "HALT_OR_LOW_ACTIVITY")["scope"]["currency"] == "USD"
    assert case_named(report, "NORMAL")["definition"] == case_named(manifest)


def test_all_explicitly_absent_current_inputs_keep_the_fixed_suite_not_run(tmp_path):
    manifest_path, manifest = suite(tmp_path)
    available_inputs = [input_path(manifest_path, case, side)
                        for case in manifest["cases"] for side in ("left", "right")]
    for case in manifest["cases"]:
        case["current"] = {"left": None, "right": None}
    write_json(manifest_path, manifest)

    report = acceptance.run_market_data_acceptance(manifest_path)

    assert all(path.is_file() for path in available_inputs)
    assert report["status"] == "NOT_RUN"
    assert report["summary"] == {
        "case_count": 6,
        "status_counts": {"MATCH": 0, "DIFFERENT": 0, "INCOMPLETE": 0,
                          "INVALID_INPUT": 0, "NOT_COMPARABLE": 0, "NOT_RUN": 6},
        "declared_grid_slots": 12, "case_scopes_unavailable": 0,
    }
    assert tuple(case["category"] for case in report["cases"]) == CATEGORIES
    for case in report["cases"]:
        assert case["status"] == "NOT_RUN"
        assert case["declared_expected_slots"] == 2
        assert case["current_comparison"]["status"] == "NOT_RUN"
        assert case["current_comparison"]["rows"] == []
        assert case["current_comparison"]["expected_slots"] is None
        assert case["history"]["status"] == "NO_BASELINE"
        assert case["history"]["previous_comparison"] is None
        assert case["history"]["bar_changes"] is None
        assert case["history"]["discrepancy_changes"] is None


@pytest.mark.parametrize("problem", ("wrong_schema", "missing_category", "duplicate_category", "unknown_category"))
def test_suite_structure_errors_cannot_silently_reduce_the_six_cases(tmp_path, problem):
    manifest_path, manifest = suite(tmp_path)
    if problem == "wrong_schema":
        manifest["schema_version"] = "unrecognized-suite"
    elif problem == "missing_category":
        manifest["cases"].pop()
    elif problem == "duplicate_category":
        manifest["cases"][-1] = deepcopy(manifest["cases"][0])
    else:
        manifest["cases"][-1]["category"] = "ANY_OTHER_DAY"
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError):
        acceptance.run_market_data_acceptance(manifest_path)


@pytest.mark.parametrize("problem", ("scope", "paths"))
def test_known_bad_case_is_retained_and_only_loses_an_unprovable_grid(tmp_path, problem):
    manifest_path, manifest = suite(tmp_path)
    case = case_named(manifest)
    add_previous(manifest_path, case)
    if problem == "scope":
        case["scope"]["window_start"] = "2025-03-03T14:30:00"
    else:
        case["current"]["left"] = 42
    write_json(manifest_path, manifest)

    report = acceptance.run_market_data_acceptance(manifest_path)

    bad = case_named(report)
    assert bad["status"] == "INVALID_INPUT"
    assert bad["errors"]
    assert bad["definition"] == case
    assert bad["current_comparison"] is None
    assert bad["history"]["status"] == "UNASSESSABLE"
    assert bad["declared_expected_slots"] == (None if problem == "scope" else 2)
    assert report["summary"]["case_count"] == 6
    assert report["summary"]["status_counts"]["MATCH"] == 5
    assert report["summary"]["case_scopes_unavailable"] == (1 if problem == "scope" else 0)
    assert report["summary"]["declared_grid_slots"] == (10 if problem == "scope" else 12)


def test_malformed_previous_paths_reject_only_history_and_preserve_current(tmp_path):
    manifest_path, manifest = suite(tmp_path)
    case = case_named(manifest)
    case["previous"] = {"left": 42, "right": None}
    write_json(manifest_path, manifest)
    expected_current = comparison.compare_snapshot_files(
        input_path(manifest_path, case, "left"), input_path(manifest_path, case, "right"))

    report = acceptance.run_market_data_acceptance(manifest_path)

    result = case_named(report)
    assert result["status"] == expected_current["status"] == "MATCH"
    assert result["current_comparison"] == expected_current
    assert result["declared_expected_slots"] == 2
    assert not result["errors"]
    history = result["history"]
    assert history["status"] == "INVALID_INPUT"
    assert history["issues"][0]["code"] == "INVALID_PREVIOUS_LOCATORS"
    assert history["issues"][0]["error"]
    assert history["previous_comparison"] is None
    assert history["previous_comparison_recomputed_under_current_rules"] is False
    assert history["bar_changes"] is None
    assert history["discrepancy_changes"] is None
    assert report["summary"]["status_counts"]["MATCH"] == 6
    assert all(other["history"]["status"] == "NO_BASELINE" for other in report["cases"]
               if other["category"] != "NORMAL")


def test_source_bar_changes_are_exact_ignore_origin_and_keep_missing_states(tmp_path):
    manifest_path, manifest = suite(tmp_path, slots=6, previous=True)
    manifest["tolerances"] = {"price_absolute": 1, "price_relative": 0, "volume_absolute": 0}
    case = case_named(manifest)
    old = read_json(input_path(manifest_path, case, "left", "previous"))
    new = read_json(input_path(manifest_path, case, "left"))
    old["bars"][0]["origin"] = {"audit": "previous"}
    new["bars"][0]["origin"] = {"audit": "current"}
    old["bars"][1]["close"] = 100.25
    new["bars"][1]["close"] = 100.5
    new["bars"][5]["volume"] = 0
    old["bars"] = [row for index, row in enumerate(old["bars"]) if index not in {2, 4}]
    new["bars"] = [row for index, row in enumerate(new["bars"]) if index not in {3, 4}]
    write_json(input_path(manifest_path, case, "left", "previous"), old)
    write_json(input_path(manifest_path, case, "left"), new)
    write_json(manifest_path, manifest)

    result = case_named(acceptance.run_market_data_acceptance(manifest_path))
    history = result["history"]

    assert result["status"] == "INCOMPLETE"
    assert history["status"] == "REPORTED"
    assert history["previous_comparison_recomputed_under_current_rules"] is True
    assert history["previous_comparison"]["tolerances"] == manifest["tolerances"]
    assert history["previous_comparison"]["rows"][1]["status"] == "MATCH"
    assert result["current_comparison"]["rows"][1]["status"] == "MATCH"
    assert history["input_diagnostics_present"] is False
    left = history["bar_changes"]["left"]
    assert left["expected_slots"] == 6
    assert left["counts"] == {
        "added": 1, "removed": 1, "changed": 2, "unchanged": 1,
        "both_missing": 1, "unassessable": 0,
    }
    assert [row["status"] for row in left["rows"]] == [
        "UNCHANGED", "CHANGED", "ADDED", "REMOVED", "BOTH_MISSING", "CHANGED",
    ]
    assert left["rows"][0]["changed_fields"] == []
    assert set(left["rows"][0]["previous"]) == set(VALUES)
    assert left["rows"][0]["previous"] == left["rows"][0]["current"]
    assert left["rows"][1]["changed_fields"] == ["close"]
    assert left["rows"][1]["previous"]["close"] == 100.25
    assert left["rows"][1]["current"]["close"] == 100.5
    assert left["rows"][5]["changed_fields"] == ["volume"]
    assert left["rows"][5]["current"]["volume"] == 0
    assert history["bar_changes"]["right"]["counts"]["unchanged"] == 6


def test_explicit_empty_previous_observation_is_distinct_from_no_baseline(tmp_path):
    manifest_path, manifest = suite(tmp_path)
    add_previous(manifest_path, case_named(manifest), empty=True)
    write_json(manifest_path, manifest)

    report = acceptance.run_market_data_acceptance(manifest_path)

    history = case_named(report)["history"]
    assert history["status"] == "REPORTED"
    assert history["previous_comparison"]["status"] == "INCOMPLETE"
    assert history["previous_comparison"]["counts"]["both_missing"] == 2
    for side in ("left", "right"):
        assert history["bar_changes"][side]["counts"]["added"] == 2
        assert all(row["previous"] is None for row in history["bar_changes"][side]["rows"])
    assert history["discrepancy_changes"]["expected_fields"] == 10
    assert history["discrepancy_changes"]["counts"]["unassessable"] == 10
    absent = case_named(report, "EARLY_CLOSE")["history"]
    assert absent["status"] == "NO_BASELINE"
    assert absent["previous_comparison"] is None
    assert absent["bar_changes"] is None
    assert absent["discrepancy_changes"] is None


def test_discrepancies_track_fields_and_never_resolve_missing_invalid_or_duplicate_rows(tmp_path):
    manifest_path, manifest = suite(tmp_path, slots=7, previous=True)
    case = case_named(manifest)
    old = read_json(input_path(manifest_path, case, "left", "previous"))
    new = read_json(input_path(manifest_path, case, "left"))
    for slot in (1, 2, 3, 4):
        old["bars"][slot]["close"] = 102
    old["bars"][5]["close"] = 0
    new["bars"][0]["close"] = 102
    new["bars"][1]["close"] = 103
    new["bars"][4]["volume"] = 20
    new["bars"].append(bar(case["scope"], 6, close=101))
    new["bars"].pop(3)
    write_json(input_path(manifest_path, case, "left", "previous"), old)
    write_json(input_path(manifest_path, case, "left"), new)

    result = case_named(acceptance.run_market_data_acceptance(manifest_path))
    history = result["history"]

    assert result["status"] == "INVALID_INPUT"
    assert history["status"] == "REPORTED"
    assert history["previous_comparison"]["status"] == "INVALID_INPUT"
    assert history["input_diagnostics_present"] is True
    changes = history["discrepancy_changes"]
    assert changes["expected_fields"] == 35
    assert changes["counts"] == {
        "new": 2, "persistent": 1, "resolved": 2, "stable_match": 15, "unassessable": 15,
    }
    assert sum(changes["counts"].values()) == 35
    assert changes["rows"][0]["fields"]["close"] == "NEW"
    assert changes["rows"][1]["fields"]["close"] == "PERSISTENT"
    assert changes["rows"][2]["fields"]["close"] == "RESOLVED"
    assert changes["rows"][4]["previous_status"] == changes["rows"][4]["current_status"] == "DIFFERENT"
    assert changes["rows"][4]["fields"]["close"] == "RESOLVED"
    assert changes["rows"][4]["fields"]["volume"] == "NEW"
    for slot in (3, 5, 6):
        assert changes["rows"][slot]["fields"] == dict.fromkeys(VALUES, "UNASSESSABLE")
    assert changes["rows"][3]["previous_status"] == "DIFFERENT"
    assert changes["rows"][3]["current_status"] == "RIGHT_ONLY"
    assert history["bar_changes"]["left"]["counts"] == {
        "added": 0, "removed": 1, "changed": 4, "unchanged": 0,
        "both_missing": 0, "unassessable": 2,
    }
    assert history["bar_changes"]["right"]["counts"]["unchanged"] == 7


@pytest.mark.parametrize(("problem", "expected_status", "issue"), (
    ("scope", "NOT_COMPARABLE", "NO_COMMON_DECLARED_CASE_GRID"),
    ("provider", "NOT_COMPARABLE", "SOURCE_DECLARATION_CHANGED"),
    ("version", "NOT_COMPARABLE", "SOURCE_DECLARATION_CHANGED"),
    ("upstream_id", "NOT_COMPARABLE", "SOURCE_DECLARATION_CHANGED"),
    ("equal_capture", "UNASSESSABLE", "BASELINE_NOT_EARLIER"),
    ("later_capture", "UNASSESSABLE", "BASELINE_NOT_EARLIER"),
))
def test_history_scope_lineage_and_per_side_capture_gates_preserve_current(
        tmp_path, problem, expected_status, issue):
    manifest_path, manifest = suite(tmp_path, previous=True)
    case = case_named(manifest)
    sides = ("left", "right") if problem == "scope" else ("right",)
    for side in sides:
        path = input_path(manifest_path, case, side, "previous")
        payload = read_json(path)
        if problem == "scope":
            payload["scope"]["currency"] = "CAD"
        elif problem == "equal_capture":
            payload["source"]["captured_at"] = CAPTURE["current"]
        elif problem == "later_capture":
            payload["source"]["captured_at"] = "2026-01-04T12:00:00Z"
        else:
            payload["source"][problem] = "different-" + problem
        write_json(path, payload)

    result = case_named(acceptance.run_market_data_acceptance(manifest_path))
    history = result["history"]

    assert result["status"] == result["current_comparison"]["status"] == "MATCH"
    assert result["declared_expected_slots"] == 2
    assert history["status"] == expected_status
    assert history["issues"][0]["code"] == issue
    assert history["previous_comparison"] is not None
    assert history["previous_comparison_recomputed_under_current_rules"] is True
    assert history["bar_changes"] is None
    assert history["discrepancy_changes"] is None
    if problem in {"provider", "version", "upstream_id"}:
        assert history["source_declaration_changes"] == [{"side": "right", "fields": {
            problem: {"previous": "different-" + problem,
                      "current": result["current_comparison"]["inputs"]["right"]["source"][problem]},
        }}]
    if problem in {"equal_capture", "later_capture"}:
        assert history["issues"][0]["sides"] == ["right"]
        assert history["observations"]["left"]["previous_captured_at"] == CAPTURE["previous"]
        assert history["observations"]["right"]["current_captured_at"] == CAPTURE["current"]


@pytest.mark.parametrize(("problem", "expected_status"), (
    ("missing_previous", "NOT_RUN"),
    ("missing_current", "NOT_RUN"),
    ("invalid_previous_json", "UNASSESSABLE"),
    ("incompatible_previous_pair", "NOT_COMPARABLE"),
))
def test_history_without_a_common_observation_is_not_an_empty_baseline(tmp_path, problem, expected_status):
    manifest_path, manifest = suite(tmp_path, previous=True)
    case = case_named(manifest)
    if problem == "missing_previous":
        input_path(manifest_path, case, "left", "previous").unlink()
    elif problem == "missing_current":
        case["current"]["left"] = None
        write_json(manifest_path, manifest)
    elif problem == "invalid_previous_json":
        input_path(manifest_path, case, "left", "previous").write_text("{invalid", encoding="utf-8")
    else:
        path = input_path(manifest_path, case, "left", "previous")
        payload = read_json(path)
        payload["scope"]["currency"] = "CAD"
        write_json(path, payload)

    result = case_named(acceptance.run_market_data_acceptance(manifest_path))
    history = result["history"]

    assert result["declared_expected_slots"] == 2
    assert history["status"] == expected_status
    assert history["issues"]
    assert history["bar_changes"] is None
    assert history["discrepancy_changes"] is None
    if problem != "missing_current":
        assert result["current_comparison"]["status"] == "MATCH"
        assert history["previous_comparison"]["expected_slots"] is None


@pytest.mark.parametrize("problem", ("normal_on_early_close", "early_close_on_normal", "no_dst_change", "not_adjacent"))
def test_calendar_categories_require_real_classification_and_adjacent_dst_dates(tmp_path, problem):
    manifest_path, manifest = suite(tmp_path, previous=True)
    if problem == "normal_on_early_close":
        change_day(manifest_path, case_named(manifest), DAYS["EARLY_CLOSE"])
        rejected = ("NORMAL",)
    elif problem == "early_close_on_normal":
        change_day(manifest_path, case_named(manifest, "EARLY_CLOSE"), DAYS["NORMAL"])
        rejected = ("EARLY_CLOSE",)
    elif problem == "no_dst_change":
        change_day(manifest_path, case_named(manifest, "DST_BEFORE"), "2025-03-03")
        change_day(manifest_path, case_named(manifest, "DST_AFTER"), "2025-03-04")
        rejected = ("DST_BEFORE", "DST_AFTER")
    else:
        change_day(manifest_path, case_named(manifest, "DST_BEFORE"), "2025-03-06")
        rejected = ("DST_BEFORE", "DST_AFTER")
    write_json(manifest_path, manifest)

    report = acceptance.run_market_data_acceptance(manifest_path)

    for category in rejected:
        case = case_named(report, category)
        assert case["status"] == "NOT_COMPARABLE"
        assert case["current_comparison"]["status"] == "MATCH"
        assert case["category_evidence"]["status"] == "MISMATCH"
        assert case["category_evidence"]["reason"]
        assert case["history"]["status"] == "NOT_COMPARABLE"
        assert case["history"]["bar_changes"] is None


def test_calendar_confirmation_and_event_declarations_are_separate_evidence(tmp_path):
    manifest_path, manifest = suite(tmp_path)
    case_named(manifest, "CORPORATE_ACTION")["event_evidence"] = "fixture://declared-split-example"
    write_json(manifest_path, manifest)

    report = acceptance.run_market_data_acceptance(manifest_path)

    assert report["summary"]["status_counts"]["MATCH"] == 6
    for category in CATEGORIES[:4]:
        evidence = case_named(report, category)["category_evidence"]
        assert evidence["status"] == "CONFIRMED"
        assert evidence["evidence_scope"] == "BUNDLED_CALENDAR_AND_TIMEZONE"
        assert evidence["authority_version"]
        assert evidence["authority_reference"]
    assert case_named(report, "EARLY_CLOSE")["category_evidence"]["classification"] == "EARLY_CLOSE"
    assert case_named(report, "DST_BEFORE")["category_evidence"]["utc_offset_seconds"] == -18000
    assert case_named(report, "DST_AFTER")["category_evidence"]["utc_offset_seconds"] == -14400
    assert case_named(report, "CORPORATE_ACTION")["category_evidence"] == {
        "status": "DECLARED", "evidence_scope": "EVENT_DECLARATION_ONLY",
        "reference": "fixture://declared-split-example",
    }
    assert case_named(report, "HALT_OR_LOW_ACTIVITY")["category_evidence"] == {
        "status": "UNAVAILABLE", "evidence_scope": "EVENT_DECLARATION_ONLY", "reference": None,
    }
    assert report["market_accuracy_certified"] is False
    assert all(case["current_comparison"]["independence"]["status"] == "SYNTHETIC" for case in report["cases"])


def test_history_reuses_each_captured_pair_when_files_change_after_comparison(tmp_path, monkeypatch):
    manifest_path, manifest = suite(tmp_path)
    case = case_named(manifest)
    add_previous(manifest_path, case)
    write_json(manifest_path, manifest)
    for period, close in (("previous", 101), ("current", 102)):
        path = input_path(manifest_path, case, "left", period)
        payload = read_json(path)
        payload["bars"][0]["close"] = close
        write_json(path, payload)
    pairs = {period: tuple(input_path(manifest_path, case, side, period) for side in ("left", "right"))
             for period in ("current", "previous")}
    original_bytes = {path: path.read_bytes() for pair in pairs.values() for path in pair}
    replacements = {}
    for path, raw in original_bytes.items():
        replacement = json.loads(raw)
        replacement["source"]["version"] = "mutated-after-capture"
        replacement["bars"] = []
        replacements[path] = replacement
    real_compare = comparison.compare_snapshot_files
    calls, captured = [], {}

    def capture_then_mutate(left, right, *, tolerances):
        pair = (Path(left), Path(right))
        calls.append(pair)
        result = real_compare(left, right, tolerances=tolerances)
        if pair in pairs.values():
            captured[pair] = deepcopy(result)
            for path in pair:
                write_json(path, replacements[path])
        return result

    monkeypatch.setattr(acceptance, "compare_snapshot_files", capture_then_mutate)

    result = case_named(acceptance.run_market_data_acceptance(manifest_path))

    assert len(calls) == 7
    assert calls.count(pairs["current"]) == calls.count(pairs["previous"]) == 1
    assert result["current_comparison"] == captured[pairs["current"]]
    history = result["history"]
    assert history["previous_comparison"] == captured[pairs["previous"]]
    assert history["status"] == "REPORTED"
    assert history["bar_changes"]["left"]["rows"][0]["status"] == "CHANGED"
    assert history["bar_changes"]["left"]["rows"][0]["previous"]["close"] == 101
    assert history["bar_changes"]["left"]["rows"][0]["current"]["close"] == 102
    assert history["discrepancy_changes"]["rows"][0]["fields"]["close"] == "PERSISTENT"
    for period, nested in (("current", result["current_comparison"]), ("previous", history["previous_comparison"])):
        for side, path in zip(("left", "right"), pairs[period], strict=True):
            assert nested["inputs"][side]["file_sha256"] == hashlib.sha256(original_bytes[path]).hexdigest()
            assert nested["inputs"][side]["source"]["version"] == "fixture-v1"
            assert path.read_bytes() != original_bytes[path]


def test_actual_cli_is_settings_free_stable_exclusive_and_keeps_inputs_unchanged(tmp_path, monkeypatch, capsys):
    manifest_path, _ = suite(tmp_path, previous=True)
    original_inputs = {path: path.read_bytes() for path in manifest_path.parent.iterdir()}
    missing_settings = tmp_path / "settings-do-not-exist.yaml"
    elsewhere = tmp_path / "unrelated-working-directory"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    outputs = (tmp_path / "first-report.json", tmp_path / "second-report.json")
    expected = acceptance.run_market_data_acceptance(manifest_path)
    for output in outputs:
        result = cli.main(["--settings", str(missing_settings), "market-data-acceptance",
                           "--manifest", str(manifest_path), "--output", str(output)])
        emitted = capsys.readouterr()
        assert result == 0, emitted.err
        assert not emitted.err
        assert emitted.out.isascii()
        payload = json.loads(emitted.out)
        assert payload["status"] == "SUCCESS"
        assert payload["output"] == str(output)
        assert payload["report"] == expected == read_json(output)
    assert outputs[0].read_bytes() == outputs[1].read_bytes() == comparison.json_bytes(expected)
    saved = outputs[0].read_bytes()

    result = cli.main(["--settings", str(missing_settings), "market-data-acceptance",
                       "--manifest", str(manifest_path), "--output", str(outputs[0])])
    emitted = capsys.readouterr()

    assert result == 1
    assert not emitted.out
    refusal = json.loads(emitted.err)
    assert refusal["status"] == "FAILED"
    assert refusal["error"]
    assert outputs[0].read_bytes() == saved
    assert {path: path.read_bytes() for path in original_inputs} == original_inputs
    assert not missing_settings.exists()
