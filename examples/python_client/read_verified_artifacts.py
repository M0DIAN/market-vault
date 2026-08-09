"""Read one Canonical build, one Dataset build, and one Dataset Catalog
snapshot through the verified ArtifactClient and print one deterministic
JSON object.

This is an examples-only, Python 3.11 standard-library + market_vault
consumer script. It is NOT part of the ``market_vault`` package, is not
a public API, and never performs its own artifact validation.

Consumer contract:

- ``--canonical-build-dir``, ``--dataset-build-dir`` and
  ``--catalog-snapshot-dir`` are all required, explicit paths to the
  exact final artifact directories;
- no settings, no latest lookup, no discovery, no glob, no recursive
  scan, no environment-variable root, no cwd-derived root, no current
  time, no network, no OpenD, no writes, no cache;
- no direct manifest / catalog / Parquet reading: every read goes
  through ``ArtifactClient`` and the formal verified readers;
- stdout carries exactly one UTF-8 JSON object (``sort_keys=True``);
  documented failures go to stderr and nothing is ever written.

Exit codes: 0 on success, 1 on any documented read failure, 2 for
argparse usage errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from market_vault import ArtifactClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="read_verified_artifacts.py",
        description=(
            "Read one verified Canonical build, one verified Dataset "
            "build, and one verified Dataset Catalog snapshot through "
            "the ArtifactClient and print one deterministic JSON object."
        ),
    )
    parser.add_argument(
        "--canonical-build-dir", required=True, metavar="PATH",
        help="Explicit final Canonical build directory",
    )
    parser.add_argument(
        "--dataset-build-dir", required=True, metavar="PATH",
        help="Explicit final Dataset build directory",
    )
    parser.add_argument(
        "--catalog-snapshot-dir", required=True, metavar="PATH",
        help="Explicit final Dataset Catalog snapshot directory",
    )
    args = parser.parse_args(argv)

    client = ArtifactClient()

    try:
        canonical = client.load_canonical_build(args.canonical_build_dir)
        dataset = client.load_dataset(args.dataset_build_dir)
        catalog = client.load_dataset_catalog(args.catalog_snapshot_dir)
    except Exception as exc:  # formal reader errors propagate unchanged
        print(f"read_verified_artifacts: error: {exc}", file=sys.stderr)
        return 1

    # Trusted fields only, straight from the verified returned objects;
    # no derived trust claims, no artifact mutation.
    payload = {
        "canonical": {
            "canonical_build_id": canonical.canonical_build_id,
            "status": canonical.status,
            "row_count": len(canonical.bars),
        },
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "status": dataset.status,
            "row_count": len(dataset.rows),
        },
        "dataset_catalog": {
            "snapshot_id": catalog.snapshot_id,
            "catalog_content_id": catalog.catalog_content_id,
            "dataset_count": catalog.dataset_count,
        },
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
