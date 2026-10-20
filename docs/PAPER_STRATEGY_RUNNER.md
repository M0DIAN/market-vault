# S19-S22: research to a bounded moomoo paper-strategy loop

Owner-authorized package, 2026-10-20 JST. Baseline:
`a45ddde391c31360e3fbeb8d8828520011ee7b7c`. Scope is one personal US
SIMULATE strategy experiment, not a production brokerage platform. Implement
in order; each final candidate needs independent exact-head review, required
CI, squash, and terminal exact-main push CI before the next implementation.
No live account action, installed-app replacement or release is part of this
code-delivery authorization. Use existing research algorithms and broker/session
primitives; do not recreate the Q1-Q91 research framework or the S1-S18 probes.

## Fixed tasks and acceptance

| Task | Goal and technical path | Dependency/defaults | Acceptance | Excluded |
| --- | --- | --- | --- | --- |
| S19 practical paper costs | Add an explicit estimated per-filled-order fee to the existing offline report analysis; share the numerical policy with the future runner. | Existing S17 public-equation checks. Owner accepts USD0.99/order as a paper research assumption. Legacy invocation remains unchanged. | Existing CLI shows assumption-adjusted match for the synthetic known case, preserves old BLOCKED/stop/source bytes, does not hide a position error or fit fees to arbitrary residuals. | Fee investigation, rewriting old journals/results, REAL rules, removing stop or granting order permission. |
| S20 frozen strategy admission/inference | Reuse existing saved DEV selection/Freeze/TEST and fitted linear/quadratic Ridge or rule semantics. Add explicit paper eligibility and frozen prediction, with no fitting in the live loop. | After S19 main. One explicit candidate; TEST is a fixed gate, never a winner-search objective. Default experimental gate: >=5 TEST days, >=5 completed trades, positive after-cost return, <=10% drawdown. | Real saved-source fixture produces identical predictions through the new entry; unavailable/failed candidate does not obtain executable admission; no TEST refitting/reselection. | New learner, unlimited parameter search, claims of statistical profitability, retraining on live future labels or paper observations. |
| S21 closed-bar shadow signals | Subscribe/poll moomoo K lines and turn completed same-session bars into existing LIGHT/CORE Features and frozen predictions. | After S20 main. One US.SPY/US.QQQ symbol; 1/5/15/30m matching the source; RTH/NONE; polling default5s; warmup and stride from source. No trading by default. | Direct source→closed window→Features→signal entry, same historical-window Feature/prediction values, no unfinished/stale/gapped/duplicate bar orders. | Tick/HFT, synthetic current prices, independent-data attestation, perpetual service, UI redesign or new archival format. |
| S22 bounded paper execution | Connect admitted frozen signals to a durable finite long/flat session, attributable BUY/SELL, fresh status/cash/position feedback, and fee-inclusive result reporting. | After S21 main. Explicit SIMULATE start; one share/maxUSD1000 per order; at most two round trips/session; one pending order; same-symbol initial flat; respect saved entry/holding/EOD windows. Existing stopped v1 journals are not resumed or reset. | Actual controller entry with a synthetic SDK boundary completes BUY→fill→SELL→fill, measures net cash once, restarts without duplicate submissions, and refuses unresolved/unowned exposure. | REAL, margin/short, adopting/liquidating old unrelated positions, unknown-order resend, automatic stop clearing, unattended deployment or asserting live execution from fixture CI. |

The gate values are transparent experimental defaults, not proof of economic
edge. Cost assumptions, position sizing and market fills differ from the
normalized historical account and must be disclosed in forward reports.
The finite research source can still return no eligible strategy; that is a
normal result, not a reason to lower the gate or search the same TEST again.

## S19: explicit estimated fee, not unlimited cash tolerance

The owner chose to treat the observed minimum-sized cash debit as an estimated
simulation trading fee and stop investigating it. Official moomoo stock paper
rules list commission USD0.0049/share with a USD0.99/order minimum, alongside
other fees. That supports plausibility, not transaction-specific confirmation:
https://www.moomoo.com/us/support/topic3_886.
https://www.moomoo.com/sg/support/topic5_689
(checked 2026-10-20 JST). Do not claim this flat assumption implements the full
published schedule or applies to every jurisdiction, product, or real account.

With reviewed source on PYTHONPATH, use the existing entry:

```text
python -m market_vault.moomoo_simulation_report --input EXISTING_EXPORT.json --output NEW_ANALYSIS.json --paper-fee-usd 0.99
```

Omitting the new option retains the legacy analysis. It is also accepted by
`analyze_report(path, paper_fee_usd="0.99")`. The additive `paper_fee_assessment`
can say `RECONCILED_WITH_ESTIMATED_PAPER_FEE` and
`blocks_paper_research=false`; source result/stop and `new_orders_authorized=false`
remain unchanged. This new owner-approved interpretation supersedes S18's
fee-attribution blocker for model/strategy research; it does not rewrite facts.

Each filled order is charged once; repeated cumulative observations are not
additional fees. Unfilled orders incur no estimated fee. Cash is compared as
`observed_delta - gross_signed_cash_flow + estimated_fee`; BUY gross is negative,
SELL positive. Only one cent of currency rounding is allowed. A different or
large residual, missing evidence, arithmetic inconsistency, or owned-position
mismatch is not covered by this assumption. Cost assumptions stay explicit in
research reports. Existing raw source and previous analyses remain unchanged.

S20-S22 in the table are implementation scope, not claims that they are already
available. Actual moomoo strategy operation needs an owner-local run after the
engineering chain is accepted; no fixture test substitutes for it.
