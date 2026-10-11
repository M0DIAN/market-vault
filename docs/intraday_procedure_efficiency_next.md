# Same-source procedure workflow and computation: Q49–Q51

## Baseline, decision and delivery

This package starts from verified Q48 main
`fd87aa3594c43c9563e8a821752a66a6ce0f8308`, tree
`be74cf142fabde6c74a7336917164b43f9d0843e`, in `M0DIAN/market-vault`.
[Q48 PR #318](https://github.com/M0DIAN/market-vault/pull/318) was squash
merged after independent final-candidate review and successful natural PR CI.
Its exact-main natural push
[38161391390/1](https://github.com/M0DIAN/market-vault/actions/runs/38161391390/attempts/1)
completed a real FULL run, with all sixteen jobs successful. The plan reported
`POST_MERGE_REUSE=false`, reason `control_plane_changed`.

The owner's 2026-10-12 Japan-time request authorizes this three-task package,
in-scope repairs, tests, commits, push, PRs, independent final-candidate review,
conditional squash merge, and exact-main verification before proceeding to
the next item. Follow the supplied Development Workflow v2 and Personal Local
Tool Workflow v1 together with checked-in repository governance.

**Order: Q49 one-source three-procedure execution → Q50 action-local identical
fit reuse → Q51 native run, save and comparison workflow.** Each implementation
starts from the preceding task's successfully verified main. Read-only planning
may overlap; implementations and merges remain sequential. Version stays 0.9.0.

## Why this direction

Q1–Q48 already provide verified intraday inputs, actual-label-end purging,
fixed linear/quadratic Ridge, chronological model/threshold/joint selection,
Freeze/TEST V1–V4, prediction and objective diagnostics, conditional return and
family evidence, execution stress, and actual market-data/sample dependencies.
This package makes those existing studies easier and cheaper to use together.

| Candidate direction | Decision and evidence |
|---|---|
| Run and compare the existing same-source Q25/Q31/Q36 studies | First priority. Their separate evaluators each strictly rebuild Q5 and reconstruct the complete identical ordinary source. Q39/Q40 then require these same-source studies as inputs. |
| Reuse identical fits inside that one action | Second. Q25 and Q36 fit the same six-member model family on the same inner inputs; Q31 can also use an identical fixed recipe. Each procedure's scoring, selection and accounts still remain distinct. |
| Connect the native run/save/compare actions | Third. Existing native entries require separate runs and saved-file reopening before Q39/Q40. The new entry produces the same standard studies and hands them to existing analysis. |
| Add another market-evidence report | Defer. Q46–Q48 already use one strict Q5 reconstruction per action; Q48 does not fit. No independent observed market input was supplied to justify a new empirical claim. |
| Add a learner, Feature family, history-search axis or TEST version | Defer. No observed study result establishes a need to enlarge the search space. Existing selection and final-evaluation capabilities are retained. |
| Optimize the Q6 numerical execution kernel | Defer. Its repeated grid preparation is measurable, but sharing whole-source preparation addresses a larger observed cost with a narrower change to the numerical core. |

The baseline code was checked for counterexamples: ordinary cost scenarios
already share fold fits inside one prepared context; Q31 already reuses the
fixed source's outer models; Q34/Q35/Q39/Q40 are recorded-only; Q33 deliberately
reconstructs its complete declared source; Q46–Q48 already share strict source
verification within their individual actions. None of those completed
capabilities is claimed as new work.

A bounded Python 3.11.17 measurement used an existing synthetic same-source
fixture with four outer folds and the `return_2` Feature. Loading the immutable
ordinary source took 0.445 s, strict Q5 reconstruction 10.647 s, preparation
from that verified object 0.079 s, and complete ordinary evaluation 0.233 s.
The reconstructed ordinary report equalled the saved report. These are local
engineering timings, not production guarantees. Removing two repeated Q5
reconstructions is a concrete opportunity; it does not imply that total
runtime or CI duration will fall by the same ratio.

## Shared defaults and compatibility

- Exactly Q25 (six-model inner MSE), Q31 (fixed-model economic threshold),
  then Q36 (24-member joint economic selection), in that order. No subsets,
  automatic winner, larger family or changed tie break.
- One explicit ordinary saved DEV source, one captured cost/candidate reference
  and an optional explicit relocated Q5 path. Preserve the source's full data,
  Feature order, training/holdout schedule, purge rules and execution policy.
- Strict Q5 admission and complete ordinary reconstruction remain mandatory
  for each new action. A previous action, filename, ID alone or saved report
  never substitutes for current source verification.
- Each procedure retains its own window construction, availability gates,
  models, recipes, predictions, complete accounts and final DEV declaration.
  Q25's COMPLETE-target scoring gate must not be imposed on Q31/Q36's economic
  holdouts. An unavailable member remains in the three-member result.
- Return the existing immutable `StrategyExperiment` objects. With identical
  source path, data relocation, metadata and environment, complete canonical
  roots and IDs must equal the existing independent entry points. No new
  selection/TEST artifact grammar or algorithm version is introduced.
- Keep source files immutable. Saving uses the existing individual experiment
  writer; each explicitly selected destination keeps its current no-overwrite
  and idempotent-identical-content behavior. Multiple saves are not advertised
  as one atomic transaction; a failure reports already completed publications.
- No persistent cache, global cache, download, extra dependency, automatic
  Freeze/TEST, real trading, release, deployment or runtime-state replacement.

The existing research methods supply these unchanged defaults:

| Item | Default retained by the package |
|---|---|
| Q25 model family and objective | Linear then quadratic Ridge, each with alpha `0.1, 1.0, 10.0`; minimize pooled COMPLETE-target MSE. |
| Q31 threshold family and objective | Keep the saved representation, alpha and Feature order; thresholds `0, 5, 10, 20` basis points; maximize inner net compounded return. |
| Q36 joint family and objective | The same six models crossed with four thresholds; model outer / threshold inner order; maximize inner net compounded return. |
| Inner chronology | Last five history days form the inner holdout; at least ten preceding inner training days; retain the source's actual-label-end purge. |
| Economic execution support | Q31/Q36 use all READY holdout observations and the complete declared session price grid; COMPLETE inner scoring labels are not required. |
| Ties and decisions | FIRST_DECLARED; LONG only when score is strictly greater than the selected threshold, otherwise FLAT. |
| Outer models | Q31 reuses the verified original fixed models/scores; Q25/Q36 refit the chosen recipe on the complete purged outer TRAIN. |
| Final DEV boundary | First TEST session open; record the final DEV recipe without fitting or evaluating TEST. |

These values come from the existing
[Q25](../src/market_vault/research/intraday_inner_selection.py),
[Q31](../src/market_vault/research/intraday_threshold_selection.py) and
[Q36](../src/market_vault/research/intraday_joint_selection.py) methods. They
are not new search axes or a replacement algorithm contract.

## Q49 — one source, three existing procedures

### Goal and implementation

Provide a small Python runner and a settings-independent CLI that generate the
complete Q25/Q31/Q36 studies from one captured ordinary source. A file entry
reads that source once; a typed immutable-source entry supports the later
native capture workflow while retaining the explicit source locator.

Validate the common selection and algorithm contracts, strictly rebuild Q5
once, prepare its actual context once, and reconstruct the complete ordinary
report once. Pass only the internally verified preparation to the existing
three evaluators. Their independent public run/replay entries continue to do
their own strict preparation. Do not expose a boolean that lets an external
caller assert that an arbitrary report is verified.

Compute the three standard studies in fixed order and retain every member,
including complete UNAVAILABLE reports. A real source, binding or computation
failure fails the action; it cannot silently produce a smaller family. Optional
CLI saves use three explicit member destinations and the existing writer.

### API and command line

`evaluate_intraday_procedure_suite(source, *, source_experiment_path,
expected_experiment_id, cost_index, candidate_index, expected_candidate_id,
intraday_data_file=None, name="", notes="")` accepts one immutable
`StrategyExperiment` and its explicit source locator. It returns a tuple of
three standard experiments in Q25/Q31/Q36 order. It does not reopen the source
locator after capture. `run_intraday_procedure_suite(source_experiment_path,
...)` is the file wrapper, which reads and validates that ordinary source once.

The settings-independent command is `research-intraday-procedure-suite`. It
requires `--source-experiment`, `--expected-experiment-id`, `--cost-index`,
`--candidate-index` and `--expected-candidate-id`, and accepts `--intraday-data`
for explicit relocation. The optional `--q25-experiment`, `--q31-experiment`
and `--q36-experiment` each name an individual save destination. `--name` and
`--notes` apply the same explicit metadata to each member. JSON output retains
the full three studies, their identities and individual publication outcomes.

### Acceptance

1. A real synthetic Q5/ordinary source produces the same three complete
   canonical studies and IDs as the independent public runners with identical
   captured inputs. The reports must agree in all fields, not only final return.
2. Counting the actual admission/evaluation boundaries proves one strict Q5
   load, one prepared context and one complete ordinary reconstruction.
3. Source/candidate/algorithm mismatches fail before a successful suite is
   returned; current source and Q5 verification are not weakened.
4. A Q25 scoring-unavailable case preserves Q25's complete reason while the
   economic procedures retain their own availability. Existing Q39/Q40 admission
   still handles the complete standard studies correctly.
5. The real CLI produces the three studies, supports explicit immutable saves,
   reports partial publication accurately, and can recover using the existing
   writer's semantics.

### Scope and exclusions

The three selection modules, a small shared-source preparation/runner module,
a thin CLI and its real router, one focused test file and this task document
are the expected surface. No fit cache yet, no Q6 changes, no new GUI, no
generic pipeline or job scheduler. Q50 and Q51 remain planned until their
respective preceding main gate succeeds.

### Q49 implementation and local evidence

The fixed runner, captured-source API and CLI are implemented. The ordinary
source content, original selection and Q5 locator bind the private preparation;
each original independent run/replay still performs its own strict preparation.
No fitted-model reuse is included in Q49.

On Python 3.11.17, the real synthetic non-first cost/candidate regression took
13.913 s for the three independent runs and 5.959 s for the suite. Ordinary
source reads, Q5 reads, strict Q5 verification, context preparation and complete
ordinary reconstruction each fell from three calls to one. All three complete
canonical roots and IDs equalled the independent results. The measured time
is one bounded local observation; the regression asserts work counts and full
content equality, not a wall-clock threshold.

`tests/test_intraday_ml_procedures_suite.py` passed all four tests in 47.04 s.
They cover real byte equality, source/candidate binding, a re-signed hidden
unselected-source discrepancy, immutable capture without reopening, complete
short-history UNAVAILABLE studies, and actual settings-independent console
publication. A second-member file conflict preserves the first saved file and
reports the third as unattempted; a new-path retry reuses the first identical
file and saves the remaining members.

The three original real-source/run/replay representative tests passed in
49.67 s. Three existing focused window tests also passed in 0.20 s, retaining
Q25's missing-score gate and Q31/Q36's economic use of READY holdouts without
COMPLETE scoring targets. This last evidence is window-level. An attempted
all-short-session full-Q5 example was rejected by the sealed calendar; no
calendar exception was added and it is not claimed as a reachable full-Q5
mixed-availability case.

Repository hygiene, release/version 0.9.0, diff whitespace and actual partition
coverage passed. The new test resolves to `intraday_ml_procedures`; no workflow
or partition configuration changed. Independent review found and resolved a
stdout-publication error whose envelope could retain SUCCESS; the corrected
CLI reports FAILED with exit 1 and preserves computed studies and completed
saves. The focused real CLI/save test, including the new reporting probe,
passed in 14.96 s. An independent isolated probe also verified retention of
all three completed saves after stdout failed.

### Q49 completed mainline gate

[PR #319](https://github.com/M0DIAN/market-vault/pull/319) received fresh
independent final-candidate PASS at
`7429ac7bb7e94ce2624cf0abd96dc3ed90a91eaf`, tree
`9971a7b9b8a6fd58c7cace9da26a1f1f8317c2f0`. Natural PR FULL
[38166192471/1](https://github.com/M0DIAN/market-vault/actions/runs/38166192471/attempts/1)
completed with all sixteen required jobs successful; actual candidate-source
`check_jobs` returned `(True, None)`, with every raw job bound to that head,
run and attempt. The earlier pre-repair run was superseded and cancelled;
none of its results substitutes for this final-candidate evidence.

The authorized squash main is
`fcde2eb340a76522b3eeca5f66ac7d7a9d6295ab`, with the same tree and the single
parent `fd87aa3594c43c9563e8a821752a66a6ce0f8308`. Its exact natural main push
[38167436490/1](https://github.com/M0DIAN/market-vault/actions/runs/38167436490/attempts/1)
completed successfully. The actual plan reported `POST_MERGE_REUSE=true`,
reason `verified_full_pr_tree_equivalence`, binding PR #319, final head
`7429ac7`, PR run `38166192471`, tested merge
`561d9873f20079e4847e2fec133c8fb72ccdfae0`, and the identical tested/main tree.
Five required non-partition jobs succeeded; the unexpanded partition job was
skipped as planned. This is verified reuse, not a second FULL execution.
Q50 implementation starts only after this terminal gate and a fresh main check.

The final PR's longest functional job was the existing strategy partition
(671 s); `intraday_ml_procedures`, which includes the new suite file, took
551 s. Its new suite test call times were 15.98, 6.11, 3.17 and 2.60 s. Keep the
existing eleven-way CI topology: this one observation does not establish a
need to move tests or change the control plane.

## Q50 — identical fits shared within one action

### Goal and implementation

Use Q49's bounded action lifetime to reuse physically identical model fits and
raw scores. Keep every procedure's conceptual fit/refit and evidence records;
physical reuse does not remove family members or change research semantics.

The private reuse identity binds the verified source/context plus model
representation, alpha, ordered Features, ordered actual training inputs and
targets, training boundary and ordered prediction inputs. Matching row keys
alone do not authorize reuse of different values. The existing ordinary
`(fold_index, type, alpha)` key is scoped to one prepared context and must not
be copied into a broader cache.

Cache model/raw-score results only. Derive fresh prediction records using each
recipe's strict `score > threshold` decision rule, and prevent mutable returned
evidence from coupling the three studies. A fixed source alpha outside
`0.1, 1.0, 10.0` remains its own fit. The cache is created and discarded inside
the suite action; individual public entry points keep their existing behavior.

### Acceptance

1. Complete canonical reports and IDs remain equal to Q49 and the independent
   runners on real linear/quadratic sources, including family order, selected
   recipes, scores, actions, ledgers and UNAVAILABLE evidence.
2. Instrumented real fits prove a reduction in duplicate work. For each shared
   available inner window, Q25/Q36's identical six fits run once; a Q31 recipe
   outside that family still runs separately.
3. Different training values/targets, Feature order, boundary or prediction
   support do not collide. Different decision thresholds can reuse raw scores
   while retaining their different LONG/FLAT actions.
4. A second action performs fresh strict admission and does not reuse a prior
   cache. Mutation of a result cannot alter another member's evidence.
5. Record bounded before/after work counts and timings without adding flaky
   wall-clock assertions or a general benchmark framework.

### Scope and exclusions

Limit changes to the suite's private fit lifecycle, the directly affected fit
call sites and focused suite regressions. Do not change Ridge arithmetic,
normalization, solver, floating-point accumulation order, Q6, selected family,
statistical objective, persisted formats or TEST.

### Q50 implementation and local evidence

The suite now creates one private `_SelectionFitCache` only after strict source
preparation succeeds. Each evaluator verifies the same prepared-object owner;
independent public runners still resolve their original fitter dynamically and
do not use the cache. The key hashes the actual ordered fit inputs and preserves
exact JSON number representations, including alpha `1` versus `1.0`. Cached
models are deep-copied on every return; immutable raw scores produce fresh
threshold actions and observation metadata on every request.

Physical solver counts are measured at `intraday_research._fit`, counting each
linear or quadratic solve once and separating complete ordinary reconstruction
from the three procedures. The existing real two-fold quadratic source uses
the non-first cost/candidate and source alpha 2.0. Its measurements were:

| Execution | Strict preparation / reconstruction | Ordinary solves | Procedure solves | Total seconds |
|---|---:|---:|---:|---:|
| Three independent public runners | 3 each | 12 | 43 | 13.148 |
| Q49 single preparation, no fit cache | 1 each | 4 | 43 | 5.997 |
| Q50 single preparation and fit reuse | 1 each | 4 | 21 | 5.495 |
| A second Q50 action with a fresh owner/cache | 1 each | 4 | 21 | 5.786 |

All three complete canonical experiments and IDs matched across these runs.
A real two-fold linear source with alpha 1000.0 also retained complete equality
with the Q49 path: procedure solves fell from 43 to 21, ordinary solves remained
2, and the outside-family alpha still required its three distinct inner fits.
Its end-to-end times were 4.817 s without reuse and 5.096 s with reuse. Measured
key construction plus model copying cost approximately 0.022–0.025 s per action.

One bounded interleaved comparison investigated this remaining timing question
using the same prepared linear source and a fresh cache on every cached run.
The measured segment includes the three procedures and immutable artifact
construction, but excludes mandatory source preparation. Three uncached samples
were 2.266295, 2.182463 and 2.128172 s; three cached samples were 2.169277,
2.271115 and 2.332223 s. The median changed from 2.182463 to 2.271115 s
(+0.088652 s, +4.062%). Every sample retained identical complete experiments and
the same 43-to-21 physical-work reduction. This compact linear fixture does
not demonstrate wall-clock acceleration. The accepted deterministic benefit
is removal of identical physical fits, with bounded measured cache overhead;
neither a runtime guarantee nor an extrapolated production speedup is claimed.

The focused suite file passed all eight tests in 73.23 s. Coverage includes
actual-value/key/order/boundary/prediction-support discrimination, exact numeric
encoding, real linear and quadratic fits, threshold and metadata independence,
nested model mutation isolation, fresh second-action verification, owner
rejection, complete unavailability and the existing actual CLI/save behavior.
Three existing focused window regressions and three of the new small cache
checks passed together in 0.40 s. Tests assert complete content and physical
work, not a wall-clock threshold. Repository hygiene and
release/version 0.9.0 checks passed. No numerical core or CI configuration was
changed.

### Q50 completed mainline gate

[PR #320](https://github.com/M0DIAN/market-vault/pull/320) received fresh
independent final-candidate PASS at
`df4bd8081af4837ba48d0c0a39fb7265fe934572`, tree
`afc960de5c5f4df770b1429ce6b75e6853e3f34c`, with no actionable P1/P2/P3
findings. The independent five-node run passed in 61.90 s, including an
additional real linear alpha-1000 oracle against all three independent public
runners: complete bytes and IDs matched, ordinary solves changed from 6 to 2,
procedure solves from 43 to 21, and source files remained unchanged. A bounded
independent boundary audit also verified owner/source/locator rejection,
dynamic legacy fitter aliases and strict threshold equality producing FLAT.

Natural PR FULL
[38168305887/1](https://github.com/M0DIAN/market-vault/actions/runs/38168305887/attempts/1)
completed with all sixteen required jobs successful. The actual candidate's
`check_jobs` returned `(True, None)` for the complete raw attempt-1 job set;
every job's head, run and attempt matched. The actual plan ran all eleven
partitions, and package validated version 0.9.0 and created the attempt-bound
FULL attestation. Synthetic tested merge
`a6f3bb79d54160d67055f1dd5a02526335f5228d` had the same candidate tree.

The authorized squash main is
`3c09fcaac37247e2fce545501798bdab2eab5275`, with that identical tree and
single parent `fcde2eb340a76522b3eeca5f66ac7d7a9d6295ab`. Exact natural main
push [38169446819/1](https://github.com/M0DIAN/market-vault/actions/runs/38169446819/attempts/1)
completed successfully. Its actual plan proved
`POST_MERGE_REUSE=true`, reason `verified_full_pr_tree_equivalence`, binding
PR #320, final head, source FULL run, tested merge and identical tested/main
tree. Five required non-partition jobs succeeded and the unexpanded partition
job was skipped as planned. The actual-main verifier and real reuse markers
were checked; this is verified reuse, not a second FULL execution. Q51 started
only after this terminal gate and another current-main check.

The Q50 PR's longest job was strategy at 649 s, followed by
`intraday_ml_procedures` at 610 s. The latter ran 64 passed / 1 existing
optional-Qt skip in 579.18 s; its increased work includes the expanded suite
oracle and new linear source regression. Cross-run timing changes are not
attributed to fit reuse. The 39 s gap between these two longest jobs does not
justify changing the established eleven-partition CI topology for this task.

## Q51 — native run, save and compare workflow

### Goal and implementation

Expose Q49/Q50 from the existing intraday workspace: capture one ordinary
source/reference, run all three studies asynchronously, inspect their complete
results, save each standard experiment, and hand the explicit results to the
existing Q39/Q40 comparison entry.

Reuse the current controller/worker lifecycle, explicit immutable captures,
monotonic input revisions, existing standard study readers/views and individual
save writer. Completed result labels follow captured inputs. Edited drafts,
stale successes, stale failures and failed retries preserve the previous
completed result. Unsaved state must be explicit; do not invent a disk path.

Preserve the three original result kinds and availability states. Comparison
uses existing complete-common-source admission and never removes an unavailable
member to make the family appear valid. Saving yields ordinary existing study
files that remain eligible for their current reader and Freeze workflows;
no TEST is run automatically.

### Acceptance

1. A real `Main.qml` session reaches the new action from an ordinary source,
   obtains all three studies, inspects results, saves/reopens the standard files
   and reaches the existing pair/family analysis through the intended controls.
2. Captured-input and stale-result checks discriminate a later draft edit from
   the completed study. A common failure preserves prior results and permits
   an explicit retry. A save failure leaves successful files recoverable.
3. English and Simplified Chinese layouts remain usable at the supported
   compact size; normal controls and scrolling expose the complete evidence.
4. Existing readers and the corresponding Freeze source admission recognize
   saved suite members; no fake source root, locator or new TEST grammar.
5. No Qt import-skip is reported as native validation. Run the actual focused
   Qt workflow locally in addition to the applicable natural CI.

### Scope and exclusions

The new controller/panel, existing workspace/registration/localization and
production inventories, narrow comparison handoff, focused native test and
this document are the expected surface. No workspace redesign, new dashboard,
automatic ranking/promotion, automatic Freeze/TEST or batch job platform.

### Native interface and operation

The appended workspace tab is **Three procedures / 三流程运行**. Select an
ordinary saved DEV linear or quadratic Ridge candidate with 1–6 Features in
the existing development controls, optionally enter a relocated Q5 file, then
run all three procedures. The new controller uses the existing Q36 admission
getter and Q49's captured-content API. The worker receives the immutable source
bytes, source path, IDs, cost/candidate indices and resolved optional Q5 path;
it does not reopen the ordinary source pathname. Suite metadata keeps the
existing default empty name and notes. No new search controls are added.

The page shows the next-run draft separately from the completed source and
three fixed Q25/Q31/Q36 result rows. Each row shows its real availability,
study/selection IDs, individual saved state and successful writer-returned
path. Save-path input text remains a draft; a failed save cannot label it as a
saved artifact or erase another successful save. Fixed delegates preserve
the input controls and their text across result and language updates.

Viewing a member adopts the completed immutable snapshot in the existing
Q25/Q31/Q36 page. Unsaved snapshots have no path and retain COMPUTED proof;
opening the saved file through its existing reader yields RECORDED proof.
Q31/Q36 receive the suite's captured completed signature rather than attaching
the current draft to an older result. Their existing independent run/open
defaults remain unchanged.

Once all three files have actually been saved, the explicit comparison action
checks their standard kinds and saved bytes, captures them atomically in the
existing comparison controller as A/B/C, and starts its existing family
analysis. Q39 pair analysis remains available through the existing mode
control. This handoff retains complete UNAVAILABLE members and the previous
completed comparison while a new input or action is being evaluated. It does
not fit models, select a winner, Freeze a candidate or run TEST.

### Q51 implementation and local evidence

The two focused tests in `tests/test_desktop_intraday_procedure_suite.py`
passed on their first complete run: **2 passed in 220.96 s**, with no skip or
retry. They launched the actual `Main.qml` through the production bootstrap,
using Python 3.11.17 and PySide6/Qt 6.11.2 with the tested checkout's explicit
source/test paths, offscreen rendering and the software Qt Quick backend.

The real four-fold, 100-evaluated-day fixture ran the suite once in 26.763 s;
all three complete canonical artifacts and IDs equalled the independent
public-runner fixture. This is a bounded local observation, not a GUI latency
or general performance guarantee. A source-read guard prohibited reopening
the captured ordinary file. After computation, guards prohibited Q5 loading,
fitting, procedure execution and execution replay throughout native viewing,
individual publication, existing-reader reopening, complete family analysis
and the existing A/B comparison. The second-member real file conflict retained
the first saved member; an explicit new-path retry completed the family.

The short-history fixture retained all three complete UNAVAILABLE reports,
their six/four/24-member method declarations and unavailable reasons. It
covered candidate and locator A→B→A changes before late success, a late failure,
one real missing-Q5 failure and one real corrected retry. The late callbacks
used newly constructed immutable tuples from the actual completed studies,
so an incorrectly adopted stale success was distinguishable without repeating
the same fits. These callbacks test state handling, not additional research
computations. Previous results and saved files survived failed or stale work.

Both tests exercised English and Simplified Chinese at 1024×600. Actual
screenshots were visually inspected; scrolling exposed the controls without
horizontal overflow. Native assertions checked control reachability and that
save-path QObject identity and typed text survived member saves and language
changes. Existing Freeze source admission accepted saved AVAILABLE members
and rejected unsaved or UNAVAILABLE members; no selection was frozen and no
TEST was loaded or run. No backend was initialized.

The existing native family identity/evidence/recovery node also passed on
the changed production checkout: **1 passed in 235.22 s**. It exercises the
old explicit-open path affected by extraction of the shared source descriptor.
Production QML inventory checks passed all five existing tests and
localization passed all nine. Repository hygiene, version 0.9.0, whitespace
and the complete 235-file partition ownership check passed. The new native
file belongs to `app_ops`; the eleven partitions and CI control plane remain
unchanged. These local Qt runs are the native evidence; any optional-Qt skip
in natural CI is not reported as a substitute.

## CI and final delivery gates

Q48 main's longest jobs were dataset_features 582 s, intraday_analytics 565 s,
intraday_research 487 s, strategy 376 s and intraday_ml_procedures 314 s;
app_ops took 161 s. All sixteen jobs were under ten minutes. Keep the existing
eleven partitions and workflow. New procedure tests use the truthful existing
`test_intraday_ml_procedures_` prefix; native tests use `test_desktop_`.

Do not move tests merely to claim an optimization. Only a measured relevant
bottleneck justifies a later bounded repartition, with unchanged assertions,
parameterized nodes and complete collection-multiset equality. The current
3.14 compatibility and package tail mean total workflow time is not the same
as its longest functional job.

For each task, fix the committed final candidate, perform a fresh independent
review, wait for successful required natural PR CI, and recheck current
head/base/tree before authorized squash merge. Verify the exact resulting main
natural push to terminal success. Any post-merge reuse must be proven by the
checked-in verifier and that actual run's plan; otherwise natural FULL is
authoritative. Do not synthesize a closure run with an empty commit.

Local verification uses Python 3.11 and the tested checkout's explicit
`PYTHONPATH`. Run the focused affected behavior and required scope/hygiene/
release checks; do not duplicate a full local pytest matrix. Record actual
runtime evidence and any true limitations, then stop after Q51's main gate.
