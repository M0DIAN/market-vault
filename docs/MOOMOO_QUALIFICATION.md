# S4-S6: bounded owner-local simulator qualification

Authorized development package, 2026-10-17. Engineering delivery uses final-HEAD
independent review, required PR CI, squash, and exact-main natural push CI for
each item before the next. No deployment, REAL trade, account reset, paid data,
learner/search/UI expansion, or new runtime database schema is authorized.

The uploaded S1 probe reports ACCOUNT_VERIFIED, SIMULATE, US, same account after
reconnect, and no orders/funds/positions read. Its source hash matches the S1
source at dccb866e8d16210288bb1dceeb02d18da00f735d with Windows CRLF line endings.
This owner-supplied report supports account selection/reconnect only; it is not
independent process attestation or order qualification. Do not repeat this probe
without a relevant environment or account change.

## Package and acceptance fixed before implementation

| Task | Goal / solution | Defaults, dependency and engineering acceptance | Excluded |
| --- | --- | --- | --- |
| S4 evidence export | Read the existing private journal in SQLite read-only snapshot mode; allowlist the upload projection and replace identities with package-local aliases. | Reuse S2/S3 schema. Preserve every event's place in the sequence, including unknown/failure events. No balances, account IDs, raw order IDs, unrelated position details or arbitrary error strings. Source and existing reports unchanged. | Broker calls, database copies/migration, new evidence platform. |
| S5 qualification entry | Reuse S1-S3 to prepare a baseline, explicitly submit the owner's bounded intent, reopen/check, and stop; use S4 for upload output. | After S4 main verification. Exactly one BUY intention / one share / SPY or QQQ / owner limit / SIMULATE. Preparation failures cannot send orders; unknown submission cannot resend. | Strategy-generated orders, automatic price selection, REAL, resets, liquidation. |
| S6 observed differences | Derive full intention-denominator counts and measurable timing/limit-versus-fill differences from recorded events, retaining S3 reconciliation. | After S5 main verification. Missing observations stay missing; duplicate cumulative observations are not summed. Local elapsed time is not broker latency; limit difference is not market slippage. | Cost fitting, profit claims, manual qualifier relabelled frozen strategy TEST or new forward sample. |

Actual owner-local order, fill/cancel, funds/positions, reconnect and stop results
remain unqualified until their records arrive. A conditional snapshot comparison
is not a complete account audit. No independent market data is available; its
gate remains NOT_SUPPLIED. Unverified turnover/volume is not execution evidence.

## S4 offline export

After closing the writer, use the same reviewed source and working Python:

```text
python -m market_vault.moomoo_simulation_evidence --journal PRIVATE.sqlite --output NEW_UPLOAD.json
```

These are argument shapes; choose existing journal and new output paths locally.
The module reads `mode=ro`, with one explicit read transaction, and never opens
OpenD. It does not overwrite an output or create a missing database. Exit 0 means
projection exported, NOT broker qualification or permission for a new order.
Malformed/incompatible journals fail with a static diagnostic; keep the input.

Only the new JSON is intended for this private development conversation. It
contains own-order symbols, limits, quantities, cumulative observed prices and
times, plus cash/position residuals needed to diagnose reconciliation. Review it
before sharing. Account identifiers/balances, raw broker IDs, unrelated position
names and quantities, raw errors, remarks, local paths and full database contents
are excluded. The original journal stays local for mapping intent-1/order-1 back
to the broker's displayed IDs. Aliases are local to this report, not global IDs.
The exporter hash identifies the exporter, NOT the source that originally traded.
Unknown event kinds retain their sequence/time as UNRECOGNIZED_EVENT; their
payload is not copied or interpreted as success. This export is a projection of
owner-local records, not signed broker evidence or an automatic acceptance gate.


## S5 owner-run entry

The separate module `market_vault.moomoo_simulation_qualifier` has four actions.
Each action writes a NEW sanitized JSON and retains the same private journal:

```text
python -m market_vault.moomoo_simulation_qualifier prepare --journal NEW_PRIVATE.sqlite --output NEW_PREPARE.json
python -m market_vault.moomoo_simulation_qualifier submit --journal SAME_PRIVATE.sqlite --output NEW_SUBMIT.json --symbol US.SPY --price OWNER_LIMIT --execute-simulate
python -m market_vault.moomoo_simulation_qualifier check --journal SAME_PRIVATE.sqlite --output NEW_CHECK.json
python -m market_vault.moomoo_simulation_qualifier stop --journal SAME_PRIVATE.sqlite --output NEW_STOP.json
```

`prepare` reads current simulator orders, long positions and USD cash using S3,
records the pre-order baseline and checks it; it NEVER calls place_order or
modify_order. Return its JSON first. Account balances/IDs stay in the local
journal and are not included in the upload. A prepare failure never overwrites
an old journal or permits submission; preserve both the journal and failure.
No funds/account reset or deposit is part of preparation.

`submit` requires this journal's successful preparation, an explicit symbol and
owner-chosen cent limit USD1..1000, and --execute-simulate. It performs fresh S3
reconciliation before calling S2 once. Its UUID is recorded automatically, so
reopening needs no copied order ID. Limits remain ONE total BUY intention and
ONE whole share, SPY/QQQ, NORMAL/DAY/RTH, cash-capacity preflight; no margin/SELL,
automatic price/strategy, retry or liquidation. Do not run it outside the actual
US regular session. Cash checks are not atomic against other account actors;
exclude manual trades, another controller, deposits, conversions and resets.
DAY expiry does not remove a filled position or guarantee an intraday-flat book.

After a submission failure with a recorded intention, stop is sticky and the
budget remains consumed. Use check, not submit, even when the response or output
is lost. Pre-admission input failures do not manufacture an order; a recorded
failed reconciliation must be resolved via explicit check before another attempt.
A failure before the journal exists yields a minimal failure report without
pretending it contains broker evidence. A hard process/machine crash may leave
an empty output and an unmatched start; keep the private journal for recovery.

`check` reopens the journal and uses S3 recovery/reconciliation without placing
orders. Re-run as a separate process to exercise reopening. A working order,
missing baseline/history, timing race or residual is BLOCKED, not success.
Do not loop rapidly: allow at least 30 seconds between manual checks; this is an
operator pacing rule, not a claim of a provider quota or automatic rate limiter.

`stop` persists the existing sticky stop BEFORE opening the report or connecting
OpenD; offline stop is the default. Optional --cancel-owned --execute-simulate
uses S3's attributable, one-attempt cancellation only. Failed connection/report/
cancellation cannot remove that stop. Cancellation ACK is not final; check again.
No resume or new journal may bypass an unknown result; no positions are liquidated.

The action record includes start/finish, actual monotonic elapsed milliseconds,
and a fixed set of execution-source SHA256 values normalized to LF plus reported
Python/SDK versions. This is bounded runtime provenance, NOT an independent
execution attestation or a hash of the complete installation. Existing S2/S3
modules and their journals are unchanged. Exporter additions only allowlist
these new fixed action fields; arbitrary runtime fields are never copied.
Exit 0 indicates the requested action completed at its named boundary, NOT that
the broker lifecycle, strategy or independent-data gate has passed. Only upload
the new JSON privately; do not upload the SQLite journal or full OpenD logs.


## S6 observed differences in the existing upload

S4 exports and S5 action reports now include the additive `observation_summary`
object (`market_vault_paper_observations_v1`). It is descriptive, requires no new
command and makes no broker call or journal change. The denominator is every
recorded intention in THIS journal, not every market signal or attempted CLI
invocation. Empty denominators produce null fractions, not 100% or zero evidence.
Each intention is classified as observed working, observed terminal, explicitly
not sent, or unresolved as of recorded evidence. ACKs alone never establish a
fresh fill/cancellation; failed queries, pending cancellations, ambiguous order
aliases or incomplete actions keep the uncertainty visible. Accepted history is
retained, not corrected. S3 progression checks are reused rather than duplicated.

The last valid cumulative quantity is used ONCE, not summed over queries. The
price difference is BUY average-fill minus the owner's limit; this is NOT market
slippage and there is no quote, signal-price or validated turnover VWAP baseline.
Missing/conflicting cumulative evidence does not produce a numeric fill result.
Local wall-clock call-to-receipt/query intervals may include account validation,
manual waiting, reconnection and clock error. Missing/negative/naive timing is
null with a reason. S5 monotonic durations belong only to matched action start/
finish pairs; an interrupted action remains incomplete with no invented duration.
Neither measurement is broker/network latency or a timestamp for an individual
execution. The local submission-boundary marker does not prove broker receipt.

The last recorded S3 reconciliation is preserved as a historical NON-ATOMIC
comparison, with subsequent activity indicated; it is never silently promoted
to current account readiness. Every summary continues to deny new-order authority
and leaves broker qualification unassessed, market slippage/latency unmeasured,
cost calibration and strategy-forward validation not performed. No strategy TEST
artifact is created from this manual one-order qualifier. Real observation values
can only be accepted after the owner's actual run/report, not from CI fixtures.

The summary projection also reports LF-normalized on-disk source hashes for the
summary module and its direct order/progression helper modules. These supplement
the exporter hash; they do not attest loaded bytecode or an entire installation.
The reconciliation's subsequent-activity marker includes successful local stop
and later action starts. Finishing the same successful check is not itself a
new account observation, whereas starting another action or stopping is recorded.


## S10-S12: first observed paper-order cycle, not another adapter

Owner-authorized next package, 2026-10-17, after S9 at
`e24f9396ef319c6aecd9351f75386bce15bc5522`. The newly supplied linked prepare report
records PREPARED, explicit USD_CURRENCY_BALANCE on baseline and comparison,
OBSERVATIONS_MATCH, no intentions, and an unstopped successor. Its funds metadata
classifies display currency as N/A and explicit USD cash as FINITE. This supports
the corrected preparation path on that run; the original failed report did not
capture those fields, so it does not establish the original response verbatim.
The old failed journal remains stopped. No owner files, account details or
runtime database belong in Git. A supplied journal projection is not independent
broker attestation. Preparation success does not qualify an order.

The existing S1-S9 Python entry points already implement this bounded exercise.
This increment fixes the task/measurement scope and operator instructions; it
adds no trading engine, collector, report schema or permanent wrapper. A merged
instruction PR is NOT completion of S10, S11 or S12. Their external acceptance
requires the observations below. In-scope defects revealed by those observations
may be repaired under the current authorization through exact-candidate review,
required CI, squash and exact-main verification; no speculative refactor.

| Task | Goal / technical path | Dependency / defaults | Required observed result | Excluded |
| --- | --- | --- | --- | --- |
| S10 first paper order | Use existing qualifier submit once on the successful S9 successor; fresh account/reconciliation/cash checks precede S2's durable intention and explicit SIMULATE SDK call. | Prepared successor, actual supported RTH, one controller; ONE BUY intention / ONE whole SPY or QQQ share / owner-selected USD1..1000 cent limit / NORMAL / DAY / adjust_limit=0. No new preparation. | Retained intent and broker-correlatable receipt plus a fresh attributable order observation. A returned ID or ACK alone is insufficient; refusal/unknown remains the actual result, not a passed order test. | REAL, auto strategy/price, margin/SELL, additional journals to retry, guaranteed fill or expiry liquidation. |
| S11 reopen, reconcile and stop | Start a separate check process against that SAME journal, then existing offline stop or explicit stop-with-owned-cancel, and a later check after reopening. | After the S10 attempt; unknown outcomes go here, never to submit. Keep original and successor. At least 30 seconds between manual checks; at most three checks in this first exercise, then preserve unresolved evidence for diagnosis. | One broker order identity, stable cumulative quantity counted once, same cash basis and zero unexplained residuals, sticky stop visible after reopening, no second submission. Working orders/unknown cancellation remain BLOCKED. Mark only the terminal branch actually seen; FILLED and CANCELLED are not both inferred from one order. | Automatic retry/resume, forced liquidation, unowned cancellation, fee imputation, claiming a live network outage from an ordinary new connection. |
| S12 first observation analysis | Read the existing S4/S6 projection and compare the owner's broker-client order record with its local mapping; compute only already defined counts, local durations, buy-average-minus-limit and reconciliation residuals. | After S10/S11 data; denominator is all recorded intentions, including failures. A missing fill gives no price statistic. Return a final sanitized check JSON; keep intermediate JSONs for a failed/incomplete path. | An actual, bounded report separates accepted observations, discrepancies and NOT_OBSERVED items. Symbol/quantity/status/price/time checked against the simulator's order view; raw ID mapping stays local. No automatic changes to execution assumptions. | Market slippage/latency inferred from limit/wall time, one-order profitability/general reliability claims, fitting costs, rewriting TEST or counting this manual exercise as frozen-strategy forward data. |

Independent market data, contemporaneous signal/market-quote observations,
individual executions/fees and post-freeze strategy samples are still missing.
This exercise cannot calibrate unobserved market slippage or prove a strategy.
Freeze a separate strategy/selection/cost/benchmark procedure before its genuinely
new forward samples; do not backdate that freeze to this manual qualifier.

### Owner execution and stopping points

Do not repeat S1, prepare, funds-repair preparation, historical recapture or SDK
installation. Reuse the pinned S9 source worktree and working interpreter.
Close other writers/controllers, leave OpenD logged in, and exclude manual
trades, cash transfers/conversions or simulator reset during the exercise.
The source pin below deliberately stays at e24f9396: this documentation increment
does not change its executable files or the successful preparation's semantics.

Run menu 1 exactly once during supported RTH. Its local confirmation concerns
SIMULATE only. Select your own symbol and limit; no price is suggested or fetched.
A limit order may remain unfilled. Both success and failure end the command;
there is no automatic next action or blind resend. If an intention was recorded,
reopening cannot restore its consumed budget. Missing output is not proof that
no order reached the broker. Outside-RTH or other pre-submit refusal sends no
order; report that refusal instead of changing a clock or relaxing the guard.

After at least 30 seconds, run menu 2 in a new process. A working order can make
check BLOCKED without proving a bug. For a verified terminal order, use menu 3
(offline stop). For an attributable working order, menu 4 explicitly requests
stop plus the existing ONE owned cancellation attempt. It also tolerates a race
to terminal by observing rather than cancelling a completed order. For an
unresolved/error state, menu 3 stops new risk; retain the report and inspect the
simulator, rather than forcing a cancel through missing attribution. If a prior
submission failure already stopped the run, check is still allowed and menu 4
may attempt attributable cancellation; neither clears stop.

Finally reopen with menu 2 (respect the 30-second pacing and three-check budget).
The desired recorded end is one attributable terminal order, explained position/
cash comparison and stopped=true. Stop alone never proves no outstanding order
or no position. If cancellation is not confirmed, do not retry it or leave the
order unattended: inspect/manage that order in the simulator client and report
any manual intervention as external activity, not program success. Filled stock
is NOT sold by any of these commands; manage that simulated residual explicitly
after preserving the final comparison. Never touch a real account for this test.

The self-contained block runs ONE chosen existing action per invocation. It
prompts for paths rather than inventing them and does not install, fetch, reset,
copy databases or rewrite source. Menu 1 additionally verifies that the selected
journal retains the supplied successful prepare-event prefix; this is local
correspondence, not account authorization. Stop does not depend on that old JSON
being available. Review the report before sharing it privately. Only the new
sanitized JSON is for upload; keep databases and raw logs local. A cropped broker
order screenshot can corroborate symbol/quantity/status/price/time; conceal
account/name/balance/unrelated rows, and keep full identity mapping local.
Screenshot agreement is not signed broker evidence or an independent quote feed.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Pin = 'e24f9396ef319c6aecd9351f75386bce15bc5522'
    $Port = 11111
    $Firm = 'NONE'
    $Source = Join-Path $env:USERPROFILE 'MarketVaultEvidence\funds-repair-source-e24f9396ef31'
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        $Source = (Read-Host 'Existing e24f9396 source worktree path').Trim().Trim('"')
    }
    $Source = (Resolve-Path -LiteralPath $Source).Path
    $Head = & git -C $Source rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or ([string]$Head).Trim() -ne $Pin) { throw 'Wrong source revision; do not substitute another version.' }
    $Dirty = & git -C $Source status --porcelain -- src/market_vault
    if ($LASTEXITCODE -ne 0 -or $Dirty) { throw 'Source changed; preserve it and stop.' }

    $Py = @('D:\GitHub\market-vault\.venv\Scripts\python.exe', 'D:\market-vault\repo\.venv\Scripts\python.exe') |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $Py) { $Py = (Read-Host 'Existing working python.exe full path').Trim().Trim('"') }
    $Py = (Resolve-Path -LiteralPath $Py).Path
    $Journal = (Read-Host 'Successful private.sqlite.funds-repair.sqlite full path (KEEP LOCAL)').Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $Journal -PathType Leaf)) { throw 'Journal missing; do not create or replace it.' }
    $Journal = (Resolve-Path -LiteralPath $Journal).Path
    $Choice = Read-Host '1=SUBMIT ONCE, 2=CHECK, 3=OFFLINE STOP, 4=STOP AND CANCEL OWNED'
    if ($Choice -notin @('1', '2', '3', '4')) { throw 'No action selected.' }
    $Action = if ($Choice -eq '1') { 'submit' } elseif ($Choice -eq '2') { 'check' } else { 'stop' }
    $Out = Join-Path (Split-Path -Parent $Journal) ('pilot-' + $Action + '-' + [guid]::NewGuid().ToString('N') + '.json')
    $Extra = @()
    if ($Choice -eq '1') {
        $Prepared = Join-Path (Split-Path -Parent $Journal) 'prepare-repair-upload.json'
        if (-not (Test-Path -LiteralPath $Prepared -PathType Leaf)) {
            $Prepared = (Read-Host 'Successful prepare-repair-upload.json full path').Trim().Trim('"')
        }
        $Prepared = (Resolve-Path -LiteralPath $Prepared).Path
        $Symbol = (Read-Host 'Choose US.SPY or US.QQQ for the simulator test').Trim().ToUpperInvariant()
        if ($Symbol -notin @('US.SPY', 'US.QQQ')) { throw 'Unsupported symbol.' }
        $Price = (Read-Host 'Your one-share USD limit, 1.00 to 1000.00 (not an automatic price)').Trim()
        Write-Host "SIMULATE ONLY: BUY 1 $Symbol, LIMIT=$Price, DAY/RTH. A filled position is NOT liquidated automatically."
        if ((Read-Host 'Type SIMULATE to submit this single intent') -cne 'SIMULATE') { throw 'No order authorized.' }
        $Extra = @('--symbol', $Symbol, '--price', $Price, '--execute-simulate')
    } elseif ($Choice -eq '4') {
        Write-Host 'Stop remains active even if cancellation fails. Only this journal-owned order may be cancelled; positions are not sold.'
        if ((Read-Host 'Type SIMULATE to allow the one owned cancellation attempt') -cne 'SIMULATE') { throw 'No cancellation authorized.' }
        $Extra = @('--cancel-owned', '--execute-simulate')
    }

    $OldPath = $env:PYTHONPATH
    Push-Location -LiteralPath $Source
    try {
        $env:PYTHONPATH = Join-Path $Source 'src'
        $Bind = @'
from pathlib import Path
import market_vault.moomoo_simulation_qualifier as q
if Path(q.__file__).resolve() != Path('src/market_vault/moomoo_simulation_qualifier.py').resolve():
    raise RuntimeError('Wrong imported source')
'@
        & $Py -c $Bind
        if ($LASTEXITCODE -ne 0) { throw 'Source binding failed; do not reinstall or fall back.' }
        if ($Choice -eq '1') {
            # Read-only correspondence check; actual account/risk guards still run in submit.
            $Verify = @'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
from market_vault.moomoo_simulation_evidence import build_evidence
from market_vault.moomoo_simulation_orders import require_rth
def require(condition, message):
    if not condition:
        raise RuntimeError(message)
prior = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig'))
require(prior['action'] == 'prepare' and prior['result'] == 'PREPARED', 'Preparation not successful')
old = prior['evidence']
now = build_evidence(Path(sys.argv[1]))
require(now['environment'] == old['environment'] == 'SIMULATE', 'Wrong environment')
require(now['journal_created_at_utc'] == old['journal_created_at_utc'], 'Wrong journal')
require(now['events'][:len(old['events'])] == old['events'], 'Preparation history mismatch')
require(not now['stopped'] and not now['intentions'], 'Stopped or already consumed: use check/stop, never submit')
require_rth(datetime.now(timezone.utc))
print('Prepared journal matched; local RTH check passed. Broker preflight still required.')
'@
            & $Py -c $Verify $Journal $Prepared
            if ($LASTEXITCODE -ne 0) { throw 'Pre-submit check failed. No submit command was invoked. Preserve files.' }
        }
        Write-Host "SOURCE_COMMIT=$Pin"
        $ArgsForModule = @('-m', 'market_vault.moomoo_simulation_qualifier', $Action,
            '--journal', $Journal, '--output', $Out, '--port', "$Port", '--security-firm', $Firm) + $Extra
        & $Py @ArgsForModule
        $Code = $LASTEXITCODE
        Write-Host "ACTION=$Action EXIT_CODE=$Code"
        if (Test-Path -LiteralPath $Out -PathType Leaf) {
            try {
                $Report = Get-Content -LiteralPath $Out -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($Report.schema -ne 'market_vault_paper_qualification_v1') { throw 'Unexpected schema' }
                Write-Host "UPLOAD_FILE=$Out"
                Write-Host ('RESULT=' + $Report.result + '; BROKER_QUALIFICATION=NOT_ASSESSED')
            } catch { Write-Host 'REPORT_EMPTY_OR_INVALID: keep journal; use check, never repeat submit.' }
        } else { Write-Host 'REPORT_MISSING: keep journal; use check, never repeat submit.' }
        Write-Host 'No automatic next action. Preserve all reports and the SAME journal. Upload only sanitized JSON.'
    } finally {
        $env:PYTHONPATH = $OldPath
        Pop-Location
    }
}
```

A missing/invalid report, unknown order, schema/account error, unexplained cash
residual or exhausted check/cancel budget ends the affected exercise. Keep the
same journal; return available JSON and the static failure, not its database.
No subsequent mainline implementation is justified merely by a missing optional
metric. Code review/CI for these instructions establishes no actual owner order.

Official order and cash-preflight interfaces checked for this package:
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/get-max-trd-qtys.html
