# Verified Dataset Reader Contract

Status: implemented in v0.5.0 PR-7
(`market_vault.dataset.reader` and `market_vault.dataset.reader_models`).

This contract defines the one public, read-only, fail-closed Dataset
artifact reader: `load_verified_dataset(build_dir)`. The reader accepts
one explicit Dataset final directory (`<output_root>/<dataset_id>`) and
independently rebuilds and verifies the complete Dataset facts from the
directory's own `dataset.parquet`, `manifest.json`, `build_report.json`,
`feature_specs/`, `label_specs/`, `split_spec.yaml`, and `_SUCCESS` —
without a `DatasetOrchestrationResult`, without re-executing PIT /
Feature / Label / split-or-materialization work, without scanning for a
`latest` directory, and without writing, repairing, or deleting any file.

## 1. Status and scope

Implemented in v0.5.0 PR-7 (`feat: add verified Dataset reader`) on top of
the immutable Dataset materialization core (PR-6). The reader turns one
committed Dataset build directory into a deeply immutable
`VerifiedDatasetBuild` whose facts are re-derived from the artifacts
themselves. It is the read half of ADR 0002 decision 9's materialization
steps; the Dataset CLI (PR-8) may only call this reader and must not
implement a second, weaker validator.

## 2. Public API

`market_vault.dataset` publicly exports:

- `load_verified_dataset(build_dir) -> VerifiedDatasetBuild` — the only
  public entry;
- `VerifiedDatasetBuild`, `DatasetBuildReportRecord`,
  `DatasetOutputLayoutRecord` — the frozen typed result models;
- `DatasetArtifactValidationError` — the single public fail-closed error
  (a subclass of `DatasetError`);
- `DATASET_READER_CONTRACT_VERSION` —
  `"market-vault-verified-dataset-reader-v1"`.

Not public: path helpers, junction helpers, hash helpers, whitelist
builders, manifest / report parsers, Arrow conversion helpers, row
validators, split reconstruction helpers, second-pass validators, and
mutable payload builders.

## 3. Reader contract version

`DATASET_READER_CONTRACT_VERSION` describes the reader code contract only.
It is carried as a field of `VerifiedDatasetBuild` and never enters
`dataset_id`, the manifest, the Parquet metadata, or any artifact; it
modifies no artifact.

## 4. Explicit build directory

The reader accepts exactly one `build_dir` argument (no expected result,
no manifest / schema / dataset_id / specs override, no `strict=False`, no
`skip_hash`, no `skip_parquet`, no `repair`, no `latest`, no `output_root`,
no writer / clock / callback / registry / network provider). The argument
must be a path-like pointing at the exact final Dataset directory
`<output_root>/<dataset_id>`; absolute and relative call forms are
accepted, and the returned `build_path` is always a lexically absolute
`Path`.

## 5. No latest scanning

The reader never scans `output_root`, never resolves `latest` / `current`
pointers, and never guesses the directory from parents. The parent
directory is only used to walk the path components for link safety. A
sibling `latest` directory, a second Dataset directory, or any other
parent content is never consulted.

## 6. Result model

`VerifiedDatasetBuild` carries: `reader_contract_version`, `dataset_id`,
`dataset_kind`, `status`, `built_at`, `dataset_as_of`, `schema`, `rows`
(strict tuple-of-tuples in the schema field order; no dicts, no pandas
objects), `manifest` (frozen typed `DatasetManifest`), `feature_specs` /
`label_specs` (frozen typed spec tuples in the manifest pin order),
`split_spec` (frozen parsed `ChronologicalSplitSpec`), `split_result`
(the `ChronologicalSplitResult` re-derived from the actual rows),
`build_report` (frozen `DatasetBuildReportRecord`), `manifest_payload`
and `build_report_payload` (the original verified canonical bytes), and
`build_path` (absolute; `build_path.name == dataset_id`; location-only,
never identity-bearing).

## 7. Deep immutability

The model is frozen and deeply immutable: no mutable dict, mutable list,
pandas DataFrame, unverified PyArrow Table, file handle, temporary path,
current time, elapsed time, arbitrary metadata, logger, or callback. (The
carried split result's `assignment_rows` remain the existing split-layer
contract's immutable tuple of mapping rows.)

## 8. Path safety

The input is checked on its raw string (both separators) for lexical `.`
/ `..` components *before* `pathlib` construction (pathlib strips `.`
during parsing), then converted to a lexically absolute `Path`; `resolve()`
is never used to mask a link. The build directory and every existing
parent component must be a real regular directory with no symlink or
junction; a path that does not exist, is a file, a FIFO, or a special
type fails closed.

## 9. Symlink / junction defense

Every path component, the build directory itself, and every artifact
entry are rejected when they are a symlink or a Windows junction / reparse
point. The check reuses the materialization layer's Python 3.11-compatible
junction detection (the `FILE_ATTRIBUTE_REPARSE_POINT` attribute through
`ctypes`), so it never relies on `Path.is_junction()` (Python 3.12+).

## 10. Python 3.11 Windows junction

On Python 3.11 Windows, junctions are detected through the Windows API
reparse-point attribute; when the API cannot be queried the check fails
closed. A path whose link status cannot be verified is never trusted.

## 11. `_SUCCESS`

`_SUCCESS` must exist as a regular file, must not be a symlink or
junction, must not be a directory or special file, and its content must
be exactly `b""`. Missing, non-empty, BOM, newline, space, directory,
symlink, junction, and special-file forms are rejected. The reader never
creates or repairs `_SUCCESS`, and `_SUCCESS` never appears in
`manifest.output_files`.

## 12. Manifest validation

`manifest.json` is read as raw bytes and passed through the existing
`validate_dataset_manifest` (typed validation, identity re-computation,
spec-container kinds, duplicate pins, row-version coverage, gap-reference
uniqueness, status / row-count combinations, output paths). The reader
additionally requires `dataset_kind == SUPERVISED`,
`serialization_format == parquet`, the current
`serialization_format_version`, `status` COMPLETE or EMPTY consistent with
the row count, `split_spec` present with kind SPLIT, Feature pins kind
FEATURE, and Label pins kind LABEL.

## 13. Canonical manifest bytes

The raw bytes must exactly equal `serialize_dataset_manifest(manifest)`:
non-canonical whitespace, pretty printing, key-order changes, trailing
whitespace, BOMs, and non-canonical timestamp representations are
rejected.

## 14. Directory-name / dataset-id binding

`manifest.dataset_id` must exactly equal the build directory name, and
the directory name must be strict lowercase 64-hex.
`.staging-<dataset_id>` and any other name are not valid build
directories.

## 15. Exact whitelist

The exact entry set is derived from the manifest pins:
`dataset.parquet`, `manifest.json`, `build_report.json`,
`split_spec.yaml`, `_SUCCESS`, the `feature_specs/` and `label_specs/`
directories, and exactly one
`<name>--<version>--<content_sha256>.yaml` file per Feature / Label pin.
Missing files, extra files, extra directories, a second Parquet, nested
Dataset directories, temp / backup / lock / log files, `.DS_Store`,
`Thumbs.db`, `__pycache__`, symlinks, junctions, FIFOs, sockets, and
non-regular entries fail closed. Nothing is ever deleted or ignored.

## 16. `DatasetOutputFile` full records

Authoritative records are rebuilt from the actual build directory and the
manifest pins: `dataset.parquet` (role `dataset`, content role
`logical_rows`, row count = manifest `logical_row_count`),
`build_report.json` (role `build_report`, content role = build-report
schema version, row count 1), Feature / Label / Split spec artifacts
(role `feature_spec` / `label_spec` / `split_spec`, content role = spec
artifact version, row count 1). `manifest.json` and `_SUCCESS` are never
recorded. `manifest.output_files` must equal the rebuilt records in all
six fields (relative_path, file_role, content_role, row_count, byte_size,
sha256) under the manifest sort rule.

## 17. File SHA / size

Every recorded file must exist as a regular non-link file with its exact
recorded byte size and streaming SHA-256.

## 18. Feature artifacts

Each Feature artifact filename is derived from the manifest pin; the raw
bytes are parsed with the existing `parse_feature_spec`, the parsed
`feature_label_spec_pin` must equal the manifest pin, and the raw bytes
must equal `feature_spec_artifact(parsed)` (canonical artifact bytes).
Return order follows the manifest pin order (never filesystem enum
order); duplicate Feature spec names fail.

## 19. Label artifacts

Each Label artifact follows the identical contract through
`parse_label_spec`, `feature_label_spec_pin`, and
`label_spec_artifact`; duplicate Label spec names fail.

## 20. Split artifact

`split_spec.yaml` is parsed with the strict package-internal
`parse_split_spec_artifact`; `kind` must be SPLIT;
`chronological_split_spec_pin(parsed)` must equal the manifest split pin;
the raw bytes must equal `split_spec_artifact(parsed)`.

## 21. Authoritative schema re-derivation

The authoritative `DatasetSchema` is re-derived from the parsed typed
specs via `dataset_orchestration_schema(feature_specs, label_specs,
include_dataset_as_of=manifest.dataset_as_of is not None)` and must
exactly equal the manifest schema; its `dataset_schema_id` must equal the
manifest's. This proves fixed fields, order, Feature non-nullability,
Label nullability, `dataset_as_of` presence, split fields, and the
absence of any drift — never by guessing specs from the Parquet schema.

## 22. Parquet schema

The single `dataset.parquet` must carry the exact Arrow schema mapped
from the logical schema: field order, Arrow types, and nullability. The
field contract and the metadata set are verified separately, because
`pa.Schema` equality ignores metadata.

## 23. Parquet metadata

The decoded UTF-8 metadata mapping must exactly equal the six fixed keys:
`market_vault.dataset_id`, `market_vault.dataset_schema_id`,
`market_vault.logical_dataset_content_id`,
`market_vault.serialization_format_version`, `market_vault.row_order`,
and `market_vault.materializer_version` — with the manifest's values and
the current materializer / row-order constants. Extra, missing, or
changed keys are rejected.

## 24. Logical rows

The Parquet is converted to schema-ordered logical tuples (date32 ->
`date`, timestamps -> UTC microseconds `datetime`); floats are rejected
when NaN or ±Infinity appear. No pandas path, no schema inference, no
automatic cast, and no automatic column completion.

## 25. Logical content ID

`logical_dataset_content_id(manifest.schema, row_mappings)` is recomputed
from the actual rows and must equal the manifest
`logical_dataset_content_id` (this also enforces every scalar type,
nullability, and NaN / Infinity rejection through the identity encoding).

## 26. Physical row order

The physical row order must be exactly `code` ASC,
`feature_window_close` ASC, `sample_key` ASC. A wrong physical order is
rejected even when the logical content ID is unchanged (the content ID is
row-order-independent by contract).

## 27. Sample uniqueness

`sample_key` values must be globally unique; duplicates fail closed.

## 28. Scope binding

Every row's `code` must belong to `manifest.scope.symbols`; codes outside
the scope are rejected. `code` is a formal column and is never recovered
by parsing `sample_key`.

## 29. `dataset_as_of`

When `manifest.dataset_as_of` is null the schema and rows must carry no
`dataset_as_of` field; when set, the schema must carry it and every row
value must exactly equal the manifest `dataset_as_of`.

## 30. Split re-derivation

From every final row's formal facts the reader constructs
`ChronologicalSplitSample(sample_key, sample_version_id,
feature_window_close, label_status, actual_label_end_time)` and calls the
existing `assign_chronological_splits(samples, split_spec)` — a pure
verification re-derivation; Feature and Label execution are never re-run
and stored assignments are never used as derivation inputs. Every stored
`feature_window_close_date`, `nominal_split`, `final_split`,
`assignment_status`, `reason_code`, and `purge_boundary` of every row
must equal the re-derived assignment for that `sample_key`.

## 31. Split result identity

The re-derived `split_result.split_result_id` must equal the build
report's `split_result_id`; the split spec content ID, sample count, and
assigned / purged / excluded counts must equal the re-derived result's
facts. The re-derived `ChronologicalSplitResult` (whose own construction
re-derives every assignment through the shared classification rule) is
carried in the result model.

## 32. Build report typed record

`build_report.json` is parsed into the frozen `DatasetBuildReportRecord`
with the exact formal field set (report schema version, materializer
version, dataset identity facts, status, `built_at` / `dataset_as_of` as
UTC microseconds, schema / content IDs, row count, orchestration contract
version, row order, manifest / serialization versions, spec counts,
canonical pin / row-version counts, completion counts, execution
diagnostics counts, split spec content ID, split result ID, and the exact
`DatasetOutputLayoutRecord`). Fixed version fields must equal the current
constants; counts are real non-negative integers; `dataset_id` and the
split IDs are strict lowercase 64-hex.

## 33. Build report canonical bytes

The reader regenerates the canonical report bytes from the parsed typed
record (never from a `DatasetOrchestrationResult`) and requires the
actual file bytes to be byte-equal: UTF-8 without BOM, sorted keys,
compact separators, `ensure_ascii=True`, trailing newline, no extra or
missing field.

## 34. Observable fact binding

Every report fact that can be independently rebuilt from the final
artifacts is exactly bound: dataset / status / timestamps / schema /
content IDs / row count / spec counts / canonical pin and row-version
counts / completion counts / split spec content ID / split result ID /
assigned / purged / excluded counts / output layout / every fixed
version field.

## 35. Non-identity recorded diagnostic limits

The following pre-filter execution diagnostics cannot be fully
regenerated from the final directory: `request_count`,
`pit_sample_count`, `feature_excluded_sample_count`, and some cross-
Feature-excluded Label complete / incomplete totals. For these the reader
verifies types, non-negativity, the fixed
`DatasetOrchestrationDiagnostics` matrix (pit == feature complete +
excluded, pit == label complete + incomplete, split == feature complete,
split == assigned + purged + excluded, logical rows == split, completion
keys == scope keys), the exact canonical bytes, and every observable
cross-check. They remain non-identity recorded facts; the reader never
claims to rebuild the full upstream execution history from the final
Parquet, never re-runs PIT / Feature / Label, never accesses Canonical
builds, and never guesses missing samples.

## 36. Upstream Canonical pin verification boundary

Canonical pins, row-version IDs, and gap references are verified through
the manifest identity contract: typed manifest validation and the
recomputed `dataset_id` over the identity-bearing fields. The reader
never scans or reloads upstream Canonical build directories; this is
Dataset-artifact self-consistency verification, not a re-audit of
upstream directories.

## 37. EMPTY Dataset

An EMPTY build is read with zero rows, the full schema, the full Parquet
metadata, all spec artifacts, a zero-assignment split result, and the
correct zero-row logical content ID; report counts are bound to the empty
result.

## 38. No write

The reader never opens any file for writing, never creates directories or
temporary / cache / lock files, never deletes, renames, replaces, chmods,
or utimes, never writes logs into the build directory, never modifies the
manifest / report / specs / Parquet, and never creates or repairs
`_SUCCESS`. Regression tests snapshot every file hash, `st_mtime_ns`, and
the entry set before and after successful and failed reads.

## 39. Second-pass verification

Before the result is constructed the reader re-verifies the path
contract, the exact whitelist, `_SUCCESS`, and every manifest file size /
hash. A concurrent modification between the first pass and the final
pass is detected and fails closed; a mixed-instant partial result is
never returned.

## 40. Fail-closed errors

Every documented failure is `DatasetArtifactValidationError` with the
`__cause__` preserved: invalid paths, missing directories, symlinks /
junctions, missing / extra files, invalid `_SUCCESS`, manifest JSON /
identity / canonical-bytes failures, hash / size mismatches, wrong roles,
spec parse / pin / canonical failures, report failures, Parquet read /
schema / metadata / content failures, split re-derivation mismatches, and
NaN / Infinity. An already-wrapped error is never double-wrapped; no
partial result is returned; broad `except Exception` is never used, so
real programming errors are not disguised as artifact corruption.

## 41. No network / OpenD

The reader uses no network and no OpenD; the complete verification is
offline and deterministic.

## 42. No PIT / Feature / Label execution

The reader never calls `assemble_point_in_time_samples`,
`execute_builtin_features`, `execute_builtin_labels`, the materializer,
or the orchestrator. The only re-executed computation is the pure split
re-derivation through the existing `assign_chronological_splits`
contract.

## 43. No repair

The reader never fixes a manifest, rewrites a report or spec, repairs a
Parquet, recreates `_SUCCESS`, or deletes unexpected files.

## 44. No Dataset CLI

This PR implements no CLI commands (`dataset-build`, `dataset-verify`,
`dataset-inspect`), no API server, and no Python client.

## 45. PR-8 handoff

PR-8's Dataset CLI may only use `load_verified_dataset` for
`dataset-verify` / `dataset-inspect`; it must not implement a second,
weaker validator. `dataset-build` stays the materializer / orchestrator
pipeline.

## 46. MarketVault / quant boundary

The reader serves verified Dataset facts only; ML training, backtesting,
and trading remain outside the project layer.

## 47. Package version

The package version stays **0.4.0** (the v0.5.0 bump happens only in
PR-10); no dependency and no identity algorithm changed.
