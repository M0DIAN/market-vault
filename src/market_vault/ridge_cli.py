"""Ridge Regression Plan + CLI V1 for the MarketVault research mainline.

The command is a thin settings-independent composition layer over:

verified Research Dataset
-> Experiment Metadata V1
-> Walk-Forward Experiment V1
-> Ridge Regression Baseline V1

It performs no Dataset discovery, random split, shuffle, hyperparameter search,
TEST evaluation, model persistence, OpenD/network access, or current-time
lookup.  Every input is declared by one strict JSON plan.
"""

from __future__ import annotations

import argparse
import codecs
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

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
    _require_string_array,
    _resolve_plan_path,
)
from .research.experiment import (
    ExperimentMetadataError,
    build_experiment_dataset,
)
from .research.ridge_baseline import (
    RIDGE_BASELINE_VERSION,
    RidgeBaselineError,
    evaluate_ridge_baseline,
)
from .research.walk_forward import (
    WalkForwardError,
    build_walk_forward_plan,
)


RIDGE_PLAN_SCHEMA_VERSION = "market-vault-ridge-plan-v1"
RIDGE_CLI_RESULT_SCHEMA_VERSION = "market-vault-ridge-cli-result-v1"

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "label_field",
    "feature_fields",
    "minimum_train_periods",
    "validation_periods",
    "step_periods",
    "alpha",
})


class RidgeCLIError(Exception):
    """Documented Ridge Plan/CLI V1 failure."""


_DOCUMENTED_ERRORS = (
    RidgeCLIError,
    RidgeBaselineError,
    WalkForwardError,
    ExperimentMetadataError,
    DatasetCLIError,
    MultiSourceCrossDayArtifactError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_ridge_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge",
        help="Evaluate Ridge Regression Baseline V1 on walk-forward folds",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-ridge-plan-v1 JSON",
    )


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RidgeCLIError(f"{label} must be a positive integer")
    return value


def _positive_number(value, label: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeCLIError(f"{label} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise RidgeCLIError(f"{label} must be finite")
    if number <= 0.0:
        raise RidgeCLIError(f"{label} must be strictly positive")
    return number


def _feature_fields(value) -> tuple[str, ...]:
    try:
        fields = _require_string_array(
            value,
            "feature_fields",
            allow_empty=False,
        )
    except DatasetCLIError as exc:
        raise RidgeCLIError(str(exc)) from exc
    if len(fields) != len(set(fields)):
        raise RidgeCLIError("feature_fields contains duplicates")
    return fields


def parse_ridge_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeCLIError("ridge plan must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeCLIError(
            f"ridge plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeCLIError(
            f"ridge plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "ridge plan root")
        _require_exact_fields(root, _PLAN_FIELDS, "ridge plan root")
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_PLAN_SCHEMA_VERSION:
            raise RidgeCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_PLAN_SCHEMA_VERSION!r} is accepted"
            )
        minimum_train = _positive_int(
            root["minimum_train_periods"],
            "minimum_train_periods",
        )
        validation = _positive_int(
            root["validation_periods"],
            "validation_periods",
        )
        step = _positive_int(
            root["step_periods"],
            "step_periods",
        )
        if step < validation:
            raise RidgeCLIError(
                "step_periods must be >= validation_periods"
            )
        return SimpleNamespace(
            plan_schema_version=version,
            dataset_build_dir=_require_string(
                root["dataset_build_dir"],
                "dataset_build_dir",
            ),
            label_field=_require_string(
                root["label_field"],
                "label_field",
            ),
            feature_fields=_feature_fields(root["feature_fields"]),
            minimum_train_periods=minimum_train,
            validation_periods=validation,
            step_periods=step,
            alpha=_positive_number(root["alpha"], "alpha"),
        )
    except DatasetCLIError as exc:
        raise RidgeCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    build_dir = _resolve_plan_path(
        plan.dataset_build_dir,
        base=plan_parent,
        label="Research Dataset build",
    )
    verified = load_verified_multi_source_cross_day_dataset(build_dir)
    experiment = build_experiment_dataset(
        verified,
        label_field=plan.label_field,
        feature_fields=plan.feature_fields,
    )
    walk_forward = build_walk_forward_plan(
        experiment,
        minimum_train_periods=plan.minimum_train_periods,
        validation_periods=plan.validation_periods,
        step_periods=plan.step_periods,
    )
    return evaluate_ridge_baseline(
        walk_forward,
        alpha=plan.alpha,
    )


def _feature_parameter_payload(report, fold) -> list[dict]:
    return [
        {
            "feature_name": name,
            "coefficient": coefficient,
            "train_mean": mean,
            "train_scale": scale,
        }
        for name, coefficient, mean, scale in zip(
            report.feature_names,
            fold.coefficients,
            fold.feature_means,
            fold.feature_scales,
        )
    ]


def _fold_payload(report, fold) -> dict:
    return {
        "fold_index": fold.fold_index,
        "fold_id": fold.fold_id,
        "train_count": fold.train_count,
        "validation_count": fold.validation_count,
        "alpha": fold.alpha,
        "intercept": fold.intercept,
        "features": _feature_parameter_payload(report, fold),
        "metrics": {
            "mae": fold.mae,
            "rmse": fold.rmse,
            "r2": fold.r2,
        },
    }


def _success_payload(report) -> dict:
    return {
        "result_schema_version": RIDGE_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "ridge_version": RIDGE_BASELINE_VERSION,
        "walk_forward_id": report.walk_forward_id,
        "dataset_id": report.dataset_id,
        "label_name": report.label_name,
        "feature_names": list(report.feature_names),
        "alpha": report.alpha,
        "validation_sample_count": report.validation_sample_count,
        "metrics": {
            "mae": report.mae,
            "rmse": report.rmse,
            "r2": report.r2,
        },
        "fold_count": len(report.folds),
        "folds": [
            _fold_payload(report, fold)
            for fold in report.folds
        ],
    }


def research_ridge_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_plan_bytes(_read_plan_bytes(plan_path))
        report = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(report),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeCLIError)
            else RidgeCLIError(f"research-ridge failed: {exc}")
        )
        print(
            json.dumps(
                {
                    "result_schema_version": RIDGE_CLI_RESULT_SCHEMA_VERSION,
                    "status": "FAILED",
                    "error": str(failure),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
