"""Risk-tier classifier: deterministic, read-only, fail-closed.

Stable framework tiers:

- ``docs_fast``:     every changed path is inside the configured docs
                     scope
- ``package_docs``:  every changed path is docs OR a configured
                     package-doc file, and at least one package-doc file
                     changed (package metadata is sensitive)
- ``control_plane``: every changed path is inside the exact configured
                     control-plane eligible subset (or the docs scope),
                     with at least one control-plane path. A validated
                     SUBSET tier: it runs the always-run cheap checks and
                     the control-plane surface — never the FULL matrix.
- ``full``:          anything else, including empty diffs and any
                     condition that prevents reliable classification

Rules remain conservative. Default behavior: unknown / unset / malformed
/ exception => ``full``. An empty diff is FULL: a fast path is never
claimed without evidence.
"""

from __future__ import annotations

from .components import Impact, compute_impact
from .policy import Config, rule_matches, violations

TIER_DOCS_FAST = "docs_fast"
TIER_PACKAGE_DOCS = "package_docs"
TIER_CONTROL_PLANE = "control_plane"
TIER_FULL = "full"

STABLE_TIERS = (TIER_DOCS_FAST, TIER_PACKAGE_DOCS, TIER_CONTROL_PLANE, TIER_FULL)

REASON_EMPTY = "empty_diff"
REASON_NOT_IN_SCOPE = "changed_path_not_in_scope"
REASON_PACKAGE_DOCS = "package_doc_changed_in_docs_scope"
REASON_DOCS = "all_changes_in_docs_scope"
REASON_CONTROL_PLANE = "all_changes_in_control_plane_scope"
REASON_SHARED = "control_plane_mutation_requires_full"
REASON_UNKNOWN = "unknown_path_requires_full"
REASON_CORE = "core_component_requires_full"
REASON_COMPONENT_NO_VALIDATION = "component_without_validation_requires_full"
REASON_INVALID_CONFIG = "invalid_config_fail_closed"
REASON_CLASSIFIER_ERROR = "classifier_error_fail_closed"


def _is_control_plane_change(
    paths: list[str], eligible_rules: list[str], docs_rules: list[str]
) -> bool:
    """Exact control-plane mixture: >= 1 control-plane path and every
    path is either a control-plane eligible rule or an existing docs
    rule. Anything else (package-doc files, src/**, non-eligible
    paths, unknown paths, renames into non-eligible paths) fails the
    allowlist and falls through to FULL."""
    return bool(paths) and any(
        any(rule_matches(r, p) for r in eligible_rules) for p in paths
    ) and all(
        any(rule_matches(r, p) for r in eligible_rules)
        or any(rule_matches(r, p) for r in docs_rules)
        for p in paths
    )


def classify(paths: list[str], config: Config) -> tuple[str, str, Impact]:
    """Return (tier, reason, impact) for a changed-path list.

    Renames are already handled by the git layer: both the old and the
    new path are in ``paths``, so a rename into or out of any scope
    classifies by both paths (fail-closed).

    Precedence (fail-closed):
      1. empty diff -> FULL
      2. invalid / unresolvable classification -> FULL (caller exit)
      3. exact docs scope -> docs_fast
      4. package-doc file(s) + docs only -> package_docs
      5. exact control-plane eligible / docs mixture with >= 1
         control-plane path -> control_plane (validated SUBSET tier)
      6. control-plane mutation outside the eligible subset -> FULL
      7. core component -> FULL
      8. any registered component without an explicit validation
         contract -> FULL
      9. unknown / anything else -> FULL

    ``full_matrix_required`` is derived from the resulting tier, so it
    always reflects the currently ACTIVE validation policy: false only
    for the validated subset tiers docs_fast / package_docs /
    control_plane, true for every FULL classification.
    """
    docs_rules = list(config.docs)
    package_docs_files = list(config.package_docs)
    control_rules = list(config.control_plane)
    eligible_rules = list(config.control_plane_eligible)
    component_rules = [rule for c in config.components for rule in c.paths]
    components = list(config.components)

    impact = compute_impact(
        paths,
        components,
        docs_rules=docs_rules,
        package_docs_files=package_docs_files,
        control_rules=control_rules,
        eligible_rules=eligible_rules,
    )

    if not paths:
        tier, reason = TIER_FULL, REASON_EMPTY
    elif violations(
        paths,
        [
            *docs_rules,
            *package_docs_files,
            *control_rules,
            *eligible_rules,
            *component_rules,
        ],
    ):
        tier, reason = TIER_FULL, REASON_NOT_IN_SCOPE
    elif all(any(rule_matches(r, p) for r in docs_rules) for p in paths):
        tier, reason = TIER_DOCS_FAST, REASON_DOCS
    elif any(p in package_docs_files for p in paths) and all(
        p in package_docs_files or any(rule_matches(r, p) for r in docs_rules)
        for p in paths
    ):
        tier, reason = TIER_PACKAGE_DOCS, REASON_PACKAGE_DOCS
    elif _is_control_plane_change(paths, eligible_rules, docs_rules):
        # The validated control-plane subset tier: it runs the always-run
        # cheap checks and the control-plane surface; it MUST NEVER
        # produce FULL evidence (full_matrix_required=false).
        tier, reason = TIER_CONTROL_PLANE, REASON_CONTROL_PLANE
    elif impact.shared_changed:
        # Control-plane mutation outside the validated allowlist
        # (workflow / classifier / registry / package schema) forces
        # FULL, regardless of components.
        tier, reason = TIER_FULL, REASON_SHARED
    elif impact.core_changed:
        tier, reason = TIER_FULL, REASON_CORE
    elif impact.components:
        # Registered component(s) with no explicit validation contract:
        # the tier stays FULL. Component impact alone never authorizes
        # skip.
        tier, reason = TIER_FULL, REASON_COMPONENT_NO_VALIDATION
    else:
        tier, reason = TIER_FULL, REASON_UNKNOWN
    impact.full_matrix_required = tier == TIER_FULL
    return tier, reason, impact
