# Intraday Research Data V1

The **Quant Research → Intraday / 日内研究** tab builds a local intraday
research file. It contains independent Feature observations, the complete
recorded session price stream and optional same-session training targets.
This is an additive data format. Cross-Day Research Dataset and Backtest V1
retain their existing semantics and entry points.

## Data and time contract

Inputs are explicit verified Canonical builds from the qualified TS2 cohort
(`10.9-mv-ts2`), one US symbol, RTH, `NONE`, one interval and an explicit
verified trading-day schedule. V1 supports **1m, 5m, 15m, 30m**. The 60m
nominal tail availability is outside this intraday contract.

The builder strictly re-reads every supplied Canonical artifact. Existing TS2
admission verifies the cohort, immutable row identities and provenance before
reconciliation. Conflicting versions fail before archive filtering. Inputs
may cover more dates than the declared schedule; only its sessions are
selected. Rows on declared closed dates, off-grid rows, nonpositive prices,
negative volume or availability different from the end of the complete bar
are errors. A non-null archive cutoff applies to the schedule and rows.

Each schedule supplies actual RTH geometry, including admitted early closes
and DST. Observed row counts never establish the session's expected end.
No price is forward-filled, interpolated or moved into another slot.

### Feature observations

The default is `5m`, `LIGHT_TECHNICAL`, `stride_bars=1`. The existing presets
and formulas are reused: LIGHT has a five-bar Feature window; CORE has 26.
Windows restart at each session open and never borrow from the previous day.
The first proposed slot is `window_bars - 1`, then every `stride_bars` on the
nominal session grid. Missing prices do not restart or shift this grid.

Each request is **Feature-only PIT**. Existing PIT assembly and TS2 Feature
execution produce the actual values and their provenance identities. A row
is `READY` only when its full declared Feature window is present and TS2
execution is complete; otherwise it remains an `UNAVAILABLE` observation.
The report records decision time, window start, slot, Feature values and
per-Feature value IDs. A session too short for the preset has zero observations
and keeps all its prices and warmup count.

### Complete prices and independent training targets

Prices retain all available session slots, including warmup and bars between
sampled observations. A separate gap list records missing expected slots.
Each price binds the exact Canonical row version, open/availability clocks
and OHLCV. Prices are historical evidence; a strategy cannot treat an entire
future bar as available at its open.

`target_horizon_bars` is a positive integer or null. Its default in the desktop
is **3**. For observation at slot `k`, the target uses the open of slot `k+1`
through the close of slot `k+H`:

```
target = close[k + H] / open[k + 1] - 1
```

Every intervening slot must exist in the same session. A complete target
records its actual last-bar availability time and exact entry/exit row IDs.
Insufficient future session bars produce `INCOMPLETE / SESSION_END`; missing
prices produce `INCOMPLETE / MISSING_PRICE`. Incomplete targets have no value
or asserted actual label-end time. Null H disables the target view entirely.
Feature observations and prices never depend on target completeness or H.

For a complete ordinary five-minute session with 78 bars, LIGHT and stride 1
give 74 observations, beginning at 09:55 New York and ending at 16:00. H=3
gives 71 complete targets; the last three observations remain present. The
admitted 42-bar early-close session gives 38 observations and 35 targets.
All serialized and displayed observation times are explicitly UTC.

## Files, verification and identity

The plan version is `market-vault-intraday-data-plan-v1`; the file version is
`market-vault-intraday-data-v1`. The file includes the normalized plan,
Canonical build IDs, applicable algorithm versions and the entire raw report.
The report includes the TS2 execution identity, ensuring Feature implementation
pins remain bound even when no observations can be emitted.

`data_id` covers all of these data and algorithm fields, excluding only input
directory locators. File content is immutable canonical JSON. A changed source
build can change identities even when some earlier Feature values stay equal.

`load_intraday_dataset` verifies the file identity, strictly reloads Canonical
sources, reruns PIT/Features/targets and compares every field of the complete
saved snapshot. A re-signed changed Feature or target therefore fails source
verification. A digest alone is not proof of data authority. Canonical sources
must remain available at the recorded paths for inspection. Moving the data
file itself does not change those recorded paths.

Saving exclusively creates one named file with flush/fsync and byte readback.
An existing identical file may be reused. Different existing content is an
error; choose a new file path. The writer does not create parent directories,
replace files or mutate source data. An interrupted creation can leave a
partial file; inspection reports the error, and a new output path is available.

## CLI

Both commands work offline without loading settings or initializing OpenD:

```bash
market-vault research-intraday-build --plan intraday-plan.json --output intraday-data.json
market-vault research-intraday-inspect --data intraday-data.json
```

The plan contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `plan_schema_version` | `market-vault-intraday-data-plan-v1` |
| `canonical_build_dirs` | Nonempty explicit directory list; relative paths resolve from the plan directory |
| `schedule` | The complete existing Research Build Plan schedule declaration, including every civil date and its evidence |
| `symbol` | One US symbol |
| `interval` | `1m`, `5m`, `15m` or `30m` |
| `preset` | `LIGHT_TECHNICAL` or `CORE_TECHNICAL` |
| `stride_bars` | Positive integer, measured on the session grid |
| `target_horizon_bars` | Positive integer or null |
| `dataset_as_of` | Aware ISO timestamp or null |

Unknown fields, duplicate keys, unsupported versions, bool-as-number and
nonfinite values are rejected. Successful stdout contains the full data and
summary in `market-vault-intraday-data-cli-result-v1`; documented failures
return code 1 with structured JSON on stderr. No result is silently truncated.

Plan and Canonical source paths use the existing lexical path contract: no
`.`/`..` components, shell expansion or hidden link resolution. Relative paths
without those components are supported. Invalid plan paths and non-string
Canonical path elements fail before output creation, so a successful build
never records an unreadable locator inherited from its plan directory.

Python entry points are in `market_vault.research.intraday_data`:
`build_intraday_dataset`, `write_intraday_dataset`, `load_intraday_dataset`,
`verify_intraday_dataset`, `intraday_summary`. Execution consumers must verify
source reconstruction before relying on caller-supplied snapshot bytes.

## Local desktop workflow

Prepare the TS2 source cohort through the existing Dataset Builder when
needed. In **Intraday**, select symbol, dates, interval, preset, stride and
optional training horizon. Preview checks calendar and local source coverage;
its predicted observation count assumes complete prices. Build always checks
the current inputs again, then materializes/reuses verified Canonical data and
saves the new intraday file to the explicit destination.

The last selected trading day needs no future trading-day coverage. Successful
build or open shows actual observation/target/gap counts and a 100-row paged
observation table. Every observation is retained in the model and file. An
open/build failure preserves the last successful file and view. Preview is a
separate display and never substitutes for data verification. Language changes
retain edited parameters. The legacy Dataset context remains independent.

This data milestone does not yet activate the intraday execution, strategy
comparison or final TEST entries; those consume this format in the following
authorized mainline tasks.
