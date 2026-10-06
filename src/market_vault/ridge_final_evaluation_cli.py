"""Final Ridge research evaluation Plan + CLI V1.

This command produces a read-only permanent TEST comparison between:

- fixed-zero Ridge trading: predicted return > 0
- VALIDATION-selected Ridge trading threshold

It uses the same leakage-safe development pipeline and plan inputs as Ridge
trading-threshold selection.  The TEST comparison is reporting-only: the plan
has no winner metric, recommendation rule, TEST threshold, TEST cost override,
or refit control.
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
from .research.ridge_final_evaluation import (
    RIDGE_FINAL_EVALUATION_VERSION,
    RidgeFinalEvaluationError,
    compare_ridge_final_trading,
)
from .research.ridge_final_trading import (
    RIDGE_FINAL_TRADING_SIGNAL_RULE,
    RidgeFinalTradingError,
    evaluate_ridge_final_trading,
)
from .research.ridge_selected_final_trading import (
    RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
    RidgeSelectedFinalTradingError,
    evaluate_ridge_selected_final_trading,
)
from .research.ridge_trading_selection import (
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


RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-plan-v1"
)
RIDGE_FINAL_EVALUATION_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-cli-result-v1"
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


class RidgeFinalEvaluationCLIError(Exception):
    """Documented read-only final Ridge evaluation CLI failure."""


_DOCUMENTED_ERRORS = (
    RidgeFinalEvaluationCLIError,
    RidgeFinalEvaluationError,
    RidgeFinalTradingError,
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


def add_ridge_final_evaluation_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-final-evaluation",
        help=(
            "Compare fixed-zero and VALIDATION-selected Ridge trading "
            "on frozen TEST"
        ),
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-ridge-final-evaluation-plan-v1 JSON",
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


def parse_ridge_final_evaluation_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeFinalEvaluationCLIError(
            "ridge final evaluation plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeFinalEvaluationCLIError(
            f"ridge final evaluation plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeFinalEvaluationCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeFinalEvaluationCLIError(
            f"ridge final evaluation plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "ridge final evaluation plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge final evaluation plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION:
            raise RidgeFinalEvaluationCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION!r} is accepted"
            )
        try:
            selection_plan = parse_ridge_trading_selection_plan_bytes(
                _selection_plan_payload(root)
            )
        except RidgeTradingSelectionCLIError as exc:
            raise RidgeFinalEvaluationCLIError(str(exc)) from exc
        return SimpleNamespace(
            plan_schema_version=version,
            selection_plan=selection_plan,
        )
    except DatasetCLIError as exc:
        raise RidgeFinalEvaluationCLIError(str(exc)) from exc


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
    fixed = evaluate_ridge_final_trading(
        verified,
        experiment,
        final,
        commission_bps=threshold_selection.costs.commission_bps,
        slippage_bps=threshold_selection.costs.slippage_bps,
    )
    selected = evaluate_ridge_selected_final_trading(
        verified,
        experiment,
        final,
        threshold_selection,
    )
    report = compare_ridge_final_trading(
        final,
        fixed,
        threshold_selection,
        selected,
    )
    return ridge_selection, threshold_selection, final, fixed, selected, report


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


def _delta_payload(delta) -> dict:
    return {
        "signal_count": delta.signal_count,
        "overlap_skipped_count": delta.overlap_skipped_count,
        "trade_count": delta.trade_count,
        "gross_total_return": delta.gross_total_return,
        "total_return": delta.total_return,
        "realized_max_drawdown": delta.realized_max_drawdown,
        "win_rate": delta.win_rate,
        "average_trade_return": delta.average_trade_return,
        "profit_factor": delta.profit_factor,
        "average_signal_to_exit_seconds": (
            delta.average_signal_to_exit_seconds
        ),
    }


def _success_payload(
    ridge_selection,
    threshold_selection,
    final,
    fixed,
    selected,
    report,
) -> dict:
    return {
        "result_schema_version": (
            RIDGE_FINAL_EVALUATION_CLI_RESULT_SCHEMA_VERSION
        ),
        "status": "SUCCESS",
        "evaluation_version": RIDGE_FINAL_EVALUATION_VERSION,
        "report_id": report.report_id,
        "ridge_selection_id": ridge_selection.selection_id,
        "walk_forward_id": report.walk_forward_id,
        "threshold_selection_id": report.threshold_selection_id,
        "selected_candidate_id": report.selected_candidate_id,
        "final_test_id": report.final_test_id,
        "model_id": report.model_id,
        "dataset_id": report.dataset_id,
        "label_name": report.label_name,
        "feature_names": list(report.feature_names),
        "selected_alpha": report.selected_alpha,
        "selected_threshold": report.selected_threshold,
        "costs": {
            "commission_bps": report.costs.commission_bps,
            "slippage_bps": report.costs.slippage_bps,
        },
        "test_count": report.test_count,
        "test_metrics": {
            "mae": report.test_mae,
            "rmse": report.test_rmse,
            "r2": report.test_r2,
        },
        "fixed_zero": {
            "signal_rule": RIDGE_FINAL_TRADING_SIGNAL_RULE,
            "trading_id": fixed.trading_id,
            "metrics": _metrics_payload(report.fixed_metrics),
        },
        "validation_selected": {
            "signal_rule": RIDGE_SELECTED_FINAL_TRADING_SIGNAL_RULE,
            "trading_id": selected.trading_id,
            "selected_threshold": threshold_selection.selected_threshold,
            "metrics": _metrics_payload(report.selected_metrics),
        },
        "delta_direction": "VALIDATION_SELECTED_MINUS_FIXED_ZERO",
        "delta": _delta_payload(report.delta),
    }


def research_ridge_final_evaluation_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_final_evaluation_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        results = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(*results),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeFinalEvaluationCLIError)
            else RidgeFinalEvaluationCLIError(
                f"research-ridge-final-evaluation failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_FINAL_EVALUATION_CLI_RESULT_SCHEMA_VERSION
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
