"""Read-only price-window screening with explicitly incomplete action coverage.

This current-reader disclosure never changes an input artifact, replays a
strategy, or turns unadjusted prices into a corporate-action total return.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from ..backtest.equity import BUY_AND_HOLD_VERSION, EQUITY_VERSION
from ..backtest.intraday import EVENT_ORDER, INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION
from ..backtest.models import BACKTEST_ENGINE_VERSION
from ..cross_day._authority import INTERVAL_MINUTES
from ..cross_day_dataset import load_verified_multi_source_cross_day_dataset
from .intraday_data import INTRADAY_DATA_VERSION, canonical_json, digest, object_fields, parse_json
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_final_test import INTRADAY_TEST_EXPERIMENT_VERSIONS
from .intraday_research import BENCHMARK_DEFINITION, INTRADAY_BENCHMARK_VERSION
from .strategy_equity import STRATEGY_EQUITY_VERSION
from .strategy_experiment import STRATEGY_EXPERIMENT_VERSION, load_strategy_experiment
from .strategy_risk import STRATEGY_RISK_VERSION


RETURN_ASSESSMENT_VERSION = "market-vault-return-assessment-v1"
RESTRICTION_LIST_VERSION = "market-vault-return-restrictions-v1"
_ZONE = ZoneInfo("America/New_York")
_CLOCK = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)")
_PRICE_FIELDS = frozenset(("open", "high", "low", "close"))
_LABELS = {f"market_vault.dataset.label_transforms.{name}:{name}": name for name in (
    "forward_return", "forward_direction", "forward_open_to_close_return",
    "maximum_favorable_excursion", "maximum_adverse_excursion",
)}


class ReturnAssessmentError(ValueError):
    """An assessment input or precision limitation, not an artifact migration."""

    def __init__(self, reason_code, message):
        self.reason_code = reason_code
        super().__init__(message)


def _require(condition, message, code="CONTRADICTORY_WINDOW_EVIDENCE"):
    if not condition:
        raise ReturnAssessmentError(code, message)


def _clock(value):
    if type(value) is str:
        _require(_CLOCK.fullmatch(value) is not None,
                 "assessment requires a full date and HH:MM:SS with Z or ±HH:MM, and at most six fractional timestamp digits",
                 "UNSUPPORTED_PRICE_CLOCK")
    parsed = datetime.fromisoformat(value) if type(value) is str else value
    _require(isinstance(parsed, datetime) and parsed.tzinfo is not None and parsed.utcoffset() is not None,
             "an aware timestamp is required", "INVALID_INPUT")
    return parsed.astimezone(timezone.utc)


def _stamp(value):
    return _clock(value).isoformat(timespec="microseconds")


def _text(value, name):
    _require(type(value) is str and bool(value.strip()), f"{name} must be a nonempty string", "INVALID_INPUT")
    return value


def _day(value):
    _require(type(value) is str and date.fromisoformat(value).isoformat() == value,
             "dates must use YYYY-MM-DD", "INVALID_INPUT")
    return value


def parse_event_restrictions(payload: bytes) -> dict:
    """Normalize an explicit finite list; its provenance is a declaration only."""
    root = parse_json(payload)
    object_fields(root, {"schema_version", "provenance", "events"}, "return restrictions")
    _require(root["schema_version"] == RESTRICTION_LIST_VERSION,
             "unsupported return restriction list version", "INVALID_INPUT")
    _text(root["provenance"], "provenance")
    _require(type(root["events"]) is list, "events must be a finite JSON array", "INVALID_INPUT")
    events, seen = [], set()
    for item in root["events"]:
        _require(type(item) is dict, "each event must be an object", "INVALID_INPUT")
        kind = item.get("kind")
        extra = ({"effective_at"} if kind == "EFFECTIVE_INSTANT" else
                 {"start_date", "end_date"} if kind == "DATE_RESTRICTION" else None)
        _require(extra is not None, "event kind must be EFFECTIVE_INSTANT or DATE_RESTRICTION", "INVALID_INPUT")
        object_fields(item, {"event_id", "symbol", "kind", "source"} | extra, "event restriction")
        event_id = _text(item["event_id"], "event_id")
        _require(event_id not in seen, "duplicate event_id", "INVALID_INPUT")
        seen.add(event_id)
        _text(item["source"], "event source")
        _require(type(item["symbol"]) is str and re.fullmatch(r"US\.[A-Z0-9][A-Z0-9.\-]*", item["symbol"]),
                 "event symbol must be an explicit canonical US symbol", "INVALID_INPUT")
        event = dict(item)
        if kind == "EFFECTIVE_INSTANT":
            event["effective_at"] = _stamp(item["effective_at"])
        else:
            start, end = _day(item["start_date"]), _day(item["end_date"])
            _require(start <= end, "date restriction is reversed", "INVALID_INPUT")
        events.append(event)
    return {**root, "events": sorted(events, key=lambda event: event["event_id"])}


def _window(role, owner, symbol, start, end, first, last, basis):
    start, end = _clock(start), _clock(end)
    _require(start <= end, "price-consuming window is reversed")
    record = {"role": role, "owner_id": owner, "symbol": symbol,
              "start_time": _stamp(start), "end_time": _stamp(end), "clock_basis": basis,
              "start_row_version_id": first, "end_row_version_id": last,
              "crosses_market_dates": start.astimezone(_ZONE).date() != end.astimezone(_ZONE).date()}
    return {**record, "window_id": digest({"version": RETURN_ASSESSMENT_VERSION, **record})}


class _DatasetPrices:
    """Index only the immutable recorded schedule and bars already verified."""

    def __init__(self, dataset):
        _require(dataset.scope.adjustment == "NONE" and dataset.scope.requested_session == "RTH",
                 "assessment v1 requires NONE/RTH Dataset prices", "UNSUPPORTED_SOURCE")
        self.days = {day.market_calendar_date: day for day in dataset.schedule.daily_records}
        self.bars = {bar.canonical_row_version_id: bar for build in dataset.identity_input.canonical_builds
                     for bar in build.bars}

    def support(self, row_id):
        _require(row_id in self.bars, "consumed price row is absent from the verified Dataset")
        bar = self.bars[row_id]
        day = self.days.get(bar.market_calendar_date)
        _require(day is not None and day.day_status == "TRADING", "consumed row has no recorded trading session")
        step = timedelta(minutes=INTERVAL_MINUTES[bar.interval])
        event, opened, closed = _clock(bar.event_time), _clock(day.session_open), _clock(day.session_close)
        _require(opened <= event < closed and (event - opened) % step == timedelta(0),
                 "consumed row does not fit its recorded session grid", "UNSUPPORTED_PRICE_CLOCK")
        # Availability is an information clock. A truncated final bar's price
        # support ends at the recorded session close, not the nominal interval.
        return bar, event, min(event + step, closed)


def _label_window(prices, value, spec, *, role="LABEL", owner=None):
    transform = _LABELS.get(spec.transform_ref)
    _require(transform is not None, "unsupported recorded Label price semantics", "UNSUPPORTED_ECONOMIC_VERSION")
    rows = [prices.support(ref.canonical_row_version_id) for ref in value.consumed_rows]
    _require(bool(rows), "complete Label has no consumed rows")
    if transform == "forward_open_to_close_return":
        first, start, _ = rows[0]
    else:
        first, _, start = prices.support(value.anchor_canonical_row_version_id)
    last, _, end = rows[-1]
    _require(all(bar.code == first.code for bar, _, _ in rows), "Label consumed mixed symbols")
    basis = ("CONSUMED_BAR_SPAN" if transform in ("maximum_favorable_excursion", "maximum_adverse_excursion")
             else "PRICE_ENDPOINTS")
    return _window(role, owner or value.sample_key + ":" + value.label_name, first.code,
                   start, end, first.canonical_row_version_id, last.canonical_row_version_id, basis)


def _dataset_windows(dataset):
    prices = _DatasetPrices(dataset)
    windows, omitted = [], Counter()
    specs = {spec.name: spec for spec in dataset.ts2_features.feature_specs}
    for sample in dataset.ts2_features.samples:
        for value in sample.values:
            fields = set(specs[value.feature_name].input_canonical_fields)
            if not fields & _PRICE_FIELDS:
                omitted["volume_only_features"] += 1
                continue
            if value.status != "COMPLETE":
                omitted["incomplete_price_features"] += 1
                continue
            rows = [prices.support(row) for row in value.consumed_canonical_row_version_ids]
            _require(bool(rows), "complete Feature has no consumed rows")
            first, event, close = rows[0]
            last, _, end = rows[-1]
            _require(all(bar.code == first.code for bar, _, _ in rows), "Feature consumed mixed symbols")
            span = bool(fields & {"open", "high", "low"})
            windows.append(_window("FEATURE", sample.sample_key + ":" + value.feature_name,
                                   first.code, event if span else close, end,
                                   first.canonical_row_version_id, last.canonical_row_version_id,
                                   "CONSUMED_BAR_SPAN" if span else "PRICE_ENDPOINTS"))
    specs = {spec.name: spec for spec in dataset.cross_day_labels.label_specs}
    for value in dataset.cross_day_labels.values:
        if value.status != "COMPLETE":
            omitted["incomplete_price_labels"] += 1
            continue
        windows.append(_label_window(prices, value, specs[value.label_name]))
    omitted["observation_features"] = sum(len(sample.values) for sample in dataset.observation_features.samples)
    return windows, dict(omitted)


def _versions(recorded, expected):
    for key, version in expected.items():
        _require(recorded.get(key) == version, f"assessment does not support recorded {key} economic version",
                 "UNSUPPORTED_ECONOMIC_VERSION")
    return {key: recorded[key] for key in sorted(expected)}


def _same_price_clock(recorded, supported):
    _require(_clock(recorded) == _clock(supported),
             "Assessment-only precision limitation: saved simulation clock " + _stamp(recorded)
             + " differs from actual price support " + _stamp(supported)
             + ". The saved artifact's validity, Open and Replay behavior are unchanged.",
             "UNSUPPORTED_PRICE_CLOCK")


def _base_windows(root, dataset):
    _require(dataset.dataset_id == root["dataset_id"], "source Dataset identity differs from the saved experiment",
             "SOURCE_ID_MISMATCH")
    _require(len(dataset.scope.symbols) == 1, "saved base assessment requires its exact single-symbol Dataset",
             "UNSUPPORTED_SOURCE")
    prices, report = _DatasetPrices(dataset), root["report"]
    expected = {"backtest": BACKTEST_ENGINE_VERSION}
    if root["evaluation_mode"] in ("EQUITY", "RISK"):
        expected.update(equity=EQUITY_VERSION, strategy_equity=STRATEGY_EQUITY_VERSION)
    if root["evaluation_mode"] == "RISK":
        expected.update(buy_and_hold=BUY_AND_HOLD_VERSION, strategy_risk=STRATEGY_RISK_VERSION)
    versions = _versions(root["algorithm_versions"], expected)
    specs = {spec.name: spec for spec in dataset.cross_day_labels.label_specs}
    spec = specs.get(report["return_label"])
    _require(spec is not None and _LABELS.get(spec.transform_ref) == "forward_open_to_close_return",
             "saved strategy needs its execution-safe open-to-close Label", "UNSUPPORTED_SOURCE")
    values = {value.sample_key: value for value in dataset.cross_day_labels.values
              if value.label_name == spec.name and value.status == "COMPLETE"}
    samples = {sample.sample_key: sample.request for sample in dataset.feature_pit.samples}
    windows = []
    for result in report["results"]:
        previous_end = None
        result_windows = []
        for trade in result["trades"]:
            key = trade["sample_key"]
            _require(key in values and key in samples and key in report["validation_sample_keys"],
                     "saved trade does not bind a complete validation Label")
            request, value = samples[key], values[key]
            _require(trade["code"] == request.code == dataset.scope.symbols[0]
                     and _clock(trade["signal_time"]) == _clock(request.feature_window_close),
                     "saved trade symbol or signal differs from its Dataset sample")
            window = _label_window(prices, value, spec, role="STRATEGY_TRADE", owner=result["result_id"] + ":" + key)
            _require(_clock(trade["entry_time"]) == _clock(window["start_time"])
                     and _clock(trade["exit_time"]) == _clock(value.actual_label_end_time),
                     "saved trade endpoints differ from its recorded Dataset Label")
            _same_price_clock(trade["exit_time"], window["end_time"])
            _require(previous_end is None or previous_end <= _clock(trade["entry_time"]), "saved strategy holdings overlap")
            previous_end = _clock(trade["exit_time"])
            windows.append(window)
            result_windows.append(window)
        if root["evaluation_mode"] in ("EQUITY", "RISK"):
            curve = next(curve for curve in report["equity"]["results"]
                         if curve["strategy_result_id"] == result["result_id"])
            points = [point for point in curve["points"] if point["event"] in ("ENTRY", "EXIT")]
            _require(len(points) == 2 * len(result_windows), "saved equity endpoints disagree with accepted trades")
            for index, (trade, window) in enumerate(zip(result["trades"], result_windows, strict=True)):
                for event, side, point in zip(("ENTRY", "EXIT"), ("start", "end"), points[2 * index:2 * index + 2], strict=True):
                    bar = prices.bars[window[side + "_row_version_id"]]
                    _require(point["event"] == event and point["sample_key"] == trade["sample_key"]
                             and point["row_version_id"] == bar.canonical_row_version_id
                             and _clock(point["timestamp"]) == _clock(window[side + "_time"])
                             and point["mark_price"] == (bar.open if event == "ENTRY" else bar.close),
                             "saved equity endpoint does not bind its trade and Dataset price")
    if root["evaluation_mode"] == "RISK":
        keys = report["validation_sample_keys"]
        _require(bool(keys) and all(key in values for key in keys), "benchmark has no complete validation price window")
        support = [_label_window(prices, values[key], spec) for key in keys]
        start = min(_clock(window["start_time"]) for window in support)
        recorded_end = max(_clock(values[key].actual_label_end_time) for key in keys)
        equity, curve = report["equity"], report["risk"]["benchmark"]["curve"]
        _require(_clock(equity["start_time"]) == start and _clock(equity["end_time"]) == recorded_end,
                 "benchmark window differs from the Dataset validation window")
        entries = [point for point in curve["points"] if point["event"] == "ENTRY"]
        exits = [point for point in curve["points"] if point["event"] == "EXIT"]
        _require(len(entries) == len(exits) == 1, "buy-and-hold benchmark must have one entry and exit")
        entry, exit = entries[0], exits[0]
        first, event, _ = prices.support(entry["row_version_id"])
        last, _, end = prices.support(exit["row_version_id"])
        _require(first.code == last.code == dataset.scope.symbols[0] and event == start
                 and _clock(entry["timestamp"]) == start and _clock(exit["timestamp"]) == recorded_end
                 and entry["mark_price"] == first.open and exit["mark_price"] == last.close,
                 "benchmark endpoint prices do not bind its Dataset")
        _same_price_clock(recorded_end, end)
        windows.append(_window("BENCHMARK_HOLDING", curve["curve_id"], first.code, start, end,
                               first.canonical_row_version_id, last.canonical_row_version_id, "PRICE_ENDPOINTS"))
    return windows, versions


def _intraday_windows(execution, symbol, owner, role):
    """Bind saved endpoints to their own daily grid, without running a kernel."""
    _require(execution["version"] == INTRADAY_EXECUTION_VERSION
             and execution["cost_version"] == INTRADAY_COST_VERSION and execution["event_order"] == EVENT_ORDER,
             "unsupported saved execution economics", "UNSUPPORTED_ECONOMIC_VERSION")
    step = timedelta(minutes=INTERVAL_MINUTES[execution["interval"]])
    sessions, previous = {}, None
    for row in execution["daily"]:
        opened, closed = _clock(row["open_time"]), _clock(row["close_time"])
        day = row["trading_day"]
        _require(opened.astimezone(_ZONE).date().isoformat() == closed.astimezone(_ZONE).date().isoformat() == day
                 and opened < closed and (closed - opened) % step == timedelta(0)
                 and (previous is None or previous < opened), "saved daily sessions contradict their market dates/grid")
        sessions[day] = (opened, closed, (closed - opened) // step)
        previous = closed
    grid, actions, price_records, index = {}, [], [], 0
    ledger = execution["ledger"]
    for day, (opened, _, count) in sessions.items():
        held_quantity = 0.0
        for slot in range(count):
            _require(index + 1 < len(ledger), "saved ledger has an incomplete price grid")
            op, cl = ledger[index:index + 2]
            index += 2
            _require(op["phase"] == "OPEN" and cl["phase"] == "CLOSE"
                     and all(point["trading_day"] == day and point["slot"] == slot for point in (op, cl))
                     and op["row_version_id"] == cl["row_version_id"]
                     and _clock(op["timestamp"]) == opened + slot * step
                     and _clock(cl["timestamp"]) == opened + (slot + 1) * step,
                     "saved OPEN/CLOSE price evidence contradicts the daily slot grid")
            _require(cl["action"] == "MARK", "a saved CLOSE point contains an execution action")
            if op["action"] == "BUY":
                _require(held_quantity == 0 and op["quantity"] > 0, "saved BUY contradicts its holding state")
                held_quantity = op["quantity"]
            elif op["action"] == "SELL":
                _require(held_quantity > 0 and op["quantity"] == 0, "saved SELL contradicts its holding state")
                held_quantity = 0.0
            _require(op["quantity"] == cl["quantity"] == held_quantity,
                     "saved price ledger contains holdings absent from its execution actions")
            price_records.append((day, slot, op["row_version_id"], _stamp(op["timestamp"]),
                                  _stamp(cl["timestamp"]), op["mark_price"], cl["mark_price"]))
            grid[day, slot] = op
            if op["action"] in ("BUY", "SELL"):
                actions.append(op)
        _require(held_quantity == 0, "saved session ends with a holding instead of forced-flat cash")
    _require(index == len(ledger), "saved ledger contains extra price grid points")
    transactions = execution["transactions"]
    _require(len(actions) == len(transactions) == 2 * len(execution["trades"]),
             "saved holdings, transactions and execution actions disagree")
    for action, transaction in zip(actions, transactions, strict=True):
        _require(action["action"] == transaction["side"] and action["mark_price"] == transaction["raw_open"]
                 and all(action[key] == transaction[key] for key in ("trading_day", "slot", "row_version_id"))
                 and _clock(action["timestamp"]) == _clock(transaction["timestamp"]),
                 "saved transaction does not bind its OPEN ledger endpoint")
        if action["action"] == "BUY":
            _require(action["quantity"] == transaction["quantity"], "saved BUY quantity differs from its holding")
    windows, previous_exit = [], None
    restrictions = {row["trading_day"]: row for row in execution["windows"]}
    decisions = {row["observation_key"]: row for row in execution["decisions"]}
    for index, trade in enumerate(execution["trades"]):
        day = trade["trading_day"]
        for prefix, transaction in zip(("entry", "exit"), transactions[2 * index:2 * index + 2], strict=True):
            point = grid.get((day, trade[prefix + "_slot"]))
            _require(point is not None and transaction["trading_day"] == day
                     and trade[prefix + "_slot"] == transaction["slot"]
                     and trade[prefix + "_row_version_id"] == transaction["row_version_id"]
                     and trade[prefix + "_raw_open"] == transaction["raw_open"]
                     and trade["quantity"] == transaction["quantity"]
                     and _clock(trade[prefix + "_time"]) == _clock(transaction["timestamp"]),
                     "saved trade endpoint does not bind its transaction and daily price grid")
        entry, exit = _clock(trade["entry_time"]), _clock(trade["exit_time"])
        decision = decisions.get(trade["entry_observation_key"])
        _require(decision is not None and decision["trading_day"] == day
                 and decision["slot"] + 1 == trade["entry_slot"]
                 and _clock(decision["decision_time"]) == _clock(trade["signal_time"]),
                 "saved entry does not bind its preceding recorded decision")
        policy_window = restrictions[day]
        _require(_clock(policy_window["earliest_entry_time"]) <= entry < _clock(policy_window["stop_new_time"])
                 and entry < exit <= _clock(policy_window["forced_flat_time"])
                 and (previous_exit is None or previous_exit < entry),
                 "saved holding crosses its entry/forced-flat window or another holding")
        previous_exit = exit
        windows.append(_window(role, owner + ":" + trade["trade_id"], symbol, entry, exit,
                               trade["entry_row_version_id"], trade["exit_row_version_id"], "RECORDED_EXECUTION"))
    return windows, tuple(price_records)


def _saved_intraday_windows(root):
    versions = _versions(root["algorithm_versions"], {
        "data": INTRADAY_DATA_VERSION, "execution": INTRADAY_EXECUTION_VERSION,
        "cost": INTRADAY_COST_VERSION, "benchmark": INTRADAY_BENCHMARK_VERSION})
    report, windows = root["report"], []
    symbol = report["context"]["symbol"]
    if root["artifact_schema_version"] in INTRADAY_EXPERIMENT_VERSIONS:
        records = []
        for group in report["groups"]:
            records.extend((result["execution"], result["candidate_id"], "STRATEGY_TRADE") for result in group["results"])
            benchmark = group["benchmark"]
            _require(benchmark["definition"] == BENCHMARK_DEFINITION, "unsupported benchmark holding definition",
                     "UNSUPPORTED_ECONOMIC_VERSION")
            records.append((benchmark["execution"], "cost:" + str(group["cost_index"]) + ":benchmark", "BENCHMARK_HOLDING"))
    else:
        _require(report["benchmark"]["definition"] == BENCHMARK_DEFINITION, "unsupported benchmark holding definition",
                 "UNSUPPORTED_ECONOMIC_VERSION")
        records = [(report["execution"], report["final_test_id"], "STRATEGY_TRADE"),
                   (report["benchmark"]["execution"], "test:benchmark", "BENCHMARK_HOLDING")]
    price_grids, row_meanings = {}, {}
    for execution, owner, role in records:
        holdings, grid = _intraday_windows(execution, symbol, owner, role)
        previous = price_grids.setdefault(execution["price_evidence_id"], grid)
        _require(previous == grid, "one saved price_evidence_id carries contradictory price grids")
        for price in grid:
            previous = row_meanings.setdefault(price[2], price)
            _require(previous == price, "one saved row version ID carries contradictory bar meanings")
        windows.extend(holdings)
    return windows, versions


def _assessment(*, source_kind, source_id, dataset_id, evidence, versions, windows, omitted, events):
    restrictions = None if events is None else parse_event_restrictions(canonical_json(events))
    windows = sorted(windows, key=lambda row: (row["role"], row["owner_id"], row["window_id"]))
    matches = []
    for event in (() if restrictions is None else restrictions["events"]):
        for window in windows:
            if event["symbol"] != window["symbol"]:
                continue
            start, end = _clock(window["start_time"]), _clock(window["end_time"])
            if event["kind"] == "EFFECTIVE_INSTANT":
                hit = start < _clock(event["effective_at"]) <= end
                reason = "DECLARED_EFFECTIVE_INSTANT_IN_WINDOW"
            else:
                hit = (start.astimezone(_ZONE).date().isoformat() <= event["end_date"]
                       and end.astimezone(_ZONE).date().isoformat() >= event["start_date"])
                reason = "CONSERVATIVE_DATE_RESTRICTION_OVERLAP"
            if hit:
                matches.append({"event_id": event["event_id"], "window_id": window["window_id"], "reason": reason})
    dataset_source = source_kind == "DATASET"
    counts = Counter(window["role"] for window in windows)
    result = {"version": RETURN_ASSESSMENT_VERSION, "source_kind": source_kind, "source_id": source_id,
        "source_evidence": evidence, "dataset_id": dataset_id, "source_economic_versions": versions,
        "price_basis": "NONE_UNADJUSTED", "split_share_adjustment": "NOT_APPLIED",
        "cash_dividend_accounting": "NOT_APPLIED", "total_return_semantics": "SIMULATED_ACCOUNT_CHANGE",
        "coverage_status": "UNKNOWN" if restrictions is None else "PARTIAL",
        "screening_status": ("NOT_CHECKED" if restrictions is None else
                             "KNOWN_RESTRICTION_INTERSECTION" if matches else "NO_LISTED_INTERSECTION"),
        "restriction_list_id": None if restrictions is None else digest(restrictions),
        "restriction_list_version": None if restrictions is None else restrictions["schema_version"],
        "restriction_provenance": None if restrictions is None else restrictions["provenance"],
        "restriction_events": None if restrictions is None else restrictions["events"],
        "assessed_classes": (["COMPLETE_PRICE_FEATURES", "COMPLETE_PRICE_LABELS"] if dataset_source else
                             ["RECORDED_STRATEGY_HOLDINGS", "RECORDED_BENCHMARK_HOLDINGS"]),
        "excluded_classes": (["VOLUME_ONLY_FEATURES", "OBSERVATION_FEATURES", "INCOMPLETE_CALCULATIONS"]
                             if dataset_source else ["TRAINING_FEATURES", "TRAINING_TARGETS", "UNEXECUTED_SIGNALS"]),
        "window_counts": {**dict(sorted(counts.items())), "total": len(windows),
                          "crosses_market_dates": sum(window["crosses_market_dates"] for window in windows)},
        "omitted_counts": dict(sorted(omitted.items())), "windows": windows, "restriction_matches": matches}
    return {**result, "assessment_id": digest(result)}


def assess_dataset(build_dir: str | Path, *, events: dict | None = None) -> dict:
    """Assess exact verified Dataset price consumption, not a requested horizon."""
    dataset = load_verified_multi_source_cross_day_dataset(build_dir)
    windows, omitted = _dataset_windows(dataset)
    return _assessment(source_kind="DATASET", source_id=dataset.dataset_id, dataset_id=dataset.dataset_id,
                       evidence="STRICT_VERIFIED_DATASET", versions={}, windows=windows, omitted=omitted, events=events)


def assess_saved_experiment(path: str | Path, *, events: dict | None = None,
                            source_dataset: str | Path | None = None) -> dict:
    """Assess validated saved records; this is neither Canonical proof nor replay."""
    root = load_strategy_experiment(path).as_dict()
    schema = root["artifact_schema_version"]
    if schema == STRATEGY_EXPERIMENT_VERSION:
        dataset = load_verified_multi_source_cross_day_dataset(source_dataset or root["plan"]["dataset_build_dir"])
        windows, versions = _base_windows(root, dataset)
        source_kind = "SAVED_BASE_EXPERIMENT"
    elif schema in (*INTRADAY_EXPERIMENT_VERSIONS, *INTRADAY_TEST_EXPERIMENT_VERSIONS):
        _require(source_dataset is None, "source-dataset applies only to a saved base experiment", "INVALID_INPUT")
        windows, versions = _saved_intraday_windows(root)
        source_kind = "SAVED_INTRADAY_EXPERIMENT"
    else:
        raise ReturnAssessmentError("UNSUPPORTED_SOURCE", "assessment v1 supports ordinary saved base/intraday/TEST experiments only")
    return _assessment(source_kind=source_kind, source_id=root["experiment_id"], dataset_id=root["dataset_id"],
                       evidence="VALIDATED_SAVED_RECORDS_NOT_REPLAYED", versions=versions,
                       windows=windows, omitted={}, events=events)
