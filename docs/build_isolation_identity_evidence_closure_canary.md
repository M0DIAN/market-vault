# P2-4 Build-Isolation Identity + Evidence-Closure Canary

**Status:** MEASURED — OBSERVED DECISION **OUTCOME A** — BUILD-ISOLATION
IDENTITY AND EVIDENCE CLOSURE BOTH PROVEN, PENDING INDEPENDENT REVIEW.
The two P2-3 proof gaps (docs/runtime_identity_fingerprint_canary.md,
OUTCOME B) are closed by measurement: the exact PEP 517 / PEP 660 isolated
build environment was resolved and fingerprinted (setuptools / wheel /
packaging artifacts with SHA256), bound to the real editable install via pip
`--build-constraint` with local direct-reference wheels, and the raw
evidence replayable offline from the uploaded artifacts alone
(`verifier_source.py verify-bundle` → `EVIDENCE_BUNDLE_REPLAY_OK` on all
four surface/run combinations). Cross-head production reuse remains **NOT
ACTIVATED**; **STOP BEFORE MERGE** pending independent review.
**PR:** #79
**Type:** measurement / shadow evidence only. No production behavior changed.

> **Decision discipline:** the observed empirical verdict is OUTCOME A, but
> the final formal decision is exactly one of OUTCOME A / OUTCOME B /
> OUTCOME C, taken by independent review after this measurement. This
> document does not claim self-embedding; the authoritative values are
> GitHub PR metadata and the exact-head CI runs referenced below.

> Every hash in this report is a **CI-ONLY / NON-FORMAL-RELEASE HASH** —
> it describes a temporary measurement artifact from an exact-head CI run,
> not any released artifact.

## 1. Scope and method

P2-3 (#78, corrected OUTCOME B) closed the runtime identity question but
left two proof gaps: (1) **build-isolation identity** — the fingerprint did
not contain resolved artifact identity for the PEP 517 isolated build
environment (setuptools / wheel), so two heads could theoretically share an
identical runtime fingerprint while resolving different build backends; and
(2) **evidence closure** — the actual heavy install reports were consumed
during CI but not retained in the uploaded measurement artifacts, so an
independent reviewer could not replay verification offline.

This PR measures both:

- A stdlib-only probe (`scripts/ci_runtime_identity_v2.py`, temporary,
  SCHEMA_VERSION=2) extends the P2-3 runtime fingerprint with a
  **build_isolation block**: the sealed `[build-system]` contract
  (backend, declared requires), the live PEP 517
  `get_requires_for_build_editable` hook result, the complete **effective
  build dependency set** with materialized exact wheels (canonical name,
  version, filename, SHA256), and a **build-only local direct-reference
  constraint** (`name @ file:///…whl#sha256=<hex>`) proven by a positive
  constrained editable install (market-vault 0.7.0, zero index fetches) and
  a negative wrong-hash rejection.
- The probe ran as a **shadow** step on the Python 3.14 matrix leg and the
  `portability-pyarrow24` job, AFTER checkout / setup-python / classifier and
  BEFORE the heavy dependency installation. A probe failure recorded
  `RUNTIME_FINGERPRINT_VALID=false` / `BUILD_CONSTRAINT_READY=false` and the
  normal FULL chain still ran — nothing was ever skipped, gated, or reused.
- When the probe proved the constraint acceptable
  (`BUILD_CONSTRAINT_READY=true`), the real heavy editable install ran
  **under that exact constraint** (`pip install --build-constraint
  fp-evidence/build_constraints.txt --report … -e ".[dev]"`), recording
  `BUILD_CONSTRAINT_USED=true`; otherwise it fell back to the normal
  install. Either way the machine-readable report and full raw log were
  retained.
- After the heavy install, `verify-installed` compared the pre-install
  fingerprint against the ACTUAL installed runtime (machine-readable pip
  reports + importlib cross-check + live PyArrow import on pyarrow24);
  `build-receipt` emitted the build-identity receipt bound to the
  constraint-used marker; `bundle` assembled a self-contained evidence
  bundle (EVIDENCE_MANIFEST.json, exact verifier-source copy, raw logs and
  reports, the build wheelhouse); the bundle was copied to a clean
  directory and **replayed offline** with `verifier_source.py verify-bundle`
  in the same job.
- Head A = probe + tests + workflow instrumentation + exact action pins +
  one semantic no-op comment `# P2_BUILD_ISOLATION_CANARY_A` in
  `tests/test_audit_v03.py`. Head B = exactly one comment flip to
  `# P2_BUILD_ISOLATION_CANARY_B`, a direct child of Head A. A→B blobs are
  byte-identical for `.github/workflows/ci.yml`,
  `scripts/ci_runtime_identity_v2.py`,
  `tests/test_ci_runtime_identity_v2.py`, `pyproject.toml`,
  `ci/python314_compatibility_surface.txt`,
  `scripts/ci_python314_surface.py`, and all of `src/**`.
- Both heads executed the CURRENT FULL four-job contract in full.
- **SHADOW EVIDENCE ONLY.** Partial Reuse V2 was NOT activated; no
  production validation was skipped; no per-surface production attestations
  were added; V1's attestation schema is unchanged; release behavior is
  unchanged. All temporary code was removed on this head; the final PR diff
  is exactly this document.

**Measurement correction (transparent record):** the first Head A run
(`ce77b72`, run `31545318378`, all four jobs success) uploaded evidence
bundles that were NOT replayable: `cmd_bundle` omitted the
`actual_constraint_used.txt` marker from the bundle (the workspace-file
list did not include it), so `verify-bundle` failed closed on the missing
required file and no `replay_summary.txt` was produced. The bug was fixed
(`SURFACE_WORKSPACE_FILES` now carries the marker; the marker read fails
closed with an explicit summary instead of a crash), the 66-test suite was
re-run green on 3.14 and 3.11, and a fresh end-to-end local smoke
(probe → verify-installed → build-receipt → bundle → offline replay)
confirmed `MARKER_IN_BUNDLE=yes`. The fixed Head A (`6217b82`, run
`31554002074`) is the authoritative Head A evidence below; the superseded
run is preserved in the artifact history.

## 2. Identities

| Item | Value |
|---|---|
| Frozen base | `3cdc162c6678bae3af74adede84f7496f9eee0f4` (origin/main at PR creation; no drift observed during measurement) |
| PR | #79 |
| Head A SHA | `6217b82894a80e1e810c6e38acbd699bd5b5823f` |
| Head A run ID | `31554002074` (conclusion: success) |
| Head A V1 FULL attestation | schema 1, `run_id=31554002074`, `pr_number=79`, `base_sha=3cdc162c…`, `head_sha=6217b82…`, tier `full`, `full_matrix_required=true` — artifact ID `9125413966` |
| Head B SHA | `3040dfe6365f8d171b1e3e23f05d7abe5f204e1b` |
| Head B run ID | `31556742065` (conclusion: success) |
| Head B V1 FULL attestation | schema 1, `run_id=31556742065`, `pr_number=79`, `base_sha=3cdc162c…`, `head_sha=3040dfe…`, tier `full`, `full_matrix_required=true` — artifact ID `9126340855` |
| Superseded first Head A | `ce77b723c49b2d72baa7b4fa3260d853606ff0d0`, run `31545318378` (all four jobs success; bundles not replayable — fixed on `6217b82`) |

## 3. Evidence artifacts

Temporary measurement artifacts (all CI-ONLY / NON-FORMAL-RELEASE):

| Surface | Head | Artifact name | Artifact ID |
|---|---|---|---|
| test-3.14 | A | `market-vault-runtime-v2-test-3.14-6217b82894a80e1e810c6e38acbd699bd5b5823f-attempt-1` | `9125333469` |
| pyarrow24 | A | `market-vault-runtime-v2-pyarrow24-6217b82894a80e1e810c6e38acbd699bd5b5823f-attempt-1` | `9125336449` |
| test-3.14 | B | `market-vault-runtime-v2-test-3.14-3040dfe6365f8d171b1e3e23f05d7abe5f204e1b-attempt-1` | `9126285565` |
| pyarrow24 | B | `market-vault-runtime-v2-pyarrow24-3040dfe6365f8d171b1e3e23f05d7abe5f204e1b-attempt-1` | `9126288503` |

Each bundle is self-contained and contains: `EVIDENCE_MANIFEST.json`
(path / size / sha256 per file, itself excluded), `runtime_identity_v2.json`
(the V2 fingerprint), `runtime_verification_receipt.json`,
`runtime_resolver_report.json`, `build_static_resolver_report.json`,
`build_dynamic_requirements.json`, `build_effective_resolver_report.json`,
`build_constraints.txt`, `build_constraint_positive.log`,
`wrong_hash_constraint.txt`, `build_constraint_negative.log`,
`build_identity_receipt.json`, `actual_constraint_used.txt`,
`verifier_source.py` (the exact executed script copy), `probe_summary.txt`,
`probe_pip_dryrun.log`, the surface's actual install reports/logs
(`actual_install_report_314.json` + `actual_install_314.log` for test-3.14;
`actual_dev_install_report.json` + `actual_dev_install.log` +
`actual_pyarrow_pin_report.json` + `actual_pyarrow_pin.log` for pyarrow24),
and `build-wheelhouse/` with the three materialized build wheels.

**Evidence closure achieved:** the raw actual-install reports are retained
inside the uploaded bundles (closing the P2-3 section-14 gap), and every
bundle replays offline: `EVIDENCE_BUNDLE_REPLAY_OK`, all 16
`REPLAY_CHECK_*` gates green, on all four surface/run combinations
(section 13).

## 4. Fingerprint schema and canonicalization contract

- `schema_version: 2` (V1 blocks + `build_isolation`). Any other version →
  INVALID (`schema_version_unsupported`).
- Canonical payload: JSON with `sort_keys=True`, compact separators,
  newline-terminated; `fingerprint_sha256` is computed over the payload
  WITHOUT itself; `resolved_distributions` and
  `effective_build_distributions` are sorted by canonical name in the
  canonical payload (raw-input ordering never changes the digest; the
  canonicalizer deep-copies before sorting so validation of unsorted input
  is never masked).
- Package names are PEP 503 canonicalized (`Moomoo_API` → `moomoo-api`).
- Download URLs are normalized; credential-bearing URLs are rejected
  (`url_credentials`); non-http(s) schemes are rejected.
- The local project itself is excluded from the resolved distribution set
  (its identity is covered by the dependency contract:
  name / version / SHA256(pyproject.toml)).
- Missing required runner image field, missing distribution version,
  duplicate canonical package, malformed artifact hash, non-wheel build
  artifact, malformed constraint line, and probe-invalid documents all fail
  closed — never "unknown".

**Scope of the V2 fingerprint:** the final installed external runtime
distribution set (as before) **plus** the exact PEP 517 isolated
build-environment dependency identity — declared `[build-system]`
requirements, the live `get_requires_for_build_editable` hook result, the
complete effective build dependency set with exact wheel artifacts, and the
constraint digest that was bound to the real install.

## 5. Identity contract recorded per surface

| Block | Fields |
|---|---|
| Runner | `run_os` (RUNNER_OS), `run_arch` (RUNNER_ARCH), `image_os` (ImageOS), `image_version` (ImageVersion) — any missing → INVALID; plus `sys_platform`, `machine`, `release`, `libc_ver`, `sysconfig_platform` |
| Python | implementation, exact `version` (x.y.z), major/minor/micro, `cache_tag`, `soabi`, `pointer_width` |
| Resolver | pip name + exact version |
| Dependency contract | project name, version, `pyproject_sha256`, sorted dependencies / dev-dependencies (tomllib, no install needed) |
| Action contract | exact-SHA checkout / setup-python / upload-artifact pins + `ci_yml_sha256` |
| Resolved distributions | canonical name, version, normalized URL, artifact SHA256 for every external package in the final installed runtime set |
| Build isolation | backend, `backend_path`, `declared_requires`, `dynamic_hook` (`get_requires_for_build_editable`), `dynamic_requires`, `effective_build_distributions` (name / version / filename / sha256), `build_constraint_sha256`, `constraint_mode`, `all_artifacts_are_wheels` |

## 6. Action identity strategy

The temporary workflow pinned the executed actions to exact 40-hex SHAs,
derived independently from real CI logs at the frozen base (not trusted
from any mutable label) — identical pins to P2-3. Auditability comments
preserved the pre-existing `@v6` / `@v7` substring contracts so every
pre-existing check kept passing while the EXECUTED action was the pinned
commit.

| Action | Exact pin |
|---|---|
| actions/checkout | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| actions/setup-python | `ece7cb06caefa5fff74198d8649806c4678c61a1` |
| actions/upload-artifact | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |

Workflow digest `ci_yml_sha256` recorded in both heads' fingerprints:
`de965e98dc439114ffa25a01fda037223e4a0c8eb0aed7f7c302c7e09e3c1233`
(CI-ONLY / NON-FORMAL-RELEASE HASH) — identical across heads, as required
(ci.yml blobs are byte-identical A→B).

## 7. Fingerprint results

All FPs are CI-ONLY / NON-FORMAL-RELEASE HASHES.

| Surface | Head A FP | Head B FP | Cross-head |
|---|---|---|---|
| test-3.14 | `dc6a9c8ca41db60750bb95d0e50e593152b0faff03e28726229a0d284902c822` | `dc6a9c8ca41db60750bb95d0e50e593152b0faff03e28726229a0d284902c822` | `RUNTIME_V2_FINGERPRINT_MATCH=true` `reason=ok` |
| pyarrow24 | `f101cf44ae52776ef4659e8a5e3c07f0136c082b3975714911cd2d6c2b2f6237` | `f101cf44ae52776ef4659e8a5e3c07f0136c082b3975714911cd2d6c2b2f6237` | `RUNTIME_V2_FINGERPRINT_MATCH=true` `reason=ok` |

Cross-surface comparison at the same head correctly reports
`RUNTIME_V2_FINGERPRINT_MATCH=false` `reason=surface_unequal` (test-3.14 and
pyarrow24 are different runtime surfaces with different requirement sets;
the build-isolation block is byte-identical across surfaces — section 12).

Head A and Head B fingerprints are byte-identical on both surfaces. This is
the natural equality case: the runtime AND build-isolation identity actually
did not change between heads (same image, same exact Pythons, same pip,
same resolved dependency sets, same effective build set — all verified
independently of the fingerprints below), and the canary comment flip lives
in `tests/test_audit_v03.py`, which is outside both measured surfaces' input
boundaries (section 9).

## 8. Probe-vs-actual verification (all four surface/run combinations)

`verify-installed` compared the resolved distribution sets of the retained
actual install reports against the pre-install fingerprint (file-match-only;
the live importlib cross-check and live PyArrow import are recorded in the
receipt as live-environment evidence but are NOT offline-replayable by
design, section 13). For pyarrow24 both retained reports are used — the
base install report and the later `pyarrow==24.0.0` pin report (later
reports override earlier ones per surface semantics).

| Run | Surface | `probe_valid` | `actual_install_verified` | `actual_install_match` | `reason` |
|---|---|---|---|---|---|
| Head A | test-3.14 | true | true | **true** | null |
| Head A | pyarrow24 | true | true | **true** | null |
| Head B | test-3.14 | true | true | **true** | null |
| Head B | pyarrow24 | true | true | **true** | null |

The pre-install probe predicted the actual heavy runtime on all four
surface/run combinations. Additionally, the heavy install on both surfaces
and both heads ran **under the measured build constraint**
(`BUILD_CONSTRAINT_READY=true` in every probe summary →
`actual_constraint_used.txt` = `BUILD_CONSTRAINT_USED=true` in every
bundle), and the build-identity receipt consistency check
(`build_receipt_consistency=ok` in every offline replay) binds the receipt's
`actual_heavy_install_used_build_constraint` field to that marker.

## 9. A→B delta irrelevance (source-input proof)

- Head B is a direct child of Head A (`3040dfe` parent = `6217b82`); the
  A→B diff is exactly one comment line in one file
  (`# P2_BUILD_ISOLATION_CANARY_A` → `# P2_BUILD_ISOLATION_CANARY_B`),
  verified byte-for-byte with `git diff` before the commit.
- Required identical A→B blobs verified: `.github/workflows/ci.yml`,
  `scripts/ci_runtime_identity_v2.py`,
  `tests/test_ci_runtime_identity_v2.py`, `pyproject.toml`,
  `ci/python314_compatibility_surface.txt`, `scripts/ci_python314_surface.py`,
  and `src/**` — all byte-identical.
- `tests/test_audit_v03.py` has NO nodes in the sealed 258-node
  `ci/python314_compatibility_surface.txt` manifest, and is none of the 10
  test files on the complete audited PyArrow 24 A/B/C path (accounted in
  docs/runtime_identity_fingerprint_canary.md section 9).
- The delta is therefore irrelevant to both reuse candidates under the #77
  selected-input boundary contract.

## 10. Actual hosted runner identity (Head A and Head B)

| Field | test-3.14 | pyarrow24 |
|---|---|---|
| ImageOS | `ubuntu24` | `ubuntu24` |
| ImageVersion | `20260720.247.2` | `20260720.247.2` |
| RUNNER_OS / RUNNER_ARCH | Linux / X64 | Linux / X64 |
| Exact Python | CPython 3.14.6 (`cpython-314-x86_64-linux-gnu`) | CPython 3.11.15 (`cpython-311-x86_64-linux-gnu`) |
| pip | 26.2.1 | 26.2.1 |
| libc / kernel | glibc 2.39 / 6.17.0-1020-azure | glibc 2.39 / 6.17.0-1020-azure |

Identical across heads. **Historical corroboration (not primary proof):**
the sealed P2-2 measurement and both P2-3 heads (#78) recorded the same
runner image `20260720.247.2` with CPython 3.14.6 and pip 26.2.1 — the
hosted image has been stable across #77-era, #78, and #79 measurements.

## 11. Performance observations (descriptive, not a gate)

| Step | Wall time |
|---|---|
| Probe (test-3.14, Head A) | 29.4 s |
| Probe (pyarrow24, Head A) | 30.8 s |
| Probe (test-3.14, Head B) | 25.2 s |
| Probe (pyarrow24, Head B) | 28.9 s |
| Heavy editable install under constraint (test-3.14) | normal install cost; constrained path adds no install-time overhead (constraint is a build-time bind) |
| Offline bundle replay (per surface) | ~0.02 s |

The V2 probe is heavier than P2-3's (~10–12 s) because it additionally
downloads the exact build wheels, executes the live
`get_requires_for_build_editable` hook in a throwaway venv, resolves the
effective build set, and runs the positive + negative constraint
enforcement installs (each ~7 s). Per-stage times are recorded in every
`probe_summary.txt`. The probe still runs in a clean venv with no dependency
on the heavy environment, and it is measured on both surfaces for both
heads.

## 12. Build-isolation identity (the P2-3 gap, now measured)

Sealed build contract (unchanged, from `pyproject.toml`):

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

Measured per surface/run (identical in all four bundles):

| Item | Value |
|---|---|
| backend | `setuptools.build_meta` (`backend_path` null) |
| declared requires | `["setuptools>=68", "wheel"]` |
| dynamic hook | `get_requires_for_build_editable` → `[]` (no dynamic additions) |
| effective build set | packaging 26.3 (`packaging-26.3-py3-none-any.whl`, sha256 `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`) · setuptools 84.0.0 (`setuptools-84.0.0-py3-none-any.whl`, sha256 `51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670`) · wheel 0.48.0 (`wheel-0.48.0-py3-none-any.whl`, sha256 `3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab`) |
| constraint mode | `local_direct_reference_sha256` |
| build constraint SHA256 | `d23280aed9e929c9ba00430cec30cac4b96b708eef7bde99f57273babb359080` |
| all artifacts wheels | true |

The effective set is identical across surfaces and heads: packaging 26.3
arrives as wheel's declared dependency, setuptools 84.0.0 and wheel 0.48.0
as the two declared build requirements. **Every distribution in the
effective set is a wheel, and every wheel is present in
`build-wheelhouse/` with a hash-verified download** (`wheelhouse_hashes=ok`
in every replay).

**Constraint enforcement (the binding proof):**

- `build_constraints.txt` contains three PEP 508 direct references —
  `packaging @ file:///…/packaging-26.3-py3-none-any.whl#sha256=…` etc.
  (absolute paths, SHA256 per wheel).
- **Positive stage** (`P24_CONSTRAINED_INSTALL_BEGIN` segment):
  `pip install --no-deps --build-constraint build_constraints.txt -e .` in
  a clean venv — build dependencies installed from the local wheelhouse,
  zero index fetches inside the segmented install (the only `Collecting`
  lines are pip's own cached self-upgrade, which precedes the separator),
  editable wheel `market_vault-0.7.0-….editable-py3-none-any.whl` built and
  installed; importlib.metadata check prints `0.7.0`;
  `P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=true reason=version=0.7.0`.
- **Negative stage**: the same constraint with one deliberate wrong hash
  (`wrong_hash_constraint.txt`) → pip refuses the build dependency;
  `P24_NEGATIVE_WRONG_HASH_REJECTED=true reason=ok` — the hash binding is
  real (a wrong SHA256 makes the constrained install fail closed).
- Marker lines present in all four bundles with the same values.

**The real heavy install was bound by the same constraint:** on both
surfaces and both heads, `BUILD_CONSTRAINT_READY=true` in the probe summary
drove `--build-constraint fp-evidence/build_constraints.txt` on the actual
`pip install -e ".[dev]"`; `BUILD_CONSTRAINT_USED=true` was recorded, and
the offline replay's `build_receipt_consistency` check ties the receipt to
the marker. The build-isolation identity is therefore not merely measured —
it was enforced on the actual editable installs this PR's CI ran.

## 13. Evidence closure (the P2-3 gap, now closed)

P2-3 section 14 required a future canary to archive the normalized actual
install reports and prove offline replay. Measured here:

- Every bundle is self-contained: `EVIDENCE_MANIFEST.json` lists every
  file with size + SHA256 (itself excluded), including the surface's raw
  actual install reports/logs and `verifier_source.py` — the exact executed
  script copy (manifest `verifier_source` check confirms the running
  script's size and SHA256 match the manifest entry).
- **Offline replay, all four surface/run combinations:**
  `EVIDENCE_BUNDLE_REPLAY_OK` with all 16 `REPLAY_CHECK_*` gates green
  (manifest present/schema/complete/hashes/binding; fingerprint
  valid/digest; resolver normalization; build reports identity; wheelhouse
  hashes; constraint identity; wrong-hash negative; positive constraint;
  runtime receipt; build receipt consistency; verifier source). Replayed
  from a clean copy of each downloaded artifact, using only the bundle's
  own `verifier_source.py`.
- The 16 gates include the fail-closed negative path: a missing required
  file now produces an explicit `EVIDENCE_BUNDLE_REPLAY_FAIL reason=…`
  summary (verified in the superseded first Head A run and in local smoke),
  never a bare crash with no summary.
- **Documented live-only evidence (not offline-replayable by design):**
  the importlib cross-check of every recorded distribution and the live
  `pyarrow.__version__` check are recorded in the runtime verification
  receipt, which is valid evidence observed in the exact CI jobs; the
  offline gates deliberately re-verify only file-derived facts.
- The superseded first Head A bundles (run `31545318378`) are the negative
  evidence sample: `manifest_complete` / `verifier_source` failed closed
  exactly as designed, which is what exposed the marker-retention bug.

## 14. Comparator branches

- **Positive branch (naturally observed):** identical canonical fingerprints
  → `RUNTIME_V2_FINGERPRINT_MATCH=true`, `reason=ok` — observed for real in
  the cross-head comparisons of both surfaces (section 7), plus all four
  probe-vs-actual verifications (section 8). No fake runtime data was
  manufactured.
- **Negative branches (naturally observed):**
  - cross-surface same-head comparison → `surface_unequal` (test-3.14 vs
    pyarrow24 fingerprints differ; build-isolation blocks identical);
  - the superseded first Head A bundles → `EVIDENCE_BUNDLE_REPLAY_FAIL`
    on the missing marker (section 13).
- **Negative branch (mutation tests):** `tests/test_ci_runtime_identity_v2.py`
  — 66 tests, all passing on CPython 3.14 and 3.11 — covering validation
  (backend missing/empty, declared/dynamic requires malformed or unsorted,
  build package missing/extra, wheel filename/sha256 malformed,
  constraint digest/mode mismatch, non-wheel artifact, credential URLs,
  unsupported schema, probe-invalid docs), comparison reasons
  (`build_backend_unequal`, `build_declared_requires_unequal`,
  `build_dynamic_requires_unequal`, `build_package_version_unequal:<name>`,
  `build_wheel_filename_unequal:<name>`, `build_wheel_sha256_unequal:<name>`,
  `build_package_missing:<name>`, `build_package_extra:<name>`,
  `build_constraint_digest_unequal`, `build_constraint_mode_unequal`,
  `build_artifacts_not_all_wheels_unequal`, plus the retained V1 reasons),
  canonicalization, URL normalization, and verify evaluation
  (probe-invalid fails closed; probe-vs-actual mismatch fails closed).

## 15. Shadow decision chain (per surface)

| Proof leg | test-3.14 | pyarrow24 |
|---|---|---|
| SOURCE PROOF: valid Head A V1 FULL attestation + 4-job success + Head A fingerprint matches actual install | PASS | PASS |
| TRANSITION: Head B direct child + exact A→B delta (one comment line) | PASS | PASS |
| SOURCE-INPUT PROOF: #77 boundary contract proves delta irrelevant | PASS | PASS |
| RUNTIME PROOF: Head B live fingerprint valid + Head B FP == Head A FP | PASS | PASS |
| BUILD-ISOLATION PROOF: effective build set resolved, wheel-hashed, constraint-bound, positively + negatively enforced, identical across heads | PASS | PASS |
| EVIDENCE-CLOSURE PROOF: all four bundles replay offline (`EVIDENCE_BUNDLE_REPLAY_OK`, 16/16) | PASS | PASS |

All observed legs pass, including the two legs P2-3 left unproven. The
shadow decision is OUTCOME A **pending independent review**; with the
fail-closed rule "unproven / unequal build-isolation identity => RUN" the
V2 schema now carries a proven build-isolation leg. No production action
consumes any of this in #79.

## 16. Decision (observed; STOP BEFORE MERGE)

**OUTCOME A — BUILD-ISOLATION IDENTITY AND EVIDENCE CLOSURE BOTH PROVEN**
(observed verdict; final decision exactly one of OUTCOME A / B / C, taken
by independent review before merge).

PROVEN by #79:

- the exact PEP 517 / PEP 660 isolated build environment is resolved and
  fingerprinted: declared `[build-system]` contract, live
  `get_requires_for_build_editable` hook result (`[]`), complete effective
  build dependency set {packaging 26.3, setuptools 84.0.0, wheel 0.48.0}
  with materialized exact wheels and SHA256, and a local direct-reference
  `--build-constraint` digest — identical across heads and surfaces;
- the constraint is real: positive constrained editable install of
  market-vault 0.7.0 with zero index fetches, negative wrong-hash
  rejection, marker lines `P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=true`
  and `P24_NEGATIVE_WRONG_HASH_REJECTED=true` in every bundle;
- the real heavy editable installs on both surfaces and both heads ran
  **under** the measured constraint (`BUILD_CONSTRAINT_READY=true` →
  `BUILD_CONSTRAINT_USED=true`, bound by `build_receipt_consistency`);
- all four surface/run combinations: probe predicted the actual runtime
  (file-match), and the evidence bundles replay offline
  (`EVIDENCE_BUNDLE_REPLAY_OK`, 16/16) from the archived artifacts alone;
- A/B cross-head V2 fingerprints matched naturally on both surfaces
  (equality on both), and cross-surface comparison correctly reports
  `surface_unequal`;
- the mutation comparator fails closed (66/66 tests on CPython 3.14 and
  3.11).

NOT PROVEN / NOT CLAIMED:

- the decision binds only the exact head pair and the sealed source-input
  boundary contract for the audited `test-3.14` and `pyarrow24` surfaces;
- no claim for the package surface, test-3.11 blanket FULL surface, or any
  unmeasured surface; no reuse authorization is granted by this document;
  Partial Reuse V2 remains NOT ACTIVATED.

## 17. Remaining limitations

- The fingerprint is a snapshot of the CI runner's hosted image and of PyPI
  state at probe time; GitHub can change `ImageVersion` between runs (no
  drift observed; any drift fails closed as `runner_image_version_unequal`
  ⇒ RUN).
- Live-environment evidence (importlib cross-check, live PyArrow import) is
  recorded in the receipts but is not offline-replayable; the offline gates
  re-verify only file-derived facts (documented in section 13).
- The probe (~25–31 s per surface) is measured, not budgeted; a production
  mechanism would need the same fail-closed semantics and its own budget.
- The measurement exercised one resolution epoch; identical fingerprints
  across a direct-parent pair prove identity at probe time, and the
  constraint binds the build environment at install time, but neither
  freezes PyPI future state.
- The canary measured two surfaces only; no claim is made for the package
  surface or the 3.11 blanket FULL surface.

## 18. Explicit statements

- **No production skip occurred.** Both heads executed the CURRENT FULL
  four-job validation contract end-to-end (test 3.11, test 3.14,
  portability-pyarrow24, package — all success on both heads).
- **No V2 activated.** Partial Reuse V2 was not activated and no reuse
  mechanism consumes any canary result.
- **No build-isolation mechanism remains active on the final head.** All
  temporary code (probe script, tests, workflow instrumentation, action
  pins, `--report` / `--build-constraint` instrumentation, canary marker)
  is removed; ci.yml and test_audit_v03.py are byte-for-byte the frozen
  base (0-byte diff vs `origin/main`), and the final PR diff is exactly
  this document.
- **No release/tag/main mutation occurred** during measurement.
- **One measurement correction is on record:** the first Head A run's
  bundles were not replayable (marker not retained); the bug was fixed and
  re-verified before Head B; the fixed run is the authoritative Head A
  evidence (sections 1, 13).
- **STOP BEFORE MERGE:** this document records the observed verdict
  (OUTCOME A) pending independent review; the final formal decision is
  exactly one of OUTCOME A / OUTCOME B / OUTCOME C.

**Final PR head:**
NOT SELF-EMBEDDED BY DESIGN.
Authoritative value = GitHub PR metadata + exact-head CI at review time.
