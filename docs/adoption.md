# Adoption guide

The framework is designed to be adopted gradually, one phase at a time.
**Enabling all optimizations at once is strongly discouraged**: observe
first, then enable safe tiers, then enable reuse — and keep the
fail-closed guards intact at every step.

## Phase 1 — classification only / observe

Goal: the classifier runs on every CI run, and its decisions are
logged. Nothing is skipped yet.

1. Copy `ciopt.example.toml` to `ciopt.toml`; set the docs scope,
   package-doc files, control-plane surfaces, registered components,
   and the formal job set to match your repository exactly.
2. Add the `Classify change tier (event-aware, fail-closed)` step from
   [templates/github-actions/ci.yml](../templates/github-actions/ci.yml)
   to every job. It resolves the mode/refs from the event
   (`pull_request` → `base.sha`/`head.sha`; anything else →
   `github.event.before`/`github.sha`), invokes
   `ci-opt classify --output github-env`, and exports the `CI_*`
   assignments — or, if the classifier exits non-zero, explicitly
   exports `CI_TIER=full` /
   `CI_TIER_REASON=classifier_error_fail_closed` /
   `CI_FULL_MATRIX_REQUIRED=true`. **No guard depends on the tier
   yet**; the fail-closed wrapper is already in place.
3. Run CI for a while. Every run logs `tier=<...>` and
   `reason=<...>`. Check that the observed classifications match your
   expectations — especially that nothing surprising classifies as a
   fast tier, and that unknown paths land on `full`.

Phase 1 alone already gives you the audit trail: every change range
carries its classification reason in the CI log.

## Phase 2 — enable safe tiers per surface

Goal: each guarded heavy step skips only for the validated tier whose
contract makes that exact surface unnecessary. **The tiers are
per-surface, not a single switch** — one guard does not fit every
heavy step.

1. **Test surface (full matrix) — triple guard**, exactly as in the
   template: `docs_fast` may skip it, and `package_docs` may skip it
   (core tests are unnecessary under a validated package-doc contract):

   ```yaml
   if: |
     env.POST_MERGE_REUSE != 'true' &&
     env.CI_TIER != 'docs_fast' &&
     env.CI_TIER != 'package_docs'
   ```

2. **Package surface (build + package validation) — double guard**:
   `package_docs` MUST NOT skip package validation — a package-doc
   change (e.g. README) is package metadata. Only `docs_fast` may skip
   this surface:

   ```yaml
   if: |
     env.POST_MERGE_REUSE != 'true' &&
     env.CI_TIER != 'docs_fast'
   ```

   Add the marker steps so skips are visible in the logs (skips alone
   are silent): `PACKAGE_DOCS_TESTS_MAY_SKIP=true` on the test surface
   and `PACKAGE_DOCS_PACKAGE_VALIDATION_MUST_RUN=true` on the package
   surface.

3. **`control_plane` is OPT-IN and disabled by default** — the
   template never claims a validated control-plane subset. Activation
   requires, in order:
   a. implement a dedicated, conservative control-plane validation
      surface step that runs **only** when `env.CI_TIER ==
      'control_plane'` — validating exactly the eligible paths;
   b. populate `control_plane_eligible` (every rule must be contained
      by `[paths].control_plane`);
   c. gate every FULL surface (any workflow/config/control-plane
      mutation not covered by that surface must stay `full`);
   d. shadow/observe first — compare the `control_plane` fast results
      against FULL on the same change before trusting it.

   Never widen the eligible list beyond what that surface covers.

The guards keep the fail-closed property: unset or unknown
`CI_TIER` means the heavy steps run.

## Phase 3 — enable post-merge FULL reuse

Goal: on eligible squash merges to `main`, reuse the PR FULL evidence
instead of rerunning the FULL matrix — only when every proof succeeds.

1. In the package job, add the `Create FULL CI attestation` step
   (`ci-opt create-attestation --config ciopt.toml ci_full_attestation.json`)
   guarded by `github.event_name == 'pull_request' && env.CI_TIER ==
   'full' && env.CI_FULL_MATRIX_REQUIRED == 'true'`, and upload the
   result with the hardcoded name
   `ci-full-attestation-${{ github.event.pull_request.head.sha }}-attempt-${{ github.run_attempt }}`
   (with `if-no-files-found: error`). The upload name must stay
   identical to the config `artifact_prefix` — both are
   `ci-full-attestation-` by default; never parameterize the workflow
   name with `vars` / `default(...)`.
2. In **every** formal job, add the `Post-merge FULL reuse proof (V1,
   read-only)` step **before the guarded heavy steps** — never after
   them — guarded by `github.event_name == 'push' && github.ref ==
   'refs/heads/main' && env.CI_TIER == 'full'`. The step runs
   `ci-opt verify-reuse --config ciopt.toml`, consumes its output, and
   on any non-zero exit (verifier crash) explicitly exports
   `POST_MERGE_REUSE=false` / `reason=verifier_crash_fail_closed` so
   heavy validation still runs. `$GITHUB_ENV` is job-scoped: each job
   must run its own proof; there is no cross-job plumbing.
3. Verify the marker steps: `FULL_TESTS_REUSED_FROM_VERIFIED_PR` when
   reuse fired, `FULL_TESTS_SKIPPED_BY_POLICY` for fast tiers.

Before enabling Phase 3, make sure `[reuse].required_jobs` exactly
matches your workflow's job names. A single mismatch silently (but
safely) denies reuse forever — it never skips validation.

## Guard checklist (never weaken)

- a heavy surface skips only when EITHER that exact surface is
  explicitly unnecessary under a validated tier contract (`docs_fast`
  may skip any heavy surface; `package_docs` may skip the core matrix
  but never the package surface), OR `POST_MERGE_REUSE` is the exact
  literal `"true"`;
- an unset / unknown `CI_TIER` or `POST_MERGE_REUSE` always runs;
- the classifier wrapper never lets a classifier failure become a fast
  tier: non-zero exit ⇒ explicit `CI_TIER=full` /
  `CI_TIER_REASON=classifier_error_fail_closed` /
  `CI_FULL_MATRIX_REQUIRED=true`;
- the verifier wrapper never lets a verifier crash become reuse:
  non-zero exit ⇒ explicit `POST_MERGE_REUSE=false` /
  `reason=verifier_crash_fail_closed`;
- every checkout uses `fetch-depth: 0` (the classifier and verifier
  resolve refs and diff against full history);
- the attestation upload uses `if-no-files-found: error` (a missing
  attestation must fail the run, never enable reuse);
- the token binding for the reuse proof is step-scoped and read-only.

## Rollback

Because the guards are strict, disabling an optimization is simply
removing it: drop the reuse step or the fast-tier guards, and every run
returns to FULL. No state is stored anywhere except the attestation
artifacts, which expire on their own.
