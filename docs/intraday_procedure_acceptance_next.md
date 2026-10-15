# Selected-procedure acceptance integration: Q77-Q79

## Baseline and choice

Owner authorization: 2026-10-15, explicitly based on completed Q1-Q76 in
`M0DIAN/market-vault`. Planning main is
`53fee7f52d855615215dbc7efc264007a652b2f0`, tree
`6c8063c54a4bb4589558f17e3bf0d8cc63786762`; its natural push CI
`38668850898`, attempt 1, succeeded. No open PR was present at planning.

Q73-Q76 provide structural preflight, data-acceptance policy, bounded exposure
history and offline quote/paper-fill differences. The current Q75 reader
accepts ordinary DEV, frozen selection and TEST, but not the saved Q25/Q31/Q36
selection studies. Q76 accepts only ordinary DEV accounts. These are deliberate
prior scope boundaries, not claims that the completed implementations failed.
The resulting gap is that the existing ML selection procedures cannot enter
the same acceptance workflow directly. Recording or comparing only their fixed
reference or final winner is not equivalent to the actual selection procedure.

Complete those connections before adding learners, Features, search dimensions,
statistical gates or another aggregate report. No supplied real observations
establish market-data accuracy, obtainable fills or profitability. More source
integration cannot certify those facts.

Order is **Q77 -> Q78 -> Q79**, each after the preceding final candidate has
independent review, required natural CI, guarded squash and exact-main natural
push CI closure. Scope-related repairs and tests are already authorized.
Read-only planning is allowed, but later implementation does not start early.
Do not claim independent review from self-checks or reuse a superseded head's
PASS. No release, tag, deployment, live feed, paid data or brokerage action.

## Q77 - complete saved selection-procedure exposure history

**Goal:** record and assess Q25/Q31/Q36 studies directly, retaining the original
saved source's declared recipes and the complete six-model, four-threshold or
24-member procedure family, not just the selected winner.

**Technical approach:** extend the existing `intraday_history` reader, using
one strict offline `load_strategy_experiment` action. Obtain context from the
validated embedded ordinary source, and derive full normalized recipes from
the recorded method and captured reference/cost policy. Never reopen recorded
locators, rebuild Q5, fit, replay, or execute TEST. Reuse existing source/event
validation and overlap reduction rather than introducing a registry.

**Dependencies:** Q75, existing Q25/Q31/Q36 immutable readers and their fixed
method grammars. Original source comparison recipes precede the complete
procedure family; preserve order and duplicates. The list describes declared
recipes, not executed-fit, independent-trial or lifetime-search counts.

**Defaults:** same literal US symbol and New York trading day overlap; all
recorded TRAIN/VALIDATION dates count conservatively as research-use exposure,
including in an UNAVAILABLE study. No recorded overlap is not proof of unseen
TEST. External coverage remains UNKNOWN and independence_certified=false.
Existing ordinary/frozen/TEST events and all-legacy assessments retain v1 and
unchanged content. Procedure events use `market-vault-intraday-history-event-v2`;
assessments with a procedure source or any v2 event use
`market-vault-intraday-test-history-v2`. Mixed histories are supported. Source
kind and event version must agree; no migration or rewriting of old files.

**Acceptance:** actual saved-source public entry for all three procedures;
complete declared family and original source recipes; one offline Open and no
fit/source reconstruction; correct mixed-history overlap/unknown/duplicate
behavior; UNAVAILABLE study retains its declared family without inventing fits;
version/identity rejection; actual module CLI publishes the matching v2 result
once and refuses overwrite. Reuse existing session fixtures in their existing
`intraday_ml_procedures` partition.

**Exclusions:** procedure suites and other artifact kinds, anti-tamper or
preregistration guarantees, global enforcement, automatic history discovery,
new trading rules and changes to Freeze/TEST scoring or existing source IDs.
The existing explicit `record`/`assess` module CLI remains the entry until Q79.

## Q78 - reconcile the selected outer DEV account, not its fixed reference

**Goal:** apply the existing Q76 quote/paper-fill calculations to the complete
saved selected outer account of an AVAILABLE Q25/Q31/Q36 procedure.

**Technical approach:** reuse strict recorded-only selection-source admission
and the existing transaction/OPEN/trade binding and metric kernels. Select
`report.selected_account.execution`, not the embedded fixed account or the
final DEV recipe. Add an explicit procedure observation v2 grammar binding
expected experiment and execution IDs; procedure accounts have no invented
single fixed candidate ID. Preserve ordinary v1 requests and outputs.

**Dependencies:** completed Q77, Q76 and existing saved-procedure readers.
No model fit, account replay or Q5 I/O. An UNAVAILABLE study has no selected
account and must fail explicitly, not become an empty successful account.

**Defaults:** retain every BUY/SELL action including scheduled exits. Preserve
missing, unmatched, stale and clock-unresolved denominators; BUY uses ask and
SELL bid against raw next open. Costs are not added twice. Procedure output
identifies its fixed reference separately and retains outer-fold applied
recipes; a final DEV winner must not be presented as the historical account's
single strategy. Clock/provenance inputs remain declarations and all capture/
fill verification flags remain false.

**Acceptance:** all three actual saved procedure entries; exact execution-ID
rejection; evidence that the selected account, not the fixed reference, supplies
the population; independently calculable signed price/clock cases through the
shared kernels; unavailable/empty accounts distinguished; old ordinary output
unchanged; immutable module CLI output and relevant existing Q76 regressions.

**Exclusions:** frozen/TEST/suite account admission, live collection, automatic
order matching, fill simulation, PnL/capacity claims, model or cost changes.

## Q79 - one settings-independent command-line entry

**Goal:** make history record/assess and forward reconciliation discoverable
through `market-vault`, without requiring users to switch to internal module
names or maintaining a second implementation of their decisions.

**Technical approach:** add thin root research-command adapters that reuse the
same parser/runner functions as existing module CLIs. Bind explicit experiment,
declaration/event/observation and output paths. Preserve legacy module commands.

**Dependencies:** completed Q78 and the existing research command dispatcher.
No new generic CLI framework, settings dependency, source discovery or GUI.

**Defaults:** preserve exit 0/2/1 meanings, actual v1/v2 result versions,
exclusive new-file publication and stderr errors. A generated report is not an
acceptance or profitability pass. Do not automatically launch fit, Freeze or
TEST after an apparently successful diagnostic.

**Acceptance:** real root and module invocations agree for representative v1/v2
success, known-exposure/nonpassing and invalid-input cases; root help exposes
the commands; missing settings do not affect them; no overwrite and no change
to existing research commands. Verify installed/public entry in natural CI.

**Exclusions:** new report schemas beyond Q77/Q78, duplicate business logic,
desktop integration, global mandatory gates, release or deployment.

## Validation and CI boundaries

Use existing FULL classification and eleven file-owned parallel partitions.
Preserve test coverage, failure propagation, Python 3.14 compatibility checks,
package checks and exact-attempt/tree attestation. Repartition only if observed
job timing establishes a need; do not increase timeouts or skip assertions to
claim speed. Prefer fixture reuse over duplicate full study construction.

The implementation workspace was obtained from Q76 CI package artifact
11943242933 after verifying its archive digest and embedded SHA256SUMS. The
matching FULL attestation 11943043041 binds the exact tree above. This is an
sdist source workspace, not a full local Git clone. The local Python 3.13
container lacks pyarrow/duckdb; the attempted Q77 public pytest command fails
during collection at `service.py: import pyarrow.parquet`, before the changed
behavior. Syntax and isolated composition probes are not integration PASS.
Required natural CI must run the real tests with the repository environment.


## Q78 observation interface and validation scope

Use `market-vault-intraday-forward-observations-v2` only with a saved AVAILABLE
Q25/Q31/Q36 study. Its exact top-level fields are `schema_version`,
`expected_experiment_id`, `expected_execution_id`, `source`,
`reference_clock_id`, `policy`, and `records`. The expected execution ID is
`report.selected_account.execution.execution_id` in that saved study. Do not
supply a cost/candidate index or candidate ID: those would denote the embedded
fixed reference, not the selected procedure's outer account. The `source`,
clock, policy and record grammars are unchanged from Q76 v1.

The result uses `market-vault-intraday-forward-reconciliation-v2`. It identifies
the exact study, procedure kind/ID, embedded source and selected execution ID.
`fixed_reference` identifies the embedded comparison candidate separately;
`outer_fold_recipes` records the actual `refit`/`application` strategy for each
outer fold, in recorded order. Neither is substituted by a final DEV winner.
An UNAVAILABLE study fails explicitly. An AVAILABLE zero-action account returns
NO_REFERENCE_ACTIONS with empty measurements, not a success or missing account.
Ordinary observation/result v1 remains unchanged, and v1/v2 source kinds are not
silently interchanged. Recognized v2 CLI errors retain a v2 envelope.

Q78 acceptance tests reuse the study fixture instances already constructed in
`test_intraday_ml_procedures_history.py`; no new cross-module fixture suite is
introduced. They cover all three real saved-study API paths, one offline Open,
selected rather than fixed execution extraction, all transaction denominators,
per-fold metadata, exact identity rejection, signed bid/ask/paper calculations,
partial/unmatched evidence, actual AVAILABLE-flat versus UNAVAILABLE behavior,
and module CLI publication/identity failures. Existing Q76 ordinary, clock,
reference-consistency and publication tests remain required regressions. The
shared calculation kernels and source readers are not changed.

Q77 completed: PR347 squash `f2363ce9345ae25fefb866cedcef65d268e4daae`, tree
`8646d9f4607f54c4a576078b49bb53540d222159`; independent Codex review binds
`dc6a61e88c079d2fe0d8a96ff11e13a13ce17024`. FULL PR CI 38671329930/1 passed
all 16 jobs; its ML partition reports 74 passed, one existing skipped, 441.95s.
Natural push/main CI 38672844316/1 passed with the existing exact-tree FULL reuse
proof. Q78 starts only after that closure. The local dependency limitation is
unchanged: syntax checks are not public integration PASS; required natural CI
and a new independent exact-head review are still required for Q78.

## Q79 public command entry

The installed `market-vault` entry now exposes the same explicit offline
operations as the original module commands. For example, with already-prepared
saved inputs in the current directory and output names that do not yet exist:

```console
market-vault research-intraday-history record --experiment saved-study.json --declaration declaration.json --output event.json
market-vault research-intraday-history assess --experiment saved-study.json --event event.json --output history-assessment.json
market-vault research-intraday-forward-reconciliation --experiment saved-study.json --observations observations.json --output reconciliation.json
```

The example filenames are inputs to prepare and explicitly select, not source
discovery or files this task claims to have captured. `--event` may be repeated
for individually named saved events; omitting it examines an empty supplied
history, not a complete global record. Existing commands remain valid:
`python -m market_vault.research.intraday_history record|assess ...` and
`python -m market_vault.research.intraday_forward_reconciliation ...`.

Root and module commands share argument builders and execution functions.
The nested history action uses `history_action`, separate from the root
`command` discriminator, so it cannot redirect execution into settings loading.
The existing root research dispatcher runs before application settings are
loaded; these actions do not require a settings file. There is no automatic
source discovery, refit, replay, Freeze, TEST or follow-on action.

Schemas, identity checks, declarations, limitations and exclusive new-file
publication are unchanged. History returns 0 for recording or no overlap in the
supplied history, 2 for known/unknown recorded exposure, and 1 for processing or
publication failure. Reconciliation returns 0 only for RECONCILED with no quote
policy exceedance, 2 for other diagnostic outcomes, and 1 for processing or
publication failure. Standard argparse usage errors retain exit 2. An exit 0
is not a certification of untouched TEST, live capture, fills or profitability.

Four added parameterized public-entry tests use the installed console executable
and the legacy modules on the existing same-module `inner_case` fixture. They
compare full v1/v2 event and assessment/reconciliation content, known exposure
and missing-evidence exits, exact-account failure, no overwrite, root help and
operation with a nonexistent settings path. No additional study construction,
new test partition, workflow, dependency, schema, GUI or generic CLI layer.

Q78 completed before Q79 implementation: PR348 independently reviewed head
`651e807924b2c059c5ecd636b7e0ba7168af69bb`; FULL PR CI 38674159770/1 passed
all 16 jobs (ML: 80 passed, one existing skipped, 412.85s). Squash main
`521d2df8c21715f814d544bbc7b483fa9090297b` retains tested tree
`867ca3158f62691ab6af6f59e13de59e6f94c44a`. Its natural push/main CI
38675628048/1 passed with the existing exact-tree FULL reuse proof. Q79 requires
its own final independent review, required natural CI and exact-main closure.
The local missing-pyarrow import limitation remains distinct from CI runtime
proof; it is not hidden with dependency stubs or skipped tests.
