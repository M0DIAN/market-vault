"""P2-4 build-isolation identity + evidence-closure comparator tests
(TEMPORARY, PR #79).

Tests the pure comparator / canonicalization / strict-schema validation of
scripts/ci_runtime_identity_v2.py (loaded via importlib, never imported),
including the build_isolation block identity contract: backend, declared
requires, dynamic-hook evidence, effective build distributions (name /
version / wheel filename / SHA256), all-wheels rule, constraint digest and
constraint mode. The probe subcommand itself (venv creation, pip dry-run,
network, real editable builds) is NOT exercised here; local unit tests
inject deterministic fixture values. The fail-closed rule: any missing,
ambiguous, malformed or unproven value makes the fingerprint INVALID and
any comparison NO MATCH — never "unknown".

Canary-only: this file is removed entirely on the final docs-only head.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = ROOT / "scripts" / "ci_runtime_identity_v2.py"


def _load() -> "module":
    spec = importlib.util.spec_from_file_location(
        "ci_runtime_identity_v2", _SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fp = _load()

CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"

DIST_FIXTURES = {
    "duckdb": ("duckdb", "1.5.5"),
    "numpy": ("numpy", "2.5.2"),
    "pandas": ("pandas", "2.3.3"),
    "pyarrow": ("pyarrow", "25.0.1"),
}

# The measured effective build set (setuptools 84.0.0, wheel 0.48.0,
# packaging 26.3 — wheel 0.48.0 transitively requires packaging>=24.0).
BUILD_FIXTURES = {
    "packaging": ("packaging", "26.3"),
    "setuptools": ("setuptools", "84.0.0"),
    "wheel": ("wheel", "0.48.0"),
}

CONSTRAINT_SHA256 = "c" * 64


def dist(name: str, version: str, *, sha256: str | None = None,
         url: str | None = None) -> dict:
    canonical = fp.canonicalize_name(name)
    return {
        "name": canonical,
        "version": version,
        "url": url or (
            f"https://files.example.org/packages/ab/cd/"
            f"{canonical}-{version}-py3-none-any.whl"
        ),
        "sha256": sha256 or hashlib.sha256(
            f"{canonical}-{version}".encode()
        ).hexdigest(),
    }


def build_dist(name: str, version: str, *, sha256: str | None = None) -> dict:
    canonical = fp.canonicalize_name(name)
    return {
        "name": canonical,
        "version": version,
        "filename": f"{canonical.replace('-', '_')}-{version}-py3-none-any.whl",
        "sha256": sha256 or hashlib.sha256(
            f"build-{canonical}-{version}".encode()
        ).hexdigest(),
    }


def make_build_isolation(**overrides: object) -> dict:
    block = {
        "backend": "setuptools.build_meta",
        "backend_path": None,
        "declared_requires": ["setuptools>=68", "wheel"],
        "dynamic_hook": "get_requires_for_build_editable",
        "dynamic_requires": [],
        "effective_build_distributions": sorted(
            (
                build_dist("packaging", "26.3"),
                build_dist("setuptools", "84.0.0"),
                build_dist("wheel", "0.48.0"),
            ),
            key=lambda entry: entry["name"],
        ),
        "build_constraint_sha256": CONSTRAINT_SHA256,
        "constraint_mode": "local_direct_reference_sha256",
        "all_artifacts_are_wheels": True,
    }
    block.update(overrides)
    return block


def make_fingerprint(**overrides: object) -> dict:
    """A fully valid V2 fingerprint with deterministic fixture values.
    Overrides are applied to the top-level dict, then the fingerprint
    SHA is recomputed (ordering differences in raw input must not change
    the fingerprint)."""
    doc = {
        "schema_version": 2,
        "surface": "test-3.14",
        "runner": {
            "run_os": "Linux",
            "run_arch": "X64",
            "image_os": "ubuntu24",
            "image_version": "20260801.1.0",
            "sys_platform": "linux",
            "machine": "x86_64",
            "release": "6.8.0-1021-azure",
            "libc_ver": ["glibc", "2.39"],
            "sysconfig_platform": "linux-x86_64",
        },
        "python": {
            "implementation": "CPython",
            "version": "3.14.4",
            "major": 3,
            "minor": 14,
            "micro": 4,
            "cache_tag": "cpython-314",
            "soabi": "cp314-x86_64-linux-gnu",
            "pointer_width": 64,
        },
        "resolver": {"name": "pip", "version": "26.2.1"},
        "dependency_contract": {
            "name": "market-vault",
            "version": "0.7.0",
            "pyproject_sha256": "a" * 64,
            "dependencies": ["pandas>=2.2,<3", "pyarrow>=16"],
            "dev_dependencies": ["pytest>=8,<10"],
        },
        "action_contract": {
            "checkout_sha": CHECKOUT_SHA,
            "setup_python_sha": SETUP_PYTHON_SHA,
            "upload_artifact_sha": UPLOAD_ARTIFACT_SHA,
            "ci_yml_sha256": "b" * 64,
        },
        "resolved_distributions": sorted(
            (
                dist("duckdb", "1.5.5"),
                dist("numpy", "2.5.2"),
                dist("pandas", "2.3.3"),
                dist("pyarrow", "25.0.1"),
            ),
            key=lambda entry: entry["name"],
        ),
        "build_isolation": make_build_isolation(),
    }
    doc.update(overrides)
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    return doc


def clone(doc: dict) -> dict:
    return json.loads(json.dumps(doc))


def _mutate_build(doc: dict, **overrides: object) -> dict:
    out = clone(doc)
    out["build_isolation"] = make_build_isolation(**overrides)
    out["fingerprint_sha256"] = fp.compute_fingerprint_sha(out)
    return out


def _first(doc_a: dict, doc_b: dict) -> tuple[str, str]:
    ok, reason = fp.compare_fingerprints(doc_a, doc_b)
    assert not ok
    return reason, fp.validate_fingerprint(doc_b)[1] or ""

# ---------------------------------------------------------------------------
# Validation: build_isolation block (fail closed).
# ---------------------------------------------------------------------------


class TestBuildIsolationValidation:
    def test_missing_build_isolation_invalid(self):
        doc = make_fingerprint()
        del doc["build_isolation"]
        doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_build_isolation"

    def test_backend_value_is_comparator_not_validation_concern(self):
        # A different backend VALUE is structurally well-formed: validation
        # accepts it (it is an identity INPUT), and only the comparator
        # flags the inequality (test_build_backend_unequal).
        doc = _mutate_build(make_fingerprint(), backend="flit_core.buildapi")
        ok, _ = fp.validate_fingerprint(doc)
        assert ok

    def test_backend_empty_invalid(self):
        doc = _mutate_build(make_fingerprint(), backend="")
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_build_isolation_backend"

    def test_declared_requires_unsorted_invalid(self):
        doc = _mutate_build(
            make_fingerprint(), declared_requires=["wheel", "setuptools>=68"]
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "build_declared_requires_unsorted"

    def test_declared_requires_empty_invalid(self):
        doc = _mutate_build(make_fingerprint(), declared_requires=[])
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "bad_build_isolation_declared_requires"

    def test_dynamic_hook_wrong_invalid(self):
        doc = _mutate_build(
            make_fingerprint(), dynamic_hook="get_requires_for_build_wheel"
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_build_isolation_dynamic_hook"

    def test_dynamic_requires_unsorted_invalid(self):
        doc = _mutate_build(
            make_fingerprint(), dynamic_requires=["wheel", "setuptools>=70"]
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "build_dynamic_requires_unsorted"

    def test_dynamic_requires_non_string_invalid(self):
        doc = _mutate_build(make_fingerprint(), dynamic_requires=[42])
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "bad_build_isolation_dynamic_requires"

    def test_constraint_digest_malformed_invalid(self):
        doc = _mutate_build(make_fingerprint(), build_constraint_sha256="x")
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "bad_build_isolation_constraint_digest"

    def test_constraint_mode_changed_invalid(self):
        doc = _mutate_build(
            make_fingerprint(), constraint_mode="index_based_pin"
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "bad_build_isolation_constraint_mode"

    def test_effective_empty_invalid(self):
        doc = _mutate_build(make_fingerprint(), effective_build_distributions=[])
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_build_isolation_effective_distributions"

    def test_effective_missing_sha_invalid(self):
        entry = build_dist("setuptools", "84.0.0")
        del entry["sha256"]
        doc = _mutate_build(
            make_fingerprint(),
            effective_build_distributions=[
                build_dist("packaging", "26.3"),
                entry,
                build_dist("wheel", "0.48.0"),
            ],
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_build_distribution_sha256"

    def test_effective_sdist_artifact_invalid(self):
        entry = build_dist("setuptools", "84.0.0")
        entry["filename"] = "setuptools-84.0.0.tar.gz"
        doc = _mutate_build(
            make_fingerprint(),
            effective_build_distributions=[
                build_dist("packaging", "26.3"),
                entry,
                build_dist("wheel", "0.48.0"),
            ],
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "build_artifact_not_wheel"

    def test_effective_duplicate_package_invalid(self):
        doc = _mutate_build(
            make_fingerprint(),
            effective_build_distributions=[
                build_dist("packaging", "26.3"),
                build_dist("setuptools", "84.0.0"),
                build_dist("setuptools", "84.0.0"),
            ],
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "duplicate_build_package"

    def test_effective_unsorted_invalid(self):
        doc = _mutate_build(
            make_fingerprint(),
            effective_build_distributions=[
                build_dist("setuptools", "84.0.0"),
                build_dist("packaging", "26.3"),
                build_dist("wheel", "0.48.0"),
            ],
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "build_distributions_unsorted"

    def test_effective_non_canonical_name_invalid(self):
        # build_dist() canonicalizes; construct a genuinely non-canonical
        # entry by hand.
        entry = build_dist("setuptools", "84.0.0")
        entry["name"] = "Setuptools"
        doc = _mutate_build(
            make_fingerprint(),
            effective_build_distributions=[
                build_dist("packaging", "26.3"),
                entry,
                build_dist("wheel", "0.48.0"),
            ],
        )
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "build_distribution_name_not_canonical"

    def test_all_artifacts_not_wheels_flag_invalid(self):
        doc = _mutate_build(make_fingerprint(), all_artifacts_are_wheels=False)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "build_artifacts_not_all_wheels"


# ---------------------------------------------------------------------------
# Validation: retained V1 strictness (schema, runner, python, contract).
# ---------------------------------------------------------------------------


class TestRetainedValidation:
    def test_schema_v1_rejected(self):
        doc = make_fingerprint()
        doc["schema_version"] = 1
        doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "schema_version_unsupported"

    def test_probe_invalid_doc_rejected(self):
        doc = {
            "schema_version": 2,
            "surface": "test-3.14",
            "valid": False,
            "invalid_reason": "x",
        }
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "probe_invalid"

    def test_runner_missing_image_version_invalid(self):
        doc = clone(make_fingerprint())
        del doc["runner"]["image_version"]
        doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_runner_image_version"

    def test_python_soabi_missing_invalid(self):
        doc = clone(make_fingerprint())
        del doc["python"]["soabi"]
        doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "missing_python_soabi"

    def test_duplicate_package_invalid(self):
        doc = clone(make_fingerprint())
        doc["resolved_distributions"] = [
            dist("pandas", "2.3.3"),
            dist("pandas", "2.3.3"),
            dist("numpy", "2.5.2"),
        ]
        doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "duplicate_package"

    def test_credential_url_invalid(self):
        doc = clone(make_fingerprint())
        doc["resolved_distributions"] = [
            {
                "name": "leak",
                "version": "1.0",
                "url": "https://user:pass@files.example.org/leak-1.0.whl",
                "sha256": "d" * 64,
            },
            dist("numpy", "2.5.2"),
            dist("pandas", "2.3.3"),
        ]
        doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "url_credentials"

    def test_fingerprint_sha_mismatch_invalid(self):
        doc = make_fingerprint()
        doc["fingerprint_sha256"] = "e" * 64
        ok, reason = fp.validate_fingerprint(doc)
        assert not ok and reason == "fingerprint_sha_mismatch"


# ---------------------------------------------------------------------------
# Comparator: build_isolation identity (section 15 mutations).
# ---------------------------------------------------------------------------


class TestBuildIsolationComparison:
    def test_identical_matches(self):
        a = make_fingerprint()
        b = clone(a)
        ok, reason = fp.compare_fingerprints(a, b)
        assert ok and reason == "ok"

    def test_build_backend_unequal(self):
        a = make_fingerprint()
        b = _mutate_build(a, backend="flit_core.buildapi")
        reason, _ = _first(a, b)
        assert reason == "build_backend_unequal"

    def test_build_declared_requires_unequal(self):
        a = make_fingerprint()
        b = _mutate_build(a, declared_requires=["setuptools>=68"])
        reason, _ = _first(a, b)
        assert reason == "build_declared_requires_unequal"

    def test_build_dynamic_requires_unequal(self):
        a = make_fingerprint()
        b = _mutate_build(a, dynamic_requires=["setuptools>=70"])
        reason, _ = _first(a, b)
        assert reason == "build_dynamic_requires_unequal"

    def test_build_package_version_unequal(self):
        a = make_fingerprint()
        b = _mutate_build(
            a,
            effective_build_distributions=sorted(
                (
                    build_dist("packaging", "26.3"),
                    build_dist("setuptools", "84.1.0"),
                    build_dist("wheel", "0.48.0"),
                ),
                key=lambda entry: entry["name"],
            ),
        )
        reason, _ = _first(a, b)
        assert reason == "build_package_version_unequal:setuptools"

    def test_build_wheel_filename_unequal(self):
        a = make_fingerprint()
        entry = build_dist("wheel", "0.48.0")
        entry["filename"] = "wheel-0.48.0-py2.py3-none-any.whl"
        b = _mutate_build(
            a,
            effective_build_distributions=sorted(
                (
                    build_dist("packaging", "26.3"),
                    build_dist("setuptools", "84.0.0"),
                    entry,
                ),
                key=lambda entry: entry["name"],
            ),
        )
        reason, _ = _first(a, b)
        assert reason == "build_wheel_filename_unequal:wheel"

    def test_build_wheel_sha_unequal(self):
        a = make_fingerprint()
        entry = build_dist("packaging", "26.3")
        entry["sha256"] = "f" * 64
        b = _mutate_build(
            a,
            effective_build_distributions=sorted(
                (
                    entry,
                    build_dist("setuptools", "84.0.0"),
                    build_dist("wheel", "0.48.0"),
                ),
                key=lambda entry: entry["name"],
            ),
        )
        reason, _ = _first(a, b)
        assert reason == "build_wheel_sha256_unequal:packaging"

    def test_build_package_missing(self):
        a = make_fingerprint()
        b = _mutate_build(
            a,
            effective_build_distributions=[
                build_dist("packaging", "26.3"),
                build_dist("setuptools", "84.0.0"),
            ],
        )
        reason, _ = _first(a, b)
        assert reason == "build_package_missing:wheel"

    def test_build_package_extra(self):
        a = make_fingerprint()
        b = _mutate_build(
            a,
            effective_build_distributions=sorted(
                (
                    build_dist("packaging", "26.3"),
                    build_dist("setuptools", "84.0.0"),
                    build_dist("wheel", "0.48.0"),
                    build_dist("setuptools-scm", "8.1.0"),
                ),
                key=lambda entry: entry["name"],
            ),
        )
        reason, _ = _first(a, b)
        assert reason == "build_package_extra:setuptools-scm"

    def test_build_constraint_digest_unequal(self):
        a = make_fingerprint()
        b = _mutate_build(a, build_constraint_sha256="1" * 64)
        reason, _ = _first(a, b)
        assert reason == "build_constraint_digest_unequal"

    def test_build_constraint_mode_unequal(self):
        a = make_fingerprint()
        b = _mutate_build(a, constraint_mode="index_based_pin")
        reason, _ = _first(a, b)
        assert reason == "build_constraint_mode_unequal"

    def test_build_isolation_invalid_fails_closed(self):
        a = make_fingerprint()
        b = _mutate_build(a, all_artifacts_are_wheels=False)
        ok, reason = fp.compare_fingerprints(a, b)
        assert not ok and reason == "build_artifacts_not_all_wheels_unequal"


# ---------------------------------------------------------------------------
# Comparator: retained V1 mutations (full #78 set).
# ---------------------------------------------------------------------------


class TestRetainedComparison:
    def test_surface_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["surface"] = "pyarrow24"
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "surface_unequal"

    def test_runner_image_version_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["runner"]["image_version"] = "20260701.1.0"
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "runner_image_version_unequal"

    def test_runner_arch_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["runner"]["run_arch"] = "ARM64"
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "runner_run_arch_unequal"

    def test_python_exact_runtime_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["python"]["version"] = "3.14.3"
        b["python"]["micro"] = 3
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "python_exact_runtime_unequal"

    def test_python_soabi_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["python"]["soabi"] = "cp314-win_amd64"
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "python_soabi_unequal"

    def test_pip_version_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["resolver"]["version"] = "26.2.2"
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "pip_version_unequal"

    def test_dependency_version_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["resolved_distributions"] = sorted(
            (
                dist("duckdb", "1.5.5"),
                dist("numpy", "2.5.2"),
                dist("pandas", "2.3.3"),
                dist("pyarrow", "24.0.0"),
            ),
            key=lambda entry: entry["name"],
        )
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "dependency_version_unequal:pyarrow"

    def test_dependency_hash_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["resolved_distributions"] = sorted(
            (
                dist("duckdb", "1.5.5"),
                dist("numpy", "2.5.2"),
                dist("pandas", "2.3.3"),
                dist("pyarrow", "25.0.1", sha256="f" * 64),
            ),
            key=lambda entry: entry["name"],
        )
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "dependency_artifact_hash_unequal:pyarrow"

    def test_dependency_missing(self):
        a = make_fingerprint()
        b = clone(a)
        b["resolved_distributions"] = [
            dist("duckdb", "1.5.5"),
            dist("numpy", "2.5.2"),
            dist("pyarrow", "25.0.1"),
        ]
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "dependency_missing:pandas"

    def test_dependency_extra(self):
        a = make_fingerprint()
        b = clone(a)
        b["resolved_distributions"] = sorted(
            (
                dist("duckdb", "1.5.5"),
                dist("numpy", "2.5.2"),
                dist("pandas", "2.3.3"),
                dist("pyarrow", "25.0.1"),
                dist("boto3", "1.35.0"),
            ),
            key=lambda entry: entry["name"],
        )
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "dependency_extra:boto3"

    def test_action_checkout_sha_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["action_contract"]["checkout_sha"] = "1" * 40
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "action_checkout_sha_unequal"

    def test_action_setup_python_sha_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["action_contract"]["setup_python_sha"] = "1" * 40
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "action_setup_python_sha_unequal"

    def test_action_upload_artifact_sha_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["action_contract"]["upload_artifact_sha"] = "1" * 40
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "action_upload_artifact_sha_unequal"

    def test_workflow_digest_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["action_contract"]["ci_yml_sha256"] = "c" * 64
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "workflow_digest_unequal"

    def test_pyproject_digest_unequal(self):
        a = make_fingerprint()
        b = clone(a)
        b["dependency_contract"]["pyproject_sha256"] = "d" * 64
        b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
        reason, _ = _first(a, b)
        assert reason == "pyproject_digest_unequal"

    def test_fingerprint_sha_unequal_after_all_identity_equal(self):
        # With every identity field equal, the digest must be the last
        # discriminator: tamper only the stored digest field.
        a = make_fingerprint()
        b = clone(a)
        b["fingerprint_sha256"] = "0" * 64
        reason, _ = _first(a, b)
        assert reason == "fingerprint_sha256_unequal"


# ---------------------------------------------------------------------------
# Canonicalization / ordering invariance.
# ---------------------------------------------------------------------------


class TestCanonicalization:
    def test_array_ordering_does_not_change_digest(self):
        a = make_fingerprint()
        b = clone(a)
        b["resolved_distributions"] = list(reversed(
            b["resolved_distributions"]
        ))
        b["build_isolation"]["effective_build_distributions"] = list(reversed(
            b["build_isolation"]["effective_build_distributions"]
        ))
        assert fp.compute_fingerprint_sha(a) == fp.compute_fingerprint_sha(b)
        ok, _ = fp.compare_fingerprints(a, b)
        assert ok

    def test_canonical_payload_omits_fingerprint_sha(self):
        doc = make_fingerprint()
        payload = fp.canonical_payload(doc)
        assert "fingerprint_sha256" not in payload
        assert fp.compute_fingerprint_sha(doc) == hashlib.sha256(
            fp.canonical_serialize(payload).encode("utf-8")
        ).hexdigest()

    def test_canonical_serialize_is_deterministic(self):
        doc = make_fingerprint()
        assert fp.canonical_serialize(doc) == fp.canonical_serialize(clone(doc))

    def test_effective_distributions_sorted_in_canonical_payload(self):
        doc = make_fingerprint()
        payload = fp.canonical_payload(doc)
        names = [
            entry["name"]
            for entry in payload["build_isolation"]["effective_build_distributions"]
        ]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Canonical URL normalization.
# ---------------------------------------------------------------------------


class TestUrlNormalization:
    def test_https_url_accepted(self):
        url, reason = fp.normalize_download_url(
            "https://files.example.org/pandas-2.3.3-py3-none-any.whl"
        )
        assert reason is None and url is not None

    def test_credentials_rejected(self):
        _, reason = fp.normalize_download_url(
            "https://user:pass@files.example.org/pandas-2.3.3-py3-none-any.whl"
        )
        assert reason == "url_credentials"

    def test_non_http_rejected(self):
        _, reason = fp.normalize_download_url(
            "file:///opt/wheels/pandas-2.3.3-py3-none-any.whl"
        )
        assert reason == "unsupported_url_scheme"


# ---------------------------------------------------------------------------
# verify-installed evaluation core (pure, injected inputs).
# ---------------------------------------------------------------------------


class TestVerifyEvaluation:
    def test_match_when_probe_valid_and_actual_identical(self):
        fingerprint = make_fingerprint()
        effective = {
            entry["name"]: entry
            for entry in fingerprint["resolved_distributions"]
        }
        receipt = fp.evaluate_verification(
            surface="test-3.14",
            fingerprint=fingerprint,
            effective=effective,
            install_verified=True,
            install_reason=None,
            importlib_mismatches=[],
            pyarrow_check=None,
        )
        assert receipt["probe_valid"] and receipt["actual_install_match"]
        assert receipt["build_isolation_valid"]

    def test_probe_invalid_fails_closed(self):
        receipt = fp.evaluate_verification(
            surface="test-3.14",
            fingerprint={"schema_version": 2, "valid": False},
            effective={},
            install_verified=True,
            install_reason=None,
            importlib_mismatches=[],
            pyarrow_check=None,
        )
        assert not receipt["probe_valid"]
        assert not receipt["actual_install_match"]
        assert receipt["reason"] == "probe_invalid"

    def test_build_block_invalid_still_fails_closed(self):
        fingerprint = make_fingerprint()
        fingerprint["build_isolation"]["all_artifacts_are_wheels"] = False
        fingerprint["fingerprint_sha256"] = fp.compute_fingerprint_sha(fingerprint)
        effective = {
            entry["name"]: entry
            for entry in fingerprint["resolved_distributions"]
        }
        receipt = fp.evaluate_verification(
            surface="test-3.14",
            fingerprint=fingerprint,
            effective=effective,
            install_verified=True,
            install_reason=None,
            importlib_mismatches=[],
            pyarrow_check=None,
        )
        assert not receipt["build_isolation_valid"]
        assert not receipt["actual_install_match"]
        assert receipt["reason"] == "probe_invalid"

    def test_install_unverified_fails_closed(self):
        fingerprint = make_fingerprint()
        receipt = fp.evaluate_verification(
            surface="test-3.14",
            fingerprint=fingerprint,
            effective={},
            install_verified=False,
            install_reason="actual_report_unreadable",
            importlib_mismatches=[],
            pyarrow_check=None,
        )
        assert not receipt["actual_install_match"]
        assert receipt["reason"] == "actual_report_unreadable"

    def test_importlib_mismatch_fails_closed(self):
        fingerprint = make_fingerprint()
        effective = {
            entry["name"]: entry
            for entry in fingerprint["resolved_distributions"]
        }
        receipt = fp.evaluate_verification(
            surface="test-3.14",
            fingerprint=fingerprint,
            effective=effective,
            install_verified=True,
            install_reason=None,
            importlib_mismatches=["pyarrow:24.0.0!=installed_25.0.1"],
            pyarrow_check=None,
        )
        assert not receipt["actual_install_match"]
        assert receipt["reason"].startswith("importlib_cross_check_mismatch")

    def test_actual_version_unequal_no_match(self):
        fingerprint = make_fingerprint()
        # Deep-copy the entries: the actual-map is NOT allowed to alias the
        # fingerprint document (mutating it would corrupt the probe input).
        effective = {
            entry["name"]: clone(entry)
            for entry in fingerprint["resolved_distributions"]
        }
        effective["pyarrow"]["version"] = "24.0.0"
        receipt = fp.evaluate_verification(
            surface="test-3.14",
            fingerprint=fingerprint,
            effective=effective,
            install_verified=True,
            install_reason=None,
            importlib_mismatches=[],
            pyarrow_check=None,
        )
        assert not receipt["actual_install_match"]
        assert receipt["reason"] == "probe_vs_actual:dependency_version_unequal:pyarrow"

    def test_pyarrow24_import_mismatch_fails_closed(self):
        fingerprint = make_fingerprint()
        fingerprint["surface"] = "pyarrow24"
        fingerprint["fingerprint_sha256"] = fp.compute_fingerprint_sha(fingerprint)
        effective = {
            entry["name"]: entry
            for entry in fingerprint["resolved_distributions"]
        }
        receipt = fp.evaluate_verification(
            surface="pyarrow24",
            fingerprint=fingerprint,
            effective=effective,
            install_verified=True,
            install_reason=None,
            importlib_mismatches=[],
            pyarrow_check={"imported": True, "version": "25.0.1", "match": False},
        )
        assert not receipt["actual_install_match"]
        assert receipt["reason"] == "pyarrow_import_version_mismatch"
