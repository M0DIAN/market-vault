# Adjusted-Price PIT As-Of Policy V1

## 1. Status and scope

This document is the current-main policy authority for adjusted historical
prices inside point-in-time (PIT) Dataset assembly.

```text
POLICY_VERSION=adjusted-price-pit-as-of-policy-v1
DESIGN_ONLY=true
RECOMMENDED_POLICY_MODEL=MODEL_C_NONE_ONLY
CURRENT_PIT_NONE_ONLY_GUARD=true
CURRENT_RUNTIME_ALREADY_CONFORMS=true
RUNTIME_ADJUSTED_PRICE_SUPPORT_ENABLED=false
VERSION=0.7.0
```

The current policy is authoritative now. Future-enablement requirements in
this document are qualification gates only: this document does not enable
QFQ or HFQ, change runtime behavior, or authorize implementation. Any future
enablement requires a separately reviewed design authority and explicit
post-merge implementation authorization.

This policy concerns only PIT-safe adjusted historical-price semantics. It
does not define portfolio accounting, total-return analytics, dividend
forecasting, corporate-action analytics, or an adjusted-price UI.

## 2. Current repository facts

The Moomoo historical collector accepts `NONE`, `QFQ`, and `HFQ`, and passes
the selected value to the provider as `AuType`. Curated and Canonical records
preserve `adjustment`; Canonical row/build identities, PIT sample keys, and
Dataset scope identity already bind that mode.

That identity binding does not establish corporate-action point-in-time
legality. The current PIT request validates `adjustment == "NONE"` and fails
closed for all other values. There is no temporary override, environment
flag, or unsafe opt-out.

The current PIT architecture has two independent clocks:

- `market_available_at` is the bar-market clock: the earliest instant a
  complete bar could have been known;
- `archive_available_at`, constrained by optional `dataset_as_of`, is the
  MarketVault archive/reproducibility clock.

It has no `corporate_action_known_at`, factor revision identity, factor
authority content ID, or corporate-action authority pin. Therefore archive
time cannot prove when an adjustment fact became public market knowledge.

```text
CURRENT_CANONICAL_ADJUSTMENT_IDENTITY_BOUND=true
CURRENT_ADJUSTMENT_FACTOR_IDENTITY_BOUND=false
CURRENT_CORPORATE_ACTION_AUTHORITY_IDENTITY_BOUND=false
CURRENT_MARKET_CLOCK_PRESENT=true
CURRENT_ARCHIVE_CLOCK_PRESENT=true
CURRENT_CORPORATE_ACTION_KNOWLEDGE_CLOCK_PRESENT=false
ARCHIVE_CLOCK_ALONE_SUFFICIENT=false
```

## 3. Official provider evidence

Each page below was reviewed independently. The version is recorded from
that page's observed heading; no single version claim is substituted for the
individual records.

| Page | URL | Observed heading/version | Capture date |
| --- | --- | --- | --- |
| Quotation Definitions | https://openapi.moomoo.com/moomoo-api-doc/en/quote/quote.html | Quotation Definitions, Moomoo API Doc v10.9 | 2026-09-11 |
| Stock Price Adjustment / Quote Related | https://openapi.moomoo.com/moomoo-api-doc/en/qa/quote.html | Quote Related, Moomoo API Doc v10.9 | 2026-09-11 |
| Get Adjustment Factor | https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-rehab.html | Get Adjustment Factor, Moomoo API Doc v10.10 | 2026-09-11 |
| Corporate Actions - Dividends | https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-corporate-actions-dividends.html | Get Corporate Actions - Dividends, Moomoo API Doc v10.10 | 2026-09-11 |
| Corporate Actions - Stock Splits | https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-corporate-actions-stock-splits.html | Get Corporate Actions - Stock Splits, Moomoo API Doc v10.10 | 2026-09-11 |

These links are review provenance, not an immutable evidence seal. A future
enablement design must preserve the exact provider authority it relies on in
a durable, content-identified record.

## 4. Provider adjustment semantics

The official definitions identify:

- `NONE` as actual/unadjusted price;
- `QFQ` as forward/default adjustment;
- `HFQ` as backward/cumulative adjustment.

For default/forward adjustment, the current price is the benchmark and all
previous prices are recalculated. For multiple adjustments, factors later
than the adjustment/calculation date participate. Consequently:

```text
QFQ_FUTURE_ACTION_RESTATEMENT_RISK=CONFIRMED
```

An adjusted QFQ bar fetched after a later corporate action can encode that
later action into an earlier Feature or Label period. Its later archive time
does not make the earlier value market-knowledge legal.

For cumulative/backward adjustment, the documented formula selects factors
earlier than or on the calculation date. The documentation therefore does
not indicate that a later post-bar action rewrites an earlier HFQ bar:

```text
HFQ_LATER_ACTION_RESTATEMENT_RISK=NOT_INDICATED_BY_DOCUMENTED_FORMULA
```

However, the provider does not expose historical factor revisions or an
as-of factor authority. Corrections to earlier factors and their historical
knowledge state cannot be reconstructed from the documented interface:

```text
HFQ_FACTOR_REVISION_AS_OF_SAFETY=UNPROVEN
```

Both modes remain unqualified for PIT.

## 5. Factor and corporate-action API limits

The documented `get_rehab(code)` response includes `ex_div_date`, action
parameters for splits/mergers, dividends, bonus or converted shares,
allotments, additional issuance and spin-offs, plus forward and backward
adjustment factor A/B values. Its request has no `as_of`, `revision`, or
`version` parameter, and its response has no formal `factor_known_at`,
`revision_id`, or historical revision chain.

```text
PROVIDER_FACTOR_HISTORICAL_AS_OF_QUERY_AVAILABLE=false
PROVIDER_FACTOR_REVISION_ID_AVAILABLE=false
```

The dividend API exposes date-level `pub_date`, `record_date`, `ex_date`, and
payment-date facts. Its lifecycle status is market/security-type limited.
The stock-split API exposes announcement-date fields and additional
market-specific lifecycle fields; an integer documented as an announcement
*date* timestamp is not proof of the exact public announcement instant.
These APIs do not constitute a complete historical authority for every US
corporate action that may contribute to adjustment factors.

```text
PROVIDER_CORPORATE_ACTION_EXACT_KNOWN_AT_AVAILABLE=false
```

## 6. Leakage boundary

For a Feature bar at `T0`, Feature close at `T1`, action announcement at
`T2`, economic effective/ex date at `T3`, provider fetch at `T4`, and
`dataset_as_of` at `T5`, a QFQ value fetched at `T4` may reflect the action
when `T2 > T1`. Allowing it because `T4 <= T5` would leak post-Feature
knowledge into the Feature set.

The same rule applies independently to Labels: information known after
`label_window_close` is illegal for that Label observation. Information
after the Feature close but no later than the Label close can be legitimate
Label knowledge only when an authoritative corporate-action clock proves it.

An archived adjusted snapshot proves reproducibility of the bytes that were
captured. It does not prove market-knowledge legality. Thus
`MODEL_A_ARCHIVE_SNAPSHOT` is insufficient: a 2026 archive containing a 2025
action must not be used for a 2024 Feature merely because
`dataset_as_of=2026`.

## 7. Three-clock future requirement

Any future adjusted-price enablement requires three distinct authorities:

1. bar market clock: `market_available_at`;
2. archive clock: `archive_available_at` and optional `dataset_as_of`;
3. corporate-action knowledge clock: a future `corporate_action_known_at`
   proving when the exact action/factor revision became publicly knowable.

```text
THIRD_CLOCK_REQUIRED_BEFORE_FUTURE_ADJUSTED_ENABLEMENT=true
THIRD_CLOCK_RUNTIME_IMPLEMENTED=false
```

Future role cutoffs are:

- Feature corporate-action knowledge no later than `feature_window_close`;
- Label corporate-action knowledge no later than `label_window_close`.

`dataset_as_of` remains an independent archive reproducibility cutoff. Both
the role-specific market-knowledge predicate and the archive predicate must
hold. Defining an adjustment cutoff as
`min(role_window_close, dataset_as_of)` is rejected because it conflates what
the market knew with what MarketVault had archived.

```text
RELATION_TO_DATASET_AS_OF=INDEPENDENT_CONJUNCTIVE_CLOCKS
```

## 8. Date-only and revision policy

If an authority carries only a publication date, same-publication-date
intraday PIT must not assume a publication time:

```text
SAME_DAY_INTRADAY_USE_WITH_DATE_ONLY_KNOWN_AT=false
```

A later design may conservatively use the next market session after that
calendar date only when the provider formally defines the date in the
relevant market timezone, the calendar is authoritative, and no more precise
timestamp authority exists. It must not fabricate an exact `known_at`.

Future authority must preserve immutable, versioned proposal, revision,
cancellation, retraction, and supersession events. Each version must bind
sufficient source contract/version, `known_at`, `captured_at`, event
identity, economic effective date, status, factor facts, relationship to
prior versions, and logical content identity. The exact artifact schema is
not frozen here. Current-state records without historical revision evidence
are not sufficient.

## 9. Current policy

```text
RECOMMENDED_POLICY_MODEL=MODEL_C_NONE_ONLY
CURRENT_PIT_NONE_ONLY_GUARD=true
CURRENT_RUNTIME_ALREADY_CONFORMS=true
FEATURE_ADJUSTED_PRICE_ALLOWED=false
LABEL_ADJUSTED_PRICE_ALLOWED=false
QFQ_PIT_ALLOWED=false
HFQ_PIT_ALLOWED=false
```

QFQ/HFQ may remain available to upstream collection and non-PIT consumers;
that does not qualify them for Feature or Label assembly.

Existing QFQ/HFQ Raw, Curated, or Canonical artifacts are not automatically
PIT-safe merely because `adjustment` is identity-bound or their capture time
is known:

```text
EXISTING_ADJUSTED_ARTIFACTS_AUTOMATICALLY_QUALIFIED=false
```

## 10. Current identity and version impact

This policy preserves existing runtime semantics and artifacts. Therefore:

```text
PIT_ASSEMBLER_VERSION_CHANGE_REQUIRED=false
PIT_SAMPLE_KEY_VERSION_CHANGE_REQUIRED=false
PIT_SAMPLE_VERSION_ID_VERSION_CHANGE_REQUIRED=false
PIT_ASSOCIATION_SCHEMA_VERSION_CHANGE_REQUIRED=false
CANONICAL_IDENTITY_ENCODING_CHANGE_REQUIRED=false
CANONICAL_SCHEMA_CHANGE_REQUIRED=false
CANONICAL_BAR_KEY_CHANGE_REQUIRED=false
CANONICAL_ROW_VERSION_ID_CHANGE_REQUIRED=false
CANONICAL_CONTENT_ID_CHANGE_REQUIRED=false
CANONICAL_BUILD_ID_CHANGE_REQUIRED=false
CANONICAL_MANIFEST_CHANGE_REQUIRED=false
DATASET_MANIFEST_CHANGE_REQUIRED=false
DATASET_ID_CHANGE_REQUIRED=false
DATASET_CATALOG_CHANGE_REQUIRED=false
VERSION=0.7.0
```

Exact future version changes are deliberately not pre-authorized:

```text
FUTURE_ADJUSTED_ENABLEMENT_PIT_VERSION_IMPACT=TBD
FUTURE_ADJUSTED_ENABLEMENT_CANONICAL_IDENTITY_IMPACT=TBD
FUTURE_ADJUSTED_ENABLEMENT_DATASET_IDENTITY_IMPACT=TBD
```

One invariant is frozen: any future corporate-action/factor authority that
changes which adjusted values are legal must be identity-bound before
adjusted PIT can be enabled.

## 11. Future enablement gates

```text
CORPORATE_ACTION_AUTHORITY_REQUIRED_BEFORE_FUTURE_ENABLEMENT=true
CORPORATE_ACTION_AUTHORITY_IDENTITY_REQUIRED=true
CORPORATE_ACTION_ARTIFACT_SCHEMA_FROZEN=false
CORPORATE_ACTION_RUNTIME_IMPLEMENTED=false
LIVE_PROVIDER_PROBE_REQUIRED_FOR_CURRENT_POLICY=false
LIVE_PROVIDER_PROBE_REQUIRED_BEFORE_FUTURE_ENABLEMENT=true
LIVE_PROVIDER_PROBE_ALONE_CAN_PROVE_HISTORICAL_KNOWN_AT=false
```

A future, separately authorized probe may capture fixed US action/control
periods across `NONE`, `QFQ`, `HFQ`, `get_rehab`, dividend records, and
stock-split records at multiple capture times. Such a probe can characterize
provider restatement behavior, but it cannot retroactively prove when an
action was historically public. Durable official authority and longitudinal
immutable evidence remain necessary.

## 12. Workstream closure

This P2 workstream is a safety-policy closure, not an enablement project. It
may close after independent design review and merge while adjusted-price PIT
runtime support remains disabled. Any later QFQ/HFQ enablement is a separate
qualified workstream.
