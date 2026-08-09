#!/usr/bin/env python3
"""MarketVault CI risk-tier classifier (CI Risk-Tier Optimization Phase 1).

Deterministic, read-only classification of a change range into one of
three conservative tiers:

- docs_fast:    every changed path is inside the docs/policy scope
                (docs/**, DEVELOPMENT_PLAYBOOK.md, RELEASE_PLAYBOOK.md,
                AGENT_HANDOFF.md)
- package_docs: every changed path is in the docs scope OR README.md,
                and README.md itself changed (README is package
                metadata-sensitive: pyproject.toml ``readme``)
- full:         anything else, including empty diffs and any condition
                that prevents reliable classification

Fail-safe: an empty diff, an unresolvable ref, or any git failure
yields tier=full (or a non-zero exit the workflow converts to full).
Unknown / unset tiers in the workflow behave as full.

Properties:
- explicit --base and --head refs; never assumes a branch
- --mode pull_request: merge-base-correct three-dot diff (base...head)
- --mode push: direct tree diff of the pushed range (base head)
- no network, no GitHub API
- read-only: never modifies the repository
- no shell=True, no eval

Usage (run from the repository root, or pass --repo):

    python scripts/ci_risk_tier.py \\
        --mode pull_request --base <GIT_REF> --head <GIT_REF>
    python scripts/ci_risk_tier.py \\
        --mode push --base <GIT_REF> --head <GIT_REF>

Output:

    tier=docs_fast|package_docs|full
    reason=<short stable explanation>
    changed_files=<count>
    files:
    - <path>
    ...

Exit codes:
    0 = classification completed (any tier, including full)
    2 = usage / git resolution error (workflow converts to tier=full)
"""

import argparse
import sys

from audit_pr import AuditError, changed_paths, resolve_ref, violations

EXIT_OK = 0
EXIT_USAGE = 2

# DOCS_FAST scope: docs/ plus the three top-level policy playbooks.
DOCS_SCOPE_RULES = [
    "docs/",
    "DEVELOPMENT_PLAYBOOK.md",
    "RELEASE_PLAYBOOK.md",
    "AGENT_HANDOFF.md",
]
README_FILE = "README.md"

TIER_DOCS_FAST = "docs_fast"
TIER_PACKAGE_DOCS = "package_docs"
TIER_FULL = "full"


def classify(paths: list[str]) -> tuple[str, str]:
    """Return (tier, reason) for a changed-path list.

    Empty diff is FULL: a fast path is never claimed without evidence.
    Renames are already handled by the caller: both the old and the new
    path are in ``paths``, so a rename into or out of the docs scope
    classifies by both paths.
    """
    if not paths:
        return TIER_FULL, "empty_diff"
    bad = violations(paths, [*DOCS_SCOPE_RULES, README_FILE])
    if bad:
        return TIER_FULL, "changed_path_not_in_docs_scope"
    if README_FILE in paths:
        return TIER_PACKAGE_DOCS, "readme_changed_in_docs_scope"
    return TIER_DOCS_FAST, "all_changes_in_docs_scope"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_risk_tier.py",
        description=(
            "Deterministic, read-only CI risk-tier classification of a "
            "change range between --base and --head."
        ),
    )
    parser.add_argument("--repo", default=".", metavar="PATH",
                        help="repository root (default: current directory)")
    parser.add_argument("--mode", required=True, choices=("pull_request", "push"),
                        help="pull_request uses the merge-base-correct three-dot "
                             "diff; push uses the direct tree diff")
    parser.add_argument("--base", required=True, metavar="GIT_REF",
                        help="base git ref (PR base SHA / push 'before' SHA)")
    parser.add_argument("--head", required=True, metavar="GIT_REF",
                        help="head git ref (PR head SHA / push SHA)")
    args = parser.parse_args(argv)

    try:
        resolve_ref(args.repo, args.base)
        resolve_ref(args.repo, args.head)
        paths = changed_paths(
            args.repo,
            args.base,
            args.head,
            merge_base=(args.mode == "pull_request"),
        )
    except AuditError as exc:
        print("tier=full")
        print("reason=classifier_error_fail_closed")
        print(f"error={exc}")
        return EXIT_USAGE

    tier, reason = classify(paths)
    print(f"tier={tier}")
    print(f"reason={reason}")
    print(f"changed_files={len(paths)}")
    print("files:")
    for path in paths:
        print(f"- {path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
