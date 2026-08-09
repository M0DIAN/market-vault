# MarketVault Verified ArtifactClient Python Examples

This directory contains a source-tree, consumer-side example of the
v0.7.0 `ArtifactClient` verified reads. It is an example only: it is not
shipped as a public client API, it is not part of the `market_vault`
package, and it never performs its own artifact validation.

> **Released.** This example targets the formally released v0.7.0
> `ArtifactClient`. The package metadata is 0.7.0.
> The formal v0.7.0 GitHub Release contains the `ArtifactClient` wheel and sdist,
> and the formal v0.6.1 GitHub Release does NOT contain `ArtifactClient`.

```text
examples/python_client/
    README.md
    read_verified_artifacts.py   # stdlib + market_vault only
```

## 1. Usage

POSIX:

```bash
python examples/python_client/read_verified_artifacts.py \
  --canonical-build-dir <PATH> \
  --dataset-build-dir <PATH> \
  --catalog-snapshot-dir <PATH>
```

Windows PowerShell (equivalent):

```powershell
python examples\python_client\read_verified_artifacts.py `
  --canonical-build-dir "D:\data\canonical\dataset=market_bars_canonical\<build-id>" `
  --dataset-build-dir "D:\data\datasets\<dataset-id>" `
  --catalog-snapshot-dir "D:\data\catalog_snapshots\<snapshot-id>"
```

All three arguments are required and must be EXPLICIT paths to the exact
final artifact directories. The script prints one deterministic JSON
object to stdout:

```json
{"canonical": {"canonical_build_id": "...", "status": "COMPLETE", "row_count": 6},
 "dataset": {"dataset_id": "...", "status": "COMPLETE", "row_count": 2},
 "dataset_catalog": {"snapshot_id": "...", "catalog_content_id": "...", "dataset_count": 1}}
```

## 2. What the example does

```python
from market_vault import ArtifactClient

client = ArtifactClient()

canonical = client.load_canonical_build(args.canonical_build_dir)
dataset = client.load_dataset(args.dataset_build_dir)
catalog = client.load_dataset_catalog(args.catalog_snapshot_dir)
```

Each method delegates verbatim to the formal verified reader and returns
the exact formal verified object. Only trusted fields from those verified
objects are printed.

## 3. Boundaries

The example never:

- requires settings or a settings file;
- looks up `latest` or any pointer;
- scans, globs, or discovers artifact paths;
- writes, repairs, rewrites, or deletes any file;
- accesses the network or OpenD;
- reads the current time;
- parses `manifest.json`, `catalog.json`, or Parquet itself;
- imports pandas or any ML / visualization framework.

The verified readers remain the only trust boundaries; the example
performs no artifact verification of its own. Exit codes: 0 on success,
1 on any documented read failure, 2 for argparse usage errors.

## 4. Fail-closed reads

A corrupt artifact, a wrong directory layout, a symlink/junction path
component, or a tampered identity raises the corresponding formal
validation error (`CanonicalArtifactValidationError`,
`DatasetArtifactValidationError`, `DatasetCatalogArtifactValidationError`);
the example reports it on stderr and exits 1. There is no
ArtifactClient-specific error type.
