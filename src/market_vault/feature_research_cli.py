"""Feature Research Plan + CLI V1.

This command is a settings-independent composition layer over the verified
Research Dataset reader, ML Dataset Adapter V1, and Feature Research V1.

It performs no Dataset discovery, no "latest" selection, no random split,
no model training, no OpenD/network access, and no current-time lookup.
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
from .research.feature_research import (
    FEATURE_RESEARCH_VERSION,
    FeatureResearchError,
    analyze_features,
)
from .research.ml import MLDatasetError, build_ml_dataset


FEATURE_RESEARCH_PLAN_SCHEMA_VERSION = "market-vault-feature-research-plan-v1"
FEATURE_RESEARCH_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-feature-research-cli-result-v1"
)

_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "dataset_build_dir",
    "label_field",
    "feature_fields",
    "split",
    "quantile_count",
})


class FeatureResearchCLIError(Exception):
    """Documented Feature Research Plan/CLI failure."""


_DOCUMENTED_ERRORS = (
    FeatureResearchCLIError,
    FeatureResearchError,
    MLDatasetError,
    DatasetCLIError,
    MultiSourceCrossDayArtifactError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_feature_research_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-feature-report",
        help="Analyze Feature IC/rank-IC/tails from one verified Research Dataset",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-feature-research-plan-v1 JSON",
    )


def _quantile_count(value) -> int:
    if type(value) is not int or not 2 <= value <= 10:
        raise FeatureResearchCLIError(
            "quantile_count must be an integer within [2, 10]"
        )
    return value


def _feature_fields(value):
    if value is None:
        return None
    try:
        fields = _require_string_array(
            value,
            "feature_fields",
            allow_empty=False,
        )
    except DatasetCLIError as exc:
        raise FeatureResearchCLIError(str(exc)) from exc
    return fields


def parse_feature_research_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise FeatureResearchCLIError(
            "feature research plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FeatureResearchCLIError(
            f"feature research plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise FeatureResearchCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise FeatureResearchCLIError(
            f"feature research plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "feature research plan root")
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "feature research plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != FEATURE_RESEARCH_PLAN_SCHEMA_VERSION:
            raise FeatureResearchCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{FEATURE_RESEARCH_PLAN_SCHEMA_VERSION!r} is accepted"
            )
        split = _require_string(root["split"], "split")
        if split not in ("TRAIN", "VALIDATION", "TEST"):
            raise FeatureResearchCLIError(
                "split must be TRAIN, VALIDATION, or TEST"
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
            split=split,
            quantile_count=_quantile_count(root["quantile_count"]),
        )
    except DatasetCLIError as exc:
        raise FeatureResearchCLIError(str(exc)) from exc


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
    return analyze_features(
        bundle,
        split=plan.split,
        feature_names=plan.feature_fields,
        quantile_count=plan.quantile_count,
    )


def _metric_payload(metric) -> dict:
    return {
        "feature_name": metric.feature_name,
        "sample_count": metric.sample_count,
        "feature_mean": metric.feature_mean,
        "feature_std": metric.feature_std,
        "pearson_ic": metric.pearson_ic,
        "rank_ic": metric.rank_ic,
        "bottom_count": metric.bottom_count,
        "top_count": metric.top_count,
        "bottom_label_mean": metric.bottom_label_mean,
        "top_label_mean": metric.top_label_mean,
        "top_bottom_spread": metric.top_bottom_spread,
    }


def _success_payload(report) -> dict:
    return {
        "result_schema_version": FEATURE_RESEARCH_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "feature_research_version": FEATURE_RESEARCH_VERSION,
        "dataset_id": report.dataset_id,
        "split": report.split,
        "label_name": report.label_name,
        "quantile_count": report.quantile_count,
        "metrics": [_metric_payload(metric) for metric in report.metrics],
    }


def research_feature_report_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_feature_research_plan_bytes(
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
            if isinstance(exc, FeatureResearchCLIError)
            else FeatureResearchCLIError(
                f"research-feature-report failed: {exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version":
                        FEATURE_RESEARCH_CLI_RESULT_SCHEMA_VERSION,
                    "status": "FAILED",
                    "error": str(failure),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
