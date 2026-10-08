"""Daily close-to-close risk statistics over an explicit session calendar."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import math
import statistics

from ..dataset.encoding import encode_identity
from .equity import EquityCurve, EquityError
from .models import _instant


DAILY_RISK_VERSION = "market-vault-daily-equity-risk-v1"
ANNUALIZATION_FACTOR = 252
RISK_FREE_RATE = 0.0
# A numerical tolerance, not a financial volatility floor.
ZERO_VOLATILITY_TOLERANCE = 1e-15


@dataclass(frozen=True, slots=True)
class SessionClose:
    trading_day: date
    timestamp: datetime

    def __post_init__(self) -> None:
        if type(self.trading_day) is not date:
            raise EquityError("session trading_day must be a date")
        _instant(self.timestamp, "session close")


@dataclass(frozen=True, slots=True)
class DailyEquity:
    trading_day: date
    timestamp: datetime
    equity: float


@dataclass(frozen=True, slots=True)
class DailyReturn:
    start_day: date
    end_day: date
    start_time: datetime
    end_time: datetime
    value: float


@dataclass(frozen=True, slots=True)
class DailyRisk:
    version: str
    risk_id: str
    annualization_factor: int
    risk_free_rate: float
    observation_count: int
    return_count: int
    start_time: datetime | None
    end_time: datetime | None
    mean_daily_return: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    unavailable_reason: str | None
    observations: tuple[DailyEquity, ...]
    returns: tuple[DailyReturn, ...]


def calculate_daily_risk(curve: EquityCurve, *, session_closes: tuple[SessionClose, ...]) -> DailyRisk:
    """Use final account state at each declared complete session close.

    The caller supplies all complete session endpoints within the valuation
    window, including dates on which the strategy stays in cash. Initial-to-
    first-close and last-close-to-partial-end returns are deliberately absent.
    This pure statistic does not establish market-data authority.
    """
    if type(curve) is not EquityCurve or not curve.points:
        raise EquityError("risk statistics require a nonempty EquityCurve")
    if type(session_closes) is not tuple or any(type(s) is not SessionClose for s in session_closes):
        raise EquityError("session_closes must be an immutable SessionClose tuple")
    times = tuple(s.timestamp for s in session_closes)
    days = tuple(s.trading_day for s in session_closes)
    if times != tuple(sorted(set(times))) or days != tuple(sorted(set(days))):
        raise EquityError("session closes must have unique increasing dates and clocks")
    if any(not curve.points[0].timestamp < t <= curve.points[-1].timestamp for t in times):
        raise EquityError("session close lies outside the equity window")
    if any(a.timestamp > b.timestamp for a, b in zip(curve.points, curve.points[1:])):
        raise EquityError("equity points must preserve chronological event order")
    # Later equal-time events include exit and subsequent entry costs.
    final_at_time = {point.timestamp: point for point in curve.points}
    observations = []
    for session in session_closes:
        point = final_at_time.get(session.timestamp)
        if point is None:
            raise EquityError("missing complete session equity observation")
        if not math.isfinite(point.equity) or point.equity <= 0:
            raise EquityError("daily equity must be finite and positive")
        observations.append(DailyEquity(session.trading_day, session.timestamp, point.equity))
    observations = tuple(observations)
    returns = tuple(DailyReturn(
        first.trading_day, last.trading_day, first.timestamp, last.timestamp,
        last.equity / first.equity - 1.0,
    ) for first, last in zip(observations, observations[1:]))
    values = tuple(item.value for item in returns)
    if any(not math.isfinite(value) for value in values):
        raise EquityError("daily returns must be finite")
    mean = statistics.mean(values) if values else None
    volatility = sharpe = None
    reason = "INSUFFICIENT_DAILY_RETURNS"
    if len(values) >= 2:
        deviation = statistics.stdev(values)
        if deviation <= ZERO_VOLATILITY_TOLERANCE:
            volatility, reason = 0.0, "ZERO_VOLATILITY"
        else:
            volatility = deviation * math.sqrt(ANNUALIZATION_FACTOR)
            sharpe = mean / deviation * math.sqrt(ANNUALIZATION_FACTOR)
            reason = None
    if any(value is not None and not math.isfinite(value) for value in (mean, volatility, sharpe)):
        raise EquityError("risk statistics must remain finite")
    risk_id = encode_identity(DAILY_RISK_VERSION, {
        "curve_id": curve.curve_id,
        "annualization_factor": ANNUALIZATION_FACTOR,
        "risk_free_rate": RISK_FREE_RATE,
        "observation_count": len(observations),
        "observations": "".join(encode_identity(DAILY_RISK_VERSION + ":close", asdict(p))
                                for p in observations),
        "annualized_volatility": volatility, "sharpe_ratio": sharpe,
        "unavailable_reason": reason,
    })
    return DailyRisk(
        DAILY_RISK_VERSION, risk_id, ANNUALIZATION_FACTOR, RISK_FREE_RATE,
        len(observations), len(returns),
        observations[0].timestamp if observations else None,
        observations[-1].timestamp if observations else None,
        mean, volatility, sharpe, reason, observations, returns,
    )
