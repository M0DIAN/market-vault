# MarketVault Verified Dataset CLI Examples

This directory contains verified, offline examples of the three formal
Dataset CLI commands:

```text
market-vault dataset-build --plan <PATH>
market-vault dataset-verify --build-dir <PATH>
market-vault dataset-inspect --build-dir <PATH> [--offset N] [--limit N]
```

Every example file is validated by the production parser and the real CLI:
`dataset-build` accepts only `--plan`; every formal input comes from the
explicit, pinned, versioned build-plan JSON
(`market-vault-dataset-build-plan-v1`). The Dataset phase is fully offline:
no `settings.yaml`, no OpenD, no network, no `latest` scanning, no Canonical
discovery, no sample-request inference, and no current time.

```text
examples/dataset_cli/
    README.md
    render_plans.py                 # stdlib-only plan renderer
    plans/
        complete.plan.template.json # COMPLETE example template
        empty.plan.template.json    # EMPTY example template
    specs/
        feature_simple_return_v1.yaml   # FeatureSpec (simple_return)
        label_forward_return_v1.yaml    # LabelSpec (forward_return)
    split_specs/
        chronological_v1.json       # standalone ChronologicalSplitSpec
```

> **About the standalone split spec.** The Dataset CLI does not accept a
> standalone `--split-spec` argument; the formal build-plan embeds the same
> `split_spec` object. `split_specs/chronological_v1.json` is a readable
> reference source and the renderer's input, not an extra CLI input.

## 1. Prerequisites

- The project is installed (`pip install -e .` or the equivalent editable
  install) and `market-vault --version` prints `market-vault 0.6.0`.
- One or more **verified Canonical final build directories** exist. Pass
  the final Canonical build directory itself (`.../canonical/dataset=market_bars_canonical/<canonical_build_id>`),
  never its parent and never a `latest` path.
- The Dataset commands run fully offline; no settings file, OpenD host, or
  network is needed. The top-level `--settings` option is used only by
  settings-backed commands; Dataset, Sample Generation, and Dataset
  Catalog commands ignore it.

## 2. Generate the example bundle

`render_plans.py` is examples-only and uses the Python 3.11 standard library
only. It renders two plans (`complete.plan.json` and `empty.plan.json`),
copies the FeatureSpec / LabelSpec files, and copies the standalone split
spec into one destination bundle:

```powershell
python examples\dataset_cli\render_plans.py `
  --canonical-build-dir "D:\data\canonical\dataset=market_bars_canonical\<build-id-1>" `
  --canonical-build-dir "D:\data\canonical\dataset=market_bars_canonical\<build-id-2>" `
  --output-root "D:\data\datasets" `
  --built-at "2026-08-05T15:00:00+00:00" `
  --destination "D:\work\market-vault-dataset-example"
```

- `--canonical-build-dir` is repeatable; at least one is required.
- `--built-at` and `--dataset-as-of` must be timezone-aware ISO 8601
  datetimes; they are normalized to UTC with microsecond precision.
- The destination must not exist or must be empty; an existing non-empty
  destination is never overwritten.
- Identical inputs produce byte-identical bundles.

## 3. Inspect the generated files

```powershell
Get-ChildItem -Recurse "D:\work\market-vault-dataset-example"
Get-Content "D:\work\market-vault-dataset-example\complete.plan.json"
```

The rendered plans reference the spec files with paths relative to the plan
file's parent directory (`specs/...`), so the bundle stays relocatable.

## 4. COMPLETE build

```powershell
$complete = market-vault dataset-build `
  --plan "D:\work\market-vault-dataset-example\complete.plan.json" |
  ConvertFrom-Json

$complete
$complete.build_path
```

`dataset-build` prints a single JSON object to stdout. A COMPLETE result
requires, per request:

- the explicitly pinned Canonical final build directories collectively
  cover the actual bars the request needs;
- the Canonical interval / session / adjustment / source schema version
  match the FeatureSpec and LabelSpec requirements;
- the Feature lookback and the Label horizon are fully covered by actual
  bars;
- the request does not cross a trading day;
- the sample is not excluded by the split / purge assignment.

An arbitrary Canonical build never guarantees COMPLETE; the CLI only reports
what the verified reader proves from the actual inputs.

## 5. Verify

```powershell
market-vault dataset-verify `
  --build-dir $complete.build_path
```

Strictly read-only: it never writes, repairs, or deletes anything.

## 6. Inspect

```powershell
market-vault dataset-inspect `
  --build-dir $complete.build_path `
  --offset 0 `
  --limit 20
```

`--limit` is capped at 1000; `--offset` and `--limit` are non-negative
integers.

## 7. Idempotent rebuild

Running the same complete plan again returns the same `dataset_id` with:

```text
created_new_build = false
```

and no artifact is rewritten: identity and the formal artifacts decide
idempotency, and an existing conflicting final directory fails closed.

## 8. EMPTY build

```powershell
$empty = market-vault dataset-build `
  --plan "D:\work\market-vault-dataset-example\empty.plan.json" |
  ConvertFrom-Json
```

The empty plan declares `requests: []` while keeping the Canonical dirs,
FeatureSpec / LabelSpec files, scope, split spec, `built_at`, and
`output_root` explicit. The result is:

```text
dataset_status = EMPTY
logical_row_count = 0
```

The build still materializes a valid zero-row Parquet file, manifest, build
report, spec artifacts, and `_SUCCESS`, and the directory passes
`dataset-verify` and `dataset-inspect`. EMPTY is a designed outcome, not a
failure.

## 9. Exit codes

```text
0 = success
1 = documented Dataset failure
2 = argparse usage error
```

## 10. stdout / stderr

- Success JSON is printed to stdout only.
- Documented failure JSON is printed to stderr only.
- Argparse diagnostics go to stderr.
- Error output is never mixed into the success JSON stream; parse the
  success JSON from stdout alone.

## 11. Common errors and fail-closed boundaries

Each entry: symptom / cause / correct handling.

1. **Canonical parent root used instead of the final Canonical build dir**
   — `dataset-build` fails on a directory without the verified-build
   layout. Cause: the plan pinned a parent directory. Correct: pin the
   final `<canonical_build_id>` directory itself.
2. **`latest` path used** — the build fails. Cause: `latest` is never a
   formal Canonical input; the CLI never scans or selects it. Correct:
   pass the explicit final Canonical build directory.
3. **Canonical final dir missing `_SUCCESS`** — the build fails closed.
   Correct: use a complete committed Canonical build.
4. **Canonical verification failure** — the build fails with the reader's
   structured error. Correct: rebuild or re-point the plan; never repair
   the artifacts.
5. **symlink / junction / reparse-point paths** — paths with link
   components fail closed. Correct: use regular directory paths.
6. **Feature / Label source schema version mismatch** — the registry
   preflight fails. Correct: align the spec
   `requirements.source_schema_versions` with the pinned Canonical input
   (the example specs declare `"10.9"`).
7. **Unregistered transform ref** — the preflight fails. Correct: use a
   built-in registry `transform_ref` only.
8. **Insufficient Feature lookback** — the sample is excluded or the build
   fails; `simple_return` needs `window_bars` actual rows. Correct: pin
   Canonical coverage that satisfies the declared window.
9. **Incomplete Label horizon** — the label is `INCOMPLETE` and excluded
   from TRAIN/VALIDATION/TEST by default; it is never synthesized. Correct:
   extend the Canonical coverage or the label window.
10. **Request inconsistent with scope** — the build fails or yields an
    unexpected scope; requests and scope must agree on code, interval,
    adjustment, session, and trade dates.
11. **Naive `built_at`** — the plan parser rejects a timezone-less
    datetime. Correct: use a timezone-aware ISO 8601 value.
12. **Naive `dataset_as_of`** — same rejection. Correct: timezone-aware or
    `null`.
13. **Plan missing a field** — strict parsing fails with the missing
    field name. Correct: keep all ten root fields
    (`plan_schema_version`, `canonical_build_dirs`, `feature_spec_files`,
    `label_spec_files`, `requests`, `scope`, `split_spec`, `dataset_as_of`,
    `output_root`, `built_at`).
14. **Unknown extra plan field** — strict parsing fails. Correct: remove
    the field; the schema is fixed.
15. **Duplicate JSON key** — parsing fails (duplicate keys are rejected).
    Correct: emit unique keys.
16. **Duplicate YAML key in a spec** — spec parsing fails closed. Correct:
    emit unique mapping keys.
17. **Relative path misinterpretation** — relative paths inside the plan
    anchor to the plan file's parent directory, never to the current
    working directory. Correct: put the spec files next to the plan or use
    absolute paths.
18. **`output_root` confused with the build dir** — `dataset-verify` /
    `dataset-inspect` need the final Dataset build directory
    (`<output_root>/<dataset_id>`), not `output_root` itself.
19. **verify/inspect pointed at `output_root`** — the reader fails closed.
    Correct: point at the final Dataset build directory.
20. **Conflicting final build** — an existing different Dataset build
    directory under the same `dataset_id` name fails closed and is never
    overwritten. Correct: choose a different `output_root` or investigate
    the conflict.
21. **Staging residue** — a leftover staging directory from a crashed
    build is reported as a failure and never adopted. Correct: remove the
    residue only after confirming it is not a committed build.
22. **Cross-trading-day / TRADING_DAYS labels** — unsupported by the
    current Dataset contract; a `TRADING_DAYS` horizon or
    `cross_trading_day.allow: true` fails closed. Correct: keep `BARS`
    horizons with `allow: false`.
23. **`--limit` above 1000** — argparse rejects it with exit code 2.
    Correct: page with `--offset` / `--limit` ≤ 1000.
24. **EMPTY mistaken for failure** — `dataset_status = EMPTY` with
    `logical_row_count = 0` is a designed outcome of `requests: []`.
    Correct: treat EMPTY as a valid, verifiable result.

Never "fix" a failing example by deleting or modifying a final Dataset to
bypass verification, by force-overwriting, by patching the manifest, by
changing hashes, by auto re-collecting data, or by relaxing any fail-closed
validation. The CLI has no `--latest`, `--force`, `--repair`, `--discover`,
or `--now` options — if an example seems to need one, the plan itself is
wrong.
