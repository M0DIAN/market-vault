"""Ridge Final TEST Plan + CLI V1 for the MarketVault research mainline.

The command is a thin settings-independent composition layer over:

verified Research Dataset
-> Experiment Metadata V1
-> Walk-Forward Experiment V1
-> Ridge Alpha Selection V1
-> Ridge Final TEST Evaluation V1

It performs no Dataset discovery, random split, shuffle, Feature selection,
model persistence, external ML framework work, OpenD/network access, or
current-time lookup.  Every input is declared by one strict JSON plan.
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
from .research.ridge_final_test import (
    RIDGE_FINAL_TEST_VERSION,
    RidgeFinalTestError,
    evaluate_ridge_final_test,
)
from .research.ridge_selection import (
    RIDGE_ALPHA_SELECTION_VERSION,
    RidgeAlphaSelectionError,
    select_ridge_alpha,
)
from .research.walk_forward import (
    WalkForwardError,
    build_walk_forward_plan,
)


RIDGE_FINAL_PLAN_SCHEMA_VERSION = "market-vault-ridge-final-plan-v1"
RIDGE_FINAL_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-final-cli-result-v1"
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
})


class RidgeFinalCLIError(Exception):
    """Documented Ridge Final TEST Plan/CLI V1 failure."""


_DOCUMENTED_ERRORS = (
    RidgeFinalCLIError,
    RidgeFinalTestError,
    RidgeAlphaSelectionError,
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


def add_ridge_final_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-final",
        help="Select Ridge alpha on validation and evaluate final TEST",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-ridge-final-plan-v1 JSON",
    )


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RidgeFinalCLIError(f"{label} must be a positive integer")
    return value


def _feature_fields(value) -> tuple[str, ...]:
    try:
        fields = _require_string_array(
            value,
            "feature_fields",
            allow_empty=False,
        )
    except DatasetCLIError as exc:
        raise RidgeFinalCLIError(str(exc)) from exc
    if len(fields) != len(set(fields)):
        raise RidgeFinalCLIError("feature_fields contains duplicates")
    return fields


def _alpha(value) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise RidgeFinalCLIError("alpha candidates must be JSON numbers")
    number = float(value)
    if not math.isfinite(number):
        raise RidgeFinalCLIError("alpha candidates must be finite")
    if number <= 0.0:
        raise RidgeFinalCLIError(
            "alpha candidates must be strictly positive"
        )
    return number


def _alphas(value) -> tuple[float, ...]:
    if type(value) is not list:
        raise RidgeFinalCLIError("alphas must be a JSON array")
    normalized = tuple(_alpha(item) for item in value)
    if len(normalized) < 2:
        raise RidgeFinalCLIError(
            "alphas must contain at least two candidates"
        )
    if len(set(normalized)) != len(normalized):
        raise RidgeFinalCLIError("alpha candidates must be unique")
    return tuple(sorted(normalized))


def parse_ridge_final_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeFinalCLIError(
            "ridge final plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeFinalCLIError(
            f"ridge final plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeFinalCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeFinalCLIError(
            f"ridge final plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "ridge final plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge final plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_FINAL_PLAN_SCHEMA_VERSION:
            raise RidgeFinalCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_FINAL_PLAN_SCHEMA_VERSION!r} is accepted"
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
            raise RidgeFinalCLIError(
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
            alphas=_alphas(root["alphas"]),
        )
    except DatasetCLIError as exc:
        raise RidgeFinalCLIError(str(exc)) from exc


def _pipeline(plan, plan_parent: Path):
    """Build the exact Ridge final pipeline once for CLI composition layers."""
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
    selection = select_ridge_alpha(
        walk_forward,
        alphas=plan.alphas,
    )
    final = evaluate_ridge_final_test(
        experiment,
        walk_forward,
        selection,
    )
    return verified, experiment, walk_forward, selection, final


def _run_plan(plan, plan_parent: Path):
    _, _, _, selection, final = _pipeline(plan, plan_parent)
    return selection, final


def _candidate_payload(candidate) -> dict:
    report = candidate.report
    return {
        "candidate_id": candidate.candidate_id,
        "alpha": candidate.alpha,
        "validation_sample_count": report.validation_sample_count,
        "metrics": {
            "mae": report.mae,
            "rmse": report.rmse,
            "r2": report.r2,
        },
    }


def _feature_parameter_payload(result) -> list[dict]:
    return [
        {
            "feature_name": name,
            "coefficient": coefficient,
            "development_mean": mean,
            "development_scale": scale,
        }
        for name, coefficient, mean, scale in zip(
            result.feature_names,
            result.coefficients,
            result.feature_means,
            result.feature_scales,
        )
    ]


def _success_payload(selection, result) -> dict:
    return {
        "result_schema_version": RIDGE_FINAL_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "alpha_selection_version": RIDGE_ALPHA_SELECTION_VERSION,
        "final_test_version": RIDGE_FINAL_TEST_VERSION,
        "selection_id": selection.selection_id,
        "final_test_id": result.final_test_id,
        "model_id": result.model_id,
        "walk_forward_id": result.walk_forward_id,
        "dataset_id": result.dataset_id,
        "label_name": result.label_name,
        "feature_names": list(result.feature_names),
        "selected_alpha": result.alpha,
        "alpha_candidates": [
            _candidate_payload(candidate)
            for candidate in selection.candidates
        ],
        "test_start_time": result.test_start_time.isoformat(),
        "development": {
            "candidate_count": result.development_candidate_count,
            "purged_count": result.development_purged_count,
            "retained_count": result.development_count,
            "sample_keys_digest": result.development_keys_digest,
        },
        "test_count": result.test_count,
        "model": {
            "intercept": result.intercept,
            "features": _feature_parameter_payload(result),
        },
        "test_metrics": {
            "mae": result.mae,
            "rmse": result.rmse,
            "r2": result.r2,
        },
        "prediction_count": len(result.predictions),
    }


def research_ridge_final_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_final_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        selection, result = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(selection, result),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeFinalCLIError)
            else RidgeFinalCLIError(
                f"research-ridge-final failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_FINAL_CLI_RESULT_SCHEMA_VERSION
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
