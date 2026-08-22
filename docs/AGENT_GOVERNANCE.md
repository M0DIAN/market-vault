# MarketVault Agent Governance

## Purpose and Authority

This document defines repository governance policy for development agents. It
does not alter product behavior, data semantics, storage contracts, CI logic,
or release state, and it does not claim that every policy statement below is
machine-enforced.

Codex is MarketVault's primary implementation and development agent. Other
agents and human contributors follow the same repository rules. The repository
owner remains the product and release authority: the owner approves scope,
product tradeoffs, merges, and formal release mutations. An independent
reviewer, separate from the implementing agent, audits architecture, final
scope, merge readiness, and release readiness. An agent's self-review is useful
evidence but is not independent approval.

## Source of Truth

Repository code and checked-in contracts outrank prompts, conversational
memory, handoff summaries, and prior agent reports. Before implementation,
inspect the relevant source, tests, `docs/contracts`, and the playbooks in
`docs/governance`.

The normal write path is:

```text
current origin/main -> feature branch -> inspect -> implement -> tests
-> local validation -> PR -> PR CI/review -> squash merge
-> exact main SHA -> post-merge CI verification
```

Feature branches and pull requests are the normal path for repository changes.
Direct development on `main` is prohibited by governance policy. Squash merge
is the default project workflow. Force-pushing or rewriting `main` history is
prohibited.

## Evidence and Validation

Important Git and CI assertions must be tied to an exact commit SHA. Where the
existing CI contract binds artifacts or attestations to a workflow attempt,
evidence must also identify and validate that exact run attempt. A green run
for a different SHA or attempt is not transferable evidence.

The active CI tier semantics must be derived from
`scripts/ci_risk_tier.py` and its regression tests, not copied into another
independently evolving classifier or policy table. The workflow in
`.github/workflows/ci.yml` is the execution authority. Unknown paths, unknown
tiers, invalid classifier inputs, classifier errors, or unprovable scope fail
closed to FULL validation according to the existing machine contract.

Post-merge FULL reuse may be claimed only when
`scripts/ci_post_merge_reuse.py` proves all existing eligibility conditions,
including required run/job evidence and Git-tree equivalence. If proof is
missing, ambiguous, stale, malformed, unreachable, or unsuccessful, normal
FULL validation remains authoritative. A successful PR run alone is never
sufficient evidence that the merged change is healthy. Completion requires
terminal CI evidence for the exact resulting `main` SHA.

Tests remain offline unless a task explicitly requires live integration. No
agent may weaken tests, assertions, contracts, or validation to obtain a green
result. When the safe validation scope cannot be proven, validation fails
closed rather than selecting a smaller surface.

## Change Visibility

Agents must not silently alter schema, storage layout, data semantics,
point-in-time behavior, compatibility guarantees, CLI contracts, CI
architecture, or release process. High-impact changes, including schema
migrations, storage-layout changes, PIT or data-semantic changes, compatibility
guarantees, CI architecture, and release-process changes, require explicit PR
visibility and independent review.

This review requirement is repository governance policy unless a cited source
or test makes a particular gate machine-enforced. Do not describe policy as an
existing CI guarantee when the repository does not enforce it.

## Release and History Protection

Formal tags and GitHub Releases are immutable governance records. Agents must
not move, delete, or recreate formal tags. They must not create, replace,
delete, or otherwise mutate formal GitHub Releases or release assets unless the
repository owner explicitly authorizes that exact action. A development agent
may prepare release notes, candidate artifacts, hashes, or audit material, but
formal release mutation remains human-authorized and follows
`docs/governance/RELEASE_PLAYBOOK.md`.

No agent may force-push, amend, rebase, or otherwise rewrite protected `main`
or formal release history. Merge authority and release authority are separate
from implementation authority.

## Security and Data Handling

Generated market data, local Parquet or DuckDB files, runtime manifests and
reports, caches, and virtual environments must remain untracked. Credentials,
API keys, tokens, passwords, account information, OpenD session details, and
other secrets must never be committed, printed in reports, included in PRs, or
exposed in logs. Live OpenD validation, when explicitly required, must report
capabilities and outcomes without disclosing credentials or session material.

## Handoff and Stop Conditions

Every handoff should identify the verified base SHA, final head SHA, changed
files, validation results, CI run and attempt evidence when applicable,
working-tree state, and unresolved uncertainty. The implementing agent stops
before merge unless the repository owner explicitly authorizes it. After an
authorized merge, the exact `main` SHA and its terminal CI result are required
before the change may be reported healthy or complete.
