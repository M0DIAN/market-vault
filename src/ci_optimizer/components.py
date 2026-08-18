"""Component impact model (additive metadata; never authorizes skip).

A registered component is a named path surface from the config file
(``[components.<name>]``). The classifier computes component impact of a
changed-path list and exposes it separately from the tier. Component
impact alone MUST NOT authorize skipping validation: every registered
component change still classifies FULL until the project registers an
explicit validated component-validation contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .policy import Component, rule_matches


@dataclass
class Impact:
    """Component impact of a changed-path list (additive, never gates).

    ``independent_only`` is eligibility/impact information only: it says
    the changed paths are structurally isolated to registered
    non-core / non-package / non-shared components. It does NOT
    authorize skipping the full matrix. ``full_matrix_required`` is
    derived by the classifier from the ACTIVE tier policy, so it can
    never contradict the reason for the tier.
    """

    components: list[str] = field(default_factory=list)
    core_changed: bool = False
    package_changed: bool = False
    unknown_changed: bool = False
    shared_changed: bool = False
    independent_only: bool = False
    full_matrix_required: bool = False


def compute_impact(
    paths: list[str],
    components: list[Component],
    *,
    docs_rules: list[str],
    package_docs_files: list[str],
    control_rules: list[str],
    eligible_rules: list[str],
) -> Impact:
    """Component impact of a changed-path list (never raises).

    ``full_matrix_required`` is intentionally left at its default here:
    the classifier derives it from the ACTIVE tier policy after the tier
    decision.
    """
    impact = Impact()
    matched: set[str] = set()
    core_hit = False
    package_hit = any(p in package_docs_files for p in paths)

    for path in paths:
        if any(rule_matches(rule, path) for rule in control_rules):
            impact.shared_changed = True
        if any(rule_matches(rule, path) for rule in docs_rules):
            continue
        if any(rule_matches(rule, path) for rule in eligible_rules):
            # The validated control-plane subset is a known path surface:
            # it never counts as an unknown path. shared_changed may
            # still be true here (e.g. the workflow file), which the tier
            # contract explicitly authorizes as impact metadata.
            continue
        hit = [c for c in components if any(rule_matches(r, path) for r in c.paths)]
        if hit:
            matched.update(c.name for c in hit)
            core_hit = core_hit or any(c.requires_full for c in hit)
            package_hit = package_hit or any(c.requires_package for c in hit)
            continue
        if path in package_docs_files:
            # Package-sensitive even without a registry entry.
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
    return impact
