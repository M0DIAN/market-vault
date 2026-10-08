"""Intraday V2 cash execution, independent of training targets and data I/O.

The research adapter establishes source authority. This pure kernel validates
an explicit complete price grid and consumes fresh Long/Flat decisions only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
import math

from .models import _finite_number, _instant


INTRADAY_EXECUTION_VERSION = "market-vault-intraday-execution-v2"
INTRADAY_COST_VERSION = "market-vault-intraday-fill-cost-v2"
EVENT_ORDER = "BAR_CLOSE_THEN_DECISION_THEN_NEXT_PLANNED_OPEN"


def _digest(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _time(value: str) -> datetime:
    if type(value) is not str:
        raise ValueError("execution timestamps must be aware ISO strings")
    result = datetime.fromisoformat(value)
    _instant(result, "execution timestamp")
    return result


@dataclass(frozen=True, slots=True)
class IntradayExecutionPolicy:
    commission_bps: float
    slippage_bps: float
    entry_delay_minutes: int = 15
    stop_new_minutes: int = 30
    flatten_minutes: int = 5
    max_hold_bars: int = 12

    def __post_init__(self) -> None:
        for name in ("commission_bps", "slippage_bps"):
            value = _finite_number(getattr(self, name), name)
            if not 0 <= value < 10_000:
                raise ValueError(f"{name} must be in [0, 10000)")
            object.__setattr__(self, name, 0.0 if value == 0 else value)
        for name in ("entry_delay_minutes", "stop_new_minutes", "flatten_minutes", "max_hold_bars"):
            value = getattr(self, name)
            minimum = 0 if name == "entry_delay_minutes" else 1
            if type(value) is not int or not minimum <= value <= 2**31 - 1:
                raise ValueError(f"{name} must be an integer >= {minimum}")


def _inputs(sessions: tuple[dict, ...], prices: tuple[dict, ...], decisions: tuple[dict, ...],
            interval: str, policy: IntradayExecutionPolicy):
    if type(policy) is not IntradayExecutionPolicy:
        raise ValueError("IntradayExecutionPolicy is required")
    policy = IntradayExecutionPolicy(**asdict(policy))
    if interval not in ("1m", "5m", "15m", "30m"):
        raise ValueError("execution interval must be 1m, 5m, 15m or 30m")
    if type(sessions) is not tuple or not sessions or type(prices) is not tuple or type(decisions) is not tuple:
        raise ValueError("explicit immutable session, price and decision sequences are required")
    delta = timedelta(minutes=int(interval[:-1]))
    calendars, expected = {}, set()
    for session in sessions:
        day = session["trading_day"]
        start, end = _time(session["open_time"]), _time(session["close_time"])
        count = session["bar_count"]
        if (type(day) is not str or day in calendars or type(count) is not int or count <= 0
                or end - start != count * delta):
            raise ValueError("invalid complete session geometry")
        # Bound minute arithmetic before constructing timedeltas.
        minutes = (end - start).total_seconds() / 60
        if any(getattr(policy, name) >= minutes for name in
               ("entry_delay_minutes", "stop_new_minutes", "flatten_minutes")):
            raise ValueError("execution windows do not fit the declared session")
        first = start + timedelta(minutes=policy.entry_delay_minutes)
        stop = end - timedelta(minutes=policy.stop_new_minutes)
        flatten_slot = (end - timedelta(minutes=policy.flatten_minutes) - start) // delta
        flatten = start + flatten_slot * delta
        if not start <= first < stop <= flatten < end:
            raise ValueError("execution windows must precede the rounded forced-flat open")
        calendars[day] = {"start": start, "end": end, "count": count,
                          "first": first, "stop": stop, "flatten_slot": flatten_slot}
        expected.update((day, slot) for slot in range(count))
    if list(calendars) != sorted(calendars) or any(
        a["end"] >= b["start"] for a, b in zip(calendars.values(), list(calendars.values())[1:])
    ):
        raise ValueError("sessions must have unique increasing days and non-overlapping clocks")
    bars = {}
    for row in prices:
        key = (row["trading_day"], row["slot"])
        if type(row["slot"]) is not int or key not in expected or key in bars:
            raise ValueError("price grid has an extra or duplicate slot")
        cal = calendars[key[0]]
        event = cal["start"] + key[1] * delta
        if _time(row["event_time"]) != event or _time(row["available_at"]) != event + delta:
            raise ValueError("price clock differs from the planned bar grid")
        values = {name: _finite_number(row[name], name) for name in ("open", "close")}
        if min(values.values()) <= 0:
            raise ValueError("execution and valuation prices must be positive")
        if type(row["row_version_id"]) is not str or not row["row_version_id"]:
            raise ValueError("price row identity is required")
        bars[key] = {**{name: row[name] for name in ("trading_day", "slot", "event_time", "available_at", "row_version_id")}, **values}
    if set(bars) != expected:
        raise ValueError("incomplete session price flow; execution is invalid")
    signals, keys = {}, set()
    for decision in decisions:
        day, slot, key = decision["trading_day"], decision["slot"], decision["observation_key"]
        if (day not in calendars or type(slot) is not int or not 0 <= slot < calendars[day]["count"]
                or (day, slot) in signals or type(key) is not str or not key or key in keys):
            raise ValueError("decisions require unique observations on the session grid")
        if _time(decision["decision_time"]) != calendars[day]["start"] + (slot + 1) * delta:
            raise ValueError("decision must follow its observed bar close")
        if decision["target"] not in ("LONG", "FLAT"):
            raise ValueError("target must be LONG or FLAT")
        score = decision.get("score")
        if score is not None:
            score = _finite_number(score, "decision score")
        signals[day, slot] = {**decision, "score": score}
        keys.add(key)
    return policy, calendars, bars, signals


def run_intraday_execution(*, sessions: tuple[dict, ...], prices: tuple[dict, ...],
                           decisions: tuple[dict, ...], interval: str,
                           policy: IntradayExecutionPolicy) -> dict:
    """Simulate one continuous normalized cash account over complete sessions.

    All price/clock checks finish before trading, even for an always-flat rule.
    Equal timestamps retain phase order in the emitted ledger. This function
    is pure numerical execution; it does not establish Canonical authority.
    """
    policy, calendars, bars, signals = _inputs(sessions, prices, decisions, interval, policy)
    commission, slippage = policy.commission_bps / 10_000, policy.slippage_bps / 10_000
    cash, quantity, peak, maximum_drawdown = 1.0, 0.0, 1.0, 0.0
    ledger, transactions, trades, daily, windows = [], [], [], [], []
    entry = None

    def mark(bar, phase, action, reason, decision):
        nonlocal peak, maximum_drawdown
        price = bar["open" if phase == "OPEN" else "close"]
        equity = cash + quantity * price
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("account equity must remain finite and positive")
        peak = max(peak, equity)
        drawdown = 1.0 - equity / peak
        maximum_drawdown = max(maximum_drawdown, drawdown)
        ledger.append({"sequence": len(ledger), "trading_day": bar["trading_day"], "slot": bar["slot"],
                       "timestamp": bar["event_time" if phase == "OPEN" else "available_at"],
                       "phase": phase, "action": action, "reason": reason,
                       "observation_key": None if decision is None else decision["observation_key"],
                       "row_version_id": bar["row_version_id"], "mark_price": price,
                       "cash": cash, "quantity": quantity, "equity": equity, "drawdown": drawdown})

    for day, cal in calendars.items():
        day_open_cash, first_trade = cash, len(trades)
        windows.append({"trading_day": day, "earliest_entry_time": cal["first"].isoformat(),
                        "stop_new_time": cal["stop"].isoformat(),
                        "forced_flat_time": bars[day, cal["flatten_slot"]]["event_time"],
                        "forced_flat_slot": cal["flatten_slot"]})
        for slot in range(cal["count"]):
            bar = bars[day, slot]
            # No remembered target: an unsampled bar creates no fresh decision.
            decision = signals.get((day, slot - 1))
            target = None if decision is None else decision["target"]
            action, reason = "HOLD" if quantity else "CASH", "NO_NEW_DECISION"
            exit_reason = None
            if quantity:
                if slot == cal["flatten_slot"]:
                    exit_reason = "EOD"
                elif slot - entry["entry_slot"] >= policy.max_hold_bars:
                    exit_reason = "MAX_HOLD"
                elif target == "FLAT":
                    exit_reason = "TARGET_FLAT"
            if exit_reason:
                fill = bar["open"] * (1.0 - slippage)
                fee = quantity * fill * commission
                slip = quantity * (bar["open"] - fill)
                after = quantity * fill * (1.0 - commission)
                if not math.isfinite(after) or after <= 0:
                    raise ValueError("exit cash must remain finite and positive")
                transactions.append({"trading_day": day, "slot": slot, "timestamp": bar["event_time"],
                                     "side": "SELL", "reason": exit_reason, "raw_open": bar["open"],
                                     "fill_price": fill, "quantity": quantity, "commission": fee,
                                     "slippage": slip, "cash_before": cash, "cash_after": after,
                                     "row_version_id": bar["row_version_id"]})
                trade = {**entry, "exit_time": bar["event_time"], "exit_slot": slot,
                         "exit_raw_open": bar["open"], "exit_fill_price": fill,
                         "exit_row_version_id": bar["row_version_id"], "exit_reason": exit_reason,
                         "exit_observation_key": decision["observation_key"] if exit_reason == "TARGET_FLAT" else None,
                         "held_bars": slot - entry["entry_slot"], "cash_after": after,
                         "gross_return": bar["open"] / entry["entry_raw_open"] - 1,
                         "net_return": after / entry["cash_before"] - 1,
                         "commission_total": entry["entry_commission"] + fee,
                         "slippage_total": entry["entry_slippage"] + slip}
                trade["trade_id"] = _digest(trade)
                trades.append(trade)
                cash, quantity, entry = after, 0.0, None
                action, reason = "SELL", exit_reason
                # The current decision is consumed even if it requested Long.
            elif not quantity and target == "LONG":
                event = _time(bar["event_time"])
                if cal["first"] <= event < cal["stop"] and slot < cal["flatten_slot"]:
                    fill = bar["open"] * (1.0 + slippage)
                    quantity = cash / (fill * (1.0 + commission))
                    fee, slip = quantity * fill * commission, quantity * (fill - bar["open"])
                    if not math.isfinite(quantity) or quantity <= 0:
                        raise ValueError("entry quantity must remain finite and positive")
                    entry = {"trading_day": day, "entry_observation_key": decision["observation_key"],
                             "signal_time": decision["decision_time"], "entry_time": bar["event_time"],
                             "entry_slot": slot, "entry_raw_open": bar["open"], "entry_fill_price": fill,
                             "entry_row_version_id": bar["row_version_id"], "quantity": quantity,
                             "entry_commission": fee, "entry_slippage": slip, "cash_before": cash}
                    transactions.append({"trading_day": day, "slot": slot, "timestamp": bar["event_time"],
                                         "side": "BUY", "reason": "TARGET_LONG", "raw_open": bar["open"],
                                         "fill_price": fill, "quantity": quantity, "commission": fee,
                                         "slippage": slip, "cash_before": cash, "cash_after": 0.0,
                                         "row_version_id": bar["row_version_id"]})
                    cash = 0.0
                    action, reason = "BUY", "TARGET_LONG"
                else:
                    reason = "OUTSIDE_ENTRY_WINDOW"
            elif target is not None:
                reason = "TARGET_" + target
            mark(bar, "OPEN", action, reason, decision)
            mark(bar, "CLOSE", "MARK", "BAR_CLOSE", None)
        if quantity or entry is not None:
            raise ValueError("session ended with an open position")
        daily.append({"trading_day": day, "open_time": cal["start"].isoformat(), "close_time": cal["end"].isoformat(),
                      "cash_open": day_open_cash, "cash_close": cash, "return": cash / day_open_cash - 1,
                      "trade_count": len(trades) - first_trade})
    result = {"version": INTRADAY_EXECUTION_VERSION, "cost_version": INTRADAY_COST_VERSION,
              "event_order": EVENT_ORDER, "interval": interval, "policy": asdict(policy),
              "price_evidence_id": _digest({"prices": list(bars.values()), "sessions": list(sessions)}),
              "windows": windows, "decisions": [signals[key] for key in sorted(signals)],
              "trades": trades, "transactions": transactions, "ledger": ledger, "daily": daily,
              "metrics": {"initial_cash": 1.0, "final_cash": cash, "total_return": cash - 1,
                          "trade_count": len(trades), "observed_max_drawdown": maximum_drawdown,
                          "commission_total": math.fsum(row["commission"] for row in transactions),
                          "slippage_total": math.fsum(row["slippage"] for row in transactions)}}
    result["execution_id"] = _digest(result)
    return result
