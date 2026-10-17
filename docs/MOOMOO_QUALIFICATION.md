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
