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
saved MATCH or filename. Evaluate complete required DEV support and preserve
unassessed, missing, invalid, duplicate, differing and agreeing denominators.
Bind the policy, data, reference content identities and declared source basis.
Return REJECTED for confirmed policy violations, NEEDS_EVIDENCE for missing
required evidence, or POLICY_SATISFIED for the stated numerical/coverage policy.
Source-independence confidence remains a separate explicit declaration, never
silently promoted by the policy verdict.

**Dependencies:** completed Q73 plus unchanged Q44-Q48 comparison and dependency
contracts. Reuse their verified price versions, actual scope and validity
reasons. One additive settings-independent service/CLI and immutable new-file
output are sufficient; no second comparison engine or evidence database.

**Defaults:** existing zero numerical tolerances; complete required coverage;
no accepted missing/duplicate/invalid required price rows; no dropping affected
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
