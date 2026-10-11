# Selection-procedure comparison and robustness: Q39–Q41

## Verified baseline and task package

The package starts at Q38 main
`7f2b42f4f2288ecf8abbcf26d0431cc0a8440fa2`, tree
`9526000002b0fdf9847f8623373db532bb65a841`, in `M0DIAN/market-vault`.
Q38 PR #308 passed natural FULL CI `38112752851/1`; the exact-main natural
push `38113989028/1` succeeded through the checked-in tree-equivalence reuse
contract. This is not a claim that main ran a second FULL matrix.

Q1–Q38 already supply source-bound data and purging, linear/quadratic Ridge,
chronological six-model MSE selection (Q25), four-threshold economic selection
(Q31), joint 24-member economic selection (Q36), corresponding immutable
Freeze/TEST V1–V4, and Q33–Q35 prediction/objective/return diagnostics extended
to Q36 by Q37. These are completed capabilities, not new work in this package.

Current code exposes a more useful gap than another learner: Q35 compares each
selected procedure only with its fixed source and benchmark. Q11/Q16/Q19 still
admit ordinary fixed DEV experiments, so they do not provide direct comparisons,
complete-family bounds or execution stress for the actual Q25/Q31/Q36 choices.

| Direction | Decision |
| --- | --- |
| Direct A/B comparison of actual selection procedures | Q39, on one identical complete ordinary source and reference. |
| Simultaneous evidence for the declared three-procedure family | Q40, reusing the existing centered-max bootstrap. |
| Fixed-decision cost and signal-delay stress | Q41, reusing the recorded-price projection and execution kernel. |
| New learner, more alphas, Features or training-history search | Deferred; larger search does not answer the identified comparison gap. |
| Another Freeze/TEST version or repeated TEST ranking | Excluded; Q38 already completes that lifecycle. |
| Global PBO/DSR, all historical attempts or profitability claims | Excluded; complete historical-search coverage and new market evidence are absent. |

The owner's 2026-10-11 request authorizes this package, including necessary
repairs, tests, commits, push, PR, independent review and conditional squash
merge. Delivery order is Q39 → Q40 → Q41. Each begins on the preceding verified
main, and finishes only after the final candidate's independent review, natural
required CI, current PR identities, authorized squash and exact-main terminal
CI. Necessary CI partition work is included in Q39. No release, deployment,
live data collection, live trading, source overwrite or storage migration.

## Shared contracts

- Saved Q25/Q31/Q36 are explicit procedure types. Never fabricate an ordinary
  strategy root or fixed candidate ID to pass an older reader's allowlist.
- Paired inputs must embed the identical complete ordinary source and original
  cost index, candidate index and candidate ID. Equal dates or data IDs alone
  are insufficient. Do not take an intersection, drop cash days or fill gaps.
- Verify actual outer dates/folds, READY support, price rows, session clocks,
  execution windows, policy and risk definition through Q35's existing basis
  checks. Preserve the benchmark's full-session maximum hold policy.
- New results are explicitly versioned derived reports. They neither change
  saved experiment IDs nor become immutable strategies eligible for Freeze.
  Existing Q11/Q15/Q16/Q19/Q35 readers, reports and algorithms retain their
  meanings. The package stays at 0.9.0 and adds no dependency.
- API, settings-independent CLI and native desktop must expose complete
  relevant evidence, captured source identities, unavailable reasons and
  recovery after failure or changed draft inputs. Completed result labels
  follow captured inputs, never a subsequently edited draft.
- These are conditional recorded-path analyses. Q39/Q40 do not read Q5,
  fit, select or execute; Q41 only reexecutes fixed recorded decisions. No
  source replay, causal authority or new empirical profitability is implied.

## Q39 — direct two-procedure paired comparison

### Goal, method and dependency

Accept exactly two explicit saved studies of different kinds from Q25/Q31/Q36,
labelled A and B. After complete common-source and account-basis admission,
derive three synchronous daily series: A, B and B−A. Each account's daily
return is `cash_close / cash_open - 1`. The difference is formed per day and
then averaged arithmetically; it is not compounded as an investable account
and is not the difference of two cumulative returns.

Reuse Q15's daily reconciliation and stationary-bootstrap interval engine.
Defaults remain 5,000 draws, seed 0, nominal 95% percentile intervals,
cube-root expected block length (at least two days), at least 100 evaluated
days and ten expected blocks. All three columns receive the same draw on
each replication. Existing gap, constant-series, resampling and numerical
unavailability rules apply. A short sample may still have descriptive means
with unavailable intervals; an unavailable study cannot produce a pair.

Preserve both actual outer accounts, outer refits/applications and their
selected recipes, complete daily support, source identities and basis checks.
The report version is `market-vault-intraday-procedure-comparison-v1`.
Implementation depends on Q35 `_account_basis`, `_saved_ml_source`, and the
Q15 daily/interval primitives; no new statistical engine.

```console
market-vault research-intraday-procedure-comparison --left /absolute/q25.json --right /absolute/q36.json
```

The command also accepts `--block-days`, `--replications` and `--seed` with
the existing numerical limits. Invalid inputs fail before analysis and do
not require an application settings file. The API is
`compare_intraday_procedures(left, right, ...)`.

### Acceptance and exclusions

Use real same-source studies, independent cash-ratio arithmetic and controlled
draws to prove direction, synchronous intervals and zero paired differences.
Check complete support, actual per-fold recipes, different-kind admission,
hidden common-source/basis differences and recorded-only execution. Exercise
CLI and real QML Open/Run, draft edits, failure/retry, evidence, language and
compact-page navigation. No alternative comparator, automatic winner, TEST,
global search correction, fit resampling or repeated Q35 reports.

## Q40 — fixed complete three-procedure family lower bounds

### Goal, method and dependency

Build on Q39's common-source admission. Require exactly Q25, Q31 and Q36,
canonical order Q25 → Q31 → Q36, regardless of supplied file order. No missing
member, duplicate kind or user-selected subset. The shared fixed candidate
is the reference, not a fourth family member. All three columns are the daily
procedure return minus that same original fixed candidate return.

Reuse Q16 `_family_bounds`: synchronous stationary-bootstrap draws, centered
maximum across all three excess columns, nonnegative 95th-percentile common
deduction and nominal 95% one-sided lower bounds. Numerical defaults and
sample gates are Q39's existing Q15/Q16 defaults. Preserve constant columns
in the centered maximum with exact centered zero and retain the existing
unavailable-bound semantics. Any invalid required member blocks family
inference; it cannot disappear from the family.

The new derived report explicitly states `DECLARED_THREE_PROCEDURES_ONLY`
and `historical_search_coverage=UNKNOWN`. Show all three excess means, lower
bounds and unavailable reasons, the common deduction, complete synchronized
daily values and original member/account identities. Extend Q39's desktop
surface and add a settings-independent three-source CLI entry.

The API is `analyze_intraday_procedure_family(snapshots, ...)`; `snapshots`
contains exactly three immutable saved studies. The CLI accepts three repeated
`--study` arguments, with the same optional numerical parameters as Q39:

```console
market-vault research-intraday-procedure-family --study /absolute/q25.json --study /absolute/q31.json --study /absolute/q36.json
```

The report version is `market-vault-intraday-procedure-family-v1`. Canonical
member order also applies to its `family_bounds_id`. The existing native
Procedure comparison page adds a family mode and a third explicitly opened
input; changing the draft mode never reinterprets a previously completed result.

### Acceptance and exclusions

An independent small-matrix oracle verifies centering, common sample indices,
maximum, quantile and every lower bound. Reordering files preserves canonical
output; missing/duplicate/invalid members and changed references cannot yield
a silently smaller family. Native three-source capture, method switches and
failure recovery must preserve Q39. No global multiple-testing correction,
p-value platform, generic registry, family customization or winner promotion.

## Q41 — fixed-decision execution stress

### Goal, method and dependency

Accept one explicit AVAILABLE Q25/Q31/Q36 study. Keep its recorded outer
decisions and chosen recipes fixed. Evaluate exactly nine ordered scenarios:
additional per-fill slippage `0, 5, 10` bp as the outer axis, and signal delay
`0, 1, 2` planned bars as the inner axis. Add slippage to the original policy;
commission and other policy fields remain fixed. These are declared stress
increments, not estimates of actual brokerage costs or liquidity.

Each scenario executes procedure, fixed reference and benchmark, at most 27
complete accounts. Preserve each role's policy, including the benchmark's
full-session maximum hold. Delay LONG and FLAT signals equally through Q19's
planned-slot transform; session tails never cross into the following day.
Signal delay does not alter opening `entry_delay_minutes`.

First require Q35's complete three-account basis and Q19's saved-price
projection. Independently reproduce all three zero-increment/zero-delay
accounts in full. Only the two declared projection identity fields,
`price_evidence_id` and `execution_id`, may differ. If any baseline fails,
do not run the remaining grid or present apparently valid stress results.
All derived execution/price identities remain the kernel's own computed IDs.

Reuse Q19's projection/delay/baseline helpers and unchanged Q6 execution.
Expose each scenario's full accounts, costs, trade counts, return/risk
metrics, changes from the baseline and descriptive daily procedure-minus-fixed
increments. No further bootstrap is needed. Label evidence
`RECORDED_PRICE_GRID_REEXECUTION`, never full source/Q5 Replay. A scenario
whose added slippage violates Q6's valid range is explicitly unavailable;
it is never clipped or omitted.

### Acceptance and exclusions

Check an independent transaction-cash formula for additive per-fill slippage,
complete zero-stress reproduction, both signal directions, no-next-open and
outside-session tails, cash-only days and the benchmark policy. Prohibit Q5,
fit and reselection calls; preserve source bytes and all nine declared rows,
including unavailable rows. Exercise the actual CLI and native scenario,
role, daily, signal-provenance and complete-account views with failure recovery.
Exclude order-book simulation, market-impact calibration, new latency feeds,
reselection under changed costs, TEST stress/ranking and strategy promotion.

## CI cost and validation scope

Q38's `strategy` job took 15m49s, with pytest reporting 923.55s. Other partitions
were below ten minutes (`intraday_research` 9m25s, `intraday_final` 8m27s,
`diagnostics` 7m42s). Q39 splits the growing ML-procedure tests into one new
functional partition, keeping full test ownership and parallel execution.
Expected gains must be checked against actual new run times; no ten-minute
timeout, skipped test or forced reduced tier can substitute for faster work.

Changes to CI controls synchronize the workflow, partition registry, full-job
expectations, attestation/reuse proof and their direct regression checks.
The first main push containing this control change must follow the existing
NORMAL FULL fallback. Subsequent eligible exact-tree merges may use the
existing verified-reuse path. Native Qt entry verification runs locally because
ordinary CI dev dependencies intentionally omit PySide6.

Validation uses compact real-source fixtures, numerical oracles and focused
failure/recovery cases, followed by independent final-candidate review and
natural FULL CI. No unrelated safety audit, whole-project refactor or new
testing framework is included.

### Observed Q39 execution and fixture reuse

Q39 is complete on main `65d374eda3203737a326a90d1ce7c685d617e271`, tree
`19c853fe8ec193d879f42800b74ac9a828ff2c96`, from PR #309. The final PR head
`f9027f329bf967caa369c6721e1ec667a253a87a` passed independent core/CI and native
review and natural FULL `38120135747/1`: all 16 jobs succeeded in 14m54s.
Exact-main push `38121023070/1` succeeded in 14m48s with 16 jobs and explicit
`reuse=false / control_plane_changed`; it actually executed FULL.

Final PR strategy took 5m45s and the new ML-procedure partition 11m14s.
The overall run was 4m21s shorter than Q38's reference run, with runner
variation and Q39's added work limiting attribution. The initial candidate's
production QML inventory failure was repaired by registering the new panel
in the production spec and Windows asset audit; both final runs passed it.

The new Q39 test file took about 123 seconds in that run, including about
70 seconds constructing its real studies. Q40 shares the existing immutable
Q25/Q31/Q36 fixture through a standard session fixture in `tests/conftest.py`
for Q39-Q41, avoiding a duplicate reconstruction for every new report file.
The original Q35 fixture's study mapping remains unchanged, test assertions
remain intact, and unavailable-study cases retain their own real inputs.
No further CI partition or timeout changes are needed for this fixture reuse.

## Method references

- [scikit-learn: nested versus non-nested cross-validation](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html): assess a selection procedure on held-out outer observations. Existing MarketVault chronological purging remains authoritative.
- [scikit-learn: common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html): preserve training-only preprocessing and keep TEST out of model choices.
- [Existing return and family inference](intraday_research_quality.md), [Q33–Q35](intraday_ml_evidence_next.md), and [Q36–Q38](intraday_joint_economic_selection_next.md) define the reused numerical and selection semantics.
