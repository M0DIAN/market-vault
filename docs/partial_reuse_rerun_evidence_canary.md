# P2-1 Partial Reuse V2 / Failed-Job Rerun Evidence Lifecycle Canary

**Status:** MEASURED — OUTCOME A (V1 already covers the failed-job rerun case)
**PR:** #76
**Type:** measurement / evidence gathering only. No production behavior changed.

## 1. Scope and method

This PR measured the REAL GitHub Actions evidence semantics for an exact-head
PR workflow run in which one formal FULL surface failed on attempt 1 and only
the failed jobs were rerun on attempt 2.

- A temporary, attempt-scoped canary was injected into the existing Python
  3.14 surface node
  `tests/test_deprecation_compatibility_v051.py::test_bar_available_at_python_int_interval_no_deprecation_warning`
  (whole-file selector `tests/test_deprecation_compatibility_v051.py` in the
  sealed manifest). The guard failed ONLY when running under GitHub Actions,
  on Python 3.14, with `GITHUB_RUN_ATTEMPT == "1"`, raising the unmistakable
  marker `P2_PARTIAL_REUSE_RERUN_CANARY_ATTEMPT1`. No test node was added,
  renamed, or parametrized; the sealed 294-node contract was untouched.
- The canary was removed byte-for-byte before this final head. The final PR
  diff is exactly this document.
- Partial Reuse V2 was NOT activated. `build_surface_reuse_plan()` was NOT
  wired into production. No post-merge skip behavior, attestation schema,
  fail-closed rule, release behavior, or CI workflow changed.

## 2. Identities

| Item | Value |
|---|---|
| Frozen base SHA (`origin/main`) | `d27158be1f4c908e208bd520e85231071df38b89` |
| Temporary measurement head SHA | `79670d42dc15bba6adc5e40ab2ac7d76b14256ed` |
| Report content commit SHA | `cfeaca3ee3a7ae934da7bf0f4c0691b9439b4c70` |
| Final PR head | NOT SELF-EMBEDDED BY DESIGN. The authoritative final head is GitHub PR metadata plus the exact-head CI run reviewed at merge time. |
| PR number | #76 |
| Canary workflow run ID | 31520818544 (run_number 258) |
| PR head SHA (both attempts) | `79670d42dc15bba6adc5e40ab2ac7d76b14256ed` |
| PR base SHA | `d27158be1f4c908e208bd520e85231071df38b89` |
| Synthetic PR merge commit | `cceb1bbcf2623848712a57ec6e627acda4d5a5a3` |
| Tested tree SHA (attested, CI-ONLY / NON-FORMAL-RELEASE HASH) | `b1bd75562d4fea25b5ab79b91f42e587354b30d9` |

`git rev-parse cceb1bbcf2623848712a57ec6e627acda4d5a5a3^{tree}` ==
`b1bd7556...` == the canary head tree: the tested tree was identical across
both attempts, as expected for the same exact head and the same PR synthetic
merge checkout. The tree digest above is a CI artifact identity, NOT a
v0.7.0 formal release hash.

### Final-head identity (self-reference note)

This document records the report-content commit SHA, not the SHA of the
commit that contains this text. Embedding the containing commit's own SHA
in tracked file content is self-referential, because changing the content
changes the commit SHA: no tracked document can state the hash of the
commit that contains it. The authoritative final PR head is therefore
GitHub PR metadata plus the exact-head CI run reviewed at merge time.

## 3. Attempt 1 — intentional failure (measured)

Run 31520818544, `run_attempt=1`, created `2026-08-11T18:04:24Z`, terminal
`18:09:14Z`, **run conclusion = failure** (intended).

| Job | Job ID | Status / Conclusion | Started → Completed |
|---|---|---|---|
| test (3.11) | 93877117070 | completed / success | 18:04:27Z → 18:09:14Z |
| test (3.14) | 93877116978 | completed / **failure** | 18:04:28Z → 18:06:14Z |
| portability-pyarrow24 | 93877117027 | completed / success | 18:04:27Z → 18:06:12Z |
| package | 93878475726 | completed / **skipped** | 18:09:14Z → 18:09:14Z |

Measured behavior: `package` (needs: test, portability-pyarrow24) was
**skipped — never started** — because a `needs` leg failed. It did not run
and produced nothing.

Python 3.14 leg steps: validator step
`Validate Python 3.14 compatibility surface` **success** with the sealed
markers `PY314_SURFACE_VALIDATION_OK`, `selectors=258`, `whole_files=2`,
`partial_selectors=256`, `resolved_nodes=294`,
`resolved_sha256=7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58`;
then `Run Python 3.14 compatibility surface` **failure** — the intentional
existing node was reached and failed with exactly
`Failed: P2_PARTIAL_REUSE_RERUN_CANARY_ATTEMPT1`
(`1 failed, 286 passed, 7 skipped`). No other failure occurred anywhere:
all hard gates passed (3.11 success, pyarrow24 success, 3.14 failure only by
the canary marker, validator success before the surface run).

## 4. Attempt 2 — failed-jobs-only rerun (measured)

`gh run rerun 31520818544 --failed` — same RUN_ID, same exact PR head SHA,
no new commit, no code edit between attempts. `run_attempt=2`, terminal
`18:13:08Z`, **run conclusion = success**.

| Job | Attempt-2 Job ID | Actually re-executed? | Conclusion | Started → Completed |
|---|---|---|---|---|
| test (3.14) | 93878737077 | **yes** (new execution) | success | 18:10:13Z → 18:12:04Z |
| test (3.11) | 93878737804 | no — carried from attempt 1 | success | 18:04:27Z → 18:09:14Z |
| portability-pyarrow24 | 93878763428 | no — carried from attempt 1 | success | 18:04:27Z → 18:06:12Z |
| package | 93879283421 | **yes** (newly executed) | success | 18:12:08Z → 18:13:07Z |

Measured GitHub semantics:

- Only the failed job (test (3.14)) was re-executed; the two successful
  attempt-1 jobs were NOT re-executed (their `started_at`/`completed_at`
  timestamps are the attempt-1 times).
- `package`, which had been *skipped* on attempt 1, **was newly executed on
  attempt 2** and ran the full chain: release checker, wheel/sdist build +
  twine check, fresh-venv install, public API smokes, wheel contents check,
  SHA256 manifest build/verify, package audit artifact upload, and
  `Create FULL CI attestation` + upload — all steps success. GitHub
  re-evaluated the `needs` closure once the rerun leg passed.
- The rerun 3.14 execution: validator **PASS** with the same sealed contract
  (`selectors=258`, `resolved_nodes=294`,
  `resolved_sha256=7561b50a...`) and `287 passed, 7 skipped` — the canary
  naturally stopped firing because `GITHUB_RUN_ATTEMPT == 2`.

## 5. Raw GitHub API evidence audit

All views queried on the terminal run (run_id 31520818544).

### 5a. `/attempts/1/jobs`
Four rows as in section 3 (3.14 failure, 3.11 + pyarrow24 success, package
skipped). Package has an attempt-1 row but it is the skipped, never-started
incarnation.

### 5b. `/attempts/2/jobs`
Four rows as in section 4. Measured quirk: the two non-rerun jobs
(3.11, pyarrow24) are re-listed under the new attempt with **new job IDs**
(93878737804 / 93878763428) but their attempt-1 timestamps — i.e. GitHub
regenerates the attempt-scoped job identity for every attempt while
preserving the execution timestamps of the execution that actually ran.

### 5c. `/jobs` (default) and `/jobs?filter=latest` — identical
Exactly four rows, all `completed`/`success`, all labeled `run_attempt=2`:

```
id=93878737077 test (3.14)         run_attempt=2 success
id=93878737804 test (3.11)         run_attempt=2 success
id=93878763428 portability-pyarrow24 run_attempt=2 success
id=93879283421 package             run_attempt=2 success
```

This is a **composite view**: 3.14/package evidence comes from attempt 2
executions, 3.11/pyarrow24 evidence is the attempt-1 execution re-listed as
attempt 2. The view does not expose per-job execution attempt — all rows
carry the run's current `run_attempt` — but it exposes exactly the four
formal surfaces with their latest successful state.

### 5d. `/jobs?filter=all`
Eight rows — both attempt incarnations of all four jobs (attempt 1 rows:
3.14 failure, 3.11 + pyarrow24 success, package skipped; attempt 2 rows as
in 5c). Distinguishing "re-executed at attempt 2" from "carried from
attempt 1" requires comparing `started_at` across the two rows per name.

### 5e. `/artifacts`
Exactly two artifacts, both attempt-2-named and unambiguous:

| Artifact ID | Name | Size | Expired |
|---|---|---|---|
| 9113212581 | `market-vault-full-ci-attestation-79670d42...-attempt-2` | 457 B | false |
| 9113212036 | `market-vault-package-79670d42...-attempt-2` | 1,269,973 B | false |

**No attempt-1 artifacts exist** (the package job never executed on
attempt 1), so there is no attestation ambiguity between attempts.

## 6. Attempt-2 attestation (validated)

Downloaded artifact 9113212581; the zip contains exactly
`ci_full_attestation.json`; strict schema validation with the repository's
existing pure functions passes:

```
schema_version=1
repository=M0DIAN/market-vault
workflow=CI
run_id=31520818544
run_attempt=2
pr_number=76
base_sha=d27158be1f4c908e208bd520e85231071df38b89
head_sha=79670d42dc15bba6adc5e40ab2ac7d76b14256ed
tested_merge_sha=cceb1bbcf2623848712a57ec6e627acda4d5a5a3
tested_tree_sha=b1bd75562d4fea25b5ab79b91f42e587354b30d9
tier=full
full_matrix_required=true
```

Every identifier matches the measured context; the tested tree matches the
actual synthetic merge commit tree. `validate_attestation_fields` ok,
`validate_attestation(context)` ok, `check_tree_equivalence` true.

## 7. Current V1 verifier verdict (existing code, unmodified)

Run against the real measured payloads with the repository's existing pure
verification functions:

- `check_jobs(filter=latest four-row view)` → **ok=True, reason=None**
  (exactly the four required surfaces, no duplicates, no extras, all
  `completed`/`success`).
- `select_attestation_artifact` → unambiguous single artifact
  (id 9113212581), not expired, plausible size.
- `parse_attestation_zip` / `validate_attestation_fields` /
  `validate_attestation` → all pass.
- `check_tree_equivalence` → true.

V1's `list_jobs()` queries `/actions/runs/{id}/jobs` with no filter, which
we measured to be exactly the filter=latest composite of section 5c — the
view V1's contract is written against. The run-level selection
(`select_successful_runs`) sees conclusion=success, run_attempt=2 on the
exact head SHA.

## 8. Decision: OUTCOME A — V1 ALREADY COVERS THIS CASE

All OUTCOME A conditions were measured and hold:

1. same exact head on both attempts — `79670d42...`;
2. failed-job rerun reached terminal success — run conclusion=success;
3. GitHub latest job evidence forms an unambiguous successful four-surface
   contract — exactly 4 rows, all success, no duplicates;
4. current V1 `check_jobs()` accepts that exact view — proven ok=True;
5. a valid exact-attempt attestation is available — attempt-2 attestation,
   schema- and context-valid, tree-valid;
6. no measured evidence gap remains for this rerun topology.

**Conclusion:** the failed-job rerun use case does NOT justify new
per-surface production attestations. No V2 activation was implemented in
this PR.

### What this means for Partial Reuse V2

The same-run failed-job rerun is fully representable by V1's single-run
model: run identity (run_id + run_attempt) + composite latest job view +
attempt-bound attestation + tree equivalence. The narrower P2 case that
remains unresolved is per-surface reuse across **distinct runs** (e.g. a
later PR run reusing surfaces proven by an earlier run of a different head,
or multi-run evidence assembly) — that is where a future #77 design would
need per-surface evidence, not for same-run rerun recovery.

### Measured caveat recorded for the record

The filter=latest composite hides per-job execution attempt (all rows are
labeled with the run's current attempt). This is not an evidence gap for V1
because the attestation binds the run/attempt, and the package chain that
creates it ran fully on attempt 2 with the composite four-surface success
as its prerequisite. Any future design that wants to distinguish
"re-executed at attempt N" from "carried from an earlier attempt" must use
`filter=all` plus per-job `started_at` comparison.

## 9. Final state assertions

- No production CI behavior changed: `.github/workflows/ci.yml`,
  `ci/python314_compatibility_surface.txt`, `scripts/ci_python314_surface.py`,
  `scripts/ci_post_merge_reuse.py`, `scripts/ci_risk_tier.py`,
  `scripts/check_release.py` and every other tracked file except this
  document are byte-identical to the frozen base.
- No release/tag/ref was changed; no tag, no release, no force-push, no
  history rewrite. Actual pre-correction history (accurate):

  frozen base `d27158be1f4c908e208bd520e85231071df38b89`
  → temporary canary `79670d42dc15bba6adc5e40ab2ac7d76b14256ed`
  → canary cleanup `50cca04950064efbf116bbd6c5d6e8b664f0fa3e`
  → measurement report `cfeaca3ee3a7ae934da7bf0f4c0691b9439b4c70`
  → attempted SHA stamp `b1ebc5c58f2ce782e3bc03a109f3c823fc5f4edc`
  → this final docs-accuracy correction commit
  (the correction commit does not embed its own SHA, for the
  self-reference reason explained in section 2)
- All digests quoted above are CI-ONLY / NON-FORMAL-RELEASE HASHes (the
  sealed PR #74 resolved digest `7561b50a...` is the pre-existing pinned
  contract value); none is a v0.7.0 formal release hash.
