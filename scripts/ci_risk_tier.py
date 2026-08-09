#!/usr/bin/env python3
"""MarketVault CI risk-tier classifier (Phase 1 + Component-Aware foundation).

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

The component-aware foundation (DP4) is additive: ``ci/components.toml``
registers component path surfaces and the classifier emits their impact
(components=, core_changed=, package_changed=, unknown_changed=,
shared_changed=, independent_only=, full_matrix_required=). The three
tiers are unchanged and no registered component makes any change faster
than before; the registry only makes impact explicit. The future rule
(a component may skip the core full matrix only with explicit path
registration + explicit validation + no core/shared/package/workflow
mutation + determinable impact) is computed as ``full_matrix_required``
but does not change the tier yet: every registered-component-only
change still classifies FULL (component_without_validation_requires_full).

Fail-safe: an empty diff, an unresolvable ref, an invalid registry, or
any git failure yields tier=full (or a non-zero exit the workflow
converts to full). Unknown / unset tiers in the workflow behave as full.

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
    components=<comma-separated component names|none>
    core_changed=<true|false>
    package_changed=<true|false>
    unknown_changed=<true|false>
    shared_changed=<true|false>
    independent_only=<true|false>
    full_matrix_required=<true|false>
    changed_files=<count>
    files:
    - <path>
    ...

Exit codes:
    0 = classification completed (any tier, including full)
    2 = usage / git resolution / registry error (workflow converts to
        tier=full)
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

from audit_pr import (
    AuditError,
    changed_paths,
    resolve_ref,
    rule_matches,
    violations,
)

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

# Component registry (DP4). A missing registry file means "no registered
# components": every non-docs path then classifies unknown -> full.
REGISTRY_REL = Path("ci") / "components.toml"

# Control-plane paths. A mutation to any of these changes the
# classification / packaging / CI contract itself, so it always forces
# FULL (future rule condition 4: package / workflow / shared schema).
# pyproject.toml is the package schema; scripts/audit_pr.py is the
# classifier's own audit dependency.
CONTROL_RULES = [
    ".github/workflows/",
    "scripts/ci_risk_tier.py",
    "scripts/audit_pr.py",
    "ci/components.toml",
    "pyproject.toml",
]

TIER_DOCS_FAST = "docs_fast"
TIER_PACKAGE_DOCS = "package_docs"
TIER_FULL = "full"

_COMPONENT_NAME_RE = r"^[a-z0-9_-]+$"

REASON_EMPTY = "empty_diff"
REASON_NOT_IN_SCOPE = "changed_path_not_in_docs_scope"
REASON_README = "readme_changed_in_docs_scope"
REASON_DOCS = "all_changes_in_docs_scope"
REASON_SHARED = "workflow_or_registry_mutation_requires_full"
REASON_UNKNOWN = "unknown_path_requires_full"
REASON_CORE = "core_component_requires_full"
REASON_COMPONENT_NO_VALIDATION = "component_without_validation_requires_full"
REASON_INVALID_REGISTRY = "invalid_registry_fail_closed"
REASON_CLASSIFIER_ERROR = "classifier_error_fail_closed"


@dataclass(frozen=True)
class Component:
    """One registered [components.<name>] entry."""

    name: str
    paths: tuple[str, ...]
    requires_core_full: bool = False
    requires_package: bool = False


@dataclass
class Impact:
    """Component impact of a changed-path list (additive, never gates)."""

    components: list[str] = field(default_factory=list)
    core_changed: bool = False
    package_changed: bool = False
    unknown_changed: bool = False
    shared_changed: bool = False
    independent_only: bool = False
    full_matrix_required: bool = False


def load_registry(repo_root: str) -> list[Component]:
    """Load ci/components.toml; [] when missing; AuditError when invalid.

    Missing file is not an error (tests and minimal repos have no
    registry): with no registered components every non-docs path is
    unknown and classifies full, which is fail-closed. A present but
    malformed registry is an error: an invalid registry must never be
    silently treated as "no components".
    """
    path = Path(repo_root) / REGISTRY_REL
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AuditError(f"invalid component registry {REGISTRY_REL}: {exc}")
    components = data.get("components")
    if not isinstance(components, dict):
        raise AuditError(
            f"invalid component registry {REGISTRY_REL}: "
            "missing [components] table"
        )
    result: list[Component] = []
    for name, entry in components.items():
        if not isinstance(name, str) or not re.fullmatch(_COMPONENT_NAME_RE, name):
            raise AuditError(
                f"invalid component registry {REGISTRY_REL}: "
                f"invalid component name {name!r}"
            )
        if not isinstance(entry, dict):
            raise AuditError(
                f"invalid component registry {REGISTRY_REL}: "
                f"[components.{name}] is not a table"
            )
        paths = entry.get("paths")
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(p, str) and p for p in paths)
        ):
            raise AuditError(
                f"invalid component registry {REGISTRY_REL}: "
                f"[components.{name}] needs a non-empty list of paths"
            )
        for flag in ("requires_core_full", "requires_package"):
            value = entry.get(flag, False)
            if not isinstance(value, bool):
                raise AuditError(
                    f"invalid component registry {REGISTRY_REL}: "
                    f"[components.{name}] {flag} must be a boolean"
                )
        result.append(
            Component(
                name=name,
                paths=tuple(paths),
                requires_core_full=bool(entry.get("requires_core_full", False)),
                requires_package=bool(entry.get("requires_package", False)),
            )
        )
    return result


def compute_impact(paths: list[str], components: list[Component]) -> Impact:
    """Component impact of a changed-path list (never raises).

    ``full_matrix_required`` is the future-rule predicate: true unless
    every changed path is covered by the docs scope, README, the
    control plane, or a registered component AND no core / shared /
    unknown surface was hit. It does not change the tier; it is the
    mechanism a future component validation can gate on.
    """
    impact = Impact()
    matched: set[str] = set()
    core_hit = False
    package_hit = any(p == README_FILE for p in paths)
    covered = True

    def _covered(path: str) -> bool:
        return any(rule_matches(rule, path) for rule in DOCS_SCOPE_RULES) or (
            path == README_FILE
        ) or any(rule_matches(rule, path) for rule in CONTROL_RULES) or any(
            rule_matches(rule, path) for c in components for rule in c.paths
        )

    for path in paths:
        if not _covered(path):
            covered = False
        if any(rule_matches(rule, path) for rule in CONTROL_RULES):
            impact.shared_changed = True
        if any(rule_matches(rule, path) for rule in DOCS_SCOPE_RULES):
            continue
        hit = [c for c in components if any(rule_matches(r, path) for r in c.paths)]
        if hit:
            matched.update(c.name for c in hit)
            core_hit = core_hit or any(c.requires_core_full for c in hit)
            package_hit = package_hit or any(c.requires_package for c in hit)
            continue
        if path == README_FILE:
            # README is package-sensitive even without a registry entry
            # (pyproject.toml ``readme``); with the real registry it is
            # matched above as [components.package].
            package_hit = True
            continue
        impact.unknown_changed = True

    impact.components = sorted(matched)
    impact.core_changed = core_hit
    impact.package_changed = package_hit
    impact.independent_only = (
        bool(paths)
        and bool(matched)
        and all(
            any(rule_matches(r, p) for c in components for r in c.paths)
            for p in paths
        )
        and not core_hit
        and not package_hit
        and not impact.shared_changed
        and not impact.unknown_changed
    )
    impact.full_matrix_required = (
        not paths
        or impact.shared_changed
        or impact.unknown_changed
        or impact.core_changed
        or not covered
    )
    return impact


def classify(
    paths: list[str], components: list[Component]
) -> tuple[str, str, Impact]:
    """Return (tier, reason, impact) for a changed-path list.

    Empty diff is FULL: a fast path is never claimed without evidence.
    Renames are already handled by the caller: both the old and the new
    path are in ``paths``, so a rename into or out of any scope
    classifies by both paths.
    """
    impact = compute_impact(paths, components)
    if not paths:
        return TIER_FULL, REASON_EMPTY, impact
    allowed = [
        *DOCS_SCOPE_RULES,
        README_FILE,
        *CONTROL_RULES,
        *(rule for c in components for rule in c.paths),
    ]
    if violations(paths, allowed):
        return TIER_FULL, REASON_NOT_IN_SCOPE, impact
    if impact.shared_changed:
        # Control-plane mutation (workflow / classifier / registry /
        # package schema) forces FULL, regardless of components.
        return TIER_FULL, REASON_SHARED, impact
    if impact.core_changed:
        # The core component requires the full matrix (condition 3/5).
        return TIER_FULL, REASON_CORE, impact
    if README_FILE in paths and all(
        p == README_FILE or any(rule_matches(r, p) for r in DOCS_SCOPE_RULES)
        for p in paths
    ):
        return TIER_PACKAGE_DOCS, REASON_README, impact
    if all(any(rule_matches(r, p) for r in DOCS_SCOPE_RULES) for p in paths):
        return TIER_DOCS_FAST, REASON_DOCS, impact
    if impact.components:
        # Registered component(s) with no validation contract yet: the
        # tier stays FULL until a future registry entry declares
        # component validation (future rule condition 2).
        return TIER_FULL, REASON_COMPONENT_NO_VALIDATION, impact
    return TIER_FULL, REASON_UNKNOWN, impact


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_risk_tier.py",
        description=(
            "Deterministic, read-only CI risk-tier classification of a "
            "change range between --base and --head, with component "
            "impact from ci/components.toml."
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

    try:
        components = load_registry(args.repo)
    except AuditError as exc:
        # A present-but-invalid registry must never be treated as "no
        # components": fail closed with a distinct reason.
        print("tier=full")
        print("reason=invalid_registry_fail_closed")
        print(f"error={exc}")
        return EXIT_USAGE

    tier, reason, impact = classify(paths, components)
    print(f"tier={tier}")
    print(f"reason={reason}")
    print(f"components={','.join(impact.components) if impact.components else 'none'}")
    print(f"core_changed={'true' if impact.core_changed else 'false'}")
    print(f"package_changed={'true' if impact.package_changed else 'false'}")
    print(f"unknown_changed={'true' if impact.unknown_changed else 'false'}")
    print(f"shared_changed={'true' if impact.shared_changed else 'false'}")
    print(f"independent_only={'true' if impact.independent_only else 'false'}")
    print(f"full_matrix_required={'true' if impact.full_matrix_required else 'false'}")
    print(f"changed_files={len(paths)}")
    print("files:")
    for path in paths:
        print(f"- {path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
