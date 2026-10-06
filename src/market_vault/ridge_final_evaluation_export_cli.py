"""Final Ridge Evaluation Artifact Export Plan + CLI V1.

The command reuses the M11.1 final-evaluation pipeline exactly once and writes
the resulting frozen RidgeFinalEvaluationReport through the M12 lightweight
artifact writer.

No model fit, alpha selection, threshold search, TEST refit, winner selection,
or second report identity is implemented here.
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
from .research.ridge_final_evaluation_artifact import (
    RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION,
    RidgeFinalEvaluationArtifactError,
    write_ridge_final_evaluation_artifact,
)
from .ridge_final_evaluation_cli import (
    RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION,
    RidgeFinalEvaluationCLIError,
    _DOCUMENTED_ERRORS as RIDGE_FINAL_EVALUATION_DOCUMENTED_ERRORS,
    _run_plan as ridge_final_evaluation_run,
    _success_payload as evaluation_success_payload,
    parse_ridge_final_evaluation_plan_bytes,
)


RIDGE_FINAL_EVALUATION_EXPORT_PLAN_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-export-plan-v1"
)
RIDGE_FINAL_EVALUATION_EXPORT_CLI_RESULT_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-export-cli-result-v1"
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


class RidgeFinalEvaluationExportCLIError(Exception):
    """Documented final-evaluation export CLI failure."""


_DOCUMENTED_ERRORS = (
    RidgeFinalEvaluationExportCLIError,
    RidgeFinalEvaluationArtifactError,
    RidgeFinalEvaluationCLIError,
    *RIDGE_FINAL_EVALUATION_DOCUMENTED_ERRORS,
    DatasetCLIError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_ridge_final_evaluation_export_subparser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research-ridge-final-evaluation-export",
        help="Run final Ridge evaluation and write one explicit JSON artifact",
    )
    parser.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help=(
            "Path to "
            "market-vault-ridge-final-evaluation-export-plan-v1 JSON"
        ),
    )


def _evaluation_plan_payload(root: dict) -> bytes:
    payload = dict(root)
    payload.pop("artifact_path")
    payload["plan_schema_version"] = (
        RIDGE_FINAL_EVALUATION_PLAN_SCHEMA_VERSION
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_ridge_final_evaluation_export_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise RidgeFinalEvaluationExportCLIError(
            "ridge final evaluation export plan must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeFinalEvaluationExportCLIError(
            "ridge final evaluation export plan is not valid UTF-8: "
            f"{exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise RidgeFinalEvaluationExportCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise RidgeFinalEvaluationExportCLIError(
            "ridge final evaluation export plan is not valid JSON: "
            f"{exc}"
        ) from exc

    try:
        root = _require_object(
            root,
            "ridge final evaluation export plan root",
        )
        _require_exact_fields(
            root,
            _PLAN_FIELDS,
            "ridge final evaluation export plan root",
        )
        version = _require_string(
            root["plan_schema_version"],
            "plan_schema_version",
        )
        if version != RIDGE_FINAL_EVALUATION_EXPORT_PLAN_SCHEMA_VERSION:
            raise RidgeFinalEvaluationExportCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RIDGE_FINAL_EVALUATION_EXPORT_PLAN_SCHEMA_VERSION!r} "
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
            raise RidgeFinalEvaluationExportCLIError(str(exc)) from exc
        return SimpleNamespace(
            plan_schema_version=version,
            evaluation_plan=evaluation_plan,
            artifact_path=artifact_path,
        )
    except DatasetCLIError as exc:
        raise RidgeFinalEvaluationExportCLIError(str(exc)) from exc


def _run_plan(plan, plan_parent: Path):
    values = ridge_final_evaluation_run(
        plan.evaluation_plan,
        plan_parent,
    )
    report = values[-1]
    artifact_path = _resolve_plan_path(
        plan.artifact_path,
        base=plan_parent,
        label="Ridge final evaluation artifact",
    )
    written = write_ridge_final_evaluation_artifact(
        report,
        path=artifact_path,
    )
    return values, written


def _success_payload(values, written) -> dict:
    payload = evaluation_success_payload(*values)
    payload["result_schema_version"] = (
        RIDGE_FINAL_EVALUATION_EXPORT_CLI_RESULT_SCHEMA_VERSION
    )
    payload["artifact"] = {
        "artifact_schema_version": (
            RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION
        ),
        "path": str(written.path),
        "report_id": written.report_id,
        "content_sha256": written.content_sha256,
        "created_new_file": written.created_new_file,
    }
    return payload


def research_ridge_final_evaluation_export_main(
    args: argparse.Namespace,
) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_ridge_final_evaluation_export_plan_bytes(
            _read_plan_bytes(plan_path)
        )
        values, written = _run_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(values, written),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        failure = (
            exc
            if isinstance(exc, RidgeFinalEvaluationExportCLIError)
            else RidgeFinalEvaluationExportCLIError(
                "research-ridge-final-evaluation-export failed: "
                f"{exc}"
            )
        )
        print(
            json.dumps(
                {
                    "result_schema_version": (
                        RIDGE_FINAL_EVALUATION_EXPORT_CLI_RESULT_SCHEMA_VERSION
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
