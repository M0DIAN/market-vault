"""Cash/share valuation of accepted Backtest V1 trades at bar-close clocks.

This layer never selects trades. Fractional shares and proportional cash costs
preserve V1's full-notional Long/Flat convention; no intrabar path is invented.
The Research adapter supplies the verified prices and complete session grid.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math

from ..dataset.encoding import encode_identity
from .engine import _trade_id
from .models import BacktestCosts, BacktestError, BacktestTrade, _finite_number, _instant


EQUITY_VERSION = "market-vault-bar-close-equity-v1"


class EquityError(BacktestError):
    """Price coverage, execution reconciliation or valuation input failure."""


@dataclass(frozen=True, slots=True)
class EquityBar:
    row_version_id: str
    event_time: datetime
    close_time: datetime
    open: float
    close: float

    def __post_init__(self) -> None:
        if (type(self.row_version_id) is not str or len(self.row_version_id) != 64
                or any(c not in "0123456789abcdef" for c in self.row_version_id)):
            raise EquityError("bar row_version_id must be a SHA-256 identity")
        if _instant(self.close_time, "close_time") <= _instant(self.event_time, "event_time"):
            raise EquityError("bar close_time must follow event_time")
        for name in ("open", "close"):
            value = _finite_number(getattr(self, name), name)
            if value <= 0:
                raise EquityError("valuation prices must be strictly positive")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class PricedTrade:
    trade: BacktestTrade
    entry_row_version_id: str
    exit_row_version_id: str


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    event: str
    cash: float
    quantity: float
    mark_price: float | None
    market_value: float
    equity: float
    drawdown: float
    transaction_cost: float
    sample_key: str | None
    row_version_id: str | None


@dataclass(frozen=True, slots=True)
class EquityCurve:
    version: str
    curve_id: str
    points: tuple[EquityPoint, ...]
    final_equity: float
    bar_close_max_drawdown: float
    transaction_cost_total: float


def build_equity_curve(
    *,
    trades: tuple[PricedTrade, ...],
    bars: tuple[EquityBar, ...],
    valuation_times: tuple[datetime, ...],
    start_time: datetime,
    end_time: datetime,
    costs: BacktestCosts,
) -> EquityCurve:
    """Value one normalized account over an explicit, shared session grid.

    Equal-time order is close mark -> exit/cost -> next entry/cost. A missing
    close fails while invested; cash-only points need no price or forward fill.
    Prices must already belong to one instrument. This pure accounting helper
    does not establish Dataset authority; use the Research combination API for
    verified strategy evaluation.
    """
    start_time = _instant(start_time, "start_time")
    end_time = _instant(end_time, "end_time")
    if start_time >= end_time or type(costs) is not BacktestCosts:
        raise EquityError("a positive valuation window and BacktestCosts are required")
    if (type(valuation_times) is not tuple or not valuation_times
            or valuation_times != tuple(sorted(set(valuation_times)))
            or any(not start_time < _instant(t, "valuation time") <= end_time for t in valuation_times)
            or valuation_times[-1] != end_time):
        raise EquityError("valuation_times must be a unique ordered grid ending at end_time")
    if type(bars) is not tuple or any(type(bar) is not EquityBar for bar in bars):
        raise EquityError("bars must be an immutable EquityBar tuple")
    by_version = {bar.row_version_id: bar for bar in bars}
    by_close = {bar.close_time: bar for bar in bars}
    grid = set(valuation_times)
    if len(by_version) != len(bars) or len(by_close) != len(bars):
        raise EquityError("duplicate valuation bar identity or close time")
    if any(bar.close_time not in grid for bar in bars):
        raise EquityError("valuation price lies outside the session grid")
    if type(trades) is not tuple or any(type(item) is not PricedTrade for item in trades):
        raise EquityError("trades must be an immutable PricedTrade tuple")

    entries = {}
    previous_exit = start_time
    expected_equity = 1.0
    for item in trades:
        trade = item.trade
        if type(trade) is not BacktestTrade:
            raise EquityError("priced trade requires an accepted BacktestTrade")
        entry = by_version.get(item.entry_row_version_id)
        exit_ = by_version.get(item.exit_row_version_id)
        if entry is None or exit_ is None:
            raise EquityError("execution price version is missing")
        if (entry.event_time != trade.entry_time or exit_.close_time != trade.exit_time
                or trade.entry_time < previous_exit or trade.exit_time > end_time):
            raise EquityError("execution prices or non-overlapping trade times differ")
        gross = exit_.close / entry.open - 1.0
        net = (1.0 + gross) * (1.0 - costs.per_side_rate) ** 2 - 1.0
        if not (math.isclose(gross, trade.gross_return, rel_tol=1e-12, abs_tol=1e-12)
                and math.isclose(net, trade.net_return, rel_tol=1e-12, abs_tol=1e-12)
                and math.isclose(expected_equity, trade.equity_before, rel_tol=1e-12, abs_tol=1e-12)
                and math.isclose(expected_equity * (1.0 + net), trade.equity_after,
                                 rel_tol=1e-12, abs_tol=1e-12)):
            raise EquityError("execution price/cost ledger differs from Backtest V1")
        entries[trade.entry_time] = item
        previous_exit = trade.exit_time
        expected_equity = trade.equity_after

    cash, quantity, peak, cost_total = 1.0, 0.0, 1.0, 0.0
    position = None
    points = []

    def record(timestamp, event, price=None, row_version_id=None, sample_key=None, cost=0.0):
        nonlocal peak, cost_total
        market_value = quantity * price if quantity else 0.0
        equity = cash + market_value
        if not math.isfinite(equity) or equity <= 0.0:
            raise EquityError("account equity must remain finite and positive")
        peak = max(peak, equity)
        cost_total += cost
        points.append(EquityPoint(
            timestamp, event, cash, quantity, price, market_value, equity,
            max(0.0, 1.0 - equity / peak), cost, sample_key, row_version_id,
        ))

    record(start_time, "INITIAL")
    for timestamp in sorted(grid | set(entries)):
        if timestamp in grid:
            bar = by_close.get(timestamp)
            if position is not None and bar is None:
                raise EquityError(f"missing held-position valuation bar at {timestamp.isoformat()}")
            record(
                timestamp, "BAR_CLOSE", bar.close if bar else None,
                bar.row_version_id if bar else None,
                position.trade.sample_key if position else None,
            )
        if position is not None and position.trade.exit_time == timestamp:
            bar = by_version[position.exit_row_version_id]
            proceeds = quantity * bar.close
            fee = proceeds * costs.per_side_rate
            cash, quantity = proceeds - fee, 0.0
            if not math.isclose(cash, position.trade.equity_after, rel_tol=1e-11, abs_tol=1e-12):
                raise EquityError("exit cash differs from accepted trade equity")
            record(timestamp, "EXIT", bar.close, bar.row_version_id, position.trade.sample_key, fee)
            position = None
        if timestamp in entries:
            if position is not None:
                raise EquityError("cannot enter while another position is open")
            position = entries[timestamp]
            bar = by_version[position.entry_row_version_id]
            fee = cash * costs.per_side_rate
            quantity, cash = (cash - fee) / bar.open, 0.0
            record(timestamp, "ENTRY", bar.open, bar.row_version_id, position.trade.sample_key, fee)
    if position is not None:
        raise EquityError("valuation window ends before the final position exits")
    curve_id = encode_identity(EQUITY_VERSION, {
        "start_time": start_time, "end_time": end_time,
        "commission_bps": costs.commission_bps, "slippage_bps": costs.slippage_bps,
        "trades": "".join(_trade_id(item.trade) for item in trades),
        "point_count": len(points),
        "points": "".join(encode_identity(EQUITY_VERSION + ":point", asdict(p)) for p in points),
    })
    return EquityCurve(
        EQUITY_VERSION, curve_id, tuple(points), points[-1].equity,
        max(point.drawdown for point in points), cost_total,
    )
