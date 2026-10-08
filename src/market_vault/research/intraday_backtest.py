"""Verified single-strategy intraday research adapter for the V2 kernel."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ..backtest.engine import _compare
from ..backtest.intraday import IntradayExecutionPolicy, run_intraday_execution
from ..dataset.cli import _resolve_plan_path
from .intraday_data import digest, load_intraday_dataset, object_fields
from .strategy_comparison import CompositeRuleStrategy, FeatureRuleStrategy, RidgeStrategy
from .strategy_config import parse_strategy_specs, strategy_plan_fields


INTRADAY_BACKTEST_PLAN_VERSION = "market-vault-intraday-backtest-plan-v2"
INTRADAY_BACKTEST_RESULT_VERSION = "market-vault-intraday-backtest-result-v2"
EXECUTION_FIELDS = {"commission_bps", "slippage_bps", "entry_delay_minutes", "stop_new_minutes", "flatten_minutes", "max_hold_bars"}


def parse_execution_policy(value: dict) -> IntradayExecutionPolicy:
    object_fields(value, EXECUTION_FIELDS, "intraday execution policy")
    return IntradayExecutionPolicy(**value)


def intraday_data_path(value: str, *, base: Path | None = None) -> Path:
    if type(value) is not str or not value.strip():
        raise ValueError("intraday data path must be a nonempty string")
    base = Path.cwd() if base is None else _resolve_plan_path(str(base), base=Path.cwd(), label="plan base")
    return _resolve_plan_path(value, base=base, label="intraday data file")


def normalize_intraday_backtest_plan(plan: dict, *, base: Path | None = None) -> dict:
    object_fields(plan, {"plan_schema_version", "intraday_data_path", "strategy", "execution"}, "intraday backtest plan")
    if plan["plan_schema_version"] != INTRADAY_BACKTEST_PLAN_VERSION:
        raise ValueError("unsupported intraday backtest plan version")
    strategy = parse_strategy_specs([plan["strategy"]])[0]
    if type(strategy) is RidgeStrategy:
        raise ValueError("Ridge requires the day-split training context in intraday research")
    policy = parse_execution_policy(plan["execution"])
    path = intraday_data_path(plan["intraday_data_path"], base=base)
    return {"plan_schema_version": INTRADAY_BACKTEST_PLAN_VERSION, "intraday_data_path": str(path),
            "strategy": strategy_plan_fields(strategy), "execution": asdict(policy)}


def rule_decisions(observations: list[dict], strategy, *, feature_names: tuple[str, ...]) -> tuple[dict, ...]:
    """Use only READY Features; neither target presence nor target horizon enters."""
    if type(strategy) is FeatureRuleStrategy:
        rules = (strategy.rule,)
    elif type(strategy) is CompositeRuleStrategy:
        rules = strategy.conditions
    else:
        raise ValueError("a Feature or Composite rule is required")
    if any(rule.signal_field not in feature_names for rule in rules):
        raise ValueError("rule Feature must belong to the explicit common projection")
    result = []
    for row in observations:
        if row["status"] != "READY":
            continue
        conditions = tuple(_compare(row["features"][rule.signal_field], rule) for rule in rules)
        active = conditions[0] if type(strategy) is FeatureRuleStrategy else (
            all(conditions) if strategy.match == "ALL" else any(conditions))
        result.append({**{name: row[name] for name in ("observation_key", "trading_day", "slot", "decision_time")},
                       "target": "LONG" if active else "FLAT",
                       "score": row["features"][rules[0].signal_field] if type(strategy) is FeatureRuleStrategy else float(active)})
    return tuple(result)


def execution_views(report: dict, *, trading_days: tuple[str, ...] | None = None) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """Project one common evaluated date set; never drop dates per candidate."""
    known = tuple(row["trading_day"] for row in report["sessions"])
    selected = known if trading_days is None else trading_days
    if (type(selected) is not tuple or not selected or selected != tuple(sorted(set(selected)))
            or not set(selected).issubset(known)):
        raise ValueError("execution requires explicit unique increasing known trading days")
    return (tuple(row for row in report["sessions"] if row["trading_day"] in selected),
            tuple(row for row in report["prices"] if row["trading_day"] in selected))


def run_intraday_backtest(plan: dict, *, base: Path | None = None, expected_data_id: str | None = None) -> dict:
    """Preflight, re-read source authority once, then run one independent rule."""
    normalized = normalize_intraday_backtest_plan(plan, base=base)
    data = load_intraday_dataset(normalized["intraday_data_path"])
    if expected_data_id is not None and data.data_id != expected_data_id:
        raise ValueError("intraday data identity differs from the selected snapshot")
    report = data.as_dict()["report"]
    strategy = parse_strategy_specs([normalized["strategy"]])[0]
    decisions = rule_decisions(report["observations"], strategy, feature_names=tuple(report["feature_names"]))
    sessions, prices = execution_views(report)
    execution = run_intraday_execution(sessions=sessions, prices=prices, decisions=decisions,
                                       interval=report["interval"], policy=parse_execution_policy(normalized["execution"]))
    result = {"result_schema_version": INTRADAY_BACKTEST_RESULT_VERSION, "status": "SUCCESS",
              "data_id": data.data_id, "symbol": report["symbol"], "plan": normalized,
              "execution": execution}
    result["backtest_id"] = digest(result)
    return result
