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
import tempfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "ci_runtime_sdist_identity.py"
)

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
