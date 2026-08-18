# PR-Head Reuse Phase-0B Product-Workload Decision

**Status: OUTCOME C**
**Decision: DO NOT IMPLEMENT PR-HEAD REUSE**
**PR_HEAD_REUSE_AUTHORIZED=false**
**Mode: historical/product-workload measurement only**
**Production mutation: none**

This document permanently records the independently accepted architectural
decision: PR-head / PR-iteration reuse is **NOT implemented** under the
currently measured MarketVault product workload. The decision is
value-based, deliberately revisitable only under the criteria in the
"Reopen criteria" section.

**No production semantics change:** this decision record changes nothing
executable. It does not implement PR-head reuse, does not change V1, does
not change workflow gating, does not change tests, does not restore any
instrumentation, and does not alter any merge gate.

---

## 1. Formal decision base

```
D =
2d1aa18877b3aa622a33ecaee4b8e954831f01a0

tree(D) =
3a1e45e8c902d053f8122e557fef5b84a3febdaa
```

`D` is the freshly fetched `origin/main` at decision time (2026-08-18),
worktree clean, fetch verified. All classification replays were executed
with the CURRENT `scripts/ci_risk_tier.py` and `ci/components.toml`
semantics against historical git objects.

## 2. Architecture history

Recorded accurately, in sequence:

- **Post-merge V1**: production FULL exact-tree reuse exists and remains
  ACTIVE. V1 binds `run_id`, `run_attempt`, `head_sha`, `tested_merge_sha`,
  `tested_tree_sha`, and the artifact name
  `market-vault-full-ci-attestation-<head>-attempt-<attempt>`.
- **P2 / P2-9**: proved sophisticated cross-head / runtime / provenance /
  evidence techniques in the post-merge production topology
  (measurement-only; Phase C removed all temporary instrumentation).
- **V2-A0**: **OUTCOME C** — post-merge Partial Reuse V2 deliberately NOT
  activated (`POST_MERGE_V2_ACTIVATION=DO_NOT_ACTIVATE`).
- **Phase 0**: the initial PR-head reuse audit found a real natural
  repeated-work example — especially PR #90 (docs-only delta, both heads
  FULL-run) — but the sample was dominated by CI / P2 / control-plane
  work. **Independent review changed the preliminary Phase-0 result to
  OUTCOME B** because representative product workload had not yet been
  measured.
- **Phase 0B**: measured representative product / feature PR history.
  Final independently accepted result: **OUTCOME C** (this record).

## 3. Two datasets, not one

Commit-chain facts and observed remote PR-head facts are **distinct
evidence classes** and must never be silently mixed.

### A. COMMIT-CHAIN DATASET

The 33 selected product PRs contain:

```
COMMIT_CHAIN_NODES = 79
COMMIT_CHAIN_TRANSITIONS = 46
```

These are exact git commit-chain facts (merge-base-correct branch chains,
all direct-parent).

### B. OBSERVED REMOTE PR-HEAD DATASET

A commit may only count as a proven remote PR head if there is evidence
that GitHub actually observed it as a PR head, such as:

- a retained `pull_request` workflow run; or
- another direct GitHub remote/event fact proving that exact SHA was an
  exposed PR head.

PR #42 commit `7b3e0b67ba9bde551cd280480d268a0034a51a06` must NOT be
presented as a proven remote PR head merely because it is in the commit
chain. Facts:

- its direct child `94bd25fe9632683484475bc5d90ec93a0e4ca86f` has the
  SAME author/committer timestamp;
- `7b3e0b6` has no retained PR workflow run;
- `94bd25f` does have the PR run;
- this is consistent with both commits being pushed together and only the
  tip being observed by Actions.

Classification:

```
7b3e0b6 = UNPROVEN_AS_REMOTE_PR_HEAD
```

(Reclassifiable only if additional direct remote/event evidence is found.)

Under the current evidence set, the frozen observed-head dataset is:

```
OBSERVED_DISTINCT_PR_HEADS = 78
OBSERVED_HEAD_TO_HEAD_TRANSITIONS = 45

INTERMEDIATE_TRANSITIONS = 19
FINAL_TRANSITIONS = 26
```

## 4. Product sample

Representative product sample = 33 PRs:

```
#3, #4, #5, #6,
#10, #11, #12, #13, #15, #17,
#21–#28,
#31, #32,
#35–#42,
#45,
#49–#52
```

```
PRODUCT_PRS_TOTAL = 33
PRODUCT_PRS_MULTI_HEAD = 26
```

Multi-head product development is **COMMON** (26/33). This OUTCOME C does
**NOT** mean "developers rarely push multiple heads." The measured reason
is different: most later heads contain real affecting code/test changes.

## 5. Current-policy replay correction

This correction is mandatory and supersedes the preliminary Phase-0B
report wording.

The current `pull_request` classifier evaluates **PR base -> current
head** using the cumulative merge-base-correct three-dot diff. It does
**NOT** classify **previous PR head -> current PR head** as the workflow
tier.

Therefore a transition may have:

```
A -> B incremental delta = docs-only
```

while:

```
PR base -> B cumulative delta = FULL
```

In that case B still runs FULL today. Such a transition must NOT be
called `ALREADY_SOLVED_BY_CURRENT_TIER_POLICY` — the preliminary report
incorrectly did so. Frozen corrected state:

```
CURRENT_FULL_CUMULATIVE_TARGETS =
  all observed product heads in the sample whose cumulative product PR
  still includes source/tests
  = 78 (every observed product head qualifies)

AFFECTING_INCREMENTAL_FULL = 43
INCREMENTAL_DOCS_FAST_WINDOWS = 2
ALREADY_SOLVED_BY_CURRENT_TIER_POLICY = 0
```

The two proven incremental docs-only windows are both **FINAL-head**
cases:

- PR #41 final correction at `35989d5...`;
- PR #42 final correction at `cbe0cfd...`.

The previously counted PR #42 `7b3e0b6 -> 94bd25f` must NOT be treated as
an observed remote head transition unless `7b3e0b6` is separately proven
as a remote PR head (it is currently `UNPROVEN_AS_REMOTE_PR_HEAD`, see
"Two datasets" above).

## 6. Why OUTCOME C still holds

The correction above does NOT create a saveable intermediate window.

Current safe model:

- **INTERMEDIATE HEAD**: may theoretically be eligible for reuse.
- **FINAL MERGE-APPROVED HEAD**: must carry fresh FULL evidence.

Observed product workload:

```
INTERMEDIATE_TRANSITIONS = 19
```

All 19 observed intermediate transitions are materially affecting
product/test corrections under the current conservative model.
Therefore:

```
INTERMEDIATE_PR_HEAD_REUSE_CANDIDATES = 0
```

The two narrow observed docs-only transitions are FINAL heads.
Therefore:

```
SAVEABLE_UNDER_FINAL_FRESHNESS = 0
```

Current-equivalent measured saving under the accepted safe
first-generation model:

```
0 job-min
```

This is the decisive value fact.

## 7. Product workload interpretation

Do NOT conclude "multi-head development is rare." 26/33 product PRs are
multi-head. However, repeated heads are usually caused by:

- product behavior hardening;
- test-contract corrections;
- source/test bug fixes;
- compatibility fixes;
- release-contract corrections coupled to executable/test surfaces.

Those heads genuinely require revalidation. The waste opportunity is small
not because iteration is rare, but because most iterations are
semantically affecting.

## 8. Canonical #90 case (reference only)

PR #90 remains a valid reference case:

```
source head A: 435f3a0dddcafc6882bbbbffa2739d0d1a96c607
target head B: e9e164af88d4b61a969aa9f223a9f2e34feb93d1
A -> B:        docs-only
```

Both heads received FULL PR CI in that CI/P2-era PR. This proves:

```
HEAD_PATTERN_OPPORTUNITY_EXISTS_IN_KIND = true
```

But PR #90 is outside the representative product denominator, so it does
NOT override the product-workload Phase-0B result.

## 9. Fail-closed contract

Frozen corrected rule:

```
NO PROVEN REUSE  =>  RUN
```

NOT:

```
NO PROVEN REUSE  =>  CI FAILURE
```

The following conditions — missing source, expired artifact, API failure,
runtime mismatch, base drift, ancestry failure, control-plane drift,
surface affected, ambiguous run, ambiguous artifact, merge-tree mismatch —
all mean:

```
PR_HEAD_REUSE=false
reason=<specific>
=> fresh validation executes
```

Invariant:

```
FAIL CLOSED TO RUN.
NEVER FAIL OPEN TO SKIP.
```

Only an actual fresh validation failure may fail the job.

## 10. Fresh-final rerun finding

Architectural finding, recorded without implementing it:

- development attempt 1: could theoretically use reuse;
- before merge: the same exact head receives an explicit rerun;
- `run_attempt > 1`: a future PR-head reuse verifier would force reuse
  OFF;
- fresh FULL runs;
- a fresh attempt-bound V1 FULL attestation is emitted;
- merge: existing post-merge V1 may consume that exact final-head fresh
  FULL attestation.

Current V1 already binds `run_id`, `run_attempt`, `head_sha`,
`tested_merge_sha`, `tested_tree_sha`, and the artifact name
`market-vault-full-ci-attestation-<head>-attempt-<attempt>`. Therefore
the V1 consumer model is compatible with attempt-bound attestations in
principle.

Historical production evidence: run `31516089021` at `run_attempt=2` was
processed cleanly by V1 logic and returned
`POST_MERGE_REUSE=false reason=control_plane_changed`. This proves
attempt-2 handling itself does not break V1.

Honest limitation: there is still no natural production example where an
attempt-2 PR FULL attestation subsequently produces
`POST_MERGE_REUSE=true` after merge.

## 11. Rerun source rule (design material only)

For any future PR-head source, the HIGHEST/LATEST `run_attempt` must
itself be:

- completed
- success
- fresh FULL
- valid attestation

If `attempt 1 SUCCESS`, `attempt 2 SUCCESS`, `attempt 3 FAILURE`, then:

```
SOURCE UNAVAILABLE
```

No fallback to attempt 2. Same-head attempt-to-attempt reuse: FORBIDDEN.
Transitive source: FORBIDDEN.

This is NOT production authorization.

## 12. Synthetic merge / topology gaps

Technical architecture remains nontrivial even though value already
fails the implementation gate. Unresolved/reopened proof areas would
include:

- cross-head synthetic merge-tree identity;
- base drift;
- source ancestry;
- runtime identity;
- control-plane byte identity;
- retained evidence replay;
- truthful RUN vs REUSED evidence;
- merge-time freshness;
- source ownership;
- dependency/build environment drift.

These gaps are NOT solved now. Because measured saveable value is zero,
there is no reason to pay this proof/maintenance cost today.

## 13. Control-plane finding

A potential future PR-head rule could conceptually distinguish:

- cumulative PR changed control plane before source A;

from:

- control plane changed between A -> B.

If A received a real fresh FULL validation under that exact control-plane
state and A -> B leaves all relevant control-plane bytes identical, that
scenario may be **SAFE_FOR_SHADOW** investigation. But it is NOT
production-authorized, and the representative product sample provides no
value reason to pursue it now.

## 14. No arbitrary cost threshold

No invented numeric thresholds — e.g. "100 job-min/quarter" or "1–3
orders of magnitude" — are formal decision criteria. The Phase-0B
decision rests on the measured fact:

```
SAVEABLE_UNDER_FINAL_FRESHNESS = 0
```

compared against nonzero implementation complexity, proof burden,
maintenance burden, and safety burden. No invented numeric threshold is
needed or used.

## 15. Formal outcome

```
OUTCOME C
```

Meaning: representative MarketVault product history shows common
multi-head development, but no proven saveable INTERMEDIATE PR-head reuse
window under the accepted fresh-final safety model. Therefore:

```
PR_HEAD_REUSE_AUTHORIZED=false
PR_HEAD_REUSE_IMPLEMENTATION=DO_NOT_IMPLEMENT
PR_HEAD_REUSE_SHADOW_CANARY=DO_NOT_START
```

This is a **value decision**, not a statement that the architecture is
impossible.

## 16. Reopen criteria

PR-head reuse may be reconsidered only if new evidence materially changes
the value equation. Valid reasons include:

- future product PRs show repeated intermediate FULL heads where the
  incremental change is provably non-affecting;
- a newly authorized surface produces a real repeated saving window;
- CI surface cost grows substantially while narrow intermediate
  corrections become common;
- current tier semantics materially change;
- a simpler independent evidence topology reduces proof/maintenance cost;
- product development workflow changes enough that Phase-0B's historical
  sample is no longer representative.

Not valid:

- "we already researched it";
- sunk P2/P2-9 cost;
- desire to activate unused foundation;
- artifact expiry by itself.

No fixed 100 job-min threshold.

## 17. Relation to V2-A0

The sealed V2-A0 decision record
([partial_reuse_v2_post_merge_activation_decision.md](partial_reuse_v2_post_merge_activation_decision.md))
is NOT modified. At V2-A0 time, PR-head reuse was correctly recorded as a
mere future unproven direction; this Phase-0B record is a LATER decision
layer, not a retroactive rewrite of history.

Final architecture sequence:

```
Post-merge V1:                 ACTIVE
Post-merge Partial Reuse V2:   V2-A0 OUTCOME C / DO NOT ACTIVATE
PR-head reuse:                 Phase-0B OUTCOME C / DO NOT IMPLEMENT
V2 foundation:                 PRESERVED / UNWIRED
P2 / P2-9:                     PRESERVED AS TECHNICAL PROOF MATERIAL
```

This closes the current reuse-optimization investigation.
