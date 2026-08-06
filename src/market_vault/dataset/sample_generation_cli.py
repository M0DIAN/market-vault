"""Deterministic Sample Generation CLI command (v0.6.0 PR-4).

This module implements the single formal Sample Generation command —
``market-vault sample-generate --plan <PATH>`` — as a thin wrapper over the
already-merged formal public chain:

``generation-plan file -> parse_sample_generation_plan_bytes ->
generate_sample_requests(plan, path_base=generation_plan_path.parent) ->
shared split-spec loader (sample_generation_split) -> pure ordinary
build-plan renderer (sample_generation_output) ->
parse_build_plan_bytes round-trip -> safe / idempotent
output_plan_path materialization -> deterministic CLI result JSON``.

The command accepts only ``--plan``: every formal fact comes from one
explicit, versioned generation-plan JSON document; the command line and the
file never form two sources of truth, so no other business option exists.

``sample-generate`` is dispatched from the top-level ``main()`` before any
settings file is read, exactly like the Dataset commands: a missing or
damaged ``--settings`` path never affects it, settings loading is never
performed, the moomoo daemon is never connected, and no network access ever
happens. It never executes ``dataset-build``, never runs PIT assembly,
never computes Feature or Label values, never calls orchestration /
materialization / the verified Dataset reader, never builds a Dataset, and
never implements a Catalog: it only writes one ordinary
``market-vault-dataset-build-plan-v1`` document that the existing
``market-vault dataset-build --plan`` command can consume directly.
COMPLETE / EMPTY are facts only a real build plus the verified reader can
prove; the CLI never claims them.

Determinism and safety: the generator core is called exactly once per
successful run; the build plan is rendered by the pure serializer from the
frozen models only; the existing ``parse_build_plan_bytes`` (not a second
validator) accepts the rendered bytes and every parsed field is verified
against the expectation before any file is touched; ``output_plan_path`` is
lexically joined to the generation-plan parent directory and materialized
exact-byte idempotently — exclusive create for a missing file, success
without rewrite for an exact-byte existing file, fail closed (never
overwrite) for a different existing file, and partial-file cleanup on write
failure. ``resolve()`` is never called, ``~`` / environment variables /
globs are never expanded, no directory is scanned, no ``latest`` is
selected, symlinks and Windows junctions / reparse points fail closed, and
``Path.cwd`` is used only to locate an explicit relative ``--plan`` argument
and never enters a model, an identity, the result, or the output build-plan
bytes.

Success writes exactly one JSON object to stdout (stderr stays empty, exit
0); formal failure writes exactly one JSON object to stderr (stdout stays
empty, exit 1). Argparse usage errors keep the standard argparse stderr and
exit code 2. Every documented failure is converted to
:class:`SampleGenerationCLIError` with the ``__cause__`` preserved and never
double-wrapped; broad ``except Exception`` is never used and real
programming errors are never caught.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .cli import parse_build_plan_bytes
from .cli_models import (
    DATASET_BUILD_PLAN_SCHEMA_VERSION,
    BuildPlan,
    DatasetCLIError,
)
from .materialization import _is_junction_or_reparse
from .sample_generation import parse_sample_generation_plan_bytes
from .sample_generation_cli_models import (
    SAMPLE_GENERATION_CLI_CONTRACT_VERSION,
    SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION,
    SampleGenerationCLIError,
)
from .sample_generation_core import generate_sample_requests
from .sample_generation_core_models import SampleGenerationResult
from .sample_generation_models import (
    SampleGenerationError,
    SampleGenerationPlan,
)
from .sample_generation_output import serialize_generated_dataset_build_plan
from .sample_generation_split import load_sample_generation_split_spec
from .split_models import (
    ChronologicalSplitSpec,
    SplitValidationError,
)

__all__ = [
    "SAMPLE_GENERATION_COMMANDS",
    "add_sample_generation_subparsers",
    "run_sample_generation_command",
]

#: The one Sample Generation command dispatched before any settings file is
#: read.
SAMPLE_GENERATION_COMMANDS = frozenset({"sample-generate"})

#: Documented failures converted to :class:`SampleGenerationCLIError` at the
#: command boundary (``json.JSONDecodeError`` is a ``ValueError`` subclass
#: and is listed explicitly for contract clarity; ``DatasetCLIError`` is
#: listed because the existing strict build-plan parser is the output
#: acceptance authority). Broad ``except Exception`` is never used.
_DOCUMENTED_ERRORS = (
    SampleGenerationError,
    DatasetCLIError,
    SplitValidationError,
    OSError,
    UnicodeError,
    json.JSONDecodeError,
)


def _as_cli_error(exc, context: str) -> None:
    """Convert a documented failure to :class:`SampleGenerationCLIError`.

    An already-raised :class:`SampleGenerationCLIError` passes through
    unchanged (never double-wrapped); the contract-listed exceptions
    (Sample Generation errors, split validation errors, the existing
    build-plan parser's errors, path / read / write ``OSError``,
    ``UnicodeError``, ``json.JSONDecodeError``) are converted with a context
    prefix and their ``__cause__`` preserved. Broad ``except Exception`` is
    never used: real programming errors are not disguised as user input
    errors.
    """
    if isinstance(exc, SampleGenerationCLIError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise SampleGenerationCLIError(f"{context}: {exc}") from exc
    raise exc


# ---------------------------------------------------------------------------
# Parser wiring (the subparser is added to the shared argparse tree).
# ---------------------------------------------------------------------------


def add_sample_generation_subparsers(subparsers) -> None:
    """Add the ``sample-generate`` subparser to the shared argparse tree.

    ``--plan`` is the only accepted option: every business input lives in
    the explicit generation-plan file, so the command line and the file can
    never form two sources of truth.
    """
    generate = subparsers.add_parser(
        "sample-generate",
        help="Deterministically generate one ordinary Dataset build plan",
    )
    generate.add_argument(
        "--plan",
        required=True,
        metavar="PATH",
        help="Path to the versioned Sample Generation plan JSON (all "
        "generation inputs are declared in the plan; no other option is "
        "accepted)",
    )


def run_sample_generation_command(command: str, args: argparse.Namespace) -> int:
    """Dispatch one Sample Generation CLI command.

    Called from the shared ``main()`` before any settings file is read so
    ``sample-generate`` never loads ``settings.yaml``, never connects to the
    moomoo daemon, and never accesses the network. Returns the process exit
    code.
    """
    if command == "sample-generate":
        return sample_generate_main(args)
    raise AssertionError(f"unknown Sample Generation CLI command {command!r}")


# ---------------------------------------------------------------------------
# Path and link safety (explicit; no filesystem semantics beyond this).
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
            raise SampleGenerationCLIError(
                f"{label} must not contain '.' or '..' path components: "
                f"{raw_text!r}"
            )


def _reject_link(path: Path, label: str) -> None:
    if path.is_symlink() or _is_junction_or_reparse(path):
        raise SampleGenerationCLIError(
            f"{label} must not be a symlink or junction: {path}"
        )


def _verify_parent_chain(path: Path, label: str) -> None:
    """Every existing parent component must be a regular non-link
    directory (fail closed on links)."""
    for component in (path.parent, *path.parent.parents):
        _reject_link(component, f"{label} parent path component")
        if component.exists() and not component.is_dir():
            raise SampleGenerationCLIError(
                f"{label} parent path component must be a regular directory: "
                f"{component}"
            )


def _resolve_path(raw_text: str, *, base: Path, label: str) -> Path:
    """Raw path -> lexically absolute Path against ``base``.

    ``resolve()`` is never used to mask a link; ``.`` / ``..`` components
    are rejected; ``~``, environment variables, and globs are never
    expanded; no extension is appended. Path normalization only affects the
    access location and never enters any identity or the output build-plan
    bytes.
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
        raise SampleGenerationCLIError(f"{label} must be a regular file: {path}")


def _coerce_generation_plan_path(raw_text: str) -> Path:
    """The ``--plan`` path: absolute or relative to the current working
    directory, lexically absolute, a regular non-link file.

    ``Path.cwd`` is used only here, only to locate the explicit CLI
    argument; it never enters a model, an identity, the result, or the
    output build-plan bytes.
    """
    path = _resolve_path(raw_text, base=Path.cwd(), label="generation plan path")
    _verify_regular_file(path, "generation plan")
    return path


def _read_plan_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SampleGenerationCLIError(
            f"cannot read generation plan {path}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Relative-path / output-parent policy.
# ---------------------------------------------------------------------------


def _check_output_parent_policy(
    plan: SampleGenerationPlan, output_plan_path: Path, path_base: Path
) -> None:
    """The generated build plan's relative paths must keep their meaning.

    ``dataset-build`` anchors relative build-plan paths to the build-plan
    file's parent directory, while the Sample Generation contract copies the
    path strings into the ordinary build plan unchanged. If any copied path
    (``canonical_build_dirs``, ``feature_spec_files``, ``label_spec_files``,
    ``output_root``) is relative, the output plan file's lexical parent must
    equal the generation-plan file's parent directory — otherwise moving the
    output plan would silently change what the relative paths mean. When
    every copied path is absolute, the output plan may live in any other
    explicit directory. ``split_spec_file`` is embedded as the formal
    ``split_spec`` object, never copied as a path, and does not participate.
    """
    candidates = (
        *plan.canonical_build_dirs,
        *plan.feature_spec_files,
        *plan.label_spec_files,
        plan.output_root,
    )
    has_relative = any(not Path(raw).is_absolute() for raw in candidates)
    if has_relative and output_plan_path.parent != path_base:
        raise SampleGenerationCLIError(
            "relative Dataset build-plan paths require output_plan_path to "
            "share the generation-plan parent directory"
        )


# ---------------------------------------------------------------------------
# Safe / idempotent output_plan_path materialization.
# ---------------------------------------------------------------------------


def _verify_output_parent(output_plan_path: Path) -> None:
    """The output plan's parent must already exist and be a regular
    non-link directory under a safe parent chain; nothing is ever created
    implicitly."""
    _verify_parent_chain(output_plan_path, "output plan path")
    if not output_plan_path.parent.exists():
        raise SampleGenerationCLIError(
            "output plan parent directory does not exist: "
            f"{output_plan_path.parent}"
        )
    _reject_link(output_plan_path.parent, "output plan parent directory")
    if not output_plan_path.parent.is_dir():
        raise SampleGenerationCLIError(
            "output plan parent must be a regular directory: "
            f"{output_plan_path.parent}"
        )


def _materialize_output_plan(output_plan_path: Path, generated_bytes: bytes) -> bool:
    """Exact-byte idempotent no-overwrite materialization.

    Missing file: exclusive create, write the exact bytes,
    ``created_new_plan == True``. Existing regular non-link file with
    identical bytes: success without rewriting, ``created_new_plan ==
    False``. Existing file with different bytes: fail closed, never
    overwrite, never truncate, never modify. A concurrently appearing file
    fails closed instead of overwriting. A write failure is converted to
    :class:`SampleGenerationCLIError` and the partial file produced by this
    round is cleaned up; pre-existing files are never touched. No
    nondeterministic identifier, current-time fact, mtime, or machine name
    is used anywhere.
    """
    _verify_output_parent(output_plan_path)
    _reject_link(output_plan_path, "output plan path")
    if output_plan_path.exists():
        if not output_plan_path.is_file():
            raise SampleGenerationCLIError(
                f"output plan path must be a regular file: {output_plan_path}"
            )
        try:
            existing_bytes = output_plan_path.read_bytes()
        except OSError as exc:
            raise SampleGenerationCLIError(
                f"cannot read existing output plan {output_plan_path}: {exc}"
            ) from exc
        if existing_bytes == generated_bytes:
            return False
        raise SampleGenerationCLIError(
            "refusing to overwrite existing build plan with different "
            f"content: {output_plan_path}"
        )
    handle = None
    try:
        handle = output_plan_path.open("xb")
    except FileExistsError as exc:
        raise SampleGenerationCLIError(
            "output plan path appeared concurrently; refusing to overwrite: "
            f"{output_plan_path}"
        ) from exc
    except OSError as exc:
        raise SampleGenerationCLIError(
            f"cannot create output plan {output_plan_path}: {exc}"
        ) from exc
    try:
        with handle:
            handle.write(generated_bytes)
    except OSError as exc:
        # The partial file was produced by this round: clean it up and never
        # touch any pre-existing file.
        try:
            output_plan_path.unlink()
        except OSError:
            pass
        raise SampleGenerationCLIError(
            f"cannot write output plan {output_plan_path}: {exc}"
        ) from exc
    return True


def _verify_read_back(output_plan_path: Path, generated_bytes: bytes) -> None:
    """After materialization the file on disk must be exactly the generated
    bytes and must pass the existing strict build-plan parser."""
    try:
        read_back_bytes = output_plan_path.read_bytes()
    except OSError as exc:
        raise SampleGenerationCLIError(
            f"cannot read back output plan {output_plan_path}: {exc}"
        ) from exc
    if read_back_bytes != generated_bytes:
        raise SampleGenerationCLIError(
            f"output plan read-back mismatch: {output_plan_path}"
        )
    parse_build_plan_bytes(read_back_bytes)


# ---------------------------------------------------------------------------
# Output acceptance through the existing build-plan parser.
# ---------------------------------------------------------------------------


def _expect(condition, label: str) -> None:
    """Fail closed when a parsed build-plan field does not match the
    expectation; ``parse_build_plan_bytes`` stays the format authority."""
    if not condition:
        raise SampleGenerationCLIError(
            f"generated build plan parse mismatch: {label}"
        )


def _verify_request_matches(parsed_request, expected) -> None:
    for label, actual, wanted in (
        ("request code", parsed_request.code, expected.code),
        ("request interval", parsed_request.interval, expected.interval),
        ("request adjustment", parsed_request.adjustment, expected.adjustment),
        (
            "request requested_session",
            parsed_request.requested_session,
            expected.requested_session,
        ),
        (
            "request anchor_market_calendar_date",
            parsed_request.anchor_market_calendar_date,
            expected.anchor_market_calendar_date,
        ),
        (
            "request feature_window_start",
            parsed_request.feature_window_start,
            expected.feature_window_start,
        ),
        (
            "request feature_window_close",
            parsed_request.feature_window_close,
            expected.feature_window_close,
        ),
        (
            "request label_window_start",
            parsed_request.label_window_start,
            expected.label_window_start,
        ),
        (
            "request label_window_close",
            parsed_request.label_window_close,
            expected.label_window_close,
        ),
    ):
        _expect(actual == wanted, label)


def _verify_split_spec_matches(parsed_split, split_spec: ChronologicalSplitSpec) -> None:
    for label, actual, wanted in (
        ("split_spec spec_schema_version", parsed_split.spec_schema_version, split_spec.spec_schema_version),
        ("split_spec name", parsed_split.name, split_spec.name),
        ("split_spec version", parsed_split.version, split_spec.version),
        (
            "split_spec boundary_timezone",
            parsed_split.boundary_timezone,
            split_spec.boundary_timezone,
        ),
        ("split_spec train_end_date", parsed_split.train_end_date, split_spec.train_end_date),
        (
            "split_spec validation_end_date",
            parsed_split.validation_end_date,
            split_spec.validation_end_date,
        ),
        ("split_spec test_end_date", parsed_split.test_end_date, split_spec.test_end_date),
        (
            "split_spec assignment_rule",
            parsed_split.assignment_rule,
            split_spec.assignment_rule,
        ),
        ("split_spec purge_rule", parsed_split.purge_rule, split_spec.purge_rule),
        (
            "split_spec incomplete_label_policy",
            parsed_split.incomplete_label_policy,
            split_spec.incomplete_label_policy,
        ),
        (
            "split_spec out_of_range_policy",
            parsed_split.out_of_range_policy,
            split_spec.out_of_range_policy,
        ),
    ):
        _expect(actual == wanted, label)


def _verify_parsed_plan(
    parsed: BuildPlan,
    plan: SampleGenerationPlan,
    result: SampleGenerationResult,
    split_spec: ChronologicalSplitSpec,
) -> None:
    """Verify every parsed build-plan field against the expectation, item by
    item, before any file is written."""
    _expect(
        parsed.plan_schema_version == DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "plan_schema_version",
    )
    _expect(
        parsed.canonical_build_dirs == plan.canonical_build_dirs,
        "canonical_build_dirs",
    )
    _expect(
        parsed.feature_spec_files == plan.feature_spec_files,
        "feature_spec_files",
    )
    _expect(parsed.label_spec_files == plan.label_spec_files, "label_spec_files")
    _expect(len(parsed.requests) == len(result.requests), "request sequence length")
    for parsed_request, expected in zip(parsed.requests, result.requests):
        _verify_request_matches(parsed_request, expected)
    _expect(parsed.scope.symbols == result.scope.symbols, "scope symbols")
    _expect(
        parsed.scope.trade_dates
        == tuple(trade_date.isoformat() for trade_date in result.scope.trade_dates),
        "scope trade_dates",
    )
    _expect(parsed.scope.interval == result.scope.interval, "scope interval")
    _expect(parsed.scope.adjustment == result.scope.adjustment, "scope adjustment")
    _expect(
        parsed.scope.requested_session == result.scope.requested_session,
        "scope requested_session",
    )
    _verify_split_spec_matches(parsed.split_spec, split_spec)
    _expect(parsed.dataset_as_of == result.dataset_as_of, "dataset_as_of")
    _expect(parsed.output_root == plan.output_root, "output_root")
    _expect(parsed.built_at == plan.built_at, "built_at")


# ---------------------------------------------------------------------------
# sample-generate: the fixed execution chain.
# ---------------------------------------------------------------------------


def _run_sample_generate(plan_arg: str) -> dict:
    """Run the complete generation chain; returns the success payload.

    The generator core is called exactly once; the shared split loader is
    the single split-spec authority of both the core and this writer; the
    existing ``parse_build_plan_bytes`` accepts the rendered bytes before
    and after materialization; every documented failure is converted to
    :class:`SampleGenerationCLIError` with the ``__cause__`` preserved; real
    programming errors pass through.
    """
    try:
        generation_plan_path = _coerce_generation_plan_path(plan_arg)
        path_base = generation_plan_path.parent
        plan = parse_sample_generation_plan_bytes(
            _read_plan_bytes(generation_plan_path)
        )
        result = generate_sample_requests(plan, path_base=path_base)
        split_spec = load_sample_generation_split_spec(
            _resolve_path(plan.split_spec_file, base=path_base, label="split spec file")
        )
        output_plan_path = _resolve_path(
            plan.output_plan_path, base=path_base, label="output plan path"
        )
        _check_output_parent_policy(plan, output_plan_path, path_base)
        generated_bytes = serialize_generated_dataset_build_plan(
            plan, result, split_spec=split_spec
        )
        parsed = parse_build_plan_bytes(generated_bytes)
        _verify_parsed_plan(parsed, plan, result, split_spec)
        created_new_plan = _materialize_output_plan(output_plan_path, generated_bytes)
        _verify_read_back(output_plan_path, generated_bytes)
        return _success_payload(plan, result, output_plan_path, created_new_plan)
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "sample-generate failed")


def _success_payload(
    plan: SampleGenerationPlan,
    result: SampleGenerationResult,
    output_plan_path: Path,
    created_new_plan: bool,
) -> dict:
    """The fixed ``sample-generate`` success JSON.

    Every fact comes from the frozen plan / result models; ``output_plan_path``
    is the lexical absolute POSIX-slash path; ``diagnostics`` is the formal
    :class:`SampleGenerationDiagnostics` of the result, never re-derived or
    fabricated. The CLI never claims a Dataset is COMPLETE or EMPTY.
    """
    diagnostics = result.diagnostics
    return {
        "result_schema_version": SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION,
        "cli_contract_version": SAMPLE_GENERATION_CLI_CONTRACT_VERSION,
        "command": "sample-generate",
        "result": "SUCCESS",
        "generation_plan_schema_version": plan.generation_plan_schema_version,
        "generator_core_version": result.generator_core_version,
        "generation_content_id": result.generation_content_id,
        "dataset_build_plan_schema_version": DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "output_plan_path": output_plan_path.as_posix(),
        "created_new_plan": created_new_plan,
        "generated_request_count": diagnostics.generated_request_count,
        "canonical_build_count": diagnostics.canonical_build_count,
        "feature_spec_count": len(result.feature_spec_pins),
        "label_spec_count": len(result.label_spec_pins),
        "split_spec_pin": {
            "kind": result.split_spec_pin.kind,
            "name": result.split_spec_pin.name,
            "version": result.split_spec_pin.version,
            "content_sha256": result.split_spec_pin.content_sha256,
        },
        "dataset_as_of": (
            _iso_utc_micros(result.dataset_as_of)
            if result.dataset_as_of is not None
            else None
        ),
        "diagnostics": {
            "canonical_build_count": diagnostics.canonical_build_count,
            "canonical_bar_count": diagnostics.canonical_bar_count,
            "in_scope_bar_count": diagnostics.in_scope_bar_count,
            "contiguous_segment_count": diagnostics.contiguous_segment_count,
            "candidate_anchor_count": diagnostics.candidate_anchor_count,
            "generated_request_count": diagnostics.generated_request_count,
            "insufficient_feature_history_count": (
                diagnostics.insufficient_feature_history_count
            ),
            "insufficient_label_future_count": diagnostics.insufficient_label_future_count,
        },
    }


def sample_generate_main(args: argparse.Namespace) -> int:
    try:
        payload = _run_sample_generate(args.plan)
    except SampleGenerationCLIError as exc:
        _write_failure(exc)
        return 1
    _write_stdout(payload)
    return 0


# ---------------------------------------------------------------------------
# Deterministic JSON output.
# ---------------------------------------------------------------------------


def _iso_utc_micros(value: datetime) -> str:
    """UTC microsecond ISO string with the explicit ``+00:00`` offset."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _write_stdout(payload: dict) -> None:
    """The only stdout writer of ``sample-generate``: exactly one JSON
    object with fixed key order, ``ensure_ascii=False``, indent 2, and a
    trailing newline. No progress, warning, or debug text is ever mixed in.
    """
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_failure(exc: SampleGenerationCLIError) -> None:
    """The fixed FAILED JSON on stderr (stdout stays empty; exit code 1 is
    returned by the caller)."""
    sys.stderr.write(
        json.dumps(
            {
                "result_schema_version": SAMPLE_GENERATION_CLI_RESULT_SCHEMA_VERSION,
                "cli_contract_version": SAMPLE_GENERATION_CLI_CONTRACT_VERSION,
                "command": "sample-generate",
                "result": "FAILED",
                "error_type": "SampleGenerationCLIError",
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
