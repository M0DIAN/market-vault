# MarketVault Development Protocol v1

The architecture and roadmap document for the MarketVault engineering
process. This document motivates Development Protocol v1 (DP1), records
the measured baseline, and defines the directions that later PRs
implement.

- Policy documents: [DEVELOPMENT_PLAYBOOK.md](../DEVELOPMENT_PLAYBOOK.md)
  and [RELEASE_PLAYBOOK.md](../RELEASE_PLAYBOOK.md).
- Agent execution contract: [AGENT_HANDOFF.md](../AGENT_HANDOFF.md).

## 1. Status

DP1 is the first process-engineering task after the completed v0.7.0
real-usage exercise. DP1 defines policy only:

- It does not change product code, version, dependencies, public API,
  CLI, schemas, or artifact formats.
- It does not optimize CI or tests yet; later PRs implement the policy
  defined here.
- It does not mutate the sealed v0.7.0 release in any way.

## 2. Motivation and measured baseline

The v0.7.0 lifecycle PR (`docs: record v0.7.0 formal release state`,
PR #54) was the observed real-usage case that motivated DP1. The
recorded observation:

- The lifecycle / docs PR took approximately 63 minutes wall-clock.
- Local testing dominated wall-clock time.
- The affected regression test file alone can take many minutes.
- Repeated full-suite execution occurred locally during the PR
  lifecycle.
- GitHub CI currently executes multiple full-suite environments (the
  Python 3.11 and 3.14 matrix, the PyArrow 24 portability gate, each
  running the full offline suite).
- Package / release verification adds another CI stage (package build,
  fresh-wheel smoke, SHA256 closure).

No exact percentages are claimed: the recorded observation is a
wall-clock measurement of one lifecycle PR, not a timing study. The
problem is qualitatively clear — small changes repeatedly pay for
full-suite-scale verification — but DP1 deliberately avoids claiming
precise breakdowns the observation does not support.

## 3. Core principle: FASTER, SAME SAFETY

The objective of DP1 is to reduce repeated human / agent instruction
overhead and wall-clock latency while preserving every current safety
guarantee.

Safety is not traded for speed. Every gate that exists today continues
to exist:

- scope freeze
- exact base
- final-head CI
- merge gate
- main verification
- release gate
- artifact hash closure

DP1's policy reduces repeated verification (local full suites run
repeatedly for the same change) and repeated instruction (the full gate
spec repeated inside every prompt), not the gates themselves.

## 4. Development Protocol v1 directions

Later PRs implement these directions. DP1 does not implement them; it
defines and prioritizes them.

### 4.1 Layered local testing

Three local verification layers — LEVEL 1 focused development, LEVEL 2
submission readiness, LEVEL 3 authoritative full verification — so a
small edit runs only what the edit needs, and the full-suite authority
sits in final-head CI. Policy is in the
[DEVELOPMENT_PLAYBOOK.md](../DEVELOPMENT_PLAYBOOK.md) section 2.

### 4.2 Parallel testing

The affected regression surface and the full suite can run as parallel
pytest processes locally, so the wall-clock cost of a regression
surface does not scale linearly with its run time.

### 4.3 Automated PR audit

An automated, scripted PR audit that checks the frozen-scope contract
(changed-file list vs. scope, no product / version / dependency / API /
CLI / schema / workflow mutation) without a human or agent re-reading
the whole diff. The audit is the mechanical part of the review; the
independent review remains human or separate-reviewer judgment.

### 4.4 Repository-native playbooks / handoff

This repository now carries the playbooks and the agent execution
contract ([DEVELOPMENT_PLAYBOOK.md](../DEVELOPMENT_PLAYBOOK.md),
[RELEASE_PLAYBOOK.md](../RELEASE_PLAYBOOK.md),
[AGENT_HANDOFF.md](../AGENT_HANDOFF.md)) so future tasks reference them
instead of repeating the full gate specification inside every prompt.

### 4.5 Lifecycle-State Decoupling

The Lifecycle-State Principle (Section 6): mutable lifecycle truth must
not be embedded as authoritative truth in immutable release payloads.
DP1 documents the rule only; the concrete release-state design
(`release/state.json` or equivalent) is DP5 after the semantics are
designed.

### 4.6 CI risk-tier optimization

The final-head CI matrix is sized by change risk instead of uniformly
running every environment for every change, while keeping the
authoritative full verification intact for changes that need it. This
direction does not weaken final-head CI; it is planned and reviewed as
its own change.

## 5. Future target wall-clock guidance

These are performance targets, not correctness gates. Missing a target
is not a failure of verification; it is a signal to improve the process.

| PR class | Target wall-clock |
|---|---|
| small PR | 15–30 min |
| medium PR | 25–45 min |
| release-prep / complex | 40–60 min |

A small PR (for example docs-only or a single-module change) should not
pay lifecycle-scale wall-clock; a release preparation should. The
targets bound total lifecycle time including final-head CI, not just
implementation time.

## 6. Lifecycle-State Principle

Any statement that becomes false immediately after a merge, tag
creation, release publication, or package publication must not be
embedded as authoritative current truth in an immutable release payload.

Two classes of truth exist:

### IMMUTABLE SOURCE TRUTH

Statements that remain true across lifecycle transitions and belong in
immutable release payloads as authoritative:

- version
- feature scope
- API / contracts
- compatibility
- non-goals
- release procedure
- artifact formats

### MUTABLE LIFECYCLE TRUTH

Statements that flip the moment a lifecycle transition happens and must
never be embedded as authoritative current truth in an immutable release
payload:

- PR open / current / merged
- current main HEAD
- tag-created state
- GitHub Release publication state
- Release ID / `published_at`
- latest status
- package-registry publication state

Where mutable lifecycle truth is recorded (for example in release-notes
documents), it is recorded as a historical record of the state at a
point in time, explicitly marked as such — exactly as
[docs/release_v0_7_0.md](release_v0_7_0.md) separates its formal release
status from its historical release-preparation record.

## 7. DP1 scope boundary

DP1:

- records the playbooks and the agent contract;
- documents the baseline, the directions, the targets, and the
  Lifecycle-State Principle;
- changes no product code, no version, no dependency, no public API, no
  CLI, no schema, no artifact format, and no CI workflow.

DP1 does NOT implement the release-state design (`release/state.json` or
equivalent). That belongs to DP5, after the semantics are designed.
