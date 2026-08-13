# P2-8 Partial Reuse V2 Proof-Stack Closure Review (PR #83, rev 2)

**Rev 2 — independent-review corrections applied.** Rev 1 (outcome A draft)
was reviewed independently; the review accepted scope discipline, exact-head
CI, historical P2-1..P2-7 outcome representation, P2-6/P2-7 technical
closure, and the candidate-surface boundary, but required: (1) an explicit
production evidence topology / provenance proof (blocking), (2) outcome
discipline re-derivation, (3) predicate-5 ambiguity removal, (4)
evidence-precision corrections, (5) retained-artifact wording tightening.
Rev 2 applies all five. The formal result changed from OUTCOME A to
**OUTCOME B** — see §12 for the exact derivation and remaining gap.

**Status: ARCHITECTURE / EVIDENCE CLOSURE REVIEW ONLY — OUTCOME B
(INTEGRATED MEASUREMENT CHAIN CLOSED; PRODUCTION V2 SURFACE-EVIDENCE
PROVENANCE / POST-MERGE TOPOLOGY BRIDGE OPEN).**

**No Partial Reuse V2 activation. No production skip. No workflow gating
change. No production code change. No test logic change. No attestation
schema change. No release/tag mutation.**

This document is the permanent integrated proof review over the sealed P2
evidence stack (PRs #76–#82). It answers one question:

> Can the existing measured evidence support a fail-closed production
> Partial Reuse V2 contract for the audited candidate surfaces?

The answer was not assumed. It is derived per proof layer below, with every
logical bridge shown. The formal result is exactly one of OUTCOME A /
OUTCOME B / OUTCOME C; the result of this review is **OUTCOME B — the
measurement chain is closed and sound for the identity mechanisms, but the
production evidence topology contains bridges that depend on new per-surface
attestation behavior not exercised by any sealed measurement** (§12). This
authorizes **no** production reuse and activates **nothing**.

---

## 1. Frozen base and identities

| Item | Value |
|---|---|
| Frozen base SHA (HEAD == origin/main, verified) | `8aeef5fb99f5abed06b25db622cb17cf9afd5fa3` |
| Base content | P2-7 merge commit (PR #82, docs-only evidence report) |
| Branch | `docs/partial-reuse-v2-proof-stack-closure` |
| PR | assigned by GitHub at creation (not assumed here) |
| Final head | not self-embedded by design (the authoritative final head is GitHub PR metadata plus the exact-head CI run at review time) |
| Working tree at base | clean (verified before branch creation) |

Base gate executed before any work: `git switch main`, `git fetch origin
--prune --tags`, `git pull --ff-only` (fast-forward to `8aeef5f`), then
`git rev-parse HEAD origin/main` → both exactly `8aeef5f…`. No drift, no
working-tree residue.

---

## 2. P2 foundation status (PR #65 — `docs/development_protocol_v1.md` §4.9)

**Status: FOUNDATION ONLY, unchanged, not activated.**

- The V2 evidence matrix lives in
  [`scripts/ci_post_merge_reuse.py`](../scripts/ci_post_merge_reuse.py)
  (`build_surface_reuse_plan` / `SurfaceDecision` / `ReusePlan` /
  `render_reuse_plan`): pure, deterministic, no I/O; NOT wired into
  `run_verifier()`; ci.yml does NOT parse its output. V1's
  `POST_MERGE_REUSE` semantics, `render_verdict()`, `skip_heavy_validation`,
  attestation schema and field order are byte-unchanged (regression-pinned
  in `tests/test_ci_post_merge_reuse.py`: V2 output never collides with the
  V1 contract; the identity-false → 4/4 `reuse=false` invariant holds for
  the complete input matrix).
- **Global identity hard boundary**: partial reuse is allowed only after
  global identity is independently proven. Identity unproven → `no_reuse`,
  every surface `reuse=false`, reason=`global_identity_unproven`. There is
  no state with `identity_proven=false` and any `surface.reuse=true`
  (regression-tested).
- **Canonical surface model** (fixed order): `test-3.11` →
  `test (3.11)`; `test-3.14` → `test (3.14)`; `pyarrow24` →
  `portability-pyarrow24`; `package` → `package`.
- **Ambiguity fail-closed**: duplicate canonical job →
  `job_duplicate_contract`; unexpected formal job →
  `job_unexpected_contract`; both → `no_reuse`, 4/4 RUN. Never partial-reuse
  around an ambiguous workflow contract.
- **Declared limitation (still true)**: the foundation does not claim to
  salvage independently successful surfaces from a PR run that never
  produced a valid global attestation. `PARTIAL_REUSE` in this project means
  **global tree/PR/run identity proven** while some surface evidence is
  missing/non-success; global attestation/tree identity unproven →
  `NO_REUSE` / FULL. A future per-surface attestation for "never reached the
  attestation point" cases is a separate design, not claimed by any P2 stage.

The P2-8 review operates strictly inside this model: it evaluates per-surface
evidence **under a proven global identity**, for the two audited candidate
surfaces, for the exact measured topology.

---

## 3. Evidence matrix (sealed reports are primary permanent evidence)

| Stage | PR | Sealed report | Original outcome | Scope measured |
|---|---|---|---|---|
| P2-1 | #76 | [partial_reuse_rerun_evidence_canary.md](partial_reuse_rerun_evidence_canary.md) | **OUTCOME A** — V1 already covers the failed-job rerun case | attempt/run identity; rerun semantics; composite job view; attempt-bound attestation |
| P2-2 | #77 | [distinct_head_surface_evidence_canary.md](distinct_head_surface_evidence_canary.md) | **OUTCOME B** (corrected from A) — source/selected-input delta sub-proof PASS; runtime/dependency identity UNRESOLVED for production reuse | direct-child topology; exact A→B delta; blob-manifest surface relevance; node-ID stability (canary file's 60 collected node IDs, base/A/B); V1 cross-head fail-closed |
| P2-3 | #78 | [runtime_identity_fingerprint_canary.md](runtime_identity_fingerprint_canary.md) | **OUTCOME B** (corrected from A) — live pre-install runtime fingerprint viable; PEP 517 build-isolation dependency identity outside the proof boundary | runner/Python/pip/resolver/action/ci.yml identity; resolved distribution set; probe-vs-actual 4/4; evidence-retention gap (raw install reports) |
| P2-4 | #79 | [build_isolation_identity_evidence_closure_canary.md](build_isolation_identity_evidence_closure_canary.md) | **OUTCOME B** (corrected from A) — build-isolation identity for the probe-observed set + evidence closure proven; ACTUAL isolated env closed-world identity NOT proven | PEP 517/660 build dependency set with exact wheel SHA256; build-constraint binding (positive + wrong-hash negative); offline replay 16/16; manifest duplicate-path hardening required |
| P2-5 | #80 | [closed_world_build_execution_canary.md](closed_world_build_execution_canary.md) | **OUTCOME A (narrowed)** — closed-world build execution viable; COMPLETE P2 STACK NOT CLOSED; its own A/B pair NOT reusable (runner image + interpreter drifted); new gap: runtime sdist output identity | exact hash-locked prebuild env; `--no-build-isolation --no-deps --check-build-dependencies`; `PIP_NO_INDEX=1`; `--require-hashes`; sentinel control/negative proof; distribution delta; normalized build identity A==B |
| P2-6 | #81 | [runtime_sdist_build_output_identity_canary.md](runtime_sdist_build_output_identity_canary.md) | **OUTCOME B** — two sealed gaps: (1) raw wheel byte nondeterminism; (2) retained evidence bundle closure failure | sdist → wheel → installed-bytes binding (report SHA == built SHA; RECORD valid; payload equal); cache-disabled double build; mutation negative; both gaps characterized exactly |
| P2-7 | #82 | [runtime_sdist_normalized_payload_identity_canary.md](runtime_sdist_normalized_payload_identity_canary.md) | **OUTCOME A** — normalized install-artifact identity valid; retained-artifact roundtrip closure valid; comparator defect fixed and accounted | normalized identity contract (raw mismatch 100% timestamp-attributed, unclassified=0); negative + positive timestamp-only controls; roundtrip replay CHECK_COUNT=28; cross-head RAW mismatch / NORMALIZED match / global contracts true |

All P2 stages were measurement/shadow only. Every stage's temporary
instrumentation was removed byte-for-byte; each final PR diff is exactly its
report document. Historical reports are sealed evidence and are **not
rewritten** by this review.

---

## 4. Exact P2 proof chain (one row per proof layer)

### P2-1 — ATTEMPT / RERUN EVIDENCE SEMANTICS

**Question:** Can successful surface evidence be interpreted without mixing
evidence across GitHub Actions attempts?

**Exact statement:**

- **Attempt identity**: GitHub exposes per-attempt job views
  (`/attempts/N/jobs`); the run carries `run_attempt` (measured 1 → 2 in
  P2-1). Job IDs are regenerated per attempt while execution timestamps of
  carried executions are preserved (`/attempts/2/jobs` re-lists non-rerun
  jobs with attempt-2 IDs but attempt-1 timestamps).
- **Run identity**: `run_id` is stable across attempts of the same rerun
  (measured `31520818544` on both attempts). A rerun is the same run, a new
  attempt — never a different run.
- **Rerun semantics**: `gh run rerun --failed` re-executes only failed jobs
  and previously-skipped `needs`-dependent jobs (measured: test-3.14
  re-executed; test-3.11/pyarrow24 carried from attempt 1; package — skipped
  on attempt 1 because a `needs` leg failed — newly executed on attempt 2).
- **Composite view**: `/jobs` (no filter, the view V1's contract is written
  against) equals `filter=latest` — exactly the four formal surfaces, all
  labeled with the run's current `run_attempt`, hiding per-job execution
  attempt. `/jobs?filter=all` exposes both attempt incarnations;
  distinguishing "re-executed at attempt N" from "carried" requires
  `started_at` comparison.
- **Ambiguity fail-closed**: run selection requires exact head SHA +
  `completed` + `success`; the attestation artifact is attempt-bound by name
  (`…-<head_sha>-attempt-<n>`); exactly one, non-expired, plausibly sized;
  jobs contract is exactly the four surfaces with no duplicate/extra/non-
  success job. Any ambiguity → deny.
- **What evidence may / may not be combined**: evidence from the composite
  latest view may be combined **within one run identity** because the
  attempt-bound attestation binds `run_id` + `run_attempt` and the package
  chain that creates it ran fully on the terminal attempt. Evidence may NOT
  be combined across distinct runs or across runs of different heads (that
  is P2-2's domain, closed only under the exact topology of §4/P2-2 and the
  production mapping of §7).

**Classify: CLOSED.** Same-run attempt semantics are fully representable by
V1's single-run model (measured OUTCOME A). Recorded caveat (not a gap): a
future design needing per-job execution-attempt attribution must use
`filter=all` + `started_at`; the production contract below inherits V1's
run-level fail-closed binding and does not need that attribution.

### P2-2 — DISTINCT-HEAD SURFACE EVIDENCE

**Question:** Can evidence from Head A support a direct-child Head B for an
unaffected surface?

**Exact statement:**

- **Direct-child topology**: PROVEN — B's parent == A (measured `79714d78`
  parent `4f6b49d7`).
- **Exact A→B delta**: PROVEN — one file, one comment-line replacement
  (`-1/+1` in `tests/test_audit_v03.py`).
- **Surface relevance proof**: PROVEN — every selected input blob is
  byte-identical A→B: the 37 manifest files of the sealed 3.14 surface
  (258 selectors over 37 files), the 10 files of the audited PyArrow 24
  surface, `src/**` (105 blobs), `pyproject.toml`, `ci.yml`, no repo-wide
  conftest; the canary file's 60 collected node IDs (base/A/B) are stable —
  comment deltas do not perturb collection. The ONLY differing path A→B is
  the canary file, selected by NEITHER sealed surface.
- **No arbitrary descendant reuse**: the measurement covers the
  direct-parent case only; arbitrary ancestry, cross-branch, and transitive
  chaining are explicitly out of scope (P2-2 §13 threat A, §15).
- **No merge-base / unrelated-head generalization**: the two heads' trees
  differ (proven), each attested `tested_tree_sha` equals its own head tree,
  and V1's tree-equivalence gate correctly rejects cross-head reuse — V1 is
  sound; it simply cannot express the narrower per-surface claim.
- **Runtime leg (threat K, residual at P2-2 closure)**: source-input
  equality alone does not prove the runtime a skipped Head B would have
  used; observed equality of two RUNNING runs does not carry over to a
  skipped one. **Closed by the later stages**: P2-3 (live pre-install probe
  that runs independently of the heavy job and predicted the actual install
  on 4/4 combinations), P2-4 (build-isolation identity + evidence closure),
  P2-5 (closed-world build execution), P2-6/P2-7 (runtime sdist output
  identity + normalized install-artifact identity).

**Classify: CLOSED** — source/selected-input sub-proof closed by P2-2's own
measurement; the runtime side closed by the P2-3 → P2-7 chain (§5 shows each
bridge). Closed **only** for: direct-child topology, fully enumerated delta,
selected-input equality, live runtime identity equality, the two audited
surfaces. Anything outside that contract has no evidence and must fail
closed (production consequence: RUN). §7 derives how this class maps to the
production post-merge topology.

### P2-3 — RUNTIME IDENTITY

**Question:** Can runtime/dependency drift invalidate reuse even when the
source delta is surface-irrelevant?

**Exact statement:**

- The live pre-install probe (stdlib-only, clean venv, no heavy deps)
  canonicalizes: runner (OS/arch/image/image version + sys fields), exact
  Python (implementation/version/soabi/cache_tag/pointer width), pip exact
  version, dependency contract (project name/version/`pyproject_sha256`/
  sorted requires), action contract (exact-SHA pins + `ci_yml_sha256`), and
  the **final installed external runtime distribution set** (PEP 503
  canonical names, versions, normalized URLs, artifact SHA256) resolved via
  pip dry-run report before the heavy install.
- Probe-vs-actual: the pre-install fingerprint predicted the actual heavy
  install on all four surface/run combinations (report records +
  importlib.metadata cross-check + live `pyarrow.__version__` on pyarrow24).
- Cross-head: fingerprints byte-identical A→B on both surfaces (natural
  equality); mutation comparator 32/32 fail-closed.
- **Every runtime identity field production V2 must fail closed on** (from
  the measured identity contract): runner image identity (`ImageOS`,
  `ImageVersion`, `RUNNER_OS`, `RUNNER_ARCH`, sys platform fields); exact
  Python identity (version, soabi, cache_tag, pointer width); resolver
  identity (pip exact version); dependency contract digest; action contract
  (exact-SHA pins, workflow digest); resolved distribution identity (canonical
  name/version/URL/artifact SHA256) — plus the later layers: source sdist
  identity, build-environment identity, normalized install-artifact identity
  (P2-6/P2-7). Any missing/unequal field ⇒ RUN. The P2-5 drift case proved
  the equality gate is enforced: `ImageVersion` rolled between heads and the
  cross-head comparison failed closed (`first_differing_field:runner`) — no
  reuse was produced.
- **Schema-binding limitation (recorded here, developed in §7/§12)**: the
  fingerprint is sealed in P2-3's canary evidence-bundle schema
  (`probe_summary.txt` and companions). The production V1 attestation schema
  carries no fingerprint fields. Binding the fingerprint into a production
  evidence object is new attestation behavior (GAP-P2-8-T1).

**Classify: CLOSED** for the mechanism (probe viable, predictive, and
fail-closed on drift). The two P2-3 residuals — build-isolation dependency
identity (setuptools/wheel resolution outside the v1 schema) and raw
actual-install report retention — are closed by P2-4, whose own residual
(closed-world enforcement) is closed by P2-5.

### P2-4 — BUILD ISOLATION IDENTITY + EVIDENCE CLOSURE

**Question:** Is the PEP 517/660 build environment itself identity-bound and
can its evidence be independently replayed?

**Exact statement:**

- **Build-system dependency identity**: schema v2 adds the
  `build_isolation` block — sealed `[build-system]` contract (backend
  `setuptools.build_meta`, declared `["setuptools>=68", "wheel"]`), live
  `get_requires_for_build_editable` hook result (`[]`), complete effective
  build set with materialized exact wheels (packaging 26.3, setuptools
  84.0.0, wheel 0.48.0; filename + SHA256 each), `build_constraint_sha256`,
  `all_artifacts_are_wheels`.
- **Dynamic/transitive build deps**: measured — wheel's declared dependency
  (packaging) arrives transitively; the effective set is complete as
  observed by the probe; sdists/VCS/direct URLs rejected; any unexpected
  package ⇒ INVALID (`build_package_extra:<name>`).
- **Constraint binding**: positive constrained editable install succeeded
  from the local wheelhouse (no index download visible in the retained
  top-level log segment — recorded log observation, not a resolver
  boundary); wrong-hash constraint rejected; the real heavy installs ran
  under `--build-constraint` (`BUILD_CONSTRAINT_USED=true` in every bundle;
  receipt consistency re-derived offline).
- **Verifier source retention**: each bundle carries `verifier_source.py` —
  the exact executed script copy, size+SHA256-bound in the manifest and
  checked at replay.
- **Evidence manifest semantics**: `EVIDENCE_MANIFEST.json` binds every
  retained file (size + SHA256; itself excluded); replay is offline from the
  bundle alone; duplicate-path rule flagged as hardening (see §6
  GAP-P2-4B), implemented by P2-5.
- **Replay semantics**: all four surface/run combinations replay
  `EVIDENCE_BUNDLE_REPLAY_OK` with 16/16 `REPLAY_CHECK_*` gates; a missing
  required file fails closed with an explicit summary (proven by the
  superseded first Head A run). P2-3's evidence-retention gap is closed:
  raw actual install reports are retained inside the bundles.
- **Historical distinction (required)**: P2-4's closure is about the
  **probe-observed** build dependency set and **evidence closure**; P2-6's
  later artifact-retention defect is a **different, later failure** (the
  post-manifest append in P2-6's own workflow). They must not be conflated:
  P2-4's bundles replay; P2-6's retained bundles do not (see GAP-P2-6C).

**Classify: CLOSED** for build-isolation identity of the probe-observed set
and evidence closure. P2-4's own sealed residual — the closed-world gap
(constraints constrain requested packages, not the allowlist of everything
that may enter the isolated env) — is closed by P2-5's measurement.

### P2-5 — CLOSED-WORLD BUILD EXECUTION

**Question:** Is source-build identity merely observed, or is the actual
source build constrained to the proven environment?

**Exact statement:**

- **Exact wheels**: the effective build set (`packaging==26.3`,
  `setuptools==84.0.0`, `wheel==0.48.0`) is materialized locally with exact
  SHA256; sdists/VCS/direct-URL rejected.
- **Hash locked**: `pip install --require-hashes -r
  exact_build_environment.txt` (every line `name==version
  --hash=sha256:…`) with `PIP_NO_INDEX=1` + `PIP_FIND_LINKS=<wheelhouse>`;
  probe hook re-invoked in the exact env and equal to the isolated-env probe
  (`DYNAMIC_HOOK_STABLE`).
- **`--no-build-isolation` / `--no-deps` / `--check-build-dependencies`**:
  the editable build executes with pip build-dependency management disabled
  (`--no-build-isolation --no-deps --check-build-dependencies --report … -e .`
  under `PIP_NO_INDEX=1`).
- **No hidden package-index / build-dependency channel**: the synthetic
  sentinel proof — under ordinary isolation pip auto-installs a runtime
  generated "fourth build dependency" (control branch machine-visible in the
  `-v` log); under the closed-world command the same backend's requirement
  is **rejected** while the artifact remains available in the candidate
  source (`ModuleNotFoundError`, no auto-install line). The only way a
  fourth build dependency could enter the build is if it were already in
  the exact prebuild env — which is hash-locked to the fingerprint set.
- **Distribution delta**: immediate pre/post-build inventory delta is
  exactly `{market-vault: 0.7.0}`, nothing changed/removed,
  `unexpected_distribution_count = 0` (standalone
  `PREBUILD_ENVIRONMENT.json` / `POSTBUILD_ENVIRONMENT.json`).
- **Stable path-free build identity**: `NORMALIZED_BUILD_IDENTITY_SHA256`
  equal A==B on both surfaces even though the environmental runner identity
  drifted — the build identity is environment-independent; the runtime
  identity is not, and the cross-head runtime gate correctly failed on the
  drift (`SHADOW_REUSE_CANDIDATE=false reason=runtime_identity_unequal
  => RUN`).

**Classify: CLOSED** — sub-proof OUTCOME A (narrowed). Honest record: P2-5's
own A/B pair was **not reusable** (runner drift detected and rejected) —
this is a successful fail-closed demonstration of the runtime-identity gate,
not an open gap. P2-5's newly discovered gap (runtime sdist output identity)
is closed by P2-6 + P2-7.

### P2-6 — SDIST → BUILT WHEEL → INSTALLED BYTES

**Question:** Can the resolver-selected runtime sdist be bound to the exact
wheel and the exact installed payload?

**Exact statement (measured on all four surface/head combinations):**

- **Resolver-selected sdist identity**: exactly one runtime sdist
  (`moomoo-api 10.9.6908` / `moomoo_api-10.9.6908.tar.gz` /
  `6df0370ed…`); `RUNTIME_SDIST_COUNT=1`, `RUNTIME_OTHER_COUNT=0`.
- **Source sdist SHA256**: materialized bytes verified against the resolved
  artifact hash (`SOURCE_SDIST_HASH_OK=true`).
- **Exact build output**: two cache-disabled builds from fresh extractions
  (`--no-cache-dir --no-deps --no-build-isolation
  --check-build-dependencies`, `PIP_NO_INDEX=1`); logs prove no `Using
  cached`; both raw wheel SHAs recorded.
- **PEP 427 RECORD validation**: wheel RECORD/structure valid; every member
  except RECORD listed with a secure hash, hashes recomputed; mutated wheel
  (one payload byte flipped) rejected at install.
- **pip install-report exact-wheel binding**: shadow install used the exact
  local wheel (report source URL slot identity); report wheel SHA == built
  wheel SHA (true on all four).
- **Installed RECORD validation**: installed dist located via
  importlib.metadata; every hash-bearing RECORD entry recomputed against
  real files (`record_valid=true`).
- **Wheel payload == installed payload**: `WHEEL_PAYLOAD_SHA256` ==
  `INSTALLED_PAYLOAD_SHA256` == `230368cd…` on all four.
- **Immutability**: source-built package survives remainder provisioning and
  the final install; final runtime contains no source artifact
  (`RUNTIME_INSTALL_FROM_WHEELS_ONLY=true`).

**P2-6's historical OUTCOME B, recorded accurately (never retroactively
OUTCOME A):**

- **Gap 6B — raw wheel byte nondeterminism**: two cache-disabled builds of
  the same sdist in the same closed-world environment are NOT byte-identical
  (`RAW_WHEEL_REPRODUCIBLE=false` ×4). Independent member-level analysis of
  the Head A test-3.14 build pair (recorded, not generalized to other legs):
  both wheels contain 424 members; every member's content is byte-identical
  (same set, same order, same SHA256, same sizes); the ONLY raw byte
  differences are the ZIP local-header DOS modification-time fields of the
  5 build-generated `dist-info/` members — `licenses/LICENSE`, `METADATA`,
  `WHEEL`, `top_level.txt`, `RECORD` — stamped at 2-second granularity
  (build #1 08:28:46 vs build #2 08:28:48 in Head A); 10 differing bytes in
  that pair. Classic bdist_wheel timestamp nondeterminism; no artificial
  determinism applied (protocol forbids it). The cross-leg contract is NOT
  a byte count: every raw difference must be classified, the allowed
  difference is the exact approved timestamp-only contract, and
  `unclassified = 0`. Closed by P2-7's normalized contract (below).
- **Gap 6C — retained artifact closure failure**: the four RETAINED GitHub
  artifacts fail offline replay — `EVIDENCE_BUNDLE_REPLAY_OK=false` ×4,
  `reason=failed_checks:manifest_hashes` — because a 15-byte marker
  (`REPLAY_OK=true\n`) was appended to `probe_summary.txt` AFTER manifest
  generation AND AFTER the replay copy was created. Stripping exactly those
  15 bytes restores the manifest SHA and full closure on all four; the
  append was the ONLY post-manifest mutation; every per-check except the
  closure gate re-derives true on the retained bytes. The in-job pre-upload
  replay copy PASSED (`REPLAY_OK=true` ×4). Closed by P2-7's roundtrip
  protocol (below).

**Classify: CLOSED** for the sdist→wheel→installed binding (GAP-P2-6A closed
by P2-6's own measurement, re-measured in P2-7) and **CLOSED** for its two
defects **only via P2-7** (GAP-P2-6B via the normalized identity contract;
GAP-P2-6C via the retained roundtrip protocol). P2-6's own formal decision
remains OUTCOME B, honestly sealed.

### P2-7 — NORMALIZED INSTALL-ARTIFACT IDENTITY

**Question:** Did P2-7 safely close P2-6 raw-wheel nondeterminism without
converting "payload equal ⇒ arbitrary wheel equivalent" into production
semantics?

**Exact normalized contract (all legs of all three heads measured):**

- RAW mismatch is acceptable ONLY if (all measured true on every leg):
  - both wheels structurally valid (`WHEEL_VALIDATION_1/2=true`,
    `RECORD_VALID_1/2/INSTALLED_RECORD_VALID=true`);
  - member sets identical (`PAYLOAD_ENTRY_COUNT_1 == _2 == 423`);
  - decompressed bytes identical (`WHEEL_PAYLOAD_SHA256` equal,
    `230368cd…`);
  - payload identity identical (`EVALUATED_WHEEL_PAYLOAD_MATCH=true`);
  - installed payload identical (`INSTALLED_PAYLOAD_SHA256` equal,
    `EVALUATED_INSTALLED_PAYLOAD_MATCH=true`);
  - RECORD semantics valid (`RECORD_VALID` ×3);
  - every raw/container difference classified
    (`EVALUATED_RAW_MISMATCH_NORMALIZATION_VALID=true`,
    `RAW_MISMATCH_REASON=timestamp_only_contract_ok`);
  - allowed difference == the exact approved timestamp-only contract
    (`local_or_central_timestamp` of build-generated members only);
  - unclassified == 0 (`RAW_DIFF_ATTRIBUTION` … `unclassified 0` on every
    leg);
  - all non-timestamp semantic metadata remains identity-sensitive
    (filename, CRC, sizes, compression method, flag bits, attributes,
    create/extract versions, extra fields except the parsed timestamp,
    comments, ordering, duplicate paths — any change ⇒ INVALID).
- RAW wheel bytes remain a **diagnostic** (`RAW_WHEEL_REPRODUCIBLE=false` is
  honest, never normalized away; the raw diagnostic SHAs and per-run noise
  are the ONLY excluded payload fields).
- **Negative controls** (every leg): mutated payload wheel, stale-RECORD
  wheel, content-drift wheels all rejected
  (`MUTATED_WHEEL_REJECTED_moomoo-api=true`).
- **Positive timestamp-only control** (every leg): a timestamp-only mutation
  within the allowed contract preserves the normalized identity and installs
  to the same installed payload (`POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK`
  and `POSITIVE_CONTROL_INSTALLED_PAYLOAD_MATCH=true`).
- **Comparator-fix history (required record)**:
  - initial comparator defect: it excluded the raw diagnostic dict but NOT
    the `raw_diagnostic_sha256` string, and did not strip the verdict's
    run-noise subfields (`diff_attribution`, `diff_byte_count`), which would
    have misreported the normalized cross-head verdict as false;
  - exact fix (head `614f5a5e`): one deterministic function extracts the
    identity payload; three regression tests (raw-diagnostic drift,
    attribution-noise drift, verdict-identity change — the third proves a
    genuine verdict change still breaks the normalized match);
  - retained A/B evidence re-comparison with the fixed comparator: RAW
    mismatch (`first_differing_field:exact_built_wheel_sha256`), NORMALIZED
    **true**, global identity **true** (both surfaces);
  - no measurement, bundle, or replay behavior changed.
- The comparator NEVER normalizes runner / python / resolver / build-env
  drift — any such drift breaks the strict comparison and the global
  contracts (P2-5's observed drift is the enforcement sample).
- Cross-head: RAW `false`, NORMALIZED `true` (reason=ok), global contracts
  `true` (ok) on both surfaces.

**Classify: CLOSED** — OUTCOME A (independently reviewed; report
transcription errors corrected without touching evidence).

### P2-7 — RETAINED GITHUB ARTIFACT CLOSURE

**Question:** Are the actual bytes retained by GitHub the same evidence
bytes that passed replay?

**Exact statement (measured on 3 heads × 2 surfaces = 6 legs):**

- Protocol: **FINALIZE → MANIFEST → PRE-UPLOAD REPLAY → NO MORE WRITES →
  UPLOAD → DOWNLOAD RETAINED ARTIFACT → REPLAY DOWNLOADED BYTES**, with the
  replay verdict written **outside** the manifest-bound bundle (workspace
  root receipt; never appended into `probe_summary.txt` or any
  manifest-bound file).
- Replay verdict is independent of the bundle it validates: the bundle's own
  `verifier_source.py` executes the 28 gates (`EVIDENCE_BUNDLE_REPLAY_OK`,
  `CHECK_COUNT=28`).
- Original artifact never mutated / never re-uploaded: the
  uploaded-then-downloaded artifact is the authoritative retained copy;
  download used an exact-SHA-pinned `download-artifact`.
- **Precise proven claim**: the downloaded retained bundle's manifest-bound
  content/tree identity matches the finalized uploaded bundle content/tree,
  and the downloaded retained bundle passes its own offline replay
  (`RETAINED_ARTIFACT_ROUNDTRIP_REPLAY_OK=true` ×6). Head A replay tree SHAs
  (retained copies): test-3.14 `572cd65d…`, pyarrow24 `cc9e146c…` — equal to
  the manifest-bound bundle tree SHA printed by the bundle step. Raw outer
  GitHub transport ZIP byte identity (the transport wrapper re-zips
  artifacts) was NOT measured and is NOT claimed.
- All measured surfaces/heads covered (3 heads × 2 surfaces; all four
  formal jobs success on every run).

**Classify: CLOSED.**

---

## 5. Closure reasoning — the integrated bridge

No later OUTCOME A is treated as closure by itself; each layer's status
below cites the exact invariant that closes it. The chain (each residual of
row N is closed by row N+1 with a measured invariant, not by assumption):

| Layer | Residual at its closure point | Closed by | Exact closing invariant |
|---|---|---|---|
| P2-1 attempt semantics | none for same-run reruns; cross-run assembly left to later stages | P2-1 (measured) | run_id + run_attempt + attempt-bound attestation + exact-job contract; composite latest view unambiguous under V1's model |
| P2-2 source/delta | runtime identity of a skipped Head B (threat K) | P2-3 → P2-7 chain | live pre-install probe predicts actual install (4/4); probe equality enforced fail-closed (P2-5 drift rejected) |
| P2-3 runtime identity | PEP 517 build-isolation dependency identity outside schema | P2-4 + P2-5 | probe-observed effective build set bound by exact wheels + constraint; actual build closed to that set (sentinel negative proof) |
| P2-4 build isolation | closed-world identity of the ACTUAL isolated env | P2-5 | `--no-build-isolation --no-deps --check-build-dependencies` + `PIP_NO_INDEX=1` + hash-locked exact env; sentinel auto-install rejected |
| P2-5 closed-world | runtime sdist output identity (sdist ≠ installed wheel bytes) | P2-6 + P2-7 | sdist→wheel→installed payload bound end-to-end (report SHA == built SHA == installed payload); raw mismatch 100% timestamp-attributed, unclassified=0 |
| P2-6 raw nondeterminism | `RAW_WHEEL_REPRODUCIBLE=false` | P2-7 | normalized install-artifact identity: payload + installed identity exact, negative + positive controls, raw stays diagnostic (Head A test-3.14 pair: 5 dist-info members, 10 bytes — recorded, not generalized) |
| P2-6 retained closure | retained bytes ≠ replayed bytes (manifest_hashes=false ×4) | P2-7 | FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES → UPLOAD → DOWNLOAD → REPLAY DOWNLOADED BYTES; verdict outside bundle; retained replay OK ×6 (downloaded bundle's manifest-bound content/tree identity == finalized bundle; downloaded bundle passes its own offline replay; no outer-transport-byte claim) |

Every closing invariant was measured in the closing stage's own retained
evidence. No gap is closed "because a later stage said OUTCOME A"; each row
names the concrete invariant and the stage that measured it.

**What remains genuinely NOT proven (and therefore must fail closed in
production):**

- Any head relationship other than direct-child with a fully enumerated,
  proven-irrelevant delta (arbitrary ancestry, cross-branch, transitive
  chaining, merge-base reuse): **no evidence, ⇒ RUN**.
- Any global identity field unequal at decision time (runner image,
  Python, pip, resolved distributions, source sdist, build environment,
  normalized artifact identity, final runtime): **⇒ RUN** (P2-5's drift is
  the measured enforcement sample).
- Any raw difference not 100% classified to the approved timestamp-only
  contract (`unclassified != 0`), or any semantic metadata change: **⇒
  INVALID ⇒ RUN**.
- Any runtime dependency resolved from a non-wheel source artifact whose
  exact installed artifact identity is not proven: **⇒ RUN**.
- test-3.11 and package surfaces: **not measured by the P2 stack, not
  authorized** (§8).
- The production evidence topology (which run owns which evidence object,
  how a reused surface is truthfully represented): **derived in §7; bridges
  depend on new per-surface attestation behavior — this is the OUTCOME B
  gap** (§12). Not an implementation detail; part of the security proof.

---

## 6. Gap ledger

For every row: originating PR/report · original failure mode · closing
PR/report · exact closing invariant · current status · production
consequence if the invariant is unavailable.

| Gap | Originating | Original failure mode | Closing | Exact closing invariant | Status | If invariant unavailable |
|---|---|---|---|---|---|---|
| GAP-P2-1 | P2-1 / #76 | cross-attempt evidence contamination: composite latest view hides per-job execution attempt; misattribution across attempts | P2-1 (measured OUTCOME A) | run-level selection on exact head + completed/success; exactly-one attempt-bound attestation; exact 4-surface job contract; ambiguity ⇒ deny | **CLOSED** | RUN |
| GAP-P2-2 | P2-2 / #77 | distinct-head reuse without surface-relevance proof; generalization risk | P2-2 (source sub-proof) + P2-3..7 (runtime chain) | direct-child topology; fully enumerated A→B delta; every selected input blob identical (37/10/105/1/1/0); live runtime fingerprint equality | **CLOSED** (for the exact topology + audited surfaces) | RUN |
| GAP-P2-3 | P2-2 threat K; P2-3 / #78 | runtime/dependency identity of a skipped head unproven; ranges resolved against live PyPI | P2-3 (probe) + P2-4 + P2-5 + P2-6/7 | live pre-install probe: runner/Python/pip/resolver/action/dependency-contract/resolved-distribution identity with artifact SHA256; probe-vs-actual 4/4; equality enforced fail-closed (P2-5 drift rejected) | **CLOSED** | RUN |
| GAP-P2-4 | P2-3; P2-4 / #79 | build-isolation dependency identity (setuptools/wheel) outside proof boundary | P2-4 (probe-observed set) + P2-5 (closed-world) | effective build set with exact wheel bytes/SHA256; `--build-constraint` binding (positive + wrong-hash negative); actual build under `--no-build-isolation --no-deps --check-build-dependencies`, `PIP_NO_INDEX=1`, hash-locked env; sentinel rejected | **CLOSED** | RUN |
| GAP-P2-5 | P2-4 residual; P2-5 / #80 | closed-world build execution unproven (constraint ≠ allowlist) | P2-5 (OUTCOME A narrowed) | exact prebuild env; pip build-dependency management disabled; `PIP_NO_INDEX=1`; `--require-hashes`; sentinel control/negative; distribution delta exactly `{market-vault: 0.7.0}`; path-free build identity stable | **CLOSED** | RUN |
| GAP-P2-6A | P2-5 §12; P2-6 / #81 | resolver-selected sdist not bound to exact installed wheel/payload bytes | P2-6 (measured) + P2-7 (re-measured) | sdist SHA verified; cache-disabled builds; report SHA == built SHA; RECORD valid; WHEEL_PAYLOAD == INSTALLED_PAYLOAD; mutation negative; wheels-only final runtime | **CLOSED** | RUN |
| GAP-P2-6B | P2-6 / #81 gap #1 | raw wheel byte nondeterminism (`RAW_WHEEL_REPRODUCIBLE=false`; Head A test-3.14 pair: ZIP timestamps of 5 dist-info members, 10 bytes) | P2-7 / #82 | normalized install-artifact identity: member sets identical; decompressed bytes identical; payload + installed payload identical; every raw difference 100% timestamp-attributed (`unclassified: 0`); negative + positive timestamp-only controls; raw stays diagnostic | **CLOSED** | RUN |
| GAP-P2-6C | P2-6 / #81 gap #2 | retained evidence bundle closure failure (15-byte post-manifest append; retained content failed its own manifest closure) | P2-7 / #82 | FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES → UPLOAD → DOWNLOAD RETAINED → REPLAY DOWNLOADED BYTES; verdict outside bundle; downloaded bundle's manifest-bound content/tree identity == finalized bundle; roundtrip OK ×6, CHECK_COUNT=28; original never mutated/re-uploaded | **CLOSED** | RUN / evidence not closed |
| GAP-P2-4B | P2-4 / #79 §13 | evidence manifest duplicate paths (hardening required) | P2-5 / #80 | generator raises `EVIDENCE_MANIFEST_INVALID reason=duplicate_path:<path>` before writing; verifier independently rejects duplicates; P2-5+ bundles duplicate-free | **CLOSED** | RUN |
| GAP-P2-5A | P2-5 / #80 §10 | offline runtime replay gate validates receipt + report presence, does not recompute full report-vs-resolution equality | P2-6/P2-7 + production implementation | live `verify-installed` ran on every leg (probe-vs-actual matched); replay re-derives the file-derived checks incl. install-report binding (P2-7 28 gates); full equality re-derivation in offline replay is a production-implementation requirement, not a measurement gap | **CLOSED** (measurement); production must implement full re-derivation | RUN |
| GAP-P2-5B | P2-5 / #80 §11 | receipt field timing: `postbuild_distribution_inventory` populated after the later runtime install | P2-5 (recorded) + production implementation | standalone `PREBUILD/POSTBUILD_ENVIRONMENT.json` correct and manifest-bound; offline verifier recomputes the delta from them; production receipt must bind the immediate POSTBUILD inventory | **CLOSED** (measured facts unaffected); production receipt schema must use immediate post-build inventory | RUN |
| GAP-P2-4A | P2-4 / #79 §12 | path-dependent constraint digest (safe false negatives only) | P2-5 / #80 | `NORMALIZED_BUILD_IDENTITY_SHA256` (path-free) vs `EXECUTION_BUILD_REQUIREMENTS_SHA256` (concrete file) separated; contract keys on the normalized identity | **CLOSED** | RUN |
| GAP-P2-7C | P2-7 / #82 §11 | comparator defect: `raw_diagnostic_sha256` not excluded; verdict run-noise not stripped (would misreport normalized match) | P2-7 fix head `614f5a5e` | one deterministic identity-extraction function; 3 regression tests (raw-diagnostic drift, attribution-noise drift, verdict-identity change); retained A/B re-comparison → RAW false / NORMALIZED true / global true | **CLOSED** | RUN (comparator must never normalize identity fields) |

Nothing in this ledger is closed "based solely on a later OUTCOME A": each
CLOSED row names its measured invariant and the stage whose retained
evidence establishes it.

---

## 7. Production evidence topology and provenance (the security proof)

The independent review required this section: the production evidence
topology is part of the security proof, not an implementation detail. This
section defines the concrete commit endpoints of every proof, which run owns
which evidence artifact, how the evidence is bound, and how the sealed
measurements map to a real post-merge main push.

### 7.1 Explicit symbols

| Symbol | Meaning |
|---|---|
| `P` | previous main SHA — the `before` of the push event that creates `M` |
| `M` | new squash/main SHA — the commit created by the merged PR |
| `A` | source surface-evidence head (the head whose runs own the reusable surface evidence) |
| `B` | target/final head whose decision run evaluates reuse |
| `T_B` | GitHub-tested synthetic merge tree for `B` (`tested_merge_sha`; its tree is the attestation's `tested_tree_sha`) |
| `tree(X)` | the git tree SHA of commit `X` |

### 7.2 Chosen production mapping

**`A := P` (previous main), `B := M` (new main).**

Rationale: P2-2 measured the direct-child class — a head whose parent is
proven, with a fully enumerated delta provably irrelevant to the candidate
surface. In production the only relation that is *guaranteed and enforced*
is the consecutive-main relation: GitHub's squash merge creates `M` with
exactly one parent, and V1's sealed topology gate requires exactly one
parent AND `parents[0] == before_sha` (i.e., `parent(M) == P`,
`check_topology` in `scripts/ci_post_merge_reuse.py`). The P2-2 canary pair
(canary-branch commits `4f6b49d7` → `79714d78`, direct child, one-line
delta) is a measured instance of this same class: same relation shape, same
enumeration method, same surface-relevance rule set.

The same-head salvage topology (reusing a PR run's own successful surfaces
when the PR run never produced a valid global attestation) is NOT this
mapping: the foundation's declared limitation (§2) explicitly excludes it,
and no P2 stage measured it. This document does not claim it.

### 7.3 Direct answers to the provenance questions

**(a) Which head owns the reusable surface evidence — `P`.** The evidence
object is the main-push attestation bound to `tree(P)`: the attestation
carries `tested_tree_sha` and V1's tree-equivalence gate validates
`tree(P) == tested_tree_sha` at the time `P` is main. Exactly one
attestation is selected per head (V1 exact-one select rule, sealed). Its
per-job blocks provide per-surface granularity (the attestation schema is
per-job; surfaces map to jobs 1:1).

**(b) Which head is the target of P2-2's direct-child proof.** In the sealed
measurement: the canary-head pair. In the production mapping: the pair
`(P, M)`. The pair that MUST satisfy the direct-child relation is
`(P, M)`: `parent(M) == P`, enforced by the sealed topology gate on every
main push. The delta to enumerate at decision time is `P..M` (the full
merged delta).

**(c) How the relation maps to a real post-merge main push.** GitHub's
squash merge of the PR creates `M` with exactly one parent, `P`; the push
event carries `before = P`. The V1 topology gate (sealed, production code)
requires exactly that. The merged delta `P..M` must then be fully enumerated
and proven irrelevant to each reused surface under the §9 predicate-5 rules
(which encode P2-2 §13 threats A–I).

**(d) Which run/attempt owns each evidence artifact.**

- `P`'s evidence: the main-push CI run at `P`, attempt-bound per P2-1. If
  `P`'s run was itself a V1 FULL reuse, the executed evidence is the merged
  PR-head run whose tested tree equals `tree(P)`; the artifact owned by
  `tree(P)` is still `P`'s main-push attestation (one per main push,
  exactly-one rule). The tree-equivalence proof collapses the provenance to
  `tree(P)` — see 7.4.
- `M`'s decision: the main-push CI run at `M`, attempt-bound (P2-1
  semantics: a rerun of `M`'s run is the same run identity; probe and
  evidence objects are attempt-bound).
- The live identity probe (P2-3 mechanism) must run in every main-push run
  (and every PR run) and its fingerprint must be recorded in a
  schema-bound evidence object — **this binding is new attestation
  behavior; see GAP-P2-8-T1 (§12)**.

**(e) Which attestation/evidence schema binds the reused surface.** A
V2-scoped evidence object (new schema, to be specified in the
production-contract PR): per-surface block
`{surface, verdict: reused, source: {evidence_id, head: P, tree: tree(P)},
identity: {fingerprint(P), fingerprint(M), equality: true, fields compared},
decision_run: {run_id, run_attempt}, executed: false}`.
The V1 FULL attestation schema binds only fully-executed runs (4/4 executed
on the tested tree) and is never used to represent reuse.

**(f) How a surface that was REUSED rather than EXECUTED on `B` is
truthfully represented.** By the explicit `verdict: reused` block above,
which names the source evidence object (bound to `tree(P)`), the identity
comparison performed, and the decision run. Fail-closed rules: a surface
with no valid evidence block ⇒ `no_reuse` ⇒ RUN; `verdict: reuse` requires
ALL of (i) a source evidence id that validates and binds `tree(P)`,
(ii) identity equality `P` vs `M`, (iii) delta `P..M` surface-irrelevance.

**(g) How B-level evidence is finally bound to the squash/main commit `M`.**
`M`'s run's V2 evidence object binds head `M`, `tree(M)`, `run_id`,
`run_attempt` via the same strict object-schema binding V1 uses (head + tree
fields, exact SHA format, no permissive parsing). For the main-push case the
tree binding is validated as `tested_tree == tree(M)` when the merged PR's
tested tree equals `M`'s tree (the V1 pattern), else `tree(M)` directly.

**(h) How the system avoids treating a V2 partial/subset proof as a V1 FULL
attestation.**

1. Distinct artifact naming: the V1 verifier selects ONLY
   `market-vault-full-ci-attestation-*` and strictly validates its schema;
   a V2 object can never validate as a V1 attestation (sealed, regression-
   pinned). Cross-class acceptance is impossible by construction.
2. Emission rule: the decision run NEVER uploads the V1-prefixed artifact
   when any heavy surface was reused or skipped. The V1 FULL attestation is
   emitted only when 4/4 surfaces executed on the tested tree — today's
   exact V1 semantics, preserved unchanged.
3. Any consumer that requires a V1 FULL attestation therefore forces full
   execution (no reuse). A V2 partial/subset object is never interpreted as
   proving FULL execution.

### 7.4 Provenance derivation — why this is not unsupported transitive chaining

The V1 tree-equivalence proof makes the attestation bound to `tree(P)` a
first-class evidence object regardless of whether `P`'s run executed or
reused: the attestation names `tested_tree_sha`, the gate validates
`tested_tree == tree(P)`, and the executed evidence is for the tested tree —
therefore the attestation IS evidence for `tree(P)`. The V2 gate on `M`
consumes exactly one first-order object (the attestation bound to
`tree(P)`) and never recurses into that attestation's own provenance. The
hop count is invariant at 1.

P2-2's excluded `A→B→C` chaining is a different shape: transient run
artifacts without a tree-binding collapse object, where `C`'s reuse depends
on `B`'s run whose evidence came from `A`'s run — a chain that grows with
each hop. The production mapping does not have this shape. Additionally,
every decision re-verifies the CURRENT tree delta (`P..M`) at decision time;
no manifest is carried across more than one hop.

The previous PR / tree-equivalence proof participates as the provenance
anchor: `P`'s main-push attestation + the tree-equivalence gate prove the
evidence object is bound to `tree(P)` and not to some other tree; the V2
gate requires exactly one such object for `tree(P)`.

### 7.5 What the sealed measurements covered vs. what remains to be sealed

| Step in the production sequence | Sealed mechanism? |
|---|---|
| 1. topology gate `parent(M) == P` | YES — V1 `check_topology` (production code, regression-pinned); P2-2 measured instance of the class |
| 2. exactly-one evidence object bound to `tree(P)` with per-surface blocks | YES — V1 attestation selection + tree-equivalence (production code, sealed); per-job blocks exist in the schema |
| 3. delta `P..M` fully enumerated; surface-relevance gates (predicate 5) | YES — P2-2 §9 methodology + §13 threat rules; decision-time computation |
| 4. identity mechanisms: live probe, build isolation, closed world, sdist→wheel→installed, normalized identity, retained replay | YES — P2-3..7, all measured |
| 5. source-head (`P`) fingerprint recorded in a schema-bound production evidence object | **NO — new attestation/evidence behavior (GAP-P2-8-T1)** |
| 6. truthful reused-surface representation; "never emit V1 FULL when a heavy surface was reused/skipped" as PRODUCTION behavior | **NO — new attestation semantics (GAP-P2-8-T2)** |
| 7. the full sequence exercised end-to-end on real consecutive main pushes (`P`→`M`) with production attestation objects | **NO — sealed measurements ran canary-branch heads with canary-bundle schemas (GAP-P2-8-T3)** |

Steps 1–4 are sealed. Steps 5–7 depend on new per-surface attestation /
evidence behavior that no sealed measurement exercised, and step 7's
sequence is a topology not covered by the sealed measurements as a runnable
production flow. This is the OUTCOME B gap (§12).

---

## 8. Surface-by-surface closure status

Canonical foundation surfaces: `test-3.11`, `test-3.14`, `pyarrow24`,
`package`. The deep runtime-sdist / normalized-output measurement candidates
(P2-2 → P2-7) were **`test-3.14` and `pyarrow24` only**.

| Surface | Measured in P2 stack | Input identity | Runtime/build/artifact identity | Closure status |
|---|---|---|---|---|
| test-3.14 | P2-2,3,4,5,6,7 (3.14 leg) | sealed 258-selector / 37-file manifest resolving to the sealed 294-node Python 3.14 compatibility surface (287 passed + 7 skipped); validator pinned (resolved_sha256=7561b50a…); canary file absent; canary file's 60 collected node IDs stable base/A/B | full runtime fingerprint (CPython 3.14.6), build-isolation, closed-world, sdist output, normalized identity — all measured | **MEASUREMENT CLOSED** for this surface; production reuse blocked by GAP-P2-8 (topology bridge) |
| pyarrow24 | P2-2,3,4,5,6,7 (pyarrow24 job) | 10-file audited surface (A 1 + B 3 + C 6); canary file absent; 60 collected node IDs stable base/A/B | full runtime fingerprint (CPython 3.11.15 + pyarrow==24.0.0 pin), build-isolation, closed-world, sdist output, normalized identity — all measured | **MEASUREMENT CLOSED** for this surface; production reuse blocked by GAP-P2-8 (topology bridge) |
| test-3.11 | none (blanket-suite leg; P2-3 §11 explicitly records the 3.11 blanket run as contextual observation only) | blanket suite includes every test file — the canary marker file was part of this surface | no runtime fingerprint, no sdist/normalized measurements | **NOT AUTHORIZED by P2-8** |
| package | none (package inputs `src/**` + `pyproject.toml` + ci.yml; P2 measured the MarketVault *editable* build under closed-world, not the package job's wheel/sdist + twine + fresh-venv + audit chain) | src/pyproject equality proven for the P2-2 pair only; artifact bytes shown to differ even for comment-only deltas | package job artifact identity not covered by the runtime-sdist fingerprint work | **NOT AUTHORIZED by P2-8** |

Precision note (per independent review): the "60 node IDs" claim means the
**60 collected node IDs of the canary file `tests/test_audit_v03.py` were
stable across base/A/B** (P2-2 §7) — it is NOT the Python 3.14 surface node
count. The 3.14 surface node count is the 294-node contract (287 passed + 7
skipped).

"Do not equate: 'global identity contract is understood' with 'every
surface is now reusable'." P2-8 explicitly refuses any inference from the
two audited candidates to test-3.11 or package. Those two surfaces require
their own dedicated measurement before any future per-surface contract.

---

## 9. Draft production fail-closed contract (specification only — NOT implemented)

If and only if the proof review supports it, the minimum production contract
for a candidate surface reuse is the following. A surface may return REUSE
**only if EVERY required predicate is true**. Any missing / malformed /
ambiguous / stale / mismatched predicate ⇒ **RUN**. No exception.
Predicates are evaluated in the decision run at `B := M` (§7.2) against the
evidence object bound to `tree(P)` and the live probe at `M`.

| # | Predicate | Evidence anchor |
|---|---|---|
| 1 | valid event / topology (push on main, single-parent squash, parent == `before` == `P`) | V1 foundation `check_event_shape`/`check_topology` (regression-pinned) |
| 2 | exact merged PR association (exactly one; `merge_commit_sha` == main SHA; base ref/sha exact) | V1 foundation `select_merged_pr` (regression-pinned) |
| 3 | exact attempt/run identity (completed + success run on exact head; attempt-bound attestation, exactly one) | V1 foundation + P2-1 |
| 4 | exact direct-child relation `parent(M) == P` (or another explicitly proven head relationship — none other exists) | V1 `check_topology` (production code) + P2-2 measured instance |
| 5 | exact surface relevance proof — delta `P..M` fully enumerated; every selected input blob identical for the reused surface; HARD RUN RULES for BOTH audited candidate surfaces (P2-2 §13 threats C–I, encoded without permissive interpretation): any `src/**` change ⇒ RUN; any `pyproject.toml` change ⇒ RUN; any relevant CI/control-plane change ⇒ RUN; any unknown/unclassified path ⇒ RUN; any repo-wide conftest addition/change ⇒ RUN; any change to that surface's selected test inputs ⇒ RUN; any deletion of a selected input ⇒ RUN. Preserves the surface-specific selected sets: test-3.14 = the sealed 37-file manifest (258 selectors); pyarrow24 = the sealed 10-file ci.yml surface | P2-2 §9 (blob manifests) + §13 threats C–I + §7 (node-ID stability: canary file's 60 collected node IDs, base/A/B) |
| 6 | no control-plane exclusion | V1 foundation `check_control_plane` |
| 7 | canonical job topology unambiguous (no duplicate, no unexpected formal job) | V1 foundation + P2-1 + V2 foundation reasons |
| 8 | prior surface evidence completed/success (evidence object bound to `tree(P)`, exactly one) | V1 foundation + P2-1 (composite latest view) + §7.3(a) |
| 9 | runtime global identity match (live probe, target head `M`) | P2-3 |
| 10 | runner identity match (image OS/version, RUNNER_OS/ARCH, sys fields) | P2-3/P2-4/P2-7 (P2-5 drift rejected) |
| 11 | Python identity match (exact version, soabi, cache_tag, pointer width) | P2-3/P2-4/P2-7 |
| 12 | resolver identity match (pip exact version) | P2-3 |
| 13 | resolved distribution identity match (canonical name/version/URL/artifact SHA256 set) | P2-3 probe-vs-actual 4/4 |
| 14 | runtime sdist identity match (name/version/source SHA256; none unexpected) | P2-6/P2-7 (`RUNTIME_SDIST_COUNT`/`SOURCE_SDIST_HASH_OK`) |
| 15 | source-build contract match (backend, declared requires, dynamic hook result) | P2-6 (`BUILD_CONTRACT_SOURCE`, declared/dynamic) |
| 16 | closed-world build-environment identity match (`SOURCE_BUILD_ENVIRONMENT_SHA256`, exact wheels, hash-locked, `PIP_NO_INDEX=1`) | P2-5/P2-6/P2-7 |
| 17 | normalized install-artifact identity valid (payload + installed payload + RECORD; raw mismatch fully timestamp-attributed) | P2-7 (all legs) |
| 18 | raw mismatch either absent or timestamp-only classified (allowed == approved `local_or_central_timestamp` of build-generated members only) | P2-7 |
| 19 | unclassified raw differences == 0 | P2-7 (`unclassified: 0` every leg) |
| 20 | installed payload identity match (installed bytes == built bytes == reported bytes) | P2-6/P2-7 (`WHEEL_PAYLOAD == INSTALLED_PAYLOAD`) |
| 21 | final runtime identity match (probe == actual install, live cross-check) | P2-3/P2-4/P2-6/P2-7 (`FINAL_RUNTIME_MATCH`) |
| 22 | retained evidence replay closure valid — evidence objects from BOTH heads replay: source object (bound to `tree(P)`) and `M`'s decision object (FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES → UPLOAD → DOWNLOAD → REPLAY DOWNLOADED BYTES; verdict outside bundle; downloaded bundle's manifest-bound content/tree identity == finalized bundle; downloaded bundle passes its own offline replay) | P2-7 (roundtrip ×6, CHECK_COUNT=28) |
| 23 | evidence schema/version exact | strict schema validation measured for V1 attestation; production V2 schema pins its own version, unknown version ⇒ INVALID |
| 24 | no duplicate/unexpected evidence | V1 `select_attestation_artifact`/`check_jobs` + P2-1 |
| 25 | no unknown field/shape accepted through permissive parsing | V1 strict attestation validation (exact key set); production V2 parsing must be strict-equivalent |
| 26 | source-head fingerprint binding: the evidence object bound to `tree(P)` carries `P`'s recorded runtime fingerprint in the production schema (schema-bound, versioned) — **NEW attestation behavior (GAP-P2-8-T1), not sealed** | P2-3 mechanism; binding schema unmeasured |
| 27 | truthful reused-surface representation: `M`'s decision object records `verdict: reused` with source evidence id + identity comparison + decision run; the V1 FULL attestation is NEVER emitted by a run in which any heavy surface was reused or skipped — **NEW attestation behavior (GAP-P2-8-T2), not sealed** | V1 semantics preserved; production rule unmeasured |

Drafting notes:

- Predicate 5's hard rules encode P2-2 §13 threats C–I exactly: threat C
  (src/** is a selected input for every surface), threat D (pyproject change
  invalidates package and both test legs conservatively), threat E
  (control-plane change invalidates ALL surfaces), threat F (conftest
  addition is a selected input of every test surface), threat G (change to
  any of the 37/10 selected files invalidates that surface), threat H
  (unknown/unclassified path invalidates everything), threat I (deletion
  conservatively invalidates). No permissive interpretation.
- Predicates 9–21 are LIVE predicates: the target head's runtime/build
  identity must be re-proven at decision time (the lightweight probe is the
  measured mechanism, ~10–31 s per surface, independent of the heavy
  install). The source head's recorded evidence supplies its side of each
  comparison.
- Predicates 26–27 are the unsealed bridges (GAP-P2-8). The contract as a
  whole cannot be certified until a canary seals them (§12/§13).
- Any single predicate failure ⇒ `no_reuse` for that surface with a
  specific `reason`; identity unproven ⇒ 4/4 `no_reuse` (foundation
  invariant).
- The production V2 evidence schema (field layout, versions, artifact
  naming) and its wiring into ci.yml are implementation work for the
  separate production-contract PR; the predicate list above is the
  unambiguous specification that implementation must satisfy.
- The 3.11 / package surfaces are excluded from any V2 plan until each has
  its own dedicated measurement and contract.

---

## 10. V1 / V2 interaction boundary

- **V1 semantics preserved exactly.** `POST_MERGE_REUSE=true` continues to
  mean: all four current formal FULL surfaces are covered by the verified
  exact-tree-equivalent FULL evidence path (V1 verifier unchanged,
  regression-pinned, still the only production reuse gate). P2-8 does not
  redefine that boolean; no P2 stage ever did.
- **The V1 FULL attestation (`market-vault-full-ci-attestation-*`) is NEVER
  emitted or interpreted as proving FULL execution when a heavy surface was
  actually reused/skipped.** A run that reuses any heavy surface emits only
  the V2-scoped evidence object with truthful per-surface verdicts (§7.3(h));
  any consumer requiring a V1 FULL attestation forces full execution. A V2
  partial/subset proof is never accepted as a V1 FULL attestation (distinct
  artifact class, strict V1 schema validation — sealed and regression-
  pinned).
- **Precedence (conceptual, not implemented in P2-8):**
  1. If existing V1 FULL reuse proves all four surfaces → use existing V1
     behavior.
  2. Else evaluate the future V2 per-surface evidence (per-surface plan,
     `full_reuse` / `partial_reuse` / `no_reuse`) under the §7 topology.
  3. Any V2 surface not independently proven → RUN.
- V2's production consumption requires its own separate PR (planning,
  implementation, review, canaries); until then all V2 output is foundation
  data only and no production gate parses it.

---

## 11. Explicit statements (permanent)

- **No Partial Reuse V2 activated.**
- **No production skip added.**
- **No V1 behavior changed.**
- **No workflow changed.**
- **No product code changed.**
- **No tests changed.**
- **No attestation schema changed.**
- **No release/tag mutation.**
- **No historical evidence artifact mutated** — every sealed P2 report
  remains byte-identical; P2-6's OUTCOME B (both gaps) is represented
  exactly as sealed; P2-7's OUTCOME A is not upgraded into a production
  authorization.
- **P2-8 is architecture/evidence closure only** — the permanent diff of
  this PR is exactly this document
  (`docs/partial_reuse_v2_proof_stack_closure.md`).
- **Production implementation requires a separate PR** — including the
  production V2 evidence schema, the live probe integration, per-surface
  plan wiring, the `development_protocol_v1.md` update, and any new
  canaries/mutation tests.
- **STOP BEFORE MERGE.**

---

## 12. Formal outcome

**OUTCOME B — INTEGRATED ARCHITECTURE SOUND AND MEASUREMENT CHAIN CLOSED;
PRODUCTION V2 SURFACE-EVIDENCE PROVENANCE / POST-MERGE TOPOLOGY BRIDGE
OPEN.**

The independent review's OUTCOME DISCIPLINE was applied: OUTCOME A is
retained only if EVERY required bridge is derivable from sealed P2 evidence
without a new measurement assumption; OUTCOME B is required if any bridge
depends on an unmeasured evidence semantic, new per-surface attestation
behavior, or a topology not covered by the sealed measurements.

**What the review accepted (unchanged in rev 2):**

- scope discipline (single docs file; no code/workflow/test/schema/release
  change);
- exact-head CI;
- historical P2-1..P2-7 outcome representation (including P2-6's sealed
  OUTCOME B with both gaps, P2-7's OUTCOME A);
- P2-6/P2-7 technical closure (sdist→wheel→installed binding; normalized
  identity with negative + positive controls; retained roundtrip replay
  ×6, CHECK_COUNT=28; comparator fix accounted);
- candidate-surface boundary (test-3.14 and pyarrow24 candidates only).

**What rev 2 added — the derived topology (§7):** the production mapping
`A := P`, `B := M` (consecutive main SHAs) with the direct-child relation
`parent(M) == P` enforced by the sealed V1 topology gate; the evidence
object bound to `tree(P)`; the decision run at `M`; the truthful
reused-surface representation rules; the V1-FULL-never-emitted-on-reuse
rules; and the provenance derivation showing the mapping is a single-hop
consumption of a tree-bound attestation, NOT transitive chaining.

**The remaining gap — named exactly:**

**GAP-P2-8 — PRODUCTION V2 SURFACE-EVIDENCE PROVENANCE / POST-MERGE
TOPOLOGY BRIDGE**, with three sub-bridges, each dependent on behavior no
sealed measurement exercised:

- **GAP-P2-8-T1 — source-head fingerprint binding.** The production
  evidence object bound to `tree(P)` must carry `P`'s recorded runtime
  fingerprint in a schema-bound, versioned field (P2-3's fingerprint is
  sealed only in the canary bundle schema; the production V1 attestation
  schema carries none). Requires the probe to run in every production
  run and its output to be schema-bound — new per-surface attestation
  behavior.
- **GAP-P2-8-T2 — truthful reused-surface representation.** The V1
  attestation is a 4/4-executed model. Representing "reused, not
  executed" (with source evidence id + identity comparison + decision
  run) and the rule "never emit/never accept a V2 partial/subset object
  as the V1 FULL attestation" are new attestation semantics; their
  production behavior has never been exercised.
- **GAP-P2-8-T3 — end-to-end post-merge topology sequence.** The sealed
  measurements ran canary-branch heads with canary-bundle evidence
  schemas. The full sequence — every main-push/PR run records the
  fingerprint; decision run at `M` validates topology, exactly-one
  evidence for `tree(P)`, delta `P..M`, identity equality, per-surface
  decision, truthful representation, replay closure — was never executed
  on real consecutive main pushes with production attestation objects.

**Why not OUTCOME C:** no evidence incompatibility or contamination — every
sealed fact and every measured invariant is intact; the comparator defect
was fixed with documented regression tests and retained re-comparison; the
gap is a scope-boundary gap (production evidence topology), not a defect in
the measured chain. Corrected outcomes inside stages (P2-2/3/4 A→B) were
independently reviewed and accepted.

**Why not OUTCOME A:** per the review's discipline, OUTCOME A would require
every bridge to be derivable from sealed evidence. T1 and T2 depend on new
per-surface attestation behavior, and T3 is a topology not covered by the
sealed measurements as a runnable production flow. Choosing A "because the
future implementation could probably be written safely" is explicitly
forbidden and is not chosen.

**Therefore:** the integrated review certifies the measurement chain (the
identity mechanisms and the direct-child source-input semantics are
measured, sound, and fail-closed) for the two audited candidate surfaces,
but a fail-closed production Partial Reuse V2 contract is NOT yet certified.
No production reuse is authorized.

---

## 13. Next-step recommendation (exact)

1. **Independent review** of this rev-2 document and its single-file diff.
   **STOP BEFORE MERGE** until explicitly authorized.
2. **The exact next canary needed — P2-9: production-topology shadow
   canary (measurement only, no gating).** Run on a real consecutive
   main-push pair (`P` → `M`) after any future merge:
   - every main-push/PR run records the live probe fingerprint in a
     schema-bound evidence object (shadow, unused by any gate);
   - in the `M` decision run (shadow): evidence binding to `tree(P)`,
     `parent(M) == P`, delta `P..M` enumeration, probe identity equality
     `P` vs `M`, per-surface fail-closed decision, truthful
     `verdict: reused` representation;
   - negative control: a V2 partial/subset object is never emitted as
     and never accepted as the V1 FULL attestation (artifact-class
     separation exercised on a real run);
   - pass criterion: shadow verdict consistent on at least one real pair
     with at least one candidate surface REUSE and one RUN; any
     inconsistency ⇒ INVALID ⇒ no contract.
   This closes GAP-P2-8-T1/T2/T3 in that order.
3. After P2-9 closes: **production-contract implementation PR** (separate):
   - implement the §9 contract with the production V2 evidence schema and
     strict validation (schema version, exact key sets, no permissive
     parsing);
   - integrate the live pre-install runtime/build-identity probe for the
     two candidate surfaces (fail-closed: INVALID never "unknown");
   - wire the per-surface plan (foundation `build_surface_reuse_plan`) under
     the proven global identity; any unproven surface ⇒ RUN;
   - implement retained-evidence replay closure per the P2-7 protocol;
   - implement the offline-replay hardening items from the ledger (full
     report-vs-resolution equality re-derivation; immediate POSTBUILD
     receipt binding);
   - update `docs/development_protocol_v1.md` (new section replacing/next
     to §4.9) in that PR — not here;
   - its own control-plane tier and canaries per the rollout sequence §4.9
     (this PR's main push must not be reused — it is docs-scope anyway).
4. **Dedicated measurement for test-3.11 and package** before any future
   per-surface contract for those surfaces — P2-8 grants them nothing.

---

## 14. Final state assertions

- Frozen base verified exactly: `8aeef5fb99f5abed06b25db622cb17cf9afd5fa3`
  (HEAD == origin/main, clean tree).
- Rev history: rev 1 (this PR's first commit) was reviewed independently;
  the review accepted scope/CI/history/closure/boundary and required the
  topology proof, outcome discipline, predicate-5 precision, evidence-
  precision, and retained-wording corrections; rev 2 (this commit) applies
  them. The corrected formal outcome is OUTCOME B (§12) — returned
  honestly, not forced.
- Permanent diff: exactly one file —
  `docs/partial_reuse_v2_proof_stack_closure.md`.
- No historical evidence report changed; no code/workflow/test/schema/
  release change.
- Local gates on the final head: `git diff --check` clean;
  `scripts/check_repo_hygiene.py` pass; `scripts/check_release.py`
  `RELEASE_CHECK_OK version=0.7.0`.
- Expected exact-head CI: `tier=docs_fast reason=all_changes_in_docs_scope
  changed_files=1 components=none full_matrix_required=false`, 4/4 formal
  jobs SUCCESS, `RELEASE_CHECK_OK version=0.7.0`, 0 artifacts. Final report
  is issued only after the exact final head SHA reaches terminal state.

---

**READY FOR INDEPENDENT REVIEW**
**STOP BEFORE MERGE**
