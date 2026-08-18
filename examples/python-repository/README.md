# Python repository example

This directory shows how a generic Python repository adopts the CI
Optimization Framework: a ready-to-adapt `ciopt.toml` and the workflow
template that consumes it.

## What it demonstrates

- `ciopt.toml` — the strict configuration contract: docs scope,
  package-doc files, control-plane surfaces, registered components, and
  the formal job set (`[reuse].required_jobs`) matching the workflow
  template's jobs exactly.
- The template at `templates/github-actions/ci.yml` — classify → cheap
  checks → guarded heavy jobs → FULL attestation → post-merge reuse
  proof, with the exact-literal `POST_MERGE_REUSE` guard.

## Adapting it

1. Copy this `ciopt.toml` to your repository root as `ciopt.toml`
   (the framework defaults to that filename).
2. Adjust `[paths]`, `[components.*]`, and `[repository]` to your
   repository.
3. Make `[reuse].required_jobs` match your workflow's job names
   exactly — including matrix legs like `"test (3.11)"`.
4. Copy `templates/github-actions/ci.yml` and replace every
   `<PLACEHOLDER>` with your real commands.

## Expected behavior

| change | tier | heavy jobs |
| --- | --- | --- |
| `docs/` only | `docs_fast` | skipped (marker step) |
| `README.md` + `docs/` | `package_docs` | skipped (marker step) |
| eligible control-plane file | `control_plane` | full (tier is not a skip) |
| anything else, unknown, empty diff, malformed config | `full` | run |

Post-merge: a squash push to `main` whose tree equals the tested PR
merge tree, with the exact run/attempt/job evidence, emits
`POST_MERGE_REUSE=true` and skips the full matrix. Anything unproven —
including control-plane mutation — emits `reuse=false` and runs FULL.
