"""Deterministic Dataset CLI commands (v0.5.0 PR-8).

This module implements the three formal Dataset commands — ``dataset-build``,
``dataset-verify``, and ``dataset-inspect`` — as a thin wrapper over the
already-merged formal public chain:

``load_verified_canonical_build`` -> ``parse_feature_spec`` /
``parse_label_spec`` -> ``ChronologicalSplitSpec`` / ``PITSampleRequest`` /
``DatasetScope`` typed construction -> ``dataset_orchestration_schema`` ->
``orchestrate_dataset_build`` -> ``materialize_dataset_artifacts`` ->
``load_verified_dataset``.

The CLI is never a second Dataset builder, never a second Dataset validator,
and never a second Canonical validator: every layer runs exactly once
through its existing public entry, every artifact is written only by the
materializer, and every read of a committed Dataset goes through the
verified reader.

``dataset-build`` accepts only ``--plan <PATH>``: every formal fact comes
from one explicit, versioned build-plan JSON document (strict UTF-8 without
BOM, duplicate keys / unknown fields / missing fields / wrong types / null
in disallowed fields all fail closed; JSON whitespace and key order never
matter and the plan bytes never enter any Dataset identity). Inner paths
are absolute or strictly relative to the plan file's parent directory;
``.`` / ``..`` components, symlinks, and Windows junctions fail closed;
``~``, environment variables, globs, and directory scanning are never
expanded or performed. ``built_at`` and ``dataset_as_of`` must be
timezone-aware; the system local timezone and ``datetime.now`` are never
used. Canonical build directories are handed to
``load_verified_canonical_build`` and ``output_root`` to
``materialize_dataset_artifacts`` for their own formal safety validation.

``dataset-verify`` and ``dataset-inspect`` accept only an explicit final
Dataset directory and call ``load_verified_dataset`` exactly once; they
never write, repair, or delete anything, never load ``settings.yaml``,
never connect to OpenD, and never access the network.

All three commands produce deterministic JSON: exactly one success object
on stdout and exit 0, or exactly one FAILED object on stderr and exit 1.
Argparse usage errors keep the standard argparse stderr and exit code 2;
real programming errors are never caught. Every documented failure of the
formal layers is converted to :class:`DatasetCLIError` with the
``__cause__`` preserved and never double-wrapped; broad ``except Exception``
is never used.
"""

from __future__ import annotations

import argparse
import codecs
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from ..canonical.reader import load_verified_canonical_build
from .cli_models import (
    DATASET_BUILD_PLAN_SCHEMA_VERSION,
    DATASET_CLI_CONTRACT_VERSION,
    DATASET_CLI_RESULT_SCHEMA_VERSION,
    BuildPlan,
    DatasetCLIError,
    PlanRequest,
    PlanScope,
    PlanSplitSpec,
)
from .encoding import DatasetError, normalize_utc_datetime
from .materialization import _is_junction_or_reparse, materialize_dataset_artifacts
from .materialization_models import DatasetMaterializationResult
from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    DatasetScope,
)
from .orchestration import orchestrate_dataset_build
from .orchestration_models import (
    DATASET_KIND_SUPERVISED,
    dataset_orchestration_schema,
)
from .pit_models import PITSampleRequest
from .reader import load_verified_dataset
from .reader_models import DATASET_READER_CONTRACT_VERSION, VerifiedDatasetBuild
from .specs import feature_label_spec_pin, parse_feature_spec, parse_label_spec
from .split_models import ChronologicalSplitSpec, chronological_split_spec_pin

__all__ = [
    "DATASET_COMMANDS",
    "add_dataset_subparsers",
    "run_dataset_command",
]

#: The three Dataset commands dispatched before ``load_settings``.
DATASET_COMMANDS = frozenset({"dataset-build", "dataset-verify", "dataset-inspect"})

#: The exact root field set of one strict build-plan JSON document.
_PLAN_ROOT_FIELDS = frozenset(
    {
        "plan_schema_version",
        "canonical_build_dirs",
        "feature_spec_files",
        "label_spec_files",
        "requests",
        "scope",
        "split_spec",
        "dataset_as_of",
        "output_root",
        "built_at",
    }
)

#: The exact field set of one request object.
_REQUEST_FIELDS = frozenset(
    {
        "code",
        "interval",
        "adjustment",
        "requested_session",
        "anchor_market_calendar_date",
        "feature_window_start",
        "feature_window_close",
        "label_window_start",
        "label_window_close",
    }
)

#: The exact field set of the scope object.
_SCOPE_FIELDS = frozenset(
    {"symbols", "trade_dates", "interval", "adjustment", "requested_session"}
)

#: The exact field set of the split_spec object.
_SPLIT_FIELDS = frozenset(
    {
        "spec_schema_version",
        "name",
        "version",
        "boundary_timezone",
        "train_end_date",
        "validation_end_date",
        "test_end_date",
        "assignment_rule",
        "purge_rule",
        "incomplete_label_policy",
        "out_of_range_policy",
    }
)

_STRICT_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Documented failures converted to :class:`DatasetCLIError` at the command
#: boundary (``json.JSONDecodeError`` is a ``ValueError`` subclass and is
#: listed explicitly for contract clarity). Broad ``except Exception`` is
#: never used.
_DOCUMENTED_ERRORS = (
    DatasetError,
    OSError,
    UnicodeError,
    json.JSONDecodeError,
    TypeError,
    ValueError,
    KeyError,
)


# ---------------------------------------------------------------------------
# Parser wiring (subcommands are added to the shared argparse tree).
# ---------------------------------------------------------------------------


def _non_negative_int_arg(value: str) -> int:
    """Argparse type for ``--offset``: real non-negative int, else code 2."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Value must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be a non-negative integer")
    return parsed


def _limit_arg(value: str) -> int:
    """Argparse type for ``--limit``: non-negative int capped at 1000.

    ``limit == 0`` is legal (returns empty rows); ``limit > 1000`` fails at
    the argparse stage with the standard exit code 2.
    """
    parsed = _non_negative_int_arg(value)
    if parsed > 1000:
        raise argparse.ArgumentTypeError("Value must not exceed 1000")
    return parsed


def add_dataset_subparsers(subparsers) -> None:
    """Add the three Dataset subparsers to the shared argparse tree."""
    build = subparsers.add_parser(
        "dataset-build",
        help="Build one immutable Dataset from an explicit versioned build plan",
    )
    build.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to the versioned Dataset build-plan JSON; all Dataset "
        "build inputs are declared in the plan",
    )
    verify = subparsers.add_parser(
        "dataset-verify",
        help="Verify one committed immutable Dataset build directory",
    )
    verify.add_argument(
        "--build-dir",
        required=True,
        metavar="PATH",
        help="Explicit final Dataset build directory "
        "(<output_root>/<dataset_id>)",
    )
    inspect = subparsers.add_parser(
        "dataset-inspect",
        help="Inspect one verified immutable Dataset build directory",
    )
    inspect.add_argument(
        "--build-dir",
        required=True,
        metavar="PATH",
        help="Explicit final Dataset build directory "
        "(<output_root>/<dataset_id>)",
    )
    inspect.add_argument(
        "--offset",
        type=_non_negative_int_arg,
        default=0,
        metavar="N",
        help="Zero-based row offset (default 0; rows are sliced, never "
        "reordered)",
    )
    inspect.add_argument(
        "--limit",
        type=_limit_arg,
        default=20,
        metavar="N",
        help="Maximum rows to return (default 20, max 1000; 0 returns no rows)",
    )


def run_dataset_command(command: str, args: argparse.Namespace) -> int:
    """Dispatch one Dataset CLI command.

    Called from the shared ``main()`` before ``load_settings`` so the
    Dataset commands never load ``settings.yaml``, never connect to OpenD,
    and never access the network. Returns the process exit code.
    """
    if command == "dataset-build":
        return dataset_build_main(args)
    if command == "dataset-verify":
        return dataset_verify_main(args)
    if command == "dataset-inspect":
        return dataset_inspect_main(args)
    raise AssertionError(f"unknown Dataset CLI command {command!r}")


# ---------------------------------------------------------------------------
# Unified documented error boundary.
# ---------------------------------------------------------------------------


def _as_cli_error(exc, context: str) -> None:
    """Convert a documented failure to :class:`DatasetCLIError`.

    An already-raised :class:`DatasetCLIError` passes through unchanged
    (never double-wrapped); the contract-listed exceptions (``DatasetError``
    and its subclasses, Canonical verification errors, ``OSError``,
    ``UnicodeError``, ``json.JSONDecodeError``, and the documented
    ``TypeError`` / ``ValueError`` / ``KeyError``) are converted with a
    context prefix and their ``__cause__`` preserved. Broad ``except
    Exception`` is never used: real programming errors are not disguised as
    user input errors.
    """
    if isinstance(exc, DatasetCLIError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise DatasetCLIError(f"{context}: {exc}") from exc
    raise exc


# ---------------------------------------------------------------------------
# Strict build-plan JSON parsing.
# ---------------------------------------------------------------------------


def _no_duplicate_pairs(pairs) -> dict:
    """``object_pairs_hook`` rejecting duplicate JSON keys at any depth."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise DatasetCLIError(f"duplicate JSON key {key!r} in build plan")
        result[key] = value
    return result


def _require_string(value, label: str) -> str:
    if not isinstance(value, str):
        raise DatasetCLIError(f"{label} must be a string, got {type(value).__name__}")
    if not value.strip():
        raise DatasetCLIError(f"{label} must not be empty")
    if value != value.strip():
        raise DatasetCLIError(
            f"{label} must not have leading or trailing whitespace"
        )
    return value


def _require_exact_fields(mapping: dict, allowed: frozenset, path: str) -> None:
    unknown = sorted(key for key in mapping if key not in allowed)
    if unknown:
        raise DatasetCLIError(
            f"unknown field(s) at {path}: {', '.join(unknown)}"
        )
    missing = sorted(allowed - set(mapping))
    if missing:
        raise DatasetCLIError(
            f"missing required field(s) at {path}: {', '.join(missing)}"
        )


def _require_object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise DatasetCLIError(
            f"{label} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _require_string_array(value, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DatasetCLIError(
            f"{label} must be a JSON array, got {type(value).__name__}"
        )
    items: list[str] = []
    for item in value:
        items.append(_require_string(item, f"{label} entry"))
    if not items and not allow_empty:
        raise DatasetCLIError(f"{label} must not be empty")
    if len(set(items)) != len(items):
        raise DatasetCLIError(f"{label} must not contain duplicates")
    return tuple(items)


def _require_path_array(value, label: str) -> tuple[str, ...]:
    return _require_string_array(value, label)


def _require_date(value, label: str) -> date:
    text = _require_string(value, label)
    if not _STRICT_ISO_DATE_RE.fullmatch(text):
        raise DatasetCLIError(
            f"{label} must be a strict ISO YYYY-MM-DD string, got {value!r}"
        )
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DatasetCLIError(
            f"{label} must be a valid calendar date, got {value!r}"
        ) from exc


def _require_datetime(value, label: str) -> datetime:
    """Timezone-aware ISO datetime, normalized to UTC microseconds.

    Naive datetimes are rejected; the system local timezone is never used.
    """
    text = _require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DatasetCLIError(
            f"{label} must be an ISO 8601 datetime, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise DatasetCLIError(
            f"{label} must be timezone-aware, got a naive value {value!r}"
        )
    try:
        return normalize_utc_datetime(parsed, label)
    except DatasetError as exc:
        raise DatasetCLIError(f"{label}: {exc}") from exc


def _require_nullable_datetime(value, label: str) -> datetime | None:
    if value is None:
        return None
    return _require_datetime(value, label)


def _parse_request(value) -> PlanRequest:
    mapping = _require_object(value, "request")
    _require_exact_fields(mapping, _REQUEST_FIELDS, "request")
    label_start = mapping["label_window_start"]
    label_close = mapping["label_window_close"]
    if (label_start is None) != (label_close is None):
        raise DatasetCLIError(
            "request label_window_start and label_window_close must both be "
            "null or both be timezone-aware ISO datetime strings"
        )
    return PlanRequest(
        code=_require_string(mapping["code"], "request code"),
        interval=_require_string(mapping["interval"], "request interval"),
        adjustment=_require_string(mapping["adjustment"], "request adjustment"),
        requested_session=_require_string(
            mapping["requested_session"], "request requested_session"
        ),
        anchor_market_calendar_date=_require_date(
            mapping["anchor_market_calendar_date"],
            "request anchor_market_calendar_date",
        ),
        feature_window_start=_require_datetime(
            mapping["feature_window_start"], "request feature_window_start"
        ),
        feature_window_close=_require_datetime(
            mapping["feature_window_close"], "request feature_window_close"
        ),
        label_window_start=(
            _require_datetime(label_start, "request label_window_start")
            if label_start is not None
            else None
        ),
        label_window_close=(
            _require_datetime(label_close, "request label_window_close")
            if label_close is not None
            else None
        ),
    )


def _parse_scope(value) -> PlanScope:
    mapping = _require_object(value, "scope")
    _require_exact_fields(mapping, _SCOPE_FIELDS, "scope")
    trade_dates = _require_string_array(mapping["trade_dates"], "scope trade_dates")
    for trade_date in trade_dates:
        _require_date(trade_date, "scope trade_dates entry")
    return PlanScope(
        symbols=_require_string_array(mapping["symbols"], "scope symbols"),
        trade_dates=trade_dates,
        interval=_require_string(mapping["interval"], "scope interval"),
        adjustment=_require_string(mapping["adjustment"], "scope adjustment"),
        requested_session=_require_string(
            mapping["requested_session"], "scope requested_session"
        ),
    )


def _parse_split_spec(value) -> PlanSplitSpec:
    mapping = _require_object(value, "split_spec")
    _require_exact_fields(mapping, _SPLIT_FIELDS, "split_spec")
    return PlanSplitSpec(
        spec_schema_version=_require_string(
            mapping["spec_schema_version"], "split_spec spec_schema_version"
        ),
        name=_require_string(mapping["name"], "split_spec name"),
        version=_require_string(mapping["version"], "split_spec version"),
        boundary_timezone=_require_string(
            mapping["boundary_timezone"], "split_spec boundary_timezone"
        ),
        train_end_date=_require_date(
            mapping["train_end_date"], "split_spec train_end_date"
        ),
        validation_end_date=_require_date(
            mapping["validation_end_date"], "split_spec validation_end_date"
        ),
        test_end_date=_require_date(
            mapping["test_end_date"], "split_spec test_end_date"
        ),
        assignment_rule=_require_string(
            mapping["assignment_rule"], "split_spec assignment_rule"
        ),
        purge_rule=_require_string(
            mapping["purge_rule"], "split_spec purge_rule"
        ),
        incomplete_label_policy=_require_string(
            mapping["incomplete_label_policy"], "split_spec incomplete_label_policy"
        ),
        out_of_range_policy=_require_string(
            mapping["out_of_range_policy"], "split_spec out_of_range_policy"
        ),
    )


def parse_build_plan_bytes(payload: bytes) -> BuildPlan:
    """Strictly parse one build-plan JSON document into a frozen
    :class:`BuildPlan`.

    The document must be UTF-8 without BOM and a single JSON object;
    duplicate JSON keys are rejected through ``object_pairs_hook``; unknown
    and missing fields fail at every level; bools never substitute for ints
    and strings never substitute for arrays; ``null`` is rejected in every
    field that does not accept it. JSON whitespace and key order never
    matter, no canonical JSON form is required, and the raw plan bytes
    never enter any Dataset identity.
    """
    if payload.startswith(codecs.BOM_UTF8):
        raise DatasetCLIError("build plan must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetCLIError(f"build plan is not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except json.JSONDecodeError as exc:
        raise DatasetCLIError(f"build plan is not valid JSON: {exc}") from exc
    root = _require_object(data, "build plan root")
    _require_exact_fields(root, _PLAN_ROOT_FIELDS, "build plan root")
    plan_schema_version = _require_string(
        root["plan_schema_version"], "plan_schema_version"
    )
    if plan_schema_version != DATASET_BUILD_PLAN_SCHEMA_VERSION:
        raise DatasetCLIError(
            f"unsupported plan_schema_version {plan_schema_version!r}; only "
            f"{DATASET_BUILD_PLAN_SCHEMA_VERSION} is accepted"
        )
    requests = root["requests"]
    if not isinstance(requests, list):
        raise DatasetCLIError(
            f"requests must be a JSON array, got {type(requests).__name__}"
        )
    return BuildPlan(
        plan_schema_version=plan_schema_version,
        canonical_build_dirs=_require_path_array(
            root["canonical_build_dirs"], "canonical_build_dirs"
        ),
        feature_spec_files=_require_path_array(
            root["feature_spec_files"], "feature_spec_files"
        ),
        label_spec_files=_require_path_array(
            root["label_spec_files"], "label_spec_files"
        ),
        requests=tuple(_parse_request(item) for item in requests),
        scope=_parse_scope(root["scope"]),
        split_spec=_parse_split_spec(root["split_spec"]),
        dataset_as_of=_require_nullable_datetime(
            root["dataset_as_of"], "dataset_as_of"
        ),
        output_root=_require_string(root["output_root"], "output_root"),
        built_at=_require_datetime(root["built_at"], "built_at"),
    )


# ---------------------------------------------------------------------------
# Path and link safety.
# ---------------------------------------------------------------------------


def _reject_dot_components(raw_text: str, label: str) -> None:
    """Reject any lexical ``.`` / ``..`` component on the raw string.

    Checked on both separators before :class:`pathlib.Path` construction,
    because pathlib itself strips ``.`` components during parsing and a
    lexical ``.`` / ``..`` component must never survive into a verified
    path.
    """
    for part in raw_text.replace("\\", "/").split("/"):
        if part in (".", ".."):
            raise DatasetCLIError(
                f"{label} must not contain '.' or '..' path components: "
                f"{raw_text!r}"
            )


def _reject_link(path: Path, label: str) -> None:
    if path.is_symlink() or _is_junction_or_reparse(path):
        raise DatasetCLIError(
            f"{label} must not be a symlink or junction: {path}"
        )


def _verify_parent_chain(path: Path, label: str) -> None:
    """Every existing parent component must be a regular non-link
    directory (fail closed on links)."""
    for component in (path.parent, *path.parent.parents):
        _reject_link(component, f"{label} parent path component")
        if component.exists() and not component.is_dir():
            raise DatasetCLIError(
                f"{label} parent path component must be a regular directory: "
                f"{component}"
            )


def _resolve_plan_path(raw_text: str, *, base: Path, label: str) -> Path:
    """Raw path -> lexically absolute Path against ``base``.

    ``resolve()`` is never used to mask a link; ``.`` / ``..`` components
    are rejected; ``~``, environment variables, and globs are never
    expanded; no extension is appended. Path normalization only affects the
    access location and never enters any Dataset identity.
    """
    _reject_dot_components(raw_text, label)
    path = Path(raw_text)
    if not path.is_absolute():
        path = base / path
    return path


def _verify_regular_file(path: Path, label: str) -> None:
    """One input must be a regular non-link file under a regular non-link
    parent chain."""
    _verify_parent_chain(path, label)
    _reject_link(path, label)
    if not path.is_file():
        raise DatasetCLIError(f"{label} must be a regular file: {path}")


def _coerce_plan_path(raw_text: str) -> Path:
    """The ``--plan`` path: absolute or relative to the current working
    directory, lexically absolute, a regular non-link file."""
    path = _resolve_plan_path(raw_text, base=Path.cwd(), label="build plan path")
    _verify_regular_file(path, "build plan")
    return path


def _read_plan_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DatasetCLIError(f"cannot read build plan {path}: {exc}") from exc


def _read_spec_text(path: Path, label: str) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise DatasetCLIError(f"{label} is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise DatasetCLIError(f"cannot read {label} {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Typed construction from the parsed plan (existing public models only).
# ---------------------------------------------------------------------------


def _to_pit_request(plan_request: PlanRequest) -> PITSampleRequest:
    return PITSampleRequest(
        code=plan_request.code,
        interval=plan_request.interval,
        adjustment=plan_request.adjustment,
        requested_session=plan_request.requested_session,
        anchor_market_calendar_date=plan_request.anchor_market_calendar_date,
        feature_window_start=plan_request.feature_window_start,
        feature_window_close=plan_request.feature_window_close,
        label_window_start=plan_request.label_window_start,
        label_window_close=plan_request.label_window_close,
    )


def _to_split_spec(plan_split: PlanSplitSpec) -> ChronologicalSplitSpec:
    return ChronologicalSplitSpec(
        spec_schema_version=plan_split.spec_schema_version,
        name=plan_split.name,
        version=plan_split.version,
        boundary_timezone=plan_split.boundary_timezone,
        train_end_date=plan_split.train_end_date,
        validation_end_date=plan_split.validation_end_date,
        test_end_date=plan_split.test_end_date,
        assignment_rule=plan_split.assignment_rule,
        purge_rule=plan_split.purge_rule,
        incomplete_label_policy=plan_split.incomplete_label_policy,
        out_of_range_policy=plan_split.out_of_range_policy,
    )


def _to_scope(plan_scope: PlanScope) -> DatasetScope:
    return DatasetScope(
        symbols=plan_scope.symbols,
        trade_dates=plan_scope.trade_dates,
        interval=plan_scope.interval,
        adjustment=plan_scope.adjustment,
        requested_session=plan_scope.requested_session,
    )


# ---------------------------------------------------------------------------
# dataset-build: the fixed execution chain.
# ---------------------------------------------------------------------------


def _build_from_plan(
    plan: BuildPlan, plan_parent: Path
) -> tuple[DatasetMaterializationResult, VerifiedDatasetBuild]:
    # 1-3. Verified Canonical builds; Feature / Label specs through the
    # existing strict parsers.
    builds = tuple(
        load_verified_canonical_build(
            _resolve_plan_path(
                raw, base=plan_parent, label="canonical build dir"
            )
        )
        for raw in plan.canonical_build_dirs
    )
    feature_specs = tuple(
        parse_feature_spec(
            _read_spec_text(
                _verified_spec_path(raw, plan_parent, "feature spec file"),
                "feature spec file",
            )
        )
        for raw in plan.feature_spec_files
    )
    label_specs = tuple(
        parse_label_spec(
            _read_spec_text(
                _verified_spec_path(raw, plan_parent, "label spec file"),
                "label spec file",
            )
        )
        for raw in plan.label_spec_files
    )

    # 4-7. Typed split spec, requests, scope, and the authoritative schema
    # (never inferred from paths or a second implementation).
    split_spec = _to_split_spec(plan.split_spec)
    requests = tuple(_to_pit_request(item) for item in plan.requests)
    scope = _to_scope(plan.scope)
    schema = dataset_orchestration_schema(
        feature_specs,
        label_specs,
        include_dataset_as_of=plan.dataset_as_of is not None,
    )

    # 8-10. One orchestration, one materialization, one final verified read.
    orchestration = orchestrate_dataset_build(
        builds=builds,
        requests=requests,
        feature_specs=feature_specs,
        label_specs=label_specs,
        split_spec=split_spec,
        scope=scope,
        schema=schema,
        dataset_as_of=plan.dataset_as_of,
        dataset_kind=DATASET_KIND_SUPERVISED,
        manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        serialization_format=SERIALIZATION_FORMAT_PARQUET,
        serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET,
    )
    materialization = materialize_dataset_artifacts(
        orchestration,
        output_root=_resolve_plan_path(
            plan.output_root, base=plan_parent, label="output root"
        ),
        built_at=plan.built_at,
    )
    verified = load_verified_dataset(materialization.build_path)

    # 11. Three-way identity binding: orchestration, materialization, and
    # the verified reader must agree exactly.
    if not (
        orchestration.dataset_id
        == materialization.dataset_id
        == verified.dataset_id
    ):
        raise DatasetCLIError(
            "dataset_id mismatch between the orchestration result, the "
            "materialization result, and the verified Dataset reader"
        )
    if materialization.build_path != verified.build_path:
        raise DatasetCLIError(
            "build_path mismatch between the materialization result and the "
            "verified Dataset reader"
        )
    return materialization, verified


def _verified_spec_path(raw: str, plan_parent: Path, label: str) -> Path:
    path = _resolve_plan_path(raw, base=plan_parent, label=label)
    _verify_regular_file(path, label)
    return path


def _run_dataset_build(plan_arg: str) -> dict:
    """Run the complete build chain; returns the success payload.

    Every documented failure of the plan path, the strict plan parse, or
    the formal build chain is converted to :class:`DatasetCLIError` with
    the ``__cause__`` preserved; real programming errors pass through.
    """
    try:
        plan_path = _coerce_plan_path(plan_arg)
        plan = parse_build_plan_bytes(_read_plan_bytes(plan_path))
        materialization, verified = _build_from_plan(plan, plan_path.parent)
        return _build_success_payload(materialization, verified)
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-build failed")


def _build_success_payload(
    materialization: DatasetMaterializationResult,
    verified: VerifiedDatasetBuild,
) -> dict:
    """The fixed ``dataset-build`` success JSON. Facts come from the final
    verified build (``built_at`` included); ``created_new_build`` is the one
    fact that comes from the materialization result."""
    return {
        "result_schema_version": DATASET_CLI_RESULT_SCHEMA_VERSION,
        "cli_contract_version": DATASET_CLI_CONTRACT_VERSION,
        "command": "dataset-build",
        "result": "SUCCESS",
        "plan_schema_version": DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "created_new_build": materialization.created_new_build,
        "dataset_id": verified.dataset_id,
        "dataset_kind": verified.dataset_kind,
        "dataset_status": verified.status,
        "build_path": verified.build_path.as_posix(),
        "built_at": _iso_utc_micros(verified.built_at),
        "dataset_as_of": (
            _iso_utc_micros(verified.dataset_as_of)
            if verified.dataset_as_of is not None
            else None
        ),
        "dataset_schema_id": verified.manifest.dataset_schema_id,
        "logical_dataset_content_id": verified.manifest.logical_dataset_content_id,
        "logical_row_count": len(verified.rows),
        "feature_spec_count": len(verified.feature_specs),
        "label_spec_count": len(verified.label_specs),
        "split_result_id": verified.split_result.split_result_id,
        "reader_contract_version": DATASET_READER_CONTRACT_VERSION,
    }


def dataset_build_main(args: argparse.Namespace) -> int:
    try:
        payload = _run_dataset_build(args.plan)
    except DatasetCLIError as exc:
        _write_failure("dataset-build", exc)
        return 1
    _write_stdout(payload)
    return 0


# ---------------------------------------------------------------------------
# dataset-verify.
# ---------------------------------------------------------------------------


def _verify_summary(command: str, result: str, verified: VerifiedDatasetBuild) -> dict:
    """The fixed verify summary shared by ``dataset-verify`` and
    ``dataset-inspect`` (never carries rows)."""
    return {
        "result_schema_version": DATASET_CLI_RESULT_SCHEMA_VERSION,
        "cli_contract_version": DATASET_CLI_CONTRACT_VERSION,
        "command": command,
        "result": result,
        "dataset_id": verified.dataset_id,
        "dataset_kind": verified.dataset_kind,
        "dataset_status": verified.status,
        "build_path": verified.build_path.as_posix(),
        "built_at": _iso_utc_micros(verified.built_at),
        "dataset_as_of": (
            _iso_utc_micros(verified.dataset_as_of)
            if verified.dataset_as_of is not None
            else None
        ),
        "dataset_schema_id": verified.manifest.dataset_schema_id,
        "logical_dataset_content_id": verified.manifest.logical_dataset_content_id,
        "logical_row_count": len(verified.rows),
        "feature_spec_count": len(verified.feature_specs),
        "label_spec_count": len(verified.label_specs),
        "split_result_id": verified.split_result.split_result_id,
        "reader_contract_version": DATASET_READER_CONTRACT_VERSION,
    }


def _run_dataset_verify(build_dir: str) -> VerifiedDatasetBuild:
    try:
        return load_verified_dataset(build_dir)
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-verify failed")


def dataset_verify_main(args: argparse.Namespace) -> int:
    try:
        verified = _run_dataset_verify(args.build_dir)
    except DatasetCLIError as exc:
        _write_failure("dataset-verify", exc)
        return 1
    _write_stdout(_verify_summary("dataset-verify", "VERIFIED", verified))
    return 0


# ---------------------------------------------------------------------------
# dataset-inspect.
# ---------------------------------------------------------------------------


def _serialize_scalar(value) -> object:
    """One logical row scalar as a formal JSON scalar.

    Dates serialize as ``YYYY-MM-DD``; datetimes as UTC microsecond ISO
    strings; null stays null; bool / int / float / string stay formal JSON
    scalars. Verified rows never carry NaN / Infinity (the reader's
    identity encoding rejects them), so no special floating-point handling
    exists.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _iso_utc_micros(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    raise DatasetCLIError(
        f"unsupported Dataset row scalar type {type(value).__name__}"
    )


def _row_to_json(row: tuple, schema) -> dict:
    """One Dataset row mapped by schema field order into a JSON object
    (never ``dataclasses.asdict`` recursion, never pandas)."""
    return {
        field.name: _serialize_scalar(value)
        for field, value in zip(schema.fields, row)
    }


def _spec_pin_entry(pin) -> dict:
    return {
        "kind": pin.kind,
        "name": pin.name,
        "version": pin.version,
        "content_sha256": pin.content_sha256,
    }


def _split_spec_entry(spec: ChronologicalSplitSpec) -> dict:
    """Every formal typed split-spec field plus its content SHA-256."""
    return {
        "spec_schema_version": spec.spec_schema_version,
        "kind": spec.kind,
        "name": spec.name,
        "version": spec.version,
        "boundary_timezone": spec.boundary_timezone,
        "train_end_date": spec.train_end_date.isoformat(),
        "validation_end_date": spec.validation_end_date.isoformat(),
        "test_end_date": spec.test_end_date.isoformat(),
        "assignment_rule": spec.assignment_rule,
        "purge_rule": spec.purge_rule,
        "incomplete_label_policy": spec.incomplete_label_policy,
        "out_of_range_policy": spec.out_of_range_policy,
        "content_sha256": chronological_split_spec_pin(spec).content_sha256,
    }


def _build_report_entry(verified: VerifiedDatasetBuild) -> dict:
    """The full typed ``build_report.json`` record plus ``output_layout``
    (explicit field mapping, never ``dataclasses.asdict`` recursion)."""
    report = verified.build_report
    layout = report.output_layout
    return {
        "report_schema_version": report.report_schema_version,
        "materializer_version": report.materializer_version,
        "dataset_id": report.dataset_id,
        "dataset_kind": report.dataset_kind,
        "status": report.status,
        "built_at": _iso_utc_micros(report.built_at),
        "dataset_as_of": (
            _iso_utc_micros(report.dataset_as_of)
            if report.dataset_as_of is not None
            else None
        ),
        "dataset_schema_id": report.dataset_schema_id,
        "logical_dataset_content_id": report.logical_dataset_content_id,
        "logical_row_count": report.logical_row_count,
        "orchestration_contract_version": report.orchestration_contract_version,
        "row_order": report.row_order,
        "manifest_schema_version": report.manifest_schema_version,
        "serialization_format": report.serialization_format,
        "serialization_format_version": report.serialization_format_version,
        "feature_spec_count": report.feature_spec_count,
        "label_spec_count": report.label_spec_count,
        "canonical_build_pin_count": report.canonical_build_pin_count,
        "canonical_row_version_count": report.canonical_row_version_count,
        "completion_complete_key_count": report.completion_complete_key_count,
        "completion_incomplete_key_count": report.completion_incomplete_key_count,
        "completion_missing_key_count": report.completion_missing_key_count,
        "request_count": report.request_count,
        "pit_sample_count": report.pit_sample_count,
        "feature_complete_sample_count": report.feature_complete_sample_count,
        "feature_excluded_sample_count": report.feature_excluded_sample_count,
        "label_complete_sample_count": report.label_complete_sample_count,
        "label_incomplete_sample_count": report.label_incomplete_sample_count,
        "split_sample_count": report.split_sample_count,
        "assigned_sample_count": report.assigned_sample_count,
        "purged_sample_count": report.purged_sample_count,
        "excluded_sample_count": report.excluded_sample_count,
        "split_spec_content_id": report.split_spec_content_id,
        "split_result_id": report.split_result_id,
        "output_layout": {
            "dataset_parquet_filename": layout.dataset_parquet_filename,
            "manifest_filename": layout.manifest_filename,
            "build_report_filename": layout.build_report_filename,
            "split_spec_filename": layout.split_spec_filename,
            "success_filename": layout.success_filename,
            "feature_specs_dirname": layout.feature_specs_dirname,
            "label_specs_dirname": layout.label_specs_dirname,
        },
    }


def _inspect_payload(
    verified: VerifiedDatasetBuild, offset: int, limit: int
) -> dict:
    """The ``dataset-inspect`` success JSON: the full verify summary plus
    scope, schema fields, spec pins, split spec, split diagnostics, build
    report, and the offset/limit row slice in the fixed physical order."""
    payload = _verify_summary("dataset-inspect", "INSPECTED", verified)
    scope = verified.manifest.scope
    payload["scope"] = {
        "symbols": list(scope.symbols),
        "trade_dates": [trade_date.isoformat() for trade_date in scope.trade_dates],
        "interval": scope.interval,
        "adjustment": scope.adjustment,
        "requested_session": scope.requested_session,
    }
    payload["schema_fields"] = [
        {
            "name": field.name,
            "logical_type": field.logical_type,
            "nullable": field.nullable,
        }
        for field in verified.schema.fields
    ]
    payload["feature_specs"] = [
        _spec_pin_entry(feature_label_spec_pin(spec))
        for spec in verified.feature_specs
    ]
    payload["label_specs"] = [
        _spec_pin_entry(feature_label_spec_pin(spec))
        for spec in verified.label_specs
    ]
    payload["split_spec"] = _split_spec_entry(verified.split_spec)
    diagnostics = verified.split_result.diagnostics
    payload["split_diagnostics"] = {
        "sample_count": diagnostics.sample_count,
        "assigned_count": diagnostics.assigned_count,
        "purged_count": diagnostics.purged_count,
        "excluded_count": diagnostics.excluded_count,
    }
    payload["build_report"] = _build_report_entry(verified)
    rows = verified.rows[offset : offset + limit]
    payload["row_offset"] = offset
    payload["row_limit"] = limit
    payload["rows_returned"] = len(rows)
    payload["rows"] = [_row_to_json(row, verified.schema) for row in rows]
    return payload


def _run_dataset_inspect(
    build_dir: str, offset: int, limit: int
) -> VerifiedDatasetBuild:
    try:
        return load_verified_dataset(build_dir)
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-inspect failed")


def dataset_inspect_main(args: argparse.Namespace) -> int:
    try:
        verified = _run_dataset_inspect(args.build_dir, args.offset, args.limit)
    except DatasetCLIError as exc:
        _write_failure("dataset-inspect", exc)
        return 1
    _write_stdout(_inspect_payload(verified, args.offset, args.limit))
    return 0


# ---------------------------------------------------------------------------
# Deterministic JSON output.
# ---------------------------------------------------------------------------


def _iso_utc_micros(value: datetime) -> str:
    """UTC microsecond ISO string with the explicit ``+00:00`` offset."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _write_stdout(payload: dict) -> None:
    """The only stdout writer of the Dataset commands: exactly one JSON
    object with fixed key order, ``ensure_ascii=False``, indent 2, and a
    trailing newline. No progress, warning, or debug text is ever mixed in.
    """
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )


def _write_failure(command: str, exc: DatasetCLIError) -> None:
    """The fixed FAILED JSON on stderr (stdout stays empty; exit code 1 is
    returned by the caller)."""
    sys.stderr.write(
        json.dumps(
            {
                "result_schema_version": DATASET_CLI_RESULT_SCHEMA_VERSION,
                "cli_contract_version": DATASET_CLI_CONTRACT_VERSION,
                "command": command,
                "result": "FAILED",
                "error_type": "DatasetCLIError",
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
