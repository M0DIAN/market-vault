# P2-5 Closed-World Build Execution Canary (PR #80)

**Status: MEASURED / OUTCOME A — READY FOR INDEPENDENT REVIEW — STOP BEFORE MERGE**

This is the permanent record of PR #80's measurement. All measurement code
was temporary (removed in commit `8d27d30`); the permanent diff of this PR is
this document only.

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
   `verifier_script_sha256`, and an offline replay that re-derives every gate
   from the bundle alone.

All legs fail closed: any crash, mismatch, or unexpected install flips
`CLOSED_WORLD_BUILD_VALID` to false.

## 3. Heads

| Head | Commit | Parent | Diff |
|---|---|---|---|
| Head A | `1b59ff9` (after fix batch; initial `623f244`) | `98eb52e5` (#79, frozen base) | instrumented ci.yml + script + tests + marker `_A` |
| Head B | `19ac23c` | `1b59ff9` | exactly one comment line: marker `_A` → `_B` |
| Cleanup | `8d27d30` | `19ac23c` | ci.yml + `tests/test_audit_v03.py` restored byte-for-byte to base; script + tests removed |
| Final (docs-only) | HEAD of PR | `8d27d30` | this document only |

Frozen base `98eb52e582ffb975720b7d389fe3ea3a852d7848` was re-verified equal to
`origin/main` before every push (no BASE_DRIFT).

## 4. CI runs

| Run | Head | Result |
|---|---|---|
| `31562238961` | `623f244` | failure — measure crash (script bugs, fixed in `1b59ff9`); no evidence conclusions drawn from it |
| `31563580625` | `1b59ff9` (Head A) | **success — 4/4 jobs** (test 3.11, test 3.14, package, portability-pyarrow24) |
| `31563995966` | `19ac23c` (Head B) | **success — 4/4 jobs** |

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

## 6. The closed-world identity

Path-free, environment-independent build identity, identical across Heads A
and B (measured on different machines, at different times):

| Identity | test-3.14 | pyarrow24 |
|---|---|---|
| `NORMALIZED_BUILD_IDENTITY_SHA256` | `0de39368f830591d3f812cff9d937c221dbe255f42a0efab9fe2d203f303c717` | `db235f200e9d18de931dd24e88f8aba94073207c1d488cc861eeb51b603e68f5` |
| `EXECUTION_BUILD_REQUIREMENTS_SHA256` (concrete requirements file) | `e36965fa33a61191bee8a357b0aaf0f0fc9a018c50160ca554cacd59e527a58b` | same |

Effective build set (re-parsed live from the resolver — not hardcoded):
`packaging==26.3`, `setuptools==84.0.0`, `wheel==0.48.0` (all wheels, exact
SHA256, materialized locally; sdists/VCS/direct-URL rejected). Backend
`setuptools.build_meta`; pip frontend `26.2.1`.

Cross-head comparison (`compare --a <HeadA identity> --b <HeadB identity>`):
**`CLOSED_WORLD_IDENTITY_MATCH=true`** for both surfaces. (The comparison
covers dependency/action contracts, the full build contract, and the outcome
booleans; runner/python/resolver environment fields are context, not identity,
and are excluded.)

## 7. The synthetic sentinel proof (dual-branch)

| Branch | Command | Result |
|---|---|---|
| Control | ordinary isolation, `-v`, sentinel wheel + backend available in candidate | pip called `get_requires_for_build_editable` and **auto-installed** `p2-closed-world-sentinel==0.0.1` into the isolated env; `build_editable` imported it (`sentinel_import found=true`) — machine-visible in the `-v` log |
| Closed world | `--no-build-isolation --no-deps`, `PIP_NO_INDEX=1`, sentinel still available | build **failed** at `import p2_closed_world_sentinel` (`ModuleNotFoundError`); no auto-install line; sentinel absent before and after; wheel still present in the candidate |

This is the direct negative proof: **pip COULD see the artifact but does not
auto-install it** when build-dependency management is disabled. The only way a
"fourth build dependency" could enter the build is if it were already in the
exact prebuild env — which is hash-locked to the fingerprint set.

## 8. Distribution delta and final runtime

- Pre/post inventory delta: exactly `market-vault 0.7.0` added, nothing
  changed, nothing removed, `unexpected_distribution_count = 0`.
- `packaging` appears as *pre-satisfied by the exact prebuild env* (it is a
  build-set member already present, so pip skips reinstalling it); the final
  env still holds it at the expected version — recorded explicitly in
  `runtime_verification_receipt.json` (`pre_satisfied_by_exact_build_env`).
- Final runtime = pre-install resolution (report records + live
  `importlib.metadata` for all 41/42 distributions) and, on pyarrow24,
  `pyarrow.__version__ == "24.0.0"`.

## 9. Evidence bundle and offline replay

Each surface's bundle (`EVIDENCE_MANIFEST.json` + all evidence + wheelhouse +
`verifier_source.py`) was produced and replayed:

- `EVIDENCE_MANIFEST_COMPLETE=true` for both surfaces.
- Offline replay re-derived every gate from the bundle alone:
  **`EVIDENCE_BUNDLE_REPLAY_OK=true`** for both surfaces on Head A and Head B,
  both in CI (visible in the job logs) and after re-downloading the artifacts
  locally. The replay runs the bundle's own `verifier_source.py` copy, whose
  SHA256 is bound in the receipt (`verifier_script_sha256`).
- Duplicate-path hardening: the generator emits each relative path exactly
  once and raises `EVIDENCE_MANIFEST_INVALID reason=duplicate_path:<path>`
  before writing; the offline verifier independently rejects duplicates.
- The V1 attestation fingerprint (payload minus `fingerprint_sha256`,
  canonicalized) recomputes to the stored value on both surfaces/heads
  (identity digest gate, part of the replay).

## 10. Outcome determination

**OUTCOME A.** The real, editable MarketVault build executes successfully in a
closed world: exact prebuild environment + pip build-dependency management
disabled + `PIP_NO_INDEX` + hash-locked requirements, producing exactly the
fingerprint set with no auto-install channel; the sentinel control branch
proves the old auto-install channel is real and the closed-world branch proves
it is closed; the build identity is path-free and stable across two heads on
different machines; the final runtime matches the pre-install resolution; the
evidence bundle replays offline. Together with #79's resolution proof, the
build-isolation proof gap is closed: **no build dependency outside the
fingerprint set can enter the real build**.

## 11. Honored constraints (no drift)

- No Partial Reuse V2 activation; no production skips; no package reuse
  authorized; no test-3.11 reuse authorized; V1 attestation schema unchanged;
  no release behavior change; audited candidate surface still `test-3.14` +
  `pyarrow24`.
- No amend / rebase / force-push / tag-release mutation anywhere in PR #80.
- Final PR diff: **this document only** (`docs/closed_world_build_execution_canary.md`).

## 12. Final local gates (docs-only head)

- `git diff --check`: clean.
- `check_repo_hygiene.py`: pass.
- `check_release.py`: `RELEASE_CHECK_OK version=0.7.0 tier=docs_fast
  reason=all_changes_in_docs_scope full_matrix_required=false`.
- Final docs-only CI: silent, 4/4 jobs success, **0 evidence artifacts**.

## 13. Evidence artifacts (retained for review)

- Run `31563580625` (Head A): `market-vault-closed-world-test-3.14-1b59ff9…-attempt-1`,
  `market-vault-closed-world-pyarrow24-1b59ff9…-attempt-1`
- Run `31563995966` (Head B): `market-vault-closed-world-test-3.14-19ac23c…-attempt-1`,
  `market-vault-closed-world-pyarrow24-19ac23c…-attempt-1`

Each contains the full receipt, identity, probe records, reports, logs,
distribution deltas, synthetic receipts, wheelhouse, manifest, and the
verifier self-copy — everything an independent reviewer needs to replay the
conclusions offline.

---

**STOP BEFORE MERGE** — pending independent review of this canary.
