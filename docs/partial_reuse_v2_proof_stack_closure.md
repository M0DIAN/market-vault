# P2-8 Partial Reuse V2 Proof-Stack Closure Review (PR #83)

**Status: ARCHITECTURE / EVIDENCE CLOSURE REVIEW ONLY — OUTCOME A (PROOF STACK
CLOSED FOR AUDITED CANDIDATE SURFACES ONLY).**

**No Partial Reuse V2 activation. No production skip. No workflow gating
change. No production code change. No test logic change. No attestation
schema change. No release/tag mutation.**

This document is the permanent integrated proof review over the sealed P2
evidence stack (PRs #76–#82). It answers one question:

> Can the existing measured evidence support a fail-closed production
> Partial Reuse V2 contract for the audited candidate surfaces?

The answer was not assumed. It is derived per proof layer below, with every
logical bridge shown. The formal result is exactly one of OUTCOME A /
OUTCOME B / OUTCOME C; the result of this review is **OUTCOME A — PROOF
STACK CLOSED FOR AUDITED CANDIDATE SURFACES ONLY** (§12), which authorizes
**no** production reuse and activates **nothing**.

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
| P2-2 | #77 | [distinct_head_surface_evidence_canary.md](distinct_head_surface_evidence_canary.md) | **OUTCOME B** (corrected from A) — source/selected-input delta sub-proof PASS; runtime/dependency identity UNRESOLVED for production reuse | direct-child topology; exact A→B delta; blob-manifest surface relevance; node-ID stability; V1 cross-head fail-closed |
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
  is P2-2's domain, closed only under the exact topology of §4/P2-2).

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
  byte-identical A→B: the 37 manifest files of the sealed 3.14 surface, the
  10 files of the audited PyArrow 24 surface, `src/**` (105 blobs),
  `pyproject.toml`, `ci.yml`, no repo-wide conftest; 60 node IDs stable
  across base/A/B (comment deltas do not perturb collection).
- **No arbitrary descendant reuse**: the measurement covers the
  direct-parent case only; arbitrary ancestry, cross-branch, and transitive
  chaining (A→B→C) are explicitly out of scope and receive no evidence.
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
closed (production consequence: RUN).

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
  (`RAW_WHEEL_REPRODUCIBLE=false` ×4). Independent member-level analysis:
  424/424 members content-identical; the ONLY raw differences are the ZIP
  local-header DOS modification-time fields of the 5 build-generated
  `dist-info/` members (10 differing bytes in the measured pair) — classic
  bdist_wheel timestamp nondeterminism, no artificial determinism applied.
  Content is fully deterministic (payload digest stable across heads AND
  surfaces). Closed by P2-7's normalized contract (below).
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
- Retained roundtrip replay true on all six legs
  (`RETAINED_ARTIFACT_ROUNDTRIP_REPLAY_OK=true`); retained replay tree SHA
  equals the manifest-bound bundle tree SHA (Head A recorded: test-3.14
  `572cd65d…`, pyarrow24 `cc9e146c…`).
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
| P2-6 raw nondeterminism | `RAW_WHEEL_REPRODUCIBLE=false` | P2-7 | normalized install-artifact identity: payload + installed identity exact, negative + positive controls, raw stays diagnostic |
| P2-6 retained closure | retained bytes ≠ replayed bytes (manifest_hashes=false ×4) | P2-7 | FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES → UPLOAD → DOWNLOAD → REPLAY DOWNLOADED BYTES; verdict outside bundle; roundtrip true ×6 |

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
- A production-consumable V2 evidence schema and its wiring into ci.yml:
  **not implemented — that is the separate production-contract PR**, whose
  contract this document specifies (§9).

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
| GAP-P2-6B | P2-6 / #81 gap #1 | raw wheel byte nondeterminism (`RAW_WHEEL_REPRODUCIBLE=false`; ZIP timestamps of 5 dist-info members) | P2-7 / #82 | normalized install-artifact identity: member sets identical; decompressed bytes identical; payload + installed payload identical; every raw difference 100% timestamp-attributed (`unclassified: 0`); negative + positive timestamp-only controls; raw stays diagnostic | **CLOSED** | RUN |
| GAP-P2-6C | P2-6 / #81 gap #2 | retained evidence bundle closure failure (15-byte post-manifest append; uploaded bytes ≠ replayed bytes) | P2-7 / #82 | FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES → UPLOAD → DOWNLOAD RETAINED → REPLAY DOWNLOADED BYTES; verdict outside bundle; roundtrip true ×6, CHECK_COUNT=28; original never mutated/re-uploaded | **CLOSED** | RUN / evidence not closed |
| GAP-P2-4B | P2-4 / #79 §13 | evidence manifest duplicate paths (hardening required) | P2-5 / #80 | generator raises `EVIDENCE_MANIFEST_INVALID reason=duplicate_path:<path>` before writing; verifier independently rejects duplicates; P2-5+ bundles duplicate-free | **CLOSED** | RUN |
| GAP-P2-5A | P2-5 / #80 §10 | offline runtime replay gate validates receipt + report presence, does not recompute full report-vs-resolution equality | P2-6/P2-7 + production implementation | live `verify-installed` ran on every leg (probe-vs-actual matched); replay re-derives the file-derived checks incl. install-report binding (P2-7 28 gates); full equality re-derivation in offline replay is a production-implementation requirement, not a measurement gap | **CLOSED** (measurement); production must implement full re-derivation | RUN |
| GAP-P2-5B | P2-5 / #80 §11 | receipt field timing: `postbuild_distribution_inventory` populated after the later runtime install | P2-5 (recorded) + production implementation | standalone `PREBUILD/POSTBUILD_ENVIRONMENT.json` correct and manifest-bound; offline verifier recomputes the delta from them; production receipt must bind the immediate POSTBUILD inventory | **CLOSED** (measured facts unaffected); production receipt schema must use immediate post-build inventory | RUN |
| GAP-P2-4A | P2-4 / #79 §12 | path-dependent constraint digest (safe false negatives only) | P2-5 / #80 | `NORMALIZED_BUILD_IDENTITY_SHA256` (path-free) vs `EXECUTION_BUILD_REQUIREMENTS_SHA256` (concrete file) separated; contract keys on the normalized identity | **CLOSED** | RUN |
| GAP-P2-7C | P2-7 / #82 §11 | comparator defect: `raw_diagnostic_sha256` not excluded; verdict run-noise not stripped (would misreport normalized match) | P2-7 fix head `614f5a5e` | one deterministic identity-extraction function; 3 regression tests (raw-diagnostic drift, attribution-noise drift, verdict-identity change); retained A/B re-comparison → RAW false / NORMALIZED true / global true | **CLOSED** | RUN (comparator must never normalize identity fields) |

Nothing in this ledger is closed "based solely on a later OUTCOME A": each
CLOSED row names its measured invariant and the stage whose retained
evidence establishes it.

---

## 7. P2 foundation status (summary)

- `scripts/ci_post_merge_reuse.py` V2 foundation: unchanged, unactivated,
  regression-pinned (identity-false invariant; canonical surface model;
  duplicate/unexpected-job fail-closed; V1 contract non-collision).
- `tests/test_ci_post_merge_reuse.py`: unchanged (this review adds no test).
- `docs/development_protocol_v1.md` §4.9: unchanged; the later
  production-contract implementation (when approved) updates the protocol in
  its own PR — not this one.

---

## 8. Surface-by-surface closure status

Canonical foundation surfaces: `test-3.11`, `test-3.14`, `pyarrow24`,
`package`. The deep runtime-sdist / normalized-output measurement candidates
(P2-2 → P2-7) were **`test-3.14` and `pyarrow24` only**.

| Surface | Measured in P2 stack | Input identity | Runtime/build/artifact identity | Closure status |
|---|---|---|---|---|
| test-3.14 | P2-2,3,4,5,6,7 (3.14 leg) | sealed 258-node/37-file manifest; validator + node-ID stability | full runtime fingerprint (CPython 3.14.6), build-isolation, closed-world, sdist output, normalized identity — all measured | **CANDIDATE — PROOF STACK CLOSED** (under the §9 contract) |
| pyarrow24 | P2-2,3,4,5,6,7 (pyarrow24 job) | 10-file audited surface (A 1 + B 3 + C 6) | full runtime fingerprint (CPython 3.11.15 + pyarrow==24.0.0 pin), build-isolation, closed-world, sdist output, normalized identity — all measured | **CANDIDATE — PROOF STACK CLOSED** (under the §9 contract) |
| test-3.11 | none (blanket-suite leg; P2-3 §11 explicitly records the 3.11 blanket run as contextual observation only) | blanket suite includes every test file — the canary marker file was part of this surface | no runtime fingerprint, no sdist/normalized measurements | **NOT AUTHORIZED by P2-8** |
| package | none (package inputs `src/**` + `pyproject.toml` + ci.yml; P2 measured the MarketVault *editable* build under closed-world, not the package job's wheel/sdist + twine + fresh-venv + audit chain) | src/pyproject equality proven for the P2-2 pair only; artifact bytes shown to differ even for comment-only deltas | package job artifact identity not covered by the runtime-sdist fingerprint work | **NOT AUTHORIZED by P2-8** |

"Do not equate: 'global identity contract is understood' with 'every
surface is now reusable'." P2-8 explicitly refuses any inference from the
two audited candidates to test-3.11 or package. Those two surfaces require
their own dedicated measurement before any future per-surface contract.

---

## 9. Draft production fail-closed contract (specification only — NOT implemented)

If and only if the proof review supports it (it does, for the two audited
candidate surfaces), the minimum production contract for a candidate surface
reuse is the following. A surface may return REUSE **only if EVERY required
predicate is true**. Any missing / malformed / ambiguous / stale / mismatched
predicate ⇒ **RUN**. No exception.

| # | Predicate | Evidence anchor |
|---|---|---|
| 1 | valid event / topology (push on main, single-parent squash, parent == `event.before`) | V1 foundation `check_event_shape`/`check_topology` (regression-pinned) |
| 2 | exact merged PR association (exactly one; `merge_commit_sha` == main SHA; base ref/sha exact) | V1 foundation `select_merged_pr` (regression-pinned) |
| 3 | exact attempt/run identity (completed + success run on exact head; attempt-bound attestation, exactly one) | V1 foundation + P2-1 |
| 4 | exact direct-child or other explicitly proven head relationship | P2-2 (direct-child measured; nothing else ever proven) |
| 5 | exact surface relevance proof (delta fully enumerated; every selected input blob identical — 3.14: 37 manifest files; pyarrow24: 10 files; plus `src/**`? per surface, `pyproject.toml`, ci.yml, no conftest; node-ID stability) | P2-2 §9 (blob manifests) |
| 6 | no control-plane exclusion | V1 foundation `check_control_plane` |
| 7 | canonical job topology unambiguous (no duplicate, no unexpected formal job) | V1 foundation + P2-1 + V2 foundation reasons |
| 8 | prior surface evidence completed/success | V1 foundation + P2-1 (composite latest view) |
| 9 | runtime global identity match (live probe, target head) | P2-3 |
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
| 22 | retained evidence replay closure valid (FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES → UPLOAD → DOWNLOAD → REPLAY DOWNLOADED BYTES; verdict outside bundle) | P2-7 (roundtrip ×6, CHECK_COUNT=28) |
| 23 | evidence schema/version exact | strict schema validation measured for V1 attestation; production V2 schema pins its own version, unknown version ⇒ INVALID |
| 24 | no duplicate/unexpected evidence | V1 `select_attestation_artifact`/`check_jobs` + P2-1 |
| 25 | no unknown field/shape accepted through permissive parsing | V1 strict attestation validation (exact key set); production V2 parsing must be strict-equivalent |

Drafting notes:

- Predicate 5 must be evaluated per surface with the surface's own selected-
  input set (test-3.14 and pyarrow24 have different input sets; `src/**` /
  `pyproject.toml` / ci.yml participate in the *global* delta check, and
  changes there invalidate package and the 3.11 blanket surface by the
  surface-boundary rules, even though those surfaces themselves are not
  reuse candidates).
- Predicates 9–21 are LIVE predicates: the target head's runtime/build
  identity must be re-proven at decision time (the lightweight probe is the
  measured mechanism, ~10–31 s per surface, independent of the heavy
  install). The source head's recorded evidence supplies its side of each
  comparison.
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
- **Precedence (conceptual, not implemented in P2-8):**
  1. If existing V1 FULL reuse proves all four surfaces → use existing V1
     behavior.
  2. Else evaluate the future V2 per-surface evidence (per-surface plan,
     `full_reuse` / `partial_reuse` / `no_reuse`).
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
  this PR is exactly this document (`docs/partial_reuse_v2_proof_stack_closure.md`).
- **Production implementation requires a separate PR** — including the
  production V2 evidence schema, the live probe integration, per-surface
  plan wiring, the `development_protocol_v1.md` update, and any new
  canaries/mutation tests.
- **STOP BEFORE MERGE.**

---

## 12. Formal outcome

**OUTCOME A — PROOF STACK CLOSED FOR AUDITED CANDIDATE SURFACES ONLY
(`test-3.14`, `pyarrow24`).**

Every OUTCOME A condition is satisfied:

- every proof gap required for the audited candidate surfaces has an exact
  logical closure (the §5 chain; each bridge is a measured invariant);
- no gap is closed merely by assumption (each closing invariant is named and
  measured in the closing stage's retained evidence);
- P2-6's historical OUTCOME B remains honestly represented (both gaps
  sealed, never retroactively A);
- P2-7 supplies valid closure for its two gaps (normalized identity with
  negative + positive controls; retained roundtrip replay ×6,
  CHECK_COUNT=28);
- retained evidence closure is valid (downloaded bytes == uploaded bytes;
  replay of downloaded bytes true);
- the comparator defect is accounted for and fixed evidence supports the
  final interpretation (defect → deterministic fix → 3 regression tests →
  retained A/B re-comparison true);
- no global identity field that should remain sensitive is normalized away
  (only per-run diagnostics and run-noise are excluded; runner/python/
  resolver/build-env drift always breaks the match — enforced by the P2-5
  drift case);
- production fail-closed behavior is specified unambiguously (§9 — any
  predicate missing/mismatched ⇒ RUN, no exception);
- no evidence supports an unsafe generalization (evidence is bounded to
  direct-child + exact-delta + live-identity equality + two surfaces; no
  evidence for arbitrary ancestry, cross-branch, transitive chaining,
  test-3.11, or package).

OUTCOME A here does **NOT** mean:

- Partial Reuse V2 is activated (it is not; no production skip exists);
- every surface is reusable (test-3.11 and package are NOT authorized);
- any head relationship other than the proven direct-child + exact-delta
  topology is reusable (nothing else has evidence);
- a production V2 implementation exists (the separate production-contract
  PR is the next step, not this PR).

---

## 13. Next-step recommendation (exact)

1. **Independent review** of this document and its single-file diff (the
   review gate per the development playbook §1.8). **STOP BEFORE MERGE**
   until explicitly authorized.
2. After merge: **production-contract implementation PR** (separate):
   - implement the §9 contract with the production V2 evidence schema and
     strict validation (schema version, exact key sets, no permissive
     parsing);
   - integrate the live pre-install runtime/build-identity probe for the two
     candidate surfaces (fail-closed: INVALID never "unknown");
   - wire the per-surface plan (foundation `build_surface_reuse_plan`) under
     the proven global identity; any unproven surface ⇒ RUN;
   - implement retained-evidence replay closure per the P2-7 protocol
     (FINALIZE → MANIFEST → REPLAY EXACT FINAL → NO FURTHER WRITES →
     UPLOAD → DOWNLOAD → REPLAY DOWNLOADED BYTES; verdict outside the
     bundle);
   - implement the offline-replay hardening items from the ledger
     (full report-vs-resolution equality re-derivation; immediate POSTBUILD
     receipt binding);
   - update `docs/development_protocol_v1.md` (new section replacing/next to
     §4.9) in that PR — not here;
   - its own control-plane tier and canaries per the rollout sequence §4.9
     (this PR's main push must not be reused — it is docs-scope anyway).
3. **Dedicated measurement for test-3.11 and package** before any future
   per-surface contract for those surfaces — P2-8 grants them nothing.

---

## 14. Final state assertions

- Frozen base verified exactly: `8aeef5fb99f5abed06b25db622cb17cf9afd5fa3`
  (HEAD == origin/main, clean tree).
- Permanent diff: exactly one file — `docs/partial_reuse_v2_proof_stack_closure.md`.
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
