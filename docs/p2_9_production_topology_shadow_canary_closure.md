# P2-9 Production-Topology Shadow Canary Closure

**Status: COMPLETE**

The P2-9 production-topology shadow canary measured, end to end and on the
real production topology, whether a single-file delta between a formally
verified source PR and a production target main push could be safely
resolved per surface (REUSE or RUN) by the temporary P2-9 shadow machinery,
using the existing V1 FULL attestation / exact-tree provenance path as a
source-proof anchor. The canary is now formally closed.

**No activation:** Partial Reuse V2 remains **OFF**. Nothing in this
experiment activates V2. The V2 foundation remains present in the tree but
is not wired into any production `if:` guard.

## 1. Historical Phase S — source instrumentation (PRs #84, #85, #86)

- **PR #84** — source instrumentation setup; the first merged main push
  after the source PR failed on plumbing.
- **PR #85** — `mkdir` plumbing repair; main CI succeeded but the
  source-locator download-layout positive path remained broken.
- **PR #86** — source-locator layout repair; Phase S formally **COMPLETE**.

Formal Phase-S source main `P`:

```
a275008388ee0af0dd528fb6deacaaa76cd2e912
```

## 2. Phase-T attempt #1 — FAILED-CLOSED (PR #87)

- Target main `M`:
  `27d4bbe8474dbef643f6314110661544baf0ce93`
- Exact post-merge run: `31959890117`
- Result: **FAILED-CLOSED / NOT COMPLETE**
  - test-3.14: `RUN` due `runtime_mismatch`
  - pyarrow24: `RUN` due `runtime_mismatch`
  - False reuse: **NONE** (the system failed closed; nothing was reused)
- Root cause: the cross-run runtime comparator overbound
  known-allowed timestamp-only raw build diagnostics.

## 3. Comparator repair (PR #88)

- Approved PR head: `83c91e2894fe68e714e8547fb333fba01a51f45f`
- Repair FULL run: `31961867996` (attempt 1)
- Formal repaired baseline `R`:
  `761b34c19a82f3bd6ddf41889529a8b5ac700f87`
- `R` tree: `63adbbd1b626ba0102913b7f7c07b3fef5bd757a`
- `R` post-merge run: `31979283086` (completed / success)

## 4. Phase-T2 — formal production target (PR #89)

- Approved PR head: `5e1111a598b7ffaf6dce415b7f068553f42a237f`
- PR FULL run: `31980154924` (attempt 1, completed / success)
- PR tested merge: `bcb2cbf153d2f1c25dab4ccc7f8239c0daa056d9`
- PR tested tree: `d61dd815603dcc9d60574152812b05e616ffee5b`
- Formal production target `T`:
  `67b65ba9e5d60c8f67da4f4ca6d69ba280791ab6`
- `T` parent: `761b34c19a82f3bd6ddf41889529a8b5ac700f87` (= `R`)
- `T` tree: `d61dd815603dcc9d60574152812b05e616ffee5b` (= PR tested tree)
- Exact production push: `31984989095` (attempt 1, completed / success,
  **4/4 jobs SUCCESS**)

### 4.1 Production V1 reuse decision

- `POST_MERGE_REUSE=true`
- `reason=verified_full_pr_tree_equivalence`

### 4.2 Production source locator (resolved by the shadow aggregator)

- Source PR: `88`
- Source head: `83c91e2894fe68e714e8547fb333fba01a51f45f`
- Source run: `31961867996`
- Source attempt: `1`
- Source tested tree: `63adbbd1b626ba0102913b7f7c07b3fef5bd757a`
- Source V1 attestation artifact: `9267509647`
- V1 artifact ZIP SHA256:
  `aacb179df29cc6960ce262277470a6788bd13cbd2a37252ee84733765fc3e166`
- Attestation JSON SHA256:
  `0e72970a9241fabe573dbb38e6d17d6e00bb62f8a45eac38f3705a1e8f5b1383`

### 4.3 Exact production delta

```
count=1
tests/test_calendar_v03.py
```

### 4.4 Production semantic result

- test-3.14:
  - `selected_input_verdict=affected`
  - `global_runtime_match=true`
  - `target_verdict=run`
  - `target_reason=run:delta_affected`
- pyarrow24:
  - `selected_input_verdict=unaffected`
  - `global_runtime_match=true`
  - `target_verdict=reused`
  - `target_reason=reused:all_predicates_valid`
- `TARGET_EVIDENCE_OK=true`

### 4.5 Target probe artifacts (exact current-run, current-attempt)

- test-3.14: ID `9273494428`,
  SHA256 `655c93ba9808835188d80f499e2069905d440c38c97e65a3b953da53614d2310`
- pyarrow24: ID `9273502171`,
  SHA256 `0a4baa927439363ac98f7dd784e878bef38dac9d1b42f81bd3cab25255962ecf`

### 4.6 Final target artifacts (per-surface shadow evidence)

- test-3.14: ID `9273513956`,
  SHA256 `76d76f4f5c948982a711094ef91ee51cbd3254d8c27412162d8f4b9a20552404`
  - `CHECK_COUNT=18`
  - `ROUNDTRIP_RECEIPT=OK`
  - `REPLAY_BUNDLE_TREE_SHA256=f8cb9c249fee299021d9e874ffd8301e02f12e28dcdea46bc8d90b4c42e80f2d`
  - manifest SHA256: `3edb0b0333e920b9aac3687d5a20d53182667b0f1d17e5e28e93ec0ba046ebf1`
- pyarrow24: ID `9273514281`,
  SHA256 `03f8f329d1d177b69009c2680d7676d519ceeb7f97f3c8b38e875ecdf5816dc9`
  - `CHECK_COUNT=18`
  - `ROUNDTRIP_RECEIPT=OK`
  - `REPLAY_BUNDLE_TREE_SHA256=ec199c59b5c80273c1eb8a4b97ca7c0697e39448d77ed3fbb1b2c0147a921251`
  - manifest SHA256: `9d19a16b453a35212150e9cbd21a70171dff62c87e3e8f6e9dc6783663ec3671`

## 5. Final Phase-T result

```
P2_9_PHASE_T_COMPLETE=true
PRODUCTION_TOPOLOGY_SHADOW_CANARY=PASS
```

- Historical attempt #1 (PR #87): **FAILED-CLOSED**, no false reuse.
- Phase-T2 (PR #89): **PASS**.
- Phase C: this report plus removal of all temporary P2-9 instrumentation
  (script, test suite, workflow steps, calendar marker).
- `V2 ACTIVATION: OFF`

## 6. Relationship to the sealed P2-8 review (#83)

- **PR #83's OUTCOME B report (`docs/partial_reuse_v2_proof_stack_closure.md`)
  is NOT rewritten.** It is sealed historical review truth at that commit:
  the production V2 surface-evidence bridge was **OPEN** in #83.
- The later P2-9 experiment **closed that specific production-topology
  bridge**: the temporary P2-9 shadow evaluator resolved the controlled
  single-file delta per surface — RUN for the affected test-3.14 surface
  and REUSED for the unaffected pyarrow24 surface — while the independent
  V1 gate simultaneously proved its separate global FULL exact-tree reuse
  contract and supplied attestation/provenance evidence used by the source
  proof. The separation is explicit:

  - **V1**: global FULL exact-tree reuse.
  - **P2-9 shadow**: per-surface production-topology measurement.
  - **V2**: future production partial-reuse mechanism, still **OFF**.
- **Successful shadow evidence does NOT itself authorize activation.** The
  canary is measurement-only; its PASS closes the specific P2-9
  production-topology / per-surface evidence bridge left OPEN by PR #83.
  It does not mean that V1 performs per-surface reuse, and it does not
  activate V2.
- **V2 activation requires a separate, explicitly reviewed production PR**
  with its own exact-head FULL CI and independent review. Nothing in this
  canary, its reports, or its closure constitutes that review.
- P2-9 artifacts are retained by GitHub only according to the configured
  artifact retention policy (30 days at upload time) and are therefore
  ephemeral. This permanent report preserves the exact artifact IDs,
  digests, tree SHAs, and semantic results above for the historical record.
