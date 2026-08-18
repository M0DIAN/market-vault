# Security model

## Trust boundary

The framework is a **read-only decision layer**:

- it never writes to the repository (no stash / reset / merge / branch /
  tag / ref mutation);
- it never runs `shell=True`, never evaluates strings, and never
  interpolates config into commands;
- its GitHub token is used with `contents: read`, `pull-requests:
  read`, `actions: read` only, is never logged, is sent only to
  `api.github.com`, and is stripped on cross-host redirect;
- the only write it performs is the attestation JSON at an explicit
  output path.

The trust boundary is the configured contract itself: the formal job
set, the control-plane surfaces, the workflow guards, and the
attestation schema. An attacker who can rewrite `ciopt.toml`, the
workflow, or the classifier's own files is out of scope — those are
control-plane paths precisely because their mutation forces FULL.

## Fail-closed semantics

The invariant in one line:

> Cannot prove safe optimization ⇒ do more work. Never: cannot prove ⇒
> skip work.

Concretely, every ambiguity lands on the expensive side:

| condition | result |
| --- | --- |
| unknown / unset / malformed config | `tier=full`, `reuse=false` |
| unknown changed path | `full` |
| empty diff | `full` |
| unresolvable ref / git failure | `full` (classify) / `reuse=false` (verify) |
| GitHub API / network failure | `reuse=false` |
| verifier internal error | `reuse=false` (`verifier_internal_error`) |
| verifier process crash (non-zero exit) | workflow exports `POST_MERGE_REUSE=false` (`reason=verifier_crash_fail_closed`) |
| classifier failure (non-zero exit) | workflow exports `CI_TIER=full` (`CI_TIER_REASON=classifier_error_fail_closed`) |
| anything other than the literal `"true"` in `POST_MERGE_REUSE` | heavy validation RUNS |
| a fast tier that does not cover the exact surface (e.g. `package_docs` reaching the package surface) | heavy validation RUNS — a heavy surface may skip only when that exact surface is explicitly unnecessary under a validated tier contract, or `POST_MERGE_REUSE` is the literal `"true"` |

## Attack / failure cases

### Stale evidence

The verifier only accepts runs of the configured workflow on the exact
PR head SHA, sorted newest-first; older-head runs are excluded by the
exact head filter. A stale run can never be mistaken for the final one.

### Base drift

The recorded PR base SHA must equal the push's `before` SHA, and the
new main commit's single parent must equal `before` too. If the base
moved between the PR and the merge, the topology or identifier check
fails and reuse is denied.

### Run attempt ambiguity

The attestation artifact name encodes the run attempt, the attestation
records it, and the verifier requires both to match the selected run.
A re-run of the same head (`run_attempt=2`) can only be reused if its
own attempt-bound artifact proves the full chain for that attempt.

### Artifact ambiguity

Exactly one matching artifact is accepted. Missing, expired,
implausibly sized, duplicate, or malformed artifacts deny reuse. The
zip must contain exactly the attestation member; anything extra is
rejected (extraction safety, size cap 64 KiB).

### Tree mismatch

The core proof: `git rev-parse <main>^{tree}` must equal the
attestation's `tested_tree_sha`. Any difference — including changes
made by the merge itself or by a concurrent push — denies reuse and
runs FULL.

### Control-plane mutation

Even with tree equivalence, a merged change touching any configured
control-plane path denies reuse. Rename old + new paths both count, so
renaming a control-plane file out (or into) the surface still forces
FULL. The control-plane check runs before any API call: a control-plane
merge never even queries the API.

### Proof tampering

An attestation is only accepted when its repository, workflow, run id,
run attempt, PR number, base SHA, and head SHA exactly match the
independently proven context, and when its tier is `full` with
`full_matrix_required=true`. A forged or mislabelled artifact for the
wrong run/attempt/head cannot pass the identifier cross-checks, because
those identifiers are re-derived from git + API, not trusted from the
artifact.

### Verifier bugs

Any unexpected exception inside the verifier is caught and converted to
`reuse=false` — never to `reuse=true`. `skip_heavy_validation()` is the
only predicate under which a heavy step may skip, and it returns `True`
only for the exact literal `"true"`.

Beyond the in-process catch, the workflow wraps the verifier invocation:
a verifier **process crash** (non-zero exit — interpreter crash, kill,
OOM, anything that bypasses the in-process catch) makes the wrapper
explicitly export `POST_MERGE_REUSE=false` /
`reason=verifier_crash_fail_closed`, and the guarded heavy steps run.
The classifier is wrapped the same way: any non-zero exit exports
`CI_TIER=full` / `CI_TIER_REASON=classifier_error_fail_closed` /
`CI_FULL_MATRIX_REQUIRED=true`. There is no code path that fails open.
