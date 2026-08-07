# MarketVault v0.6.0 Integrated Acceptance

Status: accepted (PR-8)

This document records the integrated acceptance of the v0.6.0 product
capabilities — the Deterministic Sample Generator and the immutable Dataset
Catalog — working together end to end, plus the integrated
determinism / corruption / recovery / portability / security / usability
hardening that proves it. It is the acceptance documentation for PR-8 and
the formal gate for v0.6.0 release preparation (PR-9). PR-8 is
tests / docs / CI only: no production code is changed, no new CLI command
is added, and the package version stays 0.5.1 throughout PR-8. PR-8 does
not release v0.6.0; the release happens only in PR-9.

## 1. Scope of integrated acceptance

V0.6.0 ships exactly two product capabilities; integrated acceptance
proves that they work together through the full offline chain, not just
independently:

```text
verified Canonical build
→ market-vault sample-generate --plan <PATH>
→ generated market-vault-dataset-build-plan-v1 (ordinary, unchanged)
→ market-vault dataset-build --plan <PATH>
→ verified Dataset build
→ market-vault dataset-catalog-build
→ immutable Catalog snapshot
→ market-vault dataset-catalog-verify / -list / -show
```

Both a COMPLETE chain (real bars produce real requests, a COMPLETE Dataset,
and a COMPLETE Catalog entry) and an EMPTY chain (a legal empty Canonical
build produces zero requests, an EMPTY Dataset, and an EMPTY Catalog entry;
EMPTY is a success, never a failure, and no bar is ever fabricated) are
accepted.

Accepted in PR-8:

- deterministic identity across process boundaries and directories
  for the same verified artifact and semantic inputs;
- explicit classification of the PyArrow 24.0.0 / 25.0.0 cross-writer
  physical-provenance differences (identity equality across writer
  versions is never claimed);
- fail-closed corruption handling at every stage with no repair;
- the recovery contract (recovery is not repair);
- the static reference artifact and the PyArrow 24.0.0 / 25.0.0
  portability audit;
- the security matrix (symlinks / reparse points, ``.`` / ``..``, wrong
  basenames, ambiguous duplicates);
- the read-only proof for verify / list / show;
- the usability / CLI failure JSON contract.

Not in scope of PR-8 (fixed in the direction): product code changes, new
CLI commands, schema changes, identity algorithm changes, dependency
modernization, and the v0.6.0 version bump (PR-9 only).

## 2. Product baseline

- package version stays 0.5.1 through PR-8; not released as 0.6.0;
- `pyproject.toml` declares `pyarrow>=16` (unchanged, never pinned to a
  writer version);
- Python 3.11 and Python 3.14 CI matrix (unchanged);
- all acceptance tests are fully offline: no settings, no OpenD, no
  network, no current time;
- the acceptance surface is `tests/v060_acceptance_helpers.py`,
  `tests/test_v060_portability.py`, `tests/test_v060_integrated_e2e.py`,
  and the static fixture bundle under
  `tests/fixtures/v060_portability/`.

## 3. Integrated chains

Both chains are executed as real subprocess CLI invocations (in-process
where the contract under test is the engine itself), on a decoded static
reference artifact plus locally written spec files.

COMPLETE chain acceptance facts (verified by
`test_complete_chain_all_six_cli_steps`):

- `sample-generate` reproduces the frozen generation content id
  (`FIXTURE_GENERATION_ID`) for the core chain and writes a build plan
  whose bytes reproduce the frozen relative-plan sha256 for the CLI chain;
- `dataset-build` produces a COMPLETE verified Dataset whose
  `dataset_id` / `logical_dataset_content_id` match across runs and
  directories;
- `dataset-catalog-build` produces one immutable snapshot whose
  `snapshot_id` is 64-lowercase-hex and whose directory name equals the
  snapshot id;
- `dataset-catalog-verify` returns `VERIFIED` with the same
  `snapshot_id` / `catalog_content_id`;
- `dataset-catalog-list` with exact filters
  (`--status COMPLETE --dataset-kind SUPERVISED`) returns exactly the one
  built Dataset; the stored facts are `dataset_kind: SUPERVISED`,
  `status: COMPLETE`;
- `dataset-catalog-show` by exact `dataset_id` returns the lossless facts
  record including the historical recorded build path (never followed).

EMPTY chain acceptance facts (verified by `test_empty_chain_through_catalog`):

- zero requests, `dataset_status: EMPTY`, `logical_row_count: 0`,
  verified Dataset `status == EMPTY`, Catalog entry `status == EMPTY`;
- `dataset-catalog-list --status EMPTY` matches the entry and
  `--status COMPLETE` matches zero.

## 4. Determinism matrix

| # | Property | Proved by |
|---|----------|-----------|
| A | generation: two identical generation plans in two different working roots produce byte-identical plans and the same generation content id | `matrix_a` |
| B | Dataset identity is cwd-independent: two builds of the same plan from different working directories produce identical plan bytes, the same `dataset_id` / `logical_dataset_content_id`, and different `build_path` values (path is metadata, never identity) | `matrix_b` |
| C | Catalog content identity: the same verified Dataset indexed into two different `output_root`s produces the same `catalog_content_id` and the same `snapshot_id` | `matrix_c` |
| D | snapshot id changes with a relocated Dataset copy while catalog content id stays identical (`snapshot_id = f(catalog_content_id, dataset_count, built_at, catalog_file_byte_size, catalog_file_sha256)`; output root and paths never enter it) | `matrix_d` |
| E | a copied snapshot directory verifies identically with unchanged ids and logical content (relocation is a first-class supported state) | `matrix_e` |

Determinism here means: same verified inputs + same explicit plan +
same writer version ⇒ same bytes and same identities. The portability
section states precisely what happens when the writer version differs.

## 5. Corruption cascade

Every stage fails closed with exit 1, empty stdout, a single `result:
FAILED` JSON error on stderr, and no repair, no partial adoption, no
deletion of committed artifacts:

- Canonical corruption — corrupted `manifest.json`, `resolution.jsonl`,
  or bars Parquet bytes, a deleted `_SUCCESS`, or a deleted member: the
  verified reader raises, and the CLI chain (`sample-generate`,
  `dataset-build`, `dataset-catalog-build`) fails; the corruption is
  observed but never repaired;
- generation-plan corruption — a UTF-8 BOM, duplicate keys, or an unknown
  field: strict-schema rejection at load;
- build-plan corruption — BOM / duplicate keys / unknown field in a
  dataset-build plan: strict-schema rejection at load;
- Dataset corruption — corrupted `dataset.parquet` bytes: the verified
  Dataset reader raises and `dataset-catalog-build` fails;
- Catalog snapshot corruption — corrupted `catalog.json`, `manifest.json`,
  or a deleted `_SUCCESS`, for each of verify / list / show: fail closed,
  no repair.

The corruption-cascade tests snapshot the tree (per-entry size / mtime /
sha256) after the corruption and assert it is untouched after the failed
command: a failure never rewrites, deletes, or "repairs" anything.

## 6. Recovery contract

Recovery is not repair. The contract:

- a failed step cleans only its own partial staging output: a failed
  `sample-generate` leaves no partially written plan, a failed
  `dataset-build` leaves no build directory (staging removed, final never
  created), a failed `dataset-catalog-build` leaves no snapshot;
- a committed final artifact is never deleted by a later step or by a
  rerun: rerunning an identical build is idempotent
  (`created_new_build: false`, `created_new_snapshot: false`, tree
  untouched);
- a rerun after a failure succeeds because the failure left no residue;
- foreign staging directories are never adopted: an exact
  `.staging-<snapshot_id>` of the materializer fails closed; a
  differently-named `.staging-*` is foreign residue and is ignored
  (untouched, build still succeeds);
- recovery never fabricates data: an EMPTY chain is the only "zero" state,
  produced by the engine, never by skipping or deleting.

## 7. Portability: PyArrow 24.0.0 vs 25.0.0 audit

The artifact writers are PyArrow, and the supported dependency boundary is
`pyarrow>=16` (unchanged in `pyproject.toml`). Integrated acceptance
audits the two writer versions that currently resolve at the boundary of
the tested range — PyArrow 24.0.0 and PyArrow 25.0.0 — in isolated
temporary virtual environments, and asserts the audited writer version in
CI (`portability-pyarrow24` job installs `pyarrow==24.0.0`).

The audit result (logical content and identity values):

| Observable | PyArrow 24.0.0 vs 25.0.0 |
|------------|---------------------------|
| logical rows | EQUAL |
| logical_source_rows_hash | EQUAL |
| source Parquet physical bytes | DIFFER |
| physical_snapshot_hash | DIFFER |
| canonical_bar_key | EQUAL |
| canonical_row_version_id | DIFFER |
| canonical_content_id | DIFFER |
| resolution_content_id | DIFFER |
| gap_content_id | EQUAL |
| canonical_build_id | DIFFER |
| generation_content_id | DIFFER |

Interpretation, recorded as the acceptance wording: the
upstream source / curated snapshot Parquet bytes are identity-bearing
physical source provenance. Their digest feeds `physical_snapshot_hash` /
`source_snapshot_content_hash` and therefore the row-version and
downstream provenance/version identity chain. A different but
logical-content-equal writer therefore changes physical source
provenance and build / generation identity values while leaving logical
content (`logical_source_rows_hash`, `canonical_bar_key`,
`gap_content_id`) equal. The serialized byte layout / serializer
metadata of the Canonical output Parquet artifact itself does not
independently enter Canonical logical identity. This is not "PyArrow
changed the Canonical serializer": the Canonical serializer and identity
algorithms are unchanged; the physical bytes of the upstream source /
curated snapshot are simply part of the formal identity input, exactly
as designed.

The eight required acceptance statements for portability:

1. logical rows are EQUAL between the two audited writers;
2. source Parquet physical bytes DIFFER;
3. `physical_snapshot_hash` DIFFERs and `logical_source_rows_hash` stays
   EQUAL;
4. `canonical_bar_key` stays EQUAL;
5. `canonical_row_version_id`, `canonical_content_id`, and
   `resolution_content_id` DIFFER;
6. `gap_content_id` stays EQUAL;
7. `canonical_build_id` and `generation_content_id` DIFFER;
8. the frozen regression values reproduce unchanged on both writers via
   the static reference artifact (no re-baselining on writer change);
   the upstream source snapshot physical bytes are formal
   provenance/version identity input.

## 8. Static reference artifact

The static reference artifact is the base64-text bundle
`tests/fixtures/v060_portability/canonical_fixture.b64` (TSV lines
`<POSIX path>\t<byte size>\t<sha256>\t<base64>`; repo hygiene forbids
tracked binary artifacts), produced once at PR-8 time by PyArrow 25.0.0,
with provenance recorded in `fixture_metadata.json`
(`produced_by_pyarrow_version: 25.0.0`, `canonical_build_id`,
`frozen_generation_content_id`, `frozen_relative_plan_sha256`,
member list, logical content facts).

The decoder applies strict member checks (no `.`, `..`, empty parts,
leading `/`, drive prefixes, or OS separators) and verifies every member's
byte size and sha256; the artifact is read (never re-written) by the
tests, and reproduces, unchanged, on both audited PyArrow runtimes /
readers — PyArrow 24.0.0 and PyArrow 25.0.0:

- the frozen generation content id `f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb3`
  (core chain, CORE split payload);
- the frozen relative build-plan sha256 `78cd9e895ee966722c83db8d5388a49c635b8fd448fe8de796e2b56dcebf964b`
  (CLI chain, CLI split payload, relative plan paths).

This proves the two audited runtimes; it does not claim every version in
the supported `pyarrow>=16` range or future versions. The two hard-coded
frozen regression tests migrated in PR-8
(`test_identity_frozen_fixture`,
`test_relative_fixture_build_plan_bytes_unchanged_from_old_head`) now read
the artifact through the same decoder, so the regression values are
frozen in exactly one place and proven on both audited runtimes / readers
by the CI `portability-pyarrow24` job.

## 9. Security matrix

All fail closed (exit 1, `result: FAILED`, no access through the alias):

- symlinked / junctioned (reparse-point) Canonical build directories,
  generation plans, Dataset candidate directories, and Catalog snapshot
  directories are rejected; where the OS cannot create the alias the test
  is skipped explicitly (never silently);
- `.` and `..` lexical components are rejected in generation-plan paths,
  `--dataset-root`, and `--snapshot-dir` (the CLI path coercion rejects
  them at the boundary);
- wrong basenames are rejected: a renamed Canonical build directory, a
  renamed Dataset directory, and a renamed Catalog snapshot directory do
  not match their contract location and fail;
- ambiguous duplicate Dataset location (the same `dataset_id` observed at
  both candidate locations) fails with the explicit
  "ambiguous duplicate Dataset location" error — the builder never picks
  a winner;
- `_SUCCESS` semantics, layered per contract:
  - Canonical build `_SUCCESS`: exists, regular file, link-free; the
    current Canonical reader does not bind content bytes (a deleted
    `_SUCCESS` fails; content is not part of the check);
  - Dataset Catalog snapshot `_SUCCESS`: exists, regular non-link file,
    bytes exactly empty; a non-empty `_SUCCESS` fails closed;
- a stored `None` requested_session never matches a string filter; no
  implicit case folding, no fuzzy search.

## 10. Read-only proof

`dataset-catalog-verify`, `dataset-catalog-list`, and
`dataset-catalog-show` are strictly read-only:

- per-entry (size, mtime_ns, sha256) snapshots of both the Catalog
  snapshot tree and the Dataset tree are byte-identical before and after
  each command;
- after the indexed Dataset directory (and the canonical source tree) is
  deleted, verify / list / show still succeed: the recorded build path is
  historical metadata only, never followed, and no tree is ever touched;
- the verified reader never reloads the Dataset; the Catalog snapshot is
  the sole trust boundary for discovery and query.

## 11. Usability and CLI failure contract

Every failing CLI command returns exit code 1, writes nothing to stdout,
and writes exactly one JSON object to stderr with the fixed keys
`{result_schema_version, cli_contract_version, command, result: FAILED,
error_type, error}`; `error_type` ends with `CLIError`. Success payloads
carry the fixed contract keys and the command's result verb
(`SUCCESS` / `VERIFIED` / `LISTED` / `SHOWN`). The acceptance suite
asserts the exact failure field set for the canonical, generation,
build-plan, Dataset, Catalog-build, and Catalog-read failure paths.

## 12. CI

The existing matrix stays exactly `["3.11", "3.14"]`. A new
`portability-pyarrow24` job (ubuntu-latest, Python 3.11) installs
`pyarrow==24.0.0` explicitly after the dev install, asserts the installed
version, runs the audited portability tests, the canonical reader and
frozen regression surface, and then the full offline suite under
PyArrow 24.0.0. The package job requires both the test job and the
portability job, and marks the integrated acceptance with the
`PR8_INTEGRATED_ACCEPTANCE_OK` marker once green.

## 13. Test inventory and how to run

```text
python -m pytest tests/test_v060_portability.py -q        # 10 tests
python -m pytest tests/test_v060_integrated_e2e.py -q     # integrated suite
python -m pytest tests/test_sample_generation_core.py -q  # migrated frozen core
python -m pytest tests/test_sample_generation_cli.py -q   # migrated frozen CLI
python -m pytest -q                                       # full offline suite
```

PyArrow 24.0.0 isolated audit (local):

```text
python -m venv <tmp>/venv24 && <tmp>/venv24/... pip install -e ".[dev]"
<tmp>/venv24/... pip install "pyarrow==24.0.0"
<tmp>/venv24/... python -c "import pyarrow; assert pyarrow.__version__ == '24.0.0'"
<tmp>/venv24/... python -m pytest tests/test_v060_portability.py -q
<tmp>/venv24/... python -m pytest -q
```

## 14. Version boundary and PR-9 gate

- The package version stays 0.5.1 through PR-8; `pyproject.toml` and
  `src/market_vault/_version.py` are untouched.
- No tag, no GitHub Release, no PyPI publication; v0.6.0 is not released
  and PR-8 does not release it.
- PR-9 (v0.6.0 release preparation, the only PR that bumps the version)
  has not started.
- `scripts/check_release.py` enforces this boundary; its mutation guards
  fail the release check if the acceptance doc disappears, the release
  claim is false, `pyarrow>=16` is pinned, the CI matrix changes, the
  `portability-pyarrow24` job is missing or not pinned to
  `pyarrow==24.0.0`, the frozen fixture values change, the byte-identical
  cross-writer claim is made, or PR-9 is falsely started or released.

## 15. Acceptance result and gates

All acceptance gates passed at PR-8 time on the PR branch:

- `tests/test_v060_portability.py`: 10/10 passing on PyArrow 25.0.0 and
  on the PyArrow 24.0.0 audit environment;
- `tests/test_v060_integrated_e2e.py`: 46 passing, 1 explicit skip (the
  alias-creation test on a host that cannot create symlinks or junctions);
- both migrated frozen regression tests pass on PyArrow 25.0.0 and on the
  PyArrow 24.0.0 audit environment;
- the full offline suite passes on both PyArrow 25.0.0 (the normal
  matrix) and PyArrow 24.0.0 (the `portability-pyarrow24` CI job and the
  local isolated audit): PyArrow 24.0.0 full suite **PASS, 0 failed**;
- historical note: the initial PR-8 audit exposed two pre-existing
  test-only `pq.read_table(single-file)` Hive-partition-inference
  failures in `tests/test_pit_sample_assembly.py`; PR-8 corrected those
  test helpers to `pq.ParquetFile(...).read()`. Production code remained
  unchanged;
- full offline suite passes, `compileall` passes, repo hygiene passes
  (no forbidden tracked artifacts), `git diff --check` is clean,
  `scripts/check_release.py` passes, `market-vault --version` reports
  0.5.1, and the production `src/` tree diff against the PR-8 base is
  exactly zero.

V0.6.0 is accepted for PR-9 release preparation. PR-9 will bump the
package version to 0.6.0, update the release documentation, and perform
the release smoke; PR-9 has not started.
