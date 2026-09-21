# Repository Guidelines

## Authority and Agent Role

Codex is the default primary implementation and development agent for
MarketVault. These rules are tool-agnostic and apply equally to any other
agent or contributor. Repository code, checked-in contracts, tests, and
governance documents outrank conversational memory or prior reports. Read the
relevant source and contracts before changing behavior.

The repository owner retains product and release authority. An independent
reviewer provides architecture, merge, and release audit; the implementing
agent's own report is not independent approval. See
`docs/AGENT_GOVERNANCE.md` and `docs/governance/`.

## DeepSeek Harness Review Protocol

This section binds the DeepSeek Harness agent when it inspects, reviews, or
implements work here. It supplements the authority rules above and in
`docs/AGENT_GOVERNANCE.md`; it does not replace or weaken them. Codex remains
the default primary implementation and development agent.

### Work-Order Authority First

Before implementation, inspect the active work order, phase locks, explicit
authorizations, and non-goals. Technical usefulness does not override an
explicit `IMPLEMENTATION_AUTHORIZED=false`. Implementation, production, and
merge/release authorities are separate grants; holding one never implies
another. Existing unauthorized work in progress inherits no approval merely
because it exists.

### Read-Only Discovery First

For non-trivial work, begin read-only: relevant source, tests, contracts, ADRs
under `docs/adr`, governance, current Git/worktree state, and active work-order
authority. Do not modify existing dirty-worktree content during discovery; the
clean-worktree gate before branching in the Required Development Flow below is
unaffected.

### Findings Are Hypotheses

Findings are not an automatic repair list. Every material finding needs concrete
evidence: source location, call graph, contract text, test behavior, or an
executable probe. Before a finding becomes a repair item, actively attempt to
disprove it and classify it `CONFIRMED`, `DOWNGRADED`, `RETRACTED`, or
`NEEDS_DESIGN_DECISION`. Retraction is preferable to preserving a weak finding.

Do not conflate an observed implementation fact, an unfinished implementation
gap, a reachable production defect, a test coverage gap, intentional fail-closed
behavior, contract ambiguity, and a design decision. Private-helper behavior is
not automatically a public-API defect.

### Complete Call Graph, Executable Probes

Absence of a check from one layer does not prove absence from the system; trace
the complete intended and implemented call graph before declaring an enforcement
requirement missing.

Do not reason by mental arithmetic about bitmasks and flags, hashes and
identities, byte sizes, offsets, binary layouts, encoding lengths, timestamps
and time windows, or numeric boundaries. Use an executable probe and record its
input, computed result, and assertion. A correct conclusion does not excuse
incorrect intermediate arithmetic.

### Evidence Convergence and Completion Gates

After adversarial self-review, stop broadening the search for findings and
reduce what remains to concrete completion gates. For unfinished work,
distinguish `IMPLEMENTED_AND_WIRED`, `IMPLEMENTED_NOT_WIRED`, and
`NOT_IMPLEMENTED`, and do not describe unreachable unfinished implementation as
a production vulnerability merely because it is incomplete.

Before modifying code, define the exact files expected to change, the exact
invariant being introduced or restored, the required tests, and explicit
non-goals; prefer the smallest change that makes the invariant structural. Once
implementation is authorized, stay inside the accepted gates: no opportunistic
cleanup, unrelated refactor, silent taxonomy expansion, test weakening, or
conversion of failures into skips.

### Test Proof and Independent Review

A green test is not sufficient evidence by itself. For security, filesystem,
identity, parser, fail-closed, or governance invariants, verify that the test
passes or fails for the intended reason rather than because an unrelated earlier
guard fired.

A Harness session that implemented a change must not approve its own work;
independent review follows the rules above and
`docs/governance/DEVELOPMENT_PLAYBOOK.md`. High-risk changes require independent
read-only review before merge, including artifact identity, filesystem or native
evidence, PIT semantics, destructive behavior, publication, cryptography,
CI/control-plane behavior, and security boundaries.

### Exact-Head PR Review

Before merge authorization, verify the exact PR head SHA, exact tree, exact base
SHA, exact changed-file set, exact-head CI run and attempt, and the independent
review result. Green CI alone is not merge approval, and repository-owner merge
authority is unchanged.

### Standard Harness Flow

This refines the Required Development Flow below; it does not replace it.

```text
read-only discovery -> adversarial self-review -> evidence convergence
-> completion gates -> minimal patch plan -> narrow implementation
-> focused validation -> independent implementation review -> commit / Draft PR
-> exact-head PR review -> owner merge authorization -> squash merge
-> natural main CI -> post-merge closure
```

Harness holds no automatic merge authority.

## Required Development Flow

Use this normal path:

```text
current origin/main -> feature branch -> inspect -> implement -> tests
-> local validation -> PR -> PR CI/review -> squash merge
-> exact main SHA -> post-merge CI verification
```

Never develop directly on `main`. Verify the exact current `origin/main` SHA
and a clean worktree before branching. Keep changes within the declared scope,
use feature branches and pull requests for writes, and stop before merge unless
the repository owner explicitly authorizes it. Squash merge is the default.
Never force-push or rewrite `main` history.

Important Git and CI claims must identify the exact SHA. CI evidence must also
identify the relevant run attempt when the repository contract binds evidence
to an attempt. Green PR CI does not prove a merged change healthy: verify CI for
the exact resulting `main` SHA after merge. Derive the current CI tier and
fail-closed behavior from `scripts/ci_risk_tier.py`,
`scripts/ci_post_merge_reuse.py`, `.github/workflows/ci.yml`, and their tests;
do not rely on a copied summary. If validation scope cannot be proven safe,
fail closed.

## Project Structure

Python code lives in `src/market_vault`; tests are in `tests`; settings
templates are in `config`; operational and CI helpers are in `scripts`.
Formal data, Dataset, point-in-time, CLI, and storage contracts live in
`docs/contracts`. Development and release rules live in `docs/governance`.
Runtime output belongs under ignored paths such as `data`, `catalog`,
`manifests`, and `reports`.

## Implementation and Validation

Use Python 3.11+ conventions already present in the repository: four-space
indentation, snake_case functions and variables, PascalCase classes, type
hints on public interfaces, and focused tests named `test_*.py`. Keep tests
offline unless a task explicitly requires live integration. Do not weaken,
skip, delete, or dilute tests, assertions, contracts, or validation merely to
obtain a green result.

Run checks appropriate to the changed surface and the repository's actual CI
classifier. Typical local checks include:

```powershell
python -m pytest tests/<focused-test-file>.py
./scripts/verify_full.ps1
python scripts/check_repo_hygiene.py
python scripts/check_release.py
git diff --check
```

On Windows, `scripts/verify_full.ps1` is the canonical local FULL test entry
point. Do not run FULL pytest with `--basetemp` inside a MarketVault repository
or any registered Git worktree. The wrapper proves an external temporary path
safe and checks disk capacity before pytest starts; see the Development
Playbook for its override and cleanup contract.

Do not manually force a reduced CI tier. Inspect the full diff and changed-file
scope before committing. PRs must state behavior and contract impact, tests
run, and any remaining live validation.

## Contract and Security Boundaries

Do not silently change schema, storage layout, data or point-in-time semantics,
compatibility guarantees, CLI behavior, CI architecture, or release process.
Make such impact explicit in the PR and obtain the required review visibility.
Keep OpenD SDK imports and tests compatible with the repository's offline
design unless a task explicitly changes that contract.

Before implementing a new operation that can delete, quarantine, restore over,
replace, incompatibly migrate, or otherwise make persistent runtime state
unavailable, stop and prepare a separate design-only PR under
`docs/governance/destructive_operations/`. The approved contract must already
exist in the implementation PR's base commit; adding or materially changing it
beside the implementation fails the repository gate. Follow
`docs/governance/DESTRUCTIVE_OPERATIONS.md`. Prompt text and developer intent
are not substitutes for the checked-in contract and CI gate.

Never commit or expose credentials, tokens, passwords, account details,
OpenD session details, or generated market data. Do not track `.env`, local
databases, Parquet output, caches, virtual environments, or runtime data
directories. Never move, delete, or recreate formal tags, and never create or
mutate GitHub Releases or their assets without explicit repository-owner
authorization.
