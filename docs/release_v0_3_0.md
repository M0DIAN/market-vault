# MarketVault v0.3.0 Release Notes

## Release scope

```text
base tag: v0.2.0
base commit: daa8f55c070ec7b63273c83e076c5c792645bc23
release preparation base: 08d5d6ad2ccb7d7e0c2d219bffd82b31ca506045
```

## Merged development PRs

- PR #2 — trading calendar + CI
- PR #3 — resumable history backfill
- PR #4 — immutable force snapshots and trading-date starts
- PR #5 — inventory and coverage audit
- PR #6 — intraday integrity audit

## Offline validation

```text
387 tests passed before release-prep PR
Python 3.11 / 3.12 / 3.13 / 3.14 CI passed
compileall passed
repository hygiene passed
git diff --check passed
```

## Real local-data validation

### Inventory

```text
US.MU
raw files: 3
curated files: 3
snapshot_count: 3
snapshot_row_count: 4081
latest_query_row_count: 2641
completed trade dates: 2
incomplete trade dates: 0
```

### Coverage audit

```text
2026-07-30 → 2026-07-31
expected items: 2
complete items: 2
missing: 0
incomplete: 0
coverage: 100%
status: PASS
```

### Intraday audit

```text
2026-07-30:
selected run: 1bf4131f-ad3a-47b6-83cc-b77c99b51991
eligible rows: 1440
audited rows: 1440
internal gaps: 0
status: PASS

2026-07-31:
selected run: 2604a1e0-9e0f-4ac6-8608-f888a6bceb9c
eligible rows: 1201
audited rows: 1201
internal gaps: 0
status: PASS
```

Both days pass with different bar counts (1440 vs 1201); this does not mean
the tail boundary after 2026-07-31 20:00 was validated —
`boundary_coverage.evaluated=false`.

## Upgrade notes

- No data directory deletion or rebuild, no Parquet conversion.
- `init-catalog` stays idempotent.
- V0.2 Raw/Curated data and legacy `batch-<batch_key>.parquet` filenames
  remain supported; new snapshots use run-ID filenames.
- Legacy files missing newer metadata columns are handled conservatively by
  `inventory` and the exact-key audits; no schema metadata is fabricated from
  directory paths.
- No automatic migration or deletion is performed.

## Final release checklist

- [ ] PR #7 CI passes
- [ ] All offline tests pass
- [ ] wheel/sdist builds pass
- [ ] wheel installs in a fresh virtual environment
- [ ] `market-vault --version` = 0.3.0
- [ ] package metadata version = 0.3.0
- [ ] README/CHANGELOG versions agree
- [ ] inventory real-data verification passes
- [ ] audit real-data verification passes
- [ ] intraday-audit real-data verification passes
- [ ] main working tree is clean
- [ ] Only then create the v0.3.0 tag
- [ ] After the tag, decide whether to create a GitHub Release
