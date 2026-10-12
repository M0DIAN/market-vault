# Intraday computation efficiency: Q64–Q66

## Verified baseline and authorized package

Start from `M0DIAN/market-vault` main
`9cc7daa1b69a79798aada55f62a039c0d970cb92`, complete tree
`280286fd85b003c04c5e38a4ba3f87e8076174b8`. Q63
[PR #333](https://github.com/M0DIAN/market-vault/pull/333) is merged; exact-main
natural push [38250525072/1](https://github.com/M0DIAN/market-vault/actions/runs/38250525072/attempts/1)
is terminal SUCCESS through verified FULL PR tree reuse. Remote main,
local/origin main and a clean worktree were checked before branching.

The owner's 2026-10-12 request authorizes these three tasks, including in-scope
repairs, tests, commits, push, PRs, independent final-candidate review,
conditional squash merge and exact-main CI verification. Follow the supplied
Development Workflow v2, Personal Local Tool Workflow v1 and checked-in
governance. Version remains 0.9.0. Delivery order is **Q64 → Q65 → Q66**;
each implementation starts only after its predecessor's merged-main gate
succeeds. Read-only preparation may overlap. Each worktree has one writer;
final review must be independent of that candidate's design and implementation.

## Assessment and counterevidence

Q1–Q63 already provide verified intraday data, actual-label-end purging,
linear/quadratic Ridge, chronological model/threshold/joint selection,
Freeze/TEST, prediction and economic diagnostics, uncertainty, execution
stress, market/sample evidence and a native three-procedure suite. Q55–Q63
also corrected constant Features/targets and R², reduced unnecessary JSON
copies, fixed native capture, reused TS2 leaf identities, bounded PIT scans
and computed each symmetric Gram entry once. None is repeated here.

| Candidate | Decision from inspected code and bounded evidence |
|---|---|
| TS2 digest format validation | Q64. The same exact 64-character lowercase-hex language can be checked without a Python generator visit for every character. |
| Repeated Feature ranks | Q65. Rank IC and tails sort the same Feature separately; every Feature sorts the same Label again. |
| Different-alpha training preparation | Q66. Q50 caches complete identical fits, correctly including alpha; different alphas still repeat the same standardized training matrix and Gram preparation. |
| Another CI repartition | Not needed now. Q63 FULL PR `38248907286/1` passed all 16 jobs; longest partition was 525 seconds. |
| Immutable scalar ID lookup | Defer. Five reads of a 2.3 MB Q5 object cost 0.057 seconds in this environment; the measured computations above take priority. |
| Further learners, Features or search axes | Excluded. Existing source code supplies the proposed research analyses; no observed market study justifies enlarging the search space. |

One separate numerical limitation was confirmed with actual `fit_ridge_rows`:
for nonconstant `X = (1 - 2**-50, 1, 1 + 2**-50)` and Q5-computable targets
`(0.99933 / 1 - 1, 0, 1.00067 / 1 - 1)`, alpha 1, translating X by -1 changes
the last prediction from `0.00048828125` to `0.0005024999999999613`, crossing
the existing 0.0005 threshold. These are legal float inputs, not a claim that
the complete combination was observed in market history or replayed through
a complete Canonical/Q5 study. Raw coefficients/intercept can lose low bits;
replacing the final addition alone cannot generally recover them. A reliable
repair must explicitly address the saved numerical representation and shared
baseline/final consumers. It is deferred as a separate contract-sensitive
task, not mixed into these byte-preserving optimizations. No claim that all
numerical issues are resolved follows from this package.

## Shared defaults and exclusions

- Preserve all complete model/report/artifact bytes and IDs, Feature order,
  supported alpha values and their numeric representation, thresholds,
  candidate coverage, FIRST_DECLARED ties, chronology, purging and TEST isolation.
- Preserve source admission and strict current reconstruction. Local computation
  reuse never certifies a source or upgrades a recorded result's proof state.
- Retain current statistics, floating-point multiplication/summation order,
  solver, rank ties and quantile membership. Do not fold numerical corrections
  into an optimization that promises byte equality.
- No new dependency, learner, Feature, search dimension, persistent cache,
  source overwrite, schema migration, data collection, release, deployment or
  live trade. Q66's preparation state exists only in the existing suite action.
- Use the actual CI classifier and all required coverage. No manual reduced
  tier, wall-clock assertion or unrelated safety/test expansion. Measurements
  are bounded offline software observations, not profit or production promises.

The existing fixed procedure rules remain explicit (these families are not
new user-configurable search parameters):

| Procedure | Fixed family and selection objective | Threshold and costs |
|---|---|---|
| Q25 model selection | RIDGE then QUADRATIC_RIDGE, each with alpha 0.1, 1.0, 10.0; minimize row-weighted pooled MSE across COMPLETE inner observations | Threshold and execution/cost assumptions inherit the captured ordinary source |
| Q31 threshold selection | Keep the source representation, alpha and ordered Features; maximize inner net compounded account return | Select among 0, 5, 10, 20 bps; retain source execution/cost assumptions |
| Q36 joint selection | The same six models times four thresholds, 24 declared members; maximize inner net compounded account return | Same four thresholds and source execution/cost assumptions |

All three use the final five **trading sessions** of the available history as
the inner holdout and all preceding eligible history as TRAIN, with at least
ten TRAIN sessions. Ten is a minimum, not a fixed rolling window. Preserve
actual label ends strictly before the training boundary, TRAIN-only
transformations, FIRST_DECLARED ties and
the strict `score > threshold` LONG rule (otherwise FLAT). Q25 does not impose
a universal 5 bps threshold. The ordinary source, DEV chronology and frozen
final TEST boundaries remain authoritative; this package adds no tuning axis.
Q25 scores available COMPLETE labels; Q31/Q36 evaluate the economic holdout
over READY decisions and the complete price grid, without requiring COMPLETE
scoring labels. Source reconstruction still verifies the full Q5 file,
including held-out rows; training, selection and scoring remain isolated from
TEST. The suite neither selects a winning procedure nor automatically runs TEST.
These rules come from the existing [Q25](../src/market_vault/research/intraday_inner_selection.py),
[Q31](../src/market_vault/research/intraday_threshold_selection.py),
[Q36](../src/market_vault/research/intraday_joint_selection.py) and
[suite](../src/market_vault/research/intraday_procedure_suite.py) implementations.

## Q64 — strict TS2 digest validation without per-character Python work

### Goal, implementation and defaults

In `ts2_feature/_validation.py`, use a compiled `[0-9a-f]{64}` pattern and
`fullmatch`. Retain the exact `type(value) is str` requirement, return the
original string, and preserve `RESULT_AUTHORITY: invalid identity digest`.
Uppercase, non-ASCII digits, whitespace, wrong lengths and string subclasses
remain rejected. No digest input, encoding, hash, domain or order changes.

The baseline checked 20,000 valid digests in 0.045680 seconds; a bounded
compiled-pattern prototype took 0.005282 seconds with identical results.
More usefully, the actual `load_intraday_dataset` entry reconstructed an
existing 2,300,683-byte Canonical/Q5 fixture in 5.429981 seconds versus
4.738337 seconds with that in-memory prototype (about 12.7% shorter).
Complete bytes and the source file hash remained identical. Each was one
unprofiled run on Python 3.11.17, not a permanent latency guarantee.

### Acceptance and scope

1. Actual digest and sequence composition accept exactly the same canonical
   strings and preserve input type/error behavior, including trailing newlines.
2. All existing 82 frozen digest vectors, TS2 execution/authority regressions
   and a strict Q5 reconstruction retain their complete outputs.
3. Independent exact-candidate review, natural required PR CI and exact-main
   CI succeed. An optimization need not pretend the correct baseline is red.

Scope: the TS2 scalar validator, existing identity/TS2 tests as needed, and
this task record. No regex-based parsing of unrelated objects, removal of
source checks, new API, Feature fingerprint or identity version.

### Q64 local evidence

The four existing TS2 identity/execution/boundary/canary test files passed
**232 tests in 2.11 seconds**, including the 82 unchanged frozen vectors and
the new exact-type/hex/error boundary cases. The implemented candidate's
actual strict `load_intraday_dataset` took 4.274502 seconds on the same
2,300,683-byte saved fixture; every byte remained equal, as did SHA256
`49292afa72be0ad1562b5829a5cc48c51ebfe46a170220a9b34d3a1d7b012cc4`.
The original file was unchanged. These timings remain individual observations.
Repository hygiene, whitespace and release/version 0.9.0 checks passed on
Python 3.11.17. Final independent review and remote gates are recorded in the PR.

### Q64 delivery closure

[PR #334](https://github.com/M0DIAN/market-vault/pull/334) received independent
final-candidate PASS on `d1cd72356bc3f44c2fdf116fafd2c85cd16c2876` and natural
RESEARCH_FAST PR CI
[38260030077/1](https://github.com/M0DIAN/market-vault/actions/runs/38260030077/attempts/1).
Squash main `422c515033bdcce375ff1e43d463cc450a46644f` retains the reviewed tree
`5775a05f7e53012af33407fc328c2a4ed19b5259`. Its natural push
[38260550153/1](https://github.com/M0DIAN/market-vault/actions/runs/38260550153/attempts/1)
passed all 16 physical FULL jobs. This was actual FULL, not subset reuse:
`research_fast_is_pull_request_only`, `POST_MERGE_REUSE=false`,
`jobs_missing_surface`. The longest partition took 447 seconds. Independent
post-merge review confirmed COMPLETE, exact version 0.9.0 and clean synchronized
main before Q65 implementation began.

## Q65 — calculate each split/Feature rank vector once

### Goal, plan and defaults

In `research/feature_research.py`, build the selected split's float Label
tuple and ranks once per `analyze_features` call. Compute each Feature's ranks
once, using them for both Rank IC and the existing tail membership rules.
Keep `_average_ranks` sorting keys, average tie ranks, current arithmetic,
Feature order, empty support and split permissions. Explicit local values
are sufficient; do not retain all Feature vectors in a cache.

A public-analysis prototype with 30,000 rows and six Features reduced sorting
from 18 calls to 7 and measured 0.721646 to 0.388372 seconds, with identical
complete report bytes. That is synthetic ML-input analysis, not Q5 load time.

### Acceptance and scope

1. A public multi-Feature analysis sorts each X once and Y once; a second call
   recomputes its own ranks. No cross-split or cross-call state is retained.
2. Full report bytes match the baseline for normal, constant, tied, empty and
   selected-order cases, including existing odd-sample quantile boundaries.
3. Existing Feature Research/Stability/Selection and actual CLI tests pass;
   no output field, ranking/selection rule or split admission changes.
4. Final-candidate independent review and both remote gates pass.

Scope: Feature Research internals, directly related existing tests and this
record. Q64 is a delivery dependency, not a statistics dependency. No new
statistics framework, fitted calibration, score, selector or GUI redesign.

### Q65 local evidence

Implementation starts from completed Q64 main
`422c515033bdcce375ff1e43d463cc450a46644f`. The new public-entry work-count test
fails on the unchanged production baseline with 9 rank calls instead of 4.
The candidate performs those 4 calls and recomputes all 4 on a second analysis.
Existing Feature Research, Stability, Selection and their three CLI test files
give **85 passed in 0.45 seconds**, including the one new test; previous
mathematical and split-boundary assertions remain unchanged.

Complete reports match the saved pre-implementation baseline for normal,
requested-order, tied, empty and constant cases. The same 30,000-row/six-Feature
public input also retains all 2,246 report bytes while rank calls fall 18→7.
One unprofiled local observation was 0.829853 seconds on the baseline and
0.619962 seconds on the candidate. This is a bounded software measurement, not
a timing gate or an end-to-end Q5/suite latency claim. No Feature vectors or
ranks persist beyond one analysis call. Final independent review and remote
gates are recorded in the associated PR.

### Q65 delivery closure

[PR #335](https://github.com/M0DIAN/market-vault/pull/335) received independent
final-candidate PASS on `01697da15fdf05304bca6a1a2351f3f90a9a1941`, including
85 associated tests and 324 bounded complete-report/CLI differential cases.
Natural RESEARCH_FAST PR CI
[38262393941/1](https://github.com/M0DIAN/market-vault/actions/runs/38262393941/attempts/1)
passed. Squash main `8d0ee586ff9e02e1e2273dcdc6dfeab83bec8cff` retains the
reviewed tree `8acdf7e853022e367124068af5bb55831a20ff81`. Its natural push
[38263166962/1](https://github.com/M0DIAN/market-vault/actions/runs/38263166962/attempts/1)
passed all 16 physical FULL jobs. This was actual FULL with
`POST_MERGE_REUSE=false` / `jobs_missing_surface`, not subset reuse. The longest
partition took 503 seconds. Independent post-merge review confirmed COMPLETE,
exact version 0.9.0 and clean synchronized main before Q66 implementation began.

## Q66 — reuse alpha-independent preparation within the existing suite

### Goal, plan and defaults

Separate the shared Ridge fitter's alpha-independent preparation from adding
alpha and solving. The preparation contains immutable TRAIN means/scales,
target centering, unregularized symmetric Gram matrix and target vector.
Each requested alpha still independently creates its regularized matrix,
solves it and returns its own model and predictions.

Only `_SelectionFitCache`, already owned by one strictly prepared Q49 suite
action, may retain preparations. Bind the key to the same prepared owner,
kind, ordered Features, actual TRAIN X/y, boundary and prediction support;
exclude only alpha from the existing raw-fit identity projection. Preserve
the existing alpha-specific complete-fit cache and result isolation. Pass a
private optional preparation slot through the two existing raw wrappers;
standalone callers without that slot still prepare every fit normally.
Do not cache quadratic input expansion or change selection loops.

A three-alpha actual `fit_quadratic_rows` prototype with 3,000 TRAIN rows,
600 prediction rows and six input Features (expanded width 27) reduced Gram
preparations 3→1 and dot products 1,134→378; all three solves and quadratic
expansions still ran. Complete models/forecasts (1,256,788 bytes) matched.
One unprofiled observation was 0.543369→0.303505 seconds (about 44.1% shorter).
This does not establish a 44% complete-suite improvement; actual suite
source verification, execution, serialization and other work remain.

### Acceptance and scope

1. Both representations and every existing alpha retain complete models,
   predictions, report/artifact bytes, choices and IDs against the baseline.
2. Same-owner/same-input alpha families prepare once while solving each alpha;
   changed X/y, Feature order, kind, boundary or observation support cannot
   reuse that preparation. New suite calls start fresh and reverify sources.
3. Preserve outside-family alpha behavior, numeric alpha identity, threshold
   postprocessing and mutation isolation. A failed fit cannot publish a model.
4. A real saved-source suite comparison proves complete results and work
   counts, with bounded unprofiled timing reported separately. Existing shared
   Ridge, intraday and suite regressions plus required CI remain authoritative.
5. Final-candidate independent review, required PR CI and exact-main CI pass.

Expected production scope: `research/ridge_baseline.py`,
`research/intraday_research.py`, `research/intraday_models.py` and
`research/intraday_selection_fit.py`, plus their directly relevant existing
tests and this record. Q65 is the delivery dependency; Q63's triangular Gram
and Q50's prepared-action ownership are existing technical dependencies.
No global fitting context, cross-action/window reuse, source bypass, new
solver/BLAS, alpha pruning, fitted-score reuse across different alphas,
quadratic-expansion cache, model format change or numerical correction.

### Q66 local evidence

Implementation starts from completed Q65 main
`8d0ee586ff9e02e1e2273dcdc6dfeab83bec8cff`. Both new linear/quadratic alpha-family
work-count cases were run against unchanged production first: each failed
because preparation ran three times instead of once. The candidate prepares
once and solves all three alphas, preserves the alpha-specific complete-fit
cache, and starts fresh for a different prepared action. Input/order/boundary/
support changes require new preparation; alpha numeric encoding still remains
part of the complete model identity. Failed solves do not publish cached models.

The existing shared Ridge, intraday ML, suite, selection and final TEST
regressions across eleven directly affected test files give **131 passed,
3 skipped in 505.62 seconds** on Python 3.11.17. The three skips are existing
PySide6-dependent GUI tests in the local environment; natural FULL CI supplies
that dependency. Existing dense-Gram, constant/adjacent-value, source admission,
canonical output and TEST-isolation assertions remain intact.

The pre-implementation saved fixture uses 36 sessions, two DEV folds, two
Features and a captured quadratic-alpha-2 source. That source is a fixture
choice, not a new default. The eleven relevant implementation blobs were
unchanged between the saved baseline and Q65 main. Actual public suite replay
retains all **12,623,988 bytes** and IDs across Q25 (1,933,002 bytes), Q31
(2,736,874) and Q36 (7,954,112), with original source/Q5 files unchanged.
A separate instrumented call confirms:

| Actual work in one public suite call | Before Q66 | Q66 |
|---|---:|---:|
| Strict ordinary-source reconstruction | 1 | 1 |
| Ordinary Ridge preparations / solves / quadratic expansions | 4 / 4 / 4 | 4 / 4 / 4 |
| Procedure Ridge preparations | 21 | 6 |
| Procedure solves | 21 | 21 |
| Procedure quadratic expansions | 12 | 12 |
| Fit identity projections/hashes | 43 | 64 |

The extra identity projection on each raw-fit miss binds preparations to all
existing inputs except alpha. Instrumented key-only time was 0.021003 seconds
before and 0.022309 after; these are attribution observations, not end-to-end
benchmarks. The unprofiled complete suite observation was **3.548624 → 3.795229
seconds**, so this small fixture does **not** demonstrate a wall-clock speedup.
No timing threshold is used for acceptance or claimed as a production guarantee.

For the separate 3,000-TRAIN/600-prediction/six-Feature input (quadratic width
27), all three standalone candidate fits retain the saved **1,256,788 bytes**,
SHA256 `266f58be72c6c8a31a6f86567b48cc15537e01018526522eb92789a891a3bcbc`.
One unprofiled candidate observation was 0.528282 seconds for three standalone
fits and 0.291939 seconds using the actual private preparation slot. A separate
instrumented probe confirms one preparation, three solves and three quadratic
expansions, with identical complete bytes. This bounded raw-fit probe excludes
suite identity hashing and source verification; it is neither a public source
admission test nor evidence of complete-suite latency improvement.

The production state is limited to immutable means/scales, target mean, Gram
and target vector inside the existing action cache; standardized training rows
are not retained. No dependency, schema, solver, candidate coverage, public CLI,
workflow or version change is included. Final independent review and natural
PR/exact-main gates are recorded in the associated PR.
