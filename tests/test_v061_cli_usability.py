"""Offline deterministic CLI / help / error wording freeze (v0.6.1 PR-2).

Freezes the unchanged formal CLI surface of the exact 8-command set while
the v0.6.1 PR-2 wording polish is applied:

- the exact command sets (``DATASET_COMMANDS``, ``SAMPLE_GENERATION_COMMANDS``,
  ``DATASET_CATALOG_COMMANDS``) and the absence of ``dataset-catalog-query``;
- the exact business option set of every one of the 8 commands (``-h`` /
  ``--help`` excluded);
- the fixed defaults (``dataset-inspect`` / ``dataset-catalog-list``
  ``--offset`` 0 and ``--limit`` 20) and the fixed build candidate-mode
  mutual exclusion (exactly one mode);
- the stable help substrings introduced by the PR-2 wording polish
  (``--settings`` ignored behavior, "final Dataset build directory",
  "Dataset Catalog snapshot directory", "current time is never used",
  "repeatable and mutually exclusive with --dataset-root", "Zero-based entry
  offset", "exact Dataset ID");
- the error wording (argparse stage, exit code 2, stderr carries the real
  option spellings ``--built-at`` / ``--trade-date`` / ``--dataset-id``; the
  missing ``--dataset-id`` documented failure keeps the exit 1 / stdout
  empty / stderr JSON / ``DatasetCatalogCLIError`` contract and mentions
  ``--dataset-id``).

All help smoke tests (top-level plus the 8 commands) exit 0. No product
capability, command, business argument, default, exit-code semantics, or
JSON schema is asserted to change; these tests freeze what PR-2 must not
change and what its wording must say.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from market_vault import cli as cli_module
from market_vault.dataset.cli import DATASET_COMMANDS
from market_vault.dataset.dataset_catalog_cli import DATASET_CATALOG_COMMANDS
from market_vault.dataset.sample_generation_cli import SAMPLE_GENERATION_COMMANDS

ROOT = Path(__file__).resolve().parents[1]

CATALOG_BUILT_AT = "2026-08-07T12:34:56+00:00"


def run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    try:
        code = cli_module.main(argv)
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _command_parser(name: str) -> argparse.ArgumentParser:
    parser = cli_module.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices[name]


def _business_options(name: str) -> frozenset:
    """The exact business option set of one command, ``-h`` / ``--help``
    excluded."""
    return frozenset(
        option
        for action in _command_parser(name)._actions
        for option in action.option_strings
        if action.dest != "help"
    )


def _option_default(name: str, dest: str):
    for action in _command_parser(name)._actions:
        if action.dest == dest:
            return action.default
    raise AssertionError(f"option {dest!r} not found in {name}")


def _help_stdout(argv: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(argv)
    assert excinfo.value.code == 0
    return capsys.readouterr().out


def _normalized(text: str) -> str:
    """Collapse argparse's column wrapping: whitespace runs -> one space.

    Wording assertions run against the normalized text so a phrase survives
    a wrap point, while the exact words and their order stay pinned.
    """
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Section 21. The exact 8-command formal set is frozen; no
# dataset-catalog-query.
# ---------------------------------------------------------------------------


def test_formal_command_sets_unchanged():
    assert DATASET_COMMANDS == frozenset(
        {"dataset-build", "dataset-verify", "dataset-inspect"}
    )
    assert SAMPLE_GENERATION_COMMANDS == frozenset({"sample-generate"})
    assert DATASET_CATALOG_COMMANDS == frozenset(
        {
            "dataset-catalog-build",
            "dataset-catalog-verify",
            "dataset-catalog-list",
            "dataset-catalog-show",
        }
    )


def test_no_dataset_catalog_query_command(capsys):
    assert "dataset-catalog-query" not in DATASET_CATALOG_COMMANDS
    assert "dataset-catalog-query" not in DATASET_COMMANDS
    assert "dataset-catalog-query" not in SAMPLE_GENERATION_COMMANDS
    out = _help_stdout(["--help"], capsys)
    assert "dataset-catalog-query" not in out


# ---------------------------------------------------------------------------
# Section 22. Exact business option sets per command.
# ---------------------------------------------------------------------------


def test_dataset_build_business_options_exact():
    assert _business_options("dataset-build") == {"--plan"}


def test_dataset_verify_business_options_exact():
    assert _business_options("dataset-verify") == {"--build-dir"}


def test_dataset_inspect_business_options_exact():
    assert _business_options("dataset-inspect") == {
        "--build-dir",
        "--offset",
        "--limit",
    }


def test_sample_generate_business_options_exact():
    assert _business_options("sample-generate") == {"--plan"}


def test_dataset_catalog_build_business_options_exact():
    assert _business_options("dataset-catalog-build") == {
        "--dataset-root",
        "--candidate-build-dir",
        "--output-root",
        "--built-at",
    }


def test_dataset_catalog_verify_business_options_exact():
    assert _business_options("dataset-catalog-verify") == {"--snapshot-dir"}


def test_dataset_catalog_list_business_options_exact():
    assert _business_options("dataset-catalog-list") == {
        "--snapshot-dir",
        "--status",
        "--dataset-kind",
        "--symbol",
        "--trade-date",
        "--interval",
        "--adjustment",
        "--requested-session",
        "--offset",
        "--limit",
    }


def test_dataset_catalog_show_business_options_exact():
    assert _business_options("dataset-catalog-show") == {
        "--snapshot-dir",
        "--dataset-id",
    }


# ---------------------------------------------------------------------------
# Section 23. Fixed defaults and the fixed candidate-mode mutual exclusion.
# ---------------------------------------------------------------------------


def test_dataset_inspect_pagination_defaults():
    assert _option_default("dataset-inspect", "offset") == 0
    assert _option_default("dataset-inspect", "limit") == 20


def test_dataset_catalog_list_pagination_defaults():
    assert _option_default("dataset-catalog-list", "offset") == 0
    assert _option_default("dataset-catalog-list", "limit") == 20


def test_dataset_build_accepts_only_plan():
    args = cli_module.build_parser().parse_args(
        ["dataset-build", "--plan", "plan.json"]
    )
    assert args.plan == "plan.json"
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(
            ["dataset-build", "--plan", "plan.json", "--build-dir", "d"]
        )
    assert excinfo.value.code == 2


def test_sample_generate_accepts_only_plan():
    args = cli_module.build_parser().parse_args(
        ["sample-generate", "--plan", "plan.json"]
    )
    assert args.plan == "plan.json"
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(
            ["sample-generate", "--plan", "plan.json", "--output-root", "o"]
        )
    assert excinfo.value.code == 2


def test_catalog_build_requires_exactly_one_candidate_mode():
    common = ["--output-root", "o", "--built-at", CATALOG_BUILT_AT]
    # Neither candidate mode -> exit 2 (required group).
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(["dataset-catalog-build", *common])
    assert excinfo.value.code == 2
    # Both candidate modes -> exit 2 (mutual exclusion).
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(
            [
                "dataset-catalog-build",
                "--dataset-root",
                "r",
                "--candidate-build-dir",
                "c",
                *common,
            ]
        )
    assert excinfo.value.code == 2
    # Exactly one mode parses; the repeated candidate is repeatable.
    args = cli_module.build_parser().parse_args(
        ["dataset-catalog-build", "--dataset-root", "r", *common]
    )
    assert args.dataset_root == "r"
    assert args.candidate_build_dir is None
    args = cli_module.build_parser().parse_args(
        [
            "dataset-catalog-build",
            "--candidate-build-dir",
            "c1",
            "--candidate-build-dir",
            "c2",
            *common,
        ]
    )
    assert args.candidate_build_dir == ["c1", "c2"]


# ---------------------------------------------------------------------------
# Section 24. Stable help substrings (the PR-2 wording).
# ---------------------------------------------------------------------------


def test_help_smoke_all_nine_exit_zero(capsys):
    for argv in (
        ["--help"],
        ["dataset-build", "--help"],
        ["dataset-verify", "--help"],
        ["dataset-inspect", "--help"],
        ["sample-generate", "--help"],
        ["dataset-catalog-build", "--help"],
        ["dataset-catalog-verify", "--help"],
        ["dataset-catalog-list", "--help"],
        ["dataset-catalog-show", "--help"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            cli_module.build_parser().parse_args(argv)
        assert excinfo.value.code == 0


def test_help_wording_settings_ignored(capsys):
    out = _normalized(_help_stdout(["--help"], capsys))
    assert "Settings file for settings-backed commands" in out
    assert (
        "Dataset, Sample Generation, and Dataset Catalog commands ignore it"
    ) in out


def test_help_wording_dataset_build_plan(capsys):
    out = _normalized(_help_stdout(["dataset-build", "--help"], capsys))
    assert "Path to the versioned Dataset build-plan JSON" in out
    assert "all Dataset build inputs are declared in the plan" in out


def test_help_wording_final_dataset_build_directory(capsys):
    for command in ("dataset-verify", "dataset-inspect"):
        out = _normalized(_help_stdout([command, "--help"], capsys))
        assert "final Dataset build directory" in out
        assert "(<output_root>/<dataset_id>)" in out


def test_help_wording_zero_based_row_offset(capsys):
    out = _normalized(_help_stdout(["dataset-inspect", "--help"], capsys))
    assert (
        "Zero-based row offset (default 0; rows are sliced, never reordered)"
    ) in out


def test_help_wording_sample_generation_plan(capsys):
    out = _normalized(_help_stdout(["sample-generate", "--help"], capsys))
    assert "Path to the versioned Sample Generation plan JSON" in out
    assert "all generation inputs are declared in the plan" in out


def test_help_wording_top_level_command_summaries(capsys):
    out = _normalized(_help_stdout(["--help"], capsys))
    assert (
        "Build one immutable Dataset from an explicit versioned build plan"
    ) in out
    assert "Verify one committed immutable Dataset build directory" in out
    assert "Inspect one verified immutable Dataset build directory" in out
    assert (
        "Build one immutable Dataset Catalog snapshot from explicit "
        "Dataset candidates"
    ) in out
    assert "Verify one immutable Dataset Catalog snapshot" in out
    assert (
        "List entries from one verified Dataset Catalog snapshot with "
        "read-only filters and pagination"
    ) in out
    assert (
        "Show one entry from one verified Dataset Catalog snapshot by "
        "exact Dataset ID"
    ) in out


def test_help_wording_catalog_build(capsys):
    out = _normalized(_help_stdout(["dataset-catalog-build", "--help"], capsys))
    assert "Explicit bounded Dataset discovery root" in out
    assert "repeatable and mutually exclusive with --dataset-root" in out
    assert (
        "Explicit parent directory for the committed Dataset Catalog "
        "snapshot"
    ) in out
    assert "Explicit timezone-aware Dataset Catalog snapshot build instant" in out
    assert "current time is never used" in out


def test_help_wording_catalog_snapshot_directory(capsys):
    for command in (
        "dataset-catalog-verify",
        "dataset-catalog-list",
        "dataset-catalog-show",
    ):
        out = _normalized(_help_stdout([command, "--help"], capsys))
        assert "Explicit final Dataset Catalog snapshot directory" in out
        assert "(<output_root>/<snapshot_id>)" in out


def test_help_wording_catalog_list_filters_and_pagination(capsys):
    out = _normalized(_help_stdout(["dataset-catalog-list", "--help"], capsys))
    assert "Exact Dataset status filter (COMPLETE or EMPTY)" in out
    assert "Exact Dataset kind filter" in out
    assert "symbol must be present in Dataset scope.symbols" in out
    assert "date must be present in Dataset scope.trade_dates" in out
    assert "Exact Dataset scope.interval filter" in out
    assert "Exact Dataset scope.adjustment filter" in out
    assert "Exact Dataset scope.requested_session filter" in out
    assert "a stored null never matches" in out
    assert (
        "Zero-based entry offset (default 0; entries are sliced, never "
        "reordered)"
    ) in out


def test_help_wording_catalog_show(capsys):
    out = _normalized(_help_stdout(["dataset-catalog-show", "--help"], capsys))
    assert "Exact 64-character lowercase dataset_id" in out
    assert "(^[0-9a-f]{64}$)" in out


# ---------------------------------------------------------------------------
# Section 25. Error wording: argparse stage exit 2 with the real option
# spellings; the missing --dataset-id documented failure keeps the exit 1
# JSON contract.
# ---------------------------------------------------------------------------


def _parse_args_exit_two(argv: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as excinfo:
        cli_module.build_parser().parse_args(argv)
    assert excinfo.value.code == 2
    return capsys.readouterr().err


def test_catalog_built_at_naive_exit_two_wording(capsys):
    err = _parse_args_exit_two(
        [
            "dataset-catalog-build",
            "--dataset-root",
            "r",
            "--output-root",
            "o",
            "--built-at",
            "2026-08-07T12:00:00",
        ],
        capsys,
    )
    assert "--built-at must be timezone-aware; naive datetimes are rejected" in err


def test_catalog_built_at_bad_format_exit_two_wording(capsys):
    err = _parse_args_exit_two(
        [
            "dataset-catalog-build",
            "--dataset-root",
            "r",
            "--output-root",
            "o",
            "--built-at",
            "not-a-datetime",
        ],
        capsys,
    )
    assert (
        "--built-at must be an ISO 8601 datetime (e.g. "
        "2026-08-07T12:34:56+00:00)"
    ) in err


def test_catalog_trade_date_bad_format_exit_two_wording(capsys):
    err = _parse_args_exit_two(
        [
            "dataset-catalog-list",
            "--snapshot-dir",
            "s",
            "--trade-date",
            "2026/01/01",
        ],
        capsys,
    )
    assert "--trade-date must use the strict format YYYY-MM-DD" in err


def test_catalog_trade_date_invalid_calendar_exit_two_wording(capsys):
    err = _parse_args_exit_two(
        [
            "dataset-catalog-list",
            "--snapshot-dir",
            "s",
            "--trade-date",
            "2026-13-01",
        ],
        capsys,
    )
    assert (
        "--trade-date must be a valid calendar date, got '2026-13-01'"
    ) in err


def test_catalog_dataset_id_invalid_exit_two_wording(capsys):
    err = _parse_args_exit_two(
        [
            "dataset-catalog-show",
            "--snapshot-dir",
            "s",
            "--dataset-id",
            "abc",
        ],
        capsys,
    )
    assert (
        "--dataset-id must be a 64-character lowercase SHA-256 hexadecimal "
        "string"
    ) in err


def test_catalog_offset_negative_exit_two(capsys):
    _parse_args_exit_two(
        [
            "dataset-catalog-list",
            "--snapshot-dir",
            "s",
            "--offset",
            "-1",
        ],
        capsys,
    )


def test_catalog_limit_above_1000_exit_two(capsys):
    _parse_args_exit_two(
        [
            "dataset-catalog-list",
            "--snapshot-dir",
            "s",
            "--limit",
            "1001",
        ],
        capsys,
    )


def test_catalog_show_missing_dataset_id_failure_json(tmp_path, capsys):
    """Real E2E: build an empty snapshot, then show a valid-shaped missing
    id. Exit 1, stdout empty, stderr JSON with the unchanged
    ``DatasetCatalogCLIError`` contract and the ``--dataset-id`` spelling."""
    empty_root = tmp_path / "empty-root"
    empty_root.mkdir()
    code, out, err = run_cli(
        [
            "dataset-catalog-build",
            "--dataset-root",
            str(empty_root),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--built-at",
            CATALOG_BUILT_AT,
        ],
        capsys,
    )
    assert code == 0, err
    payload = json.loads(out)
    assert payload["result"] == "SUCCESS"
    assert payload["dataset_count"] == 0

    missing = "0" * 64
    code, out, err = run_cli(
        [
            "dataset-catalog-show",
            "--snapshot-dir",
            payload["snapshot_path"],
            "--dataset-id",
            missing,
        ],
        capsys,
    )
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["result"] == "FAILED"
    assert failure["error_type"] == "DatasetCatalogCLIError"
    assert failure["command"] == "dataset-catalog-show"
    assert "--dataset-id" in failure["error"]
    assert (
        "not found in the verified Dataset Catalog snapshot"
    ) in failure["error"]
