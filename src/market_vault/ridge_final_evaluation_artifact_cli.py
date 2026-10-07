"""Final Ridge Evaluation Artifact Plan + CLI V1.

This command is a thin wrapper over the already-validated final Ridge
evaluation pipeline and artifact writer:

    final-evaluation plan
    -> one frozen RidgeFinalEvaluationReport
    -> one explicit artifact path
    -> #246 strict exclusive writer

It performs no additional alpha/threshold selection, model fit, TEST-stage
decision, report transformation, path discovery, or current-time lookup.
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
    _resolve_plan_path,
)
from .ridge_final_evaluation_cli import (
    RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION,
    RidgeFinalEvaluationCLIError,
    _DOCUMENTED_ERRORS as FINAL_EVALUATION_DOCUMENTED_ERRORS,
    _run_plan as _run_evaluation_plan,
    _success_payload as _evaluation_success_payload,
    parse_ridge_final_evaluation_plan_bytes,
)
from .research.ridge_final_evaluation_artifact import (
    RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION,
    RidgeFinalEvaluationArtifactError,
    write_ridge_final_evaluation_artifact,
)


RIDGE_FINAL_EVALUATION_ARTIFACT_PLAN_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-artifact-plan-v1"
)
RIDGE_FINAL_EVALUATION_ARTIFACT_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-artifact-cli-result-v1"
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
    "artifact_path",
})


class RidgeFinalEvaluationArtifactCLIError(Exception):
    """Documented Final Ridge Evaluation Artifact CLI failure."""


_DOCUMENTED_ERRORS = (
    RidgeFinalEvaluationArtifactCLIError,
    RidgeFinalEvaluationArtifactError,
    RidgeFinalEvaluationCLIError,
    *FINAL_EVALUATION_DOCUMENTED_ERRORS,
    DatasetCLIError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_ridge_final_evaluation_artifact_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-final-evaluation-artifact",
        help=(
            "Run frozen final Ridge evaluation once and write one explicit "
            "verified JSON artifact"
        ),
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help=(
            "Path to "
            "market-vault-ridge-final-evaluation-artifact-plan-v1 JSON"
        ),
    )


def _evaluation_plan_payload(root: dict) -> bytes:
    payload = dict(root)
    payload.pop("artifact_path")
    payload["plan_schema_version"] = RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_ridge_final_evaluation_artifact_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeFinalEvaluationArtifactCLIError(
            "ridge final evaluation artifact plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeFinalEvaluationArtifactCLIError(
            "ridge final evaluation artifact plan is not valid UTF-8: "
            f"{exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeFinalEvaluationArtifactCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeFinalEvaluationArtifactCLIError(
            "ridge final evaluation artifact plan is not valid JSON: "
            f"{exc}"
        ) from exc

    try:
        root = _require_object(
            root,
            "ridge final evaluation artifact plan root",
        )
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge final evaluation artifact plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_FINAL_EVALUATION_ARTIFACT_PLAN_SCHEMA_VERSION:
            raise RidgeFinalEvaluationArtifactCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_FINAL_EVALUATION_ARTIFACT_PLAN_SCHEMA_VERSION!r} "
                "is accepted"
            )
        artifact_path = _require_string(
            root["artifact_path"],
            "artifact_path",
        )
        try:
            evaluation_plan = parse_ridge_final_evaluation_plan_bytes(
                _evaluation_plan_payload(root)
            )
        except RidgeFinalEvaluationCLIError as exc:
            raise RidgeFinalEvaluationArtifactCLIError(str(exc)) from exc
        return SimpleNamespace(
            plan_schema_version=version,
            evaluation_plan=evaluation_plan,
            artifact_path=artifact_path,
        )
    except DatasetCLIError as exc:
        raise RidgeFinalEvaluationArtifactCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    values = _run_evaluation_plan(
        plan.evaluation_plan,
        plan_parent,
    )
    report = values[-1]
    artifact_path = _resolve_plan_path(
        plan.artifact_path,
        base=plan_parent,
        label="Ridge final evaluation artifact",
    )
    write_result = write_ridge_final_evaluation_artifact(
        report,
        path=artifact_path,
    )
    if write_result.report_id != report.report_id:
        raise RidgeFinalEvaluationArtifactCLIError(
            "artifact writer returned a different report_id"
        )
    return values, write_result


def _success_payload(values, write_result) -> dict:
    payload = dict(_evaluation_success_payload(*values))
    payload["result_schema_version"] = (
        RIDGE_FINAL_EVALUATION_ARTIFACT_CLI_RESULT_SCHEMA_VERSION
    )
    payload["artifact"] = {
        "artifact_schema_version": (
            RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION
        ),
        "path": str(write_result.path),
        "report_id": write_result.report_id,
        "content_sha256": write_result.content_sha256,
        "created_new_file": write_result.created_new_file,
    }
    return payload


def research_ridge_final_evaluation_artifact_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_final_evaluation_artifact_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        values, write_result = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(values, write_result),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeFinalEvaluationArtifactCLIError)
            else RidgeFinalEvaluationArtifactCLIError(
                "research-ridge-final-evaluation-artifact failed: "
                f"{exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_FINAL_EVALUATION_ARTIFACT_CLI_RESULT_SCHEMA_VERSION
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
