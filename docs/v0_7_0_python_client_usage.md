# MarketVault v0.7.0 Python Client Usage Guide

> **Unreleased development documentation.** This guide describes the
> unreleased v0.7 ArtifactClient under active development. The package
> metadata remains **0.6.1 through PR-5** under the frozen version policy.
> The formal v0.6.1 GitHub Release artifacts do **NOT** contain
> `ArtifactClient`. **v0.7.0 is not released yet.**

The `ArtifactClient` is the settings-independent, read-only Python client
for verified immutable artifacts. It delegates every read verbatim to the
formal verified readers, so the reader validation authority, the error
classes, and the returned verified object types are exactly the formal
ones. The client itself performs no artifact parsing, no validation, no
discovery, and no writes.

Public business methods (exactly three):

```python
ArtifactClient()
ArtifactClient.load_canonical_build(build_dir)
ArtifactClient.load_dataset(build_dir)
ArtifactClient.load_dataset_catalog(snapshot_dir)
```

**Every artifact path is EXPLICIT.** The client never looks up `latest`,
never scans or discovers artifacts, never derives a root from settings,
an environment variable, or the current working directory, and never
reads the current time. You always pass the exact final artifact
directory yourself.

## A. Python — verified Canonical read

```python
from pathlib import Path
from market_vault import ArtifactClient

client = ArtifactClient()

canonical = client.load_canonical_build(
    Path(r"D:\explicit\canonical\build")
)

print(canonical.canonical_build_id)
print(canonical.status)
print(len(canonical.bars))
```

`load_canonical_build(build_dir)` delegates verbatim to
`market_vault.canonical.reader.load_verified_canonical_build(build_dir)`
and returns the exact formal `VerifiedCanonicalBuild`. The path must be
the final Canonical build directory
(`.../canonical/dataset=market_bars_canonical/<canonical_build_id>`),
never its parent and never a `latest` path.

## B. Python — verified Dataset read

```python
dataset = client.load_dataset(
    Path(r"D:\explicit\dataset\build")
)

print(dataset.dataset_id)
print(dataset.status)
print(len(dataset.rows))
```

`load_dataset(build_dir)` delegates verbatim to
`market_vault.dataset.reader.load_verified_dataset(build_dir)` and
returns the exact formal `VerifiedDatasetBuild`. The path must be the
final Dataset build directory (`<output_root>/<dataset_id>`), never
`output_root` itself.

## C. Python — verified Dataset Catalog read

```python
catalog = client.load_dataset_catalog(
    Path(r"D:\explicit\catalog\snapshot")
)

print(catalog.snapshot_id)
print(catalog.catalog_content_id)
print(catalog.dataset_count)
```

`load_dataset_catalog(snapshot_dir)` delegates verbatim to
`market_vault.dataset.dataset_catalog_reader.load_verified_dataset_catalog(snapshot_dir)`
and returns the exact formal `VerifiedDatasetCatalogSnapshot`. The path
must be the final immutable snapshot directory
(`<output_root>/<snapshot_id>`), named exactly the 64-hex `snapshot_id`.

## Jupyter consumer example

Inside a Jupyter notebook, after the verified Dataset read above:

```python
import pandas as pd

columns = [field.name for field in dataset.schema.fields]
df = pd.DataFrame(dataset.rows, columns=columns)

df.head()
```

Be crystal clear about what this is and what it is not:

- The ArtifactClient verification happened BEFORE the DataFrame
  construction: `dataset` is the formal `VerifiedDatasetBuild` object
  produced by the verified reader.
- The DataFrame is an in-memory consumer representation of the already
  verified rows. It is not a re-verification and it carries no trust of
  its own.
- pandas is not a second artifact verification path. DataFrame
  construction is consumer-side data handling, outside the
  ArtifactClient trust contract.
- Do NOT parse `dataset.parquet` directly to bypass the verified reader.
  Reading the Parquet file yourself would create a second, unverified
  artifact interpretation and is never part of the supported usage.
- Do NOT write back into the artifact directory. Artifacts are
  immutable; nothing ever writes through ArtifactClient, and consumer
  code must not mutate artifact files either.

## ML-consumer handoff

The verified Dataset can be consumed downstream by user-owned ML code:

- the verified `dataset.rows` and `dataset.schema` carry the actual
  feature/label values and their typed schema;
- `dataset.split_result` carries the explicit chronological
  train/validation/test assignment recorded by the split spec;
- `dataset.manifest_payload` carries the pinned FeatureSpec / LabelSpec /
  split spec metadata recorded at build time.

Consumers must choose columns and splits EXPLICITLY using the verified
Dataset schema / spec / split metadata. MarketVault v0.7:

- does NOT train models;
- does NOT do automatic feature inference;
- does NOT do target inference;
- does NOT invent a train/test policy — no policy is applied by
  ArtifactClient or the verified readers;
- adds NO sklearn / PyTorch / TensorFlow dependency.

ML training and model evaluation are user-owned work that runs on the
verified facts; none of it is implemented by MarketVault v0.7.

## Formal error examples

All reads fail closed through the existing formal reader error classes;
there is no ArtifactClient-specific error type, and no new error type is
introduced by the client or by this guide.

```python
from market_vault import ArtifactClient
from market_vault.canonical import CanonicalArtifactValidationError
from market_vault.dataset import (
    DatasetArtifactValidationError,
    DatasetCatalogArtifactValidationError,
)

client = ArtifactClient()

try:
    client.load_canonical_build("D:\\missing\\canonical\\build")
except CanonicalArtifactValidationError as exc:
    print("canonical read failed closed:", exc)

try:
    client.load_dataset("D:\\missing\\dataset\\build")
except DatasetArtifactValidationError as exc:
    print("dataset read failed closed:", exc)

try:
    client.load_dataset_catalog("D:\\missing\\catalog\\snapshot")
except DatasetCatalogArtifactValidationError as exc:
    print("catalog snapshot read failed closed:", exc)
```

A corrupt artifact, a wrong directory layout, a symlink/junction path
component, an unexpected file, or a tampered identity always raises the
corresponding formal validation error; a partial or unverified result is
never returned.

## Contract reference

The formal boundary contract is `docs/contracts/python_client.md`. The
v0.7.0 direction and frozen PR sequence are in
`docs/v0_7_0_direction.md`. Runnable source-tree examples are in
`examples/python_client/`.
