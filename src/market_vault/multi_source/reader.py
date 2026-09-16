"""Sole explicit, read-only trust entry point for the separate A4.3 cohort."""

from dataclasses import fields
import hashlib
from pathlib import Path

import pyarrow as pa
import yaml

from ._artifact_paths import absolute_path, expected_inventory, inventory, object_identity, read_bytes, safe_path
from ._artifact_schema import output_contracts, parquet_rows, table_contracts
from ._artifact_validation import parse_specs, verify_bar, verify_sidecar, verify_values, verify_matrix, build_report
from ._orchestration_validation import freeze_copy
from ._serialization import canonical_json, evidence_from_bytes, read_json, require
from .artifact_models import MultiSourceDatasetArtifactError, VerifiedMultiSourceDatasetBuild
from .manifest import manifest_from_payload, MANIFEST_FIELDS


def _verify_directory(root, *, require_success, final_name):
    root = absolute_path(root)
    initial_root = object_identity(safe_path(root, directory=True))
    manifest_bytes = read_bytes(root / "manifest.json")
    obj = read_json(manifest_bytes)
    require(type(obj) is dict and set(obj) == MANIFEST_FIELDS and
            obj["manifest_schema_version"] == "multi-source-dataset-manifest-v1", "unsupported manifest version/fields")
    evidence_bytes = read_bytes(root / "associations/observation_evidence.json")
    evidence = evidence_from_bytes(evidence_bytes)
    manifest = manifest_from_payload(obj, evidence)
    identity = manifest.identity_input
    require(not final_name or root.name == manifest.dataset_id, "directory name/identity mismatch")
    contracts = output_contracts(identity)
    expected = expected_inventory(tuple(contracts) + ("manifest.json",) + (("_SUCCESS",) if require_success else ()))
    require(inventory(root) == expected, "missing or unlisted artifact member")
    require({f.relative_path for f in manifest.output_files} == set(contracts), "output whitelist mismatch")
    files = {}
    facts = {f.relative_path: f for f in manifest.output_files}
    for name, (role, content, version, parquet) in contracts.items():
        fact = facts[name]
        require((fact.file_role, fact.content_role, fact.content_id, fact.artifact_version) == (role, role, content, version),
                "output role/content/version mismatch")
        require((fact.row_count is not None) == parquet, "output row-count kind mismatch")
        data = evidence_bytes if name == "associations/observation_evidence.json" else read_bytes(root / name)
        require(len(data) == fact.byte_size and hashlib.sha256(data).hexdigest() == fact.sha256, "output hash/size mismatch")
        files[name] = data
    tables = []
    for contract in table_contracts(identity):
        rows = parquet_rows(files[contract[0]], manifest.dataset_id, contract)
        require(len(rows) == facts[contract[0]].row_count, "output row count mismatch")
        tables.append(rows)
    matrix, bar_rows, decision_rows, binding_rows, value_rows = tables
    require(len(matrix) == manifest.logical_row_count, "manifest logical row count mismatch")
    specs = parse_specs(files, identity)
    verify_bar(identity, bar_rows)
    decisions, bindings = verify_sidecar(identity, specs[1], decision_rows, binding_rows)
    observations = verify_values(identity, specs[1], value_rows, decisions, bindings)
    split = verify_matrix(identity, specs, matrix, bindings, observations)
    report = build_report(identity, manifest.built_at, manifest.logical_row_count, observations, split)
    require(canonical_json(report) == files["build_report.json"], "report recorded facts mismatch")
    if require_success:
        require(read_bytes(root / "_SUCCESS") == b"", "_SUCCESS must be empty regular marker")
    require(object_identity(safe_path(root, directory=True)) == initial_root and inventory(root) == expected,
            "root/inventory changed during verification")
    # Close every semantic decision over the initially verified bytes, not names.
    require(read_bytes(root / "manifest.json") == manifest_bytes, "manifest changed during verification")
    for name, initial in files.items():
        require(read_bytes(root / name) == initial, "output changed during verification: " + name)
    if require_success:
        require(read_bytes(root / "_SUCCESS") == b"", "_SUCCESS changed during verification")
    require(object_identity(safe_path(root, directory=True)) == initial_root and inventory(root) == expected,
            "root/inventory changed during final closure")
    return dict(dataset_id=manifest.dataset_id, status=manifest.status, manifest=manifest, schema=identity.schema,
        rows=tuple(tuple(r[f.name] for f in identity.schema.fields) for r in matrix), bar_associations=bar_rows,
        observation_decisions=decisions, sample_bindings=bindings, observation_feature_result=observations,
        observation_evidence=evidence, sample_audit=identity.sample_audit, bar_feature_specs=specs[0],
        observation_feature_specs=specs[1], label_specs=specs[2], split_spec=specs[3], split_result=split,
        build_report=report, build_dir=root)


def load_verified_multi_source_dataset(build_dir: str | Path) -> VerifiedMultiSourceDatasetBuild:
    """Verify exactly one final artifact. No discovery, repair, or trust bypass."""
    try:
        values = _verify_directory(build_dir, require_success=True, final_name=True)
        result = object.__new__(VerifiedMultiSourceDatasetBuild)
        for f in fields(result):
            object.__setattr__(result, f.name, freeze_copy(values[f.name]))
        return result
    except MultiSourceDatasetArtifactError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError, pa.ArrowException, yaml.YAMLError) as exc:
        raise MultiSourceDatasetArtifactError(f"invalid multi-source Dataset artifact: {exc}") from exc
