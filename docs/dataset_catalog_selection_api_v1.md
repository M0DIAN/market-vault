# Explicit Dataset Catalog Selection API V1

Status: POST_V0_7_CURRENT_MAIN_EXTENSION

```text
DESIGN_APPROVED=false
RUNTIME_IMPLEMENTED=false
IMPLEMENTATION_AUTHORIZED=false
```

This document prospectively defines the smallest formal Python API for
selecting exactly one entry from an already verified Dataset Catalog
snapshot. It is design authority only. It does not implement the API and
does not change any released artifact, runtime behavior, identity, schema,
or command output.

## 1. Historical boundary

The v0.6.0 Dataset Catalog contract shipped without a Python selection API.
The formally released v0.7.0 `ArtifactClient` shipped with exactly these
three public business methods:

```text
load_canonical_build
load_dataset
load_dataset_catalog
```

Those release facts remain historical truth. This proposal is a
`POST_V0_7_CURRENT_MAIN_EXTENSION`; it must not be described as part of the
already published v0.7.0 artifacts. Package version `0.7.0` is unchanged by
this design.

## 2. Purpose and result

The complete V1 operation is:

```text
already verified Dataset Catalog snapshot
+ explicit exact dataset_id
-> one exact verified Catalog entry
```

The future formal function is:

```python
select_verified_dataset_catalog_entry(
    catalog,
    dataset_id,
)
```

It will live in:

```text
market_vault.dataset.dataset_catalog_selection
```

After implementation it will be exported as:

```text
market_vault.dataset.select_verified_dataset_catalog_entry
```

It will not be exported from top-level `market_vault`.

## 3. Input trust boundary

`catalog` must be a `VerifiedDatasetCatalogSnapshot`. Selection begins only
after `load_verified_dataset_catalog(...)` has established artifact trust.
A wrong catalog object type fails closed with
`DatasetCatalogSelectionError`.

The selector is pure and in-memory. It must not:

- accept `snapshot_dir`;
- call `load_verified_dataset_catalog`;
- open, parse, hash, stat, or otherwise access snapshot files;
- parse `catalog.json` or `manifest.json`;
- read settings or current time;
- access OpenD or the network;
- mutate the supplied snapshot object or any entry.

The verified reader remains the sole artifact-validation authority. The
selector validates only its own call shape and exact-match cardinality; it
does not independently re-verify the snapshot's established invariants.

## 4. Exact selector

V1 has one selector: `dataset_id`.

It is required, has type `str`, and must match exactly 64 lowercase
hexadecimal characters. Matching is exact equality against
`entry.dataset_id`.

The selector provides no:

- prefix, substring, fuzzy, or case-folded lookup;
- first, last, or entry-order fallback;
- latest selection or `built_at` ranking;
- path, `content_id`, scope, or filter lookup;
- Dataset Catalog list/query API.

Malformed selectors fail closed with `DatasetCatalogSelectionError`. The
selector never normalizes an invalid selector into a valid one.

## 5. Content identity model

```text
CONTENT_ID_MODEL=MODEL_A
```

`dataset_id` is the only selector. `content_id` is neither required nor
optional input and is never an alternative selector. There is no
`expected_content_id` argument in V1.

`dataset_id` already binds the Dataset's formal identity, including its
logical content identity. The verified snapshot has already validated the
entry's `content_id` against the Dataset Catalog facts. Requiring a second
identity argument would duplicate already verified information without
improving V1 selection safety.

## 6. Match cardinality

The formal result is:

```text
exactly one match -> return that entry
zero matches      -> DatasetCatalogSelectionError
more than one     -> DatasetCatalogSelectionError
```

`VerifiedDatasetCatalogSnapshot` already guarantees unique `dataset_id`
values. The multiple-match branch is a defensive selection invariant, not a
second Catalog validation pass. There is no `None`, `Optional`, silent miss,
or fallback result.

## 7. Return contract

The selector returns the exact existing
`DatasetCatalogSnapshotEntryRecord` instance contained in
`catalog.entries`.

```text
RETURN_OBJECT_IDENTITY_PRESERVED=true
```

It creates no copy, dict, wrapper, `SelectionResult`, or replacement model.
It does not load a Dataset.

## 8. Error contract

The future public error is:

```python
class DatasetCatalogSelectionError(DatasetCatalogError):
    ...
```

It covers wrong catalog input type, malformed `dataset_id`, zero matches,
and the defensive duplicate-match invariant. It is distinct from
`DatasetCatalogArtifactValidationError`, which continues to mean artifact
verification failure.

Error text at the formal selector boundary must be Python/API-neutral and
must not mention CLI options. `ArtifactClient` propagates the exact formal
selection exception unwrapped.

## 9. Verified-object invariants consumed

The selector consumes, but does not re-establish, the verified snapshot's
existing guarantees:

- entry type and immutable tuple shape;
- strict `dataset_id` format, ordering, and uniqueness;
- entry `content_id` validity;
- Dataset facts and Catalog content identity;
- physical snapshot integrity.

Manually forged or internally inconsistent verified objects remain a model
and reader concern. The selector must not create a parallel artifact trust
path.

## 10. Recorded build path

```text
RECORDED_BUILD_PATH_SEMANTICS=HISTORICAL_TEXT_ONLY
RECORDED_PATH_ACCESS=false
AUTOMATIC_RECORDED_BUILD_PATH_RESOLUTION=false
AUTOMATIC_DATASET_LOAD=false
```

Selection returns an entry only. The selector must never convert
`recorded_build_path` to a `Path`, resolve it, stat it, test its existence,
open it, or pass it to `load_verified_dataset`.

A caller that intends to load a physical Dataset must separately call
`ArtifactClient.load_dataset(build_dir)` with an explicit live path supplied
by that caller. The recorded historical path is not such authority.

## 11. ArtifactClient extension

The future fourth public business method is:

```python
ArtifactClient.select_dataset_catalog_entry(
    catalog,
    dataset_id,
)
```

It imports the formal selector only inside the method body, passes the exact
caller-supplied catalog object and `dataset_id` value unchanged, returns the
exact selector result unchanged, and propagates
`DatasetCatalogSelectionError` unwrapped.

The existing constructor remains zero-argument and stateless with
`__slots__ = ()`. The method adds no settings, filesystem, OpenD, network,
current-time, or cwd-derived behavior. The existing three load methods and
their signatures remain unchanged.

## 12. One authority shared with the CLI

The future implementation architecture is:

```text
dataset-catalog-show
-> load_verified_dataset_catalog(...)
-> select_verified_dataset_catalog_entry(...)
-> existing JSON renderer
```

The current hand-written CLI lookup loop must be removed when the formal
selector is implemented. CLI code and Python API code must not remain two
independent selection authorities.

`dataset-catalog-show` retains its current arguments, exact-ID behavior,
success JSON schema, failure exit codes, and stdout/stderr contract.

The formal `DatasetCatalogSelectionError` uses API-neutral wording. At the
CLI boundary, a selection miss may be translated into the existing
`DatasetCatalogCLIError` text so the command's established external contract
stays byte/semantically compatible. That presentation translation is not a
selection authority. `dataset-catalog-list` remains unchanged.

## 13. Explicit non-goals

```text
EXACT_SINGLE_SELECTION_ONLY=true
LATEST_SELECTION=false
SNAPSHOT_ROOT_SCAN=false
DATASET_ROOT_SCAN=false
RECORDED_PATH_ACCESS=false
CURRENT_TIME_DEPENDENCY=false
SETTINGS_DEPENDENCY=false
OPEND_DEPENDENCY=false
NETWORK_DEPENDENCY=false
```

V1 does not add Python equivalents of Catalog list filters, pagination, a
general query language, filesystem discovery, Dataset loading, SQL/DuckDB,
an API server, QML, or production mutation.

## 14. Identity and artifact compatibility

The future implementation must preserve:

```text
DATASET_CATALOG_SCHEMA_CHANGE_REQUIRED=false
DATASET_ID_CHANGE_REQUIRED=false
CATALOG_CONTENT_ID_CHANGE_REQUIRED=false
SNAPSHOT_ID_CHANGE_REQUIRED=false
ARTIFACTCLIENT_CONSTRUCTOR_CHANGE_REQUIRED=false
```

No Catalog snapshot or Dataset is rewritten. No artifact migration is
required.

## 15. Deferred implementation surface

The expected later implementation is limited to:

- `src/market_vault/dataset/dataset_catalog_selection.py`;
- `src/market_vault/dataset/__init__.py`;
- `src/market_vault/artifact_client.py`;
- `src/market_vault/dataset/dataset_catalog_cli.py`;
- `scripts/check_release.py`;
- focused selector, ArtifactClient, CLI, and release-checker tests;
- the current user-facing guide and current-main usage documentation.

The release checker must change atomically with the actual fourth public
method. It is deliberately unchanged by this design-only PR:

```text
RELEASE_CHECKER_CHANGE_DEFERRED_TO_IMPLEMENTATION=true
```

Historical v0.7.0 audit, direction, usage, and release documents remain
historically accurate and must not be rewritten to imply that the published
v0.7.0 artifacts contained this extension.

## 16. Mandatory implementation tests

Future implementation must prove:

- an exact valid `dataset_id` returns the same entry object by identity;
- missing, uppercase, short, long, and non-hex IDs fail closed;
- prefix and substring values fail closed;
- there is no latest, first, last, or entry-order fallback;
- the selector performs no filesystem or recorded-path access;
- the selector uses no settings, current time, OpenD, or network;
- the supplied Catalog and its entries remain unchanged;
- the reader remains the sole artifact-validation authority;
- the ArtifactClient import is method-local, its result and error propagate
  unchanged, and its constructor remains stateless;
- all three existing ArtifactClient load methods remain unchanged;
- `dataset-catalog-show` delegates selection to the formal selector while
  retaining its success and missing-ID contracts;
- `dataset-catalog-list` remains unchanged;
- the release checker is atomically updated for the exact fourth method and
  continues to reject unauthorized convenience/query/discovery methods;
- the historical v0.7.0 release contracts remain historically accurate.

## 17. Design status

This document authorizes no implementation or merge. Independent review is
required before this proposal may become approved design authority.

```text
DESIGN_ONLY=true
DESIGN_APPROVED=false
RUNTIME_IMPLEMENTED=false
IMPLEMENTATION_AUTHORIZED=false
MERGE_AUTHORIZED=false
VERSION=0.7.0
```

The frozen V1 contract summary is:

```text
SELECTION_AUTHORITY_FUNCTION=select_verified_dataset_catalog_entry
SELECTION_MODULE=market_vault.dataset.dataset_catalog_selection
INPUT_TYPE=VerifiedDatasetCatalogSnapshot
SELECTOR_MODEL=EXACT_DATASET_ID_ONLY
CONTENT_ID_MODEL=MODEL_A
RETURN_TYPE=DatasetCatalogSnapshotEntryRecord
RETURN_OBJECT_IDENTITY_PRESERVED=true
ERROR_TYPE=DatasetCatalogSelectionError
ERROR_BASE=DatasetCatalogError
ARTIFACTCLIENT_FUTURE_METHOD=select_dataset_catalog_entry
FORMAL_DATASET_EXPORT=true
TOP_LEVEL_MARKET_VAULT_EXPORT=false
CLI_SHOW_REUSE_REQUIRED=true
CLI_OUTPUT_CONTRACT_CHANGED=false
EXACT_SINGLE_SELECTION_ONLY=true
LATEST_SELECTION=false
RECORDED_PATH_ACCESS=false
AUTOMATIC_DATASET_LOAD=false
READER_REMAINS_SOLE_VALIDATION_AUTHORITY=true
SECOND_TRUST_PATH_CREATED=false
DATASET_CATALOG_SCHEMA_CHANGE_REQUIRED=false
DATASET_ID_CHANGE_REQUIRED=false
CATALOG_CONTENT_ID_CHANGE_REQUIRED=false
SNAPSHOT_ID_CHANGE_REQUIRED=false
RELEASE_CHECKER_CHANGE_DEFERRED_TO_IMPLEMENTATION=true
```
