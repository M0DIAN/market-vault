"""Lightweight JSON artifact for Ridge Final Evaluation V1.

This module intentionally avoids a second artifact/governance framework.
The RidgeFinalEvaluationReport.report_id remains the semantic authority.

The artifact layer provides only:

- deterministic canonical JSON bytes;
- strict duplicate-key / exact-field parsing;
- exact dataclass reconstruction, which revalidates report_id;
- explicit single-file exclusive creation;
- identical-existing reuse and strict read-back.

There is no implicit output root, "latest" lookup, directory scan, clock,
network access, model fit, threshold selection, or TEST-stage decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from ..backtest.models import BacktestCosts, BacktestError
from .ridge_final_evaluation import (
    RIDGE_FINAL_EVALUATION_VERSION,
    RidgeFinalEvaluationDelta,
    RidgeFinalEvaluationError,
    RidgeFinalEvaluationReport,
)
from .ridge_final_trading import (
    RidgeFinalTradingError,
    RidgeFinalTradingMetrics,
)


RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION = (
    "market-vault-ridge-final-evaluation-artifact-v1"
)

_ROOT_FIELDS = frozenset({
    "artifact_schema_version",
    "report_id",
    "report",
})
_REPORT_FIELDS = frozenset({
    "version",
    "report_id",
    "final_test_id",
    "model_id",
    "ridge_selection_id",
    "walk_forward_id",
    "dataset_id",
    "feature_names",
    "label_name",
    "selected_alpha",
    "test_count",
    "test_mae",
    "test_rmse",
    "test_r2",
    "costs",
    "fixed_signal_rule",
    "selected_signal_rule",
    "selected_threshold",
    "threshold_selection_id",
    "selected_candidate_id",
    "fixed_trading_id",
    "selected_trading_id",
    "fixed_metrics",
    "selected_metrics",
    "delta",
})
_COST_FIELDS = frozenset({"commission_bps", "slippage_bps"})
_METRIC_FIELDS = frozenset({
    "candidate_count",
    "signal_count",
    "overlap_skipped_count",
    "trade_count",
    "gross_total_return",
    "total_return",
    "realized_max_drawdown",
    "win_rate",
    "average_trade_return",
    "profit_factor",
    "average_signal_to_exit_seconds",
})
_DELTA_FIELDS = frozenset({
    "signal_count",
    "overlap_skipped_count",
    "trade_count",
    "gross_total_return",
    "total_return",
    "realized_max_drawdown",
    "win_rate",
    "average_trade_return",
    "profit_factor",
    "average_signal_to_exit_seconds",
})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RidgeFinalEvaluationArtifactError(ValueError):
    """Fail-closed final-evaluation artifact error."""


@dataclass(frozen=True, slots=True)
class RidgeFinalEvaluationArtifactWriteResult:
    path: Path
    report_id: str
    content_sha256: str
    created_new_file: bool

    def __post_init__(self) -> None:
        if type(self.path) is not Path:
            raise RidgeFinalEvaluationArtifactError("path must be a Path")
        if type(self.report_id) is not str or _SHA256_RE.fullmatch(self.report_id) is None:
            raise RidgeFinalEvaluationArtifactError("report_id must be lowercase SHA-256")
        if (
            type(self.content_sha256) is not str
            or _SHA256_RE.fullmatch(self.content_sha256) is None
        ):
            raise RidgeFinalEvaluationArtifactError(
                "content_sha256 must be lowercase SHA-256"
            )
        if type(self.created_new_file) is not bool:
            raise RidgeFinalEvaluationArtifactError(
                "created_new_file must be boolean"
            )


def _no_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RidgeFinalEvaluationArtifactError(
                f"duplicate JSON key: {key!r}"
            )
        result[key] = value
    return result


def _object(value, fields, label: str) -> dict:
    if type(value) is not dict:
        raise RidgeFinalEvaluationArtifactError(
            f"{label} must be a JSON object"
        )
    actual = frozenset(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise RidgeFinalEvaluationArtifactError(
            f"{label} fields differ; missing={missing!r} extra={extra!r}"
        )
    return value


def _metrics_payload(metrics: RidgeFinalTradingMetrics) -> dict:
    return {
        "candidate_count": metrics.candidate_count,
        "signal_count": metrics.signal_count,
        "overlap_skipped_count": metrics.overlap_skipped_count,
        "trade_count": metrics.trade_count,
        "gross_total_return": metrics.gross_total_return,
        "total_return": metrics.total_return,
        "realized_max_drawdown": metrics.realized_max_drawdown,
        "win_rate": metrics.win_rate,
        "average_trade_return": metrics.average_trade_return,
        "profit_factor": metrics.profit_factor,
        "average_signal_to_exit_seconds": (
            metrics.average_signal_to_exit_seconds
        ),
    }


def _delta_payload(delta: RidgeFinalEvaluationDelta) -> dict:
    return {
        "signal_count": delta.signal_count,
        "overlap_skipped_count": delta.overlap_skipped_count,
        "trade_count": delta.trade_count,
        "gross_total_return": delta.gross_total_return,
        "total_return": delta.total_return,
        "realized_max_drawdown": delta.realized_max_drawdown,
        "win_rate": delta.win_rate,
        "average_trade_return": delta.average_trade_return,
        "profit_factor": delta.profit_factor,
        "average_signal_to_exit_seconds": (
            delta.average_signal_to_exit_seconds
        ),
    }


def _report_payload(report: RidgeFinalEvaluationReport) -> dict:
    return {
        "version": report.version,
        "report_id": report.report_id,
        "final_test_id": report.final_test_id,
        "model_id": report.model_id,
        "ridge_selection_id": report.ridge_selection_id,
        "walk_forward_id": report.walk_forward_id,
        "dataset_id": report.dataset_id,
        "feature_names": list(report.feature_names),
        "label_name": report.label_name,
        "selected_alpha": report.selected_alpha,
        "test_count": report.test_count,
        "test_mae": report.test_mae,
        "test_rmse": report.test_rmse,
        "test_r2": report.test_r2,
        "costs": {
            "commission_bps": report.costs.commission_bps,
            "slippage_bps": report.costs.slippage_bps,
        },
        "fixed_signal_rule": report.fixed_signal_rule,
        "selected_signal_rule": report.selected_signal_rule,
        "selected_threshold": report.selected_threshold,
        "threshold_selection_id": report.threshold_selection_id,
        "selected_candidate_id": report.selected_candidate_id,
        "fixed_trading_id": report.fixed_trading_id,
        "selected_trading_id": report.selected_trading_id,
        "fixed_metrics": _metrics_payload(report.fixed_metrics),
        "selected_metrics": _metrics_payload(report.selected_metrics),
        "delta": _delta_payload(report.delta),
    }


def serialize_ridge_final_evaluation_report(
    report: RidgeFinalEvaluationReport,
) -> bytes:
    """Return deterministic UTF-8 JSON for one exact frozen report."""
    if type(report) is not RidgeFinalEvaluationReport:
        raise RidgeFinalEvaluationArtifactError(
            "exact RidgeFinalEvaluationReport required"
        )
    try:
        validated = replace(report)
    except RidgeFinalEvaluationError as exc:
        raise RidgeFinalEvaluationArtifactError(
            "Ridge final evaluation report identity validation failed"
        ) from exc
    payload = {
        "artifact_schema_version": (
            RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION
        ),
        "report_id": validated.report_id,
        "report": _report_payload(validated),
    }
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeFinalEvaluationArtifactError(
            "report cannot be encoded as canonical JSON"
        ) from exc
    return text.encode("utf-8")


def _metrics(value, label: str) -> RidgeFinalTradingMetrics:
    obj = _object(value, _METRIC_FIELDS, label)
    try:
        return RidgeFinalTradingMetrics(
            obj["candidate_count"],
            obj["signal_count"],
            obj["overlap_skipped_count"],
            obj["trade_count"],
            obj["gross_total_return"],
            obj["total_return"],
            obj["realized_max_drawdown"],
            obj["win_rate"],
            obj["average_trade_return"],
            obj["profit_factor"],
            obj["average_signal_to_exit_seconds"],
        )
    except (RidgeFinalTradingError, TypeError, ValueError) as exc:
        raise RidgeFinalEvaluationArtifactError(
            f"{label} is invalid"
        ) from exc


def _delta(value) -> RidgeFinalEvaluationDelta:
    obj = _object(value, _DELTA_FIELDS, "report delta")
    try:
        return RidgeFinalEvaluationDelta(
            obj["signal_count"],
            obj["overlap_skipped_count"],
            obj["trade_count"],
            obj["gross_total_return"],
            obj["total_return"],
            obj["realized_max_drawdown"],
            obj["win_rate"],
            obj["average_trade_return"],
            obj["profit_factor"],
            obj["average_signal_to_exit_seconds"],
        )
    except (RidgeFinalEvaluationError, TypeError, ValueError) as exc:
        raise RidgeFinalEvaluationArtifactError(
            "report delta is invalid"
        ) from exc


def parse_ridge_final_evaluation_report_bytes(
    payload: bytes,
) -> RidgeFinalEvaluationReport:
    """Strictly decode and revalidate one Ridge Final Evaluation artifact."""
    if type(payload) is not bytes:
        raise RidgeFinalEvaluationArtifactError("artifact payload must be bytes")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise RidgeFinalEvaluationArtifactError(
            "artifact must not carry a UTF-8 BOM"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RidgeFinalEvaluationArtifactError(
            "artifact is not valid UTF-8"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except RidgeFinalEvaluationArtifactError:
        raise
    except json.JSONDecodeError as exc:
        raise RidgeFinalEvaluationArtifactError(
            "artifact is not valid JSON"
        ) from exc

    root = _object(root, _ROOT_FIELDS, "artifact root")
    if (
        root["artifact_schema_version"]
        != RIDGE_FINAL_EVALUATION_ARTIFACT_SCHEMA_VERSION
    ):
        raise RidgeFinalEvaluationArtifactError(
            "unsupported artifact_schema_version"
        )
    report_obj = _object(root["report"], _REPORT_FIELDS, "report")

    feature_names_raw = report_obj["feature_names"]
    if (
        type(feature_names_raw) is not list
        or not feature_names_raw
        or not all(type(name) is str and name for name in feature_names_raw)
    ):
        raise RidgeFinalEvaluationArtifactError(
            "report feature_names must be a non-empty string array"
        )

    costs_obj = _object(report_obj["costs"], _COST_FIELDS, "report costs")
    try:
        costs = BacktestCosts(
            costs_obj["commission_bps"],
            costs_obj["slippage_bps"],
        )
    except (BacktestError, TypeError, ValueError) as exc:
        raise RidgeFinalEvaluationArtifactError(
            "report costs are invalid"
        ) from exc

    try:
        report = RidgeFinalEvaluationReport(
            report_obj["version"],
            report_obj["report_id"],
            report_obj["final_test_id"],
            report_obj["model_id"],
            report_obj["ridge_selection_id"],
            report_obj["walk_forward_id"],
            report_obj["dataset_id"],
            tuple(feature_names_raw),
            report_obj["label_name"],
            report_obj["selected_alpha"],
            report_obj["test_count"],
            report_obj["test_mae"],
            report_obj["test_rmse"],
            report_obj["test_r2"],
            costs,
            report_obj["fixed_signal_rule"],
            report_obj["selected_signal_rule"],
            report_obj["selected_threshold"],
            report_obj["threshold_selection_id"],
            report_obj["selected_candidate_id"],
            report_obj["fixed_trading_id"],
            report_obj["selected_trading_id"],
            _metrics(report_obj["fixed_metrics"], "fixed_metrics"),
            _metrics(report_obj["selected_metrics"], "selected_metrics"),
            _delta(report_obj["delta"]),
        )
    except (RidgeFinalEvaluationError, TypeError, ValueError) as exc:
        raise RidgeFinalEvaluationArtifactError(
            "report content/identity validation failed"
        ) from exc

    if root["report_id"] != report.report_id:
        raise RidgeFinalEvaluationArtifactError(
            "artifact root report_id differs from report content"
        )
    if report.version != RIDGE_FINAL_EVALUATION_VERSION:
        raise RidgeFinalEvaluationArtifactError(
            "artifact report version is unsupported"
        )
    return report


def _explicit_path(path) -> Path:
    if type(path) is Path:
        result = path
    elif type(path) is str and path:
        result = Path(path)
    else:
        raise RidgeFinalEvaluationArtifactError(
            "artifact path must be a non-empty str or Path"
        )
    if not result.is_absolute():
        result = Path.cwd() / result
    return result


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink():
        raise RidgeFinalEvaluationArtifactError(
            "artifact path must not be a symlink"
        )
    if not path.is_file():
        raise RidgeFinalEvaluationArtifactError(
            f"artifact path must be a regular file: {path}"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RidgeFinalEvaluationArtifactError(
            f"cannot read artifact: {path}"
        ) from exc


def load_ridge_final_evaluation_artifact(
    path: str | Path,
) -> RidgeFinalEvaluationReport:
    """Read one explicit regular file and strictly revalidate its report."""
    file_path = _explicit_path(path)
    return parse_ridge_final_evaluation_report_bytes(
        _read_regular_file(file_path)
    )


def write_ridge_final_evaluation_artifact(
    report: RidgeFinalEvaluationReport,
    *,
    path: str | Path,
) -> RidgeFinalEvaluationArtifactWriteResult:
    """Exclusively create one artifact or reuse byte-identical existing file."""
    file_path = _explicit_path(path)
    parent = file_path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise RidgeFinalEvaluationArtifactError(
            f"artifact parent must be an existing regular directory: {parent}"
        )
    data = serialize_ridge_final_evaluation_report(report)
    digest = sha256(data).hexdigest()

    if file_path.exists() or file_path.is_symlink():
        existing = _read_regular_file(file_path)
        parsed = parse_ridge_final_evaluation_report_bytes(existing)
        if existing != data or parsed.report_id != report.report_id:
            raise RidgeFinalEvaluationArtifactError(
                "existing artifact differs from requested report"
            )
        return RidgeFinalEvaluationArtifactWriteResult(
            file_path,
            report.report_id,
            digest,
            False,
        )

    created = False
    try:
        with file_path.open("xb") as handle:
            created = True
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        existing = _read_regular_file(file_path)
        parsed = parse_ridge_final_evaluation_report_bytes(existing)
        if existing != data or parsed.report_id != report.report_id:
            raise RidgeFinalEvaluationArtifactError(
                "concurrent existing artifact differs from requested report"
            )
        return RidgeFinalEvaluationArtifactWriteResult(
            file_path,
            report.report_id,
            digest,
            False,
        )
    except OSError as exc:
        if created:
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise RidgeFinalEvaluationArtifactError(
            f"cannot write artifact: {file_path}"
        ) from exc

    loaded = load_ridge_final_evaluation_artifact(file_path)
    if loaded != report:
        raise RidgeFinalEvaluationArtifactError(
            "written artifact did not revalidate to requested report"
        )
    return RidgeFinalEvaluationArtifactWriteResult(
        file_path,
        report.report_id,
        digest,
        True,
    )
