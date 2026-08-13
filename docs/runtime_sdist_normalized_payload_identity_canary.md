# P2-7 Runtime Sdist Normalized Payload Identity Canary (PR #82)

## 1. The question

P2-6 (PR #81, `docs/runtime_sdist_build_output_identity_canary.md`) measured the
runtime sdist → wheel → install chain and left the P2 proof stack **NOT
CLOSED**: the two builds of the same sdist in the same closed-world
environment produced wheels whose **raw bytes differ** (ZIP timestamp
metadata), so a raw reproducibility gate can never close. P2-7 measures
whether an **acceptable normalized install-artifact identity** can close that
gap **without treating arbitrary different wheel bytes as equivalent**:

- RAW wheel bytes stay a **diagnostic** (`RAW_WHEEL_REPRODUCIBLE=false` is the
  honest measurement, never normalized away).
- The normalized identity is declared valid **only if** the raw mismatch is
  proven to consist **entirely** of the explicitly accepted non-semantic ZIP
  timestamp metadata (`zip_dos_modification_timestamps_of_build_generated_members_only`)
  with **identical decompressed payloads** and every other identity layer
  exact: normalized payload identity, installed identity, sdist, closed-world
  build environment, contracts, and final runtime.
- **Negative controls** must reject: payload byte mutation, inconsistent
  RECORD, member add/remove/rename, duplicate paths, wrong
  name/version/tags, non-timestamp ZipInfo attribute change, unclassified
  raw differences, sdist/build-env drift, installed payload mismatch.
- **Positive control** must pass: a timestamp-only mutation within the
  allowed contract preserves the normalized identity and installs to the
  same installed payload SHA.
- **Retained evidence closure** (the P2-6 defect): the uploaded evidence
  bundle is downloaded, replayed byte-exactly read-only, and the replay
  verdict lives **outside** the manifest-bound bundle. No mutation, no
  appending into `probe_summary.txt` or any manifest-bound file, no
  re-upload of a modified copy.
- **Cross-head**: two heads differing only by the canary marker comment must
  produce RAW mismatch (first differing field: raw wheel SHA) but NORMALIZED
  identity match, with all global identity contracts exact.

Scope was strictly temporary and shadow-only: `scripts/ci_runtime_sdist_normalized_identity.py`,
`tests/test_ci_runtime_sdist_normalized_identity.py`,
`.github/workflows/ci.yml`, `tests/test_audit_v03.py` (marker only). No
`src/**`, pyproject, version, dependency ranges, public API, CLI, schema,
release assets, or the v0.7.0 tag/release were touched. `POST_MERGE_REUSE`,
production skips, and the formal 3-job topology (`test`,
`portability-pyarrow24`, `package`) were never altered.

## 2. Measurement protocol (summary)

1. Resolve the runtime sdist (project surface) and record resolver identity.
2. Materialize + hash the sdist (`SOURCE_SDIST_HASH_OK`).
3. Derive the build contract exactly like pip (pyproject `[build-system]`
   table when present, else the legacy fallback `setuptools.build_meta:__legacy__`
   with `["setuptools>=40.8.0", "wheel"]`). This project has no
   pyproject.toml → `BUILD_CONTRACT_SOURCE=legacy_fallback`).
4. Provision the P2-5 closed-world build environment: exact resolved wheels
   (`packaging`, `setuptools`, `wheel`), hash-locked,
   `PIP_NO_INDEX=1` + local wheelhouse, no build isolation, no
   auto-install channel.
5. Build twice from fresh extractions with `--no-cache-dir --no-deps
   --no-build-isolation --check-build-dependencies` under
   `PIP_NO_INDEX=1`; record **both** raw wheel SHAs (diagnostic).
6. Structural + PEP 427 RECORD validation of both wheels; compute
   `WHEEL_PAYLOAD_SHA256` (canonical sorted `(relpath, member SHA256, size)`,
   own RECORD excluded).
7. Install the exact wheel with an install report; recompute the installed
   RECORD and `INSTALLED_PAYLOAD_SHA256` (RECORD/INSTALLER/REQUESTED/
   direct_url.json/.pyc/`__pycache__` excluded); require
   `WHEEL_PAYLOAD_SHA256 == INSTALLED_PAYLOAD_SHA256`.
8. Classify the raw mismatch: every differing member's raw/container
   metadata compared with fail-close on filename, CRC, sizes, compression
   method, flag bits, attributes, create/extract versions, extra fields
   (except the parsed timestamp field), comments, ordering, duplicate
   paths. Unclassified differences ⇒ INVALID.
9. Negative controls (mutated wheels must be rejected) and the positive
   timestamp-only control (must preserve normalized identity and installed
   payload).
10. Assemble the manifest-sealed evidence bundle (manifest generated last),
    replay it offline, and (in-package roundtrip) download the retained copy
    in the package job and replay it read-only with the verdict recorded
    outside the bundle.

## 3. Heads

| Head | Commit | Content |
|---|---|---|
| A | `3ab3db01c08233257b654c05b16f3a7997c619d4` | Instrumented surface + marker `P2_NORMALIZED_SDIST_PAYLOAD_CANARY_A` |
| B | `b9f24abe28a3e9c5697bdd5f7db1e753f1a33d0b` | Exact direct child of A; only diff = marker comment `_A` → `_B` |
| fix | `614f5a5e38ec61c2883a1504fdcff66fb9fc37cd` | Cross-head comparator fix (diagnostic exclusion), measurement semantics unchanged, marker stays `_B` |

A pinned-action auditability defect found on Head A's first CI run (the
formal suite requires the literal `uses: actions/<name>@<major>` string
with the `uses:` prefix; the pinned form's comment lacked it) was fixed
before the recorded Head A run: the pinned `uses:` SHA remains
authoritative and the auditability literal is preserved in the comment.

## 4. CI runs

Every recorded run is an exact-head run (run head verified equal to the
commit above) with all four jobs **success**:

| Head | Run | test 3.11 | test 3.14 | portability-pyarrow24 | package |
|---|---|---|---|---|---|
| A | `31627097067` | success | success | success | success |
| B | `31627790944` | success | success | success | success |
| fix | `31629138376` | success | success | success | success |

## 5. Results per surface per head

Surface = `test-3.14` (project `moomoo-api` 10.9.6908 resolved on the 3.14
leg) and `portability-pyarrow24`. All values below are identical across all
three heads unless stated; every leg measured `MEASURE_CRASH=false`.

| Marker | test-3.14 | pyarrow24 |
|---|---|---|
| `EVALUATED_NORMALIZED_INSTALL_ARTIFACT_IDENTITY_VALID` | true (reason=ok) | true (reason=ok) |
| `RAW_WHEEL_REPRODUCIBLE` (diagnostic) | false | false |
| `EVALUATED_RAW_MISMATCH_NORMALIZATION_VALID` | true | true |
| `RAW_MISMATCH_REASON` | timestamp_only_contract_ok | timestamp_only_contract_ok |
| `RAW_DIFF_ATTRIBUTION` (per head) | A 10 / B 8 / fix 10, unclassified **0** | A 2 / B 4 / fix 2, unclassified **0** |
| `WHEEL_PAYLOAD_SHA256` | `230368cd1d0fe21bf7a0bd25539aefcb581b9e932c8e8ff121814d54cb7472e6` | same |
| `INSTALLED_PAYLOAD_SHA256` | same (`== WHEEL_PAYLOAD_SHA256`) | same |
| `PAYLOAD_ENTRY_COUNT_1` / `_2` | 423 / 423 | 423 / 423 |
| `INSTALLED_PAYLOAD_ENTRY_COUNT` | 423 | 423 |
| `RECORD_VALID_1` / `_2` / `INSTALLED_RECORD_VALID` | true / true / true | true / true / true |
| `WHEEL_VALIDATION_1` / `_2` | true / true | true / true |
| `MUTATED_WHEEL_REJECTED_moomoo-api` | true | true |
| `POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK_moomoo-api` | true | true |
| `POSITIVE_CONTROL_INSTALLED_PAYLOAD_MATCH` | true | true |
| `SOURCE_BUILD_ENVIRONMENT_SHA256` | `34d6f71ca737fb65ab9fd206615170f9aa6834c6aa49a3b93e24cceacc164045` | same |
| `SOURCE_SDIST_HASH_OK` / `BUILD_CONTRACT_SOURCE` | true / legacy_fallback | true / legacy_fallback |
| `INSTALL_REPORT_SHA_OK` / `SLOT_OK` | true / true | true / true |
| `MANIFEST_ENTRY_COUNT` | 517 | 520 |
| `RUNTIME_WHEEL_COUNT` | 44 | 47 |
| `NORMALIZED_SOURCE_BUILD_IDENTITY_SHA256` (per head) | A `05a2a1025f6bf0be750d1b5ee5f008cdc925c4167ac66aeafe1bef1608021b67` · B `1611f4ced55476622824e23a5ff4818a87130ed9522d2cca217744c8359ea19b` · fix `77d4e3bc7c3be609f1ee66c7e5e425849b0a7125adb31eb89d1117160e9468a4` | A `bbd6236b0f57c3ebc38cee98092af3405557f30e9021c7ca16519546cd2f49cd` · B `64bf51a737af902c24d27dfad0c9c90db43993f00e31498ffd6efd76ec85bc50` · fix `88ab519536374eba00e5954ed170e4f2291654624e0f1a9fe0d6e8376f124282` |

`NORMALIZED_SOURCE_BUILD_IDENTITY_SHA256` is the per-measurement digest and
binds its context, including the canary head — it therefore differs across
heads by design. The cross-head identity claim is established by the
comparator over the head-independent identity payload (section 11), not by
equalizing this digest.

`SOURCE_BUILD_IDENTITY_VALID=false` on every leg is **correct and expected**:
it is the raw reproducibility gap that this canary characterizes and closes
via the normalized identity.

## 6. Runtime sdist inventory

The runtime sdist set (`RUNTIME_WHEEL_COUNT`: 44 on test-3.14, 47 on
pyarrow24) resolved identically across heads; `UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL=false`
and `UNEXPECTED_REMAINDER_SDIST=false` on every leg. `SDIST_PROJECT_ROOT_FOUND=true`
(the legacy `setup.py` project root is located correctly).

## 7. Source-build environment identity

`SOURCE_BUILD_ENVIRONMENT_SHA256=34d6f71c…` — identical on all six
measurements. The P2-5 closed-world contract was exercised on every leg
(`P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED=true`): exact wheels, hash-locked,
`PIP_NO_INDEX=1`, wheelhouse-only, no isolation.

## 8. Built wheel identity (raw, payload) and negative controls

- Raw: two wheels built twice from fresh extractions; both raw SHAs
  recorded as diagnostics; `RAW_WHEEL_REPRODUCIBLE=false` on every leg.
- Raw difference classification: **100% attributed** to the approved
  non-semantic ZIP modification-timestamp contract
  (`local_or_central_timestamp` members, `unclassified: 0`) with
  `RAW_DIFF_BYTE_COUNT` matching the attributed member count; the
  decompressed payload bytes are identical member-for-member
  (`WHEEL_PAYLOAD_SHA256` equal, `PAYLOAD_ENTRY_COUNT_1 == _2 == 423`).
- Negative controls on every leg: mutated payload wheel, stale-RECORD
  wheel, and content-drift wheels are all **rejected**
  (`MUTATED_WHEEL_REJECTED_moomoo-api=true`).
- Positive control on every leg: a timestamp-only mutation within the
  allowed contract preserves the normalized identity
  (`POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK_moomoo-api=true`) and
  installs to the same installed payload
  (`POSITIVE_CONTROL_INSTALLED_PAYLOAD_MATCH=true`).

## 9. Exact-wheel install binding

`WHEEL_PAYLOAD_SHA256 == INSTALLED_PAYLOAD_SHA256 = 230368cd…` on every
leg — the installed bytes equal the built bytes equal the reported bytes
(423 payload entries, `INSTALLED_RECORD_VALID=true`,
`INSTALL_REPORT_SHA_OK=true`, `INSTALL_REPORT_SLOT_OK=true`).
`EVALUATED_INSTALLED_PAYLOAD_MATCH=true`, `EVALUATED_WHEEL_PAYLOAD_MATCH=true`,
`EVALUATED_NORMALIZED_INSTALL_ARTIFACT_IDENTITY_VALID=true` (reason=ok).

## 10. Retained-artifact roundtrip closure (in-package, shadow only)

The P2-6 retained-evidence defect is closed: each measured head's evidence
bundle is uploaded from its measurement job, downloaded in the package job
with an exact-SHA-pinned `download-artifact`, and replayed **read-only**
with the verdict written **outside** the bundle (workspace-root receipt,
never appended into `probe_summary.txt` or any manifest-bound file; the
original uploaded-then-downloaded artifact is the authoritative retained
copy and is never re-uploaded).

| Head | Run | test-3.14 replay | pyarrow24 replay | overall |
|---|---|---|---|---|
| A | `31627097067` | true (28 checks) | true (28 checks) | `RETAINED_ARTIFACT_ROUNDTRIP_REPLAY_OK=true` |
| B | `31627790944` | true (28 checks) | true (28 checks) | true |
| fix | `31629138376` | true (28 checks) | true (28 checks) | true |

Head A replay tree SHAs (retained copies): test-3.14
`cc9e146c2c261c7c2a7e1ccdde6481f448c5fb83fdcae180fd1488b926128501`,
pyarrow24 `572cd65daa1ef1a3bab6b3f0adb7a75fc8a7f0f8071c89858ae877b0e22e0720`
(equal to the manifest-bound bundle tree SHA printed by the bundle step).
A roundtrip replay failure would have set the shadow verdict false and
would never have skipped production validation.

The bundle's own verifier copy is executed for replay
(`EVIDENCE_BUNDLE_REPLAY_OK=true`, `CHECK_COUNT=28`); `VERIFIER_SHA256`
changed only between Head B (`6fa20d62…`) and the fix head (`e82cead7…`)
because the comparator fix modified the tool; the verify path itself is
unchanged and every replay passed on every head.

## 11. Cross-head complete identity comparison

Per surface, over the retained Head A/B evidence bundles:

| Surface | RAW match | RAW reason | NORMALIZED match | NORMALIZED reason | Global contracts |
|---|---|---|---|---|---|
| test-3.14 | **false** | `first_differing_field:exact_built_wheel_sha256` | **true** | ok | **true** (ok) |
| pyarrow24 | **false** | `first_differing_field:exact_built_wheel_sha256` | **true** | ok | **true** (ok) |

`normalization_valid_a/b = true` on both surfaces. The RAW mismatch is
fully explained by the approved timestamp contract (`unclassified: 0` on
every leg of both heads), and every other identity layer — runner, python,
resolver, dependency/action contracts, resolved distributions, source
sdist, build environment, build contract, wheel payload identity, installed
payload identity, MarketVault P2-5 build identity, final runtime identity,
shadow surface — matches exactly. The comparator **never** normalizes
runner/python/resolver/build-env drift, and it excludes from the normalized
payload only the per-run diagnostics (raw wheel SHAs, per-run fingerprint,
canary head, surface) and the verdict's run-noise subfields
(`diff_attribution`, `diff_byte_count` — the count of timestamp-differing
members varies per build pair); the verdict's identity subfields
(`allowed_difference`, `normalization_valid`, `raw_wheel_reproducible`,
`reason`) participate and were identical.

Note on the comparator fix (head `614f5a5e`): the initial comparator
excluded the raw diagnostic dict but not the `raw_diagnostic_sha256`
string, and did not strip the verdict's run-noise subfields, which would
have misreported the normalized cross-head verdict as false. The fix
extracts the identity payload via one deterministic function, with three
regression tests (raw-diagnostic drift, attribution-noise drift, and
verdict-identity change) — the third proves a genuine verdict change still
breaks the normalized match. Re-run against the retained Head A/B evidence
produces the table above. No measurement, bundle, or replay behavior
changed.

## 12. SHADOW_REUSE_CANDIDATE

`SHADOW_REUSE_CANDIDATE = normalized_identity_valid && retained_artifact_roundtrip_replay_ok && final_runtime_match && shadow_surface_pass && all_global_identity_contracts_match` = **true** on both surfaces, derived from:
`EVALUATED_NORMALIZED_INSTALL_ARTIFACT_IDENTITY_VALID=true`,
`RETAINED_ARTIFACT_ROUNDTRIP_REPLAY_OK=true`,
`FINAL_RUNTIME_MATCH=true`, `SHADOW_SURFACE_PASS=true`, global contracts
match. This is **shadow evidence only**: it does not gate production, does
not activate V2, does not alter `POST_MERGE_REUSE`, and changes no
production skip.

## 13. Outcome determination

Exactly one formal outcome: **OUTCOME A — identity valid (all legs true)**.

Every leg of every head measured `EVALUATED_NORMALIZED_INSTALL_ARTIFACT_IDENTITY_VALID=true`
(reason=ok), all invariants true, all negative controls passed, the
positive timestamp-only control passed, the retained-artifact roundtrip
closed on both surfaces, and the cross-head comparison shows the RAW
mismatch fully explained by the approved timestamp contract while the
NORMALIZED identity and all global identity contracts match. The exact
wheel artifact install identity is bound (installed bytes == built bytes ==
reported bytes), with the raw reproducibility caveat fully characterized.
Everything measured, nothing changed.

## 14. Honored constraints (no drift)

- Scope strictly temporary: tool, tests, ci.yml instrumentation, and the
  marker in `tests/test_audit_v03.py` are removed at cleanup; the
  permanent PR diff is exactly this document.
- Exact action pins at execution time, auditability literals preserved:
  checkout `d23441a48e516b6c34aea4fa41551a30e30af803`, setup-python
  `ece7cb06caefa5fff74198d8649806c4678c61a1`, upload-artifact
  `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`, download-artifact
  `d3f86a106a0bac45b974a628896c90dbdf5c8093`.
  (Observed tag drift: `download-artifact@v7` now resolves to
  `37930b1c…`; the instrumented pin remains authoritative and the drift is
  documented, not chased.)
- No merge, no amend/rebase/force-push at any point; PR #82 head advanced
  only by new commits.
- No raw-mismatch-wins shortcut: the normalization-valid gate requires raw
  differs AND payload identical AND every raw/container difference proven
  within the timestamp contract; any unexplained difference ⇒ INVALID.
- No production semantics touched: the formal 3-job topology, release/
  package validation (including the unconditional
  `python scripts/check_release.py`), reuse gate, and all skips are
  unchanged (verified `RELEASE_CHECK_OK version=0.7.0` before every head).
- Replay verdicts live outside the manifest-bound bundle; the original
  uploaded evidence is never mutated or re-uploaded.

## 15. Evidence identities (authoritative artifacts)

Run-scoped artifacts (all `attempt-1`, names bound to the run head SHA):

| Head | Run | Bundle artifacts | Roundtrip receipt |
|---|---|---|---|
| A | `31627097067` | `…-test-3.14-3ab3db01…` `9153631857` · `…-pyarrow24-3ab3db01…` `9153637351` | `9153735915` |
| B | `31627790944` | `…-test-3.14-b9f24abe…` `9153908854` · `…-pyarrow24-b9f24abe…` `9153903855` | `9153984722` |
| fix | `31629138376` | `…-test-3.14-614f5a5e…` `9154440230` · `…-pyarrow24-614f5a5e…` `9154431750` | `9154497109` |

Formal production artifacts (unchanged semantics) also recorded per run
(`market-vault-package-…`, `market-vault-full-ci-attestation-…`).

## 16. Performance

`MEASURE_ELAPSED_SECONDS` 73–84 per leg (resolve + double build + double
install + controls), consistent with P2-6; no timeout or retry anomalies.

## 17. Remaining limitations

- The normalized identity covers the source-built wheel artifact; the raw
  reproducibility gap (ZIP timestamps of build-generated members) remains
  measured-false and is the reason the proof stack stays classified by the
  canary rather than by raw equality.
- Attribution counts (`diff_attribution`, `diff_byte_count`) vary per build
  pair and are measurement noise by design; they never enter the identity.
- The canary measured two surfaces on the CI runner image at the time of
  the runs; runner drift between heads is never normalized (it breaks the
  strict comparison and the global contracts as intended).

## 18. Final head and gates

After cleanup (ci.yml and `tests/test_audit_v03.py` restored byte-for-byte
to `1f6cf3ec`, tool + tests + scratch removed), the final docs-only head
carries exactly this document. Local gates before the final push: `git
diff --check`, `check_repo_hygiene.py`, `check_release.py`
(`RELEASE_CHECK_OK version=0.7.0`), and the offline ci-auditability/
release suites. The final exact-head CI run must conclude 4/4 jobs
success with the formal suite green and no canary artifacts.
