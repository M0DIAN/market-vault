"""Backtest Plan + CLI V1 for the MarketVault research mainline.

The CLI is a thin settings-independent wrapper over run_backtest(). It never
builds or discovers a Dataset, never selects "latest", never connects to
OpenD/network, and never reads current time defaults.

One strict JSON plan names one exact verified Research Dataset artifact and the
complete Backtest V1 configuration.
"""

from __future__ import annotations

import argparse
import codecs
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from .backtest import (
    BACKTEST_COMPARATORS,
    BACKTEST_SPLITS,
    BacktestError,
    run_backtest,
)
from .cross_day_dataset import (
    MultiSourceCrossDayArtifactError,
    load_verified_multi_source_cross_day_dataset,
)
from .dataset.cli import (
    DatasetCLIError,
    _coerce_plan_path,
    _no_duplicate_pairs,
    _read_plan_bytes,
    _require_exact_fields,
    _require_object,
    _require_string,
    _resolve_plan_path,
)


BACKTEST_PLAN_SCHEMA_VERSION = "market-vault-backtest-plan-v1"
BACKTEST_CLI_RESULT_SCHEMA_VERSION = "market-vault-backtest-cli-result-v1"

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "signal_field",
    "comparator",
    "threshold",
    "return_label",
    "split",
    "commission_bps",
    "slippage_bps",
})


class BacktestCLIError(Exception):
    """Documented user/input failure of Backtest Plan + CLI V1."""


_DOCUMENTED_ERRORS = (
    BacktestCLIError,
    BacktestError,
    DatasetCLIError,
    MultiSourceCrossDayArtifactError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_backtest_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-backtest",
        help="Run Backtest V1 from one explicit verified Research Dataset plan",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-backtest-plan-v1 JSON",
    )


def _number(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise BacktestCLIError(f"{label} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise BacktestCLIError(f"{label} must be finite")
    return 0.0 if number == 0.0 else number


def _non_negative_number(value, label: str) -> float:
    number = _number(value, label)
    if number < 0.0:
        raise BacktestCLIError(f"{label} must be non-negative")
    return number


def parse_backtest_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise BacktestCLIError("backtest plan must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BacktestCLIError(
            f"backtest plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise BacktestCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise BacktestCLIError(
            f"backtest plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "backtest plan root")
        _require_exact_fields(root, _PLAN_FIELDS, "backtest plan root")
        version = _require_string(
            root["plan_schema_version"], "plan_schema_version"
        )
        if version != BACKTEST_PLAN_SCHEMA_VERSION:
            raise BacktestCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{BACKTEST_PLAN_SCHEMA_VERSION!r} is accepted"
            )
        comparator = _require_string(root["comparator"], "comparator")
        if comparator not in BACKTEST_COMPARATORS:
            raise BacktestCLIError(
                "comparator must be one of " + ", ".join(BACKTEST_COMPARATORS)
            )
        split = _require_string(root["split"], "split")
        if split not in BACKTEST_SPLITS:
            raise BacktestCLIError(
                "split must be one of " + ", ".join(BACKTEST_SPLITS)
            )
        return SimpleNamespace(
            plan_schema_version=version,
            dataset_build_dir=_require_string(
                root["dataset_build_dir"], "dataset_build_dir"
            ),
            signal_field=_require_string(root["signal_field"], "signal_field"),
            comparator=comparator,
            threshold=_number(root["threshold"], "threshold"),
            return_label=_require_string(root["return_label"], "return_label"),
            split=split,
            commission_bps=_non_negative_number(
                root["commission_bps"], "commission_bps"
            ),
            slippage_bps=_non_negative_number(
                root["slippage_bps"], "slippage_bps"
            ),
        )
    except DatasetCLIError as exc:
        raise BacktestCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    build_dir = _resolve_plan_path(
        plan.dataset_build_dir,
        base=plan_parent,
        label="Research Dataset build",
    )
    dataset = load_verified_multi_source_cross_day_dataset(build_dir)
    return run_backtest(
        dataset,
        signal_field=plan.signal_field,
        comparator=plan.comparator,
        threshold=plan.threshold,
        return_label=plan.return_label,
        split=plan.split,
        commission_bps=plan.commission_bps,
        slippage_bps=plan.slippage_bps,
    )


def _metrics_payload(metrics) -> dict:
    return {
        "candidate_count": metrics.candidate_count,
        "signal_count": metrics.signal_count,
        "overlap_skipped_count": metrics.overlap_skipped_count,
        "trade_count": metrics.trade_count,
        "gross_total_return": metrics.gross_total_return,
        "total_return": metrics.total_return,
        "realized_max_drawdown": metrics.realized_max_drawdown,
        "win_rate": metrics.win_rate,
        "average_trade_return": metrics.average_trade_return,
        "profit_factor": metrics.profit_factor,
        "average_holding_seconds": metrics.average_holding_seconds,
        "exposure": metrics.exposure,
    }


def _success_payload(result) -> dict:
    return {
        "result_schema_version": BACKTEST_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "engine_version": result.engine_version,
        "backtest_id": result.backtest_id,
        "dataset_id": result.dataset_id,
        "split": result.split,
        "rule": {
            "signal_field": result.rule.signal_field,
            "comparator": result.rule.comparator,
            "threshold": result.rule.threshold,
        },
        "return_label": result.return_label,
        "costs": {
            "commission_bps": result.costs.commission_bps,
            "slippage_bps": result.costs.slippage_bps,
        },
        "metrics": _metrics_payload(result.metrics),
    }


def research_backtest_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_backtest_plan_bytes(_read_plan_bytes(plan_path))
        result = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(result),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = exc if isinstance(exc, BacktestCLIError) else BacktestCLIError(
            f"research-backtest failed: {exc}"
        )
        payload = {
            "result_schema_version": BACKTEST_CLI_RESULT_SCHEMA_VERSION,
            "status": "FAILED",
            "error": str(failure),
        }
        print(
            json.dumps(payload, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        return 1
