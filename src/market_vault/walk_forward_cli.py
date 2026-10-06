"""Walk-Forward Plan + CLI V1 for the MarketVault research mainline.

This is a settings-independent composition layer over:

verified Research Dataset
-> Experiment Metadata V1
-> Walk-Forward Experiment V1

It performs no Dataset discovery, random split, model fitting, Feature
selection, OpenD/network access, or current-time lookup.

The plan requires an explicit non-empty Feature list so a previously selected
Feature subset is not silently widened back to the full Dataset catalog.
"""

from __future__ import annotations

import argparse
import codecs
import json
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
from .research.walk_forward import (
    WALK_FORWARD_VERSION,
    WalkForwardError,
    build_walk_forward_plan,
)


WALK_FORWARD_PLAN_SCHEMA_VERSION = "market-vault-walk-forward-plan-v1"
WALK_FORWARD_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-walk-forward-cli-result-v1"
)

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "label_field",
    "feature_fields",
    "minimum_train_periods",
    "validation_periods",
    "step_periods",
})


class WalkForwardCLIError(Exception):
    """Documented Walk-Forward Plan/CLI V1 failure."""


_DOCUMENTED_ERRORS = (
    WalkForwardCLIError,
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


def add_walk_forward_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-walk-forward",
        help="Build leakage-safe TRAIN+VALIDATION walk-forward folds",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-walk-forward-plan-v1 JSON",
    )


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise WalkForwardCLIError(f"{label} must be a positive integer")
    return value


def _feature_fields(value) -> tuple[str, ...]:
    try:
        fields = _require_string_array(
            value,
            "feature_fields",
            allow_empty=False,
        )
    except DatasetCLIError as exc:
        raise WalkForwardCLIError(str(exc)) from exc
    if len(fields) != len(set(fields)):
        raise WalkForwardCLIError("feature_fields contains duplicates")
    return fields


def parse_walk_forward_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise WalkForwardCLIError(
            "walk-forward plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WalkForwardCLIError(
            f"walk-forward plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise WalkForwardCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise WalkForwardCLIError(
            f"walk-forward plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "walk-forward plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "walk-forward plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != WALK_FORWARD_PLAN_SCHEMA_VERSION:
            raise WalkForwardCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{WALK_FORWARD_PLAN_SCHEMA_VERSION!r} is accepted"
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
            raise WalkForwardCLIError(
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
        )
    except DatasetCLIError as exc:
        raise WalkForwardCLIError(str(exc)) from exc


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
    return build_walk_forward_plan(
        experiment,
        minimum_train_periods=plan.minimum_train_periods,
        validation_periods=plan.validation_periods,
        step_periods=plan.step_periods,
    )


def _fold_payload(fold) -> dict:
    return {
        "fold_index": fold.fold_index,
        "fold_id": fold.fold_id,
        "validation_start_time": fold.validation_start_time.isoformat(),
        "validation_end_time": fold.validation_end_time.isoformat(),
        "train_candidate_count": fold.train_candidate_count,
        "purged_train_count": fold.purged_train_count,
        "train_count": fold.train.row_count,
        "validation_count": fold.validation.row_count,
    }


def _success_payload(plan) -> dict:
    return {
        "result_schema_version": WALK_FORWARD_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "walk_forward_version": WALK_FORWARD_VERSION,
        "walk_forward_id": plan.walk_forward_id,
        "dataset_id": plan.dataset_id,
        "label_name": plan.label_name,
        "feature_names": list(plan.feature_names),
        "config": {
            "minimum_train_periods": plan.minimum_train_periods,
            "validation_periods": plan.validation_periods,
            "step_periods": plan.step_periods,
        },
        "development_period_count": plan.development_period_count,
        "development_sample_count": plan.development_sample_count,
        "held_out_test_count": plan.held_out_test_count,
        "fold_count": len(plan.folds),
        "folds": [_fold_payload(fold) for fold in plan.folds],
    }


def research_walk_forward_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_walk_forward_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        result = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(result),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, WalkForwardCLIError)
            else WalkForwardCLIError(
                f"research-walk-forward failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version":
                        WALK_FORWARD_CLI_RESULT_SCHEMA_VERSION,
                    "status": "FAILED",
                    "error": str(failure),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
