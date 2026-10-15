# Advice 03: bounded research acceptance, Q73-Q76

## Baseline, rationale and delivery order

The verified planning baseline is Q72 main
`8df93cedffaded8828be9443dc0a4a6dd59bb750`, tree
`4acdca549bae41d25be7d1983a6ca936e151e962`, in `M0DIAN/market-vault`.
This package responds to the owner's supplied **Improvement Advice 03** and
2026-10-13 authorization. It is not evidence of a profitable strategy or of
agreement between actual observed market datasets.

The advice distinguishes unchanged files, correct processing and faithful
market observations; report generation and acceptance; next-open assumptions
and obtainable fills; and saved TEST isolation and the researcher's wider
history of exposure. The implementation must retain those distinctions.

Q44-Q48 already compare external bars, bind them to actual Q5 price versions,
and explain Feature/target/fitted-sample exposure. Existing Q6/Q19 cost and
whole-bar delay stress, Q7 common evaluation opportunities, and Freeze/TEST
remain authoritative. Do not rebuild these tools or reopen Q70-Q72 numerical
and performance work without a directly relevant new counterexample.

**Order:** Q73 -> Q74 -> Q75 -> Q76. Each implementation starts from the previous
task's independently reviewed, squash-merged and exact-main-CI-verified commit.
Read-only planning of later tasks does not authorize starting their code early.
The owner has already authorized scope-related repairs, tests, commits, push,
PRs, independent review and conditional squash merge; do not seek another
approval merely because a step or candidate changed. A failed/missing review or
required CI is still a gate, not a reason to manufacture a PASS.

Shared boundaries: existing US single-symbol equity/ETF, RTH, unadjusted prices,
1/5/15/30-minute bars, long/flat research; explicit inputs, offline validation,
no latest-file discovery or automatic data repair. Preserve existing immutable
artifacts and identities. New additive result versions must be explicit.
Version remains 0.9.0. No release, tag, deployment, brokerage orders, paid data
acquisition, live subscriptions or account/credential changes are included.

## Q73 - structural comparison-plan preflight

**Goal:** before fitting or account simulation, show whether the actual declared
DEV folds have training rows and eligible fresh next-open observations. Make
feature warmup and entry-window incompatibilities visible without confusing a
valid strategy that chooses Flat with a configuration that cannot enter.

**Technical approach:** normalize an ordinary Q7 comparison V1/V2 plan; use its
existing preparation path to strictly reload Q5 once and establish the same
Feature projection, actual-label-end-purged training rows, common evaluated days
and complete price admission. Reuse Q6 calendar/window validation. Count READY
observations by session and fold; separately report unavailable Features,
first READY clock, first eligible next open and mutually exclusive exclusions.
No model, prediction, trading account, experiment or TEST performance is made.

**Dependencies:** Q5 strict reconstruction, Q7 plan/fold preparation and Q6
entry-window rounding. No new dependency, persistent cache, calendar or
alternative source-admission path.

**Defaults and decision:** existing plans and their explicit commission and
slippage remain unchanged. The 70/15/remainder day proposal and 20/5/5 walk
remain software defaults, not statistical adequacy claims. CHECKED means only
that these structural checks found no blocker. BLOCKED means no eligible
entries across the evaluated DEV dates, or a declared Ridge/quadratic Ridge
has no admitted training rows in a fold. Empty entry days/folds remain visible;
they are not dropped or automatically made fatal when other dates have entry
opportunities. Rules need no training targets. A missing target does not remove
an otherwise READY observation. Existing errors for no complete fold, no READY
validation observations, invalid windows, wrong identity or incomplete common
prices remain FAILED, without a fabricated partial successful result.

**Acceptance:** actual API and CLI over a synthetic but real verified Canonical
source; one strict reload per action; no fit/account calls; deterministic IDs;
unchanged source bytes and plan; valid all-Flat rule retains opportunities;
zero-entry and missing-learned-target cases are distinguished. Small clock
oracles cover LIGHT/CORE, normal/early close, stride, exact window endpoints and
reconciliation of all observation denominators. Check representative single
signals against the existing Q6 kernel. Required CI and independent review bind
the final candidate. Synthetic data proves behavior, not market accuracy.

**Exclusions:** no changes to preset lengths, cross-day warmup, strategy/label
semantics, research selection, existing comparison outputs, Freeze/TEST,
statistical sample-size thresholds or fills. No GUI page, diagnostics/selection
preflight adapter, mandatory launch gate or persisted preflight reader in this
task. This CLI/API scope is deliberate, not a claim of desktop integration.

### Q73 entry and report contract

```console
market-vault research-intraday-compare --plan /absolute/comparison-plan.json --preflight
```

Python entry:
`market_vault.research.intraday_preflight.analyze_intraday_preflight(plan, base=...)`.
It accepts only an explicit comparison plan, not caller-supplied verified data.

The flag is additive and accepted only by `research-intraday-compare`.
`--preflight` cannot be combined with `--experiment`, `--name` or `--notes`.
No file is published. Without the flag, the existing command and result version
remain unchanged.

The CLI envelope uses `market-vault-intraday-preflight-cli-result-v1`, with
`status` CHECKED or BLOCKED and a `preflight` object. Exit codes are 0 for
CHECKED, 2 for BLOCKED, and 1 for existing validation errors (FAILED on stderr).
The API object uses `market-vault-intraday-preflight-v1`; its `preflight_id`
hashes the complete content excluding that ID using the existing canonical
encoding. It binds the normalized plan, Q5 data ID and original Q7 context ID.
It is an ephemeral derived report, not a new source authority or experiment.

`eligible_entry_observation_count` counts fresh READY decisions that could
enter **while flat**, not trades, fills, expected participation or profits.
It deliberately does not apply any strategy's predictions, max-hold exits or
non-overlap state. Times retain the verified aware ISO representation; the
following examples express their corresponding New York wall clocks.

With default execution windows and complete normal-session READY Features,
5-minute LIGHT first observes at 09:55 and CORE at 11:40. Fifteen-minute CORE
first observes at 16:00, with no next session open; thirty-minute CORE has no
same-day observation. These are geometry examples, not measured performance.
A Q7 fold containing no READY observations is rejected by the existing Q7
preparation before a preflight report, including the last combination above.

READY exclusions are mutually exclusive in this order:
NO_NEXT_SESSION_OPEN, AT_OR_AFTER_FORCED_FLAT, BEFORE_ENTRY_WINDOW,
AT_OR_AFTER_STOP_NEW. The final two use Q6's inclusive opening eligibility and
exclusive stop-new boundary. Unavailable Features have their own count.
Eligible plus excluded equals READY; READY plus unavailable equals all
observations on every retained evaluated session. No TEST sessions or scores
are included in session summaries; split day counts remain visible.

## Q74 - policy-based dataset acceptance using existing evidence

**Goal:** turn actual-data evidence into an explicit bounded research-use
verdict, without treating successful report generation as data acceptance.

**Technical approach:** accept explicit Q5, Q46 evidence manifest and policy
inputs; reconstruct through existing Q46/Q47 entry points instead of trusting a
saved MATCH or filename. Evaluate the full Q5 grid, a conservative superset of DEV support, and retain
Q47 whole-window/target dependency links. Preserve unassessed, missing, invalid,
duplicate, differing and agreeing denominators. Full-grid inspection includes
any reserved TEST dates and recorded labels, not TEST strategy performance; it
must not be described as a certificate of unseen TEST information.
Bind the policy, data, reference content identities and declared source basis.
Return REJECTED for confirmed policy violations, NEEDS_EVIDENCE for missing
required evidence, or POLICY_SATISFIED for the stated numerical/coverage and declared-source policy.
Source-independence confidence remains a separate explicit declaration, never
silently promoted by the policy verdict.

**Dependencies:** completed Q73 plus unchanged Q44-Q48 comparison and dependency
contracts. Reuse their verified price versions, actual scope and validity
reasons. One additive settings-independent service/CLI and immutable new-file
output are sufficient; no second comparison engine or evidence database.

**Defaults:** existing zero numerical tolerances; complete FULL_Q5_GRID coverage;
no accepted missing/duplicate/invalid required price rows; both sources must be
declared OBSERVED with a claimed distinct upstream. These are required
declarations, not proof of independent provenance; no dropping affected
samples, intersecting dates or widening tolerances to obtain success. Explicit
policy deviations must be identity-bound and visible. An empty reference list
cannot satisfy the policy. POLICY_SATISFIED is not a market-accuracy certificate,
a claim of verified independence or automatic strategy promotion.

**Acceptance:** successful aligned synthetic input, partial/no evidence,
confirmed differing/invalid rows and incompatible basis all produce distinct
correct outcomes from the actual entry; counts reconcile; exact changes to
source/reference/policy invalidate the prior identity; original data remains
unchanged. Real-market acceptance requires actual supplied independent data;
its absence does not justify inventing observed agreement.

**Exclusions:** vendor selection, downloading, authentication, automatic repair,
real dataset accuracy claims without evidence, and changes to legacy research
or Freeze/TEST admission. No compulsory global clean-data gate.

### Q74 entry and decision contract

```console
market-vault research-intraday-market-evidence --data /absolute/q5.json --manifest /absolute/evidence-plan.json --policy /absolute/acceptance-policy.json --output /absolute/new-acceptance.json
```

The existing command without `--policy` is unchanged, including SUCCESS/0 when
a comparison report is generated with partial or missing evidence. With the
flag, the explicit policy selects the new result version
`market-vault-intraday-data-acceptance-v1`. The published file is the complete
acceptance object; the CLI envelope reports the **same policy status**, not
SUCCESS. Exit 0 means POLICY_SATISFIED, 2 for REJECTED or NEEDS_EVIDENCE (a new
report was still published), and 1 means invalid request or publication failure.
Existing destinations are never overwritten, including rejected reports.

Python entry:
`analyze_intraday_data_acceptance(data, manifest, policy, base=...)` in
`market_vault.research.intraday_data_acceptance`. The public action performs one
strict Q5 verification, calls Q47 -> Q46 once, and inspects every local session
with the same Q44 validity kernel. There is no saved-report or preverified-input
shortcut. Full dependency evidence contains the Q46 report **once**; its
original identifiers, input diagnostics and all denominators remain intact.

Minimal explicit policy:

```json
{"schema_version":"market-vault-intraday-data-acceptance-policy-v1"}
```

Normalization fills `scope: FULL_Q5_GRID`, all three Q44 tolerances with zero,
and `require_declared_distinct_observed: true`. Any supplied tolerances must
match the independently explicit Q46 manifest; mismatch is FAILED before data
processing, not an automatic tolerance override. The only supported scope is
the complete Q5 grid; no dates/samples are intersected away to produce a pass.
A caller can explicitly set the declaration requirement false for a numerical
policy (including synthetic software testing); that changed canonical policy
and its distinct ID stay in the report. Such a verdict does not assert
observed provenance or independence. The source-assurance field always says
SOURCE_DECLARATIONS_ONLY and `independence_verified: false`.

Known missing local prices, invalid local/reference inputs (including duplicate
or unkeyed rows), numerical differences, or prohibited synthetic/shared source
declarations produce REJECTED. Missing/partial reference coverage and unknown
required source declarations produce NEEDS_EVIDENCE. Rejections take precedence,
but the report also retains all evidence gaps. Incompatible scope/economic
basis remains the existing explicit input error: no false partial report is
manufactured. Hash consistency or Q46 AVAILABLE alone cannot satisfy a policy.

`acceptance_id` binds the entire derived result excluding that ID. `policy_id`
binds canonical normalized content; Q46 binds actual captured reference bytes
and verified Q5 content/source identities. These hashes do not prove prior
registration, an authenticated timestamp, observed accuracy or strategy value.
This is additive CLI/API functionality; there is no GUI control or automatic
research/Freeze/TEST launch gate. Synthetic integration fixtures test decisions
and input preservation; no actual market-data acceptance is claimed.

## Q75 - bounded TEST-exposure and trial-history record

**Goal:** prevent the selected local research history from being described as
untouched independent TEST after recorded exposure or tuning, while retaining
honest uncertainty about history outside that scope.

**Technical approach:** accept an explicit list of existing trial/exposure
records and the proposed research scope. Record immutable new-file events
binding data/source identity, symbol/basis, date intervals, candidate/plan/code
identity, declared candidate family/costs, observation/tuning purpose and TEST
exposure. Compare dates and economic scope, not filenames or display names.
Report KNOWN_EXPOSURE when matching TEST scope was inspected or used for tuning;
UNKNOWN_RECORDED_EXPOSURE for relevant unknown imported history, or
NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY otherwise, with external historical
coverage UNKNOWN. The report cannot relabel previously viewed TEST as pristine.

**Dependencies:** completed Q74; existing explicit experiment/Freeze/TEST
metadata readers. Do not reopen or recalculate TEST to answer the history
question. Use exclusive new-file publication and explicit input lists, not a
mutable registry, directory scan or permission service.

**Defaults:** no claim of complete worldwide or cross-machine history. Existing
Freeze/TEST bytes, IDs and readers are unchanged. Retrospective user statements
are marked declarations, not independently timestamped preregistration.
Known relevant exposure prevents an independence claim in the new assessment;
exploratory analysis remains describable as exploratory, not silently erased.

**Acceptance:** fresh supplied history, renamed/relocated identical scope,
overlapping exposed dates, disjoint dates and unknown imported history have
correct distinct explanations. A plan/data rename cannot remove matching
exposure. Inputs remain unchanged; no fitting or TEST execution occurs.

**Exclusions:** global enforcement, complete lifetime search accounting,
anti-tamper promises for user-controlled files, an approval platform, global
statistical overfitting certification, and changes to existing TEST algorithms.

### Q75 entry, scope and saved-record contract

The additive module CLI deliberately leaves existing root commands and GUI
behavior unchanged:

```console
python -m market_vault.research.intraday_history record --experiment /absolute/saved.json --declaration /absolute/history-declaration.json --output /absolute/new-event.json
python -m market_vault.research.intraday_history assess --experiment /absolute/proposed-selection.json --event /absolute/new-event.json --output /absolute/new-assessment.json
```

Repeat `--event` for each explicit history file; omitting it assesses an empty
supplied history, not a complete history. API entries are
`create_intraday_history_event(experiment_path, declaration)` and
`analyze_intraday_test_history(experiment_path, event_paths)` in that module.
No data directory or implicit latest record is accepted. Inputs may be ordinary
Q7 DEV V1/V2, frozen selection V1-V4, or saved TEST V1-V4; other artifact types
are rejected rather than being partially interpreted.

A declaration has exactly `schema_version` (value
`market-vault-intraday-history-declaration-v1`), `expected_experiment_id`,
`recorded_at` (explicit UTC instant), `purpose`, `observed_days`, `code_commit`
and `notes`. Purposes INSPECT/TUNE require a sorted unique, nonempty list of
source-scope trading days; PLAN_ONLY/UNKNOWN require an empty list. A known
code commit is an explicit full 40-character lowercase Git SHA; null means
unknown. Neither the time nor code commit is authenticated by this action.
There is no automatic timestamp or false prior-registration claim.

Creation uses the existing strict offline artifact grammar exactly once. Each
new event retains source artifact/data/plan identities, Feature/split context,
the saved candidate family and execution-cost recipes, a recipe-set identity,
algorithm/environment metadata and the complete declaration. A saved event has
version `market-vault-intraday-history-event-v1` and a full-content `event_id`.
Loading checks its grammar and content/recipe bindings; it does not re-open the
original source or certify a user-controlled file against deliberate rewriting.
Keep the original artifacts and explicit events for reproducibility.

Known research-use exposure conservatively includes **all recorded TRAIN and
VALIDATION dates**, including dates that were not scored in a DEV fold. A saved
TEST additionally includes all of its TEST dates regardless of the declaration.
This describes recorded research use, not proof that a human saw particular
pixels. Declared INSPECT/TUNE dates are added, never used to subtract existing
recorded exposure. Thus older DEV dates later proposed as TEST remain exposed,
and importing TEST with PLAN_ONLY cannot erase its saved result evidence.

Matching uses the same literal US symbol and New York trading date under the
existing RTH/unadjusted contract. Different data IDs, names, files, Feature sets,
recipes or bar intervals do not reset overlap. Currency/asset-class provenance,
related-symbol information transfer and global economic equivalence are not
verified by these saved metadata. Do not infer them from a matching verdict.

Assessment returns `market-vault-intraday-test-history-v1`. KNOWN_EXPOSURE takes
precedence over UNKNOWN_RECORDED_EXPOSURE, which represents relevant UNKNOWN
history declarations. Otherwise the status is
NO_RECORDED_EXPOSURE_IN_SUPPLIED_HISTORY. Each supplied unique event retains its
known/declared/unknown overlap explanation; duplicate content IDs are counted
but do not inflate evidence. Known and unknown day unions remain separate. A
proposed artifact that is itself a saved TEST contributes its own TEST exposure
even when the supplied event list is empty. Corrupt or unreadable event files
fail the action instead of being silently dropped.

Every result explicitly retains `external_history_coverage: UNKNOWN` and
`independence_certified: false`. An empty or disjoint history is not pristine-TEST
certification. No action fits a model, reconstructs Q5 or executes/replays TEST.
Both CLI commands exclusively publish a **new** file; existing files are never
overwritten. Exit 0 means event recorded or no overlap found in supplied history,
2 means known/unknown overlap (the report was still published), and 1 means
invalid input or publication failure. No exit status automatically authorizes a
research run, TEST use, model promotion or trade.

## Q76 - forward-observation execution discrepancy reconciliation

**Goal:** quantify the difference between saved next-open assumptions and
subsequently observed timing/quotes, without inventing obtainable fills from
OHLC or treating executable-looking quotes as guaranteed executions.

**Technical approach:** ingest explicit offline signal/quote/paper-fill records
with source and clock-basis declarations, bar-end/signal-ready/quote-received
instants and same-symbol bid/ask. Bind them to the selected recipe and reference
next-open price. Keep quoted-price discrepancy, declared paper-fill discrepancy
and measured local latency separate, with explicit unit and denominator.
Reject impossible same-clock ordering; do not subtract unsynchronized clocks
as if latency were established. Preserve stale/missing/crossed-quote reasons.

**Dependencies:** completed Q75; existing recipe/evidence identities, Q6
reference execution and Q19 bar-delay meanings. Reuse offline parsing and
exclusive report publication, not a live feed or matching engine.

**Defaults:** no fee/spread assumptions are silently supplied. Missing observed
records mean NOT_MEASURED, not zero latency/slippage. Quote age and acceptance
tolerances must be declared before judging supplied observations; no universal
market threshold is invented. Quote-based comparisons do not prove a fill,
capacity, queue priority, intrabar drawdown or live profitability.

**Acceptance:** hand-computable offline signal/quote examples, unmatched and
stale evidence, clock-basis failures, preserved denominators, deterministic
identities and unchanged input bytes. Real-forward validation remains pending
until genuine subsequently collected observations are supplied; synthetic
fixtures only validate calculation and error behavior.

**Exclusions:** subscriptions, broker orders, capture daemons, live paper
execution, bid/ask reconstruction from candles, impact/queue models, leverage,
short selling and multi-asset expansion.

## Minimal CI and review closure

Use the existing eleven functional partitions and exact file-ownership check.
Q73's `test_strategy_intraday_preflight.py` belongs to the existing
`test_strategy_` rule; no classifier, workflow or timeout change is necessary.
Use measured bottlenecks, not a new feature alone, to justify future CI
rebalancing. Never drop assertions, force a reduced tier or mask failed jobs.

Every task requires review of the actual final diff by an independent agent or
person who did not implement it, plus its required natural PR CI. A self-audit
or a request for review is not approval. Before guarded squash, refresh exact
head/base/tree/run/attempt evidence. After merge verify the actual main SHA and
its naturally triggered push CI, including the existing tree-reuse proof when
used. PR green is not exact-main green; reuse is not a second FULL execution.

Engineering completion and real-market acceptance are separate. This package
can deliver tested offline tools while observed-data, source-independence and
forward-market conclusions remain unverified. Preserve that limitation in every
acceptance record rather than manufacturing empirical success.
