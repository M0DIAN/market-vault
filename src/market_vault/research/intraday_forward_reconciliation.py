"""Offline observed-quote/paper-fill differences against one saved DEV account.

The complete saved transaction population is the denominator, not the supplied
observation subset. Clock and provenance claims are declarations, never proof
of obtainable fills, authenticated forward capture or strategy profitability.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import sys

from ..backtest.intraday import INTRADAY_COST_VERSION, INTRADAY_EXECUTION_VERSION
from ..dataset.cli import DatasetCLIError
from ..lifecycle import LifecycleLockError
from ..quality.market_data_comparison import (
    normalize_source, parse_utc, read_json_file, require_fields, utc_text,
)
from ..storage.atomic_file import AtomicFilePublicationError
from .intraday_data import digest
from .intraday_experiment import INTRADAY_EXPERIMENT_VERSIONS
from .intraday_research import _day, _identity
from .intraday_return_uncertainty import _integer
from .strategy_experiment import load_strategy_experiment


OBSERVATIONS_VERSION = "market-vault-intraday-forward-observations-v1"
RECONCILIATION_VERSION = "market-vault-intraday-forward-reconciliation-v1"
_METRICS = {"reference_to_ready_ms": "MILLISECONDS", "ready_to_quote_ms": "MILLISECONDS",
            "quote_age_ms": "MILLISECONDS", "ready_to_paper_fill_ms": "MILLISECONDS",
            "quote_adverse_bps": "BASIS_POINTS", "paper_fill_adverse_bps": "BASIS_POINTS"}


def _text(value, label):
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be nonempty text without surrounding whitespace")
    return value


def _number(value, label, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _stamp(value):
    if value is None:
        return None
    require_fields(value, ("timestamp", "clock_id"), label="clock stamp")
    return {"timestamp": utc_text(parse_utc(value["timestamp"])), "clock_id": _text(value["clock_id"], "clock_id")}


def _metric(value=None, reason=None):
    return {"value": value, "unavailable_reason": reason}


def _elapsed(first, last):
    if first is None or last is None:
        return _metric(reason="MISSING_TIMESTAMP")
    if first["clock_id"] is None or first["clock_id"] != last["clock_id"]:
        return _metric(reason="CLOCK_BASIS_MISMATCH")
    delta = (datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00")) -
             datetime.fromisoformat(first["timestamp"].replace("Z", "+00:00")))
    # Integer microseconds followed by one division preserves equality with a
    # caller's millisecond limit (9 us -> 0.009, not 0.009000000000000001).
    microseconds = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    if microseconds < 0:
        raise ValueError("impossible same-clock ordering in forward observation")
    return _metric(microseconds / 1000)


def _bps(price, reference, side):
    # Exact rational subtraction avoids an overflowing intermediate difference
    # and loss of small deviations before the final float conversion.
    try:
        value = float((Fraction(price) - Fraction(reference)) / Fraction(reference) *
                      (10000 if side == "BUY" else -10000))
    except (OverflowError, ZeroDivisionError):
        return _metric(reason="NUMERIC_OVERFLOW")
    return _metric(value) if math.isfinite(value) else _metric(reason="NUMERIC_OVERFLOW")


def _key(row):
    return row["symbol"], row["trading_day"], row["slot"], row["side"]


def normalize_forward_observations(value: dict) -> dict:
    """Normalize explicit identities, clock declarations and finite observations."""
    require_fields(value, ("schema_version", "expected_experiment_id", "cost_index", "candidate_index",
                           "expected_candidate_id", "source", "reference_clock_id", "policy", "records"),
                   label="forward observations")
    result = deepcopy(value)
    if result["schema_version"] != OBSERVATIONS_VERSION:
        raise ValueError("unsupported forward observations version")
    for key in ("expected_experiment_id", "expected_candidate_id"):
        _identity(result[key], key)
    for key in ("cost_index", "candidate_index"):
        _integer(result[key], key, 0)
    result["source"] = normalize_source(result["source"])
    if result["reference_clock_id"] is not None:
        _text(result["reference_clock_id"], "reference_clock_id")
    policy = require_fields(result["policy"], ("max_quote_age_ms", "max_adverse_quote_bps"), label="quote policy")
    _number(policy["max_quote_age_ms"], "max_quote_age_ms")
    if policy["max_adverse_quote_bps"] is not None:
        _number(policy["max_adverse_quote_bps"], "max_adverse_quote_bps")
    if type(result["records"]) is not list:
        raise ValueError("records must be an explicit array, including an empty array when unmeasured")
    seen = set()
    for row in result["records"]:
        require_fields(row, ("symbol", "trading_day", "slot", "side", "action_ready_at", "quote", "paper_fill"),
                       label="forward record")
        if type(row["symbol"]) is not str or re.fullmatch(r"US\.[A-Z0-9][A-Z0-9._-]*", row["symbol"]) is None:
            raise ValueError("record symbol must be an explicit uppercase US symbol")
        _day(row["trading_day"], "trading_day")
        _integer(row["slot"], "slot", 0)
        if row["side"] not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if _key(row) in seen:
            raise ValueError("duplicate forward action key; no silent choice or averaging")
        seen.add(_key(row))
        row["action_ready_at"] = _stamp(row["action_ready_at"])
        quote, fill = row["quote"], row["paper_fill"]
        if quote is not None:
            require_fields(quote, ("bid", "ask", "observed_at", "received_at"), label="quote")
            for key in ("bid", "ask"):
                if quote[key] is not None:
                    _number(quote[key], key, positive=True)
            for key in ("observed_at", "received_at"):
                quote[key] = _stamp(quote[key])
            _elapsed(quote["observed_at"], quote["received_at"])
            _elapsed(row["action_ready_at"], quote["received_at"])
        if fill is not None:
            require_fields(fill, ("price", "filled_at"), label="declared paper fill")
            _number(fill["price"], "paper fill price", positive=True)
            fill["filled_at"] = _stamp(fill["filled_at"])
            _elapsed(row["action_ready_at"], fill["filled_at"])
    return result


def _reference_rows(execution, symbol):
    """Bind saved transactions to their recorded OPEN grid and trade endpoints.

    The existing reader checks grammar and hashes, not every cross-record price
    relationship. These checks establish only internal reference consistency;
    they do not reconstruct Q5 or replay the account to certify market prices.
    """
    if (execution["version"] != INTRADAY_EXECUTION_VERSION
            or execution["cost_version"] != INTRADAY_COST_VERSION):
        raise ValueError("forward reconciliation requires supported execution V2 and fill-cost V2")
    signals = {(row["trading_day"], row["slot"]): row for row in execution["decisions"]}
    opens = {(row["trading_day"], row["slot"]): row for row in execution["ledger"] if row["phase"] == "OPEN"}
    starts = {row["trading_day"]: datetime.fromisoformat(row["open_time"]) for row in execution["daily"]}
    delta = timedelta(minutes=int(execution["interval"][:-1]))
    rows = []
    for index, transaction in enumerate(execution["transactions"]):
        day, slot = transaction["trading_day"], transaction["slot"]
        point = opens.get((day, slot))
        trade = execution["trades"][index // 2]
        endpoint = "entry" if transaction["side"] == "BUY" else "exit"
        clock = datetime.fromisoformat(transaction["timestamp"])
        decision = signals.get((day, slot - 1))
        decision_key = None if decision is None else decision["observation_key"]
        if (point is None or point["action"] != transaction["side"] or point["reason"] != transaction["reason"]
                or point["mark_price"] != transaction["raw_open"] or point["row_version_id"] != transaction["row_version_id"]
                or datetime.fromisoformat(point["timestamp"]) != clock or starts[day] + slot * delta != clock
                or trade["trading_day"] != day or trade[endpoint + "_slot"] != slot
                or datetime.fromisoformat(trade[endpoint + "_time"]) != clock
                or trade[endpoint + "_raw_open"] != transaction["raw_open"]
                or trade[endpoint + "_fill_price"] != transaction["fill_price"]
                or trade[endpoint + "_row_version_id"] != transaction["row_version_id"]
                or point["observation_key"] != decision_key
                or (endpoint == "exit" and trade["exit_reason"] != transaction["reason"])
                or (endpoint == "entry" and datetime.fromisoformat(trade["signal_time"]) != clock)
                or (transaction["reason"] in ("EOD", "MAX_HOLD") and trade["exit_observation_key"] is not None)):
            raise ValueError("saved transaction reference differs from its OPEN grid or trade endpoint")
        # An automatic exit can coincide with a fresh decision in the ledger;
        # validate that key above without presenting it as the exit's cause.
        signal = decision if transaction["reason"] in ("TARGET_LONG", "TARGET_FLAT") else None
        if transaction["reason"] in ("TARGET_LONG", "TARGET_FLAT") and (
                signal is None or signal["target"] != transaction["reason"].removeprefix("TARGET_")
                or datetime.fromisoformat(signal["decision_time"]) != clock
                or signal["observation_key"] != trade[endpoint + "_observation_key"]):
            raise ValueError("saved signal-triggered transaction lacks its matching preceding decision")
        rows.append({"transaction_index": index, "symbol": symbol,
                     **{key: transaction[key] for key in ("trading_day", "slot", "side", "reason", "row_version_id")},
                     "reference_open_time": utc_text(clock),
                     "raw_open": transaction["raw_open"], "modeled_fill_price": transaction["fill_price"],
                     "observation_key": None if signal is None else signal["observation_key"],
                     "signal_bar_end_time": None if signal is None else utc_text(datetime.fromisoformat(signal["decision_time"]))})
    return rows


def _reconcile(reference, record, batch):
    metrics = {key: _metric(reason="NO_OBSERVATION") for key in _METRICS}
    result = {"reference": reference, "observation": record, "metrics": metrics,
              "quote_status": "NO_OBSERVATION", "quote_policy_exceeded": None}
    if record is None:
        return result
    ready, quote, fill = record["action_ready_at"], record["quote"], record["paper_fill"]
    trigger = {"timestamp": reference["reference_open_time"], "clock_id": batch["reference_clock_id"]}
    metrics["reference_to_ready_ms"] = _elapsed(trigger, ready)
    metrics["ready_to_quote_ms"] = _elapsed(ready, None if quote is None else quote["received_at"])
    metrics["quote_age_ms"] = _elapsed(None if quote is None else quote["observed_at"],
                                        None if quote is None else quote["received_at"])
    metrics["ready_to_paper_fill_ms"] = _elapsed(ready, None if fill is None else fill["filled_at"])
    # Missing clock linkage cannot establish post-trigger/post-ready evidence.
    reason = ("NO_QUOTE" if quote is None else
              "MISSING_BID_ASK" if quote["bid"] is None or quote["ask"] is None else
              "CROSSED_QUOTE" if quote["bid"] > quote["ask"] else
              "REFERENCE_CLOCK_UNRESOLVED" if metrics["reference_to_ready_ms"]["value"] is None else
              "QUOTE_CLOCK_UNRESOLVED" if any(metrics[key]["value"] is None for key in
                                                ("ready_to_quote_ms", "quote_age_ms")) else
              "STALE_QUOTE" if metrics["quote_age_ms"]["value"] > batch["policy"]["max_quote_age_ms"] else None)
    metrics["quote_adverse_bps"] = (_metric(reason=reason) if reason else
        _bps(quote["ask" if reference["side"] == "BUY" else "bid"], reference["raw_open"], reference["side"]))
    result["quote_status"] = metrics["quote_adverse_bps"]["unavailable_reason"] or "MEASURED"
    threshold, deviation = batch["policy"]["max_adverse_quote_bps"], metrics["quote_adverse_bps"]["value"]
    if threshold is not None and deviation is not None:
        result["quote_policy_exceeded"] = deviation > threshold
    fill_reason = ("NO_PAPER_FILL" if fill is None else "PAPER_FILL_CLOCK_UNRESOLVED" if
                   metrics["reference_to_ready_ms"]["value"] is None or metrics["ready_to_paper_fill_ms"]["value"] is None else None)
    metrics["paper_fill_adverse_bps"] = (_metric(reason=fill_reason) if fill_reason else
        _bps(fill["price"], reference["raw_open"], reference["side"]))
    return result


def analyze_intraday_forward_reconciliation(experiment_path: str | Path, observations: dict) -> dict:
    """Read one exact DEV artifact and reconcile, without Q5 I/O or execution."""
    batch = normalize_forward_observations(observations)
    snapshot = load_strategy_experiment(experiment_path)
    root = snapshot.as_dict()
    if root["artifact_schema_version"] not in INTRADAY_EXPERIMENT_VERSIONS:
        raise ValueError("forward reconciliation requires an ordinary saved Q7 DEV artifact")
    if root["experiment_id"] != batch["expected_experiment_id"]:
        raise ValueError("selected experiment identity differs")
    groups = root["report"]["groups"]
    ci, si = batch["cost_index"], batch["candidate_index"]
    if ci >= len(groups) or si >= len(groups[ci]["results"]):
        raise ValueError("selected cost/candidate index is outside the saved experiment")
    candidate = groups[ci]["results"][si]
    if candidate["candidate_id"] != batch["expected_candidate_id"]:
        raise ValueError("selected candidate identity differs")
    execution = candidate["execution"]
    references = _reference_rows(execution, root["report"]["context"]["symbol"])
    recorded = {_key(row): row for row in batch["records"]}
    rows = [_reconcile(row, recorded.pop(_key(row), None), batch) for row in references]
    measured = sum(row["quote_status"] == "MEASURED" for row in rows)
    status = ("NO_REFERENCE_ACTIONS" if not rows else "NOT_MEASURED" if not measured else
              "RECONCILED" if measured == len(rows) and not recorded else "PARTIAL")
    summary = {"reference_action_count": len(rows), "supplied_record_count": len(batch["records"]),
               "matched_record_count": len(batch["records"]) - len(recorded), "unmatched_record_count": len(recorded),
               "missing_record_count": sum(row["observation"] is None for row in rows),
               "measured_quote_count": measured,
               "quote_policy_exceeded_count": sum(row["quote_policy_exceeded"] is True for row in rows)}
    statistics = {}
    for key, unit in _METRICS.items():
        values = [row["metrics"][key]["value"] for row in rows if row["metrics"][key]["value"] is not None]
        mean = float(sum(map(Fraction, values), Fraction()) / len(values)) if values else None
        statistics[key] = {"unit": unit, "available_count": len(values), "unavailable_count": len(rows) - len(values),
                           "mean": mean, "maximum": max(values) if values else None}
    result = {"version": RECONCILIATION_VERSION, "status": status,
              "source": {"experiment_id": snapshot.experiment_id, "data_id": root["dataset_id"],
                         "candidate_id": candidate["candidate_id"], "execution_id": execution["execution_id"],
                         "strategy": candidate["strategy"], "execution_policy": execution["policy"],
                         "algorithm_versions": root["algorithm_versions"], "environment": root["environment"]},
              "observations_id": digest(batch), "observation_source": batch["source"],
              "reference_clock_id": batch["reference_clock_id"], "policy": batch["policy"],
              "policy_id": digest(batch["policy"]), "summary": summary, "statistics": statistics,
              "rows": rows, "unmatched_records": list(recorded.values()),
              "forward_capture_verified": False, "fills_verified": False,
              "limitations": [
                  "Only the exact saved DEV transaction population is assessed, not all possible signals or trades.",
                  "Reference clocks, action links and observed provenance are caller declarations, not authenticated capture.",
                  "Missing/unmatched/stale/crossed/clock-unresolved evidence is retained, not zero slippage or latency.",
                  "BUY uses ask and SELL uses bid; positive basis points are adverse versus raw next open, excluding fees.",
                  "Modeled fill price is shown separately; existing slippage/commission is not added twice.",
                  "Scheduled EOD/MAX_HOLD actions have no invented signal-bar observation.",
                  "Reference-to-ready and ready-to-quote time differences are not order-routing or actual fill latency.",
                  "Paper fills are declarations separate from quotes and are not verified brokerage fills.",
                  "RECONCILED means complete quote measurement only; policy exceedances and denominators remain separate.",
                  "No policy timing, strategy preregistration, capacity, queue position, PnL or profitability is certified.",
                  "Reference consistency is checked against saved OPEN/trade records, not reconstructed market data or full execution replay.",
                  "No source data is repaired, no TEST is scored and no model/account is re-executed.",
              ]}
    return {**result, "reconciliation_id": digest(result)}


def main(argv=None) -> int:
    """Exclusive new-file module CLI; no root-command or GUI behavior changes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        from ..quality.market_data_comparison import write_market_data_json
        report = analyze_intraday_forward_reconciliation(args.experiment, read_json_file(args.observations))
        output = write_market_data_json(args.output, report)
        print(json.dumps({"version": RECONCILIATION_VERSION, "status": report["status"],
                          "output": str(output), "report": report}, allow_nan=False))
        return 0 if report["status"] == "RECONCILED" and not report["summary"]["quote_policy_exceeded_count"] else 2
    except (DatasetCLIError, OSError, TypeError, ValueError, KeyError, ArithmeticError, RecursionError,
            LifecycleLockError, AtomicFilePublicationError) as exc:
        payload = {"version": RECONCILIATION_VERSION, "status": "FAILED", "error": str(exc)}
        if isinstance(exc, AtomicFilePublicationError):
            payload["published"] = exc.published
        print(json.dumps(payload), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
