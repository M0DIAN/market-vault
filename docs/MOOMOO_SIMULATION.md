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
one BUY intention total per journal, exactly one whole share, an owner-entered
limit price USD 1.00..1000.00 in cents, NORMAL limit/DAY/RTH, adjust_limit=0.
The same or another ID cannot reset that journal's consumed intention budget,
even after a timeout, rejection, cancellation or restart. No strategy-selected
price, SELL, shorting or automatic run. The broker's max_cash_buy preflight must
cover the share and max_buy_back must be zero; margin buying power is not used.
This is a preflight, not an atomic broker cash-only guarantee: the owner must
exclude concurrent/manual account activity during qualification. Caps are per
journal, not an account-wide capital controller; do not create another journal
to bypass an unknown outcome. DAY expiration does not liquidate a filled
position. No intraday-flat or no-overnight-position guarantee is claimed.

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
Compare positions from a recorded baseline and per-order cumulative executed
quantity/average-price observations; never sum repeated cumulative snapshots.
Official deal_list_query and history_deal_list_query do not support SIMULATE,
so individual executions, their IDs/times and fees must not be fabricated or
queried through a REAL fallback. Show cash residual and unobserved fee/cash-flow
limits instead of claiming an unexplained match.
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


## S2 operator/API boundary

The separate `market_vault.moomoo_simulation_orders` module has `init`, `submit`,
`observe` and `cancel` actions. It is not called by the GUI or research pipeline.
Use the reviewed source path and the existing Python environment as for S1.
`--help` is offline. The following are command shapes, not a preselected trade:

```text
python -m market_vault.moomoo_simulation_orders init --journal NEW_LOCAL.sqlite
python -m market_vault.moomoo_simulation_orders submit --journal EXISTING_LOCAL.sqlite --intent-id UUID_HEX --symbol US.SPY --price OWNER_LIMIT --execute-simulate
python -m market_vault.moomoo_simulation_orders observe --journal EXISTING_LOCAL.sqlite --intent-id SAME_UUID_HEX
python -m market_vault.moomoo_simulation_orders cancel --journal EXISTING_LOCAL.sqlite --intent-id SAME_UUID_HEX --execute-simulate
```

Choose the journal path and a 32-character lowercase UUID once; retain both.
`init` opens no order and pins the verified account locally. Existing journals
are opened read/write without creation; initialization is exclusive and never
resets an existing database. Output includes no account ID. A mutating command
requires `--execute-simulate`; there is no REAL flag. Do not run a broker order
until the S1 local account probe passes and the bounded paper exercise is ready.

The journal commits the intention before place_order; failure after that boundary
retains UNKNOWN or a provable NOT_SENT marker. Neither outcome permits resubmission.
A sparse SDK response retains its broker ID as an UNVERIFIED query hint; a fresh
attribution check must pass before that ID can support cancellation. It does not
permit resubmission or establish a fill. A successful full response is only
SUBMISSION_ACKNOWLEDGED, not a fill. Observation
checks exact code/side/quantity/limit/type/remark/order ID. Cancellation requires
a fresh attributable SUBMITTED/FILLED_PART observation; its response is only
CANCEL_ACKNOWLEDGED. A cancel timeout remains unknown and is not blindly repeated.
S3 supplies recovery/reconciliation; it is not claimed by these S2 commands.

This journal contains local account identity and order evidence. Do not upload
it or ordinary OpenD logs to a public repository. Preserve it after a failure;
never edit metadata, delete it or initialize another journal to retry blindly.
No market database or Raw/Curated artifact is opened. The first qualifier is
single-owner/single-controller; no cross-account scheduler or custody promise.

Additional official interfaces checked 2026-10-17:
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-max-trd-qtys.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-order-list.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/modify-order.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-order-fill-list.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-history-order-fill-list.html

## S3 executable boundary and owner sequence

`market_vault.moomoo_simulation_recovery` adds `baseline`, `recover`, `reconcile`
and `stop`, using the existing journal schema and insertion-only events. No new
journal version, reset, deletion, migration, fee endpoint or execution-ID model.
A missing baseline on an older S2 journal is reported, never reconstructed from
post-trade balances. Baselines must precede any intention and cannot be replaced.

Before the first bounded order, run `baseline --journal PATH` in the recovery
module. It records all returned long-position quantities and basis-labelled USD cash,
with no working/unknown US orders observed before or after the snapshot. Stop on
a baseline failure. Use only the same selected account and single controller;
exclude manual/other-program trades, deposits, conversions and account resets.
Then use S2's explicit single-order command. After closing/reopening the process,
use `recover --journal PATH --intent-id SAME_UUID_HEX`, then `reconcile --journal
PATH`. No recovery action calls place_order, creates another intention, or
restores the one-intention budget.

Recovery queries the fresh current US order list; when the exact remark/known
locator is absent, it queries history for that symbol from the recorded intention
date through now (maximum 31 elapsed days). Unsupported/missing history stays
unknown. Identical duplicates do not add executions; conflicting rows/IDs,
unknown status, missing cumulative data/update time, backwards cumulative fills,
terminal-status regressions and same-quantity average-price revisions block.
Existing S2 observe/cancel also rejects regressing recorded observations.

Account reconciliation uses each order's cumulative executed quantity ONCE,
with fresh order observations bracketing the position/funds calls. Changing
orders, unrelated working/unknown US orders, position residuals and any nonzero
cash residual remain BLOCKED. It does not sum repeated cumulative snapshots.
S8 prefers finite explicit us_cash (USD_CURRENCY_BALANCE), not buying power or a
converted display sum. Missing/unavailable us_cash can use strictly USD-labelled
legacy cash as LEGACY_DISPLAY_USD; invalid explicit USD never falls back. The
selected cash basis must match the baseline, even if both numbers are equal.
Original v1 baselines retain their legacy meaning without rewriting them. See
MOOMOO_FUNDS_REPAIR.md. Fees and external cash flows remain unexplained.
OBSERVATIONS_MATCH is explicitly conditional and non-atomic, never proof of zero
fees, full custody reconciliation, trade profitability or live readiness.
A recorded failed reconciliation blocks new submission even with unused budget;
only an explicit later successful reconciliation removes that particular block.
Neither connection success nor reconciliation clears an emergency stop.

`stop --journal PATH` commits the sticky local stop WITHOUT importing/connecting
to OpenD. It never cancels or liquidates by default. Adding `--cancel-owned
--execute-simulate` commits stop BEFORE connecting, then makes at most S2's one
cancellation attempt for each freshly attributed working owned order. A failed
connection/cancel leaves stop in force. The cancel response is still only an ACK;
query again to establish the final outcome. Unrelated orders are never cancelled.
Already in-flight broker requests cannot be recalled by a local stop. The
supported runtime remains single-writer, not a concurrent execution service.
There is deliberately no resume command in this bounded qualifier. Keep the
stopped journal and inspect outstanding positions manually in the simulator;
do not use an older executable or another journal to bypass it.

Full order/account observations and residuals remain in the local journal.
The recovery CLI prints only an allowlisted summary, not IDs, balances or raw
SDK errors. Do not upload the journal or reset the simulator. First return only
S1's sanitized probe JSON; broker-order qualification is a subsequent owner-run
exercise. All real account/order/restart/stop qualification remains NOT_RUN until
its actual records are supplied, regardless of engineering CI success.

Additional official interfaces checked 2026-10-17:
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-history-order-list.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-funds.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-acc-cash-flow.html
