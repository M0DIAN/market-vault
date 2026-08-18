# Partial Reuse V2 Post-Merge Activation Decision — V2-A0

**Status: OUTCOME C**
**Decision: DO NOT ACTIVATE POST-MERGE V2**
**Partial Reuse V2 production gating: OFF**
**PR-head reuse: NOT AUTHORIZED / separate future architecture**

This document permanently records the independently accepted architectural
decision: post-merge Partial Reuse V2 is **NOT** activated under the current
V1 precedence / tier policy / governance. The decision is deliberate and
revisitable only under the criteria in §9.

**No activation:** this decision record changes nothing executable. It does
not activate V2, change V1, change workflow gating, change tests, restore
P2-9 instrumentation, or begin PR-head reuse implementation. The V2
foundation remains present and UNWIRED.

---

## 1. Formal decision base

```
C =
e13c229e10f5bd27c6d4aabd8a7c8b6672b73ba6

tree(C) =
29acb5da8b634ffcbdc5b074ee1132134e99ed54
```

`C` is the P2-9 Phase-C cleanup commit (PR #90) — the current production
main after the temporary P2-9 instrumentation was removed.

## 2. P2-9 lifecycle state

```
P2_9_PHASE_T_COMPLETE=true
P2_9_PHASE_C_COMPLETE=true
P2_9_LIFECYCLE_COMPLETE=true
PRODUCTION_TOPOLOGY_SHADOW_CANARY=PASS
```

The P2-9 production-topology shadow canary is technically COMPLETE and
PASS. As recorded below, that technical PASS did not by itself authorize
activation; V2-A0 independently audited production reachability/value
under current V1 precedence and governance.

## 3. Historical / evidence chain

| Point | Record |
|---|---|
| PR #65 | V2 evidence-matrix **FOUNDATION ONLY**. |
| PR #83 | P2-8 **OUTCOME B**. Measurement/identity chain sound, production topology bridge open. |
| PRs #84–#90 | P2-9 staged production-topology experiment and cleanup. |
| PR #89 / formal T | Production mixed semantic canary **PASS**: `test-3.14 = RUN`, `pyarrow24 = REUSED`. Formal T = `67b65ba9e5d60c8f67da4f4ca6d69ba280791ab6`, production run = `31984989095`. |
| PR #90 / formal C | Temporary P2-9 instrumentation removed. Formal C = `e13c229e10f5bd27c6d4aabd8a7c8b6672b73ba6`, post-merge cleanup run = `32028096783`. |
| V2-A0 | Read-only production reachability/value audit. Independent outcome: **OUTCOME C**. |

## 4. Core decision derivation

### A. Normal FULL PR → squash path

Under current governance, the successful ordinary path is:

```
exact-head successful FULL PR
+ exact four formal jobs SUCCESS
+ attempt-bound V1 attestation
+ squash merge
+ no base drift
+ main tree == PR tested tree
+ non-control-plane delta
=> existing V1 already authorizes 4/4 FULL reuse
```

Therefore post-merge V2 **cannot improve** the successful ordinary path.

**Concrete production example — PR #89:**

```
PR FULL run:      31980154924
formal T:         67b65ba9e5d60c8f67da4f4ca6d69ba280791ab6
main push:        31984989095
V1 result:        POST_MERGE_REUSE=true
                  reason=verified_full_pr_tree_equivalence
P2-9 shadow:      test-3.14 RUN
                  pyarrow24 REUSED
```

State explicitly: **the V2 shadow verdict provided no additional compute
saving on that production run because V1 had already reused all four formal
FULL surfaces.**

## 5. V1-false cases are not a natural V2 value window

The classes of V1-false states were audited; none forms a natural V2
optimization window.

**CONTROL PLANE**

V1: `control_plane_changed` → no V1 reuse. V2: the same control-plane /
relevance contract invalidates both audited V2 candidate surfaces.
Therefore: **NOT a V2 opportunity.** Do not weaken the control-plane rule.

**TOPOLOGY / PR ASSOCIATION / TREE IDENTITY**

Unproven event/topology/PR/tree identity must fail closed for V2 as well.
Therefore: **NOT a safe V2 fallback.**

**GITHUB API / TOKEN / ARTIFACT / LOCAL GIT FAILURE**

V1 and the measured V2 source-locator architecture depend on overlapping
GitHub API / artifact / token / git infrastructure. Therefore: **V2 is not
an independent availability fallback.**

**FAILED / MISSING EXACT-HEAD FULL EVIDENCE**

Some states are theoretically expressible, but current merge governance
requires final-head terminal SUCCESS and independent review before merge.
Therefore those states are not a normal production optimization window.

## 6. Tier-policy interaction

Precise:

- **docs_fast**: already avoids the product heavy validation path by tier
  policy — no V2 window needed.
- **control_plane**: the validated subset policy already skips the
  irrelevant product heavy surfaces; V2 control-plane reuse is forbidden
  anyway.
- **package_docs**: DO NOT claim that every heavy package step is skipped.
  Current `package_docs` behavior still executes the package
  validation/build path. However, `package` is NOT an authorized V2
  surface, so the remaining package_docs work does NOT create a currently
  authorized post-merge V2 optimization window. This precision correction
  is mandatory.

## 7. Current V2 authorization boundary

Measured / candidate surfaces:

- `test-3.14`
- `pyarrow24`

NOT authorized by the P2 proof stack:

- `test-3.11`
- `package`

Candidate authorization is not inferred from the global V1 job model.

## 8. P2-9 artifact precision correction

The P2-9 `market-vault-p2-9-*` bundles were **temporary shadow measurement
artifacts** used to close the production-topology evidence bridge. Phase C
intentionally removed their generators, so current `C` does not produce the
runtime/source evidence that a new production V2 implementation would need.

However, this is a **CURRENT IMPLEMENTATION STATE**, not a proof that
production V2 could never define a permanent evidence schema. P2-8 already
required any eventual production-contract PR to define its own strict
production V2 evidence schema / probe / retained-replay contract. The
OUTCOME-C decision does **not** depend on treating the temporary P2-9
artifact format as permanently mandatory. The decisive reason for OUTCOME C
is the lack of a naturally reachable, materially useful optimization window
under current V1 precedence and governance.

## 9. Natural canary decision

```
NO NATURAL PRODUCTION CANARY REACHABLE
```

Meaning: no legitimate normal main-push state was identified satisfying all
of:

- V1 = false
- V2 proof valid
- at least one authorized candidate REUSED
- actual heavy validation saved
- normal merge governance preserved
- no control-plane weakening
- no evidence tampering
- no transient infrastructure failure used as the trigger

A synthetic exercise would require an explicit override / deliberately
manufactured V1-false state. Classify: **SYNTHETIC_CANARY_OVERRIDE_REQUIRED**.

Decision: **NOT AUTHORIZED.** Do not build such a canary.

## 10. Formal outcome

**OUTCOME C**

Under current governance + V1 precedence, post-merge Partial Reuse V2 is
effectively redundant or unreachable as a meaningful production
optimization.

```
POST_MERGE_V2_ACTIVATION=DO_NOT_ACTIVATE
```

This is a deliberate architectural decision, not an unfinished rollout.

## 11. What is preserved

- V1 production reuse unchanged.
- V2 foundation model in `scripts/ci_post_merge_reuse.py` remains present
  and UNWIRED.
- P2-1..P2-9 historical proof reports remain sealed.
- P2-9 closure report remains authoritative historical evidence.
- No temporary P2-9 executable instrumentation is restored.
- v0.7.0 release/tag/assets remain untouched.

The V2 foundation is **not deleted** merely because production activation
was rejected. It remains useful proof/design material.

## 12. Reopen criteria

OUTCOME C is revisitable only if the architecture materially changes.
Valid reasons to reopen:

- V1 precedence/semantics intentionally change.
- A genuinely frequent V1-fallback class appears that does NOT share the
  same V2 fail-close invariant.
- A newly measured candidate surface creates a material saving window.
- Governance changes produce a legitimate naturally reachable V2 state.
- A new independent evidence topology materially changes the cost/value
  equation.

Artifact expiry alone is **NOT** a reason to reopen. "We already invested a
lot in P2" is **NOT** a reason to reopen.

## 13. PR-head reuse direction

Recorded as **FUTURE DIRECTION only, not authorization**.

The value audit indicates that PR iteration, rather than post-merge main
pushes, is the more promising reuse target. But P2-9 sealed only
consecutive-main topology; PR-head reuse is a NEW proof project and must
not inherit production authorization from P2-9.

Reopened proof areas:

- source/target topology
- moving base / base drift
- synthetic merge tree identity
- new PR head commits
- rerun/attempt semantics
- cross-PR evidence ownership
- target runtime probe timing
- truthful partial/reused evidence
- merge-gate compatibility
- retained replay
- freshness at merge time

```
PR_HEAD_REUSE_AUTHORIZED=false
```
