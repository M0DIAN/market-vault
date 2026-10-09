#!/usr/bin/env python3
"""Run the complete Python 3.11 suite in six functional partitions.

The registry assigns files, never individual assertions or markers. Every
discovered test file must have one owner. Jobs retain the complete checkout so
existing imports of helpers and fixtures from other test files keep working.
The classifier and verified-reuse decision remain owned by the existing CI
scripts; this module only validates their plan and the partition results.
"""

from __future__ import annotations

import argparse
from collections import Counter
import fnmatch
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tomllib


PARTITION_NAMES = (
    "data", "dataset_features", "strategy", "intraday_research",
    "intraday_final", "app_ops",
)
REGISTRY_REL = Path("ci/test_partitions.toml")
FAST_TIERS = frozenset({"docs_fast", "package_docs", "control_plane", "research_fast"})
VALID_TIERS = FAST_TIERS | {"full"}


def load_partitions(repo: Path) -> dict[str, tuple[str, ...]]:
    """Resolve the checked-in file ownership rules, rejecting gaps/overlaps."""
    registry = tomllib.loads((repo / REGISTRY_REL).read_text(encoding="utf-8"))
    if (
        set(registry) != {"schema_version", "partitions"}
        or type(registry["schema_version"]) is not int
        or registry["schema_version"] != 1
    ):
        raise ValueError("invalid partition registry schema")
    rules = registry["partitions"]
    if not isinstance(rules, dict) or set(rules) != set(PARTITION_NAMES):
        raise ValueError("partition registry must contain exactly the six named partitions")
    config = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    options = config.get("tool", {}).get("pytest", {}).get("ini_options", {})
    if options.get("testpaths") != ["tests"] or any(
        key in options for key in ("python_files", "addopts", "norecursedirs")
    ):
        raise ValueError("partition discovery requires the existing tests/default pytest discovery contract")
    discovered = sorted(
        path.relative_to(repo).as_posix()
        for path in (repo / "tests").rglob("*.py")
        if path.is_file() and (
            fnmatch.fnmatchcase(path.name, "test_*.py")
            or fnmatch.fnmatchcase(path.name, "*_test.py")
        )
    )
    if not discovered:
        raise ValueError("no test files discovered")
    discovered_names = {PurePosixPath(path).name for path in discovered}
    exact: dict[str, str] = {}
    prefixes: dict[str, list[str]] = {}
    for name in PARTITION_NAMES:
        rule = rules[name]
        if not isinstance(rule, dict) or set(rule) != {"files", "prefixes"}:
            raise ValueError(f"invalid rule for {name}")
        for field in ("files", "prefixes"):
            values = rule[field]
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValueError(f"invalid {field} for {name}")
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate {field} for {name}")
        for filename in rule["files"]:
            if PurePosixPath(filename).name != filename or filename not in discovered_names:
                raise ValueError(f"unknown explicit test file: {filename}")
            if filename in exact:
                raise ValueError(f"duplicate file ownership: {filename}")
            exact[filename] = name
        prefixes[name] = rule["prefixes"]
        if any(not value.startswith("test_") or any(c in value for c in "/*?[]") for value in prefixes[name]):
            raise ValueError(f"invalid test filename prefix for {name}")
    resolved: dict[str, list[str]] = {name: [] for name in PARTITION_NAMES}
    for relative in discovered:
        filename = PurePosixPath(relative).name
        owners = [exact[filename]] if filename in exact else [
            name for name in PARTITION_NAMES
            if any(filename.startswith(prefix) for prefix in prefixes[name])
        ]
        if len(owners) != 1:
            raise ValueError(f"test file must have exactly one owner: {relative} ({owners})")
        resolved[owners[0]].append(relative)
    if any(not files for files in resolved.values()):
        raise ValueError("every partition must contain tests")
    counts = Counter(path for files in resolved.values() for path in files)
    if set(counts) != set(discovered) or any(count != 1 for count in counts.values()):
        raise ValueError("partition union differs from discovered test files")
    return {name: tuple(files) for name, files in resolved.items()}


def execution_plan(tier: str, reuse: str, full_matrix_required: str) -> dict[str, str]:
    """Normalize incomplete decisions to FULL, never to a smaller test set."""
    if (
        tier not in VALID_TIERS
        or reuse not in {"true", "false", ""}
        or full_matrix_required != ("true" if tier == "full" else "false")
        or (reuse == "true" and tier != "full")
    ):
        tier, reuse = "full", "false"
    return {
        "tier": tier,
        "reuse": "true" if reuse == "true" else "false",
        "full_matrix_required": "true" if tier == "full" else "false",
        "run_partitions": "true" if tier == "full" and reuse != "true" else "false",
    }


def verify_results(plan_result: str, partition_result: str, tier: str, reuse: str,
                   full_matrix_required: str) -> None:
    """The stable test check must reject failed or unexpectedly skipped work."""
    if plan_result != "success":
        raise ValueError(f"CI plan did not succeed: {plan_result}")
    plan = execution_plan(tier, reuse, full_matrix_required)
    if (plan["tier"], plan["reuse"], plan["full_matrix_required"]) != (
        tier, reuse, full_matrix_required
    ):
        raise ValueError("CI plan outputs are incomplete or inconsistent")
    expected = "success" if plan["run_partitions"] == "true" else "skipped"
    if partition_result != expected:
        raise ValueError(f"partition result must be {expected}, got {partition_result}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "run", "plan", "verify"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--partition", choices=PARTITION_NAMES)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            values = execution_plan(os.environ.get("CI_TIER", ""),
                                    os.environ.get("POST_MERGE_REUSE", ""),
                                    os.environ.get("CI_FULL_MATRIX_REQUIRED", ""))
            output = "".join(f"{key}={value}\n" for key, value in values.items())
            print(output, end="")
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write(output)
            return 0
        if args.command == "verify":
            verify_results(os.environ.get("CI_PLAN_RESULT", ""),
                           os.environ.get("CI_PARTITIONS_RESULT", ""),
                           os.environ.get("CI_TIER", ""),
                           os.environ.get("POST_MERGE_REUSE", ""),
                           os.environ.get("CI_FULL_MATRIX_REQUIRED", ""))
            print("PY311_PARTITION_RESULTS_OK")
            return 0
        partitions = load_partitions(args.repo)
        if args.command == "validate":
            for name, files in partitions.items():
                print(f"{name}={len(files)}")
            print(f"PY311_PARTITION_FILE_COUNT={sum(map(len, partitions.values()))}")
            print("PY311_PARTITION_COVERAGE_OK")
            return 0
        if args.partition is None:
            raise ValueError("run requires --partition")
        if os.environ.get("PYTEST_ADDOPTS", "").strip():
            raise ValueError("PYTEST_ADDOPTS must be empty: partitions cannot inherit test filters or collect-only")
        files = partitions[args.partition]
        print(f"PY311_PARTITION={args.partition} FILE_COUNT={len(files)}", flush=True)
        command = [sys.executable, "-m", "pytest", *files, "-q", "--durations=50"]
        if args.collect_only:
            command.append("--collect-only")
        return subprocess.run(command, cwd=args.repo, check=False).returncode
    except (ValueError, OSError, KeyError) as exc:
        print(f"PY311_PARTITION_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
