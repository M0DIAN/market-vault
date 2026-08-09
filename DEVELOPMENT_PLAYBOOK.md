# MarketVault Development Playbook

The repository-native development playbook for MarketVault. Claude Code,
Codex, and human developers reference this document instead of repeating
the full gate specification inside every prompt.

- Scope: standard PR lifecycle and the three local verification layers.
- Release procedure: see [RELEASE_PLAYBOOK.md](RELEASE_PLAYBOOK.md).
- Agent execution contract: see [AGENT_HANDOFF.md](AGENT_HANDOFF.md).
- Motivation and roadmap: see
  [docs/development_protocol_v1.md](docs/development_protocol_v1.md).

This playbook is Development Protocol v1 (DP1) policy. DP1 defines
policy only; it does not modify CI, tests, or tooling. Later PRs
implement the policy.

## 1. Standard PR lifecycle

Every MarketVault PR follows the same lifecycle. The order matters; the
gates are non-negotiable.

### 1.1 Exact base

1. `git switch main`
2. `git fetch origin --prune --tags`
3. `git pull --ff-only`
4. Verify `HEAD == origin/main == <exact base SHA>` given by the task or
   by the current main HEAD.
5. Verify the working tree is clean (`git status --short` empty).

If any of these checks fail, stop and report. Never start work from an
unverified base.

### 1.2 Scope freeze

Before any edit, state the exact scope of the task: the files that may
change, the files that must not change, and the non-goals. Confirm the
scope with the requester when it is ambiguous.

A frozen scope is a promise. Expanding scope without explicit approval is
a protocol violation (see [AGENT_HANDOFF.md](AGENT_HANDOFF.md) rule 4).

### 1.3 Branch creation

Create a branch whose name reflects the change, for example
`docs/development-protocol-v1`. Push branches to the repository remote so
final-head CI runs.

### 1.4 Implementation

Implement the frozen scope on the branch. Match surrounding code style
and document density. Do not silently add adjacent work.

### 1.5 Local verification layer

Run the appropriate local verification layer (Section 2). The layer is
chosen by the size and risk of the change, not by a fixed rule that every
edit must run everything.

### 1.6 Final-head push

Push the final head: `git push -u origin <branch>`.

The final head is the last commit you intend the reviewers to evaluate.
Everything after this point is evaluated against this exact SHA.

### 1.7 GitHub final-head CI

The pull request triggers GitHub Actions for the exact final head SHA.
CI is the authoritative verification of the final head (Section 2.3).
Do not report acceptance until that CI reaches a terminal state — see
the CI-wait reporting rule in [AGENT_HANDOFF.md](AGENT_HANDOFF.md).

### 1.8 Independent review

An independent reviewer — a human or a separate reviewer process, never
the authoring agent — reviews the final head: diff, scope audit, CI
results, and any release implications. The authoring agent's own report
is not independent verification.

### 1.9 Merge gate

Merge happens only after:

- final-head CI is terminal and SUCCESS, and
- the independent review passes, and
- explicit merge authorization was given.

STOP BEFORE MERGE unless explicitly authorized.

### 1.10 Main verification

After the merge, the push to `main` triggers main CI for the merge
commit. Main CI is the authoritative post-merge run. A task that reports
COMPLETE must wait for the exact merge/main commit's CI to reach a
terminal state first (same rule as 1.7).

## 2. Local verification layers

Three layers define how much verification runs locally. Higher layers
include the lower ones.

### LEVEL 1 — focused development

For fast iteration during implementation.

- Only tests directly relevant to the changed behavior.
- Checker / lint / diff checks relevant to the changed paths
  (for example `git diff --check`, `python -m compileall` on changed
  files, repo hygiene checks when they touch the changed surface).
- Intended for fast iteration inside the implementation loop.

### LEVEL 2 — submission readiness

Before pushing a final head and opening / updating a PR.

- The affected regression surface: the regression suites that cover the
  changed code paths, run to completion.
- Scope audit: the changed-file list matches the frozen scope exactly.
- Dependency / version audit when applicable: any change that touches
  dependencies, packaging, or versions must verify the dependency and
  version surface it affects.
- No automatic full-suite requirement merely because a PR exists. A small
  docs-only or single-module PR does not automatically require the full
  local suite.

### LEVEL 3 — authoritative full verification

- GitHub final-head CI, according to repository policy
  ([.github/workflows/ci.yml](.github/workflows/ci.yml)): the full test
  matrix (Python 3.11 and 3.14), the PyArrow 24 portability gate, and the
  package build / fresh-wheel / SHA256 closure job.
- Required before merge when applicable. The local machine is never the
  authority for the full matrix; GitHub final-head CI is.

## 3. When a local full pytest run is required

A local full `pytest` run is NOT automatically required after every small
edit when authoritative final-head CI will run the full matrix.

The authoritative full verification of the final head is GitHub CI. The
local full suite is optional when CI covers it; local verification exists
to catch problems fast and early (LEVEL 1) and to prove submission
readiness (LEVEL 2), not to duplicate the full CI matrix on every edit.

Full-suite local runs are still appropriate when:

- CI is unavailable or cannot run (for example a repository network
  outage), or
- the change is a release-preparation change that must be validated
  before the release gate, or
- the task explicitly requires a local full run.

## 4. Do not weaken final-head CI

DP1 does not change CI behavior. The final-head CI defined in
[.github/workflows/ci.yml](.github/workflows/ci.yml) — the full matrix,
the PyArrow 24 gate, the package job — remains exactly as it is. Any
future change to CI is a separate, explicit PR with its own review.
