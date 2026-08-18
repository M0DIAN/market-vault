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

The template ([templates/github-actions/ci.yml](../templates/github-actions/ci.yml))
guards every heavy step with the exact literal:

```yaml
if: env.CI_TIER != 'docs_fast' && env.CI_TIER != 'package_docs' && env.POST_MERGE_REUSE != 'true'
```

Heavy validation may skip **only** when `POST_MERGE_REUSE == "true"`.
Anything else — including an unset or unknown tier — runs. An unset
`CI_TIER` fails closed because the guard compares `!= 'docs_fast'`.

### Exact-tree model

The core safety proof is tree equality, not commit equality. The PR
run tested a synthetic merge commit; the squash merge on `main` is a
different commit. Commit SHAs therefore differ by construction. What
must be identical is the **tree**: `git rev-parse <main-sha>^{tree}`
must equal the attestation's `tested_tree_sha`. See
[evidence-model.md](evidence-model.md).
