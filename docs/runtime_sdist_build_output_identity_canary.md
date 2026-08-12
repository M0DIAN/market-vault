# P2-6 Runtime Sdist Build-Output Identity Canary (PR #81)

**Status: MEASURED / OUTCOME B — READY FOR INDEPENDENT REVIEW — STOP BEFORE MERGE**

This is the permanent record of PR #81's measurement. All measurement code was
temporary (removed in commit `80fa655`); the permanent diff of this PR is
**this document only**.

## 1. The question

P2-5 ([closed_world_build_execution_canary.md](closed_world_build_execution_canary.md),
PR #80) proved the real editable MarketVault build executes in a closed world,
but left one gap open (recorded in its §12): `runtime_resolver_report.json`
and `runtime_actual_install_report.json` recorded `moomoo-api 10.9.6908` as
resolved from `moomoo_api-10.9.6908.tar.gz` (SHA256
`6df0370ed120ec6e9f0bf65576a07838a7d105bb91e3ebb929f496a096700304`), while
`runtime_install.log` recorded `Using cached moomoo_api-10.9.6908-py3-none-any.whl`.
The runtime fingerprint bound the **source sdist artifact**, not the exact
**cached/built wheel bytes** actually installed.

**P2-6 research question:** for a runtime dependency resolved from an sdist
(concrete case: `moomoo-api 10.9.6908`), can the exact wheel artifact actually
installed be bound — same sdist / name / version / resolver identity but
**different cached/rebuilt wheel bytes must NEVER be treated as equivalent**?

**P2-6 answer (measured):** the sdist → wheel → install chain is bound
end-to-end (install report wheel SHA == built wheel SHA; installed payload
digest == built wheel payload digest; wheel RECORD valid; mutation-negative;
cache disabled; offline replay independently re-derives every check). The one
remaining proof gap is that **raw wheel bytes are nondeterministic under
identical same-run inputs**: two cache-disabled builds of the same sdist in
the same closed-world environment produce content-identical wheels that
differ only in the ZIP modification timestamps of the 5 build-generated
`dist-info/` members. The content digest (WHEEL_PAYLOAD_SHA256) is stable
across all four measurements. Per the §14 protocol rule, this makes Formal
OUTCOME A impossible for the raw-wheel architecture; the decision is
**OUTCOME B** with the exact gap identified (§15).

## 2. Measurement protocol (summary)

Per head, per candidate surface (test-3.14, pyarrow24), inside the FULL CI
job, in a shadow environment (measurement only, fail-closed markers):

1. **Runtime resolution/classification** — resolve the runtime with pip
   `--report`; classify wheel / sdist / other; inventory canonical names.
2. **Sdist materialization** — download the exact sdist bytes; verify SHA256
   equals the resolved artifact hash.
3. **Safe extraction** — extract to a fresh dir (no symlink escape, no
   absolute-path writes outside the extract root).
4. **Build contract** — read `pyproject.toml` build-system requires; probe
   `get_requires_for_build_wheel` (dynamic requirements); backend
   `setuptools.build_meta:__legacy__`; declared `[setuptools>=40.8.0, wheel]`;
   dynamic `[]`.
5. **Closed-world build environment** — fresh venv, `PIP_NO_INDEX=1`,
   hash-locked requirements, exact build wheels only; inventory + path-free
   `SOURCE_BUILD_ENVIRONMENT_SHA256`.
6. **Two cache-disabled builds** — `pip wheel --no-deps --no-build-isolation
   --check-build-dependencies --no-cache-dir` over the exact local sdist into
   two fresh output dirs; log must prove a wheel was built from local source
   (no "Using cached"); compute `RAW_WHEEL_REPRODUCIBLE = (b1 == b2)`.
   No `SOURCE_DATE_EPOCH` or other artificial determinism is applied.
7. **Wheel validation** — filename tags, archive structure, `.dist-info`
   METADATA/WHEEL/RECORD; every member except RECORD itself listed by RECORD
   with a secure hash; recompute member hashes.
8. **Payload identity** — `WHEEL_PAYLOAD_SHA256` over canonical sorted
   (relative path, member SHA256, size), excluding only the wheel's own
   RECORD; diagnostic only, never overrides a raw mismatch.
9. **Exact-wheel install** — fresh shadow venv, `pip install --no-deps
   --no-cache-dir --report source_built_install_report.json <exact wheel>`;
   require report source == the local wheel and report SHA == built wheel SHA;
   no package-name resolution.
10. **Installed payload proof** — locate the installed dist via
    importlib.metadata; every hash-bearing RECORD entry recomputed against the
    real installed files; `INSTALLED_PAYLOAD_SHA256` over canonical sorted
    (relative path, SHA256, size) excluding RECORD/.pyc/INSTALLER/REQUESTED/
    direct_url.json; record_valid.
11. **Immutability through remainder** — record identity immediately after
    install, provision the whole remainder runtime from an ephemeral
    wheelhouse (the source-built dependency substituted ONLY by the exact
    built wheel), re-verify name/version/RECORD/payload — unchanged.
12. **MarketVault editable install** under the P2-5 closed-world contract;
13. **Candidate surface execution** — the audited PyArrow-24 regression
    surface in the shadow env.
14. **Negative controls** — 19 negative identity tests run locally;
    a built-wheel **byte mutation** (one payload byte flipped) must fail
    validation and be rejected at install.
15. **Evidence bundle** — receipt, identity docs, probe records, reports,
    logs, both built wheel byte sets, wheelhouse, manifest, and the verifier
    self-copy; the offline replay re-derives every check from the bundle
    (`EVIDENCE_BUNDLE_REPLAY_OK`).

## 3. Heads

| | Head A | Head B |
|---|---|---|
| Marker | `# P2_RUNTIME_SDIST_OUTPUT_CANARY_A` | `# P2_RUNTIME_SDIST_OUTPUT_CANARY_B` |
| Commit | `d491d74195bb97912d40ccffe22b92274c49319d` | `b06238aa310aab864e89a964a4b08bd6fa1122a8` |
| Parent | prior instrumented commits | `d491d74` (Head A) |
| Diff | instrumented workflow + measurement tool | **one comment line** (marker flip only) |

Both heads are measurements of the **same sealed input state**:
frozen base `bb54e69b92331d64345fb67f11a894b636657c68`; `pyproject.toml`
SHA256 `50a8140a959eb59af7e8a6c999bf8a9677ee948c8375f101d13a1fe77b398a48`;
P2-5 report treated as prior proven layers (not re-proven).

## 4. CI runs

| | Head A | Head B |
|---|---|---|
| Run | `31578454088` | `31580115217` |
| test (3.11) | success | success |
| test (3.14) | success | success |
| portability-pyarrow24 | success | success |
| package | success | success |

4/4 FULL tier green on both heads.

## 5. Results per surface per head

All verdicts identical across heads; the only differences are the raw wheel
hashes themselves and `MEASURE_ELAPSED_SECONDS` (runner noise).

### test-3.14 (both heads)

```
SOURCE_SDIST_HASH_OK=true            SOURCE_BUILD_IDENTITY_VALID=false
FINAL_RUNTIME_MATCH=true             RUNTIME_WHEEL_COUNT=44
RUNTIME_SDIST_COUNT=1                RUNTIME_OTHER_COUNT=0
SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL=true
SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL=true
RUNTIME_INSTALL_FROM_WHEELS_ONLY=true
UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL=false
SHADOW_SURFACE_PASS=true             P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED=true
MEASURE_CRASH=false                  SDIST_MATERIALIZED_moomoo-api=true
RAW_WHEEL_REPRODUCIBLE_moomoo-api=false
MUTATED_WHEEL_REJECTED_moomoo-api=true
SOURCE_BUILD_CACHE_DISABLED_moomoo-api_1=true
SOURCE_BUILD_CACHE_DISABLED_moomoo-api_2=true
REPLAY_OK=true
```

### pyarrow24 (both heads)

Identical shape; `RUNTIME_WHEEL_COUNT=47`, `MEASURE_ELAPSED_SECONDS` 199.0
(Head A) / 150.0 (Head B).

## 6. Runtime sdist inventory

Exactly one runtime dependency resolves from a non-wheel source artifact:

| field | value |
|---|---|
| name / version | `moomoo-api` / `10.9.6908` |
| source artifact | `moomoo_api-10.9.6908.tar.gz` |
| source SHA256 | `6df0370ed120ec6e9f0bf65576a07838a7d105bb91e3ebb929f496a096700304` |
| build backend | `setuptools.build_meta:__legacy__` |
| declared build requires | `setuptools>=40.8.0`, `wheel` |
| dynamic build requires | none |

## 7. Source-build environment identity

Path-free `SOURCE_BUILD_ENVIRONMENT_SHA256`, **stable across heads** (and per
surface; the two surfaces provision different base toolchains):

| surface | Head A | Head B |
|---|---|---|
| test-3.14 | `67ce99edac909a80d16499d95809e32602bc2a8564d2dba4c272c666041d0f19` | same |
| pyarrow24 | `7f01eb9ac8d8f02c6495c015d509534e36ef36dfd3dcf09360143474647fb468` | same |

## 8. Built wheel identity (raw, repeat, payload)

Wheel filename: `moomoo_api-10.9.6908-py3-none-any.whl`.

| | Head A test-3.14 | Head A pyarrow24 | Head B test-3.14 | Head B pyarrow24 |
|---|---|---|---|---|
| build #1 raw SHA256 | `263b1aa2…1eb9c9` | `2b086d2b…231fa` | `f89ad5cb…cc236` | `41164898…54892` |
| build #2 raw SHA256 | `77bc72c8…4d4c7` | `77bc72c8…4d4c7` | `2338df80…9f4c1` | `f3cdbefb…52c5c` |
| repeat-build equality | **false** | **false** | **false** | **false** |
| WHEEL_PAYLOAD_SHA256 | `230368cd1d0fe21bf7a0bd25539aefcb581b9e932c8e8ff121814d54cb7472e6` | same | same | same |
| INSTALLED_PAYLOAD_SHA256 | `230368cd…` (same) | same | same | same |
| wheel RECORD / structure | valid (replay `built_wheel_identity=true`) | valid | valid | valid |

**Characterization of the raw non-reproducibility (independent member-level
analysis of the Head A test-3.14 pair):** both wheels contain 424 members;
every member's content is byte-identical (same set, same order, same SHA256,
same sizes, same sdist-derived mtimes). The **only** raw byte differences are
the ZIP local-header DOS modification-time fields of the **5 build-generated
`dist-info/` members** — `licenses/LICENSE`, `METADATA`, `WHEEL`,
`top_level.txt`, `RECORD` — stamped with wall clock at 2-second granularity
(build #1 at 08:28:46, build #2 at 08:28:48 in Head A). Total differing bytes
in the pair: 10. This is the classic bdist_wheel timestamp nondeterminism; no
`SOURCE_DATE_EPOCH` or equivalent is applied (protocol §14 forbids artificial
determinism).

Note: the Head A build #2 raw hash coincidentally equals across the two
surfaces — both jobs' second build landed in the same 2-second DOS tick
(08:28:48 on both runners). This is wall-clock co-timing, **not** evidence of
raw determinism; the cross-head and cross-surface reproducibility evidence is
the payload digest.

## 9. Exact-wheel install binding

For all four measurements (verified from the retained bundles):

- `source_built_install_report.json` install source URL is the exact local
  wheel: `file://…/cw-evidence/built_wheels/1/moomoo_api-10.9.6908-py3-none-any.whl`
  (the `built_wheels/1/` artifact slot; bundle relocation between measure dir
  and replay dir is tolerated by slot identity).
- report `download_info.archive_info.hashes.sha256` == build #1 raw SHA256
  (**true on all four**).
- installed distribution RECORD validates (`record_valid=true`);
  `INSTALLED_PAYLOAD_SHA256` == `WHEEL_PAYLOAD_SHA256` (**true on all four**).
- no package-name resolution: `PIP_NO_INDEX=1`, `--no-deps`, `--no-cache-dir`,
  explicit wheel path.

## 10. Cache-disabled and mutation-negative proofs

- `SOURCE_BUILD_CACHE_DISABLED_moomoo-api_1/2=true` on all four — both build
  logs prove a wheel was built from the local sdist; no `Using cached`.
- `MUTATED_WHEEL_REJECTED_moomoo-api=true` on all four — a wheel with one
  payload byte flipped fails RECORD hash validation and is rejected at
  install (negative control works).
- The 19-case negative test suite (RECORD self-entry, order-dependent
  fingerprint, manifest self-hash, receipt/verdict consistency, install-report
  bundle slot, pip ≥26 report schema, canonical-name inventory, …) passed
  locally before Head A (57 tests, all green).

## 11. Immutability through remainder + final runtime

- `SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL=true` and
  `SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL=true` — the installed moomoo-api
  identity (name/version/RECORD/payload) is unchanged after remainder
  provisioning and after the full shadow install.
- Final runtime contains **no source artifact**:
  `RUNTIME_INSTALL_FROM_WHEELS_ONLY=true`,
  `UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL=false` (1 sdist expected and
  substituted by the exact built wheel).

## 12. Shadow candidate surfaces

`SHADOW_SURFACE_PASS=true` on all four: the audited PyArrow-24 regression
surface executes inside the shadow env under the P2-5 closed-world contract
(`P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED=true`).

## 13. Cross-head complete identity comparison

Offline comparator over the retained `runtime_sdist_identity.json` documents
(runner, python, resolver, dependency contract, action contract, workflow,
resolved distributions, source sdist identity, source build environment
identity, exact built wheel SHA256, installed payload identity, MarketVault
build identity, valid/final-match/shadow flags — no field normalized away):

```
test-3.14  RUNTIME_SDIST_IDENTITY_MATCH=false  first_differing_field:exact_built_wheel_sha256
pyarrow24  RUNTIME_SDIST_IDENTITY_MATCH=false  first_differing_field:exact_built_wheel_sha256
```

Every field matches across heads except `exact_built_wheel_sha256` — the raw
wheel bytes differ per build (the timestamp nondeterminism of §8). Notably,
unlike P2-5, the runner/python identities **did not drift** between heads
(first differing field is not `runner`). The build environment identity is
identical across heads (§7).

**Separable questions:** (A) architecture validity — the sdist → wheel →
installed-bytes binding is measured and works (all install/RECORD/payload/
replay checks pass on all four bundles), with the raw-reproducibility caveat;
(B) pair reusability — **not reusable**: a Head A measurement cannot stand in
for Head B's evidence because the exact built wheel SHA256 differs.

## 14. SHADOW_REUSE_CANDIDATE decision (actual, from CI logs)

`SHADOW_REUSE_CANDIDATE = replay_ok && SOURCE_BUILD_IDENTITY_VALID &&
FINAL_RUNTIME_MATCH` → `true && false && true` = **false** on all four
measurements (recorded in the CI step environment, e.g.
`SHADOW_REUSE_CANDIDATE: false` in Head B test-3.14). No reuse candidate is
produced; consistent with §15's fail-closed production rule.

## 15. Outcome determination

**OUTCOME B — RUNTIME SOURCE-BUILD OUTPUT IDENTITY STILL HAS A PROOF GAP.**

Formal OUTCOME A is impossible here by the protocol's own rule (§14): same-head
repeated raw wheel builds are **not** byte-identical
(`RAW_WHEEL_REPRODUCIBLE=false` on all four measurements). Every other
OUTCOME-A condition is measured true:

- all runtime sdists discovered (`RUNTIME_SDIST_COUNT=1`, `OTHER_COUNT=0`);
- exact source bytes/hash verified (`SOURCE_SDIST_HASH_OK=true`,
  `6df0370e…`);
- build contract identified (backend + declared + dynamic);
- source-build environment exact and closed-world (stable env identity, §7);
- pip cache disabled (`SOURCE_BUILD_CACHE_DISABLED_1/2=true`);
- exact built wheel SHA256 captured (§8);
- wheel RECORD validates (replay `built_wheel_identity=true`);
- shadow install uses the exact local wheel (report URL slot, §9);
- install report wheel SHA == built wheel SHA (true on all four);
- installed RECORD validates; installed payload identity captured
  (`230368cd…` == built payload);
- source-built package not later replaced (§11);
- final runtime contains no source artifact (§11);
- both candidate shadow surfaces pass (§12);
- mutation negative fails closed (§10);
- all four authoritative bundles replay offline (`EVIDENCE_BUNDLE_REPLAY_OK=true`
  ×4, `REPLAY_OK=true` ×4);
- no production skip occurred.

**Exact remaining gap (identified per §33):** raw wheel output is
nondeterministic under identical same-run inputs — the 5 build-generated
`dist-info/` members carry wall-clock ZIP modification timestamps. Content is
fully deterministic (424/424 members byte-identical; payload digest stable
across heads and surfaces), so the gap is precisely: **container timestamp
metadata of build-generated dist-info members**.

OUTCOME B does NOT activate V2 and does NOT mean the measured A/B pair is
reusable (it is not, §13).

**Fail-closed production rule (unchanged):** any runtime dependency resolved
from a non-wheel source artifact whose exact resulting install
artifact/code identity is not proven => **RUN**. Raw-wheel reuse remains
NOT READY for production activation.

## 16. Honored constraints (no drift)

- No Partial Reuse V2 activation; no production skips; no package reuse
  authorized; no test-3.11 reuse authorized; V1 attestation schema unchanged;
  no release behavior change; audited candidate surfaces unchanged
  (`test-3.14` + `pyarrow24`).
- No amend / rebase / force-push / release-tag mutation anywhere in PR #81.
- `pyproject.toml`, `src/**`, `scripts/ci_post_merge_reuse.py`,
  `scripts/ci_risk_tier.py`, `scripts/ci_python314_surface.py`,
  `scripts/check_release.py`, `ci/python314_compatibility_surface.txt`:
  never modified.
- Temporary scope (instrumented `ci.yml`, action pins, measurement tool,
  tests, Head A/B marker) removed in commit `80fa655`; `ci.yml` and
  `tests/test_audit_v03.py` restored **byte-for-byte** to the frozen base.
- Final PR diff: **this document only**.
- All hashes/artifacts cited here are CI-only / non-formal-release.

## 17. Evidence identities (authoritative artifacts)

| Item | Head A (`d491d74…`) | Head B (`b06238a…`) |
|---|---|---|
| Run | `31578454088` | `31580115217` |
| V1 full-CI attestation artifact | `9134336408` | `9134945513` |
| test-3.14 evidence artifact | `9134234878` | `9134891800` |
| pyarrow24 evidence artifact | `9134303596` | `9134916165` |

Each evidence artifact contains the full receipt, identity docs, probe
records, reports, logs, both built wheel byte sets, wheelhouse, manifest,
and the verifier self-copy — everything an independent reviewer needs to
replay every conclusion offline (the Head A replay was executed from a
relocated bundle copy, `replay-bundle/`, exactly as CI does).

## 18. Performance

`MEASURE_ELAPSED_SECONDS`: test-3.14 132.0 (A) / 121.5 (B); pyarrow24 199.0
(A) / 150.0 (B). Leg breakdown (Head A test-3.14, seconds):

| leg | s | leg | s |
|---|---|---|---|
| shadow surface | 63.6 | runtime resolution | 9.0 |
| remainder install | 16.0 | build-env provision | 5.8 |
| MarketVault editable install | 14.6 | exact-wheel install | 5.4 |
| build-requires probe | 11.7 | wheel build #1 / #2 | 2.0 / 2.0 |
| build-env resolve | 0.5 | sdist materialize / extract | 0.1 / 0.2 |
| wheel validation | 0.2 | installed-payload verify | 0.1 |

The measurement adds ~2–3 min to the FULL tier legs and uploads no secrets;
measurement steps are removed on the final head.

## 19. Remaining limitations and next measurement

- Raw wheel bytes remain head-variant (timestamps); a **normalized-payload
  identity design** (bind WHEEL_PAYLOAD_SHA256 + INSTALLED_PAYLOAD_SHA256 as
  the reuse identity, validated against the raw mismatch and the mutation
  negative) could be measured separately, per the protocol's §14 note.
- The gap characterization is for the current surfaces' single sdist case
  (`moomoo-api 10.9.6908`); other sdists may exhibit different
  nondeterminism.
- The wheels-only runtime substitution and the editable-install survival
  proofs were measured under the current locked runtime pinning; a changed
  runtime resolver could surface new sdist cases.

## 20. Final head and gates

Final PR head is **NOT self-embedded by design**; authoritative identity =
GitHub metadata + exact-head CI at review time. Final local gates (run on the
docs-only head): `git diff --check` clean; `check_repo_hygiene.py` pass;
`check_release.py` `RELEASE_CHECK_OK version=0.7.0`; `ci_risk_tier.py`
`tier=docs_fast reason=all_changes_in_docs_scope full_matrix_required=false`;
final CI silent, 4/4 jobs success, **0 artifacts**.

Explicitly stated:

- No V2 activated.
- No production skip occurred.
- No package reuse authorized.
- No test-3.11 reuse authorized.
- No release/tag mutation occurred.
- All measurement hashes are CI-only / non-formal-release.

**STOP BEFORE MERGE.**
