# Intraday metric correctness and data scalability: Q58–Q60

## Verified baseline and authorized package

Start from main `34a613bf8e56d23c0b62c8b491e95c852eeeaad4`, tree
`5fba9052376ff8e62455f799905463d8eb45a768`, in `M0DIAN/market-vault`.
[Q57 PR #327](https://github.com/M0DIAN/market-vault/pull/327) is merged;
its exact-main natural push
[38224408838/1](https://github.com/M0DIAN/market-vault/actions/runs/38224408838/attempts/1)
is terminal SUCCESS. Remote main and clean local/origin main were verified
before creating the Q58 feature branch.

The owner's 2026-10-12 request authorizes these three tasks, including in-scope
repairs, tests, commits, push, PRs, independent final-candidate review, conditional
squash merge and exact-main CI verification. Follow the supplied Development
Workflow v2, Personal Local Tool Workflow v1, AGENTS.md and checked-in governance.
Version remains 0.9.0. Implementation order is **Q58 → Q59 → Q60**; each starts
only after the preceding merged-main gate succeeds. Read-only preparation may
overlap. Each worktree has one writer; final review is by an agent that did not
design or implement that candidate.

## Assessment and counterevidence

Q1–Q57 already supply verified intraday data, actual-label-end purging, fixed
linear/quadratic Ridge, chronological model/threshold/joint selection, explicit
Freeze/TEST, prediction and objective diagnostics, risk and uncertainty,
paired/family comparisons, execution stress, market/sample evidence, one-source
procedure execution and native inspection. Q55 corrected TRAIN-constant
Features; Q56 removed redundant diagnostic JSON copies; Q57 captured native
selection identities. None of those completed capabilities is repeated here.

| Candidate | Decision grounded in actual code |
|---|---|
| R² for constant targets and pooled validation | Q58. Shared `_metrics` can report huge finite R² for exactly constant targets; the baseline aggregate subtracts nearly equal raw second moments and can disagree with its sole fold. |
| TS2 execution identity calculation | Q59. Each execution identity separately traverses all values for the flat value digest and again through sample digests, recomputing identical leaf identities. |
| PIT window lookup during strict Q5 reconstruction | Q60. Every request scans all reconciled historical rows. A call-local event-time index can bound that scan while preserving the existing predicate and admission. |
| Immutable Q5/experiment scalar identity reads | Defer. Five reads cost about 0.096/0.739 s on 2.3/17.4 MB fixtures; larger measured reconstruction work takes priority. |
| Cost-dependent selected outer results | Already possible by running Q49 at each explicit ordinary cost index. Q53's narrower recorded-inner report is not evidence that this computation is missing. |
| More learners, Features, selection axes or reports | Excluded. Existing capabilities cover the proposed analyses; no observed market study establishes a need for a larger search space. |
| Q6 repeated execution validation | Retain the Q55–Q57 deferral: its measured cost did not justify changing the numerical execution kernel. |

A bounded Python 3.11.17 profile of an existing synthetic 2,300,696-byte Q5
fixture found 1,977,300 PIT `_matches` calls for 1,170 requests. Profiled load
took 37.665 s; TS2 identity subtrees dominated, and PIT candidate-list filtering
took 3.824 s. Profiling overhead means these are attribution measurements, not
wall-clock performance promises. An unprofiled Q5 build took 13.018 s; a temporary
Q59 prototype took 10.183 s and retained every saved byte. These are software
measurements on offline fixtures, not market evidence or profit estimates.

## Shared defaults and boundaries

- Preserve Features, recipes, alphas, thresholds, chronology, purging, execution
  rules, complete support, FIRST_DECLARED ties and TEST isolation.
- No new dependency, learner, persistent cache, storage format, source overwrite,
  data collection, release, deployment or live trade.
- Q58 changes erroneous R² results. It leaves model fits, forecasts, MAE/RMSE,
  economic selections and execution accounts unchanged. Old saved bytes remain
  immutable and readable; strict replay of an affected old report can correctly
  report a mismatch. Fresh reports bind the corrected values in their IDs.
- Q59/Q60 retain complete results and IDs. A hash or an earlier invocation must
  never replace strict current Canonical/Q5 reconstruction or source admission.
- Required CI follows the actual classifier. Repartition only for an observed
  bottleneck, retaining complete collection and fail-closed gates; distinguish
  actual job duration from queue time. No timing threshold in permanent tests.

## Q58 — correct constant and pooled R²

### Goal, plan and defaults

Use one centered total-sum-of-squares calculation for the shared metric and
the complete pooled VALIDATION targets. Exactly equal targets have zero total
variation and R² remains null. Nonconstant targets retain the centered
`fsum((y - mean) ** 2)` calculation, without an epsilon cutoff. Pooled R² uses
every validation observation around the pooled mean, never an average of fold
R² or `sum(y²) - sum(y)²/n`. Keep the existing MAE/RMSE and fitting arithmetic.

For nine targets of 0.03 and zero predictions, old `_metrics` returns about
`-7.477e31` instead of null. The same issue occurs with 67 copies of the
Q5-computable target `1.03 / 1.0 - 1.0`. A public single-fold baseline with
validation targets `0.01 ± 1e-10` reports fold R² 0 but pooled R² about 0.262.
Q21's descriptive metric already has an exact-constant guard; do not replace
its independent availability/scale policy or describe it as newly implemented.

### Acceptance and scope

1. Reproduce both defects at real baseline/shared prediction-metric entries on
   the old code, then pass the same regressions on the candidate.
2. Single-fold and pooled R² agree; unequal folds use all observations and an
   independently computed pooled oracle. Nonconstant low-variance targets
   remain measurable; constant folds at different levels are not a constant pool.
3. Intraday prediction metrics retain COMPLETE-target pairing, missing-target
   counts, MAE/RMSE and no-target availability. No source, fit or TEST is added.
4. Existing numerical/leakage tests, artifact validation and required CI pass.

Expected scope: `research/ridge_baseline.py`, existing baseline and intraday
analysis tests, and this record. No solver rewrite, broad extreme-number policy,
new R² schema, historical-artifact migration or change to selection objectives.

### Q58 local evidence

The five added numerical cases reached the old production defect: **5 failed
in 0.25 s**. The identical cases passed after the repair: **5 passed in 0.08 s**.
The complete existing baseline and Ridge final-test files, including the new
baseline cases, gave **27 passed in 0.15 s** on Python 3.11.17. Repository hygiene,
release/version 0.9.0 and whitespace checks passed. Actual ordinary research and
installed prediction-quality CLI validation, final review and remote gate
identities are recorded in the associated PR. The old-artifact compatibility
assessment above is based on the reader/replay code, not a claimed historical
bad-artifact E2E execution.

## Q59 — reuse leaf identities within one TS2 execution digest

### Goal, plan and defaults

Within a single execution-identity calculation, calculate each leaf value ID
once and use that exact digest for both the complete values-content identity
and its parent sample identity. Preserve all existing F/V/Q/E domain strings,
field framing, sorting, counts and empty/excluded outcomes. Use temporary local
collections only; discard them when the property returns. Keep issued record
fields, constructors, source fingerprints, public helper behavior and current
source-dependent identity calculation unchanged.

### Acceptance and scope

1. Complete values/sample/execution IDs equal the old independent property
   composition, including empty, excluded and multiple-spec cases.
2. Instrument the execution-identity path to prove one value-ID computation
   per leaf instead of two; no wall-clock gate and no cross-call cache.
3. Actual Q5 build/load bytes, data IDs and Feature/target content remain equal
   on the same admitted Canonical fixture. Measure the actual entry once per
   path and identify profiling versus unprofiled timings.
4. Existing fixed identity oracles, issuance/immutability/source boundaries and
   directly affected cross-day consumers pass, followed by required CI.

Expected scope: `ts2_feature/identity.py`, `ts2_feature/models.py`, existing TS2
tests and this record. No persistent record cache, added dataclass field,
authority bypass, transform/source change, hash-version change or Q5 admission
relaxation. Q58 is the delivery dependency, not a new semantic prerequisite.

## Q60 — bound PIT candidate scans by the requested time range

### Goal, plan and defaults

After complete row/gap reconciliation, build one call-local event-time index.
Use half-open `[start, close)` bounds to select only the candidate time range
needed by each request. Restore the original candidate order before the existing
`_matches` and `_assemble_sample` logic. Preserve the existing dimensions,
cross-date Label rejection, market-then-archive counters, final ordering, gap
admission and source provenance. A single time index is sufficient for current
Q5 single-symbol inputs; no additional dimension-index abstraction is needed.

Do not filter by anchor date, actual session or either availability clock in
the index. Feature windows may span dates. Cross-date Label candidates must
still be rejected before clocks, even if a later clock filter would exclude
them. Requested-session matching remains exact, including ALL; gap matching
has its own distinct date/session rules and is not changed. Global conflicts
outside all requested windows must still fail before indexing.

### Acceptance and scope

1. Compare complete assembler results with the old full-scan path, retaining
   diagnostics, pins, gaps, association rows and every identity.
2. Existing window/clock equality, scope, cross-date, input-order, duplicate and
   conflict regressions pass. Preserve first offending candidate order too.
3. Actual Q5 reconstruction retains complete bytes while instrumentation proves
   fewer candidate checks. Measure observed end-to-end cost without a timing gate.
4. Required FULL coverage of the shared PIT path and exact-main CI succeed.

Expected scope: `dataset/pit.py`, existing PIT tests and this record. No PIT
assembler-version change, Canonical reader change, gap index, Feature formula
change, persistent cache, row omission or new cross-day/ALL policy.
