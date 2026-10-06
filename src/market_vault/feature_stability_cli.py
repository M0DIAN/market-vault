"""Feature Stability Plan + CLI V1.

This command is a settings-independent composition layer over the verified
Research Dataset reader, ML Dataset Adapter V1, and Feature Stability V1.

It performs no Dataset discovery, no "latest" selection, no random split,
no model training, no Feature ranking/selection, no OpenD/network access,
and no current-time lookup.
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
from .research.feature_stability import (
    FEATURE_STABILITY_VERSION,
    FeatureStabilityError,
    compare_feature_stability,
)
from .research.ml import MLDatasetError, build_ml_dataset


FEATURE_STABILITY_PLAN_SCHEMA_VERSION = "market-vault-feature-stability-plan-v1"
FEATURE_STABILITY_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-feature-stability-cli-result-v1"
)

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "label_field",
    "feature_fields",
    "quantile_count",
})


class FeatureStabilityCLIError(Exception):
    """Documented Feature Stability Plan/CLI failure."""


_DOCUMENTED_ERRORS = (
    FeatureStabilityCLIError,
    FeatureStabilityError,
    MLDatasetError,
    DatasetCLIError,
    MultiSourceCrossDayArtifactError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_feature_stability_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-feature-stability",
        help="Compare Feature IC/rank-IC/spread stability across ML splits",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-feature-stability-plan-v1 JSON",
    )


def _quantile_count(value) -> int:
    if type(value) is not int or not 2 <= value <= 10:
        raise FeatureStabilityCLIError(
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
        raise FeatureStabilityCLIError(str(exc)) from exc


def parse_feature_stability_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise FeatureStabilityCLIError(
            "feature stability plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FeatureStabilityCLIError(
            f"feature stability plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise FeatureStabilityCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise FeatureStabilityCLIError(
            f"feature stability plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "feature stability plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "feature stability plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != FEATURE_STABILITY_PLAN_SCHEMA_VERSION:
            raise FeatureStabilityCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{FEATURE_STABILITY_PLAN_SCHEMA_VERSION!r} is accepted"
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
        )
    except DatasetCLIError as exc:
        raise FeatureStabilityCLIError(str(exc)) from exc


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
    return compare_feature_stability(
        bundle,
        feature_names=plan.feature_fields,
        quantile_count=plan.quantile_count,
    )


def _metric_payload(metric) -> dict:
    return {
        "feature_name": metric.feature_name,
        "sample_counts": {
            "TRAIN": metric.train_sample_count,
            "VALIDATION": metric.validation_sample_count,
            "TEST": metric.test_sample_count,
        },
        "pearson_ic": {
            "TRAIN": metric.train_pearson_ic,
            "VALIDATION": metric.validation_pearson_ic,
            "TEST": metric.test_pearson_ic,
            "available_count": metric.pearson_available_count,
            "sign_consistent": metric.pearson_sign_consistent,
            "range": metric.pearson_range,
        },
        "rank_ic": {
            "TRAIN": metric.train_rank_ic,
            "VALIDATION": metric.validation_rank_ic,
            "TEST": metric.test_rank_ic,
            "available_count": metric.rank_available_count,
            "sign_consistent": metric.rank_sign_consistent,
            "range": metric.rank_range,
        },
        "top_bottom_spread": {
            "TRAIN": metric.train_top_bottom_spread,
            "VALIDATION": metric.validation_top_bottom_spread,
            "TEST": metric.test_top_bottom_spread,
            "available_count": metric.spread_available_count,
            "sign_consistent": metric.spread_sign_consistent,
            "range": metric.spread_range,
        },
    }


def _success_payload(report) -> dict:
    return {
        "result_schema_version": FEATURE_STABILITY_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "feature_stability_version": FEATURE_STABILITY_VERSION,
        "dataset_id": report.dataset_id,
        "label_name": report.label_name,
        "quantile_count": report.quantile_count,
        "metrics": [_metric_payload(metric) for metric in report.metrics],
    }


def research_feature_stability_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_feature_stability_plan_bytes(
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
            if isinstance(exc, FeatureStabilityCLIError)
            else FeatureStabilityCLIError(
                f"research-feature-stability failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version":
                        FEATURE_STABILITY_CLI_RESULT_SCHEMA_VERSION,
                    "status": "FAILED",
                    "error": str(failure),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
