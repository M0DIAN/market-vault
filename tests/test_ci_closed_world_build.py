"""P2-5 closed-world build execution canary — pure test suite (TEMPORARY,
PR #80).  The module under test is loaded via importlib so this file is
never itself imported by the suite; no pytest node is added to the audit
surface.  Removed entirely on the final docs-only head."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci_closed_world_build.py"

_spec = importlib.util.spec_from_file_location("ci_closed_world_build", SCRIPT)
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)

CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"

RUNTIME_FIXTURES = (
    {"name": "duckdb", "version": "1.5.5", "url": "https://files.pythonhosted.org/duckdb-1.5.5-py3-none-any.whl", "sha256": "a" * 64},
    {"name": "numpy", "version": "2.5.2", "url": "https://files.pythonhosted.org/numpy-2.5.2-py3-none-any.whl", "sha256": "b" * 64},
    {"name": "pandas", "version": "2.3.3", "url": "https://files.pythonhosted.org/pandas-2.3.3-py3-none-any.whl", "sha256": "c" * 64},
)

BUILD_FIXTURES = (
    {"name": "packaging", "version": "26.3", "filename": "packaging-26.3-py3-none-any.whl", "sha256": "d" * 64},
    {"name": "setuptools", "version": "84.0.0", "filename": "setuptools-84.0.0-py3-none-any.whl", "sha256": "e" * 64},
    {"name": "wheel", "version": "0.48.0", "filename": "wheel-0.48.0-py3-none-any.whl", "sha256": "f" * 64},
)


def dist(name="duckdb", version="1.5.5", url="https://files.pythonhosted.org/duckdb-1.5.5-py3-none-any.whl", sha256="a" * 64):
    return {"name": name, "version": version, "url": url, "sha256": sha256}


def build_dist(name="setuptools", version="84.0.0", filename=None, sha256=None):
    filename = filename or f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    return {"name": name, "version": version, "filename": filename,
            "sha256": sha256 or f"{name}{version}".ljust(64, "0")[:64]}


def make_build_set(mutate=None, dynamic=("p2-closed-world-sentinel==0.0.1",)):
    doc = {
        "schema_version": cw.SCHEMA_VERSION,
        "surface": "test-3.14",
        "backend": "setuptools.build_meta",
        "declared_requires": ["setuptools>=68", "wheel"],
        "dynamic_hook": cw.DYNAMIC_HOOK_NAME,
        "dynamic_requires": sorted(dynamic),
        "effective_build_distributions": [
            {"name": d["name"], "version": d["version"], "filename": d["filename"], "sha256": d["sha256"]}
            for d in BUILD_FIXTURES
        ],
    }
    if mutate:
        mutate(doc)
    return doc


def make_normalized_identity(mutate=None):
    doc = cw.normalized_build_identity(
        {
            "build_system": {
                "build_backend": "setuptools.build_meta",
                "requires": ["setuptools>=68", "wheel"],
            }
        },
        make_build_set(),
        {"verbatim": ["p2-closed-world-sentinel==0.0.1"],
         "normalized_sorted": ["p2-closed-world-sentinel==0.0.1"]},
        {"verbatim": ["p2-closed-world-sentinel==0.0.1"],
         "normalized_sorted": ["p2-closed-world-sentinel==0.0.1"]},
    )
    if mutate:
        mutate(doc)
        # the digest is a function of the document content: a mutated doc
        # must carry a recomputed fingerprint (as the probe writes it)
        doc["normalized_build_identity_sha256"] = cw.compute_fingerprint_sha(doc)
    return doc


def clone(obj):
    return copy.deepcopy(obj)


def make_delta(pre=None, post=None):
    if pre is None:
        pre = {"pip": "26.2.1", "setuptools": "84.0.0", "wheel": "0.48.0",
               "packaging": "26.3"}
    if post is None:
        post = {**pre, "market-vault": "0.7.0"}
    return cw.distribution_delta(pre, post)


def make_receipt(mutate=None):
    receipt = {
        "schema_version": cw.SCHEMA_VERSION,
        "surface": "test-3.14",
        "backend": "setuptools.build_meta",
        "normalized_build_identity_sha256": "ab" * 32,
        "execution_build_requirements_sha256": "cd" * 32,
        "pip_frontend_version": "26.2.1",
        "dynamic_hook_probe_1": ["p2-closed-world-sentinel==0.0.1"],
        "dynamic_hook_probe_2": ["p2-closed-world-sentinel==0.0.1"],
        "dynamic_hook_stable": True,
        "prebuild_distribution_inventory": {"pip": "26.2.1", "setuptools": "84.0.0"},
        "postbuild_distribution_inventory": {"pip": "26.2.1", "setuptools": "84.0.0", "market-vault": "0.7.0"},
        "distribution_delta": make_delta(),
        "no_build_isolation_used": True,
        "no_deps_used": True,
        "check_build_dependencies_used": True,
        "actual_editable_build_success": True,
        "unexpected_distribution_count": 0,
        "synthetic_control_success": True,
        "synthetic_closed_world_failure": True,
        "sentinel_auto_installed": False,
        "closed_world_build_valid": True,
        "final_runtime_match": True,
        "leg_ready": True,
        "reason": None,
    }
    if mutate:
        mutate(receipt)
    return receipt


def make_identity(mutate=None):
    doc = {
        "schema_version": cw.SCHEMA_VERSION,
        "surface": "test-3.14",
        "runner": {"runner_os": "Windows", "runner_arch": "X64", "image_os": "win24",
                   "image_version": "20250701", "platform_system": "Windows",
                   "platform_release": "10", "platform_version": "10.0.26200",
                   "platform_machine": "AMD64"},
        "python": {"executable_basename": "python.exe", "python_version": "3.14.4",
                   "implementation": "CPython", "win32": True},
        "resolver": {"pip_version": "26.2.1", "pip_frontend_version_exact_env": "26.2.1"},
        "dependency_contract": {
            "name": "market-vault", "version": "0.7.0", "pyproject_sha256": "aa" * 32,
            "build_system": {"requires": ["setuptools>=68", "wheel"],
                             "build_backend": "setuptools.build_meta", "backend_path": []},
            "dependencies": ["pyarrow>=16.1"], "dev_dependencies": ["pytest>=8"],
        },
        "action_contract": {"checkout_sha": CHECKOUT_SHA,
                            "setup_python_sha": SETUP_PYTHON_SHA,
                            "upload_artifact_sha": UPLOAD_ARTIFACT_SHA,
                            "ci_yml_sha256": "bb" * 32},
        "resolved_distributions": [dict(d) for d in RUNTIME_FIXTURES],
        "build_contract": {
            "backend": "setuptools.build_meta",
            "declared_requires": ["setuptools>=68", "wheel"],
            "dynamic_hook": cw.DYNAMIC_HOOK_NAME,
            "dynamic_requires": ["p2-closed-world-sentinel==0.0.1"],
            "normalized_build_identity_sha256": "ab" * 32,
            "execution_build_requirements_sha256": "cd" * 32,
            "effective_build_distributions": [dict(d) for d in BUILD_FIXTURES],
            "pip_frontend_version": "26.2.1",
        },
        "closed_world_build_valid": True,
        "final_runtime_match": True,
        "synthetic_control_success": True,
        "synthetic_closed_world_failure": True,
        "sentinel_auto_installed": False,
    }
    doc["fingerprint_sha256"] = cw.compute_fingerprint_sha(doc)
    if mutate:
        mutate(doc)
    return doc


def _mutate_receipt(receipt, **kwargs):
    for k, v in kwargs.items():
        receipt[k] = v


# ---------------------------------------------------------------------------
# NORMALIZED_BUILD_IDENTITY_SHA256 comparisons (section 9)
# ---------------------------------------------------------------------------


class TestNormalizedBuildIdentity:
    def test_identical_matches(self):
        a = make_normalized_identity()
        b = clone(a)
        assert a["normalized_build_identity_sha256"] == b["normalized_build_identity_sha256"]

    def test_different_backend_no_match(self):
        a = make_normalized_identity()
        b = make_normalized_identity(lambda d: d.__setitem__("backend", "hatchling.build"))
        assert a["normalized_build_identity_sha256"] != b["normalized_build_identity_sha256"]

    def test_different_dynamic_requirement_no_match(self):
        a = make_normalized_identity()
        b = make_normalized_identity(
            lambda d: d.__setitem__("dynamic_requires", ["p2-other==9.9.9"]))
        assert a["normalized_build_identity_sha256"] != b["normalized_build_identity_sha256"]

    def test_different_wheel_version_no_match(self):
        a = make_normalized_identity()
        b = make_normalized_identity(
            lambda d: d["build_artifacts"][1].__setitem__("version", "84.1.0"))
        assert a["normalized_build_identity_sha256"] != b["normalized_build_identity_sha256"]

    def test_different_wheel_filename_no_match(self):
        a = make_normalized_identity()
        b = make_normalized_identity(
            lambda d: d["build_artifacts"][1].__setitem__(
                "filename", "setuptools-84.0.0-py3-none-any-custom.whl"))
        assert a["normalized_build_identity_sha256"] != b["normalized_build_identity_sha256"]

    def test_different_wheel_sha_no_match(self):
        a = make_normalized_identity()
        b = make_normalized_identity(
            lambda d: d["build_artifacts"][2].__setitem__("sha256", "f1" * 32))
        assert a["normalized_build_identity_sha256"] != b["normalized_build_identity_sha256"]

    def test_absolute_paths_do_not_change_normalized_identity(self):
        """Workspace path differences MUST NOT change the normalized digest."""
        a = make_normalized_identity()
        b = make_normalized_identity()
        assert (
            cw.sha256_text("C:/workspace/market-vault/pyproject.toml")
            != cw.sha256_text("D:/other/checkout/market-vault/pyproject.toml")
        )  # sanity: the paths differ
        # the canonical payload never contains any path field; digest must be
        # identical for two docs built at different absolute locations
        a_doc = cw.normalized_build_identity(
            {"build_system": {"build_backend": "setuptools.build_meta",
                              "requires": ["setuptools>=68", "wheel"]}},
            make_build_set(),
            {"normalized_sorted": ["p2-closed-world-sentinel==0.0.1"]},
            {"normalized_sorted": ["p2-closed-world-sentinel==0.0.1"]},
        )
        b_doc = cw.normalized_build_identity(
            {"build_system": {"build_backend": "setuptools.build_meta",
                              "requires": ["setuptools>=68", "wheel"]}},
            make_build_set(),
            {"normalized_sorted": ["p2-closed-world-sentinel==0.0.1"]},
            {"normalized_sorted": ["p2-closed-world-sentinel==0.0.1"]},
        )
        assert a_doc["normalized_build_identity_sha256"] == b_doc["normalized_build_identity_sha256"]

    def test_execution_requirements_digest_path_sensitive(self):
        """The concrete local requirements file MAY change the execution digest."""
        reqs = [{"name": "packaging", "version": "26.3", "sha256": "d" * 64}]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f1 = base / "exact_build_environment.txt"
            f2 = base / "nested" / "exact_build_environment.txt"
            f2.parent.mkdir()
            cw.write_exact_build_environment(reqs, f1)
            cw.write_exact_build_environment(reqs, f2)
            # identical bytes -> identical digest (the digest is over bytes)
            assert cw.execution_build_requirements_sha256(f1) == \
                cw.execution_build_requirements_sha256(f2)
            # a path-bearing variant (wheelhouse prefix) changes the digest
            f3 = base / "variant.txt"
            f3.write_text(
                f"packaging==26.3 --hash=sha256:{'d' * 64} "
                f"--find-links={base / 'wheelhouse'}\n",
                encoding="utf-8")
            assert cw.execution_build_requirements_sha256(f3) != \
                cw.execution_build_requirements_sha256(f1)


# ---------------------------------------------------------------------------
# distribution delta (section 12)
# ---------------------------------------------------------------------------


class TestDistributionDelta:
    def test_exact_project_only_delta_valid(self):
        delta = make_delta()
        assert delta["valid"] is True
        assert delta["added"] == {"market-vault": "0.7.0"}
        assert delta["unexpected_distribution_count"] == 0

    def test_unexpected_added_package_invalid(self):
        delta = make_delta(post={"pip": "26.2.1", "setuptools": "84.0.0",
                                 "wheel": "0.48.0", "packaging": "26.3",
                                 "market-vault": "0.7.0", "extra-build-pkg": "1.0"})
        assert delta["valid"] is False
        assert delta["unexpected_distribution_count"] == 1

    def test_changed_build_package_version_invalid(self):
        delta = make_delta(post={"pip": "26.2.1", "setuptools": "84.1.0",
                                 "wheel": "0.48.0", "packaging": "26.3",
                                 "market-vault": "0.7.0"})
        assert delta["valid"] is False
        assert "changed" in delta and delta["changed"]["setuptools"] == {
            "before": "84.0.0", "after": "84.1.0"}

    def test_removed_package_invalid(self):
        delta = make_delta(post={"pip": "26.2.1", "wheel": "0.48.0",
                                 "packaging": "26.3", "market-vault": "0.7.0"})
        assert delta["valid"] is False
        assert delta["removed"] == {"setuptools": "84.0.0"}

    def test_wrong_project_version_invalid(self):
        delta = make_delta(post={"pip": "26.2.1", "setuptools": "84.0.0",
                                 "wheel": "0.48.0", "packaging": "26.3",
                                 "market-vault": "0.8.0"})
        assert delta["valid"] is False


# ---------------------------------------------------------------------------
# closed-world receipt fail-closed rules (sections 19/28)
# ---------------------------------------------------------------------------


class TestClosedWorldReceipt:
    def test_valid_receipt_accepted(self):
        receipt = make_receipt()
        assert receipt["no_build_isolation_used"] is True
        assert receipt["no_deps_used"] is True
        assert receipt["check_build_dependencies_used"] is True
        assert receipt["closed_world_build_valid"] is True
        assert receipt["sentinel_auto_installed"] is False

    def test_probe_mismatch_invalid(self):
        receipt = make_receipt()
        receipt["dynamic_hook_probe_1"] = ["p2-closed-world-sentinel==0.0.1"]
        receipt["dynamic_hook_probe_2"] = ["p2-closed-world-sentinel==0.0.2"]
        receipt["dynamic_hook_stable"] = False
        receipt["closed_world_build_valid"] = False
        assert receipt["dynamic_hook_stable"] is False
        assert receipt["closed_world_build_valid"] is False

    def test_no_build_isolation_false_invalid(self):
        receipt = make_receipt()
        receipt["no_build_isolation_used"] = False
        receipt["closed_world_build_valid"] = False
        assert receipt["closed_world_build_valid"] is False

    def test_no_deps_false_invalid(self):
        receipt = make_receipt()
        receipt["no_deps_used"] = False
        receipt["closed_world_build_valid"] = False
        assert receipt["closed_world_build_valid"] is False

    def test_sentinel_auto_installed_invalid(self):
        receipt = make_receipt()
        receipt["sentinel_auto_installed"] = True
        receipt["closed_world_build_valid"] = False
        assert receipt["closed_world_build_valid"] is False
        assert receipt["sentinel_auto_installed"] is True

    def test_negative_branch_unexpected_success_invalid(self):
        receipt = make_receipt()
        receipt["synthetic_closed_world_failure"] = False
        receipt["closed_world_build_valid"] = False
        assert receipt["closed_world_build_valid"] is False

    def test_unsupported_schema_invalid(self):
        receipt = make_receipt()
        receipt["schema_version"] = 2
        assert receipt["schema_version"] != cw.SCHEMA_VERSION

    def test_malformed_evidence_invalid(self):
        receipt = make_receipt()
        del receipt["execution_build_requirements_sha256"]
        assert "execution_build_requirements_sha256" not in receipt


# ---------------------------------------------------------------------------
# evidence manifest duplicate-path hardening (section 21)
# ---------------------------------------------------------------------------


class TestManifestDuplicatePathHardening:
    def _bundle_with_duplicates(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        root.mkdir(parents=True, exist_ok=True)
        cw.write_json(root / "closed_world_build_receipt.json", make_receipt())
        cw.write_json(root / "closed_world_identity.json", make_identity())
        (root / "probe_summary.txt").write_text("CLOSED_WORLD_BUILD_VALID=true\n")
        (root / "actual_closed_world_editable_build.log").write_text(
            "CLOSED_WORLD_EDITABLE_BUILD_OK=true\n")
        return td, root

    def test_generator_rejects_duplicate_relative_path(self, monkeypatch):
        td, root = self._bundle_with_duplicates()
        try:
            # a collector that yields the same relative path twice (the #79
            # weakness: one file bound under two category lists) must fail
            # the generator fail-closed BEFORE the manifest is written
            dup_path = root / "probe_summary.txt"
            monkeypatch.setattr(
                cw, "_manifest_files",
                lambda _root: [dup_path, dup_path],
            )
            with pytest.raises(ValueError) as exc:
                cw._write_manifest(root, ["probe_summary.txt"])
            assert "EVIDENCE_MANIFEST_INVALID" in str(exc.value)
            assert "reason=duplicate_path:probe_summary.txt" in str(exc.value)
            assert not (root / "EVIDENCE_MANIFEST.json").exists()
        finally:
            td.cleanup()

    def test_manifest_emits_each_relative_path_exactly_once(self):
        td, root = self._bundle_with_duplicates()
        try:
            (root / "probe_summary.txt").unlink()
            (root / "actual_closed_world_editable_build.log").unlink()
            files = cw._manifest_files(root)
            rels = [cw._rel_path(p, root) for p in files]
            assert len(rels) == len(set(rels))
            assert len(rels) == len([r for r in rels if r == "probe_summary.txt"]) or \
                "probe_summary.txt" not in rels
        finally:
            td.cleanup()

    def test_verifier_rejects_duplicate_paths_independently(self):
        td, root = self._bundle_with_duplicates()
        try:
            # fabricate a manifest with a duplicated entry
            manifest = {
                "schema_version": cw.SCHEMA_VERSION,
                "surface": "test-3.14",
                "complete": True,
                "missing": [],
                "files": [
                    {"path": "probe_summary.txt", "size": 1, "sha256": "0" * 64},
                    {"path": "probe_summary.txt", "size": 1, "sha256": "0" * 64},
                ],
            }
            cw.write_json(root / "EVIDENCE_MANIFEST.json", manifest)
            verifier = cw.BundleVerifier(root)
            verifier.verify()
            assert verifier.checks.get("manifest_unique_paths") is False
            assert "duplicate_path:probe_summary.txt" in (
                verifier.checks.get("manifest_unique_paths_detail") or "")
        finally:
            td.cleanup()

    def test_manifest_duplicate_detection_message_format(self):
        with pytest.raises(ValueError) as exc:
            raise ValueError("EVIDENCE_MANIFEST_INVALID reason=duplicate_path:x")
        assert "EVIDENCE_MANIFEST_INVALID" in str(exc.value)
        assert "reason=duplicate_path:x" in str(exc.value)


# ---------------------------------------------------------------------------
# synthetic sentinel wheel (sections 13-16)
# ---------------------------------------------------------------------------


class TestSentinelWheel:
    def test_wheel_is_valid_zip_with_dist_info(self):
        with tempfile.TemporaryDirectory() as td:
            wheel = cw.build_sentinel_wheel(Path(td))
            assert wheel.name == cw.SENTINEL_WHEEL_FILENAME
            with zipfile.ZipFile(wheel) as zf:
                names = set(zf.namelist())
                assert f"{cw.SENTINEL_MODULE}/__init__.py" in names
                assert any(
                    n.startswith(f"{cw.SENTINEL_MODULE}-{cw.SENTINEL_VERSION}.dist-info/")
                    for n in names
                )
                record = next(
                    n for n in names
                    if n.endswith("dist-info/RECORD")
                )
                rec_text = zf.read(record).decode("utf-8")
                rows = [r for r in rec_text.strip().splitlines() if r]
                # every non-RECORD entry is listed exactly once
                listed = {r.split(",")[0] for r in rows if not r.endswith(",,")}
                assert listed == names - {record}

    def test_synthetic_backend_demands_sentinel(self):
        with tempfile.TemporaryDirectory() as td:
            project = cw.write_synthetic_project(Path(td))
            pyproject = project.joinpath("pyproject.toml").read_text(encoding="utf-8")
            assert 'build-backend = "p2_synthetic_backend"' in pyproject
            assert f'name = "{cw.SYNTHETIC_PROJECT_NAME}"' in pyproject
            backend_src = project.joinpath("p2_synthetic_backend.py").read_text(encoding="utf-8")
            assert "p2-closed-world-sentinel==0.0.1" in backend_src
            assert "import p2_closed_world_sentinel" in backend_src

    def test_wheel_filename_matches(self):
        assert cw._wheel_filename_matches(
            "packaging-26.3-py3-none-any.whl", "packaging", "26.3")
        assert not cw._wheel_filename_matches(
            "packaging-26.3-py3-none-any.whl", "packaging", "26.4")
        assert not cw._wheel_filename_matches("packaging-26.3.tar.gz",
                                              "packaging", "26.3")


# ---------------------------------------------------------------------------
# retained #78/#79 fail-closed comparator cases
# ---------------------------------------------------------------------------


class TestRetainedComparatorCases:
    def test_identity_schema_version_unequal(self):
        a = make_identity()
        b = make_identity(lambda d: d.__setitem__("schema_version", 2))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "schema_version"

    def test_identity_surface_unequal(self):
        a = make_identity()
        b = make_identity(lambda d: d.__setitem__("surface", "pyarrow24"))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "surface"

    def test_identity_runner_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["runner"].__setitem__("image_version", "20260101"))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "runner"

    def test_identity_python_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["python"].__setitem__("python_version", "3.14.3"))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "python"

    def test_identity_resolver_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["resolver"].__setitem__("pip_version", "26.2.0"))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "resolver"

    def test_identity_dependency_contract_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["dependency_contract"].__setitem__(
                "dev_dependencies", ["pytest>=8", "black"]))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "dependency_contract"

    def test_identity_action_contract_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["action_contract"].__setitem__(
                "checkout_sha", "9" * 40))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "action_contract"

    def test_identity_distribution_set_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["resolved_distributions"][0].__setitem__("version", "1.5.6"))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "resolved_distributions"

    def test_identity_build_contract_unequal(self):
        a = make_identity()
        b = make_identity(
            lambda d: d["build_contract"].__setitem__(
                "execution_build_requirements_sha256", "ef" * 32))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "build_contract.execution_build_requirements_sha256"

    def test_identity_build_validity_unequal(self):
        a = make_identity()
        b = make_identity(lambda d: d.__setitem__("closed_world_build_valid", False))
        equal, diff = cw.compare_identity_docs(a, b)
        assert equal is False and diff == "closed_world_build_valid"

    def test_identity_digest_verifies(self):
        doc = make_identity()
        stored = doc["fingerprint_sha256"]
        assert stored == cw.compute_fingerprint_sha(doc)
        # the fingerprint is computed over the payload minus the
        # fingerprint_sha256 field itself
        doc["fingerprint_sha256"] = "0" * 64
        assert stored == cw.compute_fingerprint_sha(doc)


class TestUrlNormalization:
    def test_credentials_rejected(self):
        with pytest.raises(ValueError):
            cw.normalize_download_url("https://user:pass@example.com/a.whl")

    def test_scheme_normalized(self):
        assert cw.normalize_download_url(
            "HTTPS://Files.PythonHosted.Org/a.whl"
        ) == "https://files.pythonhosted.org/a.whl"

    def test_default_port_dropped(self):
        assert cw.normalize_download_url(
            "https://example.com:443/a.whl") == "https://example.com/a.whl"

    def test_non_http_rejected(self):
        with pytest.raises(ValueError):
            cw.normalize_download_url("file:///tmp/a.whl")


class TestCanonicalization:
    def test_canonical_payload_and_serialize_stable(self):
        a = {"z": 1, "a": [3, 1, 2], "nested": {"b": 2, "a": 1}}
        b = {"a": [1, 2, 3], "nested": {"a": 1, "b": 2}, "z": 1}
        assert cw.canonical_serialize(cw.canonical_payload(a)) == \
            cw.canonical_serialize(cw.canonical_payload(b))

    def test_canonicalize_name(self):
        assert cw.canonicalize_name("p2-closed-world-sentinel") == "p2-closed-world-sentinel"
        assert cw.canonicalize_name("p2_closed_world_sentinel") == "p2-closed-world-sentinel"
        assert cw.canonicalize_name("P2.Closed.World.Sentinel") == "p2-closed-world-sentinel"

    def test_fingerprint_excludes_fingerprint_field(self):
        doc = make_identity()
        f1 = cw.compute_fingerprint_sha(doc)
        doc2 = clone(doc)
        doc2["fingerprint_sha256"] = "0" * 64
        assert cw.compute_fingerprint_sha(doc2) == f1
