# P2-3 Runtime Identity Fingerprint Canary

**Status:** MEASURED — DECISION **OUTCOME B** — RUNTIME IDENTITY CONTRACT
STILL HAS A PROOF GAP. The lightweight live pre-install probe foundation
is viable and all four probe-vs-actual receipts matched, but PEP 517
isolated build-environment dependency identity is outside the proof
boundary, so the current fingerprint schema is not yet sufficient for
production reuse. Cross-head production reuse remains **NOT READY**.
Reuse was NOT activated. No runtime-fingerprint mechanism remains on this
head.
**PR:** #78
**Type:** measurement / shadow evidence only. No production behavior changed.

> **Evidence-decision correction note:** after the measurement completed,
> independent review accepted the experiment execution (live pre-install
> probe PASS, final installed distribution prediction PASS, cross-head
> comparator PASS) and corrected the formal decision from OUTCOME A to
> OUTCOME B: the fingerprint omits PEP 517 isolated build-environment
> dependency identity (setuptools / wheel resolution), which is a concrete
> proof boundary outside what #78 measured. Every empirical fact below is
> unchanged and was re-verified against the exact-head CI evidence. Head A
> and Head B were NOT rerun; no temporary instrumentation was recreated.

> Every hash in this report is a **CI-ONLY / NON-FORMAL-RELEASE HASH** —
> it describes a temporary measurement artifact from an exact-head CI run,
> not any released artifact.

## 1. Scope and method

Sealed PR #77 (P2-2) established source-input boundaries for two reuse
candidates (`test-3.14`, `pyarrow24`) and identified a **residual
RUNTIME / DEPENDENCY IDENTITY gap**: source-input equality across a
direct-parent A→B pair does not prove the runtime a skipped Head B would
have used, because the dependency contracts contain ranges resolved at
install time against live PyPI state.

This PR measures whether a lightweight, live, fail-closed **runtime
identity fingerprint** taken *before* the heavy install can close that gap.

- A stdlib-only probe (`scripts/ci_runtime_fingerprint.py`, temporary)
  resolves the runtime identity — runner, exact Python, pip, project
  dependency contract, exact action SHAs, workflow digest — and the final
  installed external runtime distribution set (canonical names, versions,
  normalized URLs, SHA256 artifact hashes) via a clean-venv
  `pip install --dry-run --report`.
- The probe ran as a **shadow** step on the Python 3.14 matrix leg and the
  `portability-pyarrow24` job, AFTER checkout / setup-python / classifier and
  BEFORE the heavy dependency installation. A probe failure recorded
  `RUNTIME_FINGERPRINT_VALID=false` and the normal FULL chain still ran —
  nothing was ever skipped, gated, or reused.
- After the heavy install, `verify-installed` compared the pre-install
  fingerprint against the ACTUAL installed runtime (machine-readable pip
  `--report` + importlib cross-check + live PyArrow import) and emitted a
  `verification_receipt.json`.
- Head A = probe + tests + workflow instrumentation + one semantic no-op
  comment `# P2_RUNTIME_IDENTITY_CANARY_A` in `tests/test_audit_v03.py`.
  Head B = exactly one comment flip to `# P2_RUNTIME_IDENTITY_CANARY_B`,
  a direct child of Head A. A→B blobs are byte-identical for
  `.github/workflows/ci.yml`, `scripts/ci_runtime_fingerprint.py`,
  `tests/test_ci_runtime_fingerprint.py`, `pyproject.toml`,
  `ci/python314_compatibility_surface.txt`,
  `scripts/ci_python314_surface.py`, and all of `src/**`.
- Both heads executed the CURRENT FULL four-job contract in full.
- **SHADOW EVIDENCE ONLY.** Partial Reuse V2 was NOT activated; no
  production validation was skipped; no per-surface production attestations
  were added; V1's attestation schema is unchanged; release behavior is
  unchanged. All temporary code was removed on this head; the final PR diff
  is exactly this document.

## 2. Identities

| Item | Value |
|---|---|
| Frozen base | `5ca28121d0e198a97ac6e26ffb1a3549f3b98107` (origin/main at PR creation; no drift observed during measurement) |
| PR | #78 |
| Head A SHA | `6a0f1b5c6c2025db8cf6484c587a1e30f07c3caa` |
| Head A run ID | `31534156493` (conclusion: success) |
| Head A V1 FULL attestation | schema 1, `run_id=31534156493`, `pr_number=78`, `base_sha=5ca28121…`, `head_sha=6a0f1b5…`, tier `full`, `full_matrix_required=true` — artifact ID `9118248219` |
| Head B SHA | `41abe630f8d3c14ee66ab5d218f6c26ab84109db` |
| Head B run ID | `31534838665` (conclusion: success) |
| Head B V1 FULL attestation | schema 1, `run_id=31534838665`, `pr_number=78`, `base_sha=5ca28121…`, `head_sha=41abe63…`, tier `full`, `full_matrix_required=true` — artifact ID `9118509668` |

## 3. Fingerprint artifacts

Temporary measurement artifacts (all CI-ONLY / NON-FORMAL-RELEASE):

| Surface | Head | Artifact name | Artifact ID |
|---|---|---|---|
| test-3.14 | A | `market-vault-runtime-fingerprint-test-3.14-6a0f1b5c6c2025db8cf6484c587a1e30f07c3caa-attempt-1` | `9118115429` |
| pyarrow24 | A | `market-vault-runtime-fingerprint-pyarrow24-6a0f1b5c6c2025db8cf6484c587a1e30f07c3caa-attempt-1` | `9118117181` |
| test-3.14 | B | `market-vault-runtime-fingerprint-test-3.14-41abe630f8d3c14ee66ab5d218f6c26ab84109db-attempt-1` | `9118380353` |
| pyarrow24 | B | `market-vault-runtime-fingerprint-pyarrow24-41abe630f8d3c14ee66ab5d218f6c26ab84109db-attempt-1` | `9118379613` |

Each artifact contains: `runtime_fingerprint.json`, `verification_receipt.json`,
`resolver_report.json`, `probe_summary.txt`, `probe_pip_dryrun.log`.

**Evidence-retention caveat (raw actual-install reports):** the actual heavy
install reports were generated and consumed during CI —
`install_report_314.json` (test-3.14), `dev_install_report.json` +
`pyarrow_pin_report.json` (pyarrow24) — but were NOT copied into
`fp-evidence/` and therefore were NOT retained inside the uploaded
measurement artifacts. Receipt generation and results were observed in the
exact CI jobs and remain valid measured evidence, but an independent
reviewer cannot replay `verify-installed` from the archived artifacts alone.
#78 does not claim full raw-evidence closure; a future canary must archive
the normalized actual install report(s).

## 4. Fingerprint schema and canonicalization contract

- `schema_version: 1`. Any other version → INVALID (`schema_version_unsupported`).
- Canonical payload: JSON with `sort_keys=True`, compact separators, ASCII
  escaping, newline-terminated; `fingerprint_sha256` field is computed over
  the payload WITHOUT itself; `resolved_distributions` are sorted by
  canonical name so raw-input ordering never changes the digest.
- Package names are PEP 503 canonicalized (`Moomoo_API` → `moomoo-api`).
- Download URLs are normalized; credential-bearing URLs are rejected
  (`url_credentials`); non-http(s) schemes are rejected.
- The local project itself is excluded from the resolved distribution set
  (its identity is covered by the project metadata contract:
  name / version / SHA256(pyproject.toml)).
- Missing required runner image field, missing distribution version,
  duplicate canonical package, malformed artifact hash, and probe-invalid
  documents all fail closed — never "unknown".

**Scope of what `resolved_distributions` proves:** the set is *the final
installed external runtime distribution set represented by pip's
machine-readable install report*. It does NOT include PEP 517 isolated
build-environment dependencies (see section 13).

## 5. Identity contract recorded per surface

| Block | Fields |
|---|---|
| Runner | `run_os` (RUNNER_OS), `run_arch` (RUNNER_ARCH), `image_os` (ImageOS), `image_version` (ImageVersion) — any missing → INVALID; plus `sys_platform`, `machine`, `release`, `libc_ver`, `sysconfig_platform` |
| Python | implementation, exact `version` (x.y.z), major/minor/micro, `cache_tag`, `soabi`, `pointer_width` |
| Resolver | pip name + exact version |
| Dependency contract | project name, version, `pyproject_sha256`, sorted dependencies / dev-dependencies (tomllib, no install needed) |
| Action contract | exact-SHA checkout / setup-python / upload-artifact pins + `ci_yml_sha256` |
| Resolved distributions | canonical name, version, normalized URL, artifact SHA256 for every external package in the final installed runtime set |

## 6. Action identity strategy

The temporary workflow pinned the executed actions to exact 40-hex SHAs,
derived independently from real CI logs at the frozen base (not trusted
from any mutable label). Auditability comments preserved the pre-existing
`@v6` / `@v7` substring contracts so every pre-existing check kept passing
while the EXECUTED action was the pinned commit.

| Action | Exact pin |
|---|---|
| actions/checkout | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| actions/setup-python | `ece7cb06caefa5fff74198d8649806c4678c61a1` |
| actions/upload-artifact | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` |

Workflow digest `ci_yml_sha256` recorded in both heads' fingerprints:
`e8bc4b21b50a306ed13cadd3971a33d6b68081b683c66bd2747cf30ad1030a8e`
(CI-ONLY / NON-FORMAL-RELEASE HASH) — identical across heads, as required
(ci.yml blobs are byte-identical A→B).

## 7. Fingerprint results

All FPs are CI-ONLY / NON-FORMAL-RELEASE HASHES.

| Surface | Head A FP | Head B FP | Cross-head |
|---|---|---|---|
| test-3.14 | `8fdfe97a7dab4412b38b50be30f223840907392ef7bfb1978b4caa220ef8e15c` | `8fdfe97a7dab4412b38b50be30f223840907392ef7bfb1978b4caa220ef8e15c` | `RUNTIME_FINGERPRINT_MATCH=true` `reason=ok` |
| pyarrow24 | `25260e426151a67e13c9933c0d93f1a58a8c0849d68c3bc090701b4c2c0581d2` | `25260e426151a67e13c9933c0d93f1a58a8c0849d68c3bc090701b4c2c0581d2` | `RUNTIME_FINGERPRINT_MATCH=true` `reason=ok` |

Head A and Head B fingerprints are byte-identical on both surfaces. This is
the natural equality case: the runtime identity actually did not change
between heads (same image, same exact Pythons, same pip, same resolved
dependency set — all verified independently of the fingerprints below), and
the canary comment flip lives in `tests/test_audit_v03.py`, which is outside
both measured surfaces' input boundaries (section 9).

## 8. Probe-vs-actual verification (all four surface/run combinations)

`verify-installed` compared ONLY the resolved distribution sets (the actual
install reports carry no runner/python/resolver identity — those are the
probe's claims, compared cross-head by the full comparator), plus a live
importlib cross-check of every recorded distribution and a live
`pyarrow.__version__` check on the pyarrow24 surface.

| Run | Surface | `probe_valid` | `actual_install_verified` | `actual_install_match` | `reason` |
|---|---|---|---|---|---|
| Head A | test-3.14 | true | true | **true** | null |
| Head A | pyarrow24 | true | true | **true** | null (pyarrow import 24.0.0 match) |
| Head B | test-3.14 | true | true | **true** | null |
| Head B | pyarrow24 | true | true | **true** | null (pyarrow import 24.0.0 match) |

The pre-install probe predicted the actual heavy runtime on all four
surface/run combinations (`PROBE_PREDICTED_RUNTIME_MATCHES_ACTUAL=true`).
No importlib cross-check mismatches anywhere. **Final installed distribution
prediction = PASS** for all four combinations.

## 9. A→B delta irrelevance (source-input proof)

- Head B is a direct child of Head A (`41abe63` parent = `6a0f1b5`); the
  A→B diff is exactly one comment line in one file.
- Required identical A→B blobs verified: `.github/workflows/ci.yml`,
  `scripts/ci_runtime_fingerprint.py`, `tests/test_ci_runtime_fingerprint.py`,
  `pyproject.toml`, `ci/python314_compatibility_surface.txt`,
  `scripts/ci_python314_surface.py`, and `src/**` — all byte-identical.
- `tests/test_audit_v03.py` has NO nodes in the sealed 258-node
  `ci/python314_compatibility_surface.txt` manifest.
- PyArrow24 surface accounting (corrected): the complete audited PyArrow 24
  path executes **10 unique test files** — 1 file on the A step
  (`tests/test_v060_portability.py`), 3 files on the B step
  (`test_canonical_reader.py`, `test_sample_generation_core.py`,
  `test_sample_generation_cli.py`), and 6 files on the C step
  (`test_canonical_materialization_v03.py`, `test_canonical_builder_v03.py`,
  `test_dataset_materialization.py`, `test_verified_dataset_reader.py`,
  `test_pit_sample_assembly.py`, `test_dataset_end_to_end_regression.py`).
  `tests/test_audit_v03.py` is none of them.
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
the sealed P2-2 measurement (docs/distinct_head_surface_evidence_canary.md,
section 11) recorded the same runner image `20260720.247.2` with CPython
3.14.6 and pip 26.2.1 — the hosted image has been stable across the #77-era
measurement and both #78 heads.

## 11. Performance observations (descriptive, not a gate)

| Step | Wall time |
|---|---|
| Probe (test-3.14, Head A) | 11.3 s |
| Probe (pyarrow24, Head A) | 10.5 s |
| Probe (test-3.14, Head B) | 12.5 s |
| Probe (pyarrow24, Head B) | 10.3 s |
| Python 3.14 compatibility surface pytest | ~55 s |
| Complete PyArrow24 A/B/C execution path | ~94 s (install 17 s + pin 2 s + A tests 1 s + B surface 35 s + C surface 39 s) |
| Heavy install (test-3.14) | ~23 s |
| 3.11 blanket FULL pytest | ~4 m 25 s — **contextual observation only**; #78 did not measure or authorize test-3.11 reuse, and this is NOT the upper bound for a surface the fingerprint could protect |

For the candidate surfaces, the probe (~10–12 s) is meaningfully cheaper
than the surfaces it could protect: the test-3.14 compatibility surface
(~55 s) and the complete PyArrow24 A/B/C path (~94 s). The probe runs in a
clean venv with no dependency on the heavy environment. **Dry-run download
analysis (from `probe_pip_dryrun.log`, not guessed):** the resolver
downloaded metadata ONLY — exactly 2 metadata fetches
(`pyarrow-25.0.1….whl.metadata`, `numpy-2.5.2….whl.metadata`), zero full
archives.

## 12. Comparator branches

- **Positive branch (naturally observed):** identical canonical fingerprints
  → `RUNTIME_FINGERPRINT_MATCH=true`, `reason=ok`. Observed for real in the
  cross-head comparisons of both surfaces (section 7), plus both
  probe-vs-actual verifications (section 8). No fake runtime data was
  manufactured.
- **Negative branch (naturally observed as mutation tests, section 18 of the
  spec):** `tests/test_ci_runtime_fingerprint.py` — 32 tests, all passing —
  covering every section-18 mutation: different ImageVersion, RUNNER_ARCH,
  Python micro, SOABI, pip version, dependency version / artifact SHA /
  missing / extra, action checkout / setup-python SHA, workflow digest,
  pyproject digest; plus strict-invalid cases (missing runner field, missing
  version, duplicate package, credential URL, malformed JSON, unsupported
  schema, probe-invalid doc, digest mismatch), ordering invariance, PEP 503
  canonicalization, URL credential rejection, and the verify-installed pure
  core (probe-invalid fails closed; probe-vs-actual mismatch fails closed;
  pyarrow24 live-import contradiction fails closed).

## 13. BUILD-ISOLATION PROOF GAP (the corrected decision's gap)

Current build contract:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

`pip install -e ".[dev]"` invokes a **PEP 517 isolated build environment**
before constructing the editable MarketVault installation. The actual FULL
logs visibly execute:

```
Installing build dependencies
Checking if build backend supports build_editable
Getting requirements to build editable
Preparing editable metadata (pyproject.toml)
Building editable for market-vault
```

The current runtime fingerprint does NOT contain resolved artifact identity
for those isolated build dependencies. Specifically,
`resolved_distributions` do NOT contain `setuptools` or `wheel` (verified in
both heads' fingerprints), and `pyproject_sha256` proves only that the
DECLARED ranges are unchanged — it does NOT prove which exact
setuptools/wheel artifacts were resolved into the build environment.

Therefore two heads can theoretically have **identical current fingerprints
but different build-backend resolution** — a possible false-positive
identity at the current schema's proof boundary.

**Fail-closed future rule:**
unproven / unequal build-isolation identity => RUN.

**Future gap to close (NOT implemented in #78): BUILD-ISOLATION IDENTITY.**
The next measurement must bind at minimum: exact build backend
distributions, exact versions, exact artifact SHA256, the build-system
requirement contract, applicable Python/runtime identity, and raw
actual-install evidence retention. Likely relevant current build
requirements: `setuptools>=68`, `wheel`.

## 14. Evidence-retention gap

Each archived runtime-fingerprint artifact contains exactly:
`runtime_fingerprint.json`, `verification_receipt.json`,
`resolver_report.json`, `probe_summary.txt`, `probe_pip_dryrun.log`.

The actual heavy install reports were generated and consumed during CI
(`install_report_314.json` for test-3.14; `dev_install_report.json` and
`pyarrow_pin_report.json` for pyarrow24) but were NOT copied into
`fp-evidence/` and therefore were NOT retained inside the uploaded
measurement artifacts. Consequences:

- receipt generation was observed in the exact CI jobs;
- receipt results remain valid measured evidence;
- but an independent reviewer cannot replay `verify-installed` from the
  archived artifact alone.

#78 does NOT claim full raw-evidence closure. A future canary MUST archive
the normalized actual install report(s).

## 15. Shadow decision chain (per surface)

| Proof leg | test-3.14 | pyarrow24 |
|---|---|---|
| SOURCE PROOF: valid Head A V1 FULL attestation + 4-job success + Head A fingerprint matches actual install | PASS | PASS |
| TRANSITION: Head B direct child + exact A→B delta | PASS | PASS |
| SOURCE-INPUT PROOF: #77 boundary contract proves delta irrelevant | PASS | PASS |
| RUNTIME PROOF: Head B live fingerprint valid + Head B FP == Head A FP | PASS | PASS |

All observed legs pass — but the shadow decision is CONDITIONAL on the
corrected decision: with the fail-closed rule "unproven / unequal
build-isolation identity => RUN", the current schema does not yet carry the
build-isolation proof leg, so production reuse is NOT READY despite the
passing observed legs. No production action consumes any of this in #78.

## 16. Decision (corrected)

**OUTCOME B — RUNTIME IDENTITY CONTRACT STILL HAS A PROOF GAP.**

PROVEN by #78:

- the lightweight live pre-install probe is viable;
- runner / Python / pip / action identity can be canonicalized;
- final external installed dependency versions + artifact SHA256 can be
  resolved before the heavy install;
- all four measured probe-vs-actual receipts matched;
- A/B cross-head fingerprints matched naturally (equality on both surfaces);
- the mutation comparator fails closed (32/32 tests);
- the probe is materially cheaper than the heavy surfaces it would protect.

NOT PROVEN:

- complete environment-construction identity — specifically PEP 517
  isolated build-environment dependency identity (setuptools / wheel
  artifact resolution) is outside the current proof boundary.

**Architecture conclusion:** #78 proves that a live pre-install runtime
fingerprint is a viable foundation, but the current schema is not yet
sufficient for production reuse because build-isolation dependency identity
is outside the proof boundary. Therefore cross-head production reuse
remains NOT READY and Partial Reuse V2 remains NOT ACTIVATED.

**Scope limit:** even the corrected decision does not change that the
fingerprint applies only to the specifically audited `test-3.14` and
`pyarrow24` surfaces. Still not allowed: package reuse, test-3.11 reuse,
arbitrary ancestry, transitive evidence chaining, cross-branch reuse,
production skipping, mutable-label-only action identity.

## 17. Remaining limitations

- PEP 517 build-isolation dependency identity is not represented (section 13).
- Raw actual-install reports were not retained in the measurement artifacts
  (section 14).
- The fingerprint is a snapshot of the CI runner's hosted image; GitHub can
  change `ImageVersion` between runs (no drift was observed here, and any
  drift would fail closed as `runner_image_version_unequal` ⇒ RUN).
- The resolved dependency set reflects PyPI state at probe time; identical
  fingerprints across a direct-parent pair prove the runtime was identical,
  but a future reuse decision still binds it to the exact head pair and the
  sealed source-input boundary contract.
- Probe cost (~10–12 s) is measured; a production mechanism would need the
  same fail-closed semantics (INVALID never "unknown") and its own
  performance budget.
- The canary measured two surfaces only; no claim is made for the package
  surface or the 3.11 blanket FULL surface.

## 18. Explicit statements

- **No production skip occurred.** Both heads executed the CURRENT FULL
  four-job validation contract end-to-end.
- **No V2 activated.** Partial Reuse V2 was not activated and no reuse
  mechanism consumes any canary result.
- **No runtime-fingerprint mechanism remains active on final head.** All
  temporary code (probe script, tests, workflow instrumentation, action
  pins, `--report` instrumentation, canary marker) is removed; ci.yml and
  test_audit_v03.py are byte-for-byte the frozen base.
- **No release/tag/main mutation occurred** during measurement preparation.
- **Raw actual-install report retention was incomplete** in the canary
  artifacts (section 14).
- **Formal decision corrected to OUTCOME B** after independent review;
  empirical measurement facts unchanged.

**Final PR head:**
NOT SELF-EMBEDDED BY DESIGN.
Authoritative value = GitHub PR metadata + exact-head CI at review time.
