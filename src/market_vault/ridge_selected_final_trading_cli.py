"""Validation-selected Ridge Final TEST Trading Plan + CLI V1.

This command composes the leakage-safe development and permanent TEST stages:

verified Research Dataset
-> Experiment Metadata
-> Walk-Forward TRAIN/VALIDATION
-> Ridge alpha selection on VALIDATION RMSE
-> trading threshold selection on VALIDATION economics
-> freeze threshold
-> final Ridge fit / permanent TEST predictions
-> apply frozen threshold once on permanent TEST

The plan exposes no TEST threshold field and no TEST tuning switch.
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from .dataset.cli import (
    DatasetCLIError,
    _coerce_plan_path,
    _no_duplicate_pairs,
    _read_plan_bytes,
    _require_exact_fields,
    _require_object,
    _require_string,
)
from .research.ridge_final_test import (
    RIDGE_FINAL_TEST_VERSION,
    RidgeFinalTestError,
    evaluate_ridge_final_test,
)
from .research.ridge_selected_final_trading import (
    RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_SELECTED_FINAL_TRADING_VERSION,
    RidgeSelectedFinalTradingError,
    evaluate_ridge_selected_final_trading,
)
from .research.ridge_trading_selection import (
    RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
)
from .ridge_trading_selection_cli import (
    RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION,
    RidgeTradingSelectionCLIError,
    _DOCUMENTED_ERRORS as RIDGE_TRADING_SELECTION_DOCUMENTED_ERRORS,
    _pipeline as _threshold_pipeline,
    parse_ridge_trading_selection_plan_bytes,
)


RIDGE_SELECTED_FINAL_TRADING_PLAN_SCHEMA_VERSION = (
    "market-vault-ridge-selected-final-trading-plan-v1"
)
RIDGE_SELECTED_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-selected-final-trading-cli-result-v1"
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
    "thresholds",
    "commission_bps",
    "slippage_bps",
})


class RidgeSelectedFinalTradingCLIError(Exception):
    """Documented selected-threshold final trading Plan/CLI failure."""


_DOCUMENTED_ERRORS = (
    RidgeSelectedFinalTradingCLIError,
    RidgeTradingSelectionCLIError,
    RidgeFinalTestError,
    RidgeSelectedFinalTradingError,
    *RIDGE_TRADING_SELECTION_DOCUMENTED_ERRORS,
    DatasetCLIError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_ridge_selected_final_trading_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-selected-final-trading",
        help=(
            "Apply VALIDATION-selected Ridge threshold once on permanent TEST"
        ),
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help=(
            "Path to market-vault-ridge-selected-final-trading-plan-v1 JSON"
        ),
    )


def _threshold_plan_payload(root: dict) -> bytes:
    payload = dict(root)
    payload["plan_schema_version"] = (
        RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_ridge_selected_final_trading_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeSelectedFinalTradingCLIError(
            "ridge selected final trading plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeSelectedFinalTradingCLIError(
            f"ridge selected final trading plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeSelectedFinalTradingCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeSelectedFinalTradingCLIError(
            f"ridge selected final trading plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(
            root,
            "ridge selected final trading plan root",
        )
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge selected final trading plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_SELECTED_FINAL_TRADING_PLAN_SCHEMA_VERSION:
            raise RidgeSelectedFinalTradingCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_SELECTED_FINAL_TRADING_PLAN_SCHEMA_VERSION!r} "
                "is accepted"
            )
        try:
            selection_plan = parse_ridge_trading_selection_plan_bytes(
                _threshold_plan_payload(root)
            )
        except RidgeTradingSelectionCLIError as exc:
            raise RidgeSelectedFinalTradingCLIError(str(exc)) from exc

        return SimpleNamespace(
            plan_schema_version=version,
            threshold_plan=selection_plan,
        )
    except DatasetCLIError as exc:
        raise RidgeSelectedFinalTradingCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    (
        verified,
        experiment,
        walk_forward,
        ridge_selection,
        threshold_selection,
    ) = _threshold_pipeline(
        plan.threshold_plan,
        plan_parent,
    )

    final_test = evaluate_ridge_final_test(
        experiment,
        walk_forward,
        ridge_selection,
    )
    final_trading = evaluate_ridge_selected_final_trading(
        verified,
        experiment,
        final_test,
        threshold_selection,
    )
    return (
        ridge_selection,
        threshold_selection,
        final_test,
        final_trading,
    )


def _candidate_metrics(candidate) -> dict:
    return {
        "validation_sample_count": candidate.validation_sample_count,
        "signal_count": candidate.signal_count,
        "overlap_skipped_count": candidate.overlap_skipped_count,
        "trade_count": candidate.trade_count,
        "gross_total_return": candidate.gross_total_return,
        "total_return": candidate.total_return,
        "realized_max_drawdown": candidate.realized_max_drawdown,
        "win_rate": candidate.win_rate,
        "average_trade_return": candidate.average_trade_return,
        "profit_factor": candidate.profit_factor,
        "average_signal_to_exit_seconds": (
            candidate.average_signal_to_exit_seconds
        ),
    }


def _trading_metrics(metrics) -> dict:
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


def _success_payload(
    ridge_selection,
    threshold_selection,
    final_test,
    final_trading,
) -> dict:
    selected_candidate = next(
        candidate
        for candidate in threshold_selection.candidates
        if candidate.candidate_id
        == threshold_selection.selected_candidate_id
    )
    return {
        "result_schema_version": (
            RIDGE_SELECTED_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
        ),
        "status": "SUCCESS",
        "threshold_selection_version": (
            RIDGE_TRADING_THRESHOLD_SELECTION_VERSION
        ),
        "final_test_version": RIDGE_FINAL_TEST_VERSION,
        "selected_final_trading_version": (
            RIDGE_SELECTED_FINAL_TRADING_VERSION
        ),
        "threshold_selection_id": (
            threshold_selection.threshold_selection_id
        ),
        "ridge_selection_id": ridge_selection.selection_id,
        "walk_forward_id": threshold_selection.walk_forward_id,
        "final_test_id": final_test.final_test_id,
        "model_id": final_test.model_id,
        "trading_id": final_trading.trading_id,
        "dataset_id": final_test.dataset_id,
        "label_name": final_test.label_name,
        "feature_names": list(final_test.feature_names),
        "selected_alpha": final_test.alpha,
        "selected_threshold": threshold_selection.selected_threshold,
        "selected_candidate_id": (
            threshold_selection.selected_candidate_id
        ),
        "signal_rule": RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
        "costs": {
            "commission_bps": threshold_selection.costs.commission_bps,
            "slippage_bps": threshold_selection.costs.slippage_bps,
        },
        "validation_selected_candidate_metrics": _candidate_metrics(
            selected_candidate
        ),
        "test_count": final_test.test_count,
        "test_regression_metrics": {
            "mae": final_test.mae,
            "rmse": final_test.rmse,
            "r2": final_test.r2,
        },
        "test_trading_metrics": _trading_metrics(
            final_trading.metrics
        ),
        "accepted_test_trade_count": len(final_trading.trades),
    }


def research_ridge_selected_final_trading_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_selected_final_trading_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        (
            ridge_selection,
            threshold_selection,
            final_test,
            final_trading,
        ) = _run_plan(
            plan,
            plan_path.parent,
        )
        print(json.dumps(
            _success_payload(
                ridge_selection,
                threshold_selection,
                final_test,
                final_trading,
            ),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeSelectedFinalTradingCLIError)
            else RidgeSelectedFinalTradingCLIError(
                "research-ridge-selected-final-trading failed: "
                f"{exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_SELECTED_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
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
