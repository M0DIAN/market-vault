# Intraday numerical correctness and measured efficiency: Q55–Q57

## Verified baseline and authorized package

Start from Q54 main `32c2bfd29b1a6ef68be89b302caf7a76525736de`, tree
`394e81cb7519de6b1918650465e28cbc4ffebc0d`, in `M0DIAN/market-vault`.
[Q54 PR #324](https://github.com/M0DIAN/market-vault/pull/324) is merged.
Its natural exact-main push [38201809612/1](https://github.com/M0DIAN/market-vault/actions/runs/38201809612/attempts/1)
is terminal SUCCESS. The remote main SHA and clean local/origin main were
verified before creating the Q55 feature branch.

The owner's 2026-10-12 request authorizes this three-task package:
in-scope fixes, tests, commits, push, PRs, independent final-candidate review,
conditional squash merge and exact-main CI verification. Follow the supplied
Development Workflow v2, Personal Local Tool Workflow v1, AGENTS.md and the
checked-in governance. Version remains 0.9.0. Each task begins implementation
only after the preceding task's merged-main gate succeeds. Read-only preparation
may overlap; each worktree has one writer, and final review is performed by an
agent that did not design or implement that candidate.

**Order: Q55 correct TRAIN-constant Ridge columns → Q56 remove redundant
serialization copies in recorded diagnostics → Q57 capture native selection
identities without repeated full-file parsing.**

## Assessment and counterevidence

Q1–Q54 already provide verified intraday inputs, actual-label-end purging,
linear/quadratic Ridge, fixed chronological inner model/threshold/joint
selection, explicit Freeze/TEST, risk and uncertainty, complete-family and
paired comparisons, recorded execution stress, market/sample evidence,
one-source three-procedure execution and native risk/inner-cost inspection.
See [Q49–Q51](intraday_procedure_efficiency_next.md) and
[Q52–Q54](intraday_selection_reliability_next.md). These remain completed
capabilities; this package addresses actual defects and measured overhead.

| Candidate direction | Decision and evidence |
|---|---|
| Shared Ridge constant-column arithmetic | Q55. `_column_stats` can give a mathematically constant TRAIN column a nonzero scale because `fsum(values) / n` rounds away from the original value. The existing constant-zero policy is consequently violated. |
| Recorded large-report serialization | Q56. Q53/Q41 copy already JSON-native trees through `intraday_data.json_values` before encoding. Existing plain canonical encoding produces identical complete reports without that copy. |
| Native source refresh | Q57. A real view change synchronously calls four source listeners; each `selection_source()` decodes the same complete ordinary artifact merely to obtain small immutable identities. |
| New cost-dependent outer research engine | Not needed. An ordinary source can already declare multiple cost groups; running Q49 for each explicit cost index performs the existing Q31/Q36 selection and actual outer refits at that cost. Q53 alone does not produce changed-winner outer performance, but this is not a missing research computation. |
| Reuse Q6 session/price validation | Defer. On the measured Q36 five-window diagnostic, 360 validations and price hashes cost 0.217 s of 2.679 s (about 8.1%). That observation does not justify changing the execution kernel in this package. |
| Optimize every serializer or add more diagnostics/models | Excluded. Q52's measured encoding saving was only about 0.06 s; no new observed research result justifies more search axes, learners or report types. |

Measurements use Python 3.11.17 and an existing synthetic Q54 study fixture,
not live market evidence or a trading-profit experiment. They identify concrete
software work; they do not establish production latency guarantees.

## Shared defaults and boundaries

- Preserve the existing ordered Features, model/threshold families, alphas,
  chronological windows, label purging, FIRST_DECLARED ties, execution rules,
  cost scenarios and complete evaluated support. No TEST-driven selection.
- No new dependency, learner, Feature, optimizer, persistent cache, storage
  format, data collection, source overwrite, deployment, release or live trade.
- Q55 repairs the already-promised TRAIN-constant-to-zero behavior. It does
  not introduce a new normalization rule or silently classify near-constant
  columns as constant. Existing v1 schemas and algorithm labels remain.
- Existing saved bytes stay immutable and readable. An older artifact affected
  by the Q55 bug may no longer reproduce its recorded fit/report under corrected
  code. Existing strict replay must report that mismatch; it must not relabel
  the historical result, overwrite it or claim that every old ID is unchanged.
  A fresh run records its corrected model/report and corresponding content IDs.
- Q56/Q57 are behavior-preserving optimizations: complete report bytes, IDs,
  supported failure behavior and captured-input/stale-result boundaries remain
  unchanged. Neither optimization replaces validation with an unverified cache.

## Q55 — exact TRAIN-constant Ridge columns

### Goal and technical plan

Make every exactly constant TRAIN Feature have zero population scale and zero
coefficient, including the Ridge layer applied to generated quadratic terms.
Detect exact equality before computing the mean; use that common value as the
mean. Keep the original `fsum / n` and variance arithmetic for every nonconstant
column. Preserve float and positive-zero output conventions. Do not add an
epsilon threshold, change regularization or rewrite the solver.

The defect is reachable through `evaluate_ridge_baseline`, ordinary intraday
`fit_ridge_rows`, Q25/Q31/Q36 and the second Ridge stage of quadratic models.
For 710 TRAIN rows with `x=0.03`, the old scale is approximately
`3.469446951953614e-18`; a shifted validation Feature can then change the
prediction despite TRAIN having no Feature variation. A symmetric six-row
quadratic example also gives its constant generated square a false coefficient.
Q23's first-stage constant protection does not cover this shared second stage.

### Acceptance and scope

1. The same focused regression fails because of the numerical defect on the
   old implementation and passes on the candidate. Validate the public baseline
   entry, actual intraday fitter and generated quadratic constant term.
2. Independently computed TRAIN means are the predictions when no predictive
   direction exists, including changed VALIDATION Feature values. Scales and
   coefficients are exactly zero, not approximately close to zero.
3. A nonconstant column differing by one representable float retains its
   variation and the original arithmetic. Existing nonconstant numerical,
   TRAIN-only fitting and model-identity regressions continue to pass.
4. Existing artifact readers/replay behavior and required CI are retained.
   No historical saved study is rewritten or automatically re-run on TEST.

Expected changes are `research/ridge_baseline.py`, the existing baseline and
intraday numerical test files, and this task record. Numerical effects are made
explicit in the PR. No new learner/version migration, general conditioning
work, prediction formula change or broader historical-data audit.

### Q55 local evidence

The five new numerical cases ran against the original production implementation
first: **4 failed, 1 passed in 0.29 s**. The failures reached the actual numerical
defect; the one-ULP nonconstant counterexample already passed. After the fix,
`test_ridge_baseline.py` and `test_intraday_research_analysis.py`, selected with
`-k ridge`, gave **27 passed, 113 deselected in 225.71 s** on Python 3.11.17.
This included the existing real Q5/saved-source/installed-CLI quadratic checks,
not a full local suite. Temporary paths were outside the repository. Hygiene,
release/version 0.9.0 and whitespace checks passed. Historical affected-artifact
Open/Replay behavior above is a code-based compatibility assessment, not a claim
that a separate old-bad-artifact end-to-end fixture was executed.

### Q55 remote closure

[PR #325](https://github.com/M0DIAN/market-vault/pull/325) received an independent
final-candidate PASS for head `e02c288988f7866b91f5999dd7c347b2c8da0ac3`, tree
`5c2f1ab8741bf2c299a8a86a52322c686e3d371c`. The reviewer independently exercised
actual base-source counterexamples, quadratic squares/interactions, signed zero
and unchanged nonconstant arithmetic. Natural FULL PR
[38208068023/1](https://github.com/M0DIAN/market-vault/actions/runs/38208068023/attempts/1)
passed all 16 required jobs, the existing job-set validator and the package
version/attestation checks. Its longest partition was 600 s.

The authorized squash produced main `1a03ae5f3d083ad6397ab13a74cd651a10dfd08f`,
with the same reviewed/tested tree and Q54 main as its sole parent. Natural main
[38209196363/1](https://github.com/M0DIAN/market-vault/actions/runs/38209196363/attempts/1)
is terminal SUCCESS. Its actual plan log reports `POST_MERGE_REUSE=true` and
`verified_full_pr_tree_equivalence`, binding PR #325, that final head, PR run
38208068023, tested merge `d54f765e7da99c51630c4faf19000ee4ecf50e0c`, and the
identical main/tested tree. All five reuse-path jobs succeeded; the partition
matrix was skipped by that existing verified contract. Q56 started only after
this gate and a fresh remote-main/clean-worktree check.

## Q56 — avoid copying already JSON-native diagnostic reports

### Goal and technical plan

Reduce Q53 inner-cost and Q41 execution-stress overhead while retaining their
complete evidence. Their source is an admitted immutable `StrategyExperiment`;
the derived trees contain decoded JSON values and newly constructed JSON-native
fields. Reuse the existing `strategy_experiment.canonical_json` encoder and
compute the existing SHA-256 over those exact bytes. Keep the newline, UTF-8,
key ordering, numeric encoding and nonfinite rejection unchanged.

Do not replace `intraday_data.canonical_json` or `json_values`: the general
helper also handles dates and container conversion, and replacing its contract
is unnecessary. No new encoder, serialization framework or optional dependency.

The bounded pre-implementation API comparison retained every report byte and ID:
Q53 produced 35,375,278 bytes in 2.410/2.296 s on the old path and
1.802/1.772 s with the prototype; Q41 produced 53,614,148 bytes in
3.268/3.223 s and 2.586/2.718 s respectively. These are local observations,
not CI or future-input performance promises.

### Acceptance and scope

1. Compare complete real saved-study diagnostic outputs, including all member
   accounts, unavailable states, identities and final report digests, with the
   old encoder as an independent compatibility oracle.
2. Retain the existing CLI and numerical/failure tests. Unsupported and
   nonfinite inputs must still fail; no Q5, fit, Freeze or TEST is introduced.
3. Measure the actual public analysis path on the same inputs and confirm
   removal of the extra tree traversal/copy. Do not assert wall-clock thresholds
   in permanent tests or discard evidence to obtain a speedup.

Scope: `research/intraday_inner_cost_sensitivity.py`,
`research/intraday_procedure_stress.py`, their focused existing tests and this
record. No Q52 expansion, execution-kernel changes, report trimming, generic
serializer changes or persistent result caching.

### Q56 local evidence

The production change is six added and six removed lines across the two
declared report modules. The two existing test files were left unchanged:
**17 passed in 119.80 s** on Python 3.11.17. They retain the unmodified
`intraday_data.digest` as an independent full-report identity oracle, complete
account/cost calculations, unavailable-state coverage, source-file immutability
and whole CLI-report equality. No duplicate test or permanent timing gate was
added.

An actual candidate API comparison loaded the old modules from Q56's base main
`1a03ae5f3d083ad6397ab13a74cd651a10dfd08f`. On the same saved Q54 Q36 fixture,
complete reports, including IDs, were byte-for-byte equal. The 17,400,706-byte
input had SHA-256
`f258933112144be8871e524e7a1c882a0708139b6ac5aff9834aaa5f56192338`:

| Report | Complete bytes | Old API | Candidate API |
|---|---:|---:|---:|
| Q53 inner-cost sensitivity | 35,375,278 | 3.219602 s | 2.038068 s |
| Q41 execution stress | 53,614,148 | 3.201175 s | 2.765924 s |

These are one bounded call per path after loading the source, not repeatable
latency guarantees. The separate pre-implementation `tracemalloc` experiment
measured transient allocation peaks of 205,383,334 → 162,846,846 bytes for Q53
and 282,431,407 → 220,146,717 bytes for Q41. Those peak figures describe the
prototype comparison; they are neither process RSS nor a new candidate memory
test. The implementation removes the same redundant conversion and preserves
the generic encoder's broader date/container contract.

### Q56 remote closure

[PR #326](https://github.com/M0DIAN/market-vault/pull/326) received an independent
final-candidate PASS for head `8f08eeab8995ff59deb9a06b36d8b31e7018234b`, tree
`1ecc64d3819a9872a0ded4f16456f05baf965078`, with Q55 main as its sole parent.
The independent checkout repeated the unchanged two-file regression selection:
**17 passed in 115.08 s**. Actual base/candidate API comparisons retained every
Q53/Q41 byte and ID, including injected unavailable/partial failure paths.
The reviewer also verified that the generic encoders' real date/custom-container
differences are not reachable through these two admitted JSON-native sources.

Natural PR [38209938241/1](https://github.com/M0DIAN/market-vault/actions/runs/38209938241/attempts/1)
was terminal SUCCESS at the actual `research_fast` tier. Its five planned jobs
succeeded; the full partition matrix was intentionally skipped. This is subset
CI evidence, not a FULL run or a reusable FULL attestation.

The authorized squash produced main `37d1bd8b4720d56ebf46d2852eca6346b50d6dba`,
with the same reviewed/tested tree and Q55 main as its sole parent. Natural main
[38210531542/1](https://github.com/M0DIAN/market-vault/actions/runs/38210531542/attempts/1)
ran FULL because `research_fast_is_pull_request_only`; all 16 required jobs
succeeded and the complete job-set validator passed. The actual plan reported
`POST_MERGE_REUSE=false`, reason `jobs_missing_surface`, so no reuse is claimed.
Version remained 0.9.0; the longest partition was 561 s. Q57 implementation
started only after this exact-main gate and a fresh remote-main/clean-worktree
check.

## Q57 — lightweight native selection capture

### Goal and technical plan

When `_apply_child` publishes one ordinary immutable content snapshot, capture
its experiment ID and ordered candidate IDs as immutable scalar/tuple metadata.
`selection_source()` then returns those IDs, the current selected cost/candidate
indices, the actual saved path and the original immutable content bytes without
decoding the full document again. Do not derive captured identity from the
mutable presentation tree on each call.

Reuse the four existing listeners and their revision/stale-callback rules.
Saving, opening another source, exporting a Q10 ordinary child and selecting
another candidate must keep path, content and identities aligned. Unsaved
sources remain ineligible. There is no new signal graph or UI redesign.

On an existing 3,579,174-byte ordinary study, a real view change caused four
full JSON decodes. Three local calls took 0.089/0.085/0.087 s, of which
0.084/0.080/0.082 s was parsing. The constant-time descriptor prototype returned
the same capture. This finding concerns candidate/view/relevant draft changes;
ordinary table pagination does not always emit the same signal.

### Acceptance and scope

1. A real native controller/production session uses the ordinary source through
   the actual selection/view controls. Captures match the immutable bytes;
   repeated refreshes no longer decode the full ordinary report.
2. Candidate/source changes, saved paths and ordinary scenario-child export
   retain correct identities and admission. A returned dictionary or mutable
   presentation-tree change cannot alter the immutable capture metadata.
3. Existing late-result rejection, failed-action recovery and save/reopen
   behavior remain. Execute the directly affected real Qt flow; optional Qt
   skips in CI are not evidence of native success.
4. The naturally triggered Windows validation must finish successfully for
   the final candidate. If a blocking job requires partitioning, preserve every
   existing native target and all QML nodes, the original platform settings,
   timeouts and required check, with a fail-closed aggregate.

Scope: `desktop/intraday_research.py`, directly related existing native tests
and this record. The observed Windows timeout additionally brings
`.github/workflows/adaptive-window-windows.yml` and the existing risk-view
test's navigation helper into the authorized in-scope repair below. No QML
layout changes, listener framework, source revalidation bypass, background
cache service or automatic research/Freeze/TEST action.

### Q57 local evidence

The production change is six added and three removed lines in the controller.
The existing Main.qml test adds 35 lines and removes two; the suite and Freeze
regressions remain unchanged. There are no QML, listener or state-machine changes.

The complete production Main.qml flow passed on Python 3.11.17 / PySide6 6.11.2:
**1 passed in 344.25 s**, without skips. Its native subprocess emitted
`REAL_PLAN_DRAFT_QML_OK`. The added assertions use an actual saved 4,437,118-byte
ordinary scenario child at cost/candidate (0, 1), then a 12,663,405-byte grid
at (1, 1). Real candidate/view controls retain the full immutable capture,
including saved path and IDs. Explicit same-source bytes/string `json.loads`
counts are zero. Perturbing the presentation IDs or clearing a returned capture
dictionary cannot change subsequent captures; test instrumentation is restored.

The two unchanged, directly related guards gave **2 passed in 133.05 s**,
without skips: the native suite's unavailable/stale-success/stale-failure/retry
flow and the controller's immutable Freeze capture with independent proofs.
They cover candidate/locator changes and changes back, retention of prior saved
results, recovery after failure, unsaved-to-saved path/admission updates and
selection changes after a worker has captured its input.

Both commands passed on their first execution. All native evidence is from the
actual candidate with explicit source `PYTHONPATH`, offscreen Qt/software Quick
rendering and repository-external temporary directories. No local full matrix,
new benchmark or permanent wall-clock assertion was added. The earlier
3,579,174-byte timing observation is a pre-implementation controller probe;
the candidate's production-Main.qml evidence proves removal of full-source
parsing, not a new measured end-to-end latency guarantee. Final independent
review and remote gate identities are recorded in the associated PR.

### Q57 Windows gate counterevidence and in-scope repair

The initial published candidate was
`4096e87cc762c159f02af5dfcc60448f0ecb3cf0`, tree
`555ebedd82473f9ba9d5f7684afe906a1bb844e9`, in
[PR #327](https://github.com/M0DIAN/market-vault/pull/327).
Its core [FULL CI 38213027109/1](https://github.com/M0DIAN/market-vault/actions/runs/38213027109/attempts/1)
completed all 16 expected jobs successfully, with a longest partition of 614 s.
The independent reviewer also passed the three directly affected native nodes:
**3 passed in 466.72 s**, with no errors, failures or skips. The reviewer's
first execution lost its tool transport before producing a terminal pytest
result; one justified recovery execution produced the terminal result, JUnit
and native completion markers. The interrupted execution is not test evidence.

These results did not satisfy the complete merge gate. The separately triggered
[Windows run 38213027033/1](https://github.com/M0DIAN/market-vault/actions/runs/38213027033/attempts/1)
was CANCELLED; the check annotation explicitly says that its single job exceeded
the maximum execution time of **20 minutes**. The full-file pytest step printed
18 success dots, `F`, then two further dots before cancellation, without a
failure traceback. Actual collection found 22 nodes; position 19 is
`test_actual_qml_offline_performance_views_in_both_languages`.
Running that complete unchanged node locally against the initial candidate
gave **1 failed in 244.18 s**: its native subprocess exceeded the existing
**120-second** limit. This is a separate reproducible local counterexample;
it does not reconstruct the missing Windows traceback. No merge occurred.

The repair retains the original Windows workflow triggers, permissions, native
platform checks, dependency installation and 20-minute worker timeouts. Four
independent Windows jobs now run the original work:

| Worker | Coverage |
|---|---|
| `windows-native` | Existing screens/DPI and actual startup probes, native placement, geometry/preferences and small-workspace QML checks, each once. |
| `qml-plan-grid` | Six nodes selected by `plan or continue_candidate or parameter_grid`. |
| `qml-saved-comparison` | Ten nodes selected by `saved and not (plan or continue_candidate or parameter_grid)`. |
| `qml-scenario-risk-final` | The seven-case complement: `not (plan or continue_candidate or parameter_grid or saved)`, including the two page cases of the existing risk-view test. |

Actual collect-only execution of the expressions read from the modified YAML
proved **23 = 6 + 10 + 7**, with no missing, duplicated or extra cases. The
original 22 test functions remain; the one long risk-view node is now two page
cases as described below. Both risk-view cases and final Freeze E2E remain in
the final group. Native Windows
steps still use the Windows Qt backend; QML steps still use offscreen/software.
The existing `native-qt-and-qml` check becomes an always-evaluated aggregate
that requires all four explicit dependency results to be `success`. Running
its actual Bash script accepted all-success and rejected all 16 cases formed
by one dependency being failure, cancelled, skipped or empty. This local
check verifies shell rejection, not remote Actions scheduling.

Verbose unbuffered pytest output, a complete failure traceback and JUnit uploads
make a failed node identifiable. A failed shard stops at its first failure;
other independent workers continue. That candidate cannot pass the aggregate.
A successful final candidate must still execute every original target and all
23 QML cases. No assertion or timeout is weakened to satisfy the gate.

The first repair attempt changed only the existing risk-view node's
`choose(name, index)` to read the displayed current index and send the necessary
real Up/Down key events. Previously each call sent Home followed by every Down
step, repeatedly rendering intermediate views even for adjacent targets.
That attempt kept focus, waits, target-index assertions, all
views/languages/source/proof checks and the native 120-second limit.

That helper-only attempt did not resolve the full node: its complete rerun
exited 1, with JUnit **1 failure, 0 errors, 0 skips, 256.224 s suite time**, again
reporting native `TimeoutExpired` at 120 seconds. Its screenshots reached both
pages' basic bilingual views and the development page's bilingual risk views;
the remaining final-page risk and source-replacement work had not completed.
This failed attempt was not published or accepted as a passing repair.

The same test is therefore parametrized by `development` / `final` page. Each
case still executes its page's entire basic and risk loops in both languages.
The development case retains the complete source/candidate replacement,
paging, zero-trade and partial-record sequence. Both cases preload the original
TEST and verify that its content, selection content and proof summary remain
unchanged. The original 54 embedded-script assertions are retained; page
filtering changes which case executes each original page loop, not its body or
targets. Actual Qt focus/key events, source immutability, offline prohibitions,
completion marker and **120 seconds per native subprocess** remain. Existing
session-scoped study fixtures are shared by the two pytest cases.

The first full page-split run passed development but failed final on a strict
visibility assertion (JUnit: 2 cases, 1 failure, 0 errors/skips, 279.616 s).
The final case failed in 35.637 s, not at the subprocess timeout. A complete
isolated native replay confirmed that the viewport changed from 351 to 294
pixels after the first scroll; the control consequently needed another 57
pixels of scrolling. The existing `reveal` helper now processes events,
remeasures geometry and scrolls for at most five iterations, retaining the
original 30 ms wait and the exact final fully-visible assertion. It neither
accepts clipping nor changes production layout. With unchanged saved inputs,
the complete final-page native-script diagnostic finished in 51.918 s, exit 0,
and emitted `REAL_INTRADAY_RISK_VIEWS_OK`; this diagnostic is not a pytest PASS.

The subsequent complete two-case pytest run passed final in 48.638 s but
development again exceeded its native 120-second limit (JUnit: 2 cases,
1 failure, 0 errors/skips, 312.510 s). Thus page splitting and geometry settling
alone did not establish adequate completion behavior. This failed candidate
was not published or accepted. The closed ComboBox's arrow events still
activated every intermediate choice and triggered work for unasserted views.

The final `choose` repair uses the real popup interaction already present in
two other QML flows in this file: Space opens it, Up/Down moves the highlighted
option, and Return commits the requested option once. Three additional
assertions verify initial and target highlights and that `currentIndex` stays
unchanged until commit. Equal current/target indices send no keys. An actual
Main.qml probe verified popup visibility and both forward/backward navigation;
this is not direct property assignment or synthetic signal emission.

The complete final embedded scripts were then exercised sequentially with
fresh settings/preferences and independent copies of the same saved inputs:
development finished in 93.745 s and final in 40.600 s. Both children exited 0,
emitted `REAL_INTRADAY_RISK_VIEWS_OK`, retained the 120-second limit and left
original/copy bytes unchanged. These diagnostic runs avoid regenerating the
research fixtures and are not counted as pytest passes. The original 54
embedded assertions remain, with the final-binding and three popup assertions
added. No production/QML change, new test framework or timeout increase was
introduced by these test repairs.

The final complete two-case pytest run, including its original research fixture
preparation, exited 0: **2 passed, 0 errors, 0 failures, 0 skips**, JUnit suite
time **279.212 s**. Development took 234.783 s including fixture setup; final
took 43.654 s. The external wrapper took 282.045 s. These are full pytest
results, distinct from the native-only diagnostics above. AST comparison
confirmed all 54 original assertions remain among the final 58 and that every
other module-level test is unchanged from the initial Q57 candidate. Hygiene,
release/version 0.9.0 and whitespace checks passed. The actual classifier on
the four-file cumulative diff requires FULL; the existing reuse control-plane
check returns `control_plane_changed`.

The replacement candidate requires its own exact-head independent review and
natural core and Windows CI results. The initial candidate's PASS and core
FULL evidence above are historical evidence, not replacement-candidate approval.
Because the repair touches a workflow path, the existing control-plane
exclusion rejects post-merge FULL reuse: Q57's exact merged main must complete
its own natural normal FULL run.

## Validation and delivery

Use the tested checkout's explicit `PYTHONPATH`, Python 3.11 and repository-external
temporary test directories. Run meaningful affected regressions, whitespace,
hygiene and release/version checks locally. Natural PR CI follows the actual
checked-in classifier. A `research_fast` PR is subset evidence and cannot mint
a FULL attestation; its natural main push is forced to FULL and must finish
successfully. A FULL PR can be reused only after the existing main verifier
proves the required run/attempt and Git-tree equivalence. Do not change paths
or add redundant tests to manipulate a tier.

The existing eleven-partition ownership and complete core FULL test selection
remain. Q54's longest PR job was 620 s, Q55's was 600 s, Q56's main FULL maximum
was 561 s and the initial Q57 FULL maximum was 614 s; these observations do not
justify changing that matrix. The separate Windows workflow did hit its
20-minute job limit, so the narrowly scoped partitioning above is necessary.
Final Windows success and observed worker durations must come from the new
candidate's natural run, not estimates or the cancelled initial run.

For each task: commit the stable candidate; independently review that exact
head; wait for successful required natural PR CI; recheck current head/base,
tree and version; squash merge under the existing owner authorization. Verify
the exact resulting main's natural push to terminal success. Post-merge reuse
is claimed only from the checked-in verifier and the actual run's evidence;
otherwise FULL fallback is authoritative. Stop after Q57's main gate.
