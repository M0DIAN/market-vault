# P2-2 Distinct-Head / Direct-Parent Surface Evidence Canary

**Status:** MEASURED — DECISION OUTCOME B — SURFACE INPUT IDENTITY IS NOT YET
DEFENSIBLE FOR PRODUCTION. SOURCE-CODE / SELECTED-INPUT DELTA SUB-PROOF:
PASS. RUNTIME / DEPENDENCY IDENTITY: UNRESOLVED FOR PRODUCTION REUSE.
Reuse was NOT activated.
**PR:** #77
**Type:** measurement / shadow evidence only. No production behavior changed.

> **Evidence-decision correction note:** after the measurement completed, a
> normal docs-only correction commit re-examined the formal decision against
> the #77 taxonomy and corrected it from OUTCOME A to OUTCOME B. Every
> empirical fact below is unchanged and was re-verified; the formal decision,
> the per-surface attestation claim, the runtime observation, and the
> residual-gap definition were corrected/added by that commit.

## 1. Scope and method

This PR measured whether a prior exact-head FULL V1 proof from Head A can
safely support reuse of selected formal surfaces on a DIRECT CHILD Head B
when the A→B delta is proven irrelevant to those surfaces.

- A single test file, `tests/test_audit_v03.py`, was chosen as the canary
  file (section 4). Head A added exactly one comment line
  (`# P2_DISTINCT_HEAD_CANARY_A`) at the top of that file. Head B — a direct
  child of Head A — replaced that one comment line with
  `# P2_DISTINCT_HEAD_CANARY_B`. No test node was added, renamed, or
  parametrized on either head.
- Both heads executed the complete FULL CI matrix (all four formal surfaces
  really ran — nothing was skipped, shadowed, or reused). The measurement
  question is whether the full A→B delta is *provably irrelevant* to the
  sealed Python 3.14 surface and the audited PyArrow 24 surface, so that a
  future V2 could reuse those surfaces' evidence across the two heads
  without re-running them.
- **SHADOW EVIDENCE ONLY.** Partial Reuse V2 was NOT activated;
  `build_surface_reuse_plan()` was NOT wired into ci.yml; no production CI
  surface was skipped; V1's attestation schema is unchanged; no per-surface
  production attestations were added; post-merge reuse behavior and release
  behavior are unchanged. The canary file was restored byte-for-byte before
  this final head; the final PR diff is exactly this document.

## 2. Identities

| Item | Value |
|---|---|
| Frozen base SHA (`origin/main`) | `62317c1aba1d141b0111444864e78f654aece284` |
| Base tree SHA | `75bdc43959052895d547e19eac3a9e62aff9e35b` |
| HEAD_A_SHA (canary marker A) | `4f6b49d71d10af5f4f8825cb0c3d63bb848c9bea` |
| HEAD_A tree SHA | `35ff31346b23d2a713f44cb9e1e917d9443b5b5e` |
| HEAD_B_SHA (canary marker B, direct child of A) | `79714d788d48d7a728f48e22b91f5807d691390f` |
| HEAD_B tree SHA | `cec5c563a0943432372ef70232ff11d201735c6a` |
| Cleanup commit (canary restored byte-for-byte) | `802e1e3df14296d776994e955548f80a5838b147` |
| PR number | #77 |
| Canary file | `tests/test_audit_v03.py` |
| Canary file blob SHA (base, A, B all differ only by the marker line; final state == base) | base/final `4b351c2b89d84edac0db910ceec9dd26adce74fb` |
| PR base SHA | `62317c1aba1d141b0111444864e78f654aece284` |
| HEAD_A workflow run | 31525169533, attempt 1, conclusion success |
| HEAD_B workflow run | 31525945139, attempt 1, conclusion success |
| HEAD_A attested tested_tree_sha | `35ff31346b23d2a713f44cb9e1e917d9443b5b5e` |
| HEAD_B attested tested_tree_sha | `cec5c563a0943432372ef70232ff11d201735c6a` |

### Final-head identity (self-reference note)

This document records the identities of the measurement heads and commits
that precede it. It does NOT embed the SHA of the commit that contains this
text: embedding a containing commit's own SHA in tracked file content is
self-referential, because changing the content changes the commit SHA — no
tracked document can state the hash of the commit that contains it. The
authoritative final PR head is therefore GitHub PR metadata plus the
exact-head CI run reviewed at review time.

## 3. Static surface relation proof (before measurement)

The canary file was selected so that its comment-only marker provably
changes exactly one formal surface's input set. Proof, all verifiable from
the frozen base:

- `tests/test_audit_v03.py` is **absent from the sealed Python 3.14 surface
  manifest** (`ci/python314_compatibility_surface.txt`, 258 selectors over
  37 files): `grep -c test_audit_v03` returns 0.
- `tests/test_audit_v03.py` is **absent from the audited PyArrow 24 surface**
  (ci.yml runs exactly 10 files: A = `test_v060_portability.py`; B =
  `test_canonical_reader.py`, `test_sample_generation_core.py`,
  `test_sample_generation_cli.py`; C = `test_canonical_materialization_v03.py`,
  `test_canonical_builder_v03.py`, `test_dataset_materialization.py`,
  `test_verified_dataset_reader.py`, `test_pit_sample_assembly.py`,
  `test_dataset_end_to_end_regression.py`): `grep -c test_audit_v03` in
  ci.yml returns 0.
- No file in either surface references it: `grep -rn test_audit_v03` across
  all `.py`/`.yml`/`.txt` files matches nothing outside the file itself (the
  sole other hit is the untracked generated build artifact
  `src/market_vault.egg-info/SOURCES.txt`, which lists source files and is
  unaffected by a comment inside one of them).
- `tests/test_audit_v03.py` imports only product modules
  (`market_vault.cli`, `market_vault.audit`, `market_vault`, ...) and no
  test module imports any other test module, so no static import chain can
  drag the canary file into either sealed surface.
- The 3.11 leg runs the FULL blanket test suite (`python -m pytest -q`), so
  the canary file IS part of the 3.11 tested surface.
- The package leg builds/audits the wheel and sdist from `src/**` +
  `pyproject.toml` and runs the release checker; the canary file is not
  part of the wheel and is referenced by none of the package steps.

Static relation (frozen base):

| Surface | Relation to canary file | Shadow expectation |
|---|---|---|
| test (3.11) | RELEVANT (blanket full-suite run includes the file) | RUN |
| test (3.14) | IRRELEVANT CANDIDATE (absent from sealed manifest; no reference chain) | REUSE_CANDIDATE |
| portability-pyarrow24 | IRRELEVANT CANDIDATE (absent from the 10-file surface; no reference chain) | REUSE_CANDIDATE |
| package | RUN (package inputs `src/**`/`pyproject.toml`/ci.yml unaffected) | RUN |

Measurement hypothesis: if the shadow plan is sound, then (a) the A→B delta
is provably irrelevant to the 3.14 and pyarrow24 surfaces, and (b) actually
executing FULL-B must show the two reuse candidates passing exactly where
the shadow plan predicted — i.e. no hidden failure.

## 4. Canary file discovery

Candidate set: 54 test files, filtered by:

1. must be a tracked test file in `tests/`;
2. must be runnable as an ordinary product test (no special runner);
3. must NOT be selected by the sealed 3.14 surface (37 manifest files excluded);
4. must NOT be selected by the audited PyArrow 24 surface (10 ci.yml files
   excluded);
5. must NOT be a control-plane / release-checker / CI-surface test
   (6 control-plane files plus `test_python314_compatibility_surface.py`
   and `test_release_v061.py` excluded);
6. must NOT import any other test module and must NOT be imported by any
   other test module;
7. must NOT be referenced by ci.yml, `scripts/check_release.py`,
   `scripts/ci_risk_tier.py`, or `scripts/ci_post_merge_reuse.py`;
8. must NOT read any other test file's source at runtime (no cross-file
   content dependency);
9. must have content-derived node IDs (no dynamic
   parametrization/collection that could shift under a comment edit);
10. must have a comment-only insertion point at the top of the file.

Candidates satisfying all rules (8): `test_audit_v03.py`, `test_backfill_v03.py`,
`test_collector.py`, `test_inventory_v03.py`, `test_moomoo_sdk.py`,
`test_quality.py`, `test_v061_cli_usability.py`,
`test_v070_python_client_examples.py`.

Selecting deterministically: lexicographically first.

**CANARY_TEST_FILE = `tests/test_audit_v03.py`**

(60 nodes, static parametrization, imports only product modules; verified
not imported or referenced anywhere.)

## 5. Head A FULL evidence (run 31525169533)

tier=full, reason=changed_path_not_in_docs_scope, full_matrix_required=true
(classifier, base → HEAD_A). All four jobs completed / success:

| Job | Job ID | Evidence |
|---|---|---|
| test (3.11) | 93891583977 | FULL blanket suite: `3874 passed, 7 skipped in 224.12s` (includes the canary file) |
| test (3.14) | 93891583984 | Validator `PY314_SURFACE_VALIDATION_OK`, `selectors=258`, `resolved_sha256=7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58`; surface run `287 passed, 7 skipped` (= 294-node contract) |
| portability-pyarrow24 | 93891583790 | A `10 passed`; B `3 passed` + `178 passed`; C `706 passed, 5 skipped` |
| package | 93892767507 | Full heavy chain: `RELEASE_CHECK_OK version=0.7.0`, wheel+sdist build, twine check, fresh-venv install, smokes, SHA256 manifest, attestation created + uploaded |

Artifacts: `market-vault-full-ci-attestation-4f6b49d7...-attempt-1` (453 B,
id 9114766676) and `market-vault-package-4f6b49d7...-attempt-1`
(1,269,149 B, id 9114766222).

Attestation (strictly validated with the repository's existing unmodified
V1 verifier functions — `validate_attestation_fields` ok,
`validate_attestation(context)` ok, `check_tree_equivalence` true):

```
schema_version=1  repository=M0DIAN/market-vault  workflow=CI
run_id=31525169533  run_attempt=1  pr_number=77
base_sha=62317c1aba1d141b0111444864e78f654aece284
head_sha=4f6b49d71d10af5f4f8825cb0c3d63bb848c9bea
tested_merge_sha=d088269ba94d18fdcc95cfe0d15d2b41d0fed1be
tested_tree_sha=35ff31346b23d2a713f44cb9e1e917d9443b5b5e
tier=full  full_matrix_required=true
```

The synthetic PR merge commit `d088269b` (GitHub API) has tree
`35ff3134...` — the tested tree equals the actual merge-checkout tree.

## 6. Head B FULL evidence (run 31525945139)

HEAD_B is a direct child of HEAD_A (parent of `79714d78...` is
`4f6b49d7...`); the A→B diff is exactly one file, one comment-line
replacement (`-1/+1` in `tests/test_audit_v03.py`).

tier=full, reason=changed_path_not_in_docs_scope, full_matrix_required=true
(classifier, base → HEAD_B). All four jobs completed / success:

| Job | Job ID | Evidence |
|---|---|---|
| test (3.11) | 93894173546 | FULL blanket suite: `3874 passed, 7 skipped` |
| test (3.14) | 93894173535 | Validator `PY314_SURFACE_VALIDATION_OK`, `selectors=258`, `resolved_sha256=7561b50a...`; surface run `287 passed, 7 skipped` |
| portability-pyarrow24 | 93894173571 | A `10 passed`; B `3 passed` + `178 passed`; C `706 passed, 5 skipped` |
| package | 93895457967 | Full heavy chain: `RELEASE_CHECK_OK version=0.7.0`, attestation created + uploaded |

Artifacts: `market-vault-full-ci-attestation-79714d78...-attempt-1` (453 B,
id 9115085564) and `market-vault-package-79714d78...-attempt-1`
(1,267,617 B, id 9115084903).

Attestation (independently validated with the same unmodified V1 verifier —
fields ok, context ok):

```
schema_version=1  repository=M0DIAN/market-vault  workflow=CI
run_id=31525945139  run_attempt=1  pr_number=77
base_sha=62317c1aba1d141b0111444864e78f654aece284
head_sha=79714d788d48d7a728f48e22b91f5807d691390f
tested_merge_sha=30e64249662bcb3c5b9780252b49e03d1ec295b2
tested_tree_sha=cec5c563a0943432372ef70232ff11d201735c6a
tier=full  full_matrix_required=true
```

Synthetic merge commit `30e64249` has tree `cec5c563...` == attested
tested_tree_sha.

## 7. Node-ID stability proof

`pytest --collect-only` on the canary file was recorded at base, at HEAD_A,
and at HEAD_B. All three collected node lists are byte-identical after
stripping the timing line: **60 collected, identical node IDs on all three
heads.** The comment markers do not perturb collection, so a comment-only
delta cannot shift any sealed node selector.

## 8. Global tree inequality (canary validity)

- HEAD_A tree `35ff3134...` ≠ HEAD_B tree `cec5c563...` (proven; the
  marker comment differs).
- Attested tested trees differ accordingly: HEAD_A tested_tree
  `35ff3134...` ≠ HEAD_B tested_tree `cec5c563...`, and each attested
  tested tree equals its own head tree.
- Therefore the two heads are genuinely DISTINCT heads in V1's evidence
  model: **V1 full reuse correctly fails closed across distinct heads**
  (the tree-equivalence gate would reject any attempt to reuse A's
  attestation for B, and B's for A). The canary is VALID: this PR genuinely
  exercises the distinct-head topology. (If the trees had matched, the
  canary would be invalid and the measurement would have stopped.)

## 9. Shadow delta proof — selected-input blob manifests

For each formal surface, every selected input file's blob (git blob SHA256
via `git show <head>:<path>`) was hashed at HEAD_A and HEAD_B and compared:

| Input set | Files | A vs B |
|---|---|---|
| 3.14 surface selected test files (37 manifest files) | 37 | ALL IDENTICAL |
| PyArrow 24 surface files (10 ci.yml files) | 10 | ALL IDENTICAL |
| `src/**` (product source) | 105 | ALL IDENTICAL |
| `pyproject.toml` | 1 | IDENTICAL (`50a8140a...`) |
| `.github/workflows/ci.yml` | 1 | IDENTICAL (`fdc25da8...`) |
| conftest.py (repo-wide) | 0 | NONE EXISTS |

The ONLY path whose blob differs between HEAD_A and HEAD_B is
`tests/test_audit_v03.py` — the canary file, which is selected by NEITHER
sealed surface (section 3). The A→B delta is therefore provably irrelevant
to the 3.14 and pyarrow24 surfaces: every selected input is byte-identical
across the two heads.

## 10. Package artifact comparison (observation only)

Package stays RUN on both heads (package inputs are unaffected); artifacts
were still compared for the record:

| Item | HEAD_A | HEAD_B | Observation |
|---|---|---|---|
| wheel `market_vault-0.7.0-py3-none-any.whl` SHA256 | `8251e593...` | `c2d9c791...` | container bytes differ |
| wheel contents (all 111 members incl. RECORD) | — | — | **byte-identical** (unzip + `diff -r`) |
| sdist `market_vault-0.7.0.tar.gz` SHA256 | `9029c208...` | `4a11f366...` | differs — expected |
| `SHA256SUMS.txt` | matches each artifact | matches each artifact | self-consistent |
| canary file in sdist? | YES (`market_vault-0.7.0/tests/test_audit_v03.py`) | YES | sdist includes `tests/`; the comment change alters the sdist blob |

Measured nuance: the wheel's content-level identity holds between A and B
(the comment is not in the wheel; RECORD and every member are identical),
and only the zip container bytes differ — the DOS timestamps embedded by
the build (`2026 Aug 11 18:59:00` vs `19:08:30`). So even a comment-only
tests/ delta does NOT produce byte-identical wheel artifacts, which is
exactly why reuse decisions must key on selected-input evidence, not on
artifact bytes.

## 11. Actual FULL-B vs shadow plan

The shadow plan (section 3) predicted: test-3.11 RUN, test-3.14
REUSE_CANDIDATE, pyarrow24 REUSE_CANDIDATE, package RUN. The actual FULL-B
run (section 6) executed ALL FOUR surfaces with zero skips:

- 3.11 really ran the full blanket suite (3874 passed) — as predicted RUN;
- 3.14 really ran its full 294-node surface and passed — the REUSE_CANDIDATE
  prediction is confirmed: had V2 reused A's 3.14 evidence, B would have
  been correctly covered (B's own run shows no failure hidden behind the
  shadow);
- pyarrow24 really ran A/B/C and passed — same confirmation;
- package really ran the heavy chain and passed with RELEASE_CHECK_OK —
  as predicted RUN.

The actual run validates the shadow plan: nothing failed where the plan
claimed the delta was irrelevant, and the plan never skipped anything in
production (all surfaces ran).

### Actual runtime observation (this A/B pair)

For THIS measured A/B pair, the visible Python 3.14 runtime was in fact
equal. Verified directly from the two raw workflow logs (both runs):

| Runtime identity item | Measured value (both heads) |
|---|---|
| Runner OS | Ubuntu 24.04 |
| Runner image | ubuntu-24.04 |
| Runner image version | `20260720.247.2` (Set up job: "Version: 20260720.247.2") |
| Python | CPython 3.14.6 (set up identically in both runs; identical setup-python cache key) |
| pip (after install step upgrade) | 26.2.1 |

Material installed dependency versions visible in the two raw logs matched
(per-job resolution identical A vs B), examples:

| Package | Resolved version | Package | Resolved version |
|---|---|---|---|
| pandas | 2.3.3 | numpy (3.14 job runtime) | 2.5.2 |
| pyarrow (dev dep, before the pyarrow24 pin) | 25.0.1 | numpy (3.11 job runtime) | 2.4.6 |
| duckdb | 1.5.5 | pytest | 9.1.1 |
| build | 1.5.0 | twine | 6.2.0 |

(The numpy nuance is real and identical in both runs: the Python 3.14 job
resolved numpy 2.5.2, the Python 3.11 jobs resolved numpy 2.4.6 — same
resolution in A and B. pyarrow 25.0.1 is the `.[dev]` resolution that the
pyarrow24 job then pins down to 24.0.0; that pin and assertion ran in both
heads.)

This proves:

- **THE ACTUAL CANARY WAS NOT CONTAMINATED BY OBSERVED RUNTIME DRIFT.** The
  environments the two FULL runs actually executed under were observably
  equal.

It does NOT prove:

- That a future SKIPPED Head-B surface would resolve the same environment
  automatically. That is the residual gap below (section 13, threat K).

## 12. Evidence-model question

*Can a prior exact-head FULL V1 proof from Head A safely support reuse of
selected formal surfaces on a DIRECT CHILD Head B when the A→B delta is
proven irrelevant to those surfaces?*

Measured answer, per condition:

1. The A→B delta is exactly known (one comment line in one file) and
   provably irrelevant to the 3.14 and pyarrow24 surfaces (section 9: every
   selected input blob identical A vs B). **Holds.**
2. Both heads carry their own independent FULL V1 proofs with valid,
   schema-strict, tree-valid attestations (sections 5–6). **Holds.**
3. The shadow expectation matched the actual FULL-B execution — no hidden
   failure on either reuse candidate. **Holds.**
4. V1's evidence model is head-bound (`tested_tree_sha` equivalence): A's
   attestation cannot be reused for B and B's cannot be reused for A, and
   V1's gate correctly rejects such reuse (section 8). **Holds — V1 is
   sound; it just cannot express the narrower claim.**

The source-input / exact-delta sub-question is answered affirmatively for
this narrow direct-parent case. The complete production-safety question is
NOT yet answered affirmatively, because runtime/dependency identity for a
skipped target surface remains unresolved. Therefore the formal decision
remains OUTCOME B. The measured source-evidence chain indicates that a
future implementation MAY be able to use:

- the existing source-head V1 FULL attestation;
- the source-head successful formal surface job;
- exact direct-parent topology;
- exact A→B delta;
- a frozen surface-input identity contract;
- and an independently proven runtime/environment identity.

**No new per-surface attestation artifact or schema is shown to be
necessary by #77.** Whether a future implementation chooses to introduce
one is a separate design decision, not a #77 measurement finding. The
canary's measured contribution is that the delta proof itself is
mechanically sound and that full execution agrees with the shadow
prediction — not that a particular future evidence artifact is required.

## 13. Threat model (A–K)

| # | Threat | Measured status |
|---|---|---|
| A | Non-direct ancestry (B not a direct child of A) | NOT COVERED. The measurement only covers the direct-parent case; arbitrary ancestry, cross-branch, and transitive chaining are explicitly out of scope (section 15). |
| B | Rename of a selected file | NOT EXERCISED. The A→B delta is a comment inside one file; no path changes. A rename changes blob identity (old path gone, new path present) and would need explicit rename-aware handling in any V2 delta prover. |
| C | `src/**` change | MEASURED SAFE HERE — 105 src blobs identical A/B. Any src change would touch the package surface and the 3.11 blanket suite; the delta prover must include src/** in its selected inputs for every surface. |
| D | `pyproject.toml` change | IDENTICAL A/B. A pyproject change would alter package inputs and dependency resolution (environment drift, threat K); must invalidate package and both test legs conservatively. |
| E | Control-plane change (ci.yml, scripts/**, classifier) | ci.yml IDENTICAL A/B; the classifier itself ran tier=full for both heads. A control-plane change must conservatively invalidate ALL surfaces (the control plane defines the evidence itself). |
| F | conftest.py hooks | NONE EXISTS repo-wide (0 conftest files). A conftest addition would be a selected input of every test surface; the delta prover must include it. |
| G | Change to a selected test file | NOT EXERCISED (canary file is selected by neither surface). A change to any of the 37/10 selected files must invalidate that surface — this is the core per-surface rule the delta prover encodes. |
| H | Unknown/unclassified path | The classifier measures `unknown_changed=true` for the canary delta and fail-closes to tier=full; the delta prover must treat any path not provably covered as invalidating everything (fail-closed). |
| I | Deletion | NOT EXERCISED. A deletion changes the 3.11 blanket surface (it runs the whole suite) and any surface selecting the deleted path; must conservatively invalidate. |
| J | Dynamic import ambiguity (test modules importing test modules) | MEASURED ABSENT: no test module imports another test module; the canary file has no reference chain into either sealed surface (section 3). |
| K | Dependency / environment drift between the A and B runs | **RESIDUAL GAP — RUNTIME / DEPENDENCY IDENTITY.** For THIS measured A/B pair the visible runtime was in fact equal (section 11: runner image `20260720.247.2`, CPython 3.14.6, pip 26.2.1, identical per-job resolved dependency versions — the canary was not contaminated by observed runtime drift). But source-input equality alone is insufficient for production reuse: the current dependency/runtime contracts contain ranges and externally resolved runtime state (e.g. `numpy>=1.23.2` resolved at install time by pip against PyPI state). If Head B's heavy surface is skipped, there is no heavy job from which to infer what exact dependency environment B would have used — the observed equality of two RUNNING runs does not carry over to a skipped one. A future production cross-head reuse verifier therefore needs an additional fail-closed runtime identity mechanism. Fail-closed rule: **runtime identity unproven or unequal => RUN.** |

## 14. Decision: OUTCOME B — SURFACE INPUT IDENTITY IS NOT YET DEFENSIBLE FOR PRODUCTION

Formal decision per the #77 taxonomy:

- **SOURCE-CODE / SELECTED-INPUT DELTA SUB-PROOF: PASS.** The experiment
  successfully proves the source-side claim: for a direct-parent
  transition, exact selected-source/test inputs can be proven unchanged at
  surface granularity even when the whole Git tree changes.
- **RUNTIME / DEPENDENCY IDENTITY: UNRESOLVED FOR PRODUCTION REUSE.** The
  experiment does not close the runtime side: a future skipped Head-B
  surface has no heavy job from which to infer its environment.

The measured gates that DID hold remain valid and are preserved:

1. direct-parent topology with exactly-known delta (parent proven);
2. delta provably irrelevant to both sealed surfaces (blob manifests);
3. both heads' FULL runs passed independently, with valid attestations;
4. actual FULL-B confirmed the shadow plan (no hidden failure);
5. V1 correctly fails closed across distinct heads (trees differ).

But per the original #77 decision taxonomy, the unresolved
runtime/environment identity boundary requires **OUTCOME B** — the canary
is NOT failed and NOT contaminated (the observed runtime of THIS A/B pair
was equal, section 11); rather, surface input identity is not yet
defensible for production because source-input equality alone does not
establish the runtime identity of a skipped target surface (threat K).

**Conclusion:** cross-head production reuse is NOT ready for activation.
Reuse was NOT activated; no V2 implementation was made in this PR.

## 15. Architecture boundary

**PROVEN:**

For a direct-parent transition, exact selected-source/test inputs can be
proven unchanged at surface granularity even when the whole Git tree
changes. (This PR: 37-file Python 3.14 selected-input equality, 10-file
PyArrow24 equality, `src/**` equality, `pyproject.toml` / ci.yml / manifest
/ validator equality, no conftest; 60-node stability; tree inequality.)

**NOT YET PROVEN:**

That the target head would execute under an equivalent runtime / dependency
environment when the heavy target surface itself is skipped.

**Therefore: cross-head production reuse is NOT ready for activation.**

The evidence does NOT support arbitrary ancestry, cross-branch reuse,
transitive chaining (A→B→C), or any reuse where the delta cannot be fully
enumerated and proven irrelevant. V1's head-bound evidence model remains
the production gate; it correctly rejects cross-head reuse today.

### Future options (identification only — MUST NOT be implemented in #77)

The measurement report may identify, but must not implement, either of the
following defensible directions. That is future #78 work; neither option is
chosen or built here.

**OPTION 1 — LIGHTWEIGHT TARGET RUNTIME FINGERPRINT.** Before reusing a
heavy surface on Head B, run a lightweight bootstrap that resolves the same
environment and computes a deterministic runtime fingerprint. Candidate
inputs: runner OS / architecture; runner image identity/version; resolved
action/toolchain identity; exact Python version; exact installed
distribution name/version set; surface-specific forced runtime pins.
Canonicalize deterministically and hash it. Require
`HEAD_A_RUNTIME_FINGERPRINT == HEAD_B_RUNTIME_FINGERPRINT`; otherwise RUN
the surface.

**OPTION 2 — LOCKED / PINNED ENVIRONMENT CONTRACT.** Introduce a separately
reviewed fully pinned environment/lock contract whose identity can be
proven unchanged A→B. The lock/toolchain contract hash then participates in
the surface evidence identity.

## 16. Cleanup

The canary file was restored byte-for-byte from the frozen base
(`git checkout origin/main -- tests/test_audit_v03.py`; verified with
`git diff --exit-code` against `62317c1...`; blob SHA
`4b351c2b89d84edac0db910ceec9dd26adce74fb` == base). Restored in a normal
commit; no amend, no rebase, no force-push, no history rewrite.

## 17. Final state assertions

- The final PR diff is exactly this document (one file added).
- `.github/workflows/ci.yml`, `ci/python314_compatibility_surface.txt`,
  `scripts/ci_python314_surface.py`, `scripts/ci_post_merge_reuse.py`,
  `scripts/ci_risk_tier.py`, `scripts/check_release.py`,
  `tests/test_ci_post_merge_reuse.py`,
  `tests/test_python314_compatibility_surface.py`, `src/**`,
  `pyproject.toml`, and the canary test file are byte-identical to the
  frozen base `62317c1...`.
- Actual history (accurate):

  frozen base `62317c1aba1d141b0111444864e78f654aece284`
  → Head A `4f6b49d71d10af5f4f8825cb0c3d63bb848c9bea` (marker A)
  → Head B `79714d788d48d7a728f48e22b91f5807d691390f` (marker B, direct child)
  → cleanup `802e1e3df14296d776994e955548f80a5838b147` (canary restored)
  → the measurement report commit
  → this final evidence-decision correction commit (OUTCOME A → OUTCOME B;
    runtime observation and residual-gap definition added; per-surface
    attestation claim corrected; does not embed its own SHA, per section 2)

- All digests quoted above are CI-ONLY / NON-FORMAL-RELEASE HASHes; the
  sealed PR #74 resolved digest `7561b50a...` is the pre-existing pinned
  contract value; none is a v0.7.0 formal release hash.
- No tag, GitHub Release, main ref, or formal release ref was changed. The
  PR branch ref advanced only through the normal commits documented above;
  no amend, rebase, or force-push was used. STOP BEFORE MERGE — this PR is
  measurement-only and must not be merged.
