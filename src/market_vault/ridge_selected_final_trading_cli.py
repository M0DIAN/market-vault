"""Validation-selected Ridge Final TEST Trading Plan + CLI V1.

This command composes the existing leakage-safe development pipeline:

verified Research Dataset
-> Experiment Metadata
-> Walk-Forward VALIDATION
-> Ridge alpha selection
-> Ridge trading threshold selection on VALIDATION
-> frozen Ridge Final TEST predictions
-> apply the already-selected threshold on permanent TEST

The plan exposes no TEST-stage threshold, cost override, model override, or
refit control.  Threshold candidates and costs belong only to the validation
selection stage and the selected values are then frozen into TEST trading.
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
from .research.ridge_selected_final_trading import (
    RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
    RIDGE_SELECTED_FINAL_TRADING_VERSION,
    RidgeSelectedFinalTradingError,
    evaluate_ridge_selected_final_trading,
)
from .research.ridge_trading_selection import (
    RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
    RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
    RidgeTradingThresholdSelectionError,
    select_ridge_trading_threshold,
)
from .ridge_final_cli import (
    RidgeFinalCLIError,
    _DOCUMENTED_ERRORS as RIDGE_FINAL_DOCUMENTED_ERRORS,
    _pipeline as ridge_final_pipeline,
)
from .ridge_trading_selection_cli import (
    RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION,
    RidgeTradingSelectionCLIError,
    _DOCUMENTED_ERRORS as RIDGE_TRADING_SELECTION_DOCUMENTED_ERRORS,
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
    """Documented selected-threshold Final TEST Trading CLI failure."""


_DOCUMENTED_ERRORS = (
    RidgeSelectedFinalTradingCLIError,
    RidgeSelectedFinalTradingError,
    RidgeTradingThresholdSelectionError,
    RidgeTradingSelectionCLIError,
    RidgeFinalCLIError,
    *RIDGE_TRADING_SELECTION_DOCUMENTED_ERRORS,
    *RIDGE_FINAL_DOCUMENTED_ERRORS,
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
            "Apply the VALIDATION-selected Ridge trading threshold "
            "to permanent TEST"
        ),
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help=(
            "Path to "
            "market-vault-ridge-selected-final-trading-plan-v1 JSON"
        ),
    )


def _selection_plan_payload(root: dict) -> bytes:
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
            "ridge selected final trading plan is not valid UTF-8: "
            f"{exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeSelectedFinalTradingCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeSelectedFinalTradingCLIError(
            "ridge selected final trading plan is not valid JSON: "
            f"{exc}"
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
                _selection_plan_payload(root)
            )
        except RidgeTradingSelectionCLIError as exc:
            raise RidgeSelectedFinalTradingCLIError(str(exc)) from exc
        return SimpleNamespace(
            plan_schema_version=version,
            selection_plan=selection_plan,
        )
    except DatasetCLIError as exc:
        raise RidgeSelectedFinalTradingCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    selection_plan = plan.selection_plan
    (
        verified,
        experiment,
        walk_forward,
        ridge_selection,
        final,
    ) = ridge_final_pipeline(
        selection_plan.ridge_plan,
        plan_parent,
    )

    threshold_selection = select_ridge_trading_threshold(
        verified,
        experiment,
        walk_forward,
        ridge_selection,
        thresholds=selection_plan.thresholds,
        commission_bps=selection_plan.commission_bps,
        slippage_bps=selection_plan.slippage_bps,
    )

    trading = evaluate_ridge_selected_final_trading(
        verified,
        experiment,
        final,
        threshold_selection,
    )
    return ridge_selection, threshold_selection, final, trading


def _candidate_payload(candidate) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "threshold": candidate.threshold,
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


def _trading_metrics_payload(metrics) -> dict:
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
    final,
    trading,
) -> dict:
    return {
        "result_schema_version": (
            RIDGE_SELECTED_FINAL_TRADING_CLI_RESULT_SCHEMA_VERSION
        ),
        "status": "SUCCESS",
        "threshold_selection_version": (
            RIDGE_TRADING_THRESHOLD_SELECTION_VERSION
        ),
        "selected_final_trading_version": (
            RIDGE_SELECTED_FINAL_TRADING_VERSION
        ),
        "ridge_selection_id": ridge_selection.selection_id,
        "walk_forward_id": threshold_selection.walk_forward_id,
        "threshold_selection_id": (
            threshold_selection.threshold_selection_id
        ),
        "selected_candidate_id": (
            threshold_selection.selected_candidate_id
        ),
        "final_test_id": final.final_test_id,
        "model_id": final.model_id,
        "trading_id": trading.trading_id,
        "dataset_id": final.dataset_id,
        "label_name": final.label_name,
        "feature_names": list(final.feature_names),
        "selected_alpha": final.alpha,
        "threshold_selection_metric": (
            RIDGE_TRADING_THRESHOLD_SELECTION_METRIC
        ),
        "selected_threshold": (
            threshold_selection.selected_threshold
        ),
        "signal_rule": RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
        "costs": {
            "commission_bps": trading.costs.commission_bps,
            "slippage_bps": trading.costs.slippage_bps,
        },
        "validation_prediction_count": len(
            threshold_selection.validation_predictions
        ),
        "validation_candidates": [
            _candidate_payload(candidate)
            for candidate in threshold_selection.candidates
        ],
        "test_count": final.test_count,
        "test_metrics": {
            "mae": final.mae,
            "rmse": final.rmse,
            "r2": final.r2,
        },
        "trading_metrics": _trading_metrics_payload(
            trading.metrics
        ),
        "trade_count": len(trading.trades),
    }


def research_ridge_selected_final_trading_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_selected_final_trading_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        ridge_selection, threshold_selection, final, trading = (
            _run_plan(plan, plan_path.parent)
        )
        print(json.dumps(
            _success_payload(
                ridge_selection,
                threshold_selection,
                final,
                trading,
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
