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
result/action must match its final recorded operation. Non-failed finishes also
need their supporting reconciliation, preparation baseline, submission receipt/ACK
or persisted stop events; duplicated declarations alone do not establish success.
It retains incomplete
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

## S15 saved/history test ownership balance

After S14 exact-main validation, three existing test files move by explicit
ownership from `strategy` to the existing `intraday_saved` partition:
`test_strategy_intraday_history.py`,
`test_strategy_intraday_forward_reconciliation.py`, and
`test_strategy_intraday_saved_test_forward.py`. Their saved-history, saved-account
and saved-TEST forward semantics match that partition. Test contents, fixtures,
assertions and imports do not change; every job retains the full checkout.
The broad strategy prefix stays unchanged, with existing exact-file precedence.

The preceding successful FULL runs were rechecked. S13 PR run 39274472793,
attempt 1, took 686 seconds for strategy and 157 seconds for intraday_saved
end-to-end. S14 final PR run 39291119877, attempt 1, took 585 and 215 seconds
respectively (partition test steps 556 and 182 seconds). S13's per-test duration
log identifies the selected files among the expensive saved/history operations;
these durations are not treated as complete per-file totals. Moving them can
repeat some imported fixture setup in a different process, so measured job
results, not subtraction of selected slow-test entries, decide the outcome.

The partition validator, runner, workflow, eleven job names, concurrency,
timeouts, required checks and Python 3.14 scope are unchanged. The ownership
regression still proves the complete discovered-file union with one owner each
and now requires all four saved-partition files. Compare actual affected PR/main
job durations after this change; target each below 600 seconds, not a permanent
runner-speed guarantee. Reuse must not be asserted as a fresh timing measurement.
No business test is removed, filtered, skipped or weakened by this change.

## S16-S18: replay the original stopped journal, not another trade

The 2026-10-20 JST package was fixed before implementation in PR #376. S16
independently replays recorded cash arithmetic; S17 connects that replay to the
existing exporter and saved-report analyzer; S18 applies those entries to the
owner's original stopped journal. Each dependent implementation follows the
previous item's independent review, required PR CI, squash and exact-main CI.
S16 and S17 source deliveries are #376 and #377. No existing trading, stop,
reconciliation tolerance, journal schema or CI policy changes in this package.

| Item | Goal / technical path | Defaults / dependency | Acceptance and exclusions |
| --- | --- | --- | --- |
| S16 | Derive recorded cash change plus one cumulative owned BUY debit, then compare with the original expected cash/residual. | Same recognized USD basis; existing v1 records; missing or contradictory supporting observations remain unavailable. | Known arithmetic, once-only cumulative quantities and contradictory-record tests. Pure computation, not fee attribution or account readiness. |
| S17 | Add replay terms to the existing read-only export; independently check the public gross debit/equation in the existing JSON analyzer. | After S16 verified main; additive fields, old reports NOT_RECORDED; original result/stop/runtime preserved. | Actual exporter-to-analyzer entry tests and altered-term rejection. No new database, broker request, strategy, UI or trading authority. |
| S18 | Export the already-existing stopped original journal once, analyze its actual terms and narrow the remaining discrepancy. | After S17 verified main; owner-local original journal, no new preparation/order/account query. | Actual original-record comparison with source bytes/stop preserved. A guide or synthetic test does not satisfy this observed acceptance. No guessed fees, tolerance waiver, reset/resume, REAL, deployment, calibration or forward acceptance. |

**S18 observed qualification remains NOT_RUN until that original-record export
is supplied and inspected.** The earlier sanitized report omitted baseline and
current private cash, so its residual cannot be backsolved and called an
independent replay. The original private journal is not available to this chat.
Instruction delivery is separate from observed qualification; do not close the
whole package merely because this guide merges.

### Reading the two different results

The export's `cash_arithmetic.status=RECOMPUTED_MATCH` means the recorded private
cash change and owned gross debit reproduce the original expected cash/residual.
`RECOMPUTED_MISMATCH` identifies inconsistent recorded arithmetic; `UNAVAILABLE`
means supporting records do not suffice. Only cash differences, not account
balances or raw IDs, are exported. Prefix sequence references retain historical
scope; later events do not rewrite earlier comparisons.

The analysis's `PUBLIC_EQUATION_VERIFIED` checks the public cumulative debit and
cash-change-plus-debit equation. Its cash delta and private expected-cash-match
flag remain exporter declarations, not independently authenticated balances or
broker evidence. It can coexist with exporter RECOMPUTED_MISMATCH. Old reports
without terms remain NOT_RECORDED. Missing basis/comparison support remains
UNAVAILABLE; altered supported terms are rejected. Original BLOCKED, unattributed
cash and sticky stop remain unchanged even when both arithmetic checks agree.

### Owner-local one-time export (PowerShell)

Close journal writers first. Select the SAME stopped journal that produced the
first-order report, not its earlier failed preparation journal. Keep all original
files. No new market session, quote, order, cancellation, reset or OpenD connection
is needed. The code fetch below needs GitHub access; the two Python actions are
then offline. Use an existing trusted Git checkout and working Python 3.11+.

This creates a unique detached source worktree at S17's verified main commit,
without switching/resetting the existing checkout or installing a package. Git
objects/worktree metadata and new temporary source/report files are written;
existing account data is not deliberately modified. Do not edit the new source
or run another writer concurrently. The checks are local correspondence checks,
not independent process attestation. The journal-shape guard cannot prove that
the owner selected the intended file; compare its exported prefix with the old
report before accepting observations.

Paste the complete block into PowerShell. Inputs are requested at runtime, not
placeholder paths. Any error stops this operation; retain files for diagnosis.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $pin = '5bff326145a1a1672987bcfb0677baac8dfe292c'
    $repo = (Resolve-Path -LiteralPath (Read-Host 'Existing market-vault Git checkout path').Trim('"')).Path
    $python = (Resolve-Path -LiteralPath (Read-Host 'Working python.exe full path').Trim('"')).Path
    $journal = (Resolve-Path -LiteralPath (Read-Host 'SAME stopped first-order SQLite journal path').Trim('"')).Path
    if (!(Test-Path -LiteralPath $repo -PathType Container) -or
        !(Test-Path -LiteralPath $python -PathType Leaf) -or
        !(Test-Path -LiteralPath $journal -PathType Leaf)) { throw 'INVALID_INPUT_PATH' }
    $null = Get-Command git -ErrorAction Stop
    $origin = git -C $repo remote get-url origin
    if ($LASTEXITCODE -ne 0 -or $origin -notmatch '^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)M0DIAN/market-vault(?:\.git)?/?$') {
        throw 'EXPECTED_MARKET_VAULT_ORIGIN'
    }
    $codeRoot = Join-Path $env:TEMP ('mv-s18-' + [guid]::NewGuid().ToString('N'))
    git -C $repo fetch --no-tags --no-recurse-submodules origin $pin
    if ($LASTEXITCODE -ne 0) { throw 'SOURCE_FETCH_FAILED' }
    git -C $repo worktree add --detach $codeRoot $pin
    if ($LASTEXITCODE -ne 0) { throw 'SOURCE_WORKTREE_FAILED' }
    $head = git -C $codeRoot rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -ne $pin) { throw 'SOURCE_PIN_MISMATCH' }
    git -C $codeRoot diff --quiet HEAD -- src
    if ($LASTEXITCODE -ne 0) { throw 'SOURCE_CHANGED' }
    $src = Join-Path $codeRoot 'src'
    $token = [guid]::NewGuid().ToString('N')
    $export = Join-Path (Split-Path -Parent $journal) ('cash-export-' + $token + '.json')
    $analysis = Join-Path (Split-Path -Parent $journal) ('cash-analysis-' + $token + '.json')
    $before = (Get-FileHash -LiteralPath $journal -Algorithm SHA256).Hash
    $runner = @'
from pathlib import Path
import sys
try:
    if len(sys.argv) != 5:
        raise ValueError('INVALID_ARGUMENTS')
    src, mode, source, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    if not src.is_dir() or not source.is_file() or output.exists():
        raise ValueError('INVALID_PATHS')
    sys.path.insert(0, str(src.resolve()))
    if mode == 'export':
        from market_vault import moomoo_simulation_evidence as entry
        _, intentions, events = entry.read_journal(source)
        if len(intentions) != 1 or not any(e['kind'] == 'EMERGENCY_STOP' for e in events):
            raise ValueError('EXPECTED_STOPPED_ORDER_JOURNAL')
        flag = '--journal'
    elif mode == 'analyze':
        from market_vault import moomoo_simulation_report as entry
        flag = '--input'
    else:
        raise ValueError('INVALID_ACTION')
    result = entry.main([flag, str(source), '--output', str(output)])
except (Exception, KeyboardInterrupt):
    print('S18_OFFLINE_ACTION_FAILED: preserve all files', file=sys.stderr)
    raise SystemExit(1)
raise SystemExit(result)
'@
    & $python -I -S -c $runner $src export $journal $export
    $exportExit = $LASTEXITCODE
    if ((Get-FileHash -LiteralPath $journal -Algorithm SHA256).Hash -ne $before) {
        throw 'JOURNAL_CHANGED_PRESERVE_ALL_FILES'
    }
    if ($exportExit -ne 0) { throw 'OFFLINE_EXPORT_FAILED_PRESERVE_FILES' }
    & $python -I -S -c $runner $src analyze $export $analysis
    if ($LASTEXITCODE -ne 0) { throw 'OFFLINE_ANALYSIS_FAILED_PRESERVE_FILES' }
    if ((Get-FileHash -LiteralPath $journal -Algorithm SHA256).Hash -ne $before) {
        throw 'JOURNAL_CHANGED_PRESERVE_ALL_FILES'
    }
    Write-Host 'OFFLINE_FILES_CREATED; S18_OBSERVED_ACCEPTANCE=PENDING; NEW_ORDERS_AUTHORIZED=false'
    Write-Host "Review and return only the sanitized export: $export"
    Write-Host "Keep the analysis and source locally: $analysis ; $codeRoot"
}
```

No output is overwritten. A missing journal or an active/corrupt unsupported
journal must be diagnosed without deleting, renaming, migrating or recreating it.
If fetching or source validation fails, stop rather than run an older installed
copy. Do not change the pin or install/upgrade the SDK to make this exercise run.
The two inline invocations reuse existing entry functions; they are not a new
permanent wrapper, nor a claim that this complete PowerShell block ran on the
owner's Windows machine during engineering delivery.

Review and return only the new `cash-export-*.json` in the private development
conversation. Keep the analysis, SQLite, original reports and raw-ID mapping
local; do not upload full OpenD logs, account balances or the database. The export
includes own-order terms and cash differences already needed for diagnosis.
Actual acceptance compares its original event prefix/result/stop with the earlier
report, separates private-replay and public-equation conclusions, and records any
remaining unavailable or contradictory observations. Producer source identity
remains distinct from the runtime that originally submitted the order.

If actual arithmetic agrees but a nonzero residual remains, its cause is still
unattributed. Transaction-specific fee/cash-flow evidence would be needed to
explain it; do not substitute a fee schedule or another trade. Missing external
evidence is a real stop point, not a reason to build another diagnostic system
or silently relax reconciliation. No result here permits resuming the account.
