"""P2-3 runtime identity fingerprint comparator tests (TEMPORARY, PR #78).

Tests the pure comparator / canonicalization / strict-schema validation of
scripts/ci_runtime_fingerprint.py (loaded via importlib, never imported).
The probe subcommand itself (venv creation, pip dry-run, network) is NOT
exercised here; local unit tests inject deterministic fixture values.

Canary-only: this file is removed entirely on the final docs-only head.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = ROOT / "scripts" / "ci_runtime_fingerprint.py"


def _load() -> "module":
    spec = importlib.util.spec_from_file_location(
        "ci_runtime_fingerprint", _SCRIPT
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


def make_fingerprint(**overrides: object) -> dict:
    """A fully valid fingerprint with deterministic fixture values.
    Overrides are applied to the top-level dict, then the fingerprint
    SHA is recomputed (ordering differences in raw input must not change
    the fingerprint)."""
    doc = {
        "schema_version": 1,
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
    }
    doc.update(overrides)
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    return doc


def clone(doc: dict) -> dict:
    return json.loads(json.dumps(doc))


# ---------------------------------------------------------------------------
# Canonicalization.
# ---------------------------------------------------------------------------


def test_identical_canonical_fingerprints_match():
    match, reason = fp.compare_fingerprints(make_fingerprint(), make_fingerprint())
    assert match is True
    assert reason == "ok"


def test_canonical_ordering_does_not_change_fingerprint():
    # Canonical ordering differences in raw input must not change the
    # fingerprint: shuffled resolved_distributions produce the same
    # canonical payload and the same digest.
    shuffled = list(make_fingerprint()["resolved_distributions"])
    shuffled.reverse()
    doc = make_fingerprint(resolved_distributions=shuffled)
    assert fp.compute_fingerprint_sha(doc) == fp.compute_fingerprint_sha(
        make_fingerprint()
    )
    assert fp.canonical_serialize(
        fp.canonical_payload(doc)
    ) == fp.canonical_serialize(fp.canonical_payload(make_fingerprint()))
    match, _ = fp.compare_fingerprints(doc, make_fingerprint())
    assert match is True


def test_canonicalize_name_pep503():
    assert fp.canonicalize_name("Moomoo_API") == "moomoo-api"
    assert fp.canonicalize_name("PyYAML") == "pyyaml"
    assert fp.canonicalize_name("a..b-c_d") == "a-b-c-d"
    assert fp.canonicalize_name("duckdb") == "duckdb"


def test_normalize_download_url_rejects_credentials():
    url, reason = fp.normalize_download_url(
        "https://user:secret@files.example.org/pkg-1.0-py3-none-any.whl"
    )
    assert url is None
    assert reason == "url_credentials"


# ---------------------------------------------------------------------------
# Positive / negative comparator branches.
# ---------------------------------------------------------------------------


def test_different_image_version_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["runner"]["image_version"] = "20260802.1.0"
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "runner_image_version_unequal"


def test_different_runner_arch_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["runner"]["run_arch"] = "ARM64"
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "runner_run_arch_unequal"


def test_different_python_micro_version_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["python"]["version"] = "3.14.5"
    b["python"]["micro"] = 5
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "python_exact_runtime_unequal"


def test_different_python_soabi_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["python"]["soabi"] = "cp314-manylinux_x86_64"
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "python_soabi_unequal"


def test_different_pip_version_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["resolver"]["version"] = "26.2.0"
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "pip_version_unequal"


def test_dependency_version_changed_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["resolved_distributions"] = [
        entry if entry["name"] != "pyarrow" else dist("pyarrow", "24.0.0")
        for entry in b["resolved_distributions"]
    ]
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "dependency_version_unequal:pyarrow"


def test_dependency_artifact_sha_changed_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["resolved_distributions"] = [
        entry
        if entry["name"] != "numpy"
        else dist("numpy", "2.5.2", sha256="c" * 64)
        for entry in b["resolved_distributions"]
    ]
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "dependency_artifact_hash_unequal:numpy"


def test_dependency_missing_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["resolved_distributions"] = [
        entry for entry in b["resolved_distributions"]
        if entry["name"] != "duckdb"
    ]
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "dependency_missing:duckdb"


def test_extra_dependency_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["resolved_distributions"] = b["resolved_distributions"] + [
        dist("moomoo-api", "9.2.0")
    ]
    b["resolved_distributions"] = sorted(
        b["resolved_distributions"], key=lambda entry: entry["name"]
    )
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "dependency_extra:moomoo-api"


def test_action_checkout_sha_changed_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["action_contract"]["checkout_sha"] = "1" * 40
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "action_checkout_sha_unequal"


def test_action_setup_python_sha_changed_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["action_contract"]["setup_python_sha"] = "2" * 40
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "action_setup_python_sha_unequal"


def test_workflow_digest_changed_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["action_contract"]["ci_yml_sha256"] = "d" * 64
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "workflow_digest_unequal"


def test_pyproject_digest_changed_no_match():
    a = make_fingerprint()
    b = make_fingerprint()
    b["dependency_contract"]["pyproject_sha256"] = "e" * 64
    b["fingerprint_sha256"] = fp.compute_fingerprint_sha(b)
    match, reason = fp.compare_fingerprints(a, b)
    assert match is False
    assert reason == "pyproject_digest_unequal"


# ---------------------------------------------------------------------------
# Strict schema validation (fail closed).
# ---------------------------------------------------------------------------


def test_missing_required_runner_image_field_invalid():
    doc = make_fingerprint()
    del doc["runner"]["image_version"]
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "missing_runner_image_version"


def test_missing_package_version_invalid():
    doc = make_fingerprint()
    entry = clone(doc["resolved_distributions"][0])
    del entry["version"]
    doc["resolved_distributions"][0] = entry
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "missing_distribution_version"


def test_duplicate_normalized_package_invalid():
    doc = make_fingerprint()
    entry = clone(doc["resolved_distributions"][0])
    doc["resolved_distributions"] = doc["resolved_distributions"] + [entry]
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "duplicate_package"


def test_credential_bearing_url_rejected_invalid():
    doc = make_fingerprint()
    entry = clone(doc["resolved_distributions"][0])
    entry["url"] = "https://user:pass@files.example.org/pkg-1.0.whl"
    doc["resolved_distributions"][0] = entry
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "url_credentials"


def test_malformed_json_invalid(capsys):
    import argparse
    a = Path(ROOT) / "tests" / "_fp_tmp_a.json"
    b = Path(ROOT) / "tests" / "_fp_tmp_b.json"
    try:
        a.write_text("{not json", encoding="utf-8")
        b.write_text("{}", encoding="utf-8")
        ns = argparse.Namespace(a=str(a), b=str(b))
        fp.cmd_compare(ns)
    finally:
        a.unlink(missing_ok=True)
        b.unlink(missing_ok=True)
    out = capsys.readouterr().out
    assert "RUNTIME_FINGERPRINT_MATCH=false" in out
    assert "reason=malformed_json_a" in out


def test_unsupported_schema_version_invalid():
    doc = make_fingerprint()
    doc["schema_version"] = 2
    doc["fingerprint_sha256"] = fp.compute_fingerprint_sha(doc)
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "schema_version_unsupported"


def test_probe_invalid_document_not_a_valid_fingerprint():
    doc = {
        "schema_version": 1,
        "surface": "test-3.14",
        "valid": False,
        "invalid_reason": "pip_dryrun_failed",
    }
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "probe_invalid"


def test_fingerprint_sha_mismatch_invalid():
    doc = make_fingerprint()
    doc["fingerprint_sha256"] = "f" * 64
    valid, reason = fp.validate_fingerprint(doc)
    assert valid is False
    assert reason == "fingerprint_sha_mismatch"


def test_invalid_fingerprint_in_comparison_fails_closed(capsys):
    import argparse
    a = Path(ROOT) / "tests" / "_fp_tmp_a.json"
    b = Path(ROOT) / "tests" / "_fp_tmp_b.json"
    try:
        a.write_text(
            fp.canonical_serialize(make_fingerprint()), encoding="utf-8"
        )
        bad = make_fingerprint()
        bad["runner"]["image_version"] = ""
        bad["fingerprint_sha256"] = fp.compute_fingerprint_sha(bad)
        b.write_text(fp.canonical_serialize(bad), encoding="utf-8")
        ns = argparse.Namespace(a=str(a), b=str(b))
        fp.cmd_compare(ns)
    finally:
        a.unlink(missing_ok=True)
        b.unlink(missing_ok=True)
    out = capsys.readouterr().out
    assert "RUNTIME_FINGERPRINT_MATCH=false" in out
    assert "reason=invalid_fingerprint_b:missing_runner_image_version" in out


# ---------------------------------------------------------------------------
# verify-installed evaluation (pure core).
# ---------------------------------------------------------------------------


def _effective_set(names: list[str]) -> dict:
    return {
        entry["name"]: entry
        for entry in (
            dist(name, DIST_FIXTURES[name][1]) for name in names
        )
    }


def test_verify_probe_valid_and_actual_matches():
    fingerprint = make_fingerprint()
    effective = _effective_set(["duckdb", "numpy", "pandas", "pyarrow"])
    receipt = fp.evaluate_verification(
        surface="test-3.14",
        fingerprint=fingerprint,
        effective=effective,
        install_verified=True,
        install_reason=None,
        importlib_mismatches=[],
        pyarrow_check=None,
    )
    assert receipt["probe_valid"] is True
    assert receipt["actual_install_verified"] is True
    assert receipt["actual_install_match"] is True
    assert receipt["reason"] is None


def test_verify_probe_invalid():
    receipt = fp.evaluate_verification(
        surface="test-3.14",
        fingerprint={"valid": False, "invalid_reason": "pip_dryrun_failed"},
        effective=_effective_set(["duckdb"]),
        install_verified=True,
        install_reason=None,
        importlib_mismatches=[],
        pyarrow_check=None,
    )
    assert receipt["probe_valid"] is False
    assert receipt["actual_install_match"] is False
    assert receipt["reason"] == "probe_invalid"


def test_verify_actual_environment_differs():
    fingerprint = make_fingerprint()
    effective = _effective_set(["duckdb", "numpy", "pandas", "pyarrow"])
    effective["pyarrow"] = dist("pyarrow", "24.0.0")
    receipt = fp.evaluate_verification(
        surface="test-3.14",
        fingerprint=fingerprint,
        effective=effective,
        install_verified=True,
        install_reason=None,
        importlib_mismatches=[],
        pyarrow_check=None,
    )
    assert receipt["actual_install_match"] is False
    assert receipt["reason"] == "probe_vs_actual:dependency_version_unequal:pyarrow"


def test_verify_pyarrow24_pin_resolved_sets_match_with_live_import_confirm():
    # For the pyarrow24 surface the probe resolves WITH the pin
    # (SURFACE_REQUIREMENTS includes pyarrow==24.0.0), so the fingerprint
    # carries pyarrow 24.0.0 and the sets match the actual install; the
    # live-import check additionally confirms the pinned runtime.
    fingerprint = make_fingerprint(surface="pyarrow24")
    fingerprint["resolved_distributions"] = [
        entry
        if entry["name"] != "pyarrow"
        else dist("pyarrow", "24.0.0")
        for entry in fingerprint["resolved_distributions"]
    ]
    fingerprint["fingerprint_sha256"] = fp.compute_fingerprint_sha(fingerprint)
    effective = _effective_set(["duckdb", "numpy", "pandas", "pyarrow"])
    effective["pyarrow"] = dist("pyarrow", "24.0.0")
    receipt = fp.evaluate_verification(
        surface="pyarrow24",
        fingerprint=fingerprint,
        effective=effective,
        install_verified=True,
        install_reason=None,
        importlib_mismatches=[],
        pyarrow_check={"imported": True, "version": "24.0.0", "match": True},
    )
    assert receipt["actual_install_match"] is True
    assert receipt["reason"] is None


def test_verify_pyarrow24_live_import_contradicts_sets_fails_closed():
    # Sets match the pin, but the live import reports a different
    # version: the receipt fails closed (never claims a match that a
    # contradicting live import can refute).
    fingerprint = make_fingerprint(surface="pyarrow24")
    fingerprint["resolved_distributions"] = [
        entry
        if entry["name"] != "pyarrow"
        else dist("pyarrow", "24.0.0")
        for entry in fingerprint["resolved_distributions"]
    ]
    fingerprint["fingerprint_sha256"] = fp.compute_fingerprint_sha(fingerprint)
    effective = _effective_set(["duckdb", "numpy", "pandas", "pyarrow"])
    effective["pyarrow"] = dist("pyarrow", "24.0.0")
    receipt = fp.evaluate_verification(
        surface="pyarrow24",
        fingerprint=fingerprint,
        effective=effective,
        install_verified=True,
        install_reason=None,
        importlib_mismatches=[],
        pyarrow_check={"imported": True, "version": "25.0.1", "match": False},
    )
    assert receipt["actual_install_match"] is False
    assert receipt["reason"] == "pyarrow_import_version_mismatch"


def test_verify_importlib_mismatch_fails_closed():
    receipt = fp.evaluate_verification(
        surface="test-3.14",
        fingerprint=make_fingerprint(),
        effective=_effective_set(["duckdb"]),
        install_verified=True,
        install_reason=None,
        importlib_mismatches=["duckdb:not_installed"],
        pyarrow_check=None,
    )
    assert receipt["actual_install_verified"] is False
    assert receipt["actual_install_match"] is False
    assert receipt["reason"] == "importlib_cross_check_mismatch:duckdb:not_installed"
