# Intraday research: CI critical path and usable forward observations, Q80-Q82

## Baseline, assessment and authority

The assessed baseline is Q79 main `51e5ba54b86aa0741eb991c634c85c50746a89b3`,
tree `05de70780c31611aee0d6a48a4aee94a0aef1b30`, version 0.9.0. At the start
of the 2026-10-15 owner request, main was actually Q78
`521d2df8c21715f814d544bbc7b483fa9090297b` and Q79 PR #349 was still open.
That prerequisite was closed only after checking its exact-head Codex review,
natural FULL PR CI `38677351178/1`, downloaded package/attestation identities,
and squash merge. Natural push/main CI `38678807920/1` then succeeded for the
actual Q79 merge commit. The user's Q1-Q79 premise is now true at source level;
it does not establish a profitable strategy or actual independent market data.

The owner authorized the next 3-4 mainline tasks in this repository on
2026-10-15, including in-scope repairs, tests, commits, push, PRs, independent
review and conditional squash merge. This record selects three tasks. Follow
AGENTS.md, repository governance, Development Workflow v2 and Personal Local
Tool Workflow v1. No repeated step authorization is needed.

**Delivery order: Q80 -> Q81 -> Q82.** Each task gets a stable exact-head
independent review and required natural PR CI before squash merge; verify the
actual main merge and its natural push CI before implementing the next task.
Read-only preparation may overlap. One writer per worktree. A planning-only PR
or an implementation request is not a completed implementation or a review.
Keep evidence in this record and the individual PRs, not a new audit platform.

### Why these tasks, and what is not being repeated

Q1-Q79 already provide verified Q5 inputs, actual-label-end purging,
linear/quadratic Ridge, model/threshold/joint selection, saved experiments,
Freeze/TEST, cost/delay stress, bootstrap uncertainty, procedure comparison,
market evidence and bounded research-history assessment. Q55-Q72 addressed
specific numerical and repeated-computation counterexamples. Q73-Q79 added
structural/data/history/forward acceptance and actual procedure/CLI connections.
Do not rebuild these or reopen closed numerical cases without a relevant new
counterexample. Existing six-model and 24-member searches are enough to test
whether a declared hypothesis adds value; more learners/search dimensions are
not justified merely by the completed-task count.

Two concrete remaining frictions are visible in the current implementation.
First, `.github/workflows/ci.yml` places BOTH Python matrix legs behind all
3.11 partitions. Q79's successful 3.14 compatibility job `116236224209` ran
from 03:47:49Z to 03:49:59Z, after that dependency, despite not consuming any
partition output. This is an approximately 130-second serial leg in that run,
not evidence that more partitioning is required or a future latency promise.
Second, forward observations currently require hand-entered exact experiment,
candidate/execution identities and action keys, although `_reference_rows`
already knows the complete saved action population. There is no template
export entry. Forward reconciliation intentionally accepts ordinary DEV and
Q25/Q31/Q36 selected outer-DEV accounts, not an already-saved TEST account.
The latter is a new bounded extension, not a previously hidden defect.

The next research-use priority is to make actual observations easier to bring
to existing comparisons and to measure the frozen candidate separately from
its DEV selection procedure. Generated templates remain unmeasured. Without
actual independent bars/quotes/paper observations, software acceptance cannot
be promoted to market validity, execution realism, capacity or profitability.
No automatic strategy choice or model promotion is part of this package.

## Q80 - run Python 3.14 compatibility beside the 3.11 partitions

**Goal.** Remove the unnecessary serial dependency while preserving every
required check, selector, failure gate and exact-version evidence contract.

**Technical plan and dependencies.** Keep the eleven existing file-owned 3.11
partitions and their runner unchanged. Keep the 3.11 aggregate behind plan and
all partitions; run the actual 3.14 compatibility leg after plan independently
of those partitions. Keep the visible required check names `test (3.11)` and
`test (3.14)`. Package publication and FULL attestation must directly depend
on successful results from BOTH legs and the existing portability job. Update
only the directly affected workflow topology checks in `check_release.py` and
its existing regression tests. Preserve classifier, post-merge reuse proof,
selector manifests, complete-file compatibility supplements and fast-tier
behavior. Do not fabricate a successful partition result for the 3.14 leg.

**Defaults.** Same eleven partitions, max parallelism, Python versions,
dependency policy, 258-selector/294-node sealed base, two research compatibility
files, PyArrow compatibility surface, tier defaults and existing timeouts.
Unknown classification or missing required evidence still fails closed. No
new worker framework, service, action dependency or global cache is needed.

**Acceptance.** Existing partition ownership and tier/reuse tests remain valid.
Focused topology regressions distinguish independent 3.14 scheduling from the
old serial graph, retain the 3.11 aggregation, and prevent package/attestation
success when either test leg fails, is cancelled or is unexpectedly skipped.
The natural FULL PR run must actually execute all existing test surfaces and
show 3.14 starting without waiting for the last 3.11 partition. Report observed
job and total durations separately; runner queue variation is not a test
failure. Final review, required CI and post-merge exact-main checks must pass.

**Exclusions.** No additional shards, selector deletion, weakened assertions,
new security audit, branch-protection changes, fake success markers, empty
commits, manual dispatch substitute or release. A sub-ten-minute job budget
is an optimization aim, not achieved by reducing coverage or lowering timeouts.

## Q81 - export an unmeasured observation template from the exact saved account

**Goal.** Eliminate manual identity/action-key copying before using Q76/Q78,
without inventing quote, action-ready or fill evidence.

**Technical plan and dependencies.** Reuse strict `load_strategy_experiment`,
the existing ordinary-candidate/selected-procedure resolution and
`_reference_rows`; factor only the directly repeated resolution needed by the
exporter and analyzer. Add a small API and root/module CLI mode on the existing
forward-reconciliation command. `--observations PATH` remains the unchanged
analysis mode; mutually exclusive `--template-declaration PATH` selects export.
The declaration has exactly `source`, `reference_clock_id` and `policy`, using
the existing validators. Ordinary DEV export requires explicit `--cost-index`
and `--candidate-index`; selected-procedure export rejects those selectors and
uses its actual selected outer-DEV account. Never silently choose a fixed
reference or final DEV winner.

Publish the existing observations v1 (ordinary) or v2 (procedure), binding IDs
from the verified artifact. Emit exactly one record per saved transaction in
saved order, with its actual symbol/day/slot/side; `action_ready_at`, `quote`
and `paper_fill` are all null. Do NOT copy modeled times/prices into observed
fields. Validate the complete generated object through the existing normalizer.
Use the existing exclusive new-file publisher. A generated template is a caller
editable input, not a new trusted market artifact or an immutable measurement.

**Defaults.** No guessed source provenance, capture timestamp, quote-age limit
or adverse-price threshold: these come from the explicit declaration. A null
reference clock stays null. A supported zero-action account emits an empty
records array; an UNAVAILABLE procedure is rejected rather than exported as
all-flat. No automatic path/latest-file discovery or existing-file overwrite.

**Acceptance.** Ordinary and all three procedure kinds produce correct full
populations and identity bindings. Generated inputs normalize and analyze as
NOT_MEASURED (or NO_REFERENCE_ACTIONS), never as measured or policy success.
A small filled observation then traverses the real CLI into existing matching
and metrics without changing other records. Root and legacy module behavior,
wrong selectors, unavailable source and no-overwrite behavior are covered by
focused tests reusing existing fixtures. One strict source open per action;
no Q5 reload, fit, replay, account execution, TEST evaluation or network call.
The export envelope explicitly reports TEMPLATE_CREATED, not RECONCILED;
exit 0 means export succeeded only. Old analysis exits 0/2/1 remain unchanged.

**Exclusions.** No new observation schema for existing DEV accounts, inferred
quotes/fills/clocks, live capture, broker connection, GUI, universal CLI router,
new study registry, automatic population filtering or capacity/PnL certificate.

## Q82 - reconcile observations against an already-saved frozen-candidate TEST

**Goal.** Measure the saved frozen candidate's TEST execution separately from
its outer-DEV selection procedure, without rerunning or reopening TEST selection.

**Technical plan and dependencies.** After Q81 closes, extend the same strict
reference resolver to the supported self-contained saved intraday TEST roots
already validated by `intraday_final_experiment.py`. Use only the TEST report's
actual `execution`, not embedded DEV, benchmark or the selection artifact alone.
Reuse the same transaction consistency checks, whole-population matching,
clock/price metrics and no-replace publication. Introduce explicit observations
and reconciliation v3 for TEST (do not reinterpret v1/v2). Bind expected
experiment ID, execution ID, final_test_id and selection_id; retain selection
experiment ID, evaluation scope and algorithm/environment/source metadata in
the result. Q81's export mode produces the matching v3 template for a TEST
artifact and rejects ordinary candidate indices for it.

**Defaults.** Only already-saved, strictly readable TEST results with supported
execution/cost versions are accepted. A selection-only artifact has no executed
TEST account and must fail. Existing ordinary/procedure v1/v2 outputs remain
unchanged. Keep the frozen recipe and complete saved TEST action denominator;
no new benchmark choice, refit, threshold selection or portfolio aggregation.
Existing policy and clock declarations retain their precise limited meaning.
Opening an already-saved TEST result is exposure to existing TEST information;
it is NOT a new unseen holdout, authenticated forward capture or preregistration.

**Acceptance.** Reuse existing ordinary/inner/threshold/joint TEST fixtures to
exercise each supported root family, with a discriminating example where DEV
and TEST transactions differ. Bind wrong TEST/selection/execution identities to
failures; prove embedded source paths can be unavailable without triggering any
source read. Test no-action, partial/missing evidence and one complete measured
population, preserving policy exceedances independently from measurement
coverage. Exact saved source bytes remain unchanged. Actual API plus root/module
CLI and template-to-analyzer round trip pass. Verify no Q5 access, fits, account
execution or TEST scoring is called. Independent review and exact CI gates apply.

**Exclusions.** No TEST execution, re-selection from TEST, automatic history
certification, authenticated broker fills, live trading, suite/portfolio account
support, new model family or alteration of historical artifacts.

## Shared delivery boundaries

Keep version 0.9.0, current US equity/ETF RTH, unadjusted 1/5/15/30-minute,
long/flat semantics, TRAIN-only transforms, actual-label-end purge, strict
score > threshold, declared-family ordering/ties and frozen TEST contracts.
No releases, tags, deployment, production replacement, paid data acquisition,
credentials/account changes, live subscription or brokerage order is included.
Synthetic fixtures demonstrate software behavior only. Missing external market
observations remain a research-evidence limitation, not a reason to fabricate
measurement or expand this package into a data-acquisition platform.
