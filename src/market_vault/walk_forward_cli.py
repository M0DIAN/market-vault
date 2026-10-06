"""Walk-Forward Plan + CLI V1.

Settings-independent composition over:

verified Research Dataset -> Experiment Metadata V1 -> Walk-Forward Fold V1.

The command performs no Dataset discovery, random split, model fitting,
Feature ranking, OpenD/network access, or current-time lookup.
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
    WalkForwardSpec,
    generate_walk_forward_folds,
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
    "minimum_train_samples",
    "validation_samples",
    "step_samples",
    "embargo_seconds",
})


class WalkForwardCLIError(Exception):
    """Documented Walk-Forward Plan/CLI failure."""


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
        help="Generate leakage-safe expanding folds from TRAIN experiment data",
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


def _non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise WalkForwardCLIError(
            f"{label} must be a non-negative integer"
        )
    return value


def _feature_fields(value):
    if value is None:
        return None
    try:
        return _require_string_array(
            value,
            "feature_fields",
            allow_empty=False,
        )
    except DatasetCLIError as exc:
        raise WalkForwardCLIError(str(exc)) from exc


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
        validation = _positive_int(
            root["validation_samples"],
            "validation_samples",
        )
        step = _positive_int(root["step_samples"], "step_samples")
        if step < validation:
            raise WalkForwardCLIError(
                "step_samples must be >= validation_samples"
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
            minimum_train_samples=_positive_int(
                root["minimum_train_samples"],
                "minimum_train_samples",
            ),
            validation_samples=validation,
            step_samples=step,
            embargo_seconds=_non_negative_int(
                root["embargo_seconds"],
                "embargo_seconds",
            ),
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
    spec = WalkForwardSpec(
        plan.minimum_train_samples,
        plan.validation_samples,
        plan.step_samples,
        plan.embargo_seconds,
    )
    return generate_walk_forward_folds(experiment, spec)


def _fold_payload(fold) -> dict:
    return {
        "fold_index": fold.fold_index,
        "validation_start_time": fold.validation_start_time.isoformat(),
        "validation_end_time": fold.validation_end_time.isoformat(),
        "train_count": fold.train_count,
        "validation_count": fold.validation_count,
        "purged_count": fold.purged_count,
        "embargoed_count": fold.embargoed_count,
    }


def _success_payload(plan) -> dict:
    return {
        "result_schema_version": WALK_FORWARD_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "walk_forward_version": WALK_FORWARD_VERSION,
        "dataset_id": plan.dataset_id,
        "label_name": plan.label_name,
        "feature_names": list(plan.feature_names),
        "source_split": plan.source_split,
        "source_row_count": plan.source_row_count,
        "unused_tail_count": plan.unused_tail_count,
        "spec": {
            "minimum_train_samples": plan.spec.minimum_train_samples,
            "validation_samples": plan.spec.validation_samples,
            "step_samples": plan.spec.step_samples,
            "embargo_seconds": plan.spec.embargo_seconds,
        },
        "fold_count": plan.fold_count,
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
