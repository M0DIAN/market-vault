"""Ridge Final TEST Trading Plan + CLI V1.

This command composes the existing leakage-safe Ridge final pipeline with
Ridge Final TEST Trading Evaluation V1.

The TEST trading signal rule is intentionally NOT configurable here:
predicted execution-safe return > 0.0 is fixed by the evaluator.  The plan
only adds explicit per-side commission/slippage costs to the already-validated
Ridge final plan inputs.
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from .backtest.models import BacktestCosts, BacktestError
from .dataset.cli import (
    DatasetCLIError,
    _coerce_plan_path,
    _no_duplicate_pairs,
    _read_plan_bytes,
    _require_exact_fields,
    _require_object,
    _require_string,
)
from .research.ridge_final_trading import (
    RIDGE_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_FINAL_TRADING_VERSION,
    RidgeFinalTradingError,
    evaluate_ridge_final_trading,
)
from .ridge_final_cli import (
    RIDGE_FINAL_PLAN_SCHEMA_VERSION,
    RidgeFinalCLIError,
    _DOCUMENTED_ERRORS as RIDGE_FINAL_DOCUMENTED_ERRORS,
    _pipeline,
    parse_ridge_final_plan_bytes,
)


RIDGE_FINAL_TRADING_PLAN_SCHEMA_VERSION = (
    "market-vault-ridge-final-trading-plan-v1"
)
RIDGE_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-final-trading-cli-result-v1"
)

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "label_field",
    "feature_fields",
    "minimum_train_periods",
    "validation_periods",
    "step_periods",
    "alphas",
    "commission_bps",
    "slippage_bps",
})


class RidgeFinalTradingCLIError(Exception):
    """Documented Ridge Final Trading Plan/CLI V1 failure."""


_DOCUMENTED_ERRORS = (
    RidgeFinalTradingCLIError,
    RidgeFinalTradingError,
    RidgeFinalCLIError,
    BacktestError,
    DatasetCLIError,
    *RIDGE_FINAL_DOCUMENTED_ERRORS,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_ridge_final_trading_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-final-trading",
        help="Evaluate fixed positive-prediction trading on final Ridge TEST",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help=(
            "Path to market-vault-ridge-final-trading-plan-v1 JSON"
        ),
    )


def _base_plan_payload(root: dict) -> bytes:
    payload = {
        key: root[key]
        for key in (
            "dataset_build_dir",
            "label_field",
            "feature_fields",
            "minimum_train_periods",
            "validation_periods",
            "step_periods",
            "alphas",
        )
    }
    payload["plan_schema_version"] = RIDGE_FINAL_PLAN_SCHEMA_VERSION
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_ridge_final_trading_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeFinalTradingCLIError(
            "ridge final trading plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeFinalTradingCLIError(
            f"ridge final trading plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeFinalTradingCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeFinalTradingCLIError(
            f"ridge final trading plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "ridge final trading plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge final trading plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_FINAL_TRADING_PLAN_SCHEMA_VERSION:
            raise RidgeFinalTradingCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_FINAL_TRADING_PLAN_SCHEMA_VERSION!r} is accepted"
            )

        try:
            base = parse_ridge_final_plan_bytes(
                _base_plan_payload(root)
            )
        except RidgeFinalCLIError as exc:
            raise RidgeFinalTradingCLIError(str(exc)) from exc

        try:
            costs = BacktestCosts(
                commission_bps=root["commission_bps"],
                slippage_bps=root["slippage_bps"],
            )
        except (BacktestError, TypeError, ValueError) as exc:
            raise RidgeFinalTradingCLIError(str(exc)) from exc

        return SimpleNamespace(
            plan_schema_version=version,
            ridge_final_plan=base,
            commission_bps=costs.commission_bps,
            slippage_bps=costs.slippage_bps,
        )
    except DatasetCLIError as exc:
        raise RidgeFinalTradingCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    (
        verified,
        experiment,
        _walk_forward,
        selection,
        final,
    ) = _pipeline(plan.ridge_final_plan, plan_parent)
    trading = evaluate_ridge_final_trading(
        verified,
        experiment,
        final,
        commission_bps=plan.commission_bps,
        slippage_bps=plan.slippage_bps,
    )
    return selection, final, trading


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
        "average_signal_to_exit_seconds": (
            metrics.average_signal_to_exit_seconds
        ),
    }


def _success_payload(selection, final, trading) -> dict:
    return {
        "result_schema_version": (
            RIDGE_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
        ),
        "status": "SUCCESS",
        "final_test_version": final.version,
        "trading_evaluation_version": RIDGE_FINAL_TRADING_VERSION,
        "selection_id": selection.selection_id,
        "final_test_id": final.final_test_id,
        "model_id": final.model_id,
        "trading_id": trading.trading_id,
        "dataset_id": final.dataset_id,
        "label_name": final.label_name,
        "feature_names": list(final.feature_names),
        "selected_alpha": final.alpha,
        "test_count": final.test_count,
        "test_metrics": {
            "mae": final.mae,
            "rmse": final.rmse,
            "r2": final.r2,
        },
        "signal_rule": RIDGE_FINAL_TRADING_SIGNAL_RULE,
        "costs": {
            "commission_bps": trading.costs.commission_bps,
            "slippage_bps": trading.costs.slippage_bps,
        },
        "trading_metrics": _metrics_payload(trading.metrics),
        "trade_count": len(trading.trades),
    }


def research_ridge_final_trading_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_final_trading_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        selection, final, trading = _run_plan(
            plan,
            plan_path.parent,
        )
        print(json.dumps(
            _success_payload(selection, final, trading),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeFinalTradingCLIError)
            else RidgeFinalTradingCLIError(
                f"research-ridge-final-trading failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
                    ),
                    "status": "FAILED",
                    "error": str(failure),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
