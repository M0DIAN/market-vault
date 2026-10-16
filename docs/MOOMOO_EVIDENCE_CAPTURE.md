# moomoo evidence-first development and local capture

## Scope and acceptance

The owner's 2026-10-16 direction is to progress by observed evidence, not feature
count: bounded primary/independent data validation; frozen selection procedures
on subsequent new samples; a separate SIMULATE execution adapter; then execution
observation/calibration. The eventual product may support owner-controlled live
capital, but this task does not authorize live orders or switching to REAL.
No additional learner, parameter search or UI is needed to close these gaps.

This first delivery only supplies a missing input path. It does **not** complete
any of those external evidence gates. `capture_moomoo_evidence.py` reuses the
existing history and trading-calendar collectors. It only opens quote contexts,
never trade contexts, and does not open the catalog, curate data, train, select
strategies or place orders. No new SDK or data dependency is added.

Capture is bounded to at most three unique US symbols and 31 calendar days,
strictly before the current New York date. History requests explicitly use
`1m`, `RTH`, `NONE`. A provider calendar is preserved before choosing requested
dates; its completeness is **not** independently established. The total date
range remains recorded even when the provider omits dates. No constant 390-bar
or intersection-only denominator is presented as verified coverage.

## First actual input request

Use `US.SPY` and `US.QQQ`, inclusive **2026-09-17 through 2026-10-14**, 1-minute
RTH, unadjusted. This is a bounded engineering data sample, not a profitability
or forward-validation sample. Keep the returned trading calendar including any
half-day labels; do not manually pad rows or drop anomalies.

Start your existing OpenD locally and log in there. Keep its listener on
`127.0.0.1`; the script defaults to port `11111` (`--port` can change the local
port). Do not unlock trading or send any passwords, tokens or OpenD config.
The existing environment must already be able to import the SDK and pandas;
this command does not upgrade packages or modify your installation.

From a checkout containing the reviewed candidate, using its existing Python:

```powershell
python scripts/capture_moomoo_evidence.py --symbols US.SPY US.QQQ `
  --start 2026-09-17 --end 2026-10-14 `
  --output (Join-Path $env:USERPROFILE ("MarketVaultEvidence\" + [guid]::NewGuid().ToString("N")))
```

For an existing development checkout, prefer a separate detached Git worktree
at the exact candidate commit, using the original checkout's already-working
Python interpreter. Do not reset/switch a dirty checkout or install over a
stable application. Output must be outside the source checkout and must not
already exist. The command prints `UPLOAD_FILE=...\upload.zip`.

Upload only that ZIP, including when its exit code is nonzero. It contains
request metadata, source file hashes and available Git identity, SDK version
metadata, raw SDK-returned CSV tables, per-request UTC capture times and hashes,
a provider schedule, and the final capture summary. It excludes databases,
account/config files and OpenD logs; inspect filenames before sharing.

Exit 0 means every scheduled history request returned nonempty data; **it does
not mean data quality passed**. Exit 2 reports empty history responses; exit 1
reports a failed capture; exit 130 reports an interruption. If the process or
machine is terminated before finalization, there may be no ZIP/manifest; keep
the folder and share only `request.json`, `events.jsonl`, `provider_schedule.json`
when present, and the CSVs created in that folder. Do not upload unrelated logs.

Each attempt creates a new folder. Earlier snapshots are retained for later
revision comparison. The script never resumes or overwrites them. Requests are
journaled before execution. Completed requests survive later failures. Partial
pages inside a failed history request are not returned by the existing
collector and are explicitly **not preserved** by this helper. CSV is a raw
SDK-table serialization, not original network/protobuf bytes. No sorting,
deduplication, imputation or OHLCV normalization is performed on captured tables.

## Independent reference still required

Provide an original export from a genuinely independent provider for the same
symbols, dates, interval/session and adjustment, with provider name, export time,
timestamp timezone, price adjustment and volume units. Preserve the native
columns and unmodified file; mapping can happen after upload. At minimum the
reference needs symbol, timestamp, open, high, low, close and volume. State any
access or coverage limitation instead of inventing missing observations.

Another moomoo/futu download is a revision snapshot, **not** an independent
reference. Do not buy a subscription just to satisfy this request without a
separate decision. Without a reference, comparison and actual coverage remain
`NOT_EVALUATED` / `NOT_SUPPLIED`; the capture helper is not a replacement for the
existing Q5/data comparison path.

Freeze the comparison tolerances and rules before inspecting differences.
Freeze strategy/selection rules, costs and benchmarks separately before any
forward sample. These historical captures must not be relabeled as post-freeze
new observations. Keep engineering, real integration and research acceptance
as separate states.

## Later simulation boundary

A future simulation adapter must force `TrdEnv.SIMULATE` at every applicable
SDK call and verify the pinned account's environment and market at startup and
reconnect. `place_order` defaults to `TrdEnv.REAL`, so a config default alone is
not sufficient. This capture helper never calls any trading interface.
Simulation recovery, reconciliation, emergency stop and broker order evidence
remain undelivered; simulated fills cannot establish real fill quality.

Official interface references (checked 2026-10-16):

- https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-history-kline.html
- https://openapi.moomoo.com/moomoo-api-doc/en/quote/request-trading-days.html
- https://openapi.moomoo.com/moomoo-api-doc/en/trade/place-order.html

The history API documents US timestamps as US Eastern and provides paginated
DataFrames. The existing collector's request-capability evidence is retained;
it is not promoted into proof of response-session coverage.
