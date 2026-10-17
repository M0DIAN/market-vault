# S7-S9: repair the observed prepare failure

Owner-authorized sequential development package, 2026-10-17. Start from
bf5ea33d1597b8958c4a9c739baba95a34ca8554 (S6). Each item requires independent
final-candidate review, required PR CI, squash, and exact-main natural push CI
before implementing the next. No deployment, REAL operation, account reset,
paid data, model/search/UI work, or runtime database migration.

## Actual input and uncertainty

The owner's sanitized prepare report says FAILED/CASH_CURRENCY_NOT_USD,
zero intentions, no baseline/reconciliation, and a sticky stop. Its seven
reported LF-normalized execution/summary source hashes match the named source
files at the baseline. This is source-file correspondence, not process or
broker attestation. The report did NOT retain the returned currency or cash
field availability; neither "the account lacks USD" nor a specific returned
currency can be concluded. Keep the original report and private journal.

Official funds documentation distinguishes display currency from explicitly
currency-denominated fields. Some account types ignore the requested display
currency; cash is obsolete and us_cash denotes actual USD cash. The upstream
Python SDK initializes absent currency to Currency.NONE and missing per-currency
cash to its unavailable sentinel, populating us_cash from USD cashInfoList.
This explains possible response shapes, not the owner's exact missing payload.
Do not infer USD from a US context, requested USD, a balance of zero, or N/A.

## Fixed package

| Task | Goal and solution | Dependency/default and acceptance | Excluded |
| --- | --- | --- | --- |
| S7 funds diagnostics | Record a fixed, amount-free FUNDS_RESPONSE before interpreting the current funds response; retain it through existing S4/S5 export. | Existing USD guard remains. Actual prepare failure still stops with zero intentions, but reports display-currency classification and cash/us_cash availability. Export revalidates the allowlist. | Raw rows/amounts/IDs, extra queries, a diagnostic service, changing acceptance. |
| S8 USD cash basis | Prefer finite explicit us_cash; retain the strictly USD-labelled legacy cash path only as a separate compatibility basis. Persist the selected basis and reject cross-basis comparison. | After S7 main verification. Missing/unavailable/invalid explicit cash is not zero; unknown display currency cannot authorize legacy cash. Equal numbers do not make different definitions comparable. Test prepare/reconcile and failure/restart paths. | FX conversion, modifying balances, SDK upgrades, guessing a US account's denomination, automatic rebasing or fees. |
| S9 pre-order failure continuation | Permit explicit linked fresh preparation only after a read-only proof that the prior journal stopped during a completed funds-related prepare failure, before any intention/baseline. Pin the same account. | After S8 main verification. Preserve the old journal byte-for-byte and stopped; reject unknown events, incomplete history, any intention/baseline, identity drift, or reused destination. New preparation still cannot place/cancel. | General resume, clearing stop, retrying an unknown submission, deleting/migrating journals or bypassing order budgets. |

Engineering completion is not owner-local completion. The revised prepare must
be run by the owner and inspected before claiming this actual failure resolved.
No simulator order/fill/fee/latency/slippage or strategy-forward gate is closed
by offline tests. Independent market data remains NOT_SUPPLIED.

## S7 diagnostic fields

The existing funds query still explicitly passes SIMULATE, pinned acc_id,
refresh_cache=True and Currency.USD. Its new event records only:

- requested_currency: USD;
- display_currency: a known currency/none/unavailable classification, never raw text;
- cash_state and us_cash_state: FINITE, MISSING, UNAVAILABLE or INVALID;
- response_shape: SINGLE_ROW or INVALID_SCHEMA.

These describe the SDK-returned table, not protobuf presence or trading power.
A missing column is distinct from an unavailable or invalid value; numeric zero
is finite, not missing. A malformed response is diagnosed without exporting its
rows. The same strict schema/currency/number guards still decide acceptance.
Later funds-response activity marks an earlier reconciliation as historical.
Old reports remain unchanged, and reports do not expose balances, identifiers,
unrelated holdings or arbitrary SDK errors. No extra command is needed.

## Sources checked 2026-10-17

- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-funds.html
- https://openapi.moomoo.com/moomoo-api-doc/trade/get-funds.html
- https://github.com/MoomooOpen/py-moomoo-api/blob/dfb09498bdd34bdeb37c12b3cfec6d55908450d9/moomoo/trade/trade_query.py
- https://github.com/MoomooOpen/py-moomoo-api/blob/dfb09498bdd34bdeb37c12b3cfec6d55908450d9/moomoo/trade/open_trade_context.py

Public SDK source above is not a claim to have read the owner's installed SDK
bytes. Owner runtime reports moomoo 10.09.6908 and Python 3.14.4. No user payload,
private journal, credential or generated market data belongs in this repository.


## S8 selected USD cash and reconciliation meaning

The existing query still uses explicit SIMULATE/pinned acc_id/refresh/USD. A
finite us_cash, including zero or a negative observed balance, is selected as
USD_CURRENCY_BALANCE independently of the optional display currency or obsolete
cash field. Negative balances are observations, not permission to borrow; the
existing separate cash-capacity/no-short-cover submission checks remain intact.

Missing/None/NONE/N/A/empty explicit USD is not imputed. Only a finite legacy cash
with returned currency exactly USD may use LEGACY_DISPLAY_USD compatibility.
NaN/infinity/bool/malformed explicit USD raises USD_CASH_INVALID and cannot fall
back to a display sum. Missing legacy columns fail schema validation; an unknown
or non-USD legacy display currency retains CASH_CURRENCY_NOT_USD. Unusable
strictly USD-labelled legacy cash raises USD_CASH_UNAVAILABLE. This does not
promise either field is available for the owner's particular simulator account.

New account observations/baselines record cash_basis. Reconciliation records
both selected and baseline bases and blocks CASH_BASIS_CHANGED before computing
a cash residual when they differ. Equal numerical amounts do not waive that
check. Original v1 baselines without the additive field had strict USD-labelled
legacy semantics and are read as LEGACY_DISPLAY_USD without updating them;
missing currency, an explicit unknown/null basis or non-USD currency blocks as
CASH_BASIS_UNVERIFIED. No baseline is replaced and no schema is migrated.

The upload allowlists these basis labels, not cash amounts. All existing
non-atomic/fee/flow/sticky-stop limits still apply. This replaces the original
S3 displayed-cash-only definition; it does not claim a real preparation succeeded.


## S9 linked preparation, not unstop or order retry

The existing qualifier's `prepare` action accepts optional `--previous-journal`.
Close all writers first. Select the original private SQLite journal, not the
sanitized upload. Its schema and metadata are read with the existing S4 parser.
A separate read-only rollback-mode transaction holds a shared lock during the
new preparation; the predecessor is never opened with the write-mode journal
class. Its SHA256 is checked before and after the operation, and no old rows,
stop markers, baselines or schema are changed. WAL, active rollback journals,
unreadable/locked files, malformed or incomplete histories are refused.

Only these exact original histories qualify: prepare START, optional S7
FUNDS_RESPONSE, EMERGENCY_STOP, and matching prepare FINISH/FAILED, with no
intention or baseline and no other event. The failure must be one of
CASH_CURRENCY_NOT_USD, USD_CASH_INVALID, or USD_CASH_UNAVAILABLE. This bounded
exception does not apply to a failed submission, an unfinished action, a manual
stop after success, a later account discrepancy or an unrecognized operation.
It verifies local records, not signed broker history or the owner's installed
SDK payload. The old failure and stop remain authoritative for that old run.

The new destination is fixed: append `.funds-repair.sqlite` to the original
canonical filename (for `private.sqlite`, use `private.sqlite.funds-repair.sqlite`
in the SAME directory). Any other destination or an existing successor refuses.
Exclusive creation prevents sibling continuations through this path; once the
successor exists, do not delete, rename or replace it to retry. This is not an
account-wide budget controller, and manually copying/renaming journals or using
other entry points must not bypass the owner's single-controller restriction.
A failed successor contains an origin event and is not itself eligible for this
one-step exception. Keep it and return its failure report instead of chaining
new runs. No sidecar registry or migration is introduced.

The account ID comes solely from the verified predecessor. Do not supply
--account-id alongside --previous-journal; REAL or changed-account selection is
rejected by S1 before creating the successor. No new broker endpoint is added:
preparation uses the existing S8 funds basis and S3 baseline/reconciliation and
still never places or cancels. The new journal starts with PREPARATION_ORIGIN,
then its own action history. Its safe export contains only predecessor SHA256,
prior failure code and event count, not source paths, account IDs or balances.
Qualifier/exporter source identities continue to identify the changed code.

PowerShell command shape, with an existing reviewed checkout/environment:

```powershell
$prior = (Resolve-Path -LiteralPath (Read-Host 'Full path of the original failed private.sqlite')).Path
$next = $prior + '.funds-repair.sqlite'
$out = Join-Path (Split-Path -Parent $prior) ('prepare-repair-' + [guid]::NewGuid().ToString('N') + '.json')
python -m market_vault.moomoo_simulation_qualifier prepare --previous-journal $prior --journal $next --output $out
```

Use the pinned reviewed source via PYTHONPATH as in the earlier instructions;
this shape alone does not select an interpreter/source checkout. Upload only
the new JSON, even on failure. Retain both private journals and the old report
locally. A PREPARED result is only the new pre-order baseline check: orders,
recovery under real disconnection, costs and strategy-forward qualification
remain unaccepted. No submit/cancel command is part of this repair instruction.
