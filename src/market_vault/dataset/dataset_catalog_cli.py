"""Deterministic Dataset Catalog CLI commands (v0.6.0 PR-7).

This module implements the four formal Dataset Catalog commands —
``dataset-catalog-build``, ``dataset-catalog-verify``,
``dataset-catalog-list``, and ``dataset-catalog-show`` — as a thin wrapper
over the already-merged formal public chain:

``build_dataset_catalog`` -> ``materialize_dataset_catalog_snapshot`` ->
``load_verified_dataset_catalog``.

The CLI is never a second Catalog builder, never a second Catalog
validator, and never a second Catalog reader: every layer runs exactly
once through its existing public entry, every artifact is written only by
the materializer, and every read of a committed snapshot goes through the
verified Catalog reader.

``dataset-catalog-build`` accepts exactly one candidate mode —
``--dataset-root <PATH>`` (explicit bounded discovery root) or one or more
repeated ``--candidate-build-dir <PATH>`` — plus the explicit
``--output-root <PATH>`` and the explicit timezone-aware ``--built-at
ISO8601``. The raw CLI path is lexically absolutized against
``Path.cwd()`` when relative (``.`` / ``..`` components are rejected;
``resolve()`` is never used to mask a link; ``~``, environment variables,
globs, and directory scans are never performed) and the absolute path is
handed to the builder / materializer, whose absolute-input contracts never
change. Link / junction / reparse / candidate trust verification is
entirely the Builder's / Materializer's / Reader's job; the CLI never
implements a second verifier. ``built_at`` must be timezone-aware (naive
and empty values fail at the argparse stage with exit code 2; ``Z`` and
explicit offsets are accepted); the CLI never calls ``datetime.now()``,
``datetime.utcnow()``, or ``time.time()`` and never fabricates a local
timezone — the timezone-equivalent instant is normalized to UTC
microseconds by the materializer. The success payload is produced from the
final verified snapshot (``load_verified_dataset_catalog`` on the
materialization's ``snapshot_path``); ``created_new_snapshot`` is the one
fact that comes from the materialization result. The CLI never parses a
manifest, never reads ``catalog.json`` directly, never reads Dataset
Parquet, never reloads a Dataset, and never constructs a snapshot
directory manually.

``dataset-catalog-verify`` accepts only an explicit ``--snapshot-dir
<PATH>`` and calls ``load_verified_dataset_catalog`` exactly once; it
never writes, repairs, rewrites, or deletes anything and its success JSON
is a summary only (never entries).

``dataset-catalog-list`` accepts an explicit ``--snapshot-dir`` plus the
optional query filters ``--status`` / ``--dataset-kind`` / ``--symbol`` /
``--trade-date`` / ``--interval`` / ``--adjustment`` /
``--requested-session`` and the pagination options ``--offset`` /
``--limit`` (default 0 / 20; ``limit == 0`` is legal, the maximum is
1000). It loads the verified snapshot once and then performs pure
in-memory filtering over ``verified.entries`` only: every filter is exact
(``--status`` / ``--dataset-kind`` / ``--interval`` / ``--adjustment`` /
``--requested-session`` compare equality against the stored facts,
``--symbol`` is a membership test against ``scope.symbols``, and
``--trade-date`` is a strict ``YYYY-MM-DD`` membership test against
``scope.trade_dates``); all provided filters combine with AND semantics;
a ``None`` stored ``requested_session`` never matches a string filter;
there is no implicit case folding and no fuzzy search. The relative order
of the already-``dataset_id``-sorted entries is never changed, no sort /
descending / random / filesystem order is ever applied, and the page is
exactly ``matched[offset:offset+limit]``. ``catalog.json``,
``manifest.json``, ``load_verified_dataset``, recorded build paths,
Dataset roots, the Catalog ``output_root``, DuckDB, SQL, pandas, and the
network are never accessed; an empty Catalog or zero matches is a success
(exit 0, ``matched_count == 0``, ``datasets == []``), never an error.

``dataset-catalog-show`` accepts an explicit ``--snapshot-dir`` and one
strict ``--dataset-id <64-lowercase-hex>`` (``^[0-9a-f]{64}$``; any other
shape fails at the argparse stage with exit code 2) and performs an exact
lookup ``entry.dataset_id == requested`` in ``verified.entries`` — never
prefix, substring, case-insensitive, latest, or path lookup. A missing id
fails with :class:`DatasetCatalogCLIError` (exit 1). The ``dataset``
object carries the complete lossless verified entry: ``content_id``, the
full 14-field ``dataset_facts`` record, and the ``observed_metadata``
(``recorded_built_at`` and the historical ``recorded_build_path`` text —
the recorded path is never turned back into a live ``Path`` and never
accessed).

All four commands are dispatched from the top-level ``main()`` before
``load_settings``: they never load ``settings.yaml``, never connect to
OpenD, never access the network, and never depend on
``config/settings.yaml`` — even an explicit ``--settings
missing-file.yaml`` cannot block them. Success writes exactly one JSON
object to stdout (stderr stays empty, exit 0); formal failure writes
exactly one JSON object to stderr (stdout stays empty, exit 1); argparse
usage errors keep the standard argparse stderr and exit code 2; real
programming errors are never caught. Output is deterministic
(``ensure_ascii=False``, ``indent=2``, trailing newline, fixed key
insertion order; no progress, warning, debug, current-time, or machine
facts). Every documented failure is converted to
:class:`DatasetCatalogCLIError` with the ``__cause__`` preserved and never
double-wrapped; broad ``except Exception`` is never used.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .dataset_catalog_builder import build_dataset_catalog
from .dataset_catalog_builder_models import DatasetCatalogBuildResult
from .dataset_catalog_cli_models import (
    DATASET_CATALOG_CLI_CONTRACT_VERSION,
    DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION,
    DatasetCatalogCLIError,
)
from .dataset_catalog_materialization import materialize_dataset_catalog_snapshot
from .dataset_catalog_materialization_models import DatasetCatalogMaterializationResult
from .dataset_catalog_models import DatasetCatalogError
from .dataset_catalog_reader import load_verified_dataset_catalog
from .dataset_catalog_reader_models import (
    DatasetCatalogSnapshotEntryRecord,
    VerifiedDatasetCatalogSnapshot,
)

__all__ = [
    "DATASET_CATALOG_COMMANDS",
    "add_dataset_catalog_subparsers",
    "run_dataset_catalog_command",
]

#: The four Dataset Catalog commands dispatched before ``load_settings``.
DATASET_CATALOG_COMMANDS = frozenset(
    {
        "dataset-catalog-build",
        "dataset-catalog-verify",
        "dataset-catalog-list",
        "dataset-catalog-show",
    }
)

_STRICT_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATASET_ID_RE = re.compile(r"^[0-9a-f]{64}$")

#: Documented failures converted to :class:`DatasetCatalogCLIError` at the
#: command boundary. ``DatasetCatalogError`` covers the builder, the
#: materializer, and the verified Catalog reader; the remaining types are
#: the documented path / read / write failures of the formal layers.
#: Broad ``except Exception`` is never used.
_DOCUMENTED_ERRORS = (
    DatasetCatalogError,
    OSError,
    UnicodeError,
    TypeError,
    ValueError,
    KeyError,
)

#: The exact keys of the fixed ``filters`` object of
#: ``dataset-catalog-list`` (always present; unused filters are ``null``).
_LIST_FILTER_KEYS = (
    "status",
    "dataset_kind",
    "symbol",
    "trade_date",
    "interval",
    "adjustment",
    "requested_session",
)


# ---------------------------------------------------------------------------
# Parser wiring (subcommands are added to the shared argparse tree).
# ---------------------------------------------------------------------------


def _non_negative_int_arg(value: str) -> int:
    """Argparse type for ``--offset``: real non-negative int, else code 2."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Value must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be a non-negative integer")
    return parsed


def _limit_arg(value: str) -> int:
    """Argparse type for ``--limit``: non-negative int capped at 1000.

    ``limit == 0`` is legal (returns an empty page); ``limit > 1000`` and
    negative values fail at the argparse stage with the standard exit
    code 2.
    """
    parsed = _non_negative_int_arg(value)
    if parsed > 1000:
        raise argparse.ArgumentTypeError("Value must not exceed 1000")
    return parsed


def _aware_datetime_arg(value: str) -> datetime:
    """Argparse type for ``--built-at``: timezone-aware ISO 8601 datetime.

    Naive datetimes, empty values, and unparseable text fail at the
    argparse stage with the standard exit code 2; ``Z`` (Python 3.11+)
    and explicit offsets are accepted. The system local timezone and the
    current time are never consulted: the returned instant is normalized
    to UTC microseconds by the materializer, so timezone-equivalent
    representations of the same instant produce the same snapshot.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--built-at must be an ISO 8601 datetime (e.g. "
            "2026-08-07T12:34:56+00:00)"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "--built-at must be timezone-aware; naive datetimes are rejected"
        )
    return parsed


def _strict_date_arg(value: str) -> date:
    """Argparse type for ``--trade-date``: strict ``YYYY-MM-DD`` date."""
    if not _STRICT_ISO_DATE_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "--trade-date must use the strict format YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--trade-date must be a valid calendar date, got {value!r}"
        ) from exc


def _dataset_id_arg(value: str) -> str:
    """Argparse type for ``--dataset-id``: strict lowercase 64-hex."""
    if not _DATASET_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "--dataset-id must be a 64-character lowercase SHA-256 "
            "hexadecimal string"
        )
    return value


def add_dataset_catalog_subparsers(subparsers) -> None:
    """Add the four Dataset Catalog subparsers to the shared argparse
    tree."""
    build = subparsers.add_parser(
        "dataset-catalog-build",
        help="Build one immutable Dataset Catalog snapshot from explicit "
        "Dataset candidates",
    )
    mode = build.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dataset-root",
        metavar="PATH",
        help="Explicit bounded Dataset discovery root; only direct 64-hex "
        "child directories are candidates",
    )
    mode.add_argument(
        "--candidate-build-dir",
        action="append",
        metavar="PATH",
        help="Explicit final Dataset build directory candidate; repeatable "
        "and mutually exclusive with --dataset-root",
    )
    build.add_argument(
        "--output-root",
        required=True,
        metavar="PATH",
        help="Explicit parent directory for the committed Dataset Catalog "
        "snapshot (<output_root>/<snapshot_id>)",
    )
    build.add_argument(
        "--built-at",
        required=True,
        type=_aware_datetime_arg,
        metavar="ISO8601",
        help="Explicit timezone-aware Dataset Catalog snapshot build "
        "instant; current time is never used",
    )

    verify = subparsers.add_parser(
        "dataset-catalog-verify",
        help="Verify one immutable Dataset Catalog snapshot",
    )
    verify.add_argument(
        "--snapshot-dir",
        required=True,
        metavar="PATH",
        help="Explicit final Dataset Catalog snapshot directory "
        "(<output_root>/<snapshot_id>)",
    )

    listing = subparsers.add_parser(
        "dataset-catalog-list",
        help="List entries from one verified Dataset Catalog snapshot with "
        "read-only filters and pagination",
    )
    listing.add_argument(
        "--snapshot-dir",
        required=True,
        metavar="PATH",
        help="Explicit final Dataset Catalog snapshot directory "
        "(<output_root>/<snapshot_id>)",
    )
    listing.add_argument(
        "--status",
        choices=("COMPLETE", "EMPTY"),
        help="Exact Dataset status filter (COMPLETE or EMPTY)",
    )
    listing.add_argument(
        "--dataset-kind",
        metavar="TEXT",
        help="Exact Dataset kind filter",
    )
    listing.add_argument(
        "--symbol",
        metavar="TEXT",
        help="Membership filter: symbol must be present in Dataset "
        "scope.symbols",
    )
    listing.add_argument(
        "--trade-date",
        type=_strict_date_arg,
        metavar="YYYY-MM-DD",
        help="Membership filter: date must be present in Dataset "
        "scope.trade_dates",
    )
    listing.add_argument(
        "--interval",
        metavar="TEXT",
        help="Exact Dataset scope.interval filter",
    )
    listing.add_argument(
        "--adjustment",
        metavar="TEXT",
        help="Exact Dataset scope.adjustment filter",
    )
    listing.add_argument(
        "--requested-session",
        metavar="TEXT",
        help="Exact Dataset scope.requested_session filter; a stored null "
        "never matches",
    )
    listing.add_argument(
        "--offset",
        type=_non_negative_int_arg,
        default=0,
        metavar="N",
        help="Zero-based entry offset (default 0; entries are sliced, never "
        "reordered)",
    )
    listing.add_argument(
        "--limit",
        type=_limit_arg,
        default=20,
        metavar="N",
        help="Maximum entries to return (default 20, max 1000; 0 returns "
        "no entries)",
    )

    show = subparsers.add_parser(
        "dataset-catalog-show",
        help="Show one entry from one verified Dataset Catalog snapshot by "
        "exact Dataset ID",
    )
    show.add_argument(
        "--snapshot-dir",
        required=True,
        metavar="PATH",
        help="Explicit final Dataset Catalog snapshot directory "
        "(<output_root>/<snapshot_id>)",
    )
    show.add_argument(
        "--dataset-id",
        required=True,
        type=_dataset_id_arg,
        metavar="HEX",
        help="Exact 64-character lowercase dataset_id (^[0-9a-f]{64}$)",
    )


def run_dataset_catalog_command(
    command: str, args: argparse.Namespace
) -> int:
    """Dispatch one Dataset Catalog CLI command.

    Called from the shared ``main()`` before ``load_settings`` so the four
    commands never load ``settings.yaml``, never connect to OpenD, and
    never access the network. Returns the process exit code.
    """
    if command == "dataset-catalog-build":
        return dataset_catalog_build_main(args)
    if command == "dataset-catalog-verify":
        return dataset_catalog_verify_main(args)
    if command == "dataset-catalog-list":
        return dataset_catalog_list_main(args)
    if command == "dataset-catalog-show":
        return dataset_catalog_show_main(args)
    raise AssertionError(
        f"unknown Dataset Catalog CLI command {command!r}"
    )


# ---------------------------------------------------------------------------
# Unified documented error boundary.
# ---------------------------------------------------------------------------


def _as_cli_error(exc, context: str) -> None:
    """Convert a documented failure to :class:`DatasetCatalogCLIError`.

    An already-raised :class:`DatasetCatalogCLIError` passes through
    unchanged (never double-wrapped); the contract-listed exceptions
    (``DatasetCatalogError`` and its subclasses — the builder, the
    materializer, and the verified Catalog reader — plus ``OSError``,
    ``UnicodeError``, and the documented ``TypeError`` / ``ValueError`` /
    ``KeyError``) are converted with a context prefix and their
    ``__cause__`` preserved. Broad ``except Exception`` is never used:
    real programming errors are not disguised as user input errors.
    """
    if isinstance(exc, DatasetCatalogCLIError):
        raise exc
    if isinstance(exc, _DOCUMENTED_ERRORS):
        raise DatasetCatalogCLIError(f"{context}: {exc}") from exc
    raise exc


# ---------------------------------------------------------------------------
# CLI path boundary (lexical absolutization only).
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
            raise DatasetCatalogCLIError(
                f"{label} must not contain '.' or '..' path components: "
                f"{raw_text!r}"
            )


def _coerce_cli_path(raw_text: str, label: str) -> Path:
    """Raw CLI path -> lexically absolute Path.

    ``Path.cwd()`` is used only here, only to complete an explicit
    relative CLI path (a CLI access-location behavior, never a Builder
    formal input). ``resolve()`` is never used to mask a link; ``.`` /
    ``..`` components are rejected; ``~``, environment variables, and
    globs are never expanded; no directory is scanned. The absolute path
    is then handed to the formal layer, whose absolute-input contract is
    unchanged.
    """
    _reject_dot_components(raw_text, label)
    path = Path(raw_text)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _coerce_snapshot_dir(raw_text: str) -> Path:
    return _coerce_cli_path(raw_text, "snapshot directory")


# ---------------------------------------------------------------------------
# dataset-catalog-build: the fixed execution chain.
# ---------------------------------------------------------------------------


def _build_inputs(
    args: argparse.Namespace,
) -> tuple[dict, Path]:
    """The explicit builder inputs as absolute CLI paths.

    Exactly one candidate mode is enforced by the mutually exclusive
    argparse group (exit code 2 on both / neither); the repeated
    ``--candidate-build-dir`` values are lexically absolutized into a
    tuple (at least one entry is enforced by argparse).
    """
    output_root = _coerce_cli_path(args.output_root, "output root")
    if args.dataset_root is not None:
        return (
            {"dataset_root": _coerce_cli_path(args.dataset_root, "dataset root")},
            output_root,
        )
    candidates = tuple(
        _coerce_cli_path(raw, "candidate build directory")
        for raw in args.candidate_build_dir
    )
    return ({"candidate_build_dirs": candidates}, output_root)


def _run_dataset_catalog_build(args: argparse.Namespace) -> dict:
    """Run the complete build chain; returns the success payload.

    ``build_dataset_catalog`` (exact candidate mode), then
    ``materialize_dataset_catalog_snapshot`` with the explicit
    ``output_root`` and the explicit timezone-aware ``built_at``, then the
    final verified snapshot read through ``load_verified_dataset_catalog``
    on the materialization's ``snapshot_path``. Every documented failure
    is converted to :class:`DatasetCatalogCLIError` with the ``__cause__``
    preserved; real programming errors pass through.
    """
    try:
        builder_inputs, output_root = _build_inputs(args)
        build_result = build_dataset_catalog(**builder_inputs)
        materialization = materialize_dataset_catalog_snapshot(
            build_result,
            output_root=output_root,
            built_at=args.built_at,
        )
        verified = load_verified_dataset_catalog(
            materialization.snapshot_path
        )
        return _build_success_payload(materialization, verified)
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-catalog-build failed")


def _build_success_payload(
    materialization: DatasetCatalogMaterializationResult,
    verified: VerifiedDatasetCatalogSnapshot,
) -> dict:
    """The fixed ``dataset-catalog-build`` success JSON. Facts come from
    the final verified snapshot (``snapshot_path`` and ``built_at``
    included); ``created_new_snapshot`` is the one fact that comes from
    the materialization result."""
    return {
        "result_schema_version": DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION,
        "cli_contract_version": DATASET_CATALOG_CLI_CONTRACT_VERSION,
        "command": "dataset-catalog-build",
        "result": "SUCCESS",
        "created_new_snapshot": materialization.created_new_snapshot,
        "snapshot_id": verified.snapshot_id,
        "catalog_content_id": verified.catalog_content_id,
        "dataset_count": verified.dataset_count,
        "snapshot_path": verified.snapshot_dir.as_posix(),
        "built_at": _iso_utc_micros(verified.built_at),
        "builder_version": verified.builder_version,
        "materializer_version": verified.manifest.materializer_version,
        "reader_contract_version": verified.reader_contract_version,
    }


def dataset_catalog_build_main(args: argparse.Namespace) -> int:
    try:
        payload = _run_dataset_catalog_build(args)
    except DatasetCatalogCLIError as exc:
        _write_failure("dataset-catalog-build", exc)
        return 1
    _write_stdout(payload)
    return 0


# ---------------------------------------------------------------------------
# dataset-catalog-verify (summary only).
# ---------------------------------------------------------------------------


def _verify_summary(
    command: str, result: str, verified: VerifiedDatasetCatalogSnapshot
) -> dict:
    """The fixed summary shared by ``dataset-catalog-verify`` (never
    carries entries)."""
    return {
        "result_schema_version": DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION,
        "cli_contract_version": DATASET_CATALOG_CLI_CONTRACT_VERSION,
        "command": command,
        "result": result,
        "snapshot_id": verified.snapshot_id,
        "catalog_content_id": verified.catalog_content_id,
        "dataset_count": verified.dataset_count,
        "snapshot_path": verified.snapshot_dir.as_posix(),
        "built_at": _iso_utc_micros(verified.built_at),
        "builder_version": verified.builder_version,
        "materializer_version": verified.manifest.materializer_version,
        "reader_contract_version": verified.reader_contract_version,
    }


def _run_dataset_catalog_verify(snapshot_dir: str) -> VerifiedDatasetCatalogSnapshot:
    try:
        return load_verified_dataset_catalog(
            _coerce_snapshot_dir(snapshot_dir)
        )
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-catalog-verify failed")


def dataset_catalog_verify_main(args: argparse.Namespace) -> int:
    try:
        verified = _run_dataset_catalog_verify(args.snapshot_dir)
    except DatasetCatalogCLIError as exc:
        _write_failure("dataset-catalog-verify", exc)
        return 1
    _write_stdout(_verify_summary("dataset-catalog-verify", "VERIFIED", verified))
    return 0


# ---------------------------------------------------------------------------
# dataset-catalog-list (pure in-memory filtering over verified.entries).
# ---------------------------------------------------------------------------


def _entry_matches_filters(
    entry: DatasetCatalogSnapshotEntryRecord, args: argparse.Namespace
) -> bool:
    """Exact AND semantics over the optional filters.

    ``--status`` / ``--dataset-kind`` / ``--interval`` / ``--adjustment`` /
    ``--requested-session`` compare equality against the stored facts;
    ``--symbol`` is membership in ``scope.symbols``; ``--trade-date`` is
    membership in ``scope.trade_dates``. There is no implicit case folding
    and no fuzzy search; a stored ``None`` requested_session never matches
    a string filter.
    """
    facts = entry.dataset_facts
    if args.status is not None and facts.status != args.status:
        return False
    if (
        args.dataset_kind is not None
        and facts.dataset_kind != args.dataset_kind
    ):
        return False
    if args.symbol is not None and args.symbol not in facts.scope.symbols:
        return False
    if (
        args.trade_date is not None
        and args.trade_date not in facts.scope.trade_dates
    ):
        return False
    if args.interval is not None and facts.scope.interval != args.interval:
        return False
    if (
        args.adjustment is not None
        and facts.scope.adjustment != args.adjustment
    ):
        return False
    if (
        args.requested_session is not None
        and facts.scope.requested_session != args.requested_session
    ):
        return False
    return True


def _filters_payload(args: argparse.Namespace) -> dict:
    """The fixed ``filters`` object: every key always present, unused
    filters ``null``, ``trade_date`` as strict ``YYYY-MM-DD``."""
    return {
        "status": args.status,
        "dataset_kind": args.dataset_kind,
        "symbol": args.symbol,
        "trade_date": (
            args.trade_date.isoformat()
            if args.trade_date is not None
            else None
        ),
        "interval": args.interval,
        "adjustment": args.adjustment,
        "requested_session": args.requested_session,
    }


def _list_summary_entry(entry: DatasetCatalogSnapshotEntryRecord) -> dict:
    """One ``datasets`` item: the discovery summary only (feature pins,
    label pins, canonical pins, and completion belong to
    ``dataset-catalog-show``)."""
    facts = entry.dataset_facts
    scope = facts.scope
    return {
        "dataset_id": entry.dataset_id,
        "content_id": entry.content_id,
        "dataset_kind": facts.dataset_kind,
        "status": facts.status,
        "logical_row_count": facts.logical_row_count,
        "dataset_as_of": (
            _iso_utc_micros(facts.dataset_as_of)
            if facts.dataset_as_of is not None
            else None
        ),
        "scope": {
            "symbols": list(scope.symbols),
            "trade_dates": [trade_date.isoformat() for trade_date in scope.trade_dates],
            "interval": scope.interval,
            "adjustment": scope.adjustment,
            "requested_session": scope.requested_session,
        },
        "recorded_built_at": _iso_utc_micros(entry.recorded_built_at),
        "recorded_build_path": entry.recorded_build_path,
    }


def _run_dataset_catalog_list(args: argparse.Namespace) -> dict:
    """Load the verified snapshot once, filter ``verified.entries`` in
    memory, and slice the page. No file is re-read, no Dataset is
    reloaded, and no order is ever changed."""
    try:
        verified = load_verified_dataset_catalog(
            _coerce_snapshot_dir(args.snapshot_dir)
        )
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-catalog-list failed")
    matched = [
        entry
        for entry in verified.entries
        if _entry_matches_filters(entry, args)
    ]
    page = matched[args.offset : args.offset + args.limit]
    payload = _verify_summary("dataset-catalog-list", "LISTED", verified)
    payload["filters"] = _filters_payload(args)
    payload["matched_count"] = len(matched)
    payload["offset"] = args.offset
    payload["limit"] = args.limit
    payload["returned_count"] = len(page)
    payload["datasets"] = [_list_summary_entry(entry) for entry in page]
    return payload


def dataset_catalog_list_main(args: argparse.Namespace) -> int:
    try:
        payload = _run_dataset_catalog_list(args)
    except DatasetCatalogCLIError as exc:
        _write_failure("dataset-catalog-list", exc)
        return 1
    _write_stdout(payload)
    return 0


# ---------------------------------------------------------------------------
# dataset-catalog-show (exact dataset_id lookup, full typed facts).
# ---------------------------------------------------------------------------


def _spec_pin_json(pin) -> dict:
    return {
        "kind": pin.kind,
        "name": pin.name,
        "version": pin.version,
        "content_sha256": pin.content_sha256,
    }


def _source_snapshot_json(snapshot) -> dict:
    return {
        "ingestion_run_id": snapshot.ingestion_run_id,
        "physical_snapshot_hash": snapshot.physical_snapshot_hash,
        "logical_source_rows_hash": snapshot.logical_source_rows_hash,
        "source_schema_version": snapshot.source_schema_version,
        "requested_trade_date": snapshot.requested_trade_date.isoformat(),
        "requested_session": snapshot.requested_session,
    }


def _canonical_build_pin_json(pin) -> dict:
    return {
        "canonical_build_id": pin.canonical_build_id,
        "canonical_content_id": pin.canonical_content_id,
        "canonical_builder_version": pin.canonical_builder_version,
        "canonical_schema_version": pin.canonical_schema_version,
        "materializer_version": pin.materializer_version,
        "gap_policy_version": pin.gap_policy_version,
        "gap_content_id": pin.gap_content_id,
        "status": pin.status,
        "canonical_row_version_ids": list(pin.canonical_row_version_ids),
        "source_snapshots": [
            _source_snapshot_json(snapshot) for snapshot in pin.source_snapshots
        ],
    }


def _completion_entry_json(entry) -> dict:
    return {
        "code": entry.code,
        "trade_date": entry.trade_date.isoformat(),
        "status": entry.status,
        "reason_code": entry.reason_code,
    }


def _completion_json(completion) -> dict:
    return {
        "complete_count": completion.complete_count,
        "incomplete_count": completion.incomplete_count,
        "missing_count": completion.missing_count,
        "entries": [
            _completion_entry_json(entry) for entry in completion.entries
        ],
    }


def _scope_json(scope) -> dict:
    return {
        "symbols": list(scope.symbols),
        "trade_dates": [trade_date.isoformat() for trade_date in scope.trade_dates],
        "interval": scope.interval,
        "adjustment": scope.adjustment,
        "requested_session": scope.requested_session,
    }


def _facts_json(facts) -> dict:
    """The complete lossless 14-field PR-5 facts record (typed objects to
    JSON only; nothing is re-read or re-parsed)."""
    return {
        "dataset_id": facts.dataset_id,
        "dataset_kind": facts.dataset_kind,
        "status": facts.status,
        "logical_row_count": facts.logical_row_count,
        "dataset_schema_id": facts.dataset_schema_id,
        "logical_dataset_content_id": facts.logical_dataset_content_id,
        "dataset_as_of": (
            _iso_utc_micros(facts.dataset_as_of)
            if facts.dataset_as_of is not None
            else None
        ),
        "scope": _scope_json(facts.scope),
        "feature_spec_pins": [
            _spec_pin_json(pin) for pin in facts.feature_spec_pins
        ],
        "label_spec_pins": [
            _spec_pin_json(pin) for pin in facts.label_spec_pins
        ],
        "split_spec_pin": (
            _spec_pin_json(facts.split_spec_pin)
            if facts.split_spec_pin is not None
            else None
        ),
        "canonical_build_pins": [
            _canonical_build_pin_json(pin) for pin in facts.canonical_build_pins
        ],
        "canonical_row_version_ids": list(facts.canonical_row_version_ids),
        "completion": _completion_json(facts.completion),
    }


def _dataset_record_json(entry: DatasetCatalogSnapshotEntryRecord) -> dict:
    """The complete lossless verified entry. ``recorded_build_path`` is
    historical text and is never turned back into a live ``Path`` and
    never accessed."""
    return {
        "content_id": entry.content_id,
        "dataset_facts": _facts_json(entry.dataset_facts),
        "observed_metadata": {
            "built_at": _iso_utc_micros(entry.recorded_built_at),
            "build_path": entry.recorded_build_path,
        },
    }


def _run_dataset_catalog_show(args: argparse.Namespace) -> dict:
    try:
        verified = load_verified_dataset_catalog(
            _coerce_snapshot_dir(args.snapshot_dir)
        )
    except _DOCUMENTED_ERRORS as exc:
        _as_cli_error(exc, "dataset-catalog-show failed")
    for entry in verified.entries:
        if entry.dataset_id == args.dataset_id:
            payload = _verify_summary("dataset-catalog-show", "SHOWN", verified)
            payload["dataset"] = _dataset_record_json(entry)
            return payload
    raise DatasetCatalogCLIError(
        f"--dataset-id was not found in the verified Dataset Catalog "
        f"snapshot: {args.dataset_id}"
    )


def dataset_catalog_show_main(args: argparse.Namespace) -> int:
    try:
        payload = _run_dataset_catalog_show(args)
    except DatasetCatalogCLIError as exc:
        _write_failure("dataset-catalog-show", exc)
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
    """The only stdout writer of the Dataset Catalog commands: exactly one
    JSON object with fixed key order, ``ensure_ascii=False``, indent 2, and
    a trailing newline. No progress, warning, or debug text is ever mixed
    in; no current-time or machine facts are ever emitted."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_failure(command: str, exc: DatasetCatalogCLIError) -> None:
    """The fixed FAILED JSON on stderr (stdout stays empty; exit code 1 is
    returned by the caller)."""
    sys.stderr.write(
        json.dumps(
            {
                "result_schema_version": DATASET_CATALOG_CLI_RESULT_SCHEMA_VERSION,
                "cli_contract_version": DATASET_CATALOG_CLI_CONTRACT_VERSION,
                "command": command,
                "result": "FAILED",
                "error_type": "DatasetCatalogCLIError",
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
