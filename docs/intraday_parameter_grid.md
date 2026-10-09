# Saved intraday parameter grid and neighbors (Q13)

Q13 describes the complete finite parameter grid already saved in an ordinary
Q7 **DEV `INTRADAY_DIAGNOSTICS`** experiment. It identifies the actual neighboring
coordinates of one explicit center and reports neutral metric differences.
It does not create or run a candidate, fit, load Q5/Canonical data, rewrite a
saved artifact, select a winner or change Open/Replay evidence.

## Inputs and retained coordinates

The cost index and center candidate index are zero-based and default to **0**.
Python indices must be actual nonnegative integers; booleans and floating-point
indices are rejected. The default metric is **`total_return`**.

The result retains every declared axis and cost scenario in original order.
For the selected cost, `cells` retains every saved candidate and its actual
index, ID, name, complete axis coordinates and selected metric. Axis descriptors
include `condition_index` for Composite rule conditions. An axis' input order
does not imply numerical order, distance or priority. JSON numbers preserve
full precision; desktop coordinate labels use round-trip decimal text rather
than the shorter formatting used for displayed return metrics.

The original Q7 grid grammar and 64-evaluation limit remain unchanged. A zero-axis
diagnostic still has its one declared candidate. A singleton axis remains an
axis with one value. Neither case invents a neighbor. Ordinary comparisons,
frozen selections, TEST and Q10 collections are unsupported inputs. Exporting
a Q10 ordinary comparison does not turn it into a diagnostics grid.

## Metrics and availability

| Metric | Source | Unit |
| --- | --- | --- |
| `total_return` | Recorded execution metrics | `RATIO` |
| `observed_max_drawdown` | Recorded execution metrics | `RATIO` |
| `trade_count` | Recorded execution metrics | `COUNT` |
| `worst_fold_return` | Q12 fold diagnostics | `RATIO` |
| `median_fold_return` | Q12 fold diagnostics | `RATIO` |
| `best_fold_return` | Q12 fold diagnostics | `RATIO` |

The first three are labelled `RECORDED`. They remain descriptions of the saved
numbers even if another Q12 derived measure is unavailable. Fold metrics use
the complete [Q12 risk availability and cash/fold reconciliation rules](intraday_risk_diagnostics.md),
with evidence `RECORDED_LEDGER_DERIVATION`. A failing candidate retains its
coordinate, identity and explicit reason; it does not erase other grid cells.
No historical version or arithmetic failure becomes zero, infinity or a
ranking penalty.

## Numeric neighbors and complete comparison basis

For each axis, keep all other coordinates fixed and select the nearest
strictly smaller and nearest strictly larger declared numeric value, when
present. There are no diagonal neighbors, interpolated points or implicit
trials. Unequally spaced and unsorted input values use the same definition.
Neighbor output follows the original axis order, with LOWER then HIGHER for
each axis, and retains the actual saved candidate indices.

Before computing neighbor minus center, Q13 uses the complete existing
[Q11 recorded comparison basis](intraday_saved_comparison.md). The check still
includes center strategy, center benchmark, neighbor strategy and neighbor
benchmark: all four complete raw price/session projections must agree. Actual
decision identities, fold dates/keys/purge boundaries, applicable algorithm
versions, initial account and risk/benchmark definitions retain their existing
checks. Matching IDs or one displayed page cannot substitute for these values.

`basis_matches` and `failed_basis_checks` describe that complete check. The
compact Q13 result lists failed check names rather than repeating the full raw
ledger arrays for every neighbor. The source experiment and candidate IDs bind
the complete records; Q11's existing full A/B report remains available when its
detailed values are needed.

A basis mismatch preserves the neighbor's recorded metric, disables its delta
with `BASIS_MISMATCH`, and excludes it from the local summary. When basis matches,
delta uses the original Q11 convention: ratio differences are multiplied by
100 and labelled `PERCENTAGE_POINTS`; count differences stay `COUNT`. Missing
values retain `LEFT_UNAVAILABLE`, `RIGHT_UNAVAILABLE` or `BOTH_UNAVAILABLE`.
Intermediate difference overflow is `NUMERIC_OVERFLOW`.

## Neighborhood summary

The summary population is explicitly
`AXIS_NEIGHBORS_EXCLUDING_CENTER`. It reports three separate counts:

- `neighbor_count`: actual axis-adjacent neighbors;
- `basis_matching_count`: neighbors sharing the complete center basis;
- `available_count`: matching neighbors with an available selected metric.

Minimum, median and maximum use only that final available population, in the
metric's original unit. They describe neighbors themselves, not differences
or a rebalanced portfolio. An even-sized median is the midpoint of its two
middle values; it can be fractional for trade counts. An unavailable center
does not erase valid neighbor values from this description, although deltas
requiring the center remain unavailable.

An empty topology is `NO_NEIGHBORS`. Existing neighbors with no basis match give
`NO_MATCHING_BASIS`. A matching population with no metric values gives
`NO_AVAILABLE_NEIGHBOR_METRICS`. All three cases have null minimum/median/maximum.
The result does not assign robustness grades, PASS/FAIL to a strategy, winners,
recommended parameters or statistical significance.

## CLI, desktop and computation scope

```console
market-vault research-intraday-parameter-grid --experiment /absolute/diagnostics.json
market-vault research-intraday-parameter-grid --experiment /absolute/diagnostics.json --cost-index 1 --center-candidate-index 3 --metric median_fold_return
```

The CLI uses `market-vault-intraday-parameter-grid-v1`. Success and descriptive
per-cell unavailability return exit 0; invalid saved files, unsupported modes,
metrics or parsed indices produce a FAILED JSON envelope on stderr and exit 1.
Noninteger argparse inputs retain exit 2. Invoke the installed `market-vault`
console entry for its process exit code. No settings or OpenD initialization
is required.

In **Intraday → Development research**, the parameter-grid view shows explicit
cost, metric and center selection, the full saved coordinates, neighbors and
their summary. Selecting a grid cell identifies the same actual candidate used
by existing model, ledger, performance and risk views. Grid/metric selection is
descriptive and does not start a new research run or freeze a candidate.

The Python API is
`analyze_intraday_parameter_grid(snapshot, *, cost_index=0, center_candidate_index=0, metric="total_return")`.
It decodes the immutable snapshot once per action, reuses the original Q11
selection/basis/delta helpers and Q12 derivation, and creates no per-cell
`StrategyExperiment` objects or global cross-action cache. Only selected-cost
cells and at most four neighbors require derived metrics or basis evaluation.

The additive report has its own version and complete-content `grid_id`. Q7/Q8
saved grammar and IDs, Q11 public output, Q12 semantics, existing research and
execution formulas, and application/package version **0.9.0** remain unchanged.
