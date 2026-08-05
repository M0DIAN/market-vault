# Dataset Materialization Contract

Status: implemented in v0.5.0 PR-6
(`market_vault.dataset.materialization`,
`market_vault.dataset.materialization_models`, and
`market_vault.dataset.artifact_serialization`).

This contract defines the immutable Dataset artifact materialization layer:
the explicit public entry over one verified
[DatasetOrchestrationResult](dataset_orchestration.md), the re-triggered PR-5
self-validation, the exact final directory layout, the explicit logical-to-
PyArrow schema mapping, the single-file Parquet writer contract and fixed
metadata, the deterministic Feature / Label / Split spec artifacts, the
deterministic non-identity build report, the `DatasetOutputFile` byte facts,
the existing DatasetManifest core integration, the fixed staging path and
write order, `_SUCCESS`-last publication, the atomic same-filesystem
no-overwrite commit, strict existing-build verification with idempotent
return, fail-closed rejection of conflicts, corruption, staging residue, and
symlinks / junctions, empty-Dataset materialization, and the unified
fail-closed error boundary. The materializer consumes only the trusted PR-5
result; it never re-executes Canonical reads, PIT assembly, Feature or Label
execution, or split / purge, and it never recomputes or modifies any existing
identity algorithm.

## 1. Status and scope

Implemented in v0.5.0 PR-6 (`feat: materialize immutable dataset artifacts`)
on top of the shipped Dataset orchestration core (PR-5). This PR turns one
verified `DatasetOrchestrationResult` into one immutable Dataset build
directory with Dataset Parquet, manifest, build report, spec artifacts, and
`_SUCCESS`. It is the first half of ADR 0002 decision 9's materialization
steps (staging, content-hash feeding, manifest, atomic commit); the verified
Dataset reader is PR-7 and the Dataset CLI is PR-8.

## 2. PR-5 handoff

The only trusted input is the `DatasetOrchestrationResult`. The materializer
re-triggers the result's complete self-validation (its `__post_init__` runs
again via `dataclasses.replace(result)`) and then explicitly re-checks:

- `dataset_schema_id(result.schema) == result.dataset_schema_id`;
- `logical_dataset_content_id(result.schema, result.logical_row_mappings())
  == result.logical_dataset_content_id`;
- `dataset_id(result.identity_input) == result.dataset_id`;
- `len(result.rows) == result.diagnostics.logical_row_count`;
- `status` consistent with the row count (EMPTY iff zero rows);
- every `identity_input` identity-bearing fact equals the carried result
  facts (kind, scope, `dataset_as_of`, schema, schema ID, content ID).

No orchestrator invocation, no PIT assembly, no Feature / Label execution,
no split / purge, and no identity recomputation of any existing algorithm is
performed by this layer. The materializer never guesses scope, specs, or
rows from Parquet data.

## 3. Public API

`market_vault.dataset` publicly exports:

- `materialize_dataset_artifacts(result, *, output_root, built_at) ->
  DatasetMaterializationResult` — the only public entry;
- `DatasetMaterializationResult`, `DatasetMaterializationError`;
- `DATASET_MATERIALIZER_VERSION`, `DATASET_BUILD_REPORT_SCHEMA_VERSION`,
  `DATASET_SPEC_ARTIFACT_VERSION`;
- the stable artifact file name constants (`DATASET_PARQUET_FILENAME`,
  `DATASET_MANIFEST_FILENAME`, `DATASET_BUILD_REPORT_FILENAME`,
  `DATASET_SPLIT_SPEC_FILENAME`, `DATASET_SUCCESS_FILENAME`,
  `DATASET_FEATURE_SPECS_DIRNAME`, `DATASET_LABEL_SPECS_DIRNAME`).

Not public: staging helpers, whitelist helpers, hash helpers, Arrow
conversion helpers, the private existing-build validator, mutable payload
builders, cleanup helpers, writer callbacks, and arbitrary serializer
options.

## 4. Explicit `built_at`

`built_at` is required, keyword-only, must be timezone-aware (naive and
`None` fail closed), and is normalized to UTC microseconds. There is no
`datetime.now()` fallback, no clock callback, and no default. `built_at` is a
recorded fact of the manifest and the build report; it never enters
`dataset_id` or any identity. The first materialization of a dataset_id uses
the caller's `built_at`; an existing verified build keeps its original
`built_at` (see section 29).

## 5. Materializer version

`DATASET_MATERIALIZER_VERSION = "market-vault-dataset-materializer-v1"` is
carried on every `DatasetMaterializationResult`, recorded in the Parquet
metadata, and recorded in `build_report.json`. It never enters any identity.

## 6. Exact directory layout

```text
<output_root>/<dataset_id>/
    dataset.parquet
    manifest.json
    build_report.json
    feature_specs/<name>--<version>--<content_sha256>.yaml
    label_specs/<name>--<version>--<content_sha256>.yaml
    split_spec.yaml
    _SUCCESS
```

The only directories are `feature_specs/` and `label_specs/`. Every entry is
a regular file or a regular directory; symlinks, junctions, temporary files,
backup / lock / log files, `.DS_Store`, `Thumbs.db`, `__pycache__`, nested
Dataset directories, and any other entry fail closed (section 31).

## 7. Final directory naming

The final directory name is exactly the lowercase 64-hex `dataset_id`
(`<output_root>/<dataset_id>`). Never: `dataset_id=<id>` prefixes,
timestamped directories, random directory names, `latest` or `current`
pointers, or symlinks. The staging directory is the fixed
`<output_root>/.staging-<dataset_id>`; the staging name is an
implementation fact that never enters any identity.

`DatasetMaterializationResult` artifact paths are **fixed direct children**
of the build directory: `dataset_path` must be exactly
`build_path / "dataset.parquet"`, `manifest_path` exactly
`build_path / "manifest.json"`, `build_report_path` exactly
`build_path / "build_report.json"`, and `success_path` exactly
`build_path / "_SUCCESS"`. A path that merely shares the build directory as
an ancestor — for example `build_path / ".." / "outside" /
"dataset.parquet"` — is rejected, and no path may carry a `.` / `..`
lexical component.

## 8. PyArrow schema mapping

The logical `DatasetSchema` maps explicitly, field order and nullability
preserved exactly, with no schema inference:

```text
string          -> pa.string()
int64           -> pa.int64()
float64         -> pa.float64()
bool            -> pa.bool_()
date32          -> pa.date32()
timestamp_us_utc-> pa.timestamp("us", tz="UTC")
```

Any unknown logical type fails closed. Timestamps are always UTC
microseconds; there are no millisecond / nanosecond timestamps, no object
columns, no dictionary logical types substituting for `string`, no pandas
index, and no implicit local-timezone conversion.

## 9. Parquet writer options

The single `dataset.parquet` is written with fixed options that callers can
never override:

```text
compression="zstd"
use_dictionary=False
write_statistics=True
coerce_timestamps="us"
allow_truncated_timestamps=False
version="2.6"            # Parquet format version
data_page_version="2.0"  # data page version
```

The empty Dataset writes a legal zero-row Parquet with the full schema and
the full metadata.

## 10. Parquet metadata

The Parquet schema metadata carries exactly these UTF-8 keys (values are the
result's facts):

```text
market_vault.dataset_id
market_vault.dataset_schema_id
market_vault.logical_dataset_content_id
market_vault.serialization_format_version
market_vault.row_order
market_vault.materializer_version
```

No other metadata key is present. Metadata never enters the logical
`DatasetSchema`, `dataset_schema_id`, or `dataset_id`.

## 11. Logical versus byte determinism

Identical `result` and `built_at` produce identical spec artifacts, split
artifact, build report, manifest, layout, logical rows, and `dataset_id`.
Because PyArrow is not pinned to a single patch version, byte-identical
Parquet across PyArrow versions is not promised; only the logical content,
schema, `dataset_id`, and verification results are the contract. The
recorded output-file SHA-256 is the hash of the actual materialized bytes,
and byte hashes never enter `dataset_id`.

## 12. Spec artifact canonical format

Feature, Label, and Split artifacts use `DATASET_SPEC_ARTIFACT_VERSION`:

- canonical JSON text that is also valid YAML: UTF-8, `ensure_ascii=True`,
  `sort_keys=True`, compact separators, a trailing newline, no BOM;
- regenerated from the typed models — never copied from caller files, never
  recording original file paths, comments, key order, or newline style;
- never `repr()`, never `yaml.dump` default object tags.

"Dataset spec artifact v1 uses canonical JSON syntax that is also valid
YAML; semantic parsing remains the existing typed spec contract."

## 13. Spec filenames

```text
feature_specs/<name>--<version>--<content_sha256>.yaml
label_specs/<name>--<version>--<content_sha256>.yaml
```

The name, version, and hash come only from the actual SpecPin of each typed
spec. No array indexes, no original input filenames, no paths, no time, and
no randomness. Filename collisions fail closed, and the artifact set is
exactly the result's spec pins: one artifact per Feature / Label pin.

## 14. Split spec artifact

`split_spec.yaml` is the deterministic canonical artifact of the single
`ChronologicalSplitSpec`. It is validated by a strict, exact-field
package-internal parser that reconstructs the identical
`ChronologicalSplitSpec` and the identical existing
`chronological_split_spec_pin`; no second split identity exists. The
`kind` field must be exactly `SPEC_KIND_SPLIT`: any other kind —
`FEATURE`, `LABEL`, empty, unknown, or a non-string value — is rejected
and never silently converted to SPLIT.

## 15. Build report schema

`build_report.json` uses `DATASET_BUILD_REPORT_SCHEMA_VERSION` and records
only stable machine facts:

- `report_schema_version`, `materializer_version`, `dataset_id`,
  `dataset_kind`, `status`, `built_at` (UTC microseconds), `dataset_as_of`;
- `dataset_schema_id`, `logical_dataset_content_id`, `logical_row_count`;
- `orchestration_contract_version`, `row_order`, `manifest_schema_version`,
  `serialization_format`, `serialization_format_version`;
- Feature spec count, Label spec count, Canonical build pin count, Canonical
  row version count;
- completion key counts and every fixed orchestration diagnostic count;
- the stable split facts (`split_spec_content_id`, `split_result_id`);
- the fixed output-layout filenames (stable machine fields only).

Serialization is deterministic: UTF-8, sorted keys, compact separators,
`ensure_ascii=True`, UTC microsecond timestamps, trailing newline. The same
`result` and `built_at` always produce the same bytes; a different
`built_at` may change the bytes but never the `dataset_id`.

## 16. Non-identity facts

`built_at`, output byte hashes, and the whole build report are recorded
facts that never enter `dataset_id` or any identity. The following never
influence `dataset_id`: `output_root`, checkout path, cwd, file mtimes,
`built_at`, Parquet byte hash, build-report byte hash, local timezone,
`created_new_build`, the staging directory name, and process ID.

## 17. `DatasetOutputFile` roles

`manifest.output_files` records exactly `dataset.parquet`, `build_report.json`,
every Feature / Label spec artifact, and `split_spec.yaml`:

```text
dataset.parquet     file_role="dataset"      row_count=<logical rows>
                    content_role="logical_rows"
build_report.json   file_role="build_report" row_count=1
                    content_role=<build-report schema version>
feature spec        file_role="feature_spec" row_count=1
                    content_role=<spec artifact version>
label spec          file_role="label_spec"   row_count=1
                    content_role=<spec artifact version>
split_spec.yaml     file_role="split_spec"   row_count=1
                    content_role=<spec artifact version>
```

Each record's `relative_path`, `byte_size`, and `sha256` come from the actual
staged file (written and closed before hashing; SHA-256 read in 1 MiB
chunks). Ordering follows the existing DatasetManifest rules (sorted by
relative path).

## 18. Manifest construction

The existing core is the only manifest path:

```python
build_dataset_manifest(
    result.identity_input,
    built_at=built_at,
    status=result.status,
    logical_row_count=len(result.rows),
    output_files=records,
)
```

Every identity-bearing, status, count, and serialization fact of the result
must equal the constructed manifest (dataset_id, dataset_kind, schema ID,
content ID, schema, scope, `dataset_as_of`, completion, Canonical pins, row
version IDs, Feature / Label pins, split pin, implementation pins, gap
references, status, row count, serialization contract). The payload is
`serialize_dataset_manifest(manifest)`, re-validated by
`validate_dataset_manifest(payload)`, and the roundtrip manifest must equal
the constructed manifest exactly. The validated payload is what is written
to `manifest.json`; no second manifest payload is ever handwritten.

## 19. Manifest self-hash exclusion

`manifest.json` is never an entry in `output_files` (a self-hash cycle is
impossible); `_SUCCESS` is likewise never an entry. `_SUCCESS` is a commit
marker, not a data artifact.

## 20. Staging path

The staging path is fixed: `<output_root>/.staging-<dataset_id>` — the same
filesystem as the final directory, deterministic, and never identity-bearing.
A pre-existing staging directory is crash residue or a concurrent build:
the call fails immediately, never deletes it, never adopts it, and never
writes into it.

## 21. Write order

1. create or verify `output_root`;
2. existing final directory -> strict existing-build verification
   (section 28), no staging is created;
3. pre-existing fixed staging -> fail closed (section 25);
4. create staging with `exist_ok=False`;
5. `dataset.parquet`;
6. Feature spec artifacts;
7. Label spec artifacts;
8. `split_spec.yaml`;
9. `build_report.json`;
10. compute `DatasetOutputFile` records from the actual files;
11. construct, verify, serialize, and validate the manifest; write
    `manifest.json`;
12. full private verification of the staging directory;
13. write `_SUCCESS` last (empty, regular, not a symlink);
14. re-verify `_SUCCESS`;
15. atomic rename staging -> final;
16. return `created_new_build=True`.

## 22. `_SUCCESS` last

`_SUCCESS` is created after every other artifact, is a regular file, is not
a symlink / junction, and its content is exactly empty bytes. After
`_SUCCESS` is written no other artifact is ever modified in that staging
directory. `_SUCCESS` never enters `manifest.output_files`.

## 23. True no-replace publication

Publication is a **true no-replace atomic directory move**, executed only
after the full staging verification and `_SUCCESS` are complete. The safety
guarantee never comes from an existence pre-check: the atomic primitive
itself refuses an existing destination. `os.replace`, `shutil.move`,
delete-then-rename, overwrite modes, and cross-filesystem fallbacks are
never used, and a plain `os.rename` — which can replace an empty destination
directory on POSIX — is never a fallback.

- **Windows**: the platform's own atomic directory-move semantics apply
  (`MoveFileExW` without `MOVEFILE_REPLACE_EXISTING`); an existing
  destination directory is never replaced and surfaces as
  `FileExistsError` (`ERROR_ALREADY_EXISTS`, winerror 183).
- **Linux**: `renameat2(..., RENAME_NOREPLACE)` is called through the
  standard-library `ctypes` with strict `errno` handling — `EEXIST` /
  `ENOTEMPTY` are destination-exists results; `EINVAL` / `ENOSYS` /
  `ENOTSUP` / `EOPNOTSUPP` and a missing `renameat2` symbol mean the
  primitive is unavailable.
- **Unsupported platforms / filesystems fail closed**: there is no
  equivalent exclusive rename and no safe primitive -> the publication
  fails with `DatasetMaterializationError`; it never degrades to an
  overwriting rename.

A destination-exists result from the atomic primitive (never a
monkeypatched or pre-checked assumption) enters the concurrent-final
handling: an identical verified final returns `created_new_build=False`,
a corrupt or conflicting final fails closed, and the final directory is
never overwritten or deleted.

## 24. No overwrite

The final directory is immutable. If it exists, the call enters strict
existing-build verification; nothing is ever rewritten, repaired, updated,
or deleted. A final directory that appears concurrently is verified in
place (section 27); a conflicting or corrupt one fails closed.

## 25. Staging residue

A fixed staging directory that exists before the call is reported as crash
residue or a concurrent build and fails closed: not deleted, not overwritten,
not adopted. A process killed mid-build leaves residue that the next call
detects; a human must resolve it. No automatic repair, continuation, or
cleanup of pre-existing residue ever happens.

## 26. Ordinary exception cleanup

When this call created the staging directory and an ordinary documented
failure occurs afterwards, only that staging directory is removed; the final
directory never appears partially. The original exception is always the
`__cause__`. Real programming errors are never swallowed and are not
converted (section 34); their staging residue stays for manual inspection.

## 27. Concurrent final appearance

If the final directory appears between the pre-rename check and the rename
(or the rename raises `FileExistsError`), the new final is never overwritten
or deleted. It is strictly verified as an existing build: if it is the same
logical Dataset, this call's staging is removed and the call returns
`created_new_build=False`; if it is corrupt or conflicting, this call's
staging is removed and a `DatasetMaterializationError` is raised.

## 28. Existing-build verification

An existing final directory is never trusted because its name equals
`dataset_id`. The private validator (shared with staging verification)
checks, all fail closed:

1. the directory is a real directory, not a symlink / junction;
2. the exact artifact whitelist (section 31);
3. `_SUCCESS` present, regular, empty bytes, not a symlink;
4. `manifest.json` present and strictly validated;
5. `manifest.dataset_id` equals the directory name (and the expected result);
6. every identity-bearing manifest fact equals the expected result's
   identity input;
7. manifest status and row count equal the result's;
8. **`output_files` equals the authoritative records rebuilt from the
   actual build directory — the full record (`relative_path`,
   `file_role`, `content_role`, `row_count`, `byte_size`, `sha256`),
   normalized by the DatasetManifest sort rule — not only path / hash /
   count**. A correct path/hash with a wrong `file_role` or
   `content_role` is rejected;
9. every listed output file exists;
10. no symlink / junction path components anywhere;
11. byte sizes match the records;
12. SHA-256 matches the records;
13. row counts match (dataset -> logical rows, others -> 1);
14. Parquet schema (field order, Arrow types, nullability) matches;
15. Parquet metadata matches exactly;
16. Parquet rows match the expected logical rows in physical order and
    value, and the recomputed `logical_dataset_content_id` matches;
17. **formal artifacts carry their exact canonical bytes**: `manifest.json`
    equals `serialize_dataset_manifest(validated manifest)`, each Feature
    artifact equals `feature_spec_artifact(expected spec)`, each Label
    artifact equals `label_spec_artifact(expected spec)`,
    `split_spec.yaml` equals `split_spec_artifact(expected split spec)`,
    and `build_report.json` equals
    `build_report_bytes(expected, manifest.built_at)` — any formatting,
    key-order, whitespace, or timestamp-representation difference is
    rejected;
18. Feature spec artifacts parse back to the expected `FeatureSpec` with
    the identical SpecPin;
19. Label spec artifacts likewise;
20. `split_spec.yaml` parses (kind must be exactly SPLIT) to the expected
    `ChronologicalSplitSpec` with the existing split SpecPin;
21. **the parsed build report payload equals `build_report_payload(
    expected, manifest.built_at)` field by field** — every field,
    including all diagnostics, completion counts, split facts, schema /
    content IDs, and the output layout; a rewritten or re-canonicalized
    field is rejected (the report `built_at` binding is part of this
    equality; a different requested `built_at` is ignored by
    construction);
22. no unexpected files or directories.

Any failure raises `DatasetMaterializationError`. Nothing is rewritten,
nothing is deleted, and no partially valid directory is ever adopted.

## 29. Idempotent return

A fully verified existing build returns `created_new_build=False` with the
artifact paths, the existing `output_files` count, and no writes of any
kind (no mtime updates, no report regeneration, no manifest repair). A
different requested `built_at` never conflicts: the existing manifest /
report keep their original `built_at`, the new value is ignored, and the
call never byte-compares "what a new build would have produced" against the
existing artifacts. Idempotency is decided by the existing artifacts' own
strict self-consistency (their manifest, logical identity, and logical
content) — never by requiring the existing Parquet byte hash to equal a
fresh uncommitted serialization.

## 30. Different `built_at` idempotency

A second call with a different `built_at` for an existing valid build:
returns `created_new_build=False`; does not change `dataset_id`, logical
content, identity input, or the final directory; keeps the existing
manifest / report `built_at`; generates no new report; and rewrites nothing.

## 31. Exact whitelist

For one result the expected file set is exactly `dataset.parquet`,
`manifest.json`, `build_report.json`, `split_spec.yaml`, `_SUCCESS`, plus
`feature_specs/<pin-derived filename>` per Feature pin and
`label_specs/<pin-derived filename>` per Label pin; the expected directory
set is exactly `feature_specs` and `label_specs`. Any unexpected entry —
temporary files, `.DS_Store`, `Thumbs.db`, `__pycache__`, extra JSON /
Parquet, old specs, backup / lock / log files, nested Dataset directories —
fails. All files and directories must be regular and must reject symlinks,
Windows junctions, path escapes, and non-regular entries.

## 32. Symlink / junction rejection

The build directory, every entry, `_SUCCESS`, every manifest-listed output
file, **`output_root` itself, and every existing path component from the
existing ancestors down to `output_root`** reject `is_symlink()` and
junction / reparse-point status; a file, FIFO, or other special type in the
path is rejected too.

**The `output_root` safety verification runs immediately after path
coercion — before any final / staging existence query, before any
existing-build access, before the staging-residue judgement, before any
artifact read, and before any directory creation.** The existing-build
idempotency path therefore shares exactly the same link boundary as the
new-build path: an `output_root` that is itself a symlink or Windows
junction, or that has a symlink / junction path component, fails closed
even when a logically valid Dataset already exists at the link target —
a valid existing Dataset never makes a linked output root acceptable. The
existing-build private boundary additionally re-verifies the build
directory's parent chain defensively before any artifact is read, so a
Dataset can never be reached through a link even if the public entry is
bypassed. A second `output_root` verification runs immediately after the
directory is created, detecting path replacement that happened during
creation. The private existing-build validator is not a public Dataset
reader, and its verification of a logically valid Dataset never
re-authorizes access through a linked path.

Junction detection is compatible with **Python 3.11**: where
`Path.is_junction` does not exist (pre-3.12), a Windows junction /
reparse-point is detected through the `FILE_ATTRIBUTE_REPARSE_POINT`
attribute via `ctypes`, and a path whose link status cannot be verified
fails closed. `resolve()` is never used to mask a link. Relative paths are
validated by the existing output relative-path safety validator (no
absolute paths, no backslashes, no `.` / `..`, no Windows drive / root
semantics, no NTFS ADS forms).

## 33. Empty Dataset

A `STATUS_EMPTY` result with zero rows still materializes the complete
directory: a zero-row `dataset.parquet` with the full schema and metadata, a
manifest with `status=EMPTY` and `logical_row_count=0`, the build report,
every Feature / Label spec artifact, `split_spec.yaml`, and an empty
`_SUCCESS`. Hashes are computed, `output_files` are recorded, the Parquet
schema and the zero-row logical content ID are verified, `dataset_id` is
verified, and the empty build supports idempotent return.

## 34. Fail-closed errors

`DatasetMaterializationError` (a `DatasetError` subclass) is the unified
public error boundary. `DatasetError`, `OSError`, `UnicodeError`, JSON
validation errors, documented PyArrow validation / write / read errors
(`pa.ArrowException`), and the documented `TypeError` / `ValueError` /
`KeyError` are wrapped with their `__cause__` preserved. PyArrow
exceptions are converted **explicitly at the public boundary** — an Arrow
failure that surfaces without an internal wrapper (for example during
`pa.array` or `pa.Table.from_arrays` construction) still becomes a
`DatasetMaterializationError` whose `__cause__` is the original Arrow
exception; an already-raised `DatasetMaterializationError` is never
double-wrapped, staging is cleaned up under the ordinary documented
policy, and no partial result is ever returned. Broad `except Exception`
is never used: real programming errors are not hidden, not wrapped, and
not cleaned up silently.

## 35. No hidden current time

There is no `datetime.now()`, no `time.time()`, no clock callback, and no
implicit default anywhere in the materialization path. `built_at` is the
only time fact and it is always explicit, timezone-aware, and normalized to
UTC microseconds.

## 36. No network / OpenD

The materializer performs no network access and no OpenD access. The only
inputs are the in-memory result, the explicit `output_root`, and the
explicit `built_at`. No environment variable decides any result.

## 37. No Dataset reader

The private `_verify_build_directory` validator serves only the
materializer's staging verification and existing-build idempotency
verification against an explicit expected result. It is not a public
Dataset reader, provides no `load_verified_dataset`, scans no "latest"
directory, and offers no data interface for training. The independent,
public, read-only Verified Dataset reader is PR-7.

## 38. No Dataset CLI

No `dataset-build` / `dataset-verify` / `dataset-inspect` commands are added
by this PR (PR-8). No API server and no Python client are implemented.

## 39. PR-7 handoff

After this PR, every artifact of a Dataset build directory is written,
verified, and immutable: `dataset.parquet` (explicit schema and metadata,
single file), `manifest.json` (existing core, byte facts recorded),
`build_report.json` (recorded facts), spec artifacts (typed, pinned),
`split_spec.yaml`, and `_SUCCESS` (commit marker). PR-7 implements one
independent public read entry point that re-verifies a committed directory
fail closed without writing anything.

## 40. MarketVault / quant-project boundary

This contract lives entirely inside the MarketVault repository and its
published Dataset contracts. It implements no strategy and no quant logic
beyond the documented deterministic dataset-building pipeline, and nothing
from other projects or repositories is imported, read, or modified.

## Explicit boundary statements

- Output hashes never enter `dataset_id`.
- `manifest.json` never records its own hash.
- `_SUCCESS` never enters `output_files`.
- `build_report.json` never enters any identity.
- An existing valid Dataset is never judged conflicting because a new
  `built_at` differs.
- Existing bytes and freshly generated candidate bytes never need to be
  equal.
- Existing artifacts must be strictly self-consistent against their own
  manifest.
- The PR-6 private validator is not a public reader.
- The package version remains **0.4.0** through PR-9 of the v0.5.0
  sequence.
