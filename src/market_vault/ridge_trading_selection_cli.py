"""Ridge validation trading threshold selection Plan + CLI V1.

This command is deliberately development-only:

verified Research Dataset
-> Experiment Metadata
-> Walk-Forward VALIDATION
-> Ridge alpha selection
-> Ridge trading threshold selection

It never invokes Ridge Final TEST evaluation and exposes no TEST-driven
threshold parameter.  The permanent TEST remains sealed.
"""

from __future__ import annotations

import argparse
import codecs
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from .backtest.models import BacktestCosts, BacktestError
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
from .research.experiment import (
    ExperimentMetadataError,
    build_experiment_dataset,
)
from .research.ridge_selection import (
    RIDGE_ALPHA_SELECTION_VERSION,
    RidgeAlphaSelectionError,
    select_ridge_alpha,
)
from .research.ridge_trading_selection import (
    RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
    RIDGE_TRADING_THRESHOLD_SELECTION_VERSION,
    RidgeTradingThresholdSelectionError,
    select_ridge_trading_threshold,
)
from .research.walk_forward import (
    WalkForwardError,
    build_walk_forward_plan,
)
from .ridge_final_cli import (
    RIDGE_FINAL_PLAN_SCHEMA_VERSION,
    RidgeFinalCLIError,
    parse_ridge_final_plan_bytes,
)


RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION = (
    "market-vault-ridge-trading-selection-plan-v1"
)
RIDGE_TRADING_SELECTION_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-trading-selection-cli-result-v1"
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


class RidgeTradingSelectionCLIError(Exception):
    """Documented Ridge validation trading-selection CLI failure."""


_DOCUMENTED_ERRORS = (
    RidgeTradingSelectionCLIError,
    RidgeTradingThresholdSelectionError,
    RidgeAlphaSelectionError,
    RidgeFinalCLIError,
    WalkForwardError,
    ExperimentMetadataError,
    BacktestError,
    DatasetCLIError,
    MultiSourceCrossDayArtifactError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_ridge_trading_selection_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-trading-select",
        help="Select Ridge trading threshold on Walk-Forward VALIDATION only",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help=(
            "Path to market-vault-ridge-trading-selection-plan-v1 JSON"
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


def _threshold(value) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeTradingSelectionCLIError(
            "threshold candidates must be JSON numbers"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RidgeTradingSelectionCLIError(
            "threshold candidates must be finite"
        )
    return 0.0 if number == 0.0 else number


def _thresholds(value) -> tuple[float, ...]:
    if type(value) is not list:
        raise RidgeTradingSelectionCLIError(
            "thresholds must be a JSON array"
        )
    normalized = tuple(_threshold(item) for item in value)
    if len(normalized) < 2:
        raise RidgeTradingSelectionCLIError(
            "thresholds must contain at least two candidates"
        )
    if len(set(normalized)) != len(normalized):
        raise RidgeTradingSelectionCLIError(
            "threshold candidates must be unique"
        )
    return tuple(sorted(normalized))


def parse_ridge_trading_selection_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeTradingSelectionCLIError(
            "ridge trading selection plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeTradingSelectionCLIError(
            f"ridge trading selection plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeTradingSelectionCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeTradingSelectionCLIError(
            f"ridge trading selection plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "ridge trading selection plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge trading selection plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION:
            raise RidgeTradingSelectionCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_TRADING_SELECTION_PLAN_SCHEMA_VERSION!r} is accepted"
            )

        try:
            base = parse_ridge_final_plan_bytes(
                _base_plan_payload(root)
            )
        except RidgeFinalCLIError as exc:
            raise RidgeTradingSelectionCLIError(str(exc)) from exc

        thresholds = _thresholds(root["thresholds"])
        try:
            costs = BacktestCosts(
                commission_bps=root["commission_bps"],
                slippage_bps=root["slippage_bps"],
            )
        except (BacktestError, TypeError, ValueError) as exc:
            raise RidgeTradingSelectionCLIError(str(exc)) from exc

        return SimpleNamespace(
            plan_schema_version=version,
            ridge_plan=base,
            thresholds=thresholds,
            commission_bps=costs.commission_bps,
            slippage_bps=costs.slippage_bps,
        )
    except DatasetCLIError as exc:
        raise RidgeTradingSelectionCLIError(str(exc)) from exc


def _pipeline(plan, plan_parent: Path):
    base = plan.ridge_plan
    build_dir = _resolve_plan_path(
        base.dataset_build_dir,
        base=plan_parent,
        label="Research Dataset build",
    )
    verified = load_verified_multi_source_cross_day_dataset(build_dir)
    experiment = build_experiment_dataset(
        verified,
        label_field=base.label_field,
        feature_fields=base.feature_fields,
    )
    walk_forward = build_walk_forward_plan(
        experiment,
        minimum_train_periods=base.minimum_train_periods,
        validation_periods=base.validation_periods,
        step_periods=base.step_periods,
    )
    ridge_selection = select_ridge_alpha(
        walk_forward,
        alphas=base.alphas,
    )
    threshold_selection = select_ridge_trading_threshold(
        verified,
        experiment,
        walk_forward,
        ridge_selection,
        thresholds=plan.thresholds,
        commission_bps=plan.commission_bps,
        slippage_bps=plan.slippage_bps,
    )
    return (
        verified,
        experiment,
        walk_forward,
        ridge_selection,
        threshold_selection,
    )


def _run_plan(plan, plan_parent: Path):
    (
        _verified,
        _experiment,
        _walk_forward,
        ridge_selection,
        threshold_selection,
    ) = _pipeline(plan, plan_parent)
    return ridge_selection, threshold_selection


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


def _success_payload(ridge_selection, threshold_selection) -> dict:
    return {
        "result_schema_version": (
            RIDGE_TRADING_SELECTION_CLI_RESULT_SCHEMA_VERSION
        ),
        "status": "SUCCESS",
        "ridge_alpha_selection_version": RIDGE_ALPHA_SELECTION_VERSION,
        "trading_threshold_selection_version": (
            RIDGE_TRADING_THRESHOLD_SELECTION_VERSION
        ),
        "threshold_selection_id": (
            threshold_selection.threshold_selection_id
        ),
        "ridge_selection_id": ridge_selection.selection_id,
        "walk_forward_id": threshold_selection.walk_forward_id,
        "dataset_id": threshold_selection.dataset_id,
        "label_name": threshold_selection.label_name,
        "feature_names": list(threshold_selection.feature_names),
        "selected_alpha": threshold_selection.selected_alpha,
        "metric": RIDGE_TRADING_THRESHOLD_SELECTION_METRIC,
        "costs": {
            "commission_bps": threshold_selection.costs.commission_bps,
            "slippage_bps": threshold_selection.costs.slippage_bps,
        },
        "validation_prediction_count": len(
            threshold_selection.validation_predictions
        ),
        "selected_threshold": threshold_selection.selected_threshold,
        "selected_candidate_id": threshold_selection.selected_candidate_id,
        "candidates": [
            _candidate_payload(candidate)
            for candidate in threshold_selection.candidates
        ],
    }


def research_ridge_trading_select_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_trading_selection_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        ridge_selection, threshold_selection = _run_plan(
            plan,
            plan_path.parent,
        )
        print(json.dumps(
            _success_payload(ridge_selection, threshold_selection),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeTradingSelectionCLIError)
            else RidgeTradingSelectionCLIError(
                f"research-ridge-trading-select failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_TRADING_SELECTION_CLI_RESULT_SCHEMA_VERSION
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
