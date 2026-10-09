# Saved intraday experiment comparison (Q11)

Q11 describes two explicitly selected saved records in A/B order. Ordinary Q7
comparisons, Q7 diagnostics and Q8 final TEST records are accepted. Export an
ordinary Q7 child from a [Q10 collection](intraday_execution_scenarios.md) before
comparing it. A frozen selection without a TEST result is not an execution.

The operation validates the two experiment files and uses their recorded
evidence. It does not read Q5/Canonical sources, fit, execute strategies, discover
files, modify experiments or create a new comparison archive format. Its derived
result version is `market-vault-intraday-saved-comparison-v1`.

## Defaults and comparison basis

A is `left`, B is `right`. Each side selects a zero-based cost and candidate
index, defaulting to zero, in saved order. TEST contains one frozen result and
requires both indices to be zero. Each side retains its own selected candidate
and policy-matched benchmark.

Only **DEV/DEV with matching complete recorded evaluation basis** permits
neutral differences, always **B minus A**. A basis mismatch remains a successful
descriptive comparison with explicit failed checks. Any comparison containing
TEST is descriptive only, including TEST compared with itself: every numerical
delta is unavailable. There is no ranking, automatic winner, TEST search,
significance claim or promotion into Freeze/TEST.

| Required common basis | Recorded fields checked |
| --- | --- |
| Data and task | Data ID, symbol, interval, target horizon and evaluation scope |
| Trading days | Complete ordered TRAIN/VALIDATION/TEST date arrays and actual evaluated dates |
| Sessions and prices | Candidate and benchmark session clocks, price evidence IDs and complete ordered ledger sequence/day/slot/time/phase/row-version/raw-mark-price projections |
| Decision population | Ordered observation key, day, slot and decision time; scores and targets may differ |
| Development training | Each fold's complete training/validation dates, boundary, training keys, purged keys and validation keys |
| Account and risk | Initial cash, event order, candidate/benchmark risk version, annualization, risk-free rate, ddof and zero-volatility tolerance |
| Benchmark | Recorded definition and version, while retaining each side's own benchmark results |
| Algorithms | Common data/research/walk-forward/execution/cost/risk/benchmark versions; the selected strategy method's version only when both selected kinds use that method |

Raw-price and session checks require consistency across all four executions:
A strategy, A benchmark, B strategy and B benchmark. Self-comparison of an
internally contradictory Q7 record does not make its evidence consistent.
Policy-dependent ledger actions, account values and transactions are excluded
from the common input projection. Complete values are checked, not counts,
summary dates or rounded display strings. TEST training boundary, training/purged
keys, test keys and final-test versions are also shown as recorded basis.

Feature projection/order, strategy kind/rules/alpha/threshold, walk-forward
configuration and all six execution fields are shown as configuration
differences. Feature or strategy changes are permitted when the actual common
data, dates, decision identities and training basis match. Different execution
windows or costs do not require identical benchmark trades or returns.

Whole context, candidate, model, execution and experiment IDs are not numerical
equality gates: intentional configuration changes can alter them. Names, notes,
paths and environment metadata do not disable differences. Algorithm entries
contributed only by unselected candidates do not disable differences. The source
identities and selected indices remain attached to the result.

## Metrics, units and unavailable values

Candidate and benchmark [Q9 performance](intraday_performance.md) are derived
independently on each side. Original account return, observed drawdown, initial
and final cash, daily-risk statistics and candidate prediction errors/counts
remain explicitly `RECORDED`. Q9 metrics use `RECORDED_LEDGER_DERIVATION`.
Neither establishes source verification or a successful Replay.

| Unit | A/B values | Difference |
| --- | --- | --- |
| `RATIO` | Returns, drawdown, volatility, exposure, win rate, mean trade return and return-target MAE/RMSE | `PERCENTAGE_POINTS`: `(B - A) * 100` |
| `NUMBER` | Sharpe, R-squared, profit factor and payoff ratio | Numerical `B - A`, without multiplying by 100 |
| `COUNT`, `MINUTES`, `BARS` | Counts and mean holding measures | The same unit |
| `INITIAL_CASH_UNITS` | Normalized cash and quantity-based cash attribution | The same initial-cash unit |

For example, returns 0.10 and 0.12 differ by 2 percentage points. The desktop
shows ratios as percentages with six significant digits, preserving small
prediction errors instead of forcing them to `0.00%`. JSON keeps full precision.

Invalid structure/hashes are rejected. A valid historical record remains
describable; unsupported Q9 derivation is
`UNSUPPORTED_EXECUTION_OR_COST_VERSION`. Cash reconciliation failure is
`RECORDED_CASH_RECONCILIATION_FAILED`. Each side's candidate and benchmark are
independent: one unavailable derivation does not erase the other three analyses
or the original recorded fields. Overflow is unavailable, never NaN or infinity.

Basis equality and derivation availability are separate. Two records with the
same historical versions may have matching recorded basis while Q9 metrics are
unavailable. Each metric keeps its A/B value, unit, evidence and reason. A delta
is null when prohibited by TEST/basis rules or when either input is unavailable;
side-specific reasons remain present. Missing values never become zero. Zero
volatility remains available zero while Sharpe can be unavailable. Non-Ridge
prediction metrics are `NOT_APPLICABLE`; undefined R-squared without a parent
error gets `UNAVAILABLE_STATISTIC`.

## CLI and desktop

```console
market-vault research-intraday-compare-saved --left /absolute/development-a.json --left-cost-index 1 --left-candidate-index 2 --right /absolute/development-b.json --right-cost-index 0 --right-candidate-index 1
market-vault research-intraday-compare-saved --left /absolute/development.json --right /absolute/test.json
```

The settings-independent CLI returns structured `SUCCESS` with `report`,
containing the bound selections, `basis_checks`, `configuration_differences`,
`strategy_metrics`, `benchmark_metrics`, `basis_matches`, `delta_allowed` and
`delta_reasons`. Each metric row contains `metric`, `left`, `right` and `delta`.
Basis mismatch or TEST involvement does not fail the command. Invalid files or
parsed integer indices that are negative or outside the saved selection return
structured stderr `FAILED` and exit 1. Non-integer CLI tokens (including `True`)
are argparse syntax errors and exit 2. The Python API rejects booleans and other
non-integer index values with `ValueError`.

In **Quant Research → Intraday → Saved A/B**, explicitly open A and B,
select their saved cost/candidate positions, and compare. The four views show
strategy metrics, benchmark metrics, configuration differences and basis checks.
Long basis arrays/objects have compact count/hash descriptions in the table;
configuration differences show their parameter values, and the core and CLI
retain full values.

Compare captures both snapshots, indices and paths before work begins. The
displayed result identifies those captured selections. Editing a later input,
opening another file or encountering a failure preserves the last successful
result and its identities. Language/view changes only affect presentation. The
panel does not inherit Replay proof from another workspace or infer a saved
child's path from a Q10 collection.
