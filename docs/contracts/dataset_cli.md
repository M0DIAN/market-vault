# Dataset CLI Contract

Status: implemented (v0.5.0 PR-8)

This document defines the contract of the three formal Dataset commands —
`market-vault dataset-build`, `market-vault dataset-verify`, and
`market-vault dataset-inspect`. The CLI is a thin wrapper over the already
merged formal public chain; it is **not** a second Dataset builder and
**not** a second Dataset validator.

## 1. Status and scope

Implemented in v0.5.0 PR-8 on top of the merged PR-5 (orchestration),
PR-6 (materialization), and PR-7 (verified Dataset reader) cores. The CLI
adds no new identity algorithm, no new artifact, no new writer, and no new
reader. The package version remains **0.4.0** (the bump to 0.5.0 happens
only in PR-10).

## 2. The three commands

```text
market-vault dataset-build --plan <PATH>
market-vault dataset-verify --build-dir <PATH>
market-vault dataset-inspect --build-dir <PATH> [--offset N] [--limit N]
```

- `dataset-build` — execute one pinned, immutable Dataset build from a
  single explicit, versioned build-plan JSON document.
- `dataset-verify` — read and strictly verify one explicit final Dataset
  directory (`<output_root>/<dataset_id>`) through the verified reader.
- `dataset-inspect` — verify the same way and additionally print the scope,
  schema, spec pins, split spec, split diagnostics, build report, and an
  offset/limit slice of the logical rows as deterministic JSON.

`dataset-build` accepts **only** `--plan`. There is no `--output-root`,
`--built-at`, `--dataset-as-of`, `--canonical-build`, `--feature-spec`,
`--label-spec`, `--split-spec`, `--request`, `--force`, `--repair`, or
`--latest`: every formal fact comes from the plan, so the command line and
the file can never be two sources of truth.

## 3. CLI contract version

```text
DATASET_CLI_CONTRACT_VERSION = "market-vault-dataset-cli-v1"
```

Describes the CLI input/output contract only. It never enters
`dataset_id`, the Dataset manifest, the Parquet metadata, any spec pin, or
any artifact. It is recorded in every success and failure JSON output.

## 4. Build-plan schema version

```text
DATASET_BUILD_PLAN_SCHEMA_VERSION = "market-vault-dataset-build-plan-v1"
```

The version of the strict build-plan JSON contract consumed by
`dataset-build`. A build plan is an **execution input**, never an identity
artifact: its raw bytes never enter `dataset_id` or any artifact.

## 5. Result schema version

```text
DATASET_CLI_RESULT_SCHEMA_VERSION = "market-vault-dataset-cli-result-v1"
```

The version of the deterministic CLI result JSON contract shared by the
success and failure outputs of all three commands.

## 6. Build-plan root fields

The root object must contain **exactly** these fields, no more and no
less:

```json
{
  "plan_schema_version": "market-vault-dataset-build-plan-v1",
  "canonical_build_dirs": ["..."],
  "feature_spec_files": ["..."],
  "label_spec_files": ["..."],
  "requests": [{"..."}],
  "scope": {"..."},
  "split_spec": {"..."},
  "dataset_as_of": null,
  "output_root": "...",
  "built_at": "..."
}
```

Unknown fields, missing fields, duplicate JSON keys, wrong types, and
`null` in fields that do not accept it fail closed. JSON whitespace and key
order are semantically irrelevant; no canonical JSON form is required.

## 7. Canonical paths are explicit

`canonical_build_dirs` is a non-empty JSON array of non-empty path
strings, one per verified Canonical final build directory. Duplicates are
rejected. No parent directory is scanned, no `latest` is selected, and
path order never affects the Dataset identity. Each directory is handed to
`load_verified_canonical_build` for the existing formal verification; the
CLI implements no second Canonical validator.

## 8. Feature / Label paths are explicit

`feature_spec_files` and `label_spec_files` are non-empty arrays, each
entry explicitly pointing at one Feature / Label YAML file. Duplicates are
rejected; directories are never scanned; Feature and Label files never
mix. Each file is read as strict UTF-8 and parsed through
`parse_feature_spec` / `parse_label_spec` (the existing spec parsers). The
source file path never enters the spec identity.

## 9. Requests are explicit

`requests` is a JSON array; an empty array is legal and produces an
explicit EMPTY Dataset (scope keys without a request become MISSING
completion entries). Each request object must contain exactly:

```json
{
  "code": "US.MU",
  "interval": "1m",
  "adjustment": "NONE",
  "requested_session": "ALL",
  "anchor_market_calendar_date": "2026-07-01",
  "feature_window_start": "2026-07-01T13:30:00+00:00",
  "feature_window_close": "2026-07-01T13:36:00+00:00",
  "label_window_start": "2026-07-01T13:36:00+00:00",
  "label_window_close": "2026-07-01T13:42:00+00:00"
}
```

`label_window_start` and `label_window_close` must both be `null` or both
be timezone-aware ISO datetime strings. Requests are never auto-generated
and never inferred from the scope; each is constructed item by item into
the existing `PITSampleRequest` model.

## 10. Scope is explicit

`scope` contains exactly `symbols` (non-empty array), `trade_dates`
(non-empty array of strict `YYYY-MM-DD`), `interval`, `adjustment`, and
`requested_session`. It is constructed into the existing `DatasetScope`
model; the request/scope binding is verified by the existing orchestrator
preflight. The scope may contain keys without requests (recorded as
MISSING) and is **never** silently narrowed to the request set.

## 11. Split spec

`split_spec` contains exactly `spec_schema_version`, `name`, `version`,
`boundary_timezone`, `train_end_date`, `validation_end_date`,
`test_end_date`, `assignment_rule`, `purge_rule`,
`incomplete_label_policy`, and `out_of_range_policy`. It is constructed
field by field into the existing `ChronologicalSplitSpec` model, which
validates the timezone, the boundary ordering, and the fixed rule values.

## 12. `dataset_as_of`

`null` or a timezone-aware ISO datetime. Naive datetimes are rejected;
the value is normalized to UTC microseconds; the system local timezone is
never used. When set, the authoritative schema includes the
`dataset_as_of` field (`dataset_orchestration_schema(...,
include_dataset_as_of=True)`).

## 13. `built_at`

Required, timezone-aware ISO datetime (never `null`, never naive),
normalized to UTC microseconds. `datetime.now`, file mtimes, and the local
timezone are never used. `built_at` is a recorded fact that never enters
`dataset_id`. When an identical build already exists, the materializer's
idempotent path returns `created_new_build=false` and the output `built_at`
comes from the final **verified existing build**, never from the new plan;
a `built_at` difference is never misjudged as an identity difference.

## 14. `output_root`

A non-empty explicit path string: the parent directory of the final
Dataset directory. The final directory name is still fixed by the
materializer as `output_root / <dataset_id>`; no `dataset_id` override is
accepted. `output_root` is handed to `materialize_dataset_artifacts` for
its own formal safety verification; the CLI never creates, repairs, or
deletes it in advance.

## 15. Relative paths are anchored to the plan file's parent

`--plan` paths are absolute or relative to the current working directory.
Paths **inside** the plan are absolute or strictly relative to the plan
file's parent directory — never to the cwd. Path normalization only
affects the access location and never enters any Dataset identity.

## 16. Path safety

`~` is never expanded, environment variables are never expanded, globs
are never expanded, no extension is appended, and directories are never
scanned for inputs. All paths are handled with `pathlib`; `resolve()` is
never used to mask a link; the CLI reports lexically absolute paths.

## 17. Symlinks and junctions

The plan file, every Feature / Label file, and every existing parent path
component must be a real regular file / regular directory: symlinks and
Windows junctions / reparse points fail closed (Python 3.11 reparse-point
detection included; a path whose link status cannot be verified fails
closed). Canonical build directories and `output_root` are verified by the
existing formal reader / materializer link checks.

## 18. No `latest`

No command scans for a `latest` directory, never reads one, and never
writes one. Every input is an explicit path; every Dataset read is an
explicit final directory.

## 19. No glob

Inputs are exact path strings; the filesystem is never searched.

## 20. No settings

Dataset commands never load `settings.yaml`. They are dispatched before
`load_settings` in the shared entry, so a missing settings file or a
broken `--settings` value can never affect a Dataset command. Old commands
still load settings exactly as before.

## 21. No OpenD / network

Dataset commands never connect to OpenD and never access the network.
They never open a socket; the build pipeline reads only the pinned local
inputs and writes only through the materializer.

## 22. `dataset-build` fixed call chain

`dataset-build` executes exactly once, in this fixed order:

1. parse and validate the `--plan` path;
2. read and strictly parse the plan JSON;
3. resolve all explicit input paths;
4. `load_verified_canonical_build(...)` once per `canonical_build_dirs`
   entry;
5. read each Feature file as UTF-8 and call `parse_feature_spec(...)`;
6. read each Label file as UTF-8 and call `parse_label_spec(...)`;
7. construct `ChronologicalSplitSpec` from the plan `split_spec`;
8. construct the `PITSampleRequest` tuple from the plan `requests`;
9. construct `DatasetScope` from the plan `scope`;
10. `dataset_orchestration_schema(feature_specs, label_specs,
    include_dataset_as_of=dataset_as_of is not None)`;
11. `orchestrate_dataset_build(...)` once with
    `dataset_kind=DATASET_KIND_SUPERVISED`,
    `manifest_schema_version=DATASET_MANIFEST_SCHEMA_VERSION`,
    `serialization_format=SERIALIZATION_FORMAT_PARQUET`,
    `serialization_format_version=SERIALIZATION_FORMAT_VERSION_PARQUET`;
12. `materialize_dataset_artifacts(orchestration_result,
    output_root=..., built_at=...)` once;
13. `load_verified_dataset(materialization.build_path)` once;
14. re-check that `orchestration.dataset_id ==
    materialization.dataset_id == verified.dataset_id` and
    `materialization.build_path == verified.build_path`;
15. print the SUCCESS JSON only after the final reader verification.

No PIT, Feature, Label, Split, Parquet, manifest, staging, or rename logic
is duplicated in the CLI layer.

## 23. Authoritative schema

The CLI calls the existing `dataset_orchestration_schema` and passes the
result to the orchestrator, which re-derives and requires an exact match.
The CLI never builds a schema itself.

## 24. Materialization

Only the materializer writes: the staging directory, `dataset.parquet`,
`manifest.json`, `build_report.json`, the Feature / Label / Split spec
artifacts, `_SUCCESS`, and the final Dataset directory. The CLI itself
never writes the plan, the spec source files, the Canonical builds, extra
logs, `latest` / `current` pointers, summary files, caches, or locks.

## 25. Final reader verification

Every build ends with exactly one `load_verified_dataset` call on the
committed build path; SUCCESS is printed only when that verification
passes and the three-way `dataset_id` binding holds.

## 26. Idempotent rebuild

When the same logical Dataset already exists, the materializer's formal
idempotent behavior applies: `created_new_build=false`, nothing is
rewritten, and the output facts (including `built_at`) come from the
verified existing build.

## 27. `dataset-verify`

`market-vault dataset-verify --build-dir <PATH>`:

- does not load settings;
- does not access Canonical;
- does not call the orchestrator or the materializer;
- calls `load_verified_dataset` exactly once;
- never reads `latest`;
- never writes, repairs, or deletes any artifact;
- prints one deterministic JSON summary on success (exit 0);
- prints one FAILED JSON to stderr on corruption (exit 1).

## 28. `dataset-inspect`

`market-vault dataset-inspect --build-dir <PATH> [--offset N] [--limit N]`
calls `load_verified_dataset` exactly once and derives everything from the
returned `VerifiedDatasetBuild`: it never re-reads Parquet, never parses
`manifest.json` separately, and implements no weak check. It writes
nothing. `offset` defaults to 0, `limit` defaults to 20, `limit` may not
exceed 1000, and `limit == 0` is legal (returns empty rows).

## 29. Offset / limit

Rows are a plain tuple slice `rows[offset : offset + limit]` in the fixed
physical order; no reordering, no split filter, no column selection, and
no Parquet predicate. An offset beyond the row count returns empty rows.
`limit > 1000` fails at the argparse stage with exit code 2.

## 30. JSON scalar serialization

Rows are mapped to JSON objects by schema field order (never
`dataclasses.asdict` recursion, never pandas): `date` values serialize as
`YYYY-MM-DD`, datetimes as UTC microsecond ISO strings with `+00:00`,
`null` stays `null`, and bool / int / float / string stay formal JSON
scalars. Verified rows never contain NaN / Infinity.

## 31. Success output

stdout carries exactly one JSON object (fixed key order,
`ensure_ascii=False`, `indent=2`, trailing newline); stderr is empty; the
exit code is 0. `dataset-build` output:

```json
{
  "result_schema_version": "market-vault-dataset-cli-result-v1",
  "cli_contract_version": "market-vault-dataset-cli-v1",
  "command": "dataset-build",
  "result": "SUCCESS",
  "plan_schema_version": "market-vault-dataset-build-plan-v1",
  "created_new_build": true,
  "dataset_id": "...",
  "dataset_kind": "SUPERVISED",
  "dataset_status": "COMPLETE",
  "build_path": "...",
  "built_at": "...",
  "dataset_as_of": null,
  "dataset_schema_id": "...",
  "logical_dataset_content_id": "...",
  "logical_row_count": 1,
  "feature_spec_count": 1,
  "label_spec_count": 1,
  "split_result_id": "...",
  "reader_contract_version": "market-vault-verified-dataset-reader-v1"
}
```

All facts come from the final `VerifiedDatasetBuild`; `created_new_build`
is the one fact from the materialization result. `build_path` is the
lexically absolute path in POSIX slash form. `dataset-verify` prints the
same summary with `result: "VERIFIED"` and without `plan_schema_version`
and `created_new_build`. `dataset-inspect` prints the verify summary with
`result: "INSPECTED"` followed by `scope`, `schema_fields`, `feature_specs`,
`label_specs`, `split_spec`, `split_diagnostics`, `build_report`,
`row_offset`, `row_limit`, `rows_returned`, and `rows`.

## 32. Failure output

On a documented failure stdout stays empty, stderr carries exactly one
FAILED JSON object, and the exit code is 1:

```json
{
  "result_schema_version": "market-vault-dataset-cli-result-v1",
  "cli_contract_version": "market-vault-dataset-cli-v1",
  "command": "dataset-build",
  "result": "FAILED",
  "error_type": "DatasetCLIError",
  "error": "stable, readable message"
}
```

Argparse usage errors keep the standard argparse stderr and exit code 2.

## 33. Exit codes

- 0 — success (one JSON object on stdout, empty stderr);
- 1 — documented failure (empty stdout, one FAILED JSON on stderr);
- 2 — argparse usage errors (standard argparse stderr).

## 34. stdout / stderr boundary

stdout carries only the success JSON; stderr carries only the FAILED JSON
(or argparse diagnostics). No progress text, no warnings followed by
success, no partial success, no traceback for documented user errors, and
no mixed writes.

## 35. No write

`dataset-verify` and `dataset-inspect` never write: hashes, `mtime_ns`,
and the entry set of the build directory are unchanged, nothing is
created, touched, deleted, renamed, replaced, chmod'ed, or utime'ed, no
cache or lock is written, and no log lands in the Dataset directory.

## 36. No repair

A corrupt or conflicting artifact is reported as a FAILED result; nothing
is fixed, overwritten, or deleted.

## 37. Identity boundary

Dataset identity is determined entirely by the existing orchestration /
identity contracts. The CLI introduces no new identity source:
plan absolute path, plan parent directory, JSON whitespace and key order,
Feature / Label source file paths, Canonical build paths, `output_root`,
`built_at`, the CLI contract version, and the CLI result schema version
never enter `dataset_id`.

## 38. The build plan never enters identity

The plan document is an execution input. Its bytes, path, and
serialization form are never hashed into any identity.

## 39. CLI versions never enter identity

`DATASET_CLI_CONTRACT_VERSION`, `DATASET_BUILD_PLAN_SCHEMA_VERSION`, and
`DATASET_CLI_RESULT_SCHEMA_VERSION` describe CLI inputs and outputs only;
they never enter `dataset_id`, the Dataset manifest, the Parquet metadata,
or any spec pin.

## 40. EMPTY Dataset

`requests: []` (or requests whose samples all exclude) builds an explicit
EMPTY Dataset with `logical_row_count == 0`, `dataset_status == "EMPTY"`,
and a legal zero-row Parquet with the full schema — through the same
formal chain as COMPLETE builds.

## 41. Package version remains 0.4.0

The package version stays **0.4.0** through PR-9 of this sequence; the
bump to 0.5.0 happens only in PR-10.

## 42. PR-9 handoff

PR-9 owns the complete end-to-end determinism and leakage regression over
the full CLI surface: the broad threat matrix, crash-recovery, and
rebuild-equivalence suites. PR-8 only proves the command layer introduces
no new identity source.

## 43. PR-10 release handoff

PR-10 prepares the v0.5.0 release: version sync, README, CHANGELOG,
release notes, and package smoke. The CLI contract of this document is
stable input for that release.

## 44. MarketVault / quant boundary

The Dataset CLI never trains models, never backtests, and never trades.
It is a data-pipeline interface only; ML, backtesting, trading, the API
server, and the Python client are outside this contract.
