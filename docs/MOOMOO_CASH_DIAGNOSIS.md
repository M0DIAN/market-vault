# S13-S15: explain observed cash differences without waiving them

Owner-authorized sequential package, 2026-10-19. Base: main
`0da59ecec70e8a2aef9fd336dd81e4d72bf317d0`. Each item needs exact-candidate
independent review, required CI, squash, and natural exact-main CI verification
before the next implementation. No deployment, REAL access, journal reset,
stop clearing, new orders, fee guessing, tolerance widening or baseline rewrite.

## Actual reason for this work

The owner's first paper-order projection records one intention, a full fill,
matching owned quantity, repeated unexplained cash reduction, and sticky stop
still present after reopening. The simulator UI supplies no fee detail. These
are owner-provided observations, not broker-signed attestation. Keep the original
files and account stopped. Do not request another trade or the same screenshots.

S10's submission/fill and S11's reopening/stop have observed support. Cash
reconciliation remains blocked; cancellation and real network-outage branches
remain unobserved. Neither S10-S12 nor live/forward acceptance is fully passed.
This work separates those conclusions; it does not retrospectively relax them.

## Fixed package

| Item | Goal and solution | Dependency, default and acceptance | Excluded |
| --- | --- | --- | --- |
| S13 split diagnosis | Extend the existing observation summary and qualifier console with separate recorded order, owned-quantity, cash/basis and stop facts. | Preserve original result/error/exit codes; nonzero cash remains unattributed, fees unobserved. Same synthetic failure must still block and refuse a new submission; no extra SDK query. | Fee schedules, cost fitting, green overall acceptance, changing engine/journal semantics. |
| S14 offline report analysis | Read an existing sanitized qualification/evidence JSON, validate/project its supported data and recompute the same summary without trusting embedded summaries. | After S13 main verification. No SQLite/OpenD access. Analyze the supplied report directly; preserve its bytes and old result; exclusive new output, unknown/missing data never upgraded. | New evidence database, importing user journals, another broker collector, fee attribution, rewriting historical runtime hashes. |
| S15 measured partition balance | Redistribute costly saved-result/history tests from strategy into existing spare-capacity intraday_saved by exact ownership. | After S14 main verification. Use measured job durations; same test files exactly once, unchanged assertions/job count/platform scope. Target affected jobs below 10 minutes on measured PR/main runs; report observed limits, not a permanent timing guarantee. | New CI framework, reduced tier, skipped tests, raised timeout, unrelated test rewrites. |

S15 baseline evidence: FULL PR run 39043790111 attempt 1 has strategy tests
611.26 seconds (627 passed, 12 skipped). The same run's intraday_saved job took
206 seconds end-to-end (test step 179 seconds). Re-check the two preceding task
runs before choosing the exact redistribution. Scope stays within the existing
11 partitions and their established ownership validator.

## S13 interpretation

`reconciliation_diagnosis` is additive to the existing v1 observation summary.
`order_states` counts only outcomes supported by accepted query observations;
ACK-only, stale, ambiguous or later unresolved work is not upgraded to a fill.
Owned-quantity comparison is NOT an account-wide audit: the public projection
omits unrelated positions. With no owned intention it says NOT_COMPARED, not
"account empty". Missing position keys are not imputed to zero.

Cash sign is classified only on the same recognized baseline/current cash basis
and after the recorded comparison stage. Nonzero means UNATTRIBUTED_DECREASE or
UNATTRIBUTED_INCREASE, never a fee or error correction. Zero means only zero
recorded residual, not no fees or live readiness. Missing or changed basis is
explicit. The source reconciliation result/error and residual remain unchanged.
Every diagnosis identifies its historical/non-atomic scope and later activity;
stop observation does not imply cancellation or liquidation. No field grants
new-order authority. The qualifier prints the same diagnostic after saving its
existing JSON, without changing the recorded action's return code or making
another account query. Earlier reports are not rewritten.

General fee rules cannot explain an individual transaction. Do not add an
unsupported simulator fee/cash-flow query or REAL fallback to obtain a number.
No transaction-specific fee evidence is currently available. Independent market
data, broker latency, market slippage, cost calibration and frozen strategy
forward validation all retain their existing missing/unperformed status.

## S14 offline saved-report entry

Use the reviewed source and existing Python, with `src` on `PYTHONPATH`:

```text
python -m market_vault.moomoo_simulation_report --input EXISTING_SANITIZED.json --output NEW_ANALYSIS.json
```

Accepted inputs are the existing `market_vault_paper_qualification_v1` wrapper
with available evidence, or a bare `market_vault_paper_evidence_v1` export.
SQLite databases, incomplete wrappers without evidence and other schemas are
not supported. UTF-8 with or without BOM is accepted. No SDK, pandas or database
connection is needed; import and fresh-process execution work without installed
site packages. Only the explicitly supplied JSON is read; no journal is opened.

The reader validates environment, limits, counts, unique sequence/intent
ownership, matching operation starts/finishes and declared stop. Wrapper
result/action must match its final recorded operation. It retains incomplete
operations in bare evidence without upgrading them. Missing comparison fields
remain missing; malformed numbers, duplicate JSON keys and inconsistent
identities are rejected. Extra private keys and embedded summaries are not
forwarded. The S13 summary is recomputed from allowlisted event data, not copied
from an old or edited summary. Only declared observations can be analyzed;
validation cannot authenticate broker activity or independently recompute cash
from private balances omitted by the original exporter.

Output schema is `market_vault_paper_report_analysis_v1`. `source_declared`
retains the original action/result/error, safe declared runtime, exporter hash
and summary-source hashes separately from `analyzer_runtime`. `input_sha256`
identifies the exact original file bytes, not a broker signature. No historical
runtime hash is relabeled as this analysis's source identity. The original file
is not changed and an existing output file is never overwritten.

Exit 0 / ANALYZED means the analysis completed, not that the source's BLOCKED
result, unexplained cash, missing fees or stopped state passed qualification.
Exit 1 leaves a static diagnostic; preserve the input. Use a new output name
only for a valid analysis retry, never another trading journal. This entry has
no trading or recovery action and cannot grant new-order authority. The owner's
already supplied report can be processed here without another OpenD session,
screenshot or account operation. No owner report or runtime values are checked
into the repository; regression fixtures remain synthetic.
