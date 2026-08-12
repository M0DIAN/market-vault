"""P2-6 runtime sdist build-output identity canary — pure negative test
suite (TEMPORARY, PR #81).  The module under test is loaded via importlib
so this file is never itself imported by the suite; no pytest node is
added to the audit surface.  Removed entirely on the final docs-only head.

Covers section 23 (19 negative identity cases) and section 24 (built-wheel
byte-mutation negative) of the canary spec, plus the offline evidence
replay fail-closed rules (section 31)."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "ci_runtime_sdist_identity.py"
)
REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "ci_runtime_sdist_identity", SCRIPT)
rsi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rsi)

CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"

SDIST_FIXTURE = {
    "name": "moomoo-api",
    "version": "10.9.6908",
    "url": ("https://files.pythonhosted.org/packages/"
            "moomoo_api-10.9.6908.tar.gz"),
    "sha256": "6df0370ed120ec6e9f0bf65576a07838a7d105bb91e3ebb929f496a096700304",
    "artifact_type": "sdist",
    "filename": "moomoo_api-10.9.6908.tar.gz",
}

WHEEL_FIXTURE = {
    "name": "moomoo-api",
    "version": "10.9.6908",
    "filename": "moomoo_api-10.9.6908-py3-none-any.whl",
    "raw_sha256": "ab" * 32,
    "WHEEL_PAYLOAD_SHA256": "cd" * 32,
    "repeat_build_raw_sha256_match": True,
}

BUILD_ENV_FIXTURE = {
    "backend": "setuptools.build_meta",
    "declared_requires": ["setuptools>=68", "wheel"],
    "dynamic_requires": [],
    "SOURCE_BUILD_ENVIRONMENT_SHA256": "ef" * 32,
    "build_distributions": [
        {"name": "setuptools", "version": "84.0.0",
         "filename": "setuptools-84.0.0-py3-none-any.whl",
         "sha256": "10" * 32},
        {"name": "wheel", "version": "0.48.0",
         "filename": "wheel-0.48.0-py3-none-any.whl",
         "sha256": "20" * 32},
    ],
}

BUILD_CONTRACT_FIXTURE = {
    "backend": "setuptools.build_meta",
    "declared_requires": ["setuptools>=68", "wheel"],
    "dynamic_requires": [],
    "SOURCE_BUILD_ENVIRONMENT_SHA256": BUILD_ENV_FIXTURE[
        "SOURCE_BUILD_ENVIRONMENT_SHA256"],
}

INSTALL_FIXTURE = {
    "local_wheel_report_sha256": WHEEL_FIXTURE["raw_sha256"],
    "install_report_valid": True,
    "INSTALLED_PAYLOAD_SHA256": WHEEL_FIXTURE["WHEEL_PAYLOAD_SHA256"],
    "installed_record_valid": True,
}


def clone(obj):
    return copy.deepcopy(obj)


def b64h(data):
    return base64.urlsafe_b64encode(
        hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def make_identity(mutate=None):
    """A complete runtime_sdist_identity.json document fixture."""
    doc = {
        "schema_version": rsi.SCHEMA_VERSION,
        "surface": "test-3.14",
        "runner": {"runner_os": "Windows", "runner_arch": "X64",
                   "image_os": "win24", "image_version": "20260810.271.1",
                   "platform_system": "Windows", "platform_release": "10",
                   "platform_version": "10.0.26200", "platform_machine": "AMD64"},
        "python": {"executable_basename": "python.exe",
                   "python_version": "3.14.7", "implementation": "CPython",
                   "win32": True},
        "resolver": {"pip_version": "26.2.1"},
        "dependency_contract": {
            "name": "market-vault", "version": "0.7.0",
            "pyproject_sha256": "aa" * 32,
            "build_system": {"requires": ["setuptools>=68", "wheel"],
                             "build_backend": "setuptools.build_meta",
                             "backend_path": []},
            "dependencies": ["moomoo-api>=9.2"],
            "dev_dependencies": ["pytest>=8"],
        },
        "action_contract": {"checkout_sha": CHECKOUT_SHA,
                            "setup_python_sha": SETUP_PYTHON_SHA,
                            "upload_artifact_sha": UPLOAD_ARTIFACT_SHA,
                            "ci_yml_sha256": "bb" * 32},
        "workflow": {"ci_yml_sha256": "bb" * 32},
        "resolved_distributions": [clone(SDIST_FIXTURE)],
        "source_sdist_identity": {
            "moomoo-api": {"filename": SDIST_FIXTURE["filename"],
                           "sha256": SDIST_FIXTURE["sha256"]},
        },
        "source_build_environment_identity": {
            "moomoo-api": clone(BUILD_CONTRACT_FIXTURE),
        },
        "exact_built_wheel_sha256": {
            "moomoo-api": clone(WHEEL_FIXTURE),
        },
        "installed_payload_identity": {
            "moomoo-api": clone(INSTALL_FIXTURE),
        },
        "marketvault_build_identity": {
            "backend": "setuptools.build_meta",
            "effective_build_distributions": [
                {"name": "packaging", "version": "26.3",
                 "filename": "packaging-26.3-py3-none-any.whl",
                 "sha256": "30" * 32},
            ],
            "closed_world_contract_used": True,
        },
        "source_build_identity_valid": True,
        "final_runtime_match": True,
        "shadow_surface_pass": True,
    }
    doc["fingerprint_sha256"] = rsi.compute_fingerprint_sha(doc)
    if mutate:
        mutate(doc)
    return doc


def make_verdicts(mutate=None):
    """A complete measured verdict set for one sdist (moomoo-api)."""
    name = "moomoo-api"
    verdicts = {
        "SOURCE_SDIST_HASH_OK": True,
        "RUNTIME_WHEEL_COUNT": 87,
        "RUNTIME_SDIST_COUNT": 1,
        "RUNTIME_OTHER_COUNT": 0,
        f"SDIST_MATERIALIZED_{name}": True,
        f"RAW_WHEEL_REPRODUCIBLE_{name}": True,
        f"MUTATED_WHEEL_REJECTED_{name}": True,
        f"SOURCE_BUILD_CACHE_DISABLED_{name}_1": True,
        f"SOURCE_BUILD_CACHE_DISABLED_{name}_2": True,
        f"SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL_{name}": True,
        "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL": True,
        "SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL": True,
        "RUNTIME_INSTALL_FROM_WHEELS_ONLY": True,
        "UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL": False,
        "SHADOW_SURFACE_PASS": True,
        "P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED": True,
        "FINAL_RUNTIME_MATCH": True,
    }
    if mutate:
        mutate(verdicts)
    return verdicts


def make_wheel(path, payload=b"print('hi')\n"):
    """Synthetic structurally-valid wheel (RECORD covers every member)."""
    path = Path(path)
    dist = "demo_pkg-1.0.dist-info"
    payloads = {
        "demo_pkg/__init__.py": payload,
        f"{dist}/METADATA": (
            b"Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.0\n"),
        f"{dist}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"),
    }
    with zipfile.ZipFile(path, "w") as zf:
        for p, d in payloads.items():
            zf.writestr(p, d)
        rows = [f"{p},{b64h(d)},{len(d)}" for p, d in payloads.items()]
        # PEP 427: RECORD ends with its own entry with empty hash+size
        # (bdist_wheel output; a wheel cannot bind its own bytes).
        rows.append(f"{dist}/RECORD,,")
        zf.writestr(f"{dist}/RECORD", "\n".join(rows) + "\n")
    return path


def make_installed_tree(root):
    """Fabricated installed distribution: pkg + dist-info (valid RECORD)."""
    root = Path(root)
    dist = "demo_pkg-1.0.dist-info"
    payload = b"print('hi')\n"
    files = {
        "demo_pkg/__init__.py": payload,
        f"{dist}/METADATA": (
            b"Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.0\n"),
        f"{dist}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"),
        f"{dist}/INSTALLER": b"pip\n",
        f"{dist}/REQUESTED": b"",
        f"{dist}/direct_url.json": json.dumps({
            "archive_info": {"hash": f"sha256={'aa' * 32}",
                             "hashes": {"sha256": "aa" * 32}},
            "url": "file:///tmp/demo_pkg-1.0-py3-none-any.whl",
        }).encode(),
    }
    rows = []
    for p, d in files.items():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_bytes(d)
        rows.append(f"{p},{b64h(d)},{len(d)}")
    (root / dist / "RECORD").write_text("\n".join(rows) + "\n",
                                        encoding="utf-8")
    return root, dist


# ---------------------------------------------------------------------------
# section 23: cross-head identity comparisons
# ---------------------------------------------------------------------------


class TestRuntimeSdistIdentityMatch:
    def test_01_same_sdist_same_wheel_sha_matches(self):
        a = make_identity()
        b = clone(a)
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is True and diff is None

    def test_02_different_wheel_sha_no_match(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["exact_built_wheel_sha256"]["moomoo-api"]
            .__setitem__("raw_sha256", "ff" * 32))
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "exact_built_wheel_sha256"

    def test_03_name_version_same_but_different_wheel_sha_no_match(self):
        a = make_identity()
        b = make_identity()
        # identical name/version/sdist, different built wheel bytes
        b["exact_built_wheel_sha256"]["moomoo-api"]["raw_sha256"] = "f1" * 32
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "exact_built_wheel_sha256"

    def test_04_different_wheel_filename_no_match(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["exact_built_wheel_sha256"]["moomoo-api"]
            .__setitem__("filename",
                         "moomoo_api-10.9.6908-py3-none-any-rebuilt.whl"))
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "exact_built_wheel_sha256"

    def test_05_different_build_environment_no_match(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["source_build_environment_identity"]["moomoo-api"]
            .__setitem__("SOURCE_BUILD_ENVIRONMENT_SHA256", "fe" * 32))
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "source_build_environment_identity"

    def test_06_different_backend_no_match(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["source_build_environment_identity"]["moomoo-api"]
            .__setitem__("backend", "hatchling.build"))
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "source_build_environment_identity"

    def test_07_different_python_no_match(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["python"].__setitem__("python_version", "3.14.6"))
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "python"

    def test_08_different_pip_no_match(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["resolver"].__setitem__("pip_version", "26.2.0"))
        equal, diff = rsi.compare_identity_docs(a, b)
        assert equal is False and diff == "resolver"


# ---------------------------------------------------------------------------
# section 23: fail-closed validity rules (SOURCE_BUILD_IDENTITY_VALID)
# ---------------------------------------------------------------------------


class TestSourceBuildIdentityValid:
    def test_09_missing_built_wheel_sha_invalid(self):
        verdicts = make_verdicts()
        verdicts.pop("RAW_WHEEL_REPRODUCIBLE_moomoo-api")
        assert rsi.evaluate_source_build_identity_valid(
            verdicts, ["moomoo-api"]) is False

    def test_10_sdist_without_verified_sha_invalid(self):
        verdicts = make_verdicts(
            lambda v: v.__setitem__("SOURCE_SDIST_HASH_OK", False))
        assert rsi.evaluate_source_build_identity_valid(
            verdicts, ["moomoo-api"]) is False
        # and the report-level rule: an sdist entry without sha256 raises
        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(ValueError):
                rsi.parse_pip_report_extended(
                    _write_report({"name": "moomoo-api",
                                   "version": "10.9.6908",
                                   "url": SDIST_FIXTURE["url"],
                                   "sha": None}, td))

    def test_11_source_build_used_cache_invalid(self):
        assert rsi.source_build_cache_ok(
            "Collecting moomoo-api\nUsing cached "
            "moomoo_api-10.9.6908.tar.gz\nBuilding wheel") is False
        verdicts = make_verdicts(
            lambda v: v.__setitem__(
                "SOURCE_BUILD_CACHE_DISABLED_moomoo-api_1", False))
        assert rsi.evaluate_source_build_identity_valid(
            verdicts, ["moomoo-api"]) is False

    def test_12_install_report_points_to_sdist_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = td / "demo_pkg-1.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-bytes")
            built_sha = hashlib.sha256(b"wheel-bytes").hexdigest()
            report = td / "r.json"
            # the report's only matching artifact is an sdist, not the wheel
            report.write_text(json.dumps({"install": [
                {"metadata": {"name": "demo-pkg", "version": "1.0"},
                 "download_info": {
                     "url": "https://pypi.org/p/demo_pkg-1.0.tar.gz",
                     "hashes": {"sha256": built_sha}}},
            ]}), encoding="utf-8")
            result = rsi.verify_install_report(report, wheel, built_sha)
            assert result["valid"] is False

    def test_13_install_report_sha_differs_from_built_sha_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = td / "demo_pkg-1.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-bytes")
            built_sha = hashlib.sha256(b"wheel-bytes").hexdigest()
            report = td / "r.json"
            report.write_text(json.dumps({"install": [
                {"metadata": {"name": "demo-pkg", "version": "1.0"},
                 "download_info": {
                     "url": wheel.as_uri(),
                     "hashes": {"sha256": "f" * 64}}},
            ]}), encoding="utf-8")
            result = rsi.verify_install_report(report, wheel, built_sha)
            assert result["valid"] is False

    def test_14_installed_record_hash_mismatch_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root, dist = make_installed_tree(Path(td))
            # tamper an installed file after RECORD was written
            (root / "demo_pkg" / "__init__.py").write_bytes(b"print('HI')\n")
            payload = rsi.verify_installed_payload_at(
                Path(td) / dist, "demo-pkg", "1.0", "1.0")
            assert payload["valid"] is False
            assert any("SHA256" in r for r in payload["reasons"])

    def test_15_installed_payload_mutation_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root, dist = make_installed_tree(Path(td))
            before = rsi.verify_installed_payload_at(
                Path(td) / dist, "demo-pkg", "1.0", "1.0")
            assert before["valid"] is True
            (root / "demo_pkg" / "__init__.py").write_bytes(b"print('yo')\n")
            after = rsi.verify_installed_payload_at(
                Path(td) / dist, "demo-pkg", "1.0", "1.0")
            assert after["valid"] is False
            assert after["INSTALLED_PAYLOAD_SHA256"] != \
                before["INSTALLED_PAYLOAD_SHA256"]

    def test_16_source_built_package_replaced_later_invalid(self):
        verdicts = make_verdicts(
            lambda v: v.__setitem__(
                "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL", False))
        assert rsi.evaluate_source_build_identity_valid(
            verdicts, ["moomoo-api"]) is False

    def test_17_unexpected_runtime_sdist_at_final_install_invalid(self):
        verdicts = make_verdicts(
            lambda v: v.__setitem__(
                "RUNTIME_INSTALL_FROM_WHEELS_ONLY", False))
        assert rsi.evaluate_source_build_identity_valid(
            verdicts, ["moomoo-api"]) is False
        # report-level: a final install report containing an sdist artifact
        # classifies it as sdist (the leg then fails wheels-only)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wh = td / "pkg-1.0-py3-none-any.whl"
            wh.write_bytes(b"x")
            report = td / "final.json"
            report.write_text(json.dumps({"install": [
                {"metadata": {"name": "pkg", "version": "1.0"},
                 "download_info": {"url": wh.as_uri(),
                                   "hashes": {
                                       "sha256": hashlib.sha256(b"x").hexdigest()}}},
                {"metadata": {"name": "other", "version": "1.0"},
                 "download_info": {
                     "url": "https://pypi.org/p/other-1.0.tar.gz",
                     "hashes": {"sha256": "a" * 64}}},
            ]}), encoding="utf-8")
            records = rsi.parse_pip_report_extended(report)
            types = {r["artifact_type"] for r in records}
            assert types == {"wheel", "sdist"}
            assert not (types <= {"wheel"})


# ---------------------------------------------------------------------------
# section 23: evidence manifest duplicate-path hardening
# ---------------------------------------------------------------------------


class TestManifestDuplicatePathHardening:
    def test_18_generator_rejects_duplicate_relative_path(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "probe_summary.txt").write_text("RUNTIME_SDIST_COUNT=1\n",
                                                    encoding="utf-8")
            dup = root / "probe_summary.txt"
            monkeypatch.setattr(
                rsi, "_manifest_files", lambda _root: [dup, dup])
            with pytest.raises(ValueError) as exc:
                rsi._write_manifest(root, ["probe_summary.txt"])
            assert "EVIDENCE_MANIFEST_INVALID" in str(exc.value)
            assert "reason=duplicate_path:probe_summary.txt" in str(exc.value)
            assert not (root / "EVIDENCE_MANIFEST.json").exists()

    def test_18b_verifier_rejects_duplicate_paths_independently(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rsi.write_json(root / "EVIDENCE_MANIFEST.json", {
                "schema_version": rsi.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [
                    {"path": "probe_summary.txt", "size": 1,
                     "sha256": "0" * 64},
                    {"path": "probe_summary.txt", "size": 1,
                     "sha256": "0" * 64},
                ],
            })
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            assert verifier.checks.get("manifest_unique_paths") is False


# ---------------------------------------------------------------------------
# section 23/31: offline evidence corruption fails closed
# ---------------------------------------------------------------------------


class TestOfflineReplayFailClosed:
    def test_19_corrupted_evidence_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = hashlib.sha256(b"x").hexdigest()
            (root / "probe_summary.txt").write_bytes(b"x")
            rsi.write_json(root / "EVIDENCE_MANIFEST.json", {
                "schema_version": rsi.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [
                    {"path": "probe_summary.txt", "size": 1,
                     "sha256": good},
                ],
            })
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            assert verifier.checks.get("manifest_present") is True
            assert verifier.checks.get("manifest_hashes") is True
            # corrupt the retained bytes -> replay must fail closed
            (root / "probe_summary.txt").write_bytes(b"y")
            verifier2 = rsi.BundleVerifier(root)
            verifier2.verify()
            assert verifier2.checks.get("manifest_hashes") is False
            assert "probe_summary.txt:SHA256" in (
                verifier2.checks.get("manifest_hashes_detail") or "")

    def test_19b_identity_digest_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity = make_identity()
            identity["fingerprint_sha256"] = "0" * 64
            (root / "runtime_sdist_identity.json").write_text(
                json.dumps(identity), encoding="utf-8")
            # recorded fingerprint no longer matches the document content
            rsi.write_json(root / "EVIDENCE_MANIFEST.json", {
                "schema_version": rsi.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [],
            })
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            assert verifier.checks.get("identity_schema") is True
            assert verifier.checks.get("identity_digest") is False

    def test_19c_sdist_bytes_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # retained sdist bytes must equal the recorded identity
            sid = {
                "schema_version": rsi.SCHEMA_VERSION,
                "name": "moomoo-api", "version": "10.9.6908",
                "filename": "moomoo_api-10.9.6908.tar.gz",
                "resolver_source_sha256": "6d" * 32,
                "local_sdist_sha256": "6d" * 32,
                "valid": True,
            }
            sdist_dir = root / rsi.SDIST_REL
            sdist_dir.mkdir(parents=True)
            (sdist_dir / "moomoo_api-10.9.6908.tar.gz").write_bytes(b"x")
            rsi.write_json(root / "source_sdist_identity.json", sid)
            rsi.write_json(root / "EVIDENCE_MANIFEST.json", {
                "schema_version": rsi.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [],
            })
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            assert verifier.checks.get("sdist_identity") is False
            assert "resolver_source_sha256_mismatch" in (
                verifier.checks.get("sdist_identity_detail") or "")


# ---------------------------------------------------------------------------
# section 24: built-wheel byte-mutation negative
# ---------------------------------------------------------------------------


class TestWheelMutationNegative:
    def test_24_mutated_wheel_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = make_wheel(td / "demo_pkg-1.0-py3-none-any.whl")
            v = rsi.validate_wheel(wheel, "demo-pkg", "1.0")
            assert v["valid"] is True
            mutation = rsi.mutation_negative(wheel, td / "mut")
            assert mutation["rejected"] is True
            # the authoritative wheel is untouched
            assert rsi.validate_wheel(wheel, "demo-pkg", "1.0")["valid"] is True
            assert mutation["mutated_wheel_filename"].startswith("mutated_")
            # the mutated copy fails structural validation independently
            mutated = td / "mut" / mutation["mutated_wheel_filename"]
            assert rsi.validate_wheel(
                mutated, "demo-pkg", "1.0")["valid"] is False

    def test_24b_payload_and_raw_sha_differ_after_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = make_wheel(td / "demo_pkg-1.0-py3-none-any.whl")
            before_payload = rsi.wheel_payload_sha256(wheel)
            before_sha = rsi.sha256_file(wheel)
            mutation = rsi.mutation_negative(wheel, td / "mut")
            assert mutation["payload_differs"] is True
            assert mutation["sha_differs"] is True
            assert rsi.wheel_payload_sha256(wheel) == before_payload
            assert rsi.sha256_file(wheel) == before_sha


class TestCliWiring:
    """CLI-level wiring guard: every Namespace attribute each cmd_*
    consumes must exist after argparse parses the documented invocation.
    This class of bug (a Namespace.actions read against --actions-*
    dests) crashed Head A's measure before any measurement happened."""

    def test_25_measure_namespace_has_all_consumed_attrs(self):
        argv = [
            "measure",
            "--surface", "test-3.14",
            "--actions-checkout", "d" * 40,
            "--actions-setup-python", "e" * 40,
            "--actions-upload-artifact", "f" * 40,
            "--repo-root", ".",
            "--out-dir", "cw-evidence",
        ]
        args = rsi.parse_argv(argv)
        for attr in ("surface", "repo_root", "out_dir",
                     "actions_checkout", "actions_setup_python",
                     "actions_upload_artifact"):
            assert hasattr(args, attr), f"missing Namespace.{attr}"

    def test_25b_bundle_namespace_has_only_documented_args(self):
        argv = ["bundle", "--out-dir", "cw-evidence"]
        args = rsi.parse_argv(argv)
        assert args.out_dir == "cw-evidence"

    def test_25c_verify_bundle_namespace_has_bundle_dir(self):
        argv = ["verify-bundle", "--bundle-dir", "cw-evidence"]
        args = rsi.parse_argv(argv)
        assert args.bundle_dir == "cw-evidence"

    def test_26_dependency_contract_reads_toml_not_json(self):
        # pyproject.toml is TOML; a JSON parse crashed Head A's measure
        # inside RuntimeSdistIdentityProbe.__init__ before any
        # measurement happened. The sealed project contract must parse.
        contract = rsi.dependency_contract(REPO_ROOT)
        assert contract["name"] == "market-vault"
        assert contract["version"] == "0.7.0"
        assert contract["build_system"]["build_backend"] == (
            "setuptools.build_meta")
        assert contract["pyproject_sha256"]

    def test_26b_read_source_build_contract_parses_toml(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "pyproject.toml").write_text(
                "[build-system]\n"
                'requires = ["setuptools>=68", "wheel"]\n'
                'build-backend = "setuptools.build_meta"\n',
                encoding="utf-8",
            )
            contract = rsi.read_source_build_contract(td)
            assert contract["pyproject_present"] is True
            assert contract["backend"] == "setuptools.build_meta"
            assert contract["requires"] == ["setuptools>=68", "wheel"]

    def test_26c_probe_init_against_sealed_repo(self):
        # The exact constructor that crashed Head A (JSON parse of
        # pyproject.toml) must succeed against the real repo.
        with tempfile.TemporaryDirectory() as td:
            probe = rsi.RuntimeSdistIdentityProbe(
                "test-3.14",
                {"checkout": "d" * 40, "setup_python": "e" * 40,
                 "upload_artifact": "f" * 40},
                REPO_ROOT,
                td,
            )
            assert probe.contract["name"] == "market-vault"

    def test_27_pip26_archive_info_hash_schema_parses(self):
        # pip >= 26 nests the archive hash under download_info.archive_info.
        # hashes; Head A crash #3 raised 'missing/odd sha256 for build' on
        # the real --report JSON from the runner.
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            report = _write_report_pip26(
                {"name": "moomoo-api", "version": "10.9.6908",
                 "url": "https://files.pythonhosted.org/packages/"
                        "moomoo_api-10.9.6908.tar.gz",
                 "sha": SDIST_FIXTURE["sha256"]},
                td,
            )
            records = rsi.parse_pip_report_extended(report)
            assert len(records) == 1
            rec = records[0]
            assert rec["artifact_type"] == "sdist"
            assert rec["sha256"] == SDIST_FIXTURE["sha256"]

    def test_27b_pip26_schema_flat_hash_still_accepted(self):
        # legacy flat download_info.hashes keeps working
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            report = _write_report(
                {"name": "moomoo-api", "version": "10.9.6908",
                 "url": "https://files.pythonhosted.org/packages/"
                        "moomoo_api-10.9.6908.tar.gz",
                 "sha": SDIST_FIXTURE["sha256"]},
                td,
            )
            records = rsi.parse_pip_report_extended(report)
            assert records[0]["artifact_type"] == "sdist"

    def test_27c_pip26_schema_odd_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            report = _write_report_pip26(
                {"name": "moomoo-api", "version": "10.9.6908",
                 "url": "https://files.pythonhosted.org/packages/"
                        "moomoo_api-10.9.6908.tar.gz",
                 "sha": "deadbeef"},
                td,
            )
            with pytest.raises(ValueError, match="missing/odd sha256"):
                rsi.parse_pip_report_extended(report)

    def test_27d_resolve_wheels_only_invokes_pip_module(self, monkeypatch):
        # Head A crash #5: the build-requires resolver ran
        # `python.exe install ...`, so 'install' was parsed as a script
        # path ('can't open file ...\\install', exit 2). The constructed
        # command MUST be `python -m pip install ...` AND carry an
        # ABSOLUTE --report path — the buildhook legs run pip with cwd in
        # a temp extract dir, so a relative report path fails (Head A
        # crash #6: 'OSError: [Errno 2] No such file or directory:
        # cw-evidence-local\\source_build_declared_report.json').
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            report = Path(cmd[cmd.index("--report") + 1])
            entry = {"name": "setuptools", "version": "84.0.0",
                     "url": "https://files.pythonhosted.org/packages/"
                            "setuptools-84.0.0-py3-none-any.whl",
                     "sha": "10" * 32}
            install_entry = {
                "metadata": {"name": entry["name"],
                             "version": entry["version"]},
                "download_info": {"url": entry["url"],
                                  "archive_info": {"hashes": {}}},
            }
            install_entry["download_info"]["archive_info"]["hashes"][
                "sha256"] = entry["sha"]
            report.write_text(
                json.dumps({"install": [install_entry]}), encoding="utf-8")

        monkeypatch.setattr(rsi, "_run", fake_run)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # relative on purpose: the bug was a relative --report path
            # reaching a pip child whose cwd is NOT the repo root
            report_arg = "declared_report.json"
            try:
                resolved = rsi.resolve_wheels_only(
                    "/venv/Scripts/python.exe",
                    ["setuptools>=68", "wheel"],
                    report_arg,
                    None,
                )
            finally:
                Path(report_arg).unlink(missing_ok=True)  # fake pip's file
            assert resolved == [
                {"name": "setuptools", "version": "84.0.0",
                 "filename": "setuptools-84.0.0-py3-none-any.whl",
                 "sha256": "10" * 32},
            ]
            cmd = captured["cmd"]
            assert cmd[:3] == ["/venv/Scripts/python.exe", "-m", "pip"]
            assert cmd[3] == "install"
            assert "--dry-run" in cmd
            assert "--ignore-installed" in cmd
            assert Path(cmd[cmd.index("--report") + 1]).is_absolute()
            assert cmd[-2:] == ["setuptools>=68", "wheel"]

    def test_27e_download_from_report_reads_archive_info_hash(
            self, monkeypatch):
        # Head A crash #7: build-wheel materialization read only the flat
        # download_info.hashes, so it never saw the pip >= 26
        # archive_info.hashes nesting ('cannot materialize build wheel
        # packaging from report' — while the same report parsed fine
        # through parse_pip_report_extended one leg earlier).
        captured = {}

        def fake_download_exact(url, sha, wheelhouse, log_path=None):
            captured["url"] = url
            captured["sha"] = sha
            return Path(wheelhouse) / "fake.whl"

        monkeypatch.setattr(rsi, "_download_exact", fake_download_exact)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            report = td / "declared_report.json"
            install = []
            for name, version, sha in [
                ("setuptools", "84.0.0", "10" * 32),
                ("wheel", "0.48.0", "20" * 32),
                ("packaging", "26.3", "30" * 32),
            ]:
                url = (f"https://files.pythonhosted.org/packages/"
                       f"{name}-{version}-py3-none-any.whl")
                install.append({
                    "metadata": {"name": name, "version": version},
                    "download_info": {"url": url,
                                      "archive_info": {"hashes": {
                                          "sha256": sha}}},
                })
            report.write_text(json.dumps({"install": install}),
                              encoding="utf-8")
            rsi._download_exact_from_report(
                {"name": "packaging", "sha256": "30" * 32},
                report, "wheelhouse", None,
            )
            assert captured["url"].endswith(
                "packaging-26.3-py3-none-any.whl")
            assert captured["sha"] == "30" * 32

    def test_27f_dist_info_probe_code_serializes(self):
        # Head A crash #8: the probe JSON-dumped d._path raw; on Windows
        # AND Linux that is a Path object -> TypeError -> 'distribution
        # moomoo-api not found in venv' although the install report said
        # 'Successfully installed moomoo-api-10.9.6908'.
        proc = subprocess.run(
            [sys.executable, "-c", rsi._DIST_INFO_PROBE_CODE, "pytest"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        assert data["name"] == "pytest"
        assert str(data["path"]).endswith("dist-info")

    def test_27g_record_sha_matches_pep427_prefixed_value(self):
        # Head A crash #9: real pip RECORDs carry 'sha256=<b64>' (PEP
        # 427); the old comparison never stripped the prefix, so every
        # hash-bearing installed file was flagged :SHA256 and an UNTOUCHED
        # install reported 'installed payload changed'.
        data = b"print('hi')\n"
        prefixed = "sha256=" + rsi._b64_sha256(data)
        assert rsi._record_sha_matches(prefixed, data) is True
        assert rsi._record_sha_matches(
            "sha256=" + rsi._b64_sha256(b"other"), data) is False
        # legacy bare form still accepted
        assert rsi._record_sha_matches(rsi._b64_sha256(data), data) is True
        # malformed / unknown algorithm / padding: fail closed
        assert rsi._record_sha_matches("md5=" + "0" * 22, data) is False
        assert rsi._record_sha_matches(
            rsi._b64_sha256(data) + "=", data) is False
        assert rsi._record_sha_matches("", data) is False

    def test_27h_installed_tree_with_pep427_record_valid(self):
        # end-to-end guard for crash #9: a REAL pip-style RECORD (with
        # the sha256= prefix) must verify clean
        with tempfile.TemporaryDirectory() as td:
            root, dist = make_installed_tree(Path(td))
            record = root / dist / "RECORD"
            rows = []
            for line in record.read_text(encoding="utf-8").splitlines():
                rel, want, size = line.split(",")
                rows.append(f"{rel},sha256={want},{size}")
            record.write_text("\n".join(rows) + "\n", encoding="utf-8")
            payload = rsi.verify_installed_payload_at(
                Path(td) / dist, "demo-pkg", "1.0", "1.0")
            assert payload["valid"] is True
            assert payload["reasons"] == []

    def test_27i_verify_install_report_pip26_nested_hash(self):
        # pip >= 26 nests the archive hash under download_info.
        # archive_info.hashes; verify_install_report read only the flat
        # form, so the exact-wheel install was flagged
        # 'report wheel SHA256 != built wheel SHA256' with sha=None (the
        # local run showed install_report_valid=false after a
        # 'Successfully installed moomoo-api-10.9.6908').
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = td / rsi.BUILT_WHEEL_REL / "1" / "demo_pkg-1.0-py3-none-any.whl"
            wheel.parent.mkdir(parents=True)
            wheel.write_bytes(b"wheel-bytes")
            built_sha = hashlib.sha256(b"wheel-bytes").hexdigest()
            report = td / "r.json"
            report.write_text(json.dumps({"install": [
                {"metadata": {"name": "demo-pkg", "version": "1.0"},
                 "download_info": {
                     "url": wheel.as_uri(),
                     "archive_info": {"hashes": {"sha256": built_sha}}}},
            ]}), encoding="utf-8")
            result = rsi.verify_install_report(report, wheel, built_sha)
            assert result["valid"] is True, result

    def test_27j_inventory_probe_canonicalizes_names(self, monkeypatch):
        # The live-env check keyed the inventory by RAW distribution name
        # ('moomoo_api', 'jaraco.classes', 'PyYAML') while the lookup used
        # the canonical form ('moomoo-api', ...) — every such dist came
        # back MISSING and FINAL_RUNTIME_MATCH went false even though the
        # whole runtime was present (local run: 8/42 MISSING, all
        # case/underscore/dot name mismatches). Canonicalization must be
        # inline: crash #12 showed importlib.metadata.canonicalize_name
        # is absent from this env's pythoncore 3.14.
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["code"] = cmd[cmd.index("-c") + 1]
            return types.SimpleNamespace(returncode=0, stdout="{}")

        monkeypatch.setattr(rsi, "_run", fake_run)
        assert rsi._inventory_json("/venv/python.exe") == {}
        assert "re.sub" in captured["code"]
        assert "importlib.metadata.canonicalize_name" not in captured["code"]
        # real interpreter: every inventory key must be canonical
        inv = rsi._inventory_json(sys.executable)
        for key in inv:
            assert key == rsi.canonicalize_name(key), key

    def test_27k_cross_head_compare_doc_not_single_head_required(self):
        # the cross-head compare doc only exists after Head B + offline
        # interpretation; a per-head CI bundle must not require it, and
        # the bundle must not silently drop it when present
        assert "runtime_sdist_identity_compare.json" not in \
            rsi.BUNDLE_REQUIRED_FILES
        assert "runtime_sdist_identity_compare.json" in \
            rsi.CROSS_HEAD_ONLY_FILES
        assert "performance.json" in rsi.BUNDLE_REQUIRED_FILES


# ---------------------------------------------------------------------------
# section 24/31: PEP 427 RECORD self entry (crash #13 families)
# ---------------------------------------------------------------------------


class TestPep427RecordSelfEntry:
    def test_28_record_self_entry_empty_hash_size_accepted(self):
        # PEP 427: RECORD's own entry (normally the last line) carries
        # EMPTY hash and size -- a wheel cannot bind its own bytes.  The
        # replay verifier rejected real bdist_wheel output with
        # 'wheel_record_invalid' until this rule was implemented.
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = make_wheel(td / "demo_pkg-1.0-py3-none-any.whl")
            v = rsi.validate_wheel(wheel, "demo-pkg", "1.0")
            assert v["valid"] is True
            assert v["record_ok"] is True

    def test_28b_record_missing_self_entry_invalid(self):
        # a RECORD that does not list itself is malformed -> fail closed
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = make_wheel(td / "demo_pkg-1.0-py3-none-any.whl")
            dist = "demo_pkg-1.0.dist-info"
            with zipfile.ZipFile(wheel, "r") as zf:
                payloads = {
                    p: zf.read(p) for p in zf.namelist()
                    if p != f"{dist}/RECORD"
                }
            with zipfile.ZipFile(wheel, "w") as zf:
                rows = [f"{p},{b64h(d)},{len(d)}"
                        for p, d in sorted(payloads.items())]
                for p, d in sorted(payloads.items()):
                    zf.writestr(p, d)
                zf.writestr(f"{dist}/RECORD",
                            "\n".join(rows) + "\n")  # no self entry
            v = rsi.validate_wheel(wheel, "demo-pkg", "1.0")
            assert v["valid"] is False
            assert "RECORD does not list itself" in v["reasons"]

    def test_28c_record_self_entry_with_hash_invalid(self):
        # a self entry carrying a hash or size is a lie (self-binding is
        # impossible) -> fail closed
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel = make_wheel(td / "demo_pkg-1.0-py3-none-any.whl")
            dist = "demo_pkg-1.0.dist-info"
            with zipfile.ZipFile(wheel, "r") as zf:
                payloads = {
                    p: zf.read(p) for p in zf.namelist()
                    if p != f"{dist}/RECORD"
                }
            with zipfile.ZipFile(wheel, "w") as zf:
                rows = [f"{p},{b64h(d)},{len(d)}"
                        for p, d in sorted(payloads.items())]
                rows.append(f"{dist}/RECORD,sha256={b64h(b'x')},3")
                for p, d in sorted(payloads.items()):
                    zf.writestr(p, d)
                zf.writestr(f"{dist}/RECORD", "\n".join(rows) + "\n")
            v = rsi.validate_wheel(wheel, "demo-pkg", "1.0")
            assert v["valid"] is False
            assert "empty hash and size" in " ".join(v["reasons"])


# ---------------------------------------------------------------------------
# section 31: canonical fingerprint is order-independent (crash #13)
# ---------------------------------------------------------------------------


class TestFingerprintOrderIndependence:
    def test_29_fingerprint_invariant_under_key_permutation(self):
        # crash #13: _sort_arrays sorted lists by json.dumps(sort_keys=
        # False), whose key strings depend on dict KEY INSERTION ORDER --
        # the same document in a different key order got a different
        # fingerprint, so the stored fingerprint never matched the
        # verifier's recompute over the (recursively key-sorted) read-back.
        doc = make_identity()
        base = rsi.compute_fingerprint_sha(doc)
        permuted = copy.deepcopy(doc)
        permuted["resolved_distributions"] = [
            {k: r[k] for k in reversed(list(r.keys()))}
            for r in doc["resolved_distributions"]
        ]
        permuted["marketvault_build_identity"] = {
            k: permuted["marketvault_build_identity"][k]
            for k in reversed(list(permuted["marketvault_build_identity"].keys()))
        }
        assert rsi.compute_fingerprint_sha(permuted) == base

    def test_29b_fingerprint_survives_json_round_trip(self):
        # the fingerprint the measure stores must equal the verifier's
        # recompute over the file it wrote (write_json sorts keys
        # recursively; canonical_payload must produce the same form)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identity.json"
            doc = make_identity()
            rsi.write_json(path, doc)
            read_back = rsi.read_json(path)
            assert read_back["fingerprint_sha256"] == \
                rsi.compute_fingerprint_sha(read_back)

    def test_29c_verdicts_from_summary_round_trip(self):
        text = (
            "SOURCE_BUILD_IDENTITY_VALID=false\n"
            "reason=see per-leg verdicts in probe_summary.txt\n"
            "RUNTIME_OTHER_COUNT=0\n"
            "RUNTIME_SDIST_COUNT=1\n"
            "RAW_WHEEL_REPRODUCIBLE_moomoo-api=false\n"
            "reason=build1 aaaa != build2 bbbb\n"
            "FINAL_RUNTIME_MATCH=true\n"
            "MEASURE_CRASH=false\n"
        )
        verdicts = rsi._verdicts_from_summary_text(text)
        assert verdicts["SOURCE_BUILD_IDENTITY_VALID"] is False
        assert verdicts["RUNTIME_OTHER_COUNT"] == 0
        assert verdicts["RUNTIME_SDIST_COUNT"] == 1
        assert verdicts["RAW_WHEEL_REPRODUCIBLE_moomoo-api"] is False
        assert verdicts["FINAL_RUNTIME_MATCH"] is True
        assert verdicts["MEASURE_CRASH"] is False
        assert "reason" not in verdicts


# ---------------------------------------------------------------------------
# section 31: manifest self entry cannot bind itself
# ---------------------------------------------------------------------------


class TestManifestSelfEntry:
    def test_30_manifest_records_null_self_hash(self):
        # the manifest lists itself (BUNDLE_REQUIRED_FILES requires it)
        # but must record null size/sha256 for its own entry -- a stale
        # pre-write hash made every replay's manifest_hashes fail
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "probe_summary.txt").write_text(
                "RUNTIME_SDIST_COUNT=1\n", encoding="utf-8")
            # cmd_bundle writes the manifest twice (before and after the
            # verifier self-copy); only the second call can list itself
            rsi._write_manifest(root, ["probe_summary.txt"])
            manifest = rsi._write_manifest(root, ["probe_summary.txt"])
            self_entry = next(
                e for e in manifest["files"]
                if e["path"] == rsi.MANIFEST_NAME)
            assert self_entry["sha256"] is None
            assert self_entry["size"] is None
            other = next(
                e for e in manifest["files"]
                if e["path"] == "probe_summary.txt")
            assert other["sha256"] is not None
            assert other["size"] is not None

    def test_30b_verifier_accepts_null_self_entry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "probe_summary.txt").write_text(
                "RUNTIME_SDIST_COUNT=1\n", encoding="utf-8")
            # as in cmd_bundle: first pass writes the manifest, the second
            # pass includes the (null-hashed) self entry
            rsi._write_manifest(root, ["probe_summary.txt"])
            rsi._write_manifest(root, ["probe_summary.txt"])
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            # completeness is not the point here (the sparse test bundle
            # lacks the full required set); the self entry must verify
            assert verifier.checks.get("manifest_hashes") is True

    def test_30c_verifier_rejects_stale_self_hash(self):
        # a manifest that records its own hash is either stale or a lie
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "probe_summary.txt").write_text(
                "RUNTIME_SDIST_COUNT=1\n", encoding="utf-8")
            rsi.write_json(root / "EVIDENCE_MANIFEST.json", {
                "schema_version": rsi.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [
                    {"path": "probe_summary.txt", "size": 20,
                     "sha256": "11" * 32},
                    {"path": rsi.MANIFEST_NAME, "size": 123,
                     "sha256": "22" * 32},
                ],
            })
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            assert verifier.checks.get("manifest_hashes") is False
            assert rsi.MANIFEST_NAME + ":SELF_HASH" in (
                verifier.checks.get("manifest_hashes_detail") or "")


# ---------------------------------------------------------------------------
# section 31: recorded flags are a consistency check, not a pass/fail
# ---------------------------------------------------------------------------


class TestRecordedFlagsConsistency:
    def _run_verifier(self, receipt, summary_text):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rsi.write_json(root / "runtime_sdist_identity_receipt.json",
                           receipt)
            (root / "probe_summary.txt").write_text(summary_text,
                                                    encoding="utf-8")
            rsi.write_json(root / "EVIDENCE_MANIFEST.json", {
                "schema_version": rsi.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [],
            })
            verifier = rsi.BundleVerifier(root)
            verifier.verify()
            return verifier.checks.get("recorded_flags")

    def test_31_measured_invalid_identity_still_replays(self):
        # a measured valid=false (e.g. raw wheel bytes not reproducible)
        # is legitimate evidence: the receipt must AGREE with the derived
        # verdict, not claim true
        receipt = {
            "schema_version": rsi.SCHEMA_VERSION,
            "surface": "test-3.14",
            "source_build_identity_valid": False,
            "final_runtime_match": True,
        }
        summary = (
            "SOURCE_BUILD_IDENTITY_VALID=false\n"
            "FINAL_RUNTIME_MATCH=true\n"
            "RUNTIME_OTHER_COUNT=0\n"
            "RUNTIME_SDIST_COUNT=1\n"
            "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL=true\n"
            "RUNTIME_INSTALL_FROM_WHEELS_ONLY=true\n"
            "SHADOW_SURFACE_PASS=true\n"
            "MEASURE_CRASH=false\n"
            "RAW_WHEEL_REPRODUCIBLE_moomoo-api=false\n"
        )
        assert self._run_verifier(receipt, summary) is True

    def test_31b_receipt_disagreeing_with_summary_fails(self):
        # receipt claims valid=true but the retained verdicts derive
        # false -> the bundle is self-inconsistent -> replay fails closed
        receipt = {
            "schema_version": rsi.SCHEMA_VERSION,
            "surface": "test-3.14",
            "source_build_identity_valid": True,
            "final_runtime_match": True,
        }
        summary = (
            "SOURCE_BUILD_IDENTITY_VALID=false\n"
            "FINAL_RUNTIME_MATCH=true\n"
            "RUNTIME_OTHER_COUNT=0\n"
            "RUNTIME_SDIST_COUNT=1\n"
            "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL=true\n"
            "RUNTIME_INSTALL_FROM_WHEELS_ONLY=true\n"
            "SHADOW_SURFACE_PASS=true\n"
            "MEASURE_CRASH=false\n"
            "RAW_WHEEL_REPRODUCIBLE_moomoo-api=false\n"
        )
        assert self._run_verifier(receipt, summary) is False

    def test_31c_summary_final_match_disagreement_fails(self):
        receipt = {
            "schema_version": rsi.SCHEMA_VERSION,
            "surface": "test-3.14",
            "source_build_identity_valid": False,
            "final_runtime_match": True,
        }
        summary = (
            "SOURCE_BUILD_IDENTITY_VALID=false\n"
            "FINAL_RUNTIME_MATCH=false\n"
            "RUNTIME_OTHER_COUNT=0\n"
            "RUNTIME_SDIST_COUNT=1\n"
            "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL=true\n"
            "RUNTIME_INSTALL_FROM_WHEELS_ONLY=true\n"
            "SHADOW_SURFACE_PASS=true\n"
            "MEASURE_CRASH=false\n"
            "RAW_WHEEL_REPRODUCIBLE_moomoo-api=false\n"
        )
        assert self._run_verifier(receipt, summary) is False


class TestInstallReportBundleSlot:
    # The bundle is relocated between the measure's out-dir and the replay
    # dir (ci.yml copies cw-evidence/. into replay-bundle/), so absolute
    # path equality can never hold at replay time.  The exact local wheel
    # is identified by its slot: <any-prefix>/built_wheels/1/<filename>.

    def _wheel(self, td):
        wheel = td / rsi.BUILT_WHEEL_REL / "1" / "demo_pkg-1.0-py3-none-any.whl"
        wheel.parent.mkdir(parents=True, exist_ok=True)
        wheel.write_bytes(b"wheel-bytes")
        return wheel, hashlib.sha256(b"wheel-bytes").hexdigest()

    def _report(self, td, url, sha):
        path = td / "r.json"
        path.write_text(json.dumps({"install": [
            {"metadata": {"name": "demo-pkg", "version": "1.0"},
             "download_info": {"url": url, "hashes": {"sha256": sha}}},
        ]}), encoding="utf-8")
        return path

    def test_32_relocated_bundle_still_valid(self):
        # recorded URL points at the ORIGINAL out-dir (cw-evidence), the
        # wheel passed by the verifier lives in the replay dir: different
        # absolute prefixes, same built_wheels/1/<filename> slot -> valid
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel, built_sha = self._wheel(td)
            out_dir = td.parent / "cw-evidence"
            url = out_dir.joinpath(
                rsi.BUILT_WHEEL_REL, "1", wheel.name).as_uri()
            result = rsi.verify_install_report(
                self._report(td, url, built_sha), wheel, built_sha)
            assert result["valid"] is True, result

    def test_32b_rebuilt_wheel_slot_rejected(self):
        # the rebuilt wheel slot built_wheels/2 must never satisfy the
        # exact-wheel check: different cached/rebuilt bytes are not the
        # installed artifact even when the basename is identical
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel, built_sha = self._wheel(td)
            other = td / rsi.BUILT_WHEEL_REL / "2" / wheel.name
            other.parent.mkdir(parents=True)
            result = rsi.verify_install_report(
                self._report(td, other.as_uri(), built_sha), wheel, built_sha)
            assert result["valid"] is False
            assert "exact local wheel" in result["reasons"][0]

    def test_32c_pip_cache_style_url_rejected(self):
        # a pip-cache artifact carries cache-hash path components, not the
        # built_wheels/1 slot
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel, built_sha = self._wheel(td)
            cached = td / "pip-cache" / "abc123" / wheel.name
            cached.parent.mkdir(parents=True)
            result = rsi.verify_install_report(
                self._report(td, cached.as_uri(), built_sha), wheel, built_sha)
            assert result["valid"] is False
            assert "exact local wheel" in result["reasons"][0]

    def test_32d_non_file_url_rejected(self):
        # an index-resolved install (https) is never the exact local wheel
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            wheel, built_sha = self._wheel(td)
            url = ("https://pypi.org/packages/"
                   f"{rsi.BUILT_WHEEL_REL}/1/{wheel.name}")
            result = rsi.verify_install_report(
                self._report(td, url, built_sha), wheel, built_sha)
            assert result["valid"] is False
            assert "file:// wheel" in result["reasons"][0]


def _write_report(entry, td):
    """Fabricate a pip --report JSON on disk (one install entry)."""
    path = Path(td) / "report.json"
    install_entry = {
        "metadata": {"name": entry["name"], "version": entry["version"]},
        "download_info": {"url": entry["url"], "hashes": {}},
    }
    if entry.get("sha"):
        install_entry["download_info"]["hashes"]["sha256"] = entry["sha"]
    path.write_text(json.dumps({"install": [install_entry]}),
                    encoding="utf-8")
    return path


def _write_report_pip26(entry, td):
    """pip >= 26 report schema: archive_info.hashes nested under
    download_info (Head A crash #3 was a parse of this exact shape)."""
    path = Path(td) / "report.json"
    install_entry = {
        "metadata": {"name": entry["name"], "version": entry["version"]},
        "download_info": {"url": entry["url"], "archive_info": {"hashes": {}}},
    }
    if entry.get("sha"):
        install_entry["download_info"]["archive_info"]["hashes"]["sha256"] = (
            entry["sha"])
    path.write_text(json.dumps({"install": [install_entry]}),
                    encoding="utf-8")
    return path
