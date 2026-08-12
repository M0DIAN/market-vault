# P2-5 Closed-World Build Execution Canary (PR #80)

**Status: MEASURED / OUTCOME A (narrowed) — READY FOR INDEPENDENT REVIEW — STOP BEFORE MERGE**

This is the permanent record of PR #80's measurement. All measurement code
was temporary (removed in commit `8d27d30`); the permanent diff of this PR is
this document only.

> **Correction record (independent review):** this document was corrected
> after independent review of the authoritative evidence artifacts. Three
> findings were incorporated: (1) the retained cross-head comparator compares
> `runner`/`python`/`resolver`/`dependency_contract`/`action_contract`/
> `resolved_distributions`, and the authoritative replay gives
> `CLOSED_WORLD_IDENTITY_MATCH=false` with `first_differing_field:runner` for
> both surfaces — Head A and Head B ran on different runner images
> (runtime identity drifted); (2) a new remaining P2 gap was discovered: the
> runtime fingerprint binds `moomoo-api`'s source sdist, not the exact
> cached/built wheel bytes actually installed; (3) the offline runtime replay
> gate validates the recorded receipt + report presence, it does not
> independently recompute full report-vs-resolution equality. The closed-world
> build execution sub-proof itself (OUTCOME A, narrowed as defined in §12)
> remains PASS. Head A/Head B were NOT re-run; no measurement instrumentation
> was recreated.

## 1. The question

[PR #79](https://github.com/M0DIAN/market-vault/pull/79) proved that the
*resolved* build dependency set of the real, editable MarketVault build is
exactly `{packaging, setuptools, wheel}`. It left one gap open: a resolution
proof says what pip *would* install, not how a *real* build executes. pip's
default mode (build isolation) lets pip itself fetch and install anything the
backend declares dynamically — a backend could request a "fourth build
dependency" pip had never resolved before, and pip would silently install it
out of band.

The P2-5 canary measures whether the real editable build can be executed in a
**closed world**: an exact, hash-locked prebuild environment with pip's
build-dependency management disabled (`--no-build-isolation --no-deps
--check-build-dependencies`, `PIP_NO_INDEX=1`, `--require-hashes`), so pip has
no channel to auto-install anything outside the pinned fingerprint set.

**Constraint: measurement/shadow evidence only.** Partial Reuse V2 was NOT
activated, no production skip was added, no package reuse was authorized, no
test-3.11 reuse was authorized, the V1 attestation schema was NOT changed, and
no release behavior changed. The audited candidate surface remains strictly
`test-3.14` + `pyarrow24`.

## 2. Measurement protocol (summary)

For each surface (`test-3.14` with `-e .[dev]`; `pyarrow24` with the
`pyarrow==24.0.0` pin) the temporary script
`scripts/ci_closed_world_build.py` (Head A/B only, since removed) ran:

1. **Runtime resolution** — pip dry-run report of `-e .[dev]` (+ pin) from a
   fresh venv; canonical name/version/artifact records.
2. **Build set resolution** — declared `build-system.requires` → static dry-run
   → `get_requires_for_build_editable` hook probe (probe 1, isolated env) →
   effective set → wheel-only materialization (exact bytes, SHA256; sdists /
   VCS / direct URLs rejected) into `exact_build_wheelhouse/`.
3. **Exact prebuild env** — fresh venv, `pip install --upgrade pip` (26.2.1),
   then `PIP_NO_INDEX=1 PIP_FIND_LINKS=<wheelhouse> pip install
   --require-hashes -r exact_build_environment.txt` (every line
   `name==version --hash=sha256:…`). Hook probe 2 in that exact env must equal
   probe 1 (`DYNAMIC_HOOK_STABLE`).
4. **Closed-world build** — `pip install --no-build-isolation --no-deps
   --check-build-dependencies --report actual_editable_install_report.json -e .`
   with `PIP_NO_INDEX=1` in the exact env. Pre/post `importlib.metadata`
   inventories must delta to exactly `{market-vault: 0.7.0}` added, nothing
   changed or removed.
5. **Synthetic sentinel proof** — a runtime-generated wheel
   `p2_closed_world_sentinel-0.0.1` plus an in-tree backend delegating to
   `setuptools.build_meta` that demands the sentinel via
   `get_requires_for_build_editable` and imports it in `build_editable`.
   Under ordinary isolation the sentinel must be auto-installed (control);
   under the closed-world command it must be rejected while remaining
   available in the candidate source (negative proof).
6. **Final runtime match** — runtime deps installed from the pyproject
   dependency strings (+ `pyarrow==24.0.0` pin), then the final env compared to
   the pre-install resolution (report records + live `importlib.metadata`
   cross-check + `pyarrow.__version__ == "24.0.0"` on pyarrow24).
7. **Evidence bundle** — `EVIDENCE_MANIFEST.json` (every retained file bound
   by size + SHA256, duplicate-path hardened; the manifest itself cannot bind
   its own bytes so it is excluded from its own entry), verifier self-copy
   (`verifier_source.py`) bound by the receipt's
   `verifier_script_sha256`, and an offline replay that re-derives the
   file-derived gates from the bundle alone.

All legs fail closed: any crash, mismatch, or unexpected install flips
`CLOSED_WORLD_BUILD_VALID` to false.

## 3. Heads

| Head | Commit | Parent | Diff |
|---|---|---|---|
| Head A | `1b59ff9` (after fix batch; initial `623f244`) | `98eb52e5` (#79, frozen base) | instrumented ci.yml + script + tests + marker `_A` |
| Head B | `19ac23c` | `1b59ff9` | exactly one comment line: marker `_A` → `_B` |
| Cleanup | `8d27d30` | `19ac23c` | ci.yml + `tests/test_audit_v03.py` restored byte-for-byte to base; script + tests removed |
| Evidence accuracy correction | HEAD of PR (this commit; SHA deliberately not self-embedded) | `8d27d30` | this document only (corrections) |

Frozen base `98eb52e582ffb975720b7d389fe3ea3a852d7848` was re-verified equal to
`origin/main` before every push (no BASE_DRIFT).

## 4. CI runs

| Run | Head | Result |
|---|---|---|
| `31562238961` | `623f244` | failure — measure crash (script bugs, fixed in `1b59ff9`); no evidence conclusions drawn from it |
| `31563580625` | `1b59ff9` (Head A) | **success — 4/4 jobs** (test 3.11, test 3.14, package, portability-pyarrow24) |
| `31563995966` | `19ac23c` (Head B) | **success — 4/4 jobs** |
| `31564470710` | previous docs-only head | success — superseded by the exact-head run of this correction commit; stale for merge authorization |

The measure steps ran in jobs `test (3.14)` and `portability-pyarrow24` only,
under the tier guard (`docs_fast` / `package_docs` / post-merge-reuse /
control-plane short-circuits apply), `|| true` shadow semantics: measurement
never fails a job. Evidence was uploaded as
`market-vault-closed-world-{surface}-<sha>-attempt-<n>` artifacts.

## 5. Results per surface (Head A = Head B)

### test-3.14

| Verdict | Value |
|---|---|
| `CLOSED_WORLD_BUILD_VALID` | `true` |
| `CLOSED_WORLD_LEG_READY` | `true` |
| `FINAL_RUNTIME_MATCH` | `true` |
| `DYNAMIC_HOOK_STABLE` (probe1 == probe2) | `true` |
| `CLOSED_WORLD_EDITABLE_BUILD_OK` | `true` |
| `CLOSED_WORLD_DISTRIBUTION_DELTA_OK` | `true` |
| `PREBUILD_ENVIRONMENT_OK` | `true` |
| `CONTROL_DYNAMIC_REQUIREMENT_INSTALLED` (sentinel control) | `true` |
| `CLOSED_WORLD_SENTINEL_AUTO_INSTALL` | `false` |
| `CLOSED_WORLD_DYNAMIC_REQUIREMENT_REJECTED` | `true` |
| `MEASURE_CRASH` | `false` |

### pyarrow24

Same verdicts, all green, plus `pyarrow24_version = "24.0.0"` and
`pyarrow24_match = true` (import of the pinned runtime, verified by report +
live `importlib.metadata` + `pyarrow.__version__`).

## 6. The closed-world build identity (A == B)

The path-free, environment-independent **build identity itself did remain
equal across Heads A and B** (measured on different machines at different
times):

| Identity | test-3.14 | pyarrow24 |
|---|---|---|
| `NORMALIZED_BUILD_IDENTITY_SHA256` | `0de39368f830591d3f812cff9d937c221dbe255f42a0efab9fe2d203f303c717` | `db235f200e9d18de931dd24e88f8aba94073207c1d488cc861eeb51b603e68f5` |
| `EXECUTION_BUILD_REQUIREMENTS_SHA256` (concrete requirements file) | `e36965fa33a61191bee8a357b0aaf0f0fc9a018c50160ca554cacd59e527a58b` | same |

Effective build set (re-parsed live from the resolver — not hardcoded):
`packaging==26.3`, `setuptools==84.0.0`, `wheel==0.48.0` (all wheels, exact
SHA256, materialized locally; sdists/VCS/direct-URL rejected). Backend
`setuptools.build_meta`; pip frontend `26.2.1`.

## 7. Cross-head full identity comparison — corrected fact

The retained verifier (`verifier_source.py` inside each evidence bundle) —
the authoritative comparator — `compare_identity_docs()` compares
`runner`, `python`, `resolver`, `dependency_contract`, `action_contract`,
`resolved_distributions`, the full `build_contract`, and the outcome booleans.
Independent replay of the authoritative Head A / Head B identity documents
with that comparator gives:

```
test-3.14:   CLOSED_WORLD_IDENTITY_MATCH=false  reason=first_differing_field:runner
pyarrow24:   CLOSED_WORLD_IDENTITY_MATCH=false  reason=first_differing_field:runner
```

### Actual runtime observations (recorded in the identity documents)

| Surface | Head A | Head B |
|---|---|---|
| test-3.14 | `ImageVersion=20260810.271.1`, Python `3.14.7` | `ImageVersion=20260720.247.2`, Python `3.14.6` |
| pyarrow24 | Python `3.11.15`, ImageVersion `20260810.271.1` | Python `3.11.15`, ImageVersion `20260720.247.2` |

Head A and Head B executed on different GitHub-hosted runner images; the
runtime identity (runner image + interpreter) drifted between heads. The
closed-world build identity (`NORMALIZED_BUILD_IDENTITY_SHA256`) did not move
(§6) — only the environmental runtime identity did.

### Actual shadow decision

P2-5's temporary per-run shadow flag (replay + valid + runtime-match +
sentinel-absent, evaluated inside each head's own run) evaluated `true` per
head, but the complete P2 runtime-identity gate — the cross-head comparison
above — failed on runner drift. The **actual shadow decision for BOTH
surfaces** is therefore:

```
SHADOW_REUSE_CANDIDATE=false
reason=runtime_identity_unequal
=> RUN
```

This is valid fail-closed behavior: a reuse decision must not be made when
the measured runtime identity differs between heads. It does NOT invalidate
the P2-5 closed-world build execution sub-proof (OUTCOME A, §12).

## 8. The synthetic sentinel proof (dual-branch)

| Branch | Command | Result |
|---|---|---|
| Control | ordinary isolation, `-v`, sentinel wheel + backend available in candidate | pip called `get_requires_for_build_editable` and **auto-installed** `p2-closed-world-sentinel==0.0.1` into the isolated env; `build_editable` imported it (`sentinel_import found=true`) — machine-visible in the `-v` log |
| Closed world | `--no-build-isolation --no-deps`, `PIP_NO_INDEX=1`, sentinel still available | build **failed** at `import p2_closed_world_sentinel` (`ModuleNotFoundError`); no auto-install line; sentinel absent before and after; wheel still present in the candidate |

This is the direct negative proof: **pip COULD see the artifact but does not
auto-install it** when build-dependency management is disabled. The only way a
"fourth build dependency" could enter the build is if it were already in the
exact prebuild env — which is hash-locked to the fingerprint set.

## 9. Distribution delta and final runtime

- Immediate pre/post-build inventory delta: exactly `market-vault 0.7.0`
  added, nothing changed, nothing removed,
  `unexpected_distribution_count = 0` (standalone
  `PREBUILD_ENVIRONMENT.json` / `POSTBUILD_ENVIRONMENT.json`, captured
  immediately around the real editable build; see §11 for receipt timing).
- `packaging` appears as *pre-satisfied by the exact prebuild env* (it is a
  build-set member already present, so pip skips reinstalling it); the final
  env still holds it at the expected version — recorded explicitly in
  `runtime_verification_receipt.json` (`pre_satisfied_by_exact_build_env`).
- Final runtime = pre-install resolution (report records + live
  `importlib.metadata` for all 41/42 distributions) and, on pyarrow24,
  `pyarrow.__version__ == "24.0.0"`.

## 10. Evidence bundle and offline replay (narrowed scope)

Each surface's bundle (`EVIDENCE_MANIFEST.json` + all evidence + wheelhouse +
`verifier_source.py`) was produced and replayed:

- `EVIDENCE_MANIFEST_COMPLETE=true` for both surfaces.
- **Offline replay re-derived all implemented file-derived gates and
  validated the recorded runtime receipt plus retained report presence** —
  `EVIDENCE_BUNDLE_REPLAY_OK=true` for both surfaces on Head A and Head B,
  both in CI (visible in the job logs) and after re-downloading the artifacts
  locally. The replay runs the bundle's own `verifier_source.py` copy, whose
  SHA256 is bound in the receipt (`verifier_script_sha256`).
- Duplicate-path hardening: the generator emits each relative path exactly
  once and raises `EVIDENCE_MANIFEST_INVALID reason=duplicate_path:<path>`
  before writing; the offline verifier independently rejects duplicates.
- The V1 attestation fingerprint (payload minus `fingerprint_sha256`,
  canonicalized) recomputes to the stored value on both surfaces/heads
  (identity digest gate, part of the replay).

**Scope limitation (recorded as `RUNTIME REPLAY HARDENING REQUIRED`, not a
P2-5 closed-world blocker):** the offline verifier's `runtime_receipt` gate
checks `final_runtime_match == true` and the presence of
`runtime_resolver_report.json` + `runtime_actual_install_report.json`; it does
NOT independently recompute full report-vs-resolution equality from those
JSON files. A future hardening should re-derive that equality in replay.

## 11. Receipt inventory timing (recorded, non-blocking)

- The standalone `PREBUILD_ENVIRONMENT.json` / `POSTBUILD_ENVIRONMENT.json`
  correctly capture the immediate pre/post MarketVault-build state and prove
  `delta == {market-vault: 0.7.0}`; the offline verifier recomputes the delta
  from these correct, manifest-bound files.
- `closed_world_build_receipt.json`'s `postbuild_distribution_inventory` is
  populated **after `leg_runtime_install()`**, so it contains the later
  runtime-dependency environment rather than the immediate post-build
  environment.

Classified as **`RECEIPT FIELD TIMING / SCHEMA HARDENING REQUIRED`**. This
does NOT invalidate the closed-world delta proof (the standalone files are
correct and manifest-bound). Future implementation must bind the receipt to
the immediate `POSTBUILD_ENVIRONMENT` inventory.

## 12. Newly discovered remaining P2 gap — runtime source-build output identity

Independent artifact review found, in **all four authoritative bundles**
(Head A/B × test-3.14/pyarrow24):

- `runtime_resolver_report.json` **and** `runtime_actual_install_report.json`
  record `moomoo-api 10.9.6908` with download source:
  `moomoo_api-10.9.6908.tar.gz`, source SHA256
  `6df0370ed120ec6e9f0bf65576a07838a7d105bb91e3ebb929f496a096700304`;
- but `runtime_install.log` records `Using cached
  moomoo_api-10.9.6908-py3-none-any.whl`.

Therefore the runtime fingerprint binds the **source sdist artifact**, but
does **NOT** bind the exact cached/built **wheel bytes** that were actually
installed into the tested environment. `runtime_verification_receipt.json`
verifies package name/version and report provenance; it does not hash the
installed moomoo-api wheel/code payload.

**Possible false positive:** same sdist SHA, same package version, same
resolver identity — but different cached/rebuilt wheel bytes => the recorded
runtime identity may still match.

**Recorded as `NEW REMAINING P2 GAP = RUNTIME SOURCE-BUILD OUTPUT IDENTITY`.**

**Fail-closed production rule:** any runtime dependency resolved from a
non-wheel source artifact whose exact resulting install artifact/code identity
is not proven => **RUN**.

## 13. Outcome determination (narrowed meaning)

**OUTCOME A / PASS — closed-world build execution.** OUTCOME A means exactly:

> An externally provisioned exact build environment executing with pip
> build-dependency management disabled is a viable closed-world MarketVault
> editable-build architecture.

OUTCOME A does **NOT** mean:

- the complete Partial Reuse V2 proof stack is closed; and
- the measured Head A/B pair was reusable — **it was not**, because runtime
  identity drifted between heads (runner image + interpreter, §7), and the
  runtime sdist output-identity gap (§12) remains open.

What is proven: the real editable build executes in a closed world (exact
prebuild env, pip build-dependency management disabled, `PIP_NO_INDEX`,
hash-locked requirements) with the sentinel control/negative proof intact, a
stable path-free build identity, the immediate project-only distribution
delta, and a replayable evidence bundle.

**COMPLETE P2 PROOF STACK = NOT CLOSED.** Remaining primary gap: **runtime
source-build output identity** (sdist → built/cached wheel bytes).

**Partial Reuse V2 remains NOT READY for production activation or
shadow-production integration.**

## 14. Honored constraints (no drift)

- No Partial Reuse V2 activation; no production skips; no package reuse
  authorized; no test-3.11 reuse authorized; V1 attestation schema unchanged;
  no release behavior change; audited candidate surface still `test-3.14` +
  `pyarrow24`.
- No amend / rebase / force-push / tag-release mutation anywhere in PR #80.
- Final PR diff: **this document only** (`docs/closed_world_build_execution_canary.md`).
- All hashes/artifacts cited here are CI-only / non-formal-release.

## 15. Final local gates (docs-only head)

- `git diff --check`: clean.
- `check_repo_hygiene.py`: pass.
- `check_release.py`: `RELEASE_CHECK_OK version=0.7.0`, exit 0.
- `ci_risk_tier.py`: `tier=docs_fast reason=all_changes_in_docs_scope
  full_matrix_required=false`, `changed_files=1`.
- Exact-head docs-only CI: silent, 4/4 jobs success, **0 artifacts**.

## 16. Evidence identities (authoritative artifacts)

| Item | Head A (`1b59ff941781c3431c4d0e20728799224bc00c45`) | Head B (`19ac23c696f38301f76778771a0670d19114eb53`) |
|---|---|---|
| Run | `31563580625` | `31563995966` |
| V1 full-CI attestation artifact | `9128710588` | `9128867621` |
| test-3.14 closed-world evidence artifact | `9128658200` | `9128813620` |
| pyarrow24 closed-world evidence artifact | `9128657275` | `9128799868` |

Each closed-world artifact contains the full receipt, identity, probe records,
reports, logs, distribution deltas, synthetic receipts, wheelhouse, manifest,
and the verifier self-copy — everything an independent reviewer needs to
replay the conclusions offline (as this correction's review did).

## 17. Next measurement — P2-6 RUNTIME SDIST BUILD-OUTPUT IDENTITY CANARY

**Not implemented in #80; no production architecture chosen here.**

Research question: *can every source-built runtime dependency be converted
into a deterministic, exact, hash-bound install artifact before a reuse
decision?* For the current surfaces the concrete case is
`moomoo-api 10.9.6908` (resolved from sdist; installed as a cached wheel).

Candidate approaches (NOT implemented in #80):

- **A.** reject all runtime sdists for reuse — non-wheel runtime artifact
  => RUN;
- **B.** materialize/build the sdist under a measured closed-world build
  environment, hash the resulting wheel, and install exactly that wheel;
- **C.** additionally bind installed distribution file/RECORD hashes.

## 18. Final architecture conclusion

- **P2-5 CLOSED-WORLD BUILD EXECUTION = OUTCOME A / PASS.**
- **COMPLETE P2 PROOF STACK = NOT CLOSED** — remaining primary gap: runtime
  source-build output identity (sdist → built/cached wheel bytes).
- **Partial Reuse V2 remains NOT READY** for production activation or
  shadow-production integration.
- **Next: P2-6 runtime sdist build-output identity measurement.**
- No V2 activated; no production skip added.

---

**STOP BEFORE MERGE** — pending independent review of this canary and its
corrections.
