"""Feature Selection Plan + CLI V1.

This command is a settings-independent composition layer over one verified
Research Dataset artifact, ML Dataset Adapter V1, and Feature Selection V1.

It performs no Dataset discovery, no latest selection, no random split, no
TEST-based Feature selection, no model training, no OpenD/network access, and
no current-time lookup.
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
from .research.feature_selection import (
    FEATURE_SELECTION_VERSION,
    FeatureSelectionError,
    FeatureSelectionPolicy,
    select_features,
)
from .research.ml import MLDatasetError, build_ml_dataset


FEATURE_SELECTION_PLAN_SCHEMA_VERSION = (
    "market-vault-feature-selection-plan-v1"
)
FEATURE_SELECTION_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-feature-selection-cli-result-v1"
)

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "label_field",
    "feature_fields",
    "quantile_count",
    "policy",
})
_POLICY_FIELDS = frozenset({
    "minimum_train_samples",
    "minimum_validation_samples",
    "minimum_abs_train_rank_ic",
    "minimum_abs_validation_rank_ic",
    "maximum_rank_ic_drift",
    "require_same_sign",
})


class FeatureSelectionCLIError(Exception):
    """Documented Feature Selection Plan/CLI failure."""


_DOCUMENTED_ERRORS = (
    FeatureSelectionCLIError,
    FeatureSelectionError,
    MLDatasetError,
    DatasetCLIError,
    MultiSourceCrossDayArtifactError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_feature_selection_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-feature-select",
        help="Select Features from TRAIN + VALIDATION Rank-IC stability",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-feature-selection-plan-v1 JSON",
    )


def _quantile_count(value) -> int:
    if type(value) is not int or not 2 <= value <= 10:
        raise FeatureSelectionCLIError(
            "quantile_count must be an integer within [2, 10]"
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
        raise FeatureSelectionCLIError(str(exc)) from exc


def _policy(value) -> FeatureSelectionPolicy:
    try:
        mapping = _require_object(value, "policy")
        _require_exact_fields(mapping, _POLICY_FIELDS, "policy")
    except DatasetCLIError as exc:
        raise FeatureSelectionCLIError(str(exc)) from exc
    try:
        return FeatureSelectionPolicy(
            mapping["minimum_train_samples"],
            mapping["minimum_validation_samples"],
            mapping["minimum_abs_train_rank_ic"],
            mapping["minimum_abs_validation_rank_ic"],
            mapping["maximum_rank_ic_drift"],
            mapping["require_same_sign"],
        )
    except FeatureSelectionError as exc:
        raise FeatureSelectionCLIError(str(exc)) from exc


def parse_feature_selection_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise FeatureSelectionCLIError(
            "feature selection plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FeatureSelectionCLIError(
            f"feature selection plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise FeatureSelectionCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise FeatureSelectionCLIError(
            f"feature selection plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "feature selection plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "feature selection plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != FEATURE_SELECTION_PLAN_SCHEMA_VERSION:
            raise FeatureSelectionCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{FEATURE_SELECTION_PLAN_SCHEMA_VERSION!r} is accepted"
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
            quantile_count=_quantile_count(root["quantile_count"]),
            policy=_policy(root["policy"]),
        )
    except DatasetCLIError as exc:
        raise FeatureSelectionCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    build_dir = _resolve_plan_path(
        plan.dataset_build_dir,
        base=plan_parent,
        label="Research Dataset build",
    )
    verified = load_verified_multi_source_cross_day_dataset(build_dir)
    bundle = build_ml_dataset(
        verified,
        label_field=plan.label_field,
        feature_fields=plan.feature_fields,
    )
    return select_features(
        bundle,
        policy=plan.policy,
        feature_names=plan.feature_fields,
        quantile_count=plan.quantile_count,
    )


def _policy_payload(policy) -> dict:
    return {
        "minimum_train_samples": policy.minimum_train_samples,
        "minimum_validation_samples": policy.minimum_validation_samples,
        "minimum_abs_train_rank_ic":
            policy.minimum_abs_train_rank_ic,
        "minimum_abs_validation_rank_ic":
            policy.minimum_abs_validation_rank_ic,
        "maximum_rank_ic_drift": policy.maximum_rank_ic_drift,
        "require_same_sign": policy.require_same_sign,
    }


def _decision_payload(decision) -> dict:
    return {
        "feature_name": decision.feature_name,
        "selected": decision.selected,
        "reason_codes": list(decision.reason_codes),
        "train_sample_count": decision.train_sample_count,
        "validation_sample_count": decision.validation_sample_count,
        "train_rank_ic": decision.train_rank_ic,
        "validation_rank_ic": decision.validation_rank_ic,
        "rank_ic_drift": decision.rank_ic_drift,
        "rank_ic_sign_consistent": decision.rank_ic_sign_consistent,
    }


def _success_payload(report) -> dict:
    return {
        "result_schema_version":
            FEATURE_SELECTION_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "feature_selection_version": FEATURE_SELECTION_VERSION,
        "dataset_id": report.dataset_id,
        "label_name": report.label_name,
        "quantile_count": report.quantile_count,
        "policy": _policy_payload(report.policy),
        "selected_features": list(report.selected_features),
        "decisions": [
            _decision_payload(decision)
            for decision in report.decisions
        ],
    }


def research_feature_select_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_feature_selection_plan_bytes(
            _read_plan_bytes(plan_path)
        )
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
            if isinstance(exc, FeatureSelectionCLIError)
            else FeatureSelectionCLIError(
                f"research-feature-select failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version":
                        FEATURE_SELECTION_CLI_RESULT_SCHEMA_VERSION,
                    "status": "FAILED",
                    "error": str(failure),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
