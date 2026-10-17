# Moomoo simulation: S1-S3 implementation package

Owner-authorized on 2026-10-17: implement, test, commit, push, open PRs,
independently review each final candidate, squash after required CI and exact
identity checks, verify the resulting main push CI, then continue. No release,
production installation, account reset, real-money order, or REAL switch.

## Baseline and evidence boundary

PR #362 is prerequisite delivery, not another implementation task. Its existing
quote-only capture and owner-supplied repeated snapshot are reused, not rewritten.
The owner has no independent data provider. Independent market-data verification
remains NOT_SUPPLIED/NOT_EVALUATED; repeated identical downloads cannot close it.
Do not use unverified turnover/volume as accepted VWAP or execution-price evidence.
Do not add learners, parameter search, UI, extra data subscriptions or another
evidence platform in this package.

There are two different acceptance layers, fixed before implementation:

- **Engineering delivery:** actual CLI/API paths under controlled offline SDK
  responses, relevant failure/restart tests, independent final-HEAD review,
  required PR CI, squash, and exact-main natural push CI. This is mergeable
  development code, not permission to operate an account unattended.
- **Owner-local qualification:** the real OpenD/broker responses below. These
  remain NOT_RUN until supplied and inspected. Offline substitutes cannot mark
  a broker order, fill, account balance or forward strategy result as observed.

## S1 — pinned simulation account and read-only probe

**Goal:** distinguish a usable US stock-capable paper account from REAL,
unsupported, disabled, missing or ambiguous accounts, including after reconnect.

**Solution:** reuse the lazy SDK loader; create only an OpenSecTradeContext with
explicit US filter and loopback host; read get_acc_list; pin acc_id after a unique
valid selection (or validate an explicit local ID). Require SIMULATE, ACTIVE,
US market permission and STOCK or STOCK_AND_OPTION. Never use acc_index or
substitute another account when a pin disappears. Clear readiness before every
validation. Close contexts on success and failure. Export allowlisted diagnostic
metadata only, not raw rows, account IDs, card numbers or SDK exception text.

**Dependency/default:** after #362 main validation. Port 11111, SecurityFirm.NONE
(auto routing by the existing SDK, not a guessed firm); explicit firm override
must exist in the SDK and is never silently replaced. No trade unlock and no
orders, funds, positions or market-data queries in the probe.

**Engineering acceptance:** mixed REAL/paper lists select only the sole eligible
paper account; ambiguous/malformed lists fail; explicit REAL IDs are rejected;
reconnect remains pinned or fails closed; failed revalidation invalidates prior
readiness; actual module CLI produces a sanitized JSON without overwriting an
existing file. Imports/help work without the OpenD SDK or connection.

**Owner-local acceptance:** run the probe through two actual connections, inspect
ACCOUNT_VERIFIED and reconnect_same_account=true, orders_sent=false. This proves
only account selection/reconnect, not execution recovery or data correctness.

**Excluded:** live orders, automatic login/unlock, broker account changes, funds
or position exports, GUI, key storage and generalized provider abstraction.

## S2 — bounded simulation orders and durable intentions

**Goal:** send a bounded, explicit paper order/cancel and preserve enough evidence
to avoid blind resubmission after a timeout or crash.

**Solution:** a separate execution module using S1; every relevant SDK call has
explicit SIMULATE and pinned acc_id. Validate order type, symbol, quantity,
notional and trading window. Persist intention before submission, bind returned
broker order identity, retain unknown outcomes. Cancellation is limited to
orders owned by this journal. The local runtime journal is separate from market
catalogs, append-preserving and never automatically reset or migrated.

**Dependency/default:** S1 merged/main verified. First scope US.SPY/US.QQQ,
whole shares, limit DAY orders, regular session only, no borrowing/shorting,
no strategy-selected price or automatic live run. Conservative engineering
limits are recorded explicitly by the executable entry point before use.

**Engineering acceptance:** same intention cannot submit twice; failures after
submission are UNKNOWN rather than assumed rejected; environment mismatch never
reaches a mutating SDK call; invalid/excess orders fail before submission; a
cancel acknowledgement is not labeled a final cancellation or fill; journal
failure before submission means no order is sent.

**Owner-local acceptance:** one bounded paper order with broker-correlatable ID,
observed status and cancel/fill outcome. Simulated fills do not prove real fills.

**Excluded:** REAL, market orders, options/futures, shorting, margin use,
automatic liquidation, unmanaged account-wide cancellation and optimization.

## S3 — restart reconciliation and persistent emergency stop

**Goal:** reconnect without creating duplicate risk; compare known orders/fills,
positions and cash; stop new risk durably, including across process restart.

**Solution:** reconcile S2 intentions against fresh, explicitly SIMULATE broker
queries, with duplicate/partial/out-of-order handling and no resend while status
is unresolved. Preserve broker and local identities in local-only records.
Compare positions from a recorded baseline and unique fills; show cash residual
and unobserved fee/cash-flow limits instead of claiming an unexplained match.
Persist stop before cancellation; cancel only attributable working orders.
Keep stopped state after restart; any local resume is explicit and contingent
on reconciled state, never inferred from a successful connection.

**Dependency/default:** S2 merged/main verified. One writer per runtime journal;
unknown orders, missing history, account drift or unexplained reconciliation
remain blocked. Use existing calendar/observation conventions where applicable,
without changing Raw/Curated data, TEST history, schemas or frozen strategies.

**Engineering acceptance:** restart after unknown submission cannot duplicate it;
partial fill plus cancel preserves the fill; duplicate events do not double
positions/cash; stale/ambiguous status cannot authorize new orders; failed cancel
still leaves emergency stop active; unrelated orders are untouched; missing
fees or non-atomic snapshot timing are visible limitations, not zero cost.

**Owner-local acceptance:** broker-correlatable order/fill/position/cash records,
one reconnect/restart and one stop exercise. A real disconnection is not claimed
from an injected offline failure. Forward strategy qualification remains outside
this engineering result until rules are frozen before genuinely new samples.

**Excluded:** production activation, retroactive strategy tuning, full account
synchronization platform, account resets, forced liquidation or live readiness.

## S1 operator entry

Run from the reviewed source with the existing environment, using the source
path rather than an older installed package. PowerShell example:

```powershell
$previous = $env:PYTHONPATH
try {
  $env:PYTHONPATH = (Resolve-Path .\src).Path
  $out = Join-Path $env:TEMP ("mv-simulation-probe-" + [guid]::NewGuid().ToString("N") + ".json")
  python -m market_vault.moomoo_simulation --output $out
  $code = $LASTEXITCODE
  Write-Host "PROBE_EXIT=$code REPORT=$out"
} finally {
  $env:PYTHONPATH = $previous
}
```

OpenD must already be running and logged in locally. Do not unlock trading.
Exit 0 means ACCOUNT_VERIFIED; 1 is a failed account/environment probe; 2 means
the output could not be created or written. An existing destination is rejected
before connecting. Keep failures.
Upload only this JSON, not OpenD logs, command transcripts, credentials or raw
account tables. If several valid paper accounts exist, provide --account-id
locally to choose one; its value is never written to the report. Account probing
does not enable order submission.

Official interfaces checked 2026-10-17:
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/base.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-acc-list.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-position-list.html

The SDK defaults of trading queries/orders must not be relied on: the documented
place_order and position_list_query defaults are REAL. S1 itself calls only
get_acc_list, which has no trading-environment argument; its returned environment
is checked explicitly before the account is accepted.
