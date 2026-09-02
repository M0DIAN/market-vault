# Market-Bar Timestamp Semantics V2 Production Activation

## Status

This document seals the production activation evidence for the
`10.9-mv-ts2` market-bar cohort. It records three distinct outcomes that must
not be combined or reinterpreted:

```text
TS2_PRODUCTION_ACTIVATION_ATTEMPT_1=FAIL
FAIL_REASON=UNAUTHORIZED_COVERAGE_REPORT_SCOPE

TS2_PRODUCTION_ACTIVATION_SCOPE_REMEDIATION=PASS
PRODUCTION_TS2_OPERATIONAL_STATE=ACCEPTED
PRODUCT_DEFECT_FOUND=false
```

The successful read-only remediation and the accepted current operational
state do not retroactively convert activation attempt 1 into a pass. The ALL
Coverage report was not authorized.

## Sealed Production Identity

```text
FORMAL_MAIN_SHA=ef99c49fda9f7076443c2b352f3a3be528f8c463
PRODUCTION_EXE_SHA256=eb1bb136ac1968b92c31866f688a9cc7e3b1970ad0de436cfdfae066aa8d977e
PRODUCTION_SETTINGS_SHA256=06f95924c1a290b44c00eb62be226e912afb0db8c96c21ded304d0eb1209a8cd
PRODUCTION_SCHEMA=10.9-mv-ts2
AUTHORIZED_PHYSICAL_SCOPE=US.SPY / 2026-08-24 / 1m / RTH / NONE / 10.9-mv-ts2
VERSION=0.7.0
```

## Sealed Physical Data Result

The authorized physical scope contains one immutable Raw/Curated pair and one
market-bar ingestion run:

```text
RAW_FILE_COUNT=1
CURATED_FILE_COUNT=1

RAW_ROWS=390
RAW_FIRST=09:31
RAW_LAST=16:00

CURATED_ROWS=390
CURATED_FIRST=09:30
CURATED_LAST=15:59

REGULAR_ROWS=390
AFTER_HOURS_ROWS=0
PRE_MARKET_ROWS=0
OVERNIGHT_ROWS=0
DUPLICATE_TIMESTAMPS=0

CURRENT_VIEW_ROWS=390
CURRENT_VIEW_FIRST=09:30
CURRENT_VIEW_LAST=15:59
CURRENT_VIEW_1600_ROWS=0

MARKET_BAR_INGESTION_RUN_COUNT=1
RTH_RUN_ID=d701ce34-e4a0-42e4-b2ed-8d0ae91ef0f5
RTH_RUN_STATUS=SUCCESS
RTH_RUN_ROWS=390
RTH_RUN_SUCCESSFUL_SYMBOLS=["US.SPY"]
RTH_RUN_FAILED_SYMBOLS={}
```

## Report-Only Scope Incident

Read-only inspection proved that the incorrect ALL audit scope created no
physical market-bar cohort:

```text
ALL_RAW_FILES=0
ALL_CURATED_FILES=0
ALL_MARKET_BAR_INGESTION_RUN_COUNT=0
ALL_SNAPSHOT_PAIR_COUNT=0
UNAUTHORIZED_PHYSICAL_MARKET_DATA_CREATED=false
```

The incident affected audit-report scope only. It did not create a second Raw
file, Curated file, ingestion run, or registered snapshot pair.

## Retained Incident Evidence

The unauthorized report remains part of the production audit trail:

```text
UNAUTHORIZED_REPORT_PATH=D:\MarketVault\App\MarketVault\reports\data_quality\market_bars_audit_abf5e339-7b8e-4efe-93e1-97626c4d78a9.json
UNAUTHORIZED_REPORT_SHA256=7b68b3cc7146ebaf707861c8593b77a50eb3c05275623abdf5442e9d123238fd
UNAUTHORIZED_REPORT_STATUS=WARN
UNAUTHORIZED_REPORT_SESSION=ALL
UNAUTHORIZED_REPORT_COVERAGE_PERCENTAGE=0
SCOPE_INCIDENT_EVIDENCE_RETAINED=true
```

The report was intentionally not deleted, renamed, moved, edited, or
quarantined. Retaining it does not authorize its scope or change activation
attempt 1 from FAIL.

## Root Cause

```text
INCIDENT_ROOT_CAUSE=ACTIVATION_PROCEDURE_SESSION_SELECTION_ERROR
AUTOMATIC_BACKGROUND_GENERATION=false
PRODUCT_DEFECT_FOUND=false
```

Formal-main source inspection established that:

- `ConsoleBackend.coverage_audit` defaults `session` to `ALL`.
- `AuditPage` presents session choices as `["ALL", "RTH", "ETH"]`, with ALL
  first and therefore selected by default.
- Coverage Audit runs from the explicit audit button action; no automatic or
  background invocation was found.
- Coverage Audit is a local audit that may persist an audit report. Running it
  does not itself imply physical market-data ingestion.

The evidence therefore supports an operator procedure error, not a product
defect.

## Mandatory Coverage Preflight

Before executing Coverage Audit, the operator must explicitly select and
visibly verify the Coverage session against the authorized physical scope.
Never rely on the default session selection.

For an RTH Timestamp Semantics V2 activation:

```text
EXPECTED_COVERAGE_SESSION=RTH
REQUIRED_PREFLIGHT=selected Coverage session == RTH
```

Audit scope and physical collection scope are separate approvals. A successful
RTH collection does not authorize an ALL audit scope. The operator must compare
symbol, date range, interval, session, adjustment, and source schema before
starting the audit.

If an incorrect audit report is created:

1. Preserve the report as incident evidence; do not silently delete or alter
   it.
2. Stop additional production operations and classify the incident read-only.
3. Prove whether contamination is report-only or includes physical data.
4. Do not recollect valid physical data merely to repair an audit-report scope
   mistake.

## Closure Boundary

This evidence seal records completed operations; it authorizes no new
collection, audit, cleanup, schema change, or other production mutation. The
historical attempt remains FAIL, while the separately verified current TS2
production state is ACCEPTED.
