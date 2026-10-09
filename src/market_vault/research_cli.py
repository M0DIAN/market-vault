"""Research Build Plan + CLI for the v0.9.0 research mainline.

This command is a thin usability layer over build_research_dataset. It does not
implement another Dataset builder, another artifact reader, schedule discovery,
latest selection, OpenD access, network access, or current-time defaults.

All execution inputs are declared by one strict JSON plan. Paths are absolute
or relative to the plan file's parent directory and reuse the Dataset CLI's
existing lexical and link-safety helpers.
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from .backtest_cli import add_backtest_subparser, research_backtest_main
from .strategy_comparison_cli import (
    add_strategy_comparison_subparser,
    research_compare_strategies_main,
)
from .strategy_experiment_cli import add_strategy_experiment_subparsers, research_experiment_main
from .strategy_diagnostics_cli import add_strategy_diagnostics_subparser, research_diagnose_strategy_main
from .intraday_data_cli import add_intraday_data_subparsers, research_intraday_data_main
from .intraday_backtest_cli import add_intraday_backtest_subparser, research_intraday_backtest_main
from .intraday_research_cli import add_intraday_research_subparsers, research_intraday_research_main
from .intraday_performance_cli import add_intraday_performance_subparser, research_intraday_performance_main
from .intraday_risk_diagnostics_cli import add_intraday_risk_diagnostics_subparser, research_intraday_risk_diagnostics_main
from .intraday_parameter_grid_cli import add_intraday_parameter_grid_subparser, research_intraday_parameter_grid_main
from .intraday_return_uncertainty_cli import add_intraday_return_uncertainty_subparser, research_intraday_return_uncertainty_main
from .intraday_plan_cli import add_intraday_plan_subparser, research_intraday_plan_main
from .intraday_saved_comparison_cli import add_intraday_saved_comparison_subparser, research_intraday_saved_comparison_main
from .intraday_execution_scenarios_cli import add_intraday_execution_scenarios_subparsers, research_intraday_execution_scenarios_main
from .intraday_final_cli import add_intraday_final_subparsers, research_intraday_final_main
from .feature_research_cli import (
    add_feature_research_subparser,
    research_feature_report_main,
)
from .feature_selection_cli import (
    add_feature_selection_subparser,
    research_feature_select_main,
)
from .feature_stability_cli import (
    add_feature_stability_subparser,
    research_feature_stability_main,
)
from .ridge_cli import add_ridge_subparser, research_ridge_main
from .ridge_final_cli import (
    add_ridge_final_subparser,
    research_ridge_final_main,
)
from .ridge_final_evaluation_cli import (
    add_ridge_final_evaluation_subparser,
    research_ridge_final_evaluation_main,
)
from .ridge_final_evaluation_artifact_cli import (
    add_ridge_final_evaluation_artifact_subparser,
    research_ridge_final_evaluation_artifact_main,
)
from .ridge_trading_selection_cli import (
    add_ridge_trading_selection_subparser,
    research_ridge_trading_select_main,
)
from .ridge_final_trading_cli import (
    add_ridge_final_trading_subparser,
    research_ridge_final_trading_main,
)
from .ridge_selected_final_trading_cli import (
    add_ridge_selected_final_trading_subparser,
    research_ridge_selected_final_trading_main,
)
from .walk_forward_cli import (
    add_walk_forward_subparser,
    research_walk_forward_main,
)
from .canonical.reader import load_verified_canonical_build
from .cross_day import TradingDayRecord, verify_trading_day_schedule
from .cross_day_dataset import CrossDayAnchor
from .dataset.cli import (
    DatasetCLIError,
    _coerce_plan_path,
    _no_duplicate_pairs,
    _parse_scope,
    _parse_split_spec,
    _read_plan_bytes,
    _read_spec_text,
    _require_date,
    _require_datetime,
    _require_exact_fields,
    _require_nullable_datetime,
    _require_object,
    _require_string,
    _require_string_array,
    _resolve_plan_path,
    _to_scope,
    _to_split_spec,
    _verify_regular_file,
)
from .dataset.encoding import DatasetError
from .dataset.specs import parse_feature_spec, parse_label_spec
from .multi_source.feature_specs import parse_observation_feature_spec
from .observation._validation import ObservationError
from .observation.reader import load_verified_observation_build
from .research_dataset import build_research_dataset


RESEARCH_COMMANDS = frozenset({
    "research-intraday-freeze", "research-intraday-test",
    "research-intraday-plan", "research-intraday-compare", "research-intraday-diagnose",
    "research-intraday-performance",
    "research-intraday-risk-diagnostics",
    "research-intraday-parameter-grid",
    "research-intraday-return-uncertainty",
    "research-intraday-plan-from-candidate",
    "research-intraday-compare-saved",
    "research-intraday-scenarios", "research-intraday-export-scenario",
    "research-intraday-backtest",
    "research-intraday-build",
    "research-intraday-inspect",
    "research-build",
    "research-backtest",
    "research-compare-strategies",
    "research-experiment-open",
    "research-experiment-replay",
    "research-diagnose-strategy",
    "research-feature-report",
    "research-feature-select",
    "research-feature-stability",
    "research-ridge",
    "research-ridge-final",
    "research-ridge-final-evaluation",
    "research-ridge-final-evaluation-artifact",
    "research-ridge-final-trading",
    "research-ridge-selected-final-trading",
    "research-ridge-trading-select",
    "research-walk-forward",
})
RESEARCH_BUILD_PLAN_SCHEMA_VERSION = "market-vault-research-build-plan-v1"
RESEARCH_CLI_RESULT_SCHEMA_VERSION = "market-vault-research-cli-result-v1"


class ResearchCLIError(Exception):
    """Documented user/input failure of the Research CLI layer."""


_PLAN_FIELDS = frozenset({
    "plan_schema_version",
    "feature_build_dirs",
    "label_build_dirs",
    "observation_build_dirs",
    "ts2_feature_spec_files",
    "observation_feature_spec_files",
    "label_spec_files",
    "schedule",
    "scope",
    "split_spec",
    "anchors",
    "feature_window_bars",
    "dataset_as_of",
    "output_root",
    "built_at",
})
_ANCHOR_FIELDS = frozenset({"code", "market_calendar_date", "anchor_slot"})
_SCHEDULE_FIELDS = frozenset({
    "schedule_schema_version",
    "market",
    "requested_session",
    "market_timezone",
    "coverage_start_date",
    "coverage_end_date",
    "daily_records",
    "source_snapshot_id",
    "source_content_hash",
    "calendar_contract_version",
    "normalization_version",
    "coverage_completion_evidence_id",
    "coverage_complete",
    "archive_available_at",
})
_DAY_FIELDS = frozenset({
    "market_calendar_date",
    "day_status",
    "session_open",
    "session_close",
    "session_profile",
})
_DOCUMENTED_ERRORS = (
    ResearchCLIError,
    DatasetCLIError,
    DatasetError,
    ObservationError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)


def add_research_subparsers(subparsers) -> None:
    build = subparsers.add_parser(
        "research-build",
        help="Build one PIT-safe research Dataset from an explicit research plan",
    )
    build.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to market-vault-research-build-plan-v1 JSON",
    )
    add_backtest_subparser(subparsers)
    add_strategy_comparison_subparser(subparsers)
    add_strategy_experiment_subparsers(subparsers)
    add_strategy_diagnostics_subparser(subparsers)
    add_intraday_data_subparsers(subparsers)
    add_intraday_backtest_subparser(subparsers)
    add_intraday_research_subparsers(subparsers)
    add_intraday_performance_subparser(subparsers)
    add_intraday_risk_diagnostics_subparser(subparsers)
    add_intraday_parameter_grid_subparser(subparsers)
    add_intraday_return_uncertainty_subparser(subparsers)
    add_intraday_plan_subparser(subparsers)
    add_intraday_saved_comparison_subparser(subparsers)
    add_intraday_execution_scenarios_subparsers(subparsers)
    add_intraday_final_subparsers(subparsers)
    add_feature_research_subparser(subparsers)
    add_feature_selection_subparser(subparsers)
    add_feature_stability_subparser(subparsers)
    add_ridge_subparser(subparsers)
    add_ridge_final_subparser(subparsers)
    add_ridge_final_evaluation_subparser(subparsers)
    add_ridge_final_evaluation_artifact_subparser(subparsers)
    add_ridge_final_trading_subparser(subparsers)
    add_ridge_selected_final_trading_subparser(subparsers)
    add_ridge_trading_selection_subparser(subparsers)
    add_walk_forward_subparser(subparsers)


def run_research_command(command: str, args: argparse.Namespace) -> int:
    if command in ("research-intraday-scenarios", "research-intraday-export-scenario"):
        return research_intraday_execution_scenarios_main(args, command=command)
    if command == "research-intraday-performance":
        return research_intraday_performance_main(args)
    if command == "research-intraday-risk-diagnostics":
        return research_intraday_risk_diagnostics_main(args)
    if command == "research-intraday-parameter-grid":
        return research_intraday_parameter_grid_main(args)
    if command == "research-intraday-return-uncertainty":
        return research_intraday_return_uncertainty_main(args)
    if command == "research-intraday-plan-from-candidate":
        return research_intraday_plan_main(args)
    if command == "research-intraday-compare-saved":
        return research_intraday_saved_comparison_main(args)
    if command in ("research-intraday-freeze", "research-intraday-test"):
        return research_intraday_final_main(args, command=command)
    if command in ("research-intraday-plan", "research-intraday-compare", "research-intraday-diagnose"):
        return research_intraday_research_main(args, command=command)
    if command == "research-intraday-backtest":
        return research_intraday_backtest_main(args)
    if command in ("research-intraday-build", "research-intraday-inspect"):
        return research_intraday_data_main(args, inspect=command == "research-intraday-inspect")
    if command == "research-build":
        return research_build_main(args)
    if command == "research-backtest":
        return research_backtest_main(args)
    if command == "research-compare-strategies":
        return research_compare_strategies_main(args)
    if command in ("research-experiment-open", "research-experiment-replay"):
        return research_experiment_main(args, replay=command == "research-experiment-replay")
    if command == "research-diagnose-strategy":
        return research_diagnose_strategy_main(args)
    if command == "research-feature-report":
        return research_feature_report_main(args)
    if command == "research-feature-select":
        return research_feature_select_main(args)
    if command == "research-feature-stability":
        return research_feature_stability_main(args)
    if command == "research-ridge":
        return research_ridge_main(args)
    if command == "research-ridge-final":
        return research_ridge_final_main(args)
    if command == "research-ridge-final-evaluation":
        return research_ridge_final_evaluation_main(args)
    if command == "research-ridge-final-evaluation-artifact":
        return research_ridge_final_evaluation_artifact_main(args)
    if command == "research-ridge-final-trading":
        return research_ridge_final_trading_main(args)
    if command == "research-ridge-selected-final-trading":
        return research_ridge_selected_final_trading_main(args)
    if command == "research-ridge-trading-select":
        return research_ridge_trading_select_main(args)
    if command == "research-walk-forward":
        return research_walk_forward_main(args)
    raise AssertionError(f"unknown Research command {command!r}")


def _research_error(exc, context: str):
    if isinstance(exc, ResearchCLIError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise ResearchCLIError(f"{context}: {exc}") from exc
    raise exc


def _positive_int(value, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ResearchCLIError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ResearchCLIError(f"{label} must be a non-negative integer")
    return value


def _paths(value, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    try:
        return _require_string_array(value, label, allow_empty=allow_empty)
    except DatasetCLIError as exc:
        raise ResearchCLIError(str(exc)) from exc


def _nullable_string(value, label: str) -> str | None:
    if value is None:
        return None
    try:
        return _require_string(value, label)
    except DatasetCLIError as exc:
        raise ResearchCLIError(str(exc)) from exc


def _parse_anchor(value) -> CrossDayAnchor:
    try:
        mapping = _require_object(value, "anchor")
        _require_exact_fields(mapping, _ANCHOR_FIELDS, "anchor")
        return CrossDayAnchor(
            _require_string(mapping["code"], "anchor code"),
            _require_date(
                mapping["market_calendar_date"], "anchor market_calendar_date"
            ),
            _non_negative_int(mapping["anchor_slot"], "anchor_slot"),
        )
    except DatasetCLIError as exc:
        raise ResearchCLIError(str(exc)) from exc


def _parse_schedule(value, *, dataset_as_of):
    try:
        mapping = _require_object(value, "schedule")
        _require_exact_fields(mapping, _SCHEDULE_FIELDS, "schedule")
        raw_days = mapping["daily_records"]
        if type(raw_days) is not list or not raw_days:
            raise ResearchCLIError(
                "schedule daily_records must be a non-empty JSON array"
            )
        days = []
        for raw in raw_days:
            day = _require_object(raw, "schedule daily record")
            _require_exact_fields(day, _DAY_FIELDS, "schedule daily record")
            days.append(TradingDayRecord(
                _require_date(
                    day["market_calendar_date"],
                    "schedule record market_calendar_date",
                ),
                _require_string(day["day_status"], "schedule record day_status"),
                _require_nullable_datetime(
                    day["session_open"], "schedule record session_open"
                ),
                _require_nullable_datetime(
                    day["session_close"], "schedule record session_close"
                ),
                _nullable_string(
                    day["session_profile"], "schedule record session_profile"
                ),
            ))
        if type(mapping["coverage_complete"]) is not bool:
            raise ResearchCLIError(
                "schedule coverage_complete must be a boolean"
            )
        return verify_trading_day_schedule(
            dataset_as_of=dataset_as_of,
            schedule_schema_version=_require_string(
                mapping["schedule_schema_version"], "schedule_schema_version"
            ),
            market=_require_string(mapping["market"], "schedule market"),
            requested_session=_require_string(
                mapping["requested_session"], "schedule requested_session"
            ),
            market_timezone=_require_string(
                mapping["market_timezone"], "schedule market_timezone"
            ),
            coverage_start_date=_require_date(
                mapping["coverage_start_date"], "schedule coverage_start_date"
            ),
            coverage_end_date=_require_date(
                mapping["coverage_end_date"], "schedule coverage_end_date"
            ),
            daily_records=tuple(days),
            source_snapshot_id=_require_string(
                mapping["source_snapshot_id"], "schedule source_snapshot_id"
            ),
            source_content_hash=_require_string(
                mapping["source_content_hash"], "schedule source_content_hash"
            ),
            calendar_contract_version=_require_string(
                mapping["calendar_contract_version"],
                "schedule calendar_contract_version",
            ),
            normalization_version=_require_string(
                mapping["normalization_version"],
                "schedule normalization_version",
            ),
            coverage_completion_evidence_id=_require_string(
                mapping["coverage_completion_evidence_id"],
                "schedule coverage_completion_evidence_id",
            ),
            coverage_complete=mapping["coverage_complete"],
            archive_available_at=_require_datetime(
                mapping["archive_available_at"],
                "schedule archive_available_at",
            ),
        )
    except DatasetCLIError as exc:
        raise ResearchCLIError(str(exc)) from exc


def parse_research_plan_bytes(payload: bytes):
    if payload.startswith(codecs.BOM_UTF8):
        raise ResearchCLIError("research plan must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchCLIError(
            f"research plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        root = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except DatasetCLIError as exc:
        raise ResearchCLIError(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ResearchCLIError(
            f"research plan is not valid JSON: {exc}"
        ) from exc

    try:
        root = _require_object(root, "research plan root")
        _require_exact_fields(root, _PLAN_FIELDS, "research plan root")
        version = _require_string(
            root["plan_schema_version"], "plan_schema_version"
        )
        if version != RESEARCH_BUILD_PLAN_SCHEMA_VERSION:
            raise ResearchCLIError(
                f"unsupported plan_schema_version {version!r}; only "
                f"{RESEARCH_BUILD_PLAN_SCHEMA_VERSION!r} is accepted"
            )
        dataset_as_of = _require_nullable_datetime(
            root["dataset_as_of"], "dataset_as_of"
        )
        ts2_files = _paths(
            root["ts2_feature_spec_files"],
            "ts2_feature_spec_files",
            allow_empty=True,
        )
        observation_files = _paths(
            root["observation_feature_spec_files"],
            "observation_feature_spec_files",
            allow_empty=True,
        )
        if not ts2_files and not observation_files:
            raise ResearchCLIError(
                "at least one TS2 or Observation Feature spec is required"
            )
        anchors_raw = root["anchors"]
        if type(anchors_raw) is not list or not anchors_raw:
            raise ResearchCLIError("anchors must be a non-empty JSON array")
        return SimpleNamespace(
            plan_schema_version=version,
            feature_build_dirs=_paths(
                root["feature_build_dirs"], "feature_build_dirs"
            ),
            label_build_dirs=_paths(
                root["label_build_dirs"], "label_build_dirs"
            ),
            observation_build_dirs=_paths(
                root["observation_build_dirs"],
                "observation_build_dirs",
                allow_empty=True,
            ),
            ts2_feature_spec_files=ts2_files,
            observation_feature_spec_files=observation_files,
            label_spec_files=_paths(
                root["label_spec_files"], "label_spec_files"
            ),
            schedule=_parse_schedule(
                root["schedule"], dataset_as_of=dataset_as_of
            ),
            scope=_to_scope(_parse_scope(root["scope"])),
            split_spec=_to_split_spec(_parse_split_spec(root["split_spec"])),
            anchors=tuple(_parse_anchor(item) for item in anchors_raw),
            feature_window_bars=_positive_int(
                root["feature_window_bars"], "feature_window_bars"
            ),
            dataset_as_of=dataset_as_of,
            output_root=_require_string(
                root["output_root"], "output_root"
            ),
            built_at=_require_datetime(root["built_at"], "built_at"),
        )
    except DatasetCLIError as exc:
        raise ResearchCLIError(str(exc)) from exc


def _spec(path_text: str, *, base: Path, label: str, parser):
    path = _resolve_plan_path(path_text, base=base, label=label)
    _verify_regular_file(path, label)
    return parser(_read_spec_text(path, label))


def _build_from_plan(plan, plan_parent: Path):
    feature_builds = tuple(
        load_verified_canonical_build(
            _resolve_plan_path(
                raw, base=plan_parent, label="feature Canonical build"
            )
        )
        for raw in plan.feature_build_dirs
    )
    label_builds = tuple(
        load_verified_canonical_build(
            _resolve_plan_path(
                raw, base=plan_parent, label="label Canonical build"
            )
        )
        for raw in plan.label_build_dirs
    )
    observation_builds = tuple(
        load_verified_observation_build(
            _resolve_plan_path(
                raw, base=plan_parent, label="Observation build"
            )
        )
        for raw in plan.observation_build_dirs
    )
    ts2_specs = tuple(
        _spec(
            raw,
            base=plan_parent,
            label="TS2 Feature spec",
            parser=parse_feature_spec,
        )
        for raw in plan.ts2_feature_spec_files
    )
    observation_specs = tuple(
        _spec(
            raw,
            base=plan_parent,
            label="Observation Feature spec",
            parser=parse_observation_feature_spec,
        )
        for raw in plan.observation_feature_spec_files
    )
    label_specs = tuple(
        _spec(
            raw,
            base=plan_parent,
            label="Label spec",
            parser=parse_label_spec,
        )
        for raw in plan.label_spec_files
    )
    return build_research_dataset(
        feature_builds=feature_builds,
        label_builds=label_builds,
        observation_builds=observation_builds,
        schedule=plan.schedule,
        scope=plan.scope,
        split_spec=plan.split_spec,
        anchors=plan.anchors,
        ts2_feature_specs=ts2_specs,
        observation_feature_specs=observation_specs,
        label_specs=label_specs,
        feature_window_bars=plan.feature_window_bars,
        dataset_as_of=plan.dataset_as_of,
        output_root=_resolve_plan_path(
            plan.output_root,
            base=plan_parent,
            label="research output root",
        ),
        built_at=plan.built_at,
    )


def _success_payload(result) -> dict:
    verified = result.verified
    assignments = verified.split_result.assignments
    split_counts = {
        name: sum(
            a.assignment_status == "ASSIGNED" and a.final_split == name
            for a in assignments
        )
        for name in ("TRAIN", "VALIDATION", "TEST")
    }
    split_counts["PURGED"] = sum(
        a.assignment_status == "PURGED" for a in assignments
    )
    split_counts["EXCLUDED"] = sum(
        a.assignment_status == "EXCLUDED" for a in assignments
    )
    return {
        "result_schema_version": RESEARCH_CLI_RESULT_SCHEMA_VERSION,
        "status": "SUCCESS",
        "dataset_id": verified.dataset_id,
        "dataset_status": verified.status,
        "created_new_build": result.created_new_build,
        "build_path": str(verified.build_path),
        "row_count": len(verified.rows),
        "feature_count": (
            len(verified.ts2_features.feature_specs)
            + len(verified.observation_features.feature_spec_pins)
        ),
        "label_count": len(verified.cross_day_labels.label_specs),
        "split_counts": split_counts,
        "completion": {
            "complete": verified.completion.complete_count,
            "incomplete": verified.completion.incomplete_count,
            "missing": verified.completion.missing_count,
        },
    }


def research_build_main(args: argparse.Namespace) -> int:
    try:
        plan_path = _coerce_plan_path(args.plan)
        plan = parse_research_plan_bytes(_read_plan_bytes(plan_path))
        result = _build_from_plan(plan, plan_path.parent)
        print(json.dumps(
            _success_payload(result),
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except _DOCUMENTED_ERRORS as exc:
        try:
            _research_error(exc, "research-build failed")
        except ResearchCLIError as failure:
            payload = {
                "result_schema_version": RESEARCH_CLI_RESULT_SCHEMA_VERSION,
                "status": "FAILED",
                "error": str(failure),
            }
            print(
                json.dumps(payload, ensure_ascii=False, indent=2),
                file=sys.stderr,
            )
            return 1
