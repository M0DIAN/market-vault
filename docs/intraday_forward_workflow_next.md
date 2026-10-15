# Intraday research: usable forward observations and CI closure, Q80-Q82

## Verified continuation baseline and scope decision

The owner's 2026-10-15 continuation request authorizes 3-4 bounded mainline
items, including repairs, tests, commits, push, PRs, independent exact-candidate
review and guarded squash followed by exact-main natural push CI verification.
The owner also requested direct implementation rather than delegating coding
to the unavailable cloud worker. Existing repository governance still applies.

The actual continuation main is `f8b7d4cdf93ff203402131a56af8bb8ad4647933`,
tree `c922b4e877064c1cadd0b122325279135226e24a`. PR #350 merged only this task
document (one file, 192 additions), not the Q80 workflow/checker/test patch.
Natural main push CI `38690082289/1` succeeded for that documentation scope;
it does not establish Q80 implementation or parallel scheduling. Q80 is OPEN.
Q79 source remains the previously accepted
`51e5ba54b86aa0741eb991c634c85c50746a89b3`, tested tree
`05de70780c31611aee0d6a48a4aee94a0aef1b30`, with FULL PR CI
`38677351178/1` and exact-main push CI `38678807920/1` successful.

This continuation retains three items: Q81 observations export, Q82 saved-TEST
reconciliation, and completion of Q80 CI parallelism. **Delivery order is now
Q81 -> Q82 -> Q80 closure**, superseding the earlier Q80-first scheduling.
Q81 depends on Q76/Q78/Q79, not on the CI optimization. Q82 actually depends on
Q81; Q80 is orthogonal. The healthy existing workflow remains authoritative
while the product work proceeds. This prioritizes a usable research input path
rather than making a throughput improvement an artificial product dependency.
Do not mark Q80 complete, remove its acceptance conditions, or relabel it Q83.

Each item is a separate PR from the then-current verified main. Implement the
next item only after final independent review, required natural CI, guarded
squash and actual merged-main CI closure for its predecessor. Read-only
preparation may overlap. One writer per worktree; no self-review presented as
independent approval. A planning-only PR or source blob is not an accepted
implementation. This document and the individual PRs are the task record.

## Assessment and exclusions common to the package

Q1-Q79 already provide verified Q5 inputs, actual-label-end purging,
linear/quadratic Ridge, model/threshold/joint selection, saved experiments,
Freeze/TEST, cost/delay stress, uncertainty, procedure comparison, market
comparison evidence and bounded research history. Q55-Q72 corrected specific
numerical and repeated-computation cases. Q73-Q79 added structural/data/history
acceptance and actual procedure/CLI connections. Do not rebuild these or reopen
closed numerical cases without a directly relevant counterexample.

The current forward input requires manually copying exact identities and action
keys even though the reader already knows the complete saved action population.
Its scope ends at ordinary DEV and Q25/Q31/Q36 selected outer DEV. The first gap
is practical input preparation; the second is the deliberately unsupported
already-saved TEST account. They justify Q81 and Q82, not a new comparison
engine. Q80 removes an observed unnecessary dependency: the old Python 3.14 job
waits for all 3.11 partitions, although it consumes no partition result. In
Q79 that compatibility job took about 130 seconds after the wait. This is one
observed serial cost, not a guaranteed future saving or a reason for new shards.

Keep version 0.9.0 and current US equity/ETF, RTH, unadjusted 1/5/15/30-minute,
long/flat scope, TRAIN-only transforms, actual-label-end purge, strict score >
threshold, declared-family ordering/ties and frozen TEST semantics. No new
learners, Features, search dimensions, automatic selection/promotion, releases,
tags, deployment, production replacement, paid data, credential/account changes,
live subscriptions or brokerage orders. Synthetic inputs demonstrate software
behavior, not market accuracy, actual capture, obtainable fills or profitability.
No supplied real independent observations are being claimed by this package.

## Q81 - export an unmeasured template for the exact saved DEV account

**Goal.** Remove manual identity/action-key copying without creating evidence
that was never observed.

**Technical approach and dependencies.** Reuse strict
`load_strategy_experiment`, existing ordinary-candidate/selected-procedure
resolution and `_reference_rows`. The two callers share only the necessary
account and declaration helpers. The existing root and legacy module CLI share
the same parser/runner; add mutually exclusive `--template-declaration PATH`
beside unchanged `--observations PATH`. No new router or GUI.

The declaration has exactly `source`, `reference_clock_id` and `policy`, using
the existing metadata validators. Ordinary DEV requires both explicit
`--cost-index` and `--candidate-index`; selected procedures reject these flags,
even zero, and use their complete actual selected outer-DEV account. Never use
the fixed reference or final DEV winner as a substitute. The Python entry is
`create_intraday_forward_template(experiment_path, declaration, *,
cost_index=None, candidate_index=None)` in `intraday_forward_reconciliation`.

**Defaults.** Emit existing observations v1 for ordinary DEV and v2 for a
supported AVAILABLE procedure. Derive exact experiment and candidate/execution
identities from the validated saved source. Preserve every saved transaction in
recorded order with symbol, trading_day, slot and side. `action_ready_at`,
`quote` and `paper_fill` must all be null; modeled prices/times are never copied
into observed fields. Normalize the generated object through the existing
observation grammar before returning or publishing it.

Source provenance, source timestamp, clock basis and policy thresholds are
explicit caller inputs, not guessed defaults. Preserve a null reference clock.
An AVAILABLE zero-action account exports an empty array; an UNAVAILABLE study
fails. Use the existing exclusive new-file publisher; no overwrite or discovery.
The output is editable input, not a trusted immutable market measurement.

**Acceptance.** Real saved ordinary and all three procedure inputs prove exact
whole populations, selected-not-fixed account choice and one strict Open per
action. Generated input normalizes and yields NOT_MEASURED (or
NO_REFERENCE_ACTIONS), never measured acceptance. Null records are present
matches with unavailable measurements, not missing records and not zero costs.
Reuse the same existing study fixtures, including existing flat/unavailable
cases. Test invalid/missing/boolean/negative/out-of-range selectors, explicit
unknown clock, declaration validation and unchanged source/declaration bytes.

Real installed root and legacy module exports must agree. Pass the resulting
file back into both unchanged analysis entries; then fill one synthetic record
and prove exactly one measurement while all other null records remain in the
denominator. Verify no overwrite, mutually exclusive modes, index rejection in
analysis mode, and operation without settings. Instrument no Q5 reconstruction,
fit, procedure evaluation or account replay. Existing Q76-Q79 tests remain.

The export envelope is `market-vault-intraday-forward-template-cli-result-v1`
with status TEMPLATE_CREATED, output path and template. Exit 0 means export
succeeded only. Template errors use FAILED/exit 1 with that envelope; argparse
usage errors remain 2. Existing analysis v1/v2 content and 0/2/1 exits remain
unchanged. No report is promoted into profitability or untouched-TEST proof.

**Exclusions.** No new DEV observation grammar, observed data generation,
quote/fill/clock inference, automatic history certification, live collection,
broker service, source repair, refit, execution, TEST scoring or new registry.

### Q81 usage

Prepare an explicit declaration with the same source/clock/policy fields as the
existing observation interface. These illustrative filenames must already
exist for inputs; output names must not exist:

```console
market-vault research-intraday-forward-reconciliation --experiment saved-dev.json --template-declaration declaration.json --cost-index 0 --candidate-index 1 --output observations-to-fill.json
market-vault research-intraday-forward-reconciliation --experiment saved-procedure.json --template-declaration declaration.json --output procedure-observations-to-fill.json
market-vault research-intraday-forward-reconciliation --experiment saved-procedure.json --observations procedure-observations-to-fill.json --output unmeasured-reconciliation.json
```

The first command's 0/1 indices are an example, not automatic candidate choice.
The final command still reports missing measurement until genuine compatible
observations are supplied. Keep unknown fields null rather than copy modeled
reference values to manufacture an apparently complete capture.

## Q82 - reconcile an already-saved frozen-candidate TEST execution

**Goal.** Assess the frozen candidate's saved TEST account separately from its
DEV selection procedure, without rerunning or reopening TEST selection.

**Approach and dependencies.** After Q81 closes, extend the same resolver to
self-contained supported intraday TEST roots already validated by
`intraday_final_experiment.py`. Use only the TEST report's own execution, not
embedded DEV, benchmark or a selection-only file. Reuse transaction consistency,
whole-population matching, clock/price metrics and exclusive publication.
Introduce explicit observations/reconciliation v3 for TEST; bind expected
experiment_id, execution_id, final_test_id and selection_id. Retain selection
experiment identity, evaluation scope and algorithm/environment/source metadata.
Q81's template entry produces matching v3 and rejects ordinary indices.

**Defaults.** Only already-saved, strictly readable TEST with supported
execution/cost versions. Selection-only artifacts have no TEST account and fail.
Preserve ordinary/procedure v1/v2 outputs and historical bytes. Preserve the
frozen recipe and complete action denominator. Opening saved TEST exposes
existing TEST information; it is not a new unseen holdout, authenticated capture,
preregistration or verified brokerage fill.

**Acceptance.** Reuse supported ordinary/inner/threshold/joint TEST fixtures,
including a case with different DEV/TEST transactions. Reject wrong
TEST/selection/execution identities. Missing embedded source paths must not
trigger data reads. Cover no actions, partial/missing evidence and a complete
measured population; keep policy exceedance separate from coverage. Actual API,
root/module CLI and template round trip pass with source bytes unchanged and
no Q5 reads, fitting, account execution or TEST scoring. Exact review/CI gates
remain required.

**Exclusions.** No TEST execution/reselection, history certification, automatic
promotion, live capture/trading, suite/portfolio support or new model family.

## Q80 closure - independent Python 3.14 compatibility scheduling

**Goal.** Remove the unnecessary serial dependency without reducing coverage.

**Approach.** Keep the eleven file-owned 3.11 partitions and 3.11 aggregation.
Run actual 3.14 compatibility after plan independently of partitions. Preserve
visible checks `test (3.11)` and `test (3.14)`. Package/FULL attestation must
directly require both test legs and existing portability success. Adapt only
directly affected workflow/checker/topology tests. The earlier uncommitted
patch is not accepted: inspect all active checker entry points, including
`check_ci_auditability`, rather than trusting earlier sparse checks.

**Defaults.** Same partitions, parallelism, Python/dependency policy, sealed
258-selector/294-node base and two research compatibility files, PyArrow surface,
classifier/reuse behavior, unknown-to-FULL policy and timeouts. Do not fabricate
partition success in the independent 3.14 environment.

**Acceptance.** Whole-file coverage and failure propagation remain. Focused
topology tests reject the old serial graph and package/attestation success when
either leg fails, is cancelled or unexpectedly skipped. Natural FULL must execute
all existing surfaces and demonstrate 3.14 starting before the final partition
completes. Record job duration and end-to-end duration separately; queue variance
is not a correctness failure. Final review and exact-main CI must pass.

**Exclusions.** No extra shards, deleted selectors, weaker assertions, new
framework/cache/service, branch-protection changes, fake markers, empty commits,
manual-dispatch substitute, increased timeouts or release. Sub-ten-minute jobs
are an optimization aim, not achieved by relaxing the checks.

## Q81 candidate evidence boundary

Direct implementation changes only the existing forward module, its existing
same-fixture acceptance test module and this record. No CI workflow change is
included in the Q81 candidate. Local Python 3.13 syntax checks passed. Nine
calculation/reference kernels and the complete report-reduction AST are unchanged;
12 isolated normalizer equivalence cases and five parser cases passed using
extracted source definitions. These are supplementary checks, not public runtime
or independent evidence. Actual public pytest was attempted and exited 2 during
collection at `service.py: import pyarrow.parquet`; zero acceptance tests ran in
this local environment. No dependency stubs or skipped assertions conceal that
limitation. Required natural FULL CI must execute the genuine installed-entry,
saved-reader and procedure tests. Final review and merge remain separate gates.
