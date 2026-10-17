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
