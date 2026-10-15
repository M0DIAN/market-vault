# Q76: offline forward-observation reconciliation

This is the last task in the owner-authorized
[Advice03 Q73-Q76 package](intraday_acceptance_next.md). Implementation starts
from Q75 main `6b41ac72bdf299a47f953fdf209e1b930188a9e4`, after natural push CI
`38664865873/1` completed successfully. The tool compares explicitly supplied
observations with a selected saved DEV account; it does not collect forward
observations or certify that they were recorded before the outcome was known.

## Entry and supported scope

```console
python -m market_vault.research.intraday_forward_reconciliation --experiment /absolute/development.json --observations /absolute/observations.json --output /absolute/new-reconciliation.json
```

The API is `analyze_intraday_forward_reconciliation(experiment_path, observations)`
in that module. It strictly opens one ordinary Q7 DEV V1/V2 experiment using the
existing offline reader. The explicit cost/candidate indices and expected IDs
must match. Its selected execution must use the existing execution V2 and cost
V2 versions. No automatic strategy choice, data discovery, Q5 reconstruction,
fit, account replay or TEST evaluation occurs. Existing commands, GUI, artifacts
and identities remain unchanged. Package version remains 0.9.0.

Every saved BUY and SELL transaction is retained in original order, including
scheduled EOD and maximum-hold exits. Its reference clock, raw open, modeled
fill and row identity must agree with the recorded OPEN grid and trade endpoint.
Signal-driven actions must have the corresponding preceding decision and
observation key. Scheduled exits have no invented signal or observation key.
These internal consistency checks are not price authority or full replay proof.

The population is **saved transactions, not all emitted signals or all possible
trades**. A previously unused later period can be recorded as an ordinary DEV
artifact and explicitly selected here, but this tool does not run that research
or establish prospective recipe selection. Frozen selections, saved TEST and
selection-procedure studies are not accepted by this entry.

## Explicit observation manifest

All root fields below are required. The example is a schema illustration:
replace the identity placeholders with the actual selected saved IDs. No default
clock synchronization, quote age or adverse-price tolerance is invented.

```json
{
  "schema_version": "market-vault-intraday-forward-observations-v1",
  "expected_experiment_id": "<actual 64-character experiment ID>",
  "cost_index": 0,
  "candidate_index": 0,
  "expected_candidate_id": "<actual 64-character candidate ID>",
  "source": {
    "provider": "explicit-capture-provider",
    "version": "1",
    "captured_at": "2026-10-15T20:00:00Z",
    "data_kind": "UNKNOWN",
    "upstream_id": null,
    "upstream_evidence": null
  },
  "reference_clock_id": null,
  "policy": {"max_quote_age_ms": 100, "max_adverse_quote_bps": null},
  "records": []
}
```

The source is the existing Q44 six-field declaration; `data_kind` is OBSERVED,
SYNTHETIC or UNKNOWN. It is not authenticated provenance. The illustrative
100 milliseconds is an explicit caller value, not a recommended market limit.
`max_quote_age_ms` must be finite and nonnegative. The adverse threshold must be
finite and nonnegative or null (measurement only, no adverse-threshold verdict).
Neither policy content nor its hash proves preregistration.

Each record has exactly `symbol`, `trading_day`, `slot`, `side`,
`action_ready_at`, `quote`, and `paper_fill`. Its key is the literal uppercase
US symbol, New York trading day, saved zero-based transaction slot and BUY/SELL
side. Duplicate keys fail instead of choosing or averaging. Unmatched keys are
retained separately, including a wrong symbol/day/slot/side; they do not remove
unmatched reference actions or enter measurement summaries.

A timestamp is null when missing, otherwise exactly
`{"timestamp":"2026-10-15T14:55:00.020Z","clock_id":"capture-host"}`. The timestamp
must be explicit UTC ISO text with seconds and optional microseconds, in Z or
+00:00 form. Equal clock IDs declare a common synchronized time basis; different
IDs are not subtracted. A nonnull `reference_clock_id` declares the basis of
the saved market reference clock; null leaves that relation unresolved. These
IDs do not verify clock synchronization or source identity.

`action_ready_at` is when the caller records that action as ready. `quote` is
null or exactly `{bid, ask, observed_at, received_at}`; each side may be null,
otherwise it must be a positive finite number. Its two timestamps use the same
stamp grammar. `paper_fill` is null or exactly `{price, filled_at}`, with positive
finite price and nullable stamp. Partial fills and quantity matching are not
modeled. Contradictory known same-clock ordering fails: receipt cannot precede
quote observation or action readiness; paper fill cannot precede readiness;
readiness cannot precede the matched reference open. Unrelated clocks remain
unavailable, not false negative latency.

## Measurements and decisions

For each matched action the report keeps four time differences, in milliseconds:
reference open to readiness, readiness to quote receipt, quote observation to
receipt (quote age), and readiness to declared paper fill. These are recorded
clock differences, not order-routing, queue or confirmed execution latency.
Missing inputs and incompatible clock bases produce null with explicit reasons.
Local time differences can remain measurable even when the reference clock is
unresolved.

A quote-price difference additionally requires both noncrossed sides, a known
reference-to-ready relation, known readiness-to-receipt and quote age, and age
at most the supplied maximum (equality allowed). Its adverse basis points are:

```text
BUY:  10000 * (ask / raw_next_open - 1)
SELL: 10000 * (1 - bid / raw_next_open)
```

Positive means worse, negative means better. Paper-price adverse basis points
use the same sign rule but are separate from the quote and require only their
own consistent reference/readiness/fill clocks. Missing or stale quote evidence
does not discard an otherwise measurable declared paper price. The saved
modeled fill is shown separately, never used as a raw-open denominator. No fee,
commission, existing slippage, account PnL or net strategy return is recalculated.
Finite operands with an unrepresentable result give null/NUMERIC_OVERFLOW.

Per-action quote reasons retain NO_OBSERVATION, NO_QUOTE, MISSING_BID_ASK,
CROSSED_QUOTE, REFERENCE_CLOCK_UNRESOLVED, QUOTE_CLOCK_UNRESOLVED, STALE_QUOTE,
NUMERIC_OVERFLOW or MEASURED. A measured quote exceeds an explicit adverse limit
only when strictly greater. Without a limit the verdict is null, not a PASS.
Statistics use only available values but retain available and unavailable counts
against **every reference action**; missing measurements never become zeros.

The report version is `market-vault-intraday-forward-reconciliation-v1`.
RECONCILED means all reference quotes are measured with no unmatched supplied
records. It does not mean the adverse-price policy passed or that a fill was
obtainable. PARTIAL retains some measured quotes plus gaps or unmatched records;
NOT_MEASURED means no quote-price measurement, even if some local timing or paper
prices are measurable. NO_REFERENCE_ACTIONS means the selected account has no
transactions. No hypothetical transactions are invented for a valid Flat rule.

The full-content `reconciliation_id` binds the source IDs, recipe, environment,
normalized observation identity, explicit clock/policy, all rows and denominators.
`observations_id` binds normalized JSON content, not original whitespace or an
authenticated capture log. `forward_capture_verified` and `fills_verified` are
always false. Output uses existing exclusive new-file publication: even a
nonpassing result cannot overwrite an existing report. Exit 0 means RECONCILED
and no observed adverse-policy exceedance (possibly measurement-only with a null
threshold); 2 means another computed outcome or any exceedance; 1 means invalid
input or publication failure. A report is still published for exit 2.

## Acceptance and exclusions

Focused tests cover hand-computable BUY/SELL differences and clock units, missing
and stale quotes, incomparable clocks, contradictory ordering, saved-reference
cross-bindings, complete/partial/empty/Flat denominators, unchanged input bytes,
identity changes, one offline source Open, and actual subprocess CLI publication.
Synthetic fixtures prove software behavior only. Real forward acceptance remains
pending until genuine observations are supplied and their collection procedure
is evaluated separately.

This task adds no dependency, root command, GUI page, market feed, capture daemon,
subscription, order routing, brokerage action, fill simulator, capacity/impact
model, cross-asset search, release or deployment. It does not reconstruct quotes
from OHLC, assess intrabar drawdown, certify untouched TEST, or establish actual
profitability. Q6 next-open assumptions and Q19 whole-bar delay studies remain
unchanged; neither is upgraded into observed execution evidence by this report.
