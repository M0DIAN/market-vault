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
