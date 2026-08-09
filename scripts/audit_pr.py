#!/usr/bin/env python3
"""MarketVault automated PR scope audit (DP2).

Read-only, deterministic audit of the changed-file set between two git
refs against an explicit allowlist scope policy.

This tool replaces the mechanical parts of a manual scope audit. It does
NOT replace independent review.

Properties:
- explicit --base and --head refs; never assumes ``main``
- no network, no GitHub API
- read-only: never modifies the repository (no stash/reset/merge/branch
  changes)
- fail closed: invalid refs or git failures are errors, never PASS

Usage (run from the repository root, or pass --repo):

    python scripts/audit_pr.py \\
        --base <GIT_REF> \\
        --head <GIT_REF> \\
        --allow <PATH_OR_PREFIX> ...

Exit codes:
    0 = audit PASS (every changed path matches an allow rule)
    1 = audit FAIL (scope violations; all violations are reported)
    2 = usage / git resolution error
"""

import argparse
import os
import subprocess
import sys

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

PRODUCT_SRC_DEFAULT = "src/market_vault/"
WORKFLOW_DIR = ".github/workflows/"
TESTS_DIR = "tests/"
PYPROJECT_FILE = "pyproject.toml"
DOCS_DIR = "docs/"


class AuditError(Exception):
    """Usage or git resolution error: the audit cannot run."""


def _git(repo: str, *args: str) -> str:
    env = dict(os.environ, LC_ALL="C")
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "-c", "core.quotepath=false", *args],
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        raise AuditError("git executable not found")
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "(no stderr)"
        raise AuditError(f"git command failed: git {' '.join(args)}\n{stderr}")
    return proc.stdout


def resolve_ref(repo: str, ref: str) -> None:
    """Fail closed when the ref does not exist in the repository."""
    _git(repo, "rev-parse", "--verify", "--quiet", ref)


def changed_paths(repo: str, base: str, head: str, merge_base: bool = True) -> list[str]:
    """Resolve the exact changed-file list between two refs.

    With ``merge_base=True`` (the default) the diff is the three-dot
    merge-base diff ``base...head``; with ``merge_base=False`` it is the
    direct tree diff ``base head``. pull_request ranges use the
    merge-base diff; push ranges use the direct diff of the pushed
    range.

    Renames (R<similarity> old new) contribute BOTH the old and the new
    path so a rename can never escape the scope audit.
    """
    if merge_base:
        diff_args = [f"{base}...{head}"]
    else:
        diff_args = [base, head]
    out = _git(repo, "diff", "--name-status", "-M", *diff_args)
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R") and len(parts) == 3:
            paths.append(parts[1])
            paths.append(parts[2])
        elif len(parts) == 2:
            paths.append(parts[1])
        else:
            raise AuditError(f"unparseable git diff line: {line!r}")
    return list(dict.fromkeys(paths))


def rule_matches(rule: str, path: str) -> bool:
    """Exact file match or directory-prefix match.

    A rule matches a path when the path equals the rule or the path
    starts with rule + "/". Trailing slashes in the rule are ignored.
    There is no substring / fuzzy matching: the rule "script" does NOT
    match "scripts/audit_pr.py".
    """
    rule = rule.rstrip("/")
    return path == rule or path.startswith(rule + "/")


def violations(paths: list[str], rules: list[str]) -> list[str]:
    return [p for p in paths if not any(rule_matches(r, p) for r in rules)]


def compute_flags(paths: list[str], product_src: str) -> dict[str, bool]:
    product_prefix = product_src.rstrip("/") + "/"
    return {
        "docs_only": bool(paths) and all(
            p.startswith(DOCS_DIR) or p.endswith(".md") for p in paths
        ),
        "product_src_changed": any(p.startswith(product_prefix) for p in paths),
        "pyproject_changed": any(p == PYPROJECT_FILE for p in paths),
        "workflow_changed": any(p.startswith(WORKFLOW_DIR) for p in paths),
        "tests_changed": any(p.startswith(TESTS_DIR) for p in paths),
    }


def _flag_text(value: bool) -> str:
    return "true" if value else "false"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_pr.py",
        description=(
            "Deterministic, read-only PR scope audit: resolves the changed-file "
            "list between --base and --head and checks it against --allow rules."
        ),
    )
    parser.add_argument("--base", required=True, metavar="GIT_REF",
                        help="base git ref (e.g. exact base SHA)")
    parser.add_argument("--head", required=True, metavar="GIT_REF",
                        help="head git ref (e.g. HEAD)")
    parser.add_argument("--allow", action="append", default=[], metavar="PATH_OR_PREFIX",
                        help="allowed path or directory prefix; repeatable")
    parser.add_argument("--product-src", default=PRODUCT_SRC_DEFAULT, metavar="PREFIX",
                        help=f"product source prefix (default: {PRODUCT_SRC_DEFAULT})")
    parser.add_argument("--repo", default=".", metavar="PATH",
                        help="repository root (default: current directory)")
    args = parser.parse_args(argv)

    try:
        resolve_ref(args.repo, args.base)
        resolve_ref(args.repo, args.head)
        paths = changed_paths(args.repo, args.base, args.head)
    except AuditError as exc:
        print("AUDIT_PR_FAILED")
        print(f"error={exc}")
        return EXIT_USAGE

    flags = compute_flags(paths, args.product_src)
    bad = violations(paths, args.allow)

    if bad:
        print("AUDIT_PR_FAILED")
    else:
        print("AUDIT_PR_OK")
    print(f"base={args.base}")
    print(f"head={args.head}")
    print(f"changed_files={len(paths)}")
    for key in ("docs_only", "product_src_changed", "pyproject_changed",
                "workflow_changed", "tests_changed"):
        print(f"{key}={_flag_text(flags[key])}")
    print("files:")
    for path in paths:
        print(f"- {path}")
    if bad:
        print("scope violations:")
        for path in bad:
            print(f"- {path}")
        print("scope=FAIL")
        return EXIT_FAIL
    print("scope=PASS")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
