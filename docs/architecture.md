# Architecture

The framework is a read-only decision layer around your existing CI. It
never runs your tests itself; it decides, deterministically and
fail-closed, whether a given change range requires FULL validation, and
whether a merged commit may reuse the FULL evidence a pull request
already produced.

## Components

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│ ci-opt classify             │     │ ci-opt verify-reuse          │
│                             │     │                              │
│  git layer ──▶ classifier   │     │  git layer ──▶ V1 proof       │
│                  │          │     │  GitHub API ─┘   │            │
│                  ▼          │     │                 ▼             │
│            impact model     │     │      attestation validation   │
└─────────────────────────────┘     └──────────────────────────────┘
```

### Classifier boundary

`ci-opt classify` resolves the exact changed-file list between two git
refs (three-dot merge-base diff for `pull_request` mode, direct pushed
range for `push` mode) and maps it to one of four stable tiers:
`docs_fast`, `package_docs`, `control_plane`, `full`. The classifier is
pure with respect to the config and the path list: same input, same
output. It never reads the network and never mutates the repository.

The tier decision is deliberately conservative and ordered
(fail-closed precedence):

1. empty diff ⇒ `full`
2. any path outside every known scope (docs, package-doc files,
   control-plane rules, registered component paths) ⇒ `full`
3. docs-only ⇒ `docs_fast`
4. package-doc file + docs ⇒ `package_docs`
5. exact control-plane eligible subset (or docs) with ≥ 1 control-plane
   path ⇒ `control_plane`
6. control-plane mutation outside the eligible subset ⇒ `full`
7. core component ⇒ `full`
8. any registered component without a validation contract ⇒ `full`
9. anything else ⇒ `full`

Rule 5 is an OPT-IN extension: `control_plane_eligible` defaults to
empty (disabled), so in every default config a workflow/config mutation
lands on `full` via rule 6. The generic template never claims a
validated control-plane subset; a downstream repository activates the
tier only after implementing and reviewing its own conservative
control-plane validation surface (see [adoption.md](adoption.md)).

### Config

`ciopt.toml` (schema version 1) is the single place where project
assumptions live: docs scope, package-doc files, control-plane surface,
the fast-eligible control-plane subset, registered components, and the
post-merge reuse contract (formal job set, control-plane exclusion
paths, artifact prefix). Parsing is strict and deterministic — no
`eval`, no shell interpolation. A malformed config fails closed to
`full` / `reuse=false`. See [configuration.md](configuration.md).

### Evidence producer

On a `pull_request` FULL run, the workflow's package job invokes
`ci-opt create-attestation` after the full chain succeeds. It records
the exact identifiers (repository, workflow, run id, run attempt, PR
number, base SHA, head SHA), the synthetic PR merge commit SHA
(`GITHUB_SHA`), and its tree SHA. The JSON is deterministic (stable key
order, UTF-8, newline-terminated), strictly validated before writing,
and uploaded as an attempt-bound artifact named
`<prefix><head_sha>-attempt-<run_attempt>`.

### Evidence consumer

On an eligible push to `main`, `ci-opt verify-reuse` proves all eight
V1 conditions in order. Every failure yields `POST_MERGE_REUSE=false`
with a specific `reason=`; the workflow guards then run normal FULL
validation. Proof failure is never a CI failure.

### GitHub API

The read-only adapter (`github_api.py`) uses `contents: read`,
`pull-requests: read`, `actions: read` only. The token is never logged,
is sent only to `api.github.com`, and is stripped on cross-host
redirects (artifact CDN). Network/API failures map to `reuse=false`.

### Workflow guards

Every formal job in the template
([templates/github-actions/ci.yml](../templates/github-actions/ci.yml))
and in the framework self-CI
([.github/workflows/ci.yml](../.github/workflows/ci.yml)) runs the same
order: checkout (`fetch-depth: 0`) → setup → install → classify →
post-merge FULL reuse proof (V1) → cheap checks → heavy validation.

**Classification is event-aware and fail-closed.** The step selects the
mode and refs from the event (`pull_request` → `base.sha`/`head.sha`/`pull_request`;
anything else → `github.event.before`/`github.sha`/`push`) and invokes
`ci-opt classify --output github-env`, which emits only valid GitHub
Actions `CI_*` environment assignments (never raw `files:` blocks). If
the classifier exits non-zero — config error, unresolvable ref, git
failure — the workflow explicitly exports:

```text
CI_TIER=full
CI_TIER_REASON=classifier_error_fail_closed
CI_FULL_MATRIX_REQUIRED=true
```

Classifier inability must never silently create a fast tier.

**The V1 reuse proof runs before heavy validation, in every formal
job** (job-scoped `GITHUB_ENV` does not propagate between jobs). On a
full push to `main` the proof step runs `ci-opt verify-reuse`; on
success its output is consumed, on any non-zero exit the workflow
explicitly exports `POST_MERGE_REUSE=false` /
`reason=verifier_crash_fail_closed`. Invariant: proof failure or
verifier crash ⇒ fresh heavy validation runs.

**Every heavy surface is guarded by the exact literal, and tier
semantics are per-surface.** Two dimensions compose, never merge:

1. **Reuse dimension (post-merge):** the guard always contains
   `env.POST_MERGE_REUSE != 'true'`.
2. **Tier dimension (per-surface):** a surface may skip only when its
   own validation is explicitly unnecessary under a validated tier
   contract.

The template's test surface (full matrix) uses the full triple guard:

```yaml
if: |
  env.POST_MERGE_REUSE != 'true' &&
  env.CI_TIER != 'docs_fast' &&
  env.CI_TIER != 'package_docs'
```

The package surface uses only the double guard — `package_docs` MUST
NOT skip package validation (a package-doc change such as README is
package metadata):

```yaml
if: |
  env.POST_MERGE_REUSE != 'true' &&
  env.CI_TIER != 'docs_fast'
```

**A heavy surface may skip only when EITHER (1) that exact surface is
explicitly unnecessary under a validated tier contract, OR (2)
`POST_MERGE_REUSE` is the exact literal `"true"`. Anything else runs.**
In particular, `package_docs` does NOT authorize skipping package
validation. An unset `CI_TIER` fails closed because the guards compare
`!= 'docs_fast'` / `!= 'package_docs'`. Cheap checks (compile, metadata
sanity) run unconditionally; on PR FULL runs the real package surface
still executes before the attestation is created, so attestation
evidence always covers a real validation run.

### Exact-tree model

The core safety proof is tree equality, not commit equality. The PR
run tested a synthetic merge commit; the squash merge on `main` is a
different commit. Commit SHAs therefore differ by construction. What
must be identical is the **tree**: `git rev-parse <main-sha>^{tree}`
must equal the attestation's `tested_tree_sha`. See
[evidence-model.md](evidence-model.md).
