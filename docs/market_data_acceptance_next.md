# Market-data trust task package: Q42–Q45

The next package is [Q46–Q48 actual research-data evidence and sample usage](intraday_market_evidence_next.md).
The completed comparison and acceptance meanings below remain unchanged.

## Baseline, authorization and delivery

Verified baseline: `90ad32e3f48130a17c71db7001070bc9c8af9f3c`, tree
`9437f4e3183748aeeb10cdd8f048000e9e79309b`, after Q41. The owner's
2026-10-11 instruction adopts the supplied Improvement Suggestions 02 and
authorizes implementation, in-scope repairs, tests, commits, push, PR,
independent final-candidate review and conditional squash merge. Each task
starts from the preceding task's verified main. Required natural PR CI,
reviewed candidate identity and current base must agree before merge; terminal
successful CI for the exact resulting main is required before the next task.
The package follows the supplied Development Workflow v2 and Personal Local
Tool Workflow v1 plus the checked-in governance. Package version stays 0.9.0.

The next useful step is trustworthy input evidence. Q39–Q41 already deliver
selection-procedure comparison, simultaneous family evidence and fixed
decision execution stress; none is repeated here. Canonical already retains
physical source and row versions. A new hash alone is not independent market
validation, and archive time is not a vendor's first publication time.

Order: **Q42 numeric admission → Q43 SDK session capability → Q44 explicit
two-source comparison → Q45 fixed acceptance suite and observed revisions**.
Independent read-only investigations may overlap; implementation and merges
remain sequential. Existing CI classification and eleven functional partitions
remain authoritative. Only measured bottlenecks justify further partition work;
no test filtering, lowered gates or forced reduced tier.

## Q42 — shared numeric constraints and scoped basic quality

**Goal:** stop invalid OHLC, volume and option strikes receiving a misleading
all-PASS basic report. The A/B defects were reproduced through the current
functions, not merely copied expressions: all-zero/self-consistent negative
OHLC, infinite high/volume, and NaN strike were admitted. This does not establish
that these values reached a completed backtest.

**Design/defaults:** share finite positive price and finite nonnegative volume
predicates across basic checks, Canonical builder/reader admission and intraday data
admission. Strikes must be present, finite and strictly positive. Zero volume
remains valid. Coercible numeric strings remain supported at normalization
boundaries; typed research JSON keeps its existing stricter checks. Include all
duplicate-key columns in required-column checks so malformed frames produce
FAIL instead of KeyError. A `validation_scope` result identifies
`BASIC_BAR_STRUCTURE_AND_NUMERICS`, explicitly separate from session coverage,
Canonical/PIT qualification and independent market accuracy.

**Dependencies:** existing normalization, quality recording, complete-snapshot
selection, Canonical and research loaders. No new dependency or stored schema.
Accepted valid data retains its existing IDs and calculation bytes. Canonical
admission, including previously saved artifact reads, becomes stricter for
nonpositive prices and negative volume; no
automatic rewrite of old artifacts, optional market fields or economic returns.

**Acceptance:** discriminating regression tests reject the reproduced cases,
missing/non-numeric strikes and missing duplicate keys; valid prices and zero
volume pass. Real collection service with an offline provider preserves raw
input yet marks invalid numeric runs PARTIAL and excludes them from complete
selection. Related Canonical, normalization, options and intraday regressions
pass. Tests must not replace the admission boundary being demonstrated.
The existing TS2 zero-price domain checks now require refusal at Canonical
reader admission; zero-volume ratio denominators still reach and fail the
formula domain check. This is an explicit earlier rejection, not a weakened
formula guard or a historical artifact rewrite.
The legacy Dataset feature suite likewise keeps verified fixtures numerically
valid: nonpositive return inputs exercise the existing transforms directly,
and legal zero-volume Canonical data proves the executor's error wrapping,
including transform/spec/sample attribution and the original cause.

**Exclusions:** filling or correcting data, changing run-wide quality attribution,
rewriting archives, volatility-domain expansion, corporate-action accounting,
QFQ/HFQ research admission or complete market accuracy claims.

## Q43 — SDK session semantics without silent downgrade

**Goal:** a request for ALL must never silently become merely pre/post-market
history when the installed SDK lacks its session parameter.

**Design/defaults:** inspect the callable's explicit keyword capability before
requesting history. Use native session when supported; legacy `extended_time`
is permitted only for documented equivalent RTH/ETH requests. ALL requires
native session support. Unknown capability and unsupported scope fail clearly.
Do not catch a broad execution TypeError and retry with altered semantics.
Retain pagination and the existing batch retry policy. Surface requested scope,
effective request scope and SDK capability evidence without treating capability
as proof of actual full-session response coverage.

**Dependencies:** Q42; current SDK loader, collector, collection reports and
per-symbol failure handling; official moomoo history API semantics.

**Acceptance:** current-session pagination, equivalent legacy RTH/ETH, unsupported
ALL before a data request, and an internal TypeError with no fallback/retry.
Successful archive evidence states request versus effective support; failed
symbols remain failures without poisoning unrelated successful symbols through
new run-wide quality flags. Offline tests do not claim live OpenD qualification.

**Exclusions:** new session aliases, new SDK/transport framework, provider
qualification, live OpenD calls, changing trading calendars or timestamp rules.

## Q44 — explicit independent-source bar comparison

**Goal:** compare two explicitly supplied finite datasets without hiding one-sided
coverage or incompatible meaning. Deliver a Python API and settings-independent
CLI, a normalized input contract and a reproducible report.

**Design/defaults:** US equities/ETFs, NONE, explicit RTH and one declared minute
interval. Require unambiguous UTC instants, bar start/end convention, interval
endpoints and aggregation/volume basis. Compare exact business keys, retain
duplicates, invalid rows, left-only/right-only rows and denominator counts;
never silently take only an intersection. Report OHLC absolute/relative
differences and volume differences with explicit fixed tolerances (default
zero). Preserve provenance, source/version/observation time and input content
identity. Distinguish evidence of source independence from different labels;
known shared upstream or unknown lineage cannot assert independent verification.
Missing rows have unknown reason unless separately supported; no filling,
averaging, automatic ratio fitting or replacing source values.

**Dependencies:** Q42 constraints, Q43 declared request semantics, existing
offline report/CLI conventions. Explicit local source exports are the primary
input; reuse verified archive/Canonical reads where applicable, not a new
provider or general storage system.

**Acceptance:** real CLI/API compare same-basis inputs; controlled wrong prices,
volume mismatch, duplicates, one-sided gaps, ambiguous timestamps and
incompatible rules produce distinct truthful outcomes. Re-running identical
inputs is stable and inputs remain byte-identical. Synthetic fixtures prove
the comparator only. A real independent market acceptance result requires
actual qualifying external data; absent data is NOT_RUN/UNAVAILABLE, never PASS.

**Exclusions:** runtime downloads, subscriptions, arbitrary market adapters,
real-market accuracy certification, automatic data repair or inferred actions.

## Q45 — fixed cases and observed snapshot changes

**Goal:** make Q44 repeatable on a predeclared case set, retaining missing and
failed cases, and explain changes between explicitly observed snapshots.

**Design/defaults:** a bounded case manifest declares normal, early-close,
DST-before/after, corporate-action and halt/low-activity categories with exact
scope and source locators. Missing inputs retain their original place and
denominator. Reuse Q44 alignment/statistics. Optional explicit earlier snapshots
allow added/removed/changed bars and new/persistent/resolved discrepancies to
be reported. Rules and case definitions must match for historical comparison;
changed scope is not a market revision. No implicit latest selection. Reports
are separate new artifacts; previous evidence is not overwritten.

**Dependencies:** Q44 comparison kernel and source contract, existing archived
snapshot/version evidence where supplied. No global database or background job.

**Acceptance:** a mixed fixed set keeps all pass/difference/unavailable cases and
every category denominator; detail reconciles to Q44. Added, missing, changed
OHLC/volume and unchanged bars are correctly identified. Changed definitions
cannot masquerade as revisions. No earlier snapshot means no historical baseline.
Only changes between the supplied observations are proven; capture/archive time
does not claim the vendor's revision-publication time or complete revision history.

**Exclusions:** supplier-wide historical revision authority, inferred knowability,
automatic schedule creation, archive replacement, schema migration, corporate
action total returns, historical whole-market membership, cross-experiment TEST
exposure enforcement or additional strategy searches.

## Empirical completion boundary

This package's engineering completion includes actual entry-point tests,
independent review, required CI and main integration. Real-data acceptance is a
separate result requiring independently sourced, same-basis actual inputs for
the declared cases. No such files accompany this task. Missing cases remain
visible and NOT_RUN; test fixtures cannot certify vendor accuracy. Q45 is chosen
over TEST-use registration because it directly reuses Q44; a truthful TEST
exposure feature must also cover unsaved CLI/API/GUI runs and unknown prior use.
