"""P2-4 build-isolation identity + evidence-closure canary tool (TEMPORARY, PR #79).

Measurement-only shadow evidence closing the two proof gaps identified by
sealed PR #78: (1) PEP 517 / PEP 660 isolated build-environment identity,
and (2) replayable raw-evidence retention. This tool is CANARY-ONLY: it
exists only during the temporary measurement heads, is never wired into any
production skip decision, and is removed entirely on the final docs-only
head.

Purpose: a target head, BEFORE running its heavy surface, resolves and
fingerprints (a) the runtime it WOULD use (as in #78) and (b) the exact
isolated build environment it WOULD construct (declared [build-system]
requirements, the PEP 660 editable build hook's dynamic requirements, the
complete effective build dependency set, materialized wheel artifacts with
SHA256 identity, and a build-only local direct-reference constraint proven
by positive and negative enforcement tests). The strong claim measured:

    SOURCE_V2_FINGERPRINT == TARGET_V2_FINGERPRINT

covering BOTH final runtime identity AND build-isolation identity.

Stdlib only. Deterministic. Fail closed: anything missing, ambiguous,
malformed, or unproven makes the fingerprint INVALID (a future decision
must RUN), never silently downgrades to a weaker identity.

Subcommands:

  probe
      Runtime identity probe as in #78, then the build-isolation probe:
      static resolution of [build-system].requires via machine-readable pip
      dry-run report; exact-artifact wheelhouse materialization (local
      SHA256 == resolver SHA256 required); dynamic editable-hook probe
      (get_requires_for_build_editable invoked from a backend-probe venv
      containing exactly the static wheel set); complete effective
      resolution of declared + dynamic requirements; generation of a
      build-only constraint file with named PEP 508 direct references to
      the local exact wheels (SHA256 identity); a positive constrained
      editable-build test in a throwaway clean venv; and a negative
      wrong-hash enforcement test (exactly one deliberately wrong SHA256
      must make the constrained editable build FAIL during build-dependency
      resolution). Never installs the MarketVault runtime into the probe.

  verify-installed
      Verify the pre-install fingerprint against the ACTUAL heavy runtime
      (machine-readable pip install reports + live importlib cross-check +
      pyarrow live import on the pyarrow24 surface). Writes
      runtime_verification_receipt.json.

  build-receipt
      Assemble build_identity_receipt.json from the retained evidence:
      every build gate re-derived from the retained files (static /
      dynamic / effective resolution, all-wheels, wheelhouse hashes,
      positive / negative constraint enforcement, and whether the actual
      heavy install ran under the measured build constraint).

  compare
      Pure comparator over two fingerprint JSON files. Prints
      ``RUNTIME_V2_FINGERPRINT_MATCH=true`` or ``=false`` with the exact
      first-mismatch reason. No permissive fallback.

  canonicalize
      Print the canonical payload of a fingerprint and its digest.

  bundle
      Assemble the self-contained evidence bundle: copy the surface's
      actual heavy install reports/logs from the workspace, place the
      exact verifier source (this script) as verifier_source.py, and write
      EVIDENCE_MANIFEST.json binding every retained file (size + SHA256).

  verify-bundle
      OFFLINE replay gate. Run from inside a copy of the bundle with the
      retained verifier source: verify the manifest, the fingerprint
      digest, resolver-report normalization, wheelhouse hashes, constraint
      identity, runtime report vs receipt, build receipt consistency and
      the wrong-hash negative identity. Prints
      ``EVIDENCE_BUNDLE_REPLAY_OK`` or ``EVIDENCE_BUNDLE_REPLAY_FAIL``.
      Never touches the network.

Fingerprint schema V2 (owned by this module):

  {
    "schema_version": 2,
    "surface": "test-3.14" | "pyarrow24",
    "runner": {...},               # as V1
    "python": {...},               # as V1
    "resolver": {...},             # as V1
    "dependency_contract": {...},  # as V1
    "action_contract": {...},      # as V1
    "resolved_distributions": [...],  # as V1
    "build_isolation": {
      "backend": "...",            # build-backend from [build-system]
      "backend_path": null,        # backend-path (None unless set)
      "declared_requires": [...],  # sorted [build-system].requires
      "dynamic_hook": "get_requires_for_build_editable",
      "dynamic_requires": [...],   # sorted normalized hook result (may be [])
      "effective_build_distributions": [
        {"name", "version", "filename", "sha256"}, ...
      ],
      "build_constraint_sha256": "...",   # SHA256 of build_constraints.txt
      "constraint_mode": "local_direct_reference_sha256",
      "all_artifacts_are_wheels": true
    },
    "fingerprint_sha256": "..."
  }

Canonical serialization: UTF-8, JSON, sort_keys=True, separators=(",", ":"),
ensure_ascii=True, newline-terminated. resolved_distributions and
effective_build_distributions are sorted by canonical name before hashing,
so array ordering in raw input never changes the fingerprint.
fingerprint_sha256 is the SHA256 of the canonical payload with the
fingerprint_sha256 field omitted.

No timestamps. No run IDs. No job IDs. No head SHA. No absolute workspace
path. No ephemeral runner name. Absolute wheelhouse paths NEVER enter the
canonical fingerprint: the build identity is represented by canonical name,
exact version, wheel filename and SHA256 only.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA_VERSION = 2

SURFACES = ("test-3.14", "pyarrow24")

# The exact measured surfaces and their resolution contracts (as sealed in
# #78). The probe dry-run mirrors the surface's real install command as
# closely as the machine-readable report mechanism allows.
SURFACE_REQUIREMENTS = {
    "test-3.14": ("-e", ".[dev]"),
    "pyarrow24": ("-e", ".[dev]", "pyarrow==24.0.0"),
}

LOCAL_PROJECT_NAME = "market-vault"
EXPECTED_PROJECT_VERSION = "0.7.0"
DYNAMIC_HOOK_NAME = "get_requires_for_build_editable"
CONSTRAINT_MODE = "local_direct_reference_sha256"

# The editable-build hook is the ONLY relevant hook: the current
# installation is editable, so the wheel hook is never substituted.
EDITED_SUBCMDS = ("probe", "build-receipt", "bundle")

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
WHEEL_RE = re.compile(r"^.+\.whl$")
CONSTRAINT_LINE_RE = re.compile(
    r"^([A-Za-z0-9._-]+)\s*@\s*(file://\S+)#sha256=([0-9a-f]{64})$"
)
INDEX_FETCH_RE = re.compile(r"^Downloading ", re.MULTILINE)

# ---------------------------------------------------------------------------
# Canonicalization (the fingerprint's identity contract).
# ---------------------------------------------------------------------------


def canonicalize_name(name: str) -> str:
    """PEP 503 canonical package name: lowercase, runs of ``-_.`` collapsed
    to a single ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def normalize_download_url(url: str) -> tuple[str | None, str | None]:
    """Return (url, None) for a credential-free http(s) URL, else
    (None, specific_reason). Credential-bearing URLs are REJECTED, never
    silently stripped."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None, "malformed_url"
    if parsed.username is not None or parsed.password is not None:
        return None, "url_credentials"
    if parsed.scheme not in ("http", "https"):
        return None, "unsupported_url_scheme"
    if not parsed.netloc:
        return None, "malformed_url"
    return url, None


def canonical_payload(doc: dict) -> dict:
    """The payload that fingerprint_sha256 is computed over: the document
    minus the fingerprint_sha256 field, with both distribution arrays
    sorted by canonical name so array ordering never changes the
    fingerprint. The input document is NEVER mutated: the payload is a
    deep copy, so fail-closed schema validation of the raw document
    (e.g. unsorted-array detection) always sees the caller's exact input."""
    payload = copy.deepcopy(
        {
            key: value
            for key, value in doc.items()
            if key != "fingerprint_sha256"
        }
    )
    dists = payload.get("resolved_distributions")
    if isinstance(dists, list):
        payload["resolved_distributions"] = sorted(
            dists, key=lambda entry: str(entry.get("name", ""))
        )
    build = payload.get("build_isolation")
    if isinstance(build, dict):
        effective = build.get("effective_build_distributions")
        if isinstance(effective, list):
            build["effective_build_distributions"] = sorted(
                effective, key=lambda entry: str(entry.get("name", ""))
            )
    return payload


def canonical_serialize(payload: dict) -> str:
    """Deterministic canonical JSON: UTF-8, sort_keys=True,
    separators=(",", ":"), newline-terminated."""
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True)
        + "\n"
    )


def compute_fingerprint_sha(doc: dict) -> str:
    return hashlib.sha256(
        canonical_serialize(canonical_payload(doc)).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Strict schema validation (fail closed; any hole => INVALID).
# ---------------------------------------------------------------------------

RUNNER_REQUIRED_FIELDS = (
    "run_os",
    "run_arch",
    "image_os",
    "image_version",
)

RUNNER_PLATFORM_FIELDS = (
    "sys_platform",
    "machine",
    "release",
    "libc_ver",
    "sysconfig_platform",
)

PYTHON_REQUIRED_FIELDS = (
    "implementation",
    "version",
    "major",
    "minor",
    "micro",
    "cache_tag",
    "soabi",
    "pointer_width",
)

RESOLVER_REQUIRED_FIELDS = ("name", "version")

DEPENDENCY_CONTRACT_FIELDS = (
    "name",
    "version",
    "pyproject_sha256",
    "dependencies",
    "dev_dependencies",
)

ACTION_CONTRACT_FIELDS = (
    "checkout_sha",
    "setup_python_sha",
    "upload_artifact_sha",
    "ci_yml_sha256",
)

DISTRIBUTION_FIELDS = ("name", "version", "url", "sha256")

BUILD_DISTRIBUTION_FIELDS = ("name", "version", "filename", "sha256")


def _missing_reason(fields: tuple[str, ...], block: dict, prefix: str) -> str | None:
    for field in fields:
        value = block.get(field)
        if value is None or value == "" or value == []:
            return f"missing_{prefix}_{field}"
    return None


def validate_build_isolation(build: object) -> tuple[bool, str | None]:
    """Strict validation of the build_isolation block. Returns
    (True, None) or (False, specific_reason)."""
    if not isinstance(build, dict):
        return False, "missing_build_isolation"
    reason = _missing_reason(("backend",), build, "build_isolation")
    if reason:
        return False, reason
    backend = build.get("backend")
    if not isinstance(backend, str) or not backend.strip():
        return False, "bad_build_isolation_backend"
    backend_path = build.get("backend_path")
    if backend_path is not None and not isinstance(backend_path, str):
        return False, "bad_build_isolation_backend_path"
    declared = build.get("declared_requires")
    if not isinstance(declared, list) or not declared or not all(
        isinstance(item, str) and item.strip() for item in declared
    ):
        return False, "bad_build_isolation_declared_requires"
    if declared != sorted(declared):
        return False, "build_declared_requires_unsorted"
    if build.get("dynamic_hook") != DYNAMIC_HOOK_NAME:
        return False, "missing_build_isolation_dynamic_hook"
    dynamic = build.get("dynamic_requires")
    if not isinstance(dynamic, list) or not all(
        isinstance(item, str) and item.strip() for item in dynamic
    ):
        return False, "bad_build_isolation_dynamic_requires"
    if dynamic != sorted(dynamic):
        return False, "build_dynamic_requires_unsorted"
    if build.get("constraint_mode") != CONSTRAINT_MODE:
        return False, "bad_build_isolation_constraint_mode"
    digest = build.get("build_constraint_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        return False, "bad_build_isolation_constraint_digest"
    effective = build.get("effective_build_distributions")
    if not isinstance(effective, list) or not effective:
        return False, "missing_build_isolation_effective_distributions"
    seen: set[str] = set()
    previous = ""
    for entry in effective:
        if not isinstance(entry, dict):
            return False, "malformed_build_distribution_entry"
        for field in BUILD_DISTRIBUTION_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                return False, f"missing_build_distribution_{field}"
        name = entry["name"]
        if canonicalize_name(name) != name:
            return False, "build_distribution_name_not_canonical"
        if not SHA256_RE.fullmatch(entry["sha256"]):
            return False, "malformed_build_artifact_hash"
        if not WHEEL_RE.fullmatch(entry["filename"]):
            return False, "build_artifact_not_wheel"
        if name in seen:
            return False, "duplicate_build_package"
        seen.add(name)
        if previous and name < previous:
            return False, "build_distributions_unsorted"
        previous = name
    if build.get("all_artifacts_are_wheels") is not True:
        return False, "build_artifacts_not_all_wheels"
    return True, None


def validate_fingerprint(doc: object) -> tuple[bool, str | None]:
    """Strict schema validation of a V2 fingerprint document. Returns
    (True, None) or (False, specific_reason). A probe-invalid document
    (``valid: false``) is not a valid fingerprint."""
    if not isinstance(doc, dict):
        return False, "not_a_dict"
    if doc.get("valid") is False:
        return False, "probe_invalid"
    if doc.get("schema_version") != SCHEMA_VERSION:
        return False, "schema_version_unsupported"
    surface = doc.get("surface")
    if surface not in SURFACES:
        return False, "surface_unknown"
    runner = doc.get("runner")
    if not isinstance(runner, dict):
        return False, "missing_runner"
    reason = _missing_reason(RUNNER_REQUIRED_FIELDS, runner, "runner")
    if reason:
        return False, reason
    for field in RUNNER_PLATFORM_FIELDS:
        if field not in runner:
            return False, f"missing_runner_{field}"
    libc = runner.get("libc_ver")
    if not isinstance(libc, list) or len(libc) != 2 or not all(
        isinstance(item, str) for item in libc
    ):
        return False, "missing_runner_libc_ver"
    python = doc.get("python")
    if not isinstance(python, dict):
        return False, "missing_python"
    reason = _missing_reason(PYTHON_REQUIRED_FIELDS, python, "python")
    if reason:
        return False, reason
    if not isinstance(python.get("major"), int) or not isinstance(
        python.get("minor"), int
    ) or not isinstance(python.get("micro"), int):
        return False, "python_version_parts"
    version = python.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", version
    ):
        return False, "python_version_format"
    if python.get("soabi") is not None and not isinstance(
        python.get("soabi"), str
    ):
        return False, "python_soabi"
    resolver = doc.get("resolver")
    if not isinstance(resolver, dict):
        return False, "missing_resolver"
    reason = _missing_reason(RESOLVER_REQUIRED_FIELDS, resolver, "resolver")
    if reason:
        return False, reason
    if resolver.get("name") != "pip":
        return False, "resolver_not_pip"
    contract = doc.get("dependency_contract")
    if not isinstance(contract, dict):
        return False, "missing_dependency_contract"
    reason = _missing_reason(DEPENDENCY_CONTRACT_FIELDS, contract, "dependency_contract")
    if reason:
        return False, reason
    if not SHA256_RE.fullmatch(str(contract.get("pyproject_sha256"))):
        return False, "bad_pyproject_digest"
    for key in ("dependencies", "dev_dependencies"):
        values = contract.get(key)
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            return False, f"bad_dependency_contract_{key}"
    actions = doc.get("action_contract")
    if not isinstance(actions, dict):
        return False, "missing_action_contract"
    for field, digest_re in (
        ("checkout_sha", SHA40_RE),
        ("setup_python_sha", SHA40_RE),
        ("upload_artifact_sha", SHA40_RE),
        ("ci_yml_sha256", SHA256_RE),
    ):
        value = str(actions.get(field) or "")
        if not digest_re.fullmatch(value):
            return False, f"bad_action_contract_{field}"
    dists = doc.get("resolved_distributions")
    if not isinstance(dists, list) or not dists:
        return False, "missing_resolved_distributions"
    seen: set[str] = set()
    previous = ""
    for entry in dists:
        if not isinstance(entry, dict):
            return False, "malformed_distribution_entry"
        for field in DISTRIBUTION_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                if field == "sha256":
                    return False, "missing_artifact_hash"
                return False, f"missing_distribution_{field}"
        name = entry["name"]
        if canonicalize_name(name) != name:
            return False, "distribution_name_not_canonical"
        if not SHA256_RE.fullmatch(entry["sha256"]):
            return False, "malformed_artifact_hash"
        url, url_reason = normalize_download_url(entry["url"])
        if url_reason:
            return False, url_reason
        if name in seen:
            return False, "duplicate_package"
        seen.add(name)
        if previous and name < previous:
            return False, "distributions_unsorted"
        previous = name
    ok, reason = validate_build_isolation(doc.get("build_isolation"))
    if not ok:
        return False, reason
    if "fingerprint_sha256" not in doc or not SHA256_RE.fullmatch(
        str(doc["fingerprint_sha256"])
    ):
        return False, "missing_fingerprint_sha"
    if compute_fingerprint_sha(doc) != doc["fingerprint_sha256"]:
        return False, "fingerprint_sha_mismatch"
    return True, None


# ---------------------------------------------------------------------------
# Pure comparator (fail closed, exact first-mismatch reason).
# ---------------------------------------------------------------------------

COMPARE_STEPS = (
    ("schema_version_unequal", "schema_version"),
    ("surface_unequal", "surface"),
)


def _compare_block(
    a: dict, b: dict, fields: tuple[str, ...], reason_format: str
) -> tuple[bool, str | None]:
    for field in fields:
        if a.get(field) != b.get(field):
            return False, reason_format.format(field=field)
    return True, None


def compare_build_distribution_sets(
    map_a: dict, map_b: dict
) -> tuple[bool, str]:
    """Compare two canonical-name -> {version, filename, sha256} maps of
    effective build distributions. Returns (True, "ok") or (False, exact
    reason)."""
    missing = sorted(set(map_a) - set(map_b))
    if missing:
        return False, f"build_package_missing:{missing[0]}"
    extra = sorted(set(map_b) - set(map_a))
    if extra:
        return False, f"build_package_extra:{extra[0]}"
    for name in sorted(map_a):
        entry_a, entry_b = map_a[name], map_b[name]
        if entry_a["version"] != entry_b["version"]:
            return False, f"build_package_version_unequal:{name}"
        if entry_a["filename"] != entry_b["filename"]:
            return False, f"build_wheel_filename_unequal:{name}"
        if entry_a["sha256"] != entry_b["sha256"]:
            return False, f"build_wheel_sha256_unequal:{name}"
    return True, "ok"


def _build_distribution_map(entries: list) -> dict:
    return {
        str(entry.get("name", "")): {
            "version": str(entry.get("version", "")),
            "filename": str(entry.get("filename", "")),
            "sha256": str(entry.get("sha256", "")),
        }
        for entry in entries
        if isinstance(entry, dict)
    }


def _compare_build_isolation(a: dict, b: dict) -> tuple[bool, str | None]:
    ba, bb = a.get("build_isolation", {}), b.get("build_isolation", {})
    if ba.get("backend") != bb.get("backend"):
        return False, "build_backend_unequal"
    if ba.get("declared_requires") != bb.get("declared_requires"):
        return False, "build_declared_requires_unequal"
    if ba.get("dynamic_hook") != bb.get("dynamic_hook"):
        return False, "build_dynamic_hook_unequal"
    if ba.get("dynamic_requires") != bb.get("dynamic_requires"):
        return False, "build_dynamic_requires_unequal"
    if ba.get("constraint_mode") != bb.get("constraint_mode"):
        return False, "build_constraint_mode_unequal"
    if ba.get("build_constraint_sha256") != bb.get("build_constraint_sha256"):
        return False, "build_constraint_digest_unequal"
    map_a = _build_distribution_map(
        ba.get("effective_build_distributions", [])
    )
    map_b = _build_distribution_map(
        bb.get("effective_build_distributions", [])
    )
    match, reason = compare_build_distribution_sets(map_a, map_b)
    if not match:
        return False, reason
    if ba.get("all_artifacts_are_wheels") != bb.get(
        "all_artifacts_are_wheels"
    ):
        return False, "build_artifacts_not_all_wheels_unequal"
    return True, None


def compare_fingerprints(a: dict, b: dict) -> tuple[bool, str]:
    """Pure, deterministic comparison of two fingerprint documents.
    Returns (True, "ok") or (False, exact_first_mismatch_reason). No
    permissive fallback: any invalid input fails closed."""
    for reason, key in COMPARE_STEPS:
        if a.get(key) != b.get(key):
            return False, reason
    ra_block, rb_block = a.get("runner", {}), b.get("runner", {})
    ok, reason = _compare_block(
        ra_block, rb_block, RUNNER_REQUIRED_FIELDS, "runner_{field}_unequal"
    )
    if not ok:
        return False, reason
    ok, reason = _compare_block(
        ra_block, rb_block, RUNNER_PLATFORM_FIELDS, "runner_{field}_unequal"
    )
    if not ok:
        return False, reason
    pa, pb = a.get("python", {}), b.get("python", {})
    for field, reason_label in (
        ("implementation", "python_implementation_unequal"),
        ("version", "python_exact_runtime_unequal"),
        ("cache_tag", "python_cache_tag_unequal"),
        ("soabi", "python_soabi_unequal"),
        ("pointer_width", "python_pointer_width_unequal"),
    ):
        if pa.get(field) != pb.get(field):
            return False, reason_label
    ra, rb = a.get("resolver", {}), b.get("resolver", {})
    if ra.get("name") != rb.get("name"):
        return False, "resolver_unequal"
    if ra.get("version") != rb.get("version"):
        return False, "pip_version_unequal"
    da, db = a.get("dependency_contract", {}), b.get("dependency_contract", {})
    if da != db:
        if da.get("pyproject_sha256") != db.get("pyproject_sha256"):
            return False, "pyproject_digest_unequal"
        return False, "dependency_contract_unequal"
    aa, ab = a.get("action_contract", {}), b.get("action_contract", {})
    for field, reason_label in (
        ("checkout_sha", "action_checkout_sha_unequal"),
        ("setup_python_sha", "action_setup_python_sha_unequal"),
        ("upload_artifact_sha", "action_upload_artifact_sha_unequal"),
        ("ci_yml_sha256", "workflow_digest_unequal"),
    ):
        if aa.get(field) != ab.get(field):
            return False, reason_label
    map_a = _distribution_map(a.get("resolved_distributions", []))
    map_b = _distribution_map(b.get("resolved_distributions", []))
    match, reason = compare_distribution_sets(map_a, map_b)
    if not match:
        return False, reason
    ok, reason = _compare_build_isolation(a, b)
    if not ok:
        assert reason is not None
        return False, reason
    if a.get("fingerprint_sha256") != b.get("fingerprint_sha256"):
        return False, "fingerprint_sha256_unequal"
    return True, "ok"


def compare_distribution_sets(
    map_a: dict, map_b: dict
) -> tuple[bool, str]:
    """Compare two canonical-name -> {version, url, sha256} maps. Returns
    (True, "ok") or (False, exact reason)."""
    missing = sorted(set(map_a) - set(map_b))
    if missing:
        return False, f"dependency_missing:{missing[0]}"
    extra = sorted(set(map_b) - set(map_a))
    if extra:
        return False, f"dependency_extra:{extra[0]}"
    for name in sorted(map_a):
        entry_a, entry_b = map_a[name], map_b[name]
        if entry_a["version"] != entry_b["version"]:
            return False, f"dependency_version_unequal:{name}"
        if entry_a["url"] != entry_b["url"]:
            return False, f"dependency_artifact_url_unequal:{name}"
        if entry_a["sha256"] != entry_b["sha256"]:
            return False, f"dependency_artifact_hash_unequal:{name}"
    return True, "ok"


def _distribution_map(dists: list) -> dict:
    return {
        str(entry.get("name", "")): {
            "version": str(entry.get("version", "")),
            "url": str(entry.get("url", "")),
            "sha256": str(entry.get("sha256", "")),
        }
        for entry in dists
        if isinstance(entry, dict)
    }


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(cmd: list[str], cwd: Path, log: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, appending its stdout+stderr to ``log``."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=1800,
    )
    with log.open("a", encoding="utf-8") as handle:
        handle.write("$ " + " ".join(cmd) + "\n")
        handle.write(proc.stdout)
        handle.write(proc.stderr)
    return proc


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _parse_pip_version(pip_version_output: str) -> str | None:
    """``pip 26.2.1 from ...`` -> ``26.2.1``. Anything else is unparseable
    and fails the probe closed."""
    parts = pip_version_output.strip().split()
    if len(parts) < 2 or parts[0] != "pip":
        return None
    return parts[1]


def runner_identity(env: dict[str, str]) -> dict | None:
    """Runner identity from the GitHub-hosted environment. Any missing
    required env value makes the fingerprint INVALID (None returned)."""
    values = {}
    for key, field in (
        ("RUNNER_OS", "run_os"),
        ("RUNNER_ARCH", "run_arch"),
        ("ImageOS", "image_os"),
        ("ImageVersion", "image_version"),
    ):
        value = env.get(key)
        if not value:
            return None
        values[field] = value
    libc_name, libc_version = platform.libc_ver()
    values.update(
        {
            "sys_platform": sys.platform,
            "machine": platform.machine(),
            "release": platform.release(),
            "libc_ver": [libc_name, libc_version],
            "sysconfig_platform": sysconfig.get_platform(),
        }
    )
    return values


def python_identity() -> dict:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
        "cache_tag": sys.implementation.cache_tag,
        "soabi": sysconfig.get_config_var("SOABI"),
        "pointer_width": struct.calcsize("P") * 8,
    }


def dependency_contract(repo_root: Path) -> dict | None:
    """Project metadata identity from pyproject.toml (read via stdlib
    tomllib)."""
    pyproject = repo_root / "pyproject.toml"
    try:
        raw = pyproject.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project") or {}
    name = project.get("name")
    version = project.get("version")
    dependencies = project.get("dependencies")
    dev = (data.get("project", {}).get("optional-dependencies") or {}).get("dev")
    if not isinstance(name, str) or not isinstance(version, str):
        return None
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        return None
    if not isinstance(dev, list) or not all(isinstance(item, str) for item in dev):
        return None
    return {
        "name": name,
        "version": version,
        "pyproject_sha256": hashlib.sha256(raw).hexdigest(),
        "dependencies": sorted(dependencies),
        "dev_dependencies": sorted(dev),
    }


def action_contract(
    repo_root: Path, checkout_sha: str, setup_python_sha: str,
    upload_artifact_sha: str,
) -> dict | None:
    """The exact canary-pinned action SHAs for the measured job plus
    SHA256(.github/workflows/ci.yml)."""
    for value in (checkout_sha, setup_python_sha, upload_artifact_sha):
        if not SHA40_RE.fullmatch(value):
            return None
    workflow = repo_root / ".github" / "workflows" / "ci.yml"
    try:
        digest = sha256_file(workflow)
    except OSError:
        return None
    return {
        "checkout_sha": checkout_sha,
        "setup_python_sha": setup_python_sha,
        "upload_artifact_sha": upload_artifact_sha,
        "ci_yml_sha256": digest,
    }


def parse_pip_report(
    data: object,
) -> tuple[list[dict] | None, str | None]:
    """Derive the exact external distribution set from a pip
    machine-readable install/dry-run report. Returns
    (sorted_records, None) or (None, specific_reason). The local
    MarketVault project is never treated as an external wheel."""
    if not isinstance(data, dict):
        return None, "report_not_a_dict"
    install = data.get("install")
    if not isinstance(install, list):
        return None, "report_missing_install"
    records: dict[str, dict] = {}
    for entry in install:
        if not isinstance(entry, dict):
            return None, "report_entry_malformed"
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            return None, "report_entry_missing_metadata"
        name = metadata.get("name")
        version = metadata.get("version")
        if not isinstance(name, str) or not name:
            return None, "report_entry_missing_name"
        if not isinstance(version, str) or not version:
            return None, "report_entry_missing_version"
        canonical = canonicalize_name(name)
        if canonical == LOCAL_PROJECT_NAME:
            continue
        if canonical in records:
            return None, "duplicate_package"
        download_info = entry.get("download_info")
        if not isinstance(download_info, dict) or not isinstance(
            download_info.get("url"), str
        ):
            return None, "missing_artifact_identity"
        url, url_reason = normalize_download_url(download_info["url"])
        if url_reason:
            return None, url_reason
        archive_info = download_info.get("archive_info")
        if not isinstance(archive_info, dict):
            return None, "missing_artifact_hash"
        hashes = archive_info.get("hashes")
        if not isinstance(hashes, dict):
            return None, "missing_artifact_hash"
        sha256 = hashes.get("sha256")
        if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            return None, "missing_artifact_hash"
        records[canonical] = {
            "name": canonical,
            "version": version,
            "url": url,
            "sha256": sha256,
        }
    if not records:
        return None, "report_empty"
    return sorted(records.values(), key=lambda entry: entry["name"]), None


def parse_build_report(
    data: object,
) -> tuple[list[dict] | None, str | None]:
    """Like parse_pip_report but for build-environment resolution: every
    selected artifact must be a WHEEL (sdist / VCS / local source tree /
    unhashed archive => INVALID), and each entry additionally carries its
    exact wheel filename derived from the URL."""
    records, reason = parse_pip_report(data)
    if reason:
        return None, reason
    assert records is not None
    result: list[dict] = []
    for entry in records:
        url = entry["url"]
        filename = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        if not WHEEL_RE.fullmatch(filename):
            return None, "build_artifact_not_wheel"
        result.append(
            {
                "name": entry["name"],
                "version": entry["version"],
                "filename": filename,
                "url": url,
                "sha256": entry["sha256"],
            }
        )
    return result, None


# ---------------------------------------------------------------------------
# Build-isolation probe.
# ---------------------------------------------------------------------------


class BuildProbe:
    """The complete build-isolation measurement pipeline. Each stage
    records its outcome; a failed stage sets a fail-closed verdict without
    raising (the heavy validation chain must never be broken by the
    measurement)."""

    def __init__(
        self, *, surface: str, repo_root: Path, out_dir: Path,
        probe_python: Path, probe_venv_dir: Path, log: Path,
    ):
        self.surface = surface
        self.repo_root = repo_root
        self.out_dir = out_dir
        self.probe_python = probe_python
        self.probe_venv_dir = probe_venv_dir
        self.log = log
        self.wheelhouse = out_dir / "build-wheelhouse"
        self.wheelhouse.mkdir(parents=True, exist_ok=True)
        self.valid = True
        self.reason: str | None = None
        self.times: dict[str, float] = {}
        self.pyproject_build = None
        self.static_report: list[dict] | None = None
        self.dynamic_doc: dict | None = None
        self.effective_report: list[dict] | None = None
        self.constraint_digest: str | None = None

    def fail(self, reason: str) -> None:
        if self.valid:
            self.valid = False
            self.reason = reason

    def _timed(self, key: str) -> "Timer":
        return Timer(self, key)

    # -- stage 1: static resolution of declared build requirements --------

    def stage_static(self) -> None:
        start = time.monotonic()
        try:
            pyproject_path = self.repo_root / "pyproject.toml"
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            self.fail("pyproject_unreadable")
            return
        build_system = data.get("build-system")
        if not isinstance(build_system, dict):
            self.fail("build_system_missing")
            return
        backend = build_system.get("build-backend")
        requires = build_system.get("requires")
        backend_path = build_system.get("backend-path")
        if not isinstance(backend, str) or not backend:
            self.fail("build_backend_missing")
            return
        if not isinstance(requires, list) or not requires or not all(
            isinstance(item, str) and item.strip() for item in requires
        ):
            self.fail("build_requires_malformed")
            return
        if backend_path is not None and not isinstance(backend_path, list):
            self.fail("build_backend_path_malformed")
            return
        self.pyproject_build = {
            "backend": backend,
            "backend_path": None
            if not backend_path
            else [str(item) for item in backend_path],
            "declared_requires": sorted(requires),
        }
        report_path = self.probe_venv_dir / "build_static_resolve.json"
        proc = _run(
            [
                str(self.probe_python), "-m", "pip", "install",
                "--dry-run", "--ignore-installed",
                "--report", str(report_path),
                *requires,
            ],
            self.repo_root, self.log,
        )
        if proc.returncode != 0:
            self.fail("build_static_resolution_failed")
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self.fail("build_static_report_unreadable")
            return
        entries, reason = parse_build_report(report)
        if reason:
            self.fail(f"build_static_{reason}")
            return
        assert entries is not None
        # Every DECLARED package must be present in the resolved set.
        # Requirements carry specifiers ("setuptools>=68"): extract the
        # leading NAME token before canonicalizing (a requirement without a
        # name token is malformed and fails the probe closed).
        declared_names: set[str] = set()
        for item in requires:
            match = re.match(r"^([A-Za-z0-9._-]+)", item.strip())
            if not match:
                self.fail("build_requires_name_malformed")
                return
            declared_names.add(canonicalize_name(match.group(1)))
        resolved_names = {entry["name"] for entry in entries}
        missing = sorted(declared_names - resolved_names)
        if missing:
            self.fail(f"build_static_missing_declared:{missing[0]}")
            return
        self.static_report = entries
        (self.out_dir / "build_static_resolver_report.json").write_text(
            canonical_serialize({"surface": self.surface,
                                 "distributions": entries}),
            encoding="utf-8", newline="\n",
        )
        self.times["build_static"] = time.monotonic() - start

    # -- stage 2: exact-artifact wheelhouse materialization --------------

    def stage_wheelhouse(self) -> None:
        start = time.monotonic()
        if self.static_report is None:
            self.fail("build_wheelhouse_no_static_report")
            return
        for entry in self.static_report:
            target = self.wheelhouse / entry["filename"]
            if not self._materialize_exact(target, entry):
                return
        self.times["wheelhouse"] = time.monotonic() - start

    def _materialize_exact(self, target: Path, entry: dict) -> bool:
        """Download the EXACT artifact from the resolver report URL (never
        re-resolve) and require LOCAL_SHA256 == REPORTED_SHA256."""
        if target.exists() and sha256_file(target) == entry["sha256"]:
            return True
        url = entry["url"]
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "market-vault-p24-canary-probe/1.0"},
                )
                with urllib.request.urlopen(request, timeout=300) as response:
                    data = response.read()
                local = hashlib.sha256(data).hexdigest()
                if local != entry["sha256"]:
                    self.fail(f"wheelhouse_hash_mismatch:{entry['name']}")
                    return False
                target.write_bytes(data)
                return True
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last_error = exc
        self.fail(f"wheelhouse_download_failed:{entry['name']}")
        return False

    # -- stage 3: dynamic editable-hook probe -----------------------------

    def stage_dynamic_hook(self) -> None:
        start = time.monotonic()
        if self.static_report is None or self.pyproject_build is None:
            self.fail("build_dynamic_no_static_report")
            return
        hook_venv = self.probe_venv_dir.parent / "hook-venv"
        proc = _run(
            [sys.executable, "-m", "venv", str(hook_venv)],
            self.repo_root, self.log,
        )
        if proc.returncode != 0:
            self.fail("build_hook_venv_failed")
            return
        hook_python = _venv_python(hook_venv)
        proc = _run(
            [
                str(hook_python), "-m", "pip", "install", "--no-deps",
                *[str(self.wheelhouse / entry["filename"])
                  for entry in self.static_report],
            ],
            self.repo_root, self.log,
        )
        if proc.returncode != 0:
            self.fail("build_hook_wheel_install_failed")
            return
        snippet = self.probe_venv_dir.parent / "hook_probe.py"
        snippet.write_text(
            "import importlib, json, sys\n"
            "try:\n"
            "    backend = importlib.import_module(sys.argv[1])\n"
            "    hook = getattr(backend, sys.argv[2])\n"
            "    reqs = list(hook(None))\n"
            "    if not all(isinstance(item, str) for item in reqs):\n"
            "        print(json.dumps({'error': 'non_string_requirement'}))\n"
            "    else:\n"
            "        print(json.dumps({'requires': reqs, 'error': None}))\n"
            "except Exception as exc:\n"
            "    print(json.dumps({'error': 'hook_crash:' + type(exc).__name__}))\n",
            encoding="utf-8",
        )
        proc = _run(
            [
                str(hook_python), str(snippet),
                self.pyproject_build["backend"], DYNAMIC_HOOK_NAME,
            ],
            self.repo_root, self.log,
        )
        if proc.returncode != 0:
            self.fail("build_hook_probe_failed")
            return
        try:
            captured = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            self.fail("build_hook_output_unparseable")
            return
        if captured.get("error"):
            self.fail(f"build_hook_error:{captured['error']}")
            return
        verbatim = captured.get("requires")
        if not isinstance(verbatim, list) or not all(
            isinstance(item, str) and item.strip() for item in verbatim
        ):
            self.fail("build_hook_requirements_malformed")
            return
        normalized = sorted({item.strip() for item in verbatim})
        self.dynamic_doc = {
            "dynamic_hook": DYNAMIC_HOOK_NAME,
            "verbatim": [str(item) for item in verbatim],
            "normalized_sorted": normalized,
        }
        (self.out_dir / "build_dynamic_requirements.json").write_text(
            canonical_serialize(self.dynamic_doc),
            encoding="utf-8", newline="\n",
        )
        self.times["build_dynamic"] = time.monotonic() - start

    # -- stage 4: complete effective resolution ---------------------------

    def stage_effective(self) -> None:
        start = time.monotonic()
        if (
            self.pyproject_build is None or self.dynamic_doc is None
            or self.static_report is None
        ):
            self.fail("build_effective_missing_stages")
            return
        requires = list(self.pyproject_build["declared_requires"])
        requires.extend(self.dynamic_doc["normalized_sorted"])
        report_path = self.probe_venv_dir / "build_effective_resolve.json"
        proc = _run(
            [
                str(self.probe_python), "-m", "pip", "install",
                "--dry-run", "--ignore-installed",
                "--report", str(report_path),
                *requires,
            ],
            self.repo_root, self.log,
        )
        if proc.returncode != 0:
            self.fail("build_effective_resolution_failed")
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            self.fail("build_effective_report_unreadable")
            return
        entries, reason = parse_build_report(report)
        if reason:
            self.fail(f"build_effective_{reason}")
            return
        assert entries is not None
        static_names = {entry["name"] for entry in self.static_report}
        effective_names = {entry["name"] for entry in entries}
        missing = sorted(static_names - effective_names)
        if missing:
            self.fail(f"build_effective_missing_static:{missing[0]}")
            return
        self.effective_report = entries
        (self.out_dir / "build_effective_resolver_report.json").write_text(
            canonical_serialize({"surface": self.surface,
                                 "distributions": entries}),
            encoding="utf-8", newline="\n",
        )
        # Materialize any effective artifact not already in the wheelhouse.
        for entry in entries:
            target = self.wheelhouse / entry["filename"]
            if not target.exists() or sha256_file(target) != entry["sha256"]:
                if not self._materialize_exact(target, entry):
                    return
        # Gate: every effective artifact must be a prebuilt wheel.
        for entry in entries:
            if not WHEEL_RE.fullmatch(entry["filename"]):
                self.fail("build_effective_not_wheel")
                return
        self.times["build_effective"] = time.monotonic() - start

    # -- stage 5: build-only exact constraint -----------------------------

    def stage_constraint(self) -> None:
        start = time.monotonic()
        if self.effective_report is None:
            self.fail("build_constraint_no_effective_report")
            return
        lines = []
        for entry in self.effective_report:
            uri = (self.wheelhouse / entry["filename"]).resolve().as_uri()
            lines.append(f"{entry['name']} @ {uri}#sha256={entry['sha256']}")
        text = "\n".join(lines) + "\n"
        constraint_path = self.out_dir / "build_constraints.txt"
        constraint_path.write_text(text, encoding="utf-8", newline="\n")
        self.constraint_digest = sha256_file(constraint_path)
        self.times["constraint"] = time.monotonic() - start

    # -- stage 6: positive constrained editable build ---------------------

    def stage_positive(self) -> None:
        start = time.monotonic()
        if self.constraint_digest is None:
            self.fail("build_positive_no_constraint")
            return
        log_path = self.out_dir / "build_constraint_positive.log"
        positive_venv = self.probe_venv_dir.parent / "positive-venv"
        proc = _run(
            [sys.executable, "-m", "venv", str(positive_venv)],
            self.repo_root, log_path,
        )
        if proc.returncode != 0:
            self._mark(log_path, "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=false",
                       "venv_creation_failed")
            self.times["positive"] = time.monotonic() - start
            return
        positive_python = _venv_python(positive_venv)
        proc = _run(
            [str(positive_python), "-m", "pip", "install", "--upgrade", "pip"],
            self.repo_root, log_path,
        )
        if proc.returncode != 0:
            self._mark(log_path, "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=false",
                       "pip_upgrade_failed")
            self.times["positive"] = time.monotonic() - start
            return
        constraint_path = (self.out_dir / "build_constraints.txt").resolve()
        separator = "--- P24_CONSTRAINED_INSTALL_BEGIN ---"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(separator + "\n")
        proc = _run(
            [
                str(positive_python), "-m", "pip", "install",
                "--no-deps",
                "--build-constraint", str(constraint_path),
                "-e", ".",
            ],
            self.repo_root, log_path,
        )
        install_ok = proc.returncode == 0
        version_check = _run(
            [str(positive_python), "-c",
             "import importlib.metadata; print(importlib.metadata.version('market-vault'))"],
            self.repo_root, log_path,
        )
        version_ok = (
            install_ok
            and version_check.returncode == 0
            and version_check.stdout.strip() == EXPECTED_PROJECT_VERSION
        )
        segment = self._log_segment(log_path, separator)
        index_fetch = INDEX_FETCH_RE.search(segment) is not None
        if install_ok and version_ok and not index_fetch:
            self._mark(log_path, "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=true",
                       f"version={EXPECTED_PROJECT_VERSION}")
        elif index_fetch:
            self._mark(log_path, "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=false",
                       "index_fetch_in_install_segment")
        elif not version_ok:
            self._mark(log_path, "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=false",
                       "version_mismatch")
        else:
            self._mark(log_path, "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=false",
                       "install_failed")
        self.times["positive"] = time.monotonic() - start

    # -- stage 7: negative wrong-hash enforcement -------------------------

    def stage_negative(self) -> None:
        start = time.monotonic()
        if self.constraint_digest is None:
            self.fail("build_negative_no_constraint")
            return
        constraint_path = self.out_dir / "build_constraints.txt"
        wrong_path = self.out_dir / "wrong_hash_constraint.txt"
        try:
            lines = constraint_path.read_text(encoding="utf-8").splitlines()
            flipped = False
            wrong_lines = []
            for line in lines:
                match = CONSTRAINT_LINE_RE.fullmatch(line.strip())
                if not match:
                    wrong_lines.append(line)
                    continue
                name, url, digest = match.groups()
                if not flipped:
                    bad_digest = (
                        "0" if digest[0] != "0" else "1"
                    ) + digest[1:]
                    wrong_lines.append(line.replace(digest, bad_digest, 1))
                    flipped = True
                else:
                    wrong_lines.append(line)
            if not flipped:
                self.fail("build_negative_no_constraint_line")
                return
            wrong_path.write_text(
                "\n".join(wrong_lines) + "\n", encoding="utf-8", newline="\n"
            )
        except OSError:
            self.fail("build_negative_constraint_unreadable")
            return
        log_path = self.out_dir / "build_constraint_negative.log"
        negative_venv = self.probe_venv_dir.parent / "negative-venv"
        proc = _run(
            [sys.executable, "-m", "venv", str(negative_venv)],
            self.repo_root, log_path,
        )
        if proc.returncode != 0:
            self._mark(log_path, "P24_NEGATIVE_WRONG_HASH_REJECTED=false",
                       "venv_creation_failed")
            self.times["negative"] = time.monotonic() - start
            return
        negative_python = _venv_python(negative_venv)
        proc = _run(
            [str(negative_python), "-m", "pip", "install", "--upgrade", "pip"],
            self.repo_root, log_path,
        )
        if proc.returncode != 0:
            self._mark(log_path, "P24_NEGATIVE_WRONG_HASH_REJECTED=false",
                       "pip_upgrade_failed")
            self.times["negative"] = time.monotonic() - start
            return
        separator = "--- P24_WRONG_HASH_INSTALL_BEGIN ---"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(separator + "\n")
        proc = _run(
            [
                str(negative_python), "-m", "pip", "install",
                "--no-deps",
                "--build-constraint", str(wrong_path.resolve()),
                "-e", ".",
            ],
            self.repo_root, log_path,
        )
        install_failed = proc.returncode != 0
        segment = self._log_segment(log_path, separator)
        hash_rejected = (
            "DO NOT MATCH THE HASHES" in segment
            and "THESE PACKAGES" in segment
        )
        installed_check = _run(
            [str(negative_python), "-c",
             "import importlib.metadata; importlib.metadata.version('market-vault')"],
            self.repo_root, log_path,
        )
        nothing_installed = installed_check.returncode != 0
        if install_failed and hash_rejected and nothing_installed:
            self._mark(log_path, "P24_NEGATIVE_WRONG_HASH_REJECTED=true", "ok")
        elif install_failed and not hash_rejected:
            self._mark(log_path, "P24_NEGATIVE_WRONG_HASH_REJECTED=false",
                       "failure_but_no_hash_rejection_evidence")
        else:
            self._mark(log_path, "P24_NEGATIVE_WRONG_HASH_REJECTED=false",
                       "install_succeeded")
        self.times["negative"] = time.monotonic() - start

    # -- shared -----------------------------------------------------------

    def _mark(self, log_path: Path, line: str, detail: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line} reason={detail}\n")

    def _log_segment(self, log_path: Path, separator: str) -> str:
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError:
            return ""
        parts = text.split(separator)
        if len(parts) < 2:
            return text
        return separator + parts[-1]

    def build_isolation_block(self) -> dict | None:
        if (
            self.pyproject_build is None or self.dynamic_doc is None
            or self.effective_report is None or self.constraint_digest is None
            or not self.valid
        ):
            return None
        effective = [
            {
                "name": entry["name"],
                "version": entry["version"],
                "filename": entry["filename"],
                "sha256": entry["sha256"],
            }
            for entry in self.effective_report
        ]
        effective.sort(key=lambda entry: entry["name"])
        return {
            "backend": self.pyproject_build["backend"],
            "backend_path": self.pyproject_build["backend_path"],
            "declared_requires": self.pyproject_build["declared_requires"],
            "dynamic_hook": DYNAMIC_HOOK_NAME,
            "dynamic_requires": self.dynamic_doc["normalized_sorted"],
            "effective_build_distributions": effective,
            "build_constraint_sha256": self.constraint_digest,
            "constraint_mode": CONSTRAINT_MODE,
            "all_artifacts_are_wheels": True,
        }


class Timer:
    def __init__(self, probe: BuildProbe, key: str):
        self.probe = probe
        self.key = key
        self.start = time.monotonic()

    def __enter__(self) -> "Timer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.probe.times[self.key] = time.monotonic() - self.start


# ---------------------------------------------------------------------------
# Probe: identity collection.
# ---------------------------------------------------------------------------


def _run_probe(
    *, surface: str, repo_root: Path, out_dir: Path,
    checkout_sha: str, setup_python_sha: str, upload_artifact_sha: str,
    env: dict[str, str],
) -> tuple[bool, str, str | None, BuildProbe | None]:
    """The full probe pipeline. Returns
    (valid, reason, fingerprint_sha, build_probe). Never raises."""
    try:
        runner = runner_identity(env)
        if runner is None:
            return False, "missing_runner_image_version", None, None
        requirements = SURFACE_REQUIREMENTS[surface]
        work_dir = Path(tempfile.mkdtemp(prefix="mv-v2-probe-"))
        try:
            venv_dir = work_dir / "venv"
            log = out_dir / "probe_pip_dryrun.log"
            proc = _run([sys.executable, "-m", "venv", str(venv_dir)], repo_root, log)
            if proc.returncode != 0:
                return False, "venv_creation_failed", None, None
            probe_python = _venv_python(venv_dir)
            proc = _run(
                [str(probe_python), "-m", "pip", "install", "--upgrade", "pip"],
                repo_root, log,
            )
            if proc.returncode != 0:
                return False, "resolver_bootstrap_failed", None, None
            proc = _run([str(probe_python), "-m", "pip", "--version"], repo_root, log)
            if proc.returncode != 0:
                return False, "pip_version_failed", None, None
            pip_version = _parse_pip_version(proc.stdout)
            if pip_version is None:
                return False, "pip_version_unparseable", None, None
            report_path = work_dir / "resolver_report_raw.json"
            proc = _run(
                [
                    str(probe_python), "-m", "pip", "install",
                    "--dry-run", "--ignore-installed",
                    "--report", str(report_path),
                    *requirements,
                ],
                repo_root, log,
            )
            if proc.returncode != 0:
                return False, "pip_dryrun_failed", None, None
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                return False, "pip_report_unreadable", None, None
            distributions, report_reason = parse_pip_report(report)
            if report_reason:
                return False, report_reason, None, None
            contract = dependency_contract(repo_root)
            if contract is None:
                return False, "pyproject_unreadable", None, None
            actions = action_contract(
                repo_root, checkout_sha, setup_python_sha, upload_artifact_sha
            )
            if actions is None:
                return False, "action_contract_invalid", None, None

            # Build-isolation probe (independent of the runtime result).
            build = BuildProbe(
                surface=surface, repo_root=repo_root, out_dir=out_dir,
                probe_python=probe_python, probe_venv_dir=venv_dir, log=log,
            )
            with build._timed("build_static"):
                build.stage_static()
            with build._timed("wheelhouse"):
                build.stage_wheelhouse()
            with build._timed("build_dynamic"):
                build.stage_dynamic_hook()
            with build._timed("build_effective"):
                build.stage_effective()
            with build._timed("constraint"):
                build.stage_constraint()
            with build._timed("positive"):
                build.stage_positive()
            with build._timed("negative"):
                build.stage_negative()

            build_block = build.build_isolation_block()
            build_valid = build_block is not None
            if not build_valid:
                build_reason = build.reason or "build_probe_incomplete"
            else:
                build_reason = "ok"

            doc = {
                "schema_version": SCHEMA_VERSION,
                "surface": surface,
                "runner": runner,
                "python": python_identity(),
                "resolver": {"name": "pip", "version": pip_version},
                "dependency_contract": contract,
                "action_contract": actions,
                "resolved_distributions": distributions,
            }
            if build_block is not None:
                doc["build_isolation"] = build_block
            doc["fingerprint_sha256"] = compute_fingerprint_sha(doc)
            ok, reason = validate_fingerprint(doc)
            if not ok:
                return False, f"self_check_{reason}", None, build
            (out_dir / "runtime_identity_v2.json").write_text(
                canonical_serialize(doc), encoding="utf-8", newline="\n"
            )
            resolver_evidence = {
                "pip_version": pip_version,
                "install": distributions,
            }
            (out_dir / "runtime_resolver_report.json").write_text(
                canonical_serialize(resolver_evidence),
                encoding="utf-8", newline="\n",
            )
            return True, "ok", doc["fingerprint_sha256"], build
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        return False, "probe_internal_error", None, None


def _write_invalid_fingerprint(out_dir: Path, surface: str, reason: str) -> None:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "surface": surface,
        "valid": False,
        "invalid_reason": reason,
    }
    (out_dir / "runtime_identity_v2.json").write_text(
        canonical_serialize(doc), encoding="utf-8", newline="\n"
    )


def cmd_probe(args: argparse.Namespace) -> int:
    """Always exits 0 (measurement only): a probe failure must NOT fail the
    heavy surface; the marker line carries validity and the heavy chain
    runs regardless."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(args.repo).resolve()
    started = time.monotonic()
    valid, reason, fingerprint_sha, build = _run_probe(
        surface=args.surface, repo_root=repo_root, out_dir=out_dir,
        checkout_sha=args.checkout, setup_python_sha=args.setup_python,
        upload_artifact_sha=args.upload_artifact, env=os.environ,
    )
    elapsed = time.monotonic() - started
    summary = [
        f"RUNTIME_FINGERPRINT_VALID={'true' if valid else 'false'}",
        f"reason={reason}",
    ]
    if build is not None:
        summary.append(
            f"BUILD_IDENTITY_VALID={'true' if build.valid else 'false'}"
        )
        summary.append(f"build_reason={build.reason or 'ok'}")
        constraint_ready = (
            build.valid and build.constraint_digest is not None
            and (out_dir / "build_constraints.txt").exists()
            and _positive_marker(out_dir / "build_constraint_positive.log")
        )
        summary.append(f"BUILD_CONSTRAINT_READY={'true' if constraint_ready else 'false'}")
        for key in (
            "build_static", "wheelhouse", "build_dynamic", "build_effective",
            "constraint", "positive", "negative",
        ):
            summary.append(
                f"{key.upper()}_SECONDS={build.times.get(key, 0.0):.3f}"
            )
    if valid:
        assert fingerprint_sha is not None
        summary.append(f"fingerprint_sha256={fingerprint_sha}")
    summary.append(f"PROBE_ELAPSED_SECONDS={elapsed:.3f}")
    if not valid:
        _write_invalid_fingerprint(out_dir, args.surface, reason)
    text = "\n".join(summary) + "\n"
    (out_dir / "probe_summary.txt").write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(text)
    return 0


def _positive_marker(log_path: Path) -> bool:
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=true" in text


# ---------------------------------------------------------------------------
# verify-installed: probe vs actual heavy runtime.
# ---------------------------------------------------------------------------


def _parse_actual_report(path: Path) -> tuple[dict[str, dict] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None, "actual_report_unreadable"
    distributions, reason = parse_pip_report(data)
    if reason:
        return None, f"actual_report_{reason}"
    assert distributions is not None
    return {entry["name"]: entry for entry in distributions}, None


def _importlib_cross_check(records: dict[str, dict]) -> list[str]:
    """The report is the authoritative install record; this cross-checks
    the actual installed distributions via importlib.metadata (the live
    environment truth). Returns the list of mismatches."""
    mismatches = []
    for name in sorted(records):
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"{name}:not_installed")
            continue
        if actual != records[name]["version"]:
            mismatches.append(f"{name}:{records[name]['version']}!=installed_{actual}")
    return mismatches


def evaluate_verification(
    *,
    surface: str,
    fingerprint: dict | None,
    effective: dict[str, dict],
    install_verified: bool,
    install_reason: str | None,
    importlib_mismatches: list[str],
    pyarrow_check: dict | None,
) -> dict:
    """Pure evaluation core of verify-installed (no I/O, no environment
    reads; all inputs injected). Returns the verification receipt."""
    probe_valid = False
    build_valid = False
    fingerprint_sha = None
    if isinstance(fingerprint, dict):
        ok, _ = validate_fingerprint(fingerprint)
        probe_valid = ok
        build_ok, _ = validate_build_isolation(
            fingerprint.get("build_isolation")
        )
        build_valid = build_ok
        fingerprint_sha = fingerprint.get("fingerprint_sha256")
    verified = install_verified and not importlib_mismatches
    verify_reason = install_reason
    if importlib_mismatches:
        verify_reason = f"importlib_cross_check_mismatch:{importlib_mismatches[0]}"
    actual_match = False
    match_reason: str | None = None
    if probe_valid and verified:
        match, reason = compare_distribution_sets(
            _distribution_map(fingerprint.get("resolved_distributions", [])),
            effective,
        )
        if match:
            actual_match = True
        else:
            match_reason = f"probe_vs_actual:{reason}"
    elif not probe_valid:
        match_reason = "probe_invalid"
    elif not verified:
        match_reason = verify_reason
    if surface == "pyarrow24" and actual_match:
        if pyarrow_check is None or not pyarrow_check.get("match"):
            actual_match = False
            match_reason = "pyarrow_import_version_mismatch"
    return {
        "schema_version": SCHEMA_VERSION,
        "surface": surface,
        "fingerprint_sha256": fingerprint_sha,
        "probe_valid": probe_valid,
        "build_isolation_valid": build_valid,
        "actual_install_verified": verified,
        "actual_install_match": actual_match,
        "reason": match_reason,
        "importlib_cross_check_mismatches": importlib_mismatches,
        "pyarrow_import_check": pyarrow_check,
    }


def cmd_verify_installed(args: argparse.Namespace) -> int:
    """Compare the pre-install fingerprint against the actual heavy
    runtime. Always exits 0 (measurement only)."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprint_path = Path(args.fingerprint)
    try:
        fingerprint = json.loads(fingerprint_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        fingerprint = None
    actual_report_files = sorted(Path(p) for p in args.actual_report)
    effective: dict[str, dict] = {}
    verified = True
    verify_reason: str | None = None
    for report_path in actual_report_files:
        records, reason = _parse_actual_report(report_path)
        if reason:
            verified = False
            verify_reason = reason
            continue
        assert records is not None
        effective.update(records)
    importlib_mismatches: list[str] = []
    if verified:
        importlib_mismatches = _importlib_cross_check(effective)
    probe_valid = (
        isinstance(fingerprint, dict)
        and validate_fingerprint(fingerprint)[0]
    )
    pyarrow_check: dict | None = None
    if args.surface == "pyarrow24" and verified and probe_valid:
        pyarrow_check = {"imported": False, "version": None, "match": False}
        try:
            module = importlib.import_module("pyarrow")
            version = getattr(module, "__version__", None)
            pyarrow_check = {
                "imported": True,
                "version": version,
                "match": version == "24.0.0",
            }
        except Exception:
            pyarrow_check = {"imported": False, "version": None, "match": False}
    receipt = evaluate_verification(
        surface=args.surface,
        fingerprint=fingerprint,
        effective=effective,
        install_verified=verified,
        install_reason=verify_reason,
        importlib_mismatches=importlib_mismatches,
        pyarrow_check=pyarrow_check,
    )
    receipt["actual_report_files"] = [
        path.name for path in actual_report_files
    ]
    (out_dir / "runtime_verification_receipt.json").write_text(
        canonical_serialize(receipt), encoding="utf-8", newline="\n"
    )
    actual_match = receipt["actual_install_match"]
    sys.stdout.write(
        f"PROBE_PREDICTED_RUNTIME_MATCHES_ACTUAL={'true' if actual_match else 'false'}\n"
        f"RUNTIME_ACTUAL_MATCH={'true' if actual_match else 'false'}\n"
        f"reason={receipt['reason'] or 'ok'}\n"
    )
    return 0


# ---------------------------------------------------------------------------
# build-receipt: assemble the final build-identity receipt from evidence.
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_build_report(path: Path) -> list[dict] | None:
    """Read a probe-written build resolver report (the
    {"surface": ..., "distributions": [...]} envelope of already-derived
    entries) and strictly re-validate every entry: canonical name, exact
    version, wheel filename, exact URL (credential-free), SHA256, sorted
    order. Any deviation makes the evidence unreadable (None)."""
    doc = _load_json(path)
    if doc is None:
        return None
    dists = doc.get("distributions") if isinstance(doc, dict) else None
    if not isinstance(dists, list) or not dists:
        return None
    result: list[dict] = []
    for entry in dists:
        if not isinstance(entry, dict):
            return None
        for field in ("name", "version", "filename", "url", "sha256"):
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                return None
        if canonicalize_name(entry["name"]) != entry["name"]:
            return None
        if not WHEEL_RE.fullmatch(entry["filename"]):
            return None
        if not SHA256_RE.fullmatch(entry["sha256"]):
            return None
        _, url_reason = normalize_download_url(entry["url"])
        if url_reason:
            return None
        result.append(
            {
                "name": entry["name"],
                "version": entry["version"],
                "filename": entry["filename"],
                "url": entry["url"],
                "sha256": entry["sha256"],
            }
        )
    if result != sorted(result, key=lambda entry: entry["name"]):
        return None
    return result


def _read_runtime_report(path: Path) -> list[dict] | None:
    """Read a probe-written runtime resolver report (the
    {"pip_version": ..., "install": [...]} envelope of already-derived
    entries) and strictly re-validate every entry: canonical name, exact
    version, credential-free exact URL, SHA256, sorted order."""
    doc = _load_json(path)
    if doc is None:
        return None
    dists = doc.get("install") if isinstance(doc, dict) else None
    if not isinstance(dists, list) or not dists:
        return None
    result: list[dict] = []
    for entry in dists:
        if not isinstance(entry, dict):
            return None
        for field in ("name", "version", "url", "sha256"):
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                return None
        if canonicalize_name(entry["name"]) != entry["name"]:
            return None
        if not SHA256_RE.fullmatch(entry["sha256"]):
            return None
        _, url_reason = normalize_download_url(entry["url"])
        if url_reason:
            return None
        result.append(
            {
                "name": entry["name"],
                "version": entry["version"],
                "url": entry["url"],
                "sha256": entry["sha256"],
            }
        )
    if result != sorted(result, key=lambda entry: entry["name"]):
        return None
    return result


def _read_dynamic_doc(path: Path) -> dict | None:
    doc = _load_json(path)
    if doc is None:
        return None
    if doc.get("dynamic_hook") != DYNAMIC_HOOK_NAME:
        return None
    normalized = doc.get("normalized_sorted")
    if not isinstance(normalized, list) or not all(
        isinstance(item, str) and item.strip() for item in normalized
    ):
        return None
    return doc


def _constraint_entries(path: Path) -> dict[str, tuple[str, str]] | None:
    """Parse a build constraint file into name -> (filename, sha256).
    Returns None on any malformed or non-file: line."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    entries: dict[str, tuple[str, str]] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = CONSTRAINT_LINE_RE.fullmatch(line)
        if not match:
            return None
        name, url, digest = match.groups()
        canonical = canonicalize_name(name)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "file":
            return None
        filename = parsed.path.rsplit("/", 1)[-1]
        if canonical in entries:
            return None
        entries[canonical] = (filename, digest)
    return entries


def cmd_build_receipt(args: argparse.Namespace) -> int:
    """Assemble build_identity_receipt.json from the retained evidence.
    Always exits 0 (measurement only)."""
    out_dir = Path(args.out_dir)
    fingerprint = _load_json(out_dir / "runtime_identity_v2.json")
    build_block = None
    if fingerprint is not None:
        ok, _ = validate_fingerprint(fingerprint)
        if ok:
            build_block = fingerprint.get("build_isolation")
    fingerprint_build = build_block if isinstance(build_block, dict) else {}

    static_entries = _read_build_report(
        out_dir / "build_static_resolver_report.json"
    )
    dynamic_doc = _read_dynamic_doc(out_dir / "build_dynamic_requirements.json")
    effective_entries = _read_build_report(
        out_dir / "build_effective_resolver_report.json"
    )
    constraint_entries = _constraint_entries(out_dir / "build_constraints.txt")
    wrong_entries = _constraint_entries(out_dir / "wrong_hash_constraint.txt")
    positive_log = (out_dir / "build_constraint_positive.log").read_text(
        encoding="utf-8", errors="replace"
    ) if (out_dir / "build_constraint_positive.log").exists() else ""
    negative_log = (out_dir / "build_constraint_negative.log").read_text(
        encoding="utf-8", errors="replace"
    ) if (out_dir / "build_constraint_negative.log").exists() else ""

    static_valid = static_entries is not None
    dynamic_valid = dynamic_doc is not None
    effective_valid = effective_entries is not None
    all_wheels = effective_entries is not None and all(
        WHEEL_RE.fullmatch(entry["filename"]) for entry in effective_entries
    )
    wheelhouse_verified = False
    if effective_entries is not None:
        wheelhouse_verified = True
        for entry in effective_entries:
            target = out_dir / "build-wheelhouse" / entry["filename"]
            if not target.exists() or sha256_file(target) != entry["sha256"]:
                wheelhouse_verified = False
                break

    # Positive gate: marker + no index fetch inside the constrained install
    # segment (the build environment must bind exactly the local wheels).
    positive_passed = "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=true" in positive_log
    separator = "--- P24_CONSTRAINED_INSTALL_BEGIN ---"
    if separator in positive_log:
        segment = positive_log.split(separator)[-1]
        if INDEX_FETCH_RE.search(segment):
            positive_passed = False
    negative_passed = "P24_NEGATIVE_WRONG_HASH_REJECTED=true" in negative_log
    wrong_hash_valid = _wrong_hash_differs(wrong_entries, constraint_entries)

    used_marker = "false"
    marker_path = Path(args.constraint_used_marker)
    try:
        used_marker = marker_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    if "BUILD_CONSTRAINT_USED=" not in used_marker:
        used_marker = "false"
    actual_used = used_marker.endswith("=true")

    flags = {
        "static_resolution_valid": static_valid,
        "dynamic_hook_valid": dynamic_valid,
        "effective_resolution_valid": effective_valid,
        "all_build_artifacts_wheels": all_wheels,
        "wheelhouse_hashes_verified": wheelhouse_verified,
        "positive_constraint_install_passed": positive_passed,
        "negative_wrong_hash_rejected": negative_passed and wrong_hash_valid,
        "actual_heavy_install_used_build_constraint": actual_used,
    }
    build_identity_valid = all(flags.values()) and static_valid

    declared = build_block.get("declared_requires") if isinstance(
        build_block, dict
    ) else None
    dynamic = build_block.get("dynamic_requires") if isinstance(
        build_block, dict
    ) else None
    effective = build_block.get("effective_build_distributions") if isinstance(
        build_block, dict
    ) else None
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "surface": args.surface,
        "build_backend": build_block.get("backend") if isinstance(
            build_block, dict
        ) else None,
        "declared_requirements": declared,
        "dynamic_requirements": dynamic,
        "effective_build_distributions": effective,
        "build_constraint_sha256": build_block.get(
            "build_constraint_sha256"
        ) if isinstance(build_block, dict) else None,
        "constraint_mode": build_block.get("constraint_mode") if isinstance(
            build_block, dict
        ) else None,
        **flags,
        "build_identity_valid": build_identity_valid,
        "reason": None if build_identity_valid else "build_identity_gate_failed",
    }
    (out_dir / "build_identity_receipt.json").write_text(
        canonical_serialize(receipt), encoding="utf-8", newline="\n"
    )
    sys.stdout.write(
        f"BUILD_IDENTITY_VALID={'true' if build_identity_valid else 'false'}\n"
    )
    return 0


def _wrong_hash_differs(
    wrong: dict | None, correct: dict | None
) -> bool:
    """The wrong-hash constraint must parse, bind the same package set, and
    differ in EXACTLY one SHA256."""
    if wrong is None or correct is None:
        return False
    if set(wrong) != set(correct):
        return False
    if any(wrong[name][0] != correct[name][0] for name in correct):
        return False
    differing = [
        name for name in correct
        if wrong[name][1] != correct[name][1]
    ]
    return len(differing) == 1


# ---------------------------------------------------------------------------
# bundle: self-contained evidence bundle + EVIDENCE_MANIFEST.json.
# ---------------------------------------------------------------------------

SURFACE_WORKSPACE_FILES = {
    "test-3.14": (
        "actual_install_report_314.json",
        "actual_install_314.log",
    ),
    "pyarrow24": (
        "actual_dev_install_report.json",
        "actual_dev_install.log",
        "actual_pyarrow_pin_report.json",
        "actual_pyarrow_pin.log",
    ),
}

BUNDLE_REQUIRED_FILES = (
    "runtime_identity_v2.json",
    "runtime_verification_receipt.json",
    "runtime_resolver_report.json",
    "build_static_resolver_report.json",
    "build_dynamic_requirements.json",
    "build_effective_resolver_report.json",
    "build_constraints.txt",
    "build_constraint_positive.log",
    "wrong_hash_constraint.txt",
    "build_constraint_negative.log",
    "build_identity_receipt.json",
    "actual_constraint_used.txt",
    "verifier_source.py",
    "probe_summary.txt",
    "probe_pip_dryrun.log",
)


def cmd_bundle(args: argparse.Namespace) -> int:
    """Assemble the self-contained evidence bundle and write
    EVIDENCE_MANIFEST.json. Always exits 0 (measurement only)."""
    out_dir = Path(args.out_dir)
    workspace = Path(args.workspace).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Exact verifier source copy: this script, as executed by this run.
    source = Path(__file__).resolve()
    if not source.exists():
        sys.stdout.write("EVIDENCE_MANIFEST_SHA256=missing_verifier_source\n")
        return 0
    target_source = out_dir / "verifier_source.py"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            shutil.copy2(source, target_source)
            break
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    else:
        # Windows fallback: some watchers hold the source without read
        # sharing; byte-copy instead of the API-based copy.
        try:
            target_source.write_bytes(source.read_bytes())
        except OSError:
            sys.stdout.write(
                f"EVIDENCE_MANIFEST_SHA256=copy_failed:{last_error}\n"
            )
            return 0

    required = list(BUNDLE_REQUIRED_FILES)
    missing: list[str] = []
    for name in SURFACE_WORKSPACE_FILES[args.surface]:
        src = workspace / name
        if not src.exists():
            missing.append(f"workspace:{name}")
        elif src.resolve() != (out_dir / name).resolve():
            shutil.copy2(src, out_dir / name)
        required.append(name)
    wheelhouse = out_dir / "build-wheelhouse"
    wheels = sorted(
        wheelhouse.glob("*.whl")
    ) if wheelhouse.exists() else []
    if not wheels:
        missing.append("build-wheelhouse:no_wheels")

    entries = []
    for path in sorted(required):
        target = out_dir / path
        if not target.is_file():
            if path not in missing:
                missing.append(f"bundle:{path}")
            continue
        entries.append(
            {
                "path": path,
                "size": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        )
    for wheel in wheels:
        rel = f"build-wheelhouse/{wheel.name}"
        entries.append(
            {
                "path": rel,
                "size": wheel.stat().st_size,
                "sha256": sha256_file(wheel),
            }
        )
    entries.sort(key=lambda entry: entry["path"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "surface": args.surface,
        "complete": not missing,
        "missing": sorted(set(missing)),
        "files": entries,
    }
    manifest_path = out_dir / "EVIDENCE_MANIFEST.json"
    manifest_path.write_text(
        canonical_serialize(manifest), encoding="utf-8", newline="\n"
    )
    digest = sha256_file(manifest_path)
    sys.stdout.write(f"EVIDENCE_MANIFEST_SHA256={digest}\n")
    if missing:
        sys.stdout.write(
            "EVIDENCE_BUNDLE_INCOMPLETE=" + ",".join(sorted(set(missing))) + "\n"
        )
    return 0


# ---------------------------------------------------------------------------
# verify-bundle: OFFLINE replay gate.
# ---------------------------------------------------------------------------


def _replay_check(results: list[tuple[str, bool]], name: str, ok: bool) -> bool:
    results.append((name, ok))
    return ok


def cmd_verify_bundle(args: argparse.Namespace) -> int:
    """Offline replay of the retained evidence bundle. Never touches the
    network. Always exits 0 (measurement only): the marker line carries the
    verdict."""
    bundle = Path(args.bundle_dir)
    started = time.monotonic()
    results: list[tuple[str, bool]] = []
    summary_lines: list[str] = []

    manifest = _load_json(bundle / "EVIDENCE_MANIFEST.json")
    _replay_check(results, "manifest_present", manifest is not None)
    if manifest is None:
        return _finish_replay(bundle, results, started)

    if manifest.get("schema_version") != SCHEMA_VERSION:
        _replay_check(results, "manifest_schema", False)
        return _finish_replay(bundle, results, started)
    _replay_check(results, "manifest_schema", True)

    complete = manifest.get("complete") is True
    _replay_check(results, "manifest_complete", complete)

    files = manifest.get("files")
    if not isinstance(files, list):
        _replay_check(results, "manifest_files", False)
        return _finish_replay(bundle, results, started)
    manifest_ok = True
    manifest_by_path: dict[str, dict] = {}
    for entry in files:
        if not isinstance(entry, dict):
            manifest_ok = False
            break
        path = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if (
            not isinstance(path, str) or not isinstance(size, int)
            or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
        ):
            manifest_ok = False
            break
        if "/" in path.replace("\\", "/") and ".." in path:
            manifest_ok = False
            break
        manifest_by_path[path] = entry
        target = bundle / path
        if not target.is_file():
            manifest_ok = False
            break
        if target.stat().st_size != size:
            manifest_ok = False
            break
        if sha256_file(target) != digest:
            manifest_ok = False
            break
    _replay_check(results, "manifest_hashes", manifest_ok)

    # Every file in the bundle (except the manifest and the replay summary)
    # must be bound by the manifest.
    unbound: list[str] = []
    for target in sorted(bundle.rglob("*")):
        if not target.is_file():
            continue
        rel = target.relative_to(bundle).as_posix()
        if rel in ("EVIDENCE_MANIFEST.json", "replay_summary.txt"):
            continue
        if rel not in manifest_by_path:
            unbound.append(rel)
    _replay_check(results, "manifest_binding", not unbound)

    fingerprint = _load_json(bundle / "runtime_identity_v2.json")
    fp_valid = False
    if fingerprint is not None:
        fp_valid, fp_reason = validate_fingerprint(fingerprint)
    _replay_check(results, "fingerprint_valid", fp_valid)
    if fp_valid:
        assert fingerprint is not None
        digest_ok = (
            compute_fingerprint_sha(fingerprint)
            == fingerprint.get("fingerprint_sha256")
        )
        _replay_check(results, "fingerprint_digest", digest_ok)
        build_block = fingerprint.get("build_isolation")
        effective = build_block.get("effective_build_distributions")
        declared = build_block.get("declared_requires")
        dynamic = build_block.get("dynamic_requires")
        constraint_digest = build_block.get("build_constraint_sha256")
    else:
        _replay_check(results, "fingerprint_digest", False)
        effective = declared = dynamic = constraint_digest = None

    # Resolver-report normalization: probe runtime set == fingerprint set.
    resolver_entries = _read_runtime_report(
        bundle / "runtime_resolver_report.json"
    )
    resolver_ok = (
        resolver_entries is not None
        and fp_valid
        and _distribution_map(resolver_entries)
        == _distribution_map(fingerprint.get("resolved_distributions", []))
    )
    _replay_check(results, "resolver_normalization", resolver_ok)

    # Build reports vs fingerprint build identity.
    static_entries = _read_build_report(bundle / "build_static_resolver_report.json")
    dynamic_doc = _read_dynamic_doc(bundle / "build_dynamic_requirements.json")
    effective_entries = _read_build_report(bundle / "build_effective_resolver_report.json")
    build_reports_ok = (
        static_entries is not None
        and dynamic_doc is not None
        and effective_entries is not None
    )
    if build_reports_ok and fp_valid:
        effective_ok = {
            (entry["name"], entry["version"], entry["filename"], entry["sha256"])
            for entry in effective_entries
        } == {
            (entry["name"], entry["version"], entry["filename"], entry["sha256"])
            for entry in effective
        }
        dynamic_ok = (
            dynamic_doc.get("normalized_sorted") == dynamic
        )
        build_reports_ok = effective_ok and dynamic_ok
    _replay_check(results, "build_reports_identity", build_reports_ok)

    # Wheelhouse hashes.
    wheelhouse_ok = False
    if fp_valid and effective_entries is not None:
        wheelhouse_ok = True
        for entry in effective_entries:
            target = bundle / "build-wheelhouse" / entry["filename"]
            if not target.is_file() or sha256_file(target) != entry["sha256"]:
                wheelhouse_ok = False
                break
        if wheelhouse_ok:
            manifest_wheels = [
                (entry.get("path"), entry.get("sha256"))
                for entry in manifest_by_path.values()
                if entry.get("path", "").startswith("build-wheelhouse/")
            ]
            for path, digest in manifest_wheels:
                if sha256_file(bundle / path) != digest:
                    wheelhouse_ok = False
                    break
    _replay_check(results, "wheelhouse_hashes", wheelhouse_ok)

    # Constraint identity.
    constraint_ok = False
    if fp_valid and effective_entries is not None:
        constraint_entries = _constraint_entries(bundle / "build_constraints.txt")
        if constraint_entries is not None:
            names = sorted(constraint_entries)
            effective_map = {
                entry["name"]: (entry["filename"], entry["sha256"])
                for entry in effective_entries
            }
            if names == sorted(effective_map) and all(
                constraint_entries[name] == effective_map[name] for name in names
            ):
                constraint_ok = (
                    sha256_file(bundle / "build_constraints.txt")
                    == constraint_digest
                )
    _replay_check(results, "constraint_identity", constraint_ok)

    # Wrong-hash negative identity.
    wrong_entries = _constraint_entries(bundle / "wrong_hash_constraint.txt")
    correct_entries = _constraint_entries(bundle / "build_constraints.txt")
    wrong_ok = _wrong_hash_differs(wrong_entries, correct_entries)
    negative_log = (bundle / "build_constraint_negative.log").read_text(
        encoding="utf-8", errors="replace"
    ) if (bundle / "build_constraint_negative.log").exists() else ""
    negative_marker = "P24_NEGATIVE_WRONG_HASH_REJECTED=true" in negative_log
    _replay_check(results, "wrong_hash_negative", wrong_ok and negative_marker)

    # Positive constraint test identity.
    positive_log = (bundle / "build_constraint_positive.log").read_text(
        encoding="utf-8", errors="replace"
    ) if (bundle / "build_constraint_positive.log").exists() else ""
    positive_marker = "P24_POSITIVE_BUILD_CONSTRAINT_INSTALL_PASSED=true" in positive_log
    separator = "--- P24_CONSTRAINED_INSTALL_BEGIN ---"
    positive_no_index = True
    if separator in positive_log:
        positive_no_index = (
            INDEX_FETCH_RE.search(positive_log.split(separator)[-1]) is None
        )
    _replay_check(
        results, "positive_constraint", positive_marker and positive_no_index
    )

    # Runtime report vs receipt. The receipt records BOTH file-derived
    # verdicts (parsed install reports) and live-environment verdicts
    # (importlib cross-check, pyarrow live import) that are recorded but
    # inherently NOT offline-replayable. The offline gate proves the
    # file-derived side: the retained actual reports must normalize to
    # exactly the fingerprint's resolved set, and the receipt's digest /
    # surface bindings must hold. A receipt claiming actual_install_match
    # while the retained files do NOT match fails the replay.
    receipt = _load_json(bundle / "runtime_verification_receipt.json")
    receipt_ok = False
    if receipt is not None and fp_valid:
        receipt_ok = (
            receipt.get("fingerprint_sha256") == fingerprint.get("fingerprint_sha256")
            and receipt.get("surface") == fingerprint.get("surface")
        )
        actual_files = receipt.get("actual_report_files")
        if receipt_ok and isinstance(actual_files, list):
            derived: dict[str, dict] = {}
            parse_ok = True
            for name in actual_files:
                target = bundle / name
                if not target.is_file():
                    parse_ok = False
                    break
                records, reason = _parse_actual_report(target)
                if reason:
                    parse_ok = False
                    break
                assert records is not None
                derived.update(records)
            if not parse_ok:
                receipt_ok = False
            else:
                match, _ = compare_distribution_sets(
                    _distribution_map(fingerprint.get("resolved_distributions", [])),
                    derived,
                )
                receipt_ok = match
        else:
            receipt_ok = False
    _replay_check(results, "runtime_receipt", receipt_ok)

    # Build receipt consistency.
    build_receipt = _load_json(bundle / "build_identity_receipt.json")
    build_receipt_ok = False
    if build_receipt is not None and fp_valid and constraint_ok:
        build_receipt_ok = (
            build_receipt.get("build_backend") == build_block.get("backend")
            and build_receipt.get("declared_requirements") == declared
            and build_receipt.get("dynamic_requirements") == dynamic
            and build_receipt.get("effective_build_distributions") == effective
            and build_receipt.get("build_constraint_sha256") == constraint_digest
            and build_receipt.get("constraint_mode") == CONSTRAINT_MODE
        )
        if build_receipt_ok:
            used_marker = (bundle / "actual_constraint_used.txt").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
            marker_used = used_marker.endswith("=true")
            build_receipt_ok = (
                bool(build_receipt.get("actual_heavy_install_used_build_constraint"))
                == marker_used
            )
        if build_receipt_ok:
            build_receipt_ok = (
                bool(build_receipt.get("build_identity_valid"))
                == (
                    build_receipt.get("static_resolution_valid")
                    and build_receipt.get("dynamic_hook_valid")
                    and build_receipt.get("effective_resolution_valid")
                    and build_receipt.get("all_build_artifacts_wheels")
                    and build_receipt.get("wheelhouse_hashes_verified")
                    and build_receipt.get("positive_constraint_install_passed")
                    and build_receipt.get("negative_wrong_hash_rejected")
                    and build_receipt.get("actual_heavy_install_used_build_constraint")
                )
            )
    _replay_check(results, "build_receipt_consistency", build_receipt_ok)

    # The retained verifier source is the running script.
    running_source = Path(__file__).resolve()
    source_ok = False
    if running_source.is_file():
        manifest_entry = manifest_by_path.get("verifier_source.py")
        if manifest_entry is not None:
            source_ok = (
                running_source.stat().st_size == manifest_entry.get("size")
                and sha256_file(running_source) == manifest_entry.get("sha256")
            )
    _replay_check(results, "verifier_source", source_ok)

    ok = all(flag for _, flag in results)
    for name, flag in results:
        summary_lines.append(f"REPLAY_CHECK_{name}={'ok' if flag else 'FAIL'}")
    if ok:
        summary_lines.append("EVIDENCE_BUNDLE_REPLAY_OK")
    else:
        failed = next((name for name, flag in results if not flag), "unknown")
        summary_lines.append(f"EVIDENCE_BUNDLE_REPLAY_FAIL reason={failed}")
    summary_lines.append(
        f"REPLAY_ELAPSED_SECONDS={time.monotonic() - started:.3f}"
    )
    return _finish_replay(bundle, results, started, summary_lines)


def _finish_replay(
    bundle: Path, results: list[tuple[str, bool]], started: float,
    extra_lines: list[str] | None = None,
) -> int:
    lines = list(extra_lines or [])
    if not lines:
        lines.append("EVIDENCE_BUNDLE_REPLAY_FAIL reason=manifest_missing")
        lines.append(f"REPLAY_ELAPSED_SECONDS={time.monotonic() - started:.3f}")
    try:
        (bundle / "replay_summary.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
        )
    except OSError:
        pass
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


# ---------------------------------------------------------------------------
# compare / canonicalize.
# ---------------------------------------------------------------------------


def _load_document(path: str) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def cmd_compare(args: argparse.Namespace) -> int:
    """Pure comparator over two fingerprint files. Always exits 0: the
    marker line carries the verdict; nothing in the canary consumes it."""
    a = _load_document(args.a)
    b = _load_document(args.b)
    if a is None or b is None:
        sys.stdout.write(
            "RUNTIME_V2_FINGERPRINT_MATCH=false\n"
            f"reason={'malformed_json_a' if a is None and b is not None else ('malformed_json_b' if b is None and a is not None else 'malformed_json')}\n"
        )
        return 0
    ok_a, reason_a = validate_fingerprint(a)
    ok_b, reason_b = validate_fingerprint(b)
    if not ok_a:
        sys.stdout.write(
            "RUNTIME_V2_FINGERPRINT_MATCH=false\n"
            f"reason=invalid_fingerprint_a:{reason_a}\n"
        )
        return 0
    if not ok_b:
        sys.stdout.write(
            "RUNTIME_V2_FINGERPRINT_MATCH=false\n"
            f"reason=invalid_fingerprint_b:{reason_b}\n"
        )
        return 0
    match, reason = compare_fingerprints(a, b)
    sys.stdout.write(
        f"RUNTIME_V2_FINGERPRINT_MATCH={'true' if match else 'false'}\n"
        f"reason={reason}\n"
    )
    return 0


def cmd_canonicalize(args: argparse.Namespace) -> int:
    """Print the canonical payload of a fingerprint (with the
    fingerprint_sha256 field omitted) and verify the stored digest."""
    doc = _load_document(args.input)
    if doc is None:
        sys.stdout.write("FINGERPRINT_CANONICAL=INVALID reason=malformed_json\n")
        return 0
    ok, reason = validate_fingerprint(doc)
    if not ok:
        sys.stdout.write(f"FINGERPRINT_CANONICAL=INVALID reason={reason}\n")
        return 0
    payload = canonical_payload(doc)
    sys.stdout.write(canonical_serialize(payload))
    sys.stdout.write(f"fingerprint_sha256={compute_fingerprint_sha(doc)}\n")
    return 0


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="P2-4 build-isolation identity + evidence-closure canary "
        "tool (TEMPORARY, measurement only, fail-closed)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="create the pre-install V2 fingerprint")
    probe.add_argument("--surface", required=True, choices=SURFACES)
    probe.add_argument("--repo", default=".", help="repository root (default .)")
    probe.add_argument("--out-dir", required=True)
    probe.add_argument("--actions-checkout", dest="checkout", required=True)
    probe.add_argument("--actions-setup-python", dest="setup_python", required=True)
    probe.add_argument("--actions-upload-artifact", dest="upload_artifact", required=True)

    verify = sub.add_parser(
        "verify-installed",
        help="verify a fingerprint against the actual heavy install reports",
    )
    verify.add_argument("--surface", required=True, choices=SURFACES)
    verify.add_argument("--fingerprint", required=True)
    verify.add_argument("--actual-report", action="append", required=True,
                        help="pip install --report JSON (repeatable; later "
                             "reports override earlier canonical entries)")
    verify.add_argument("--out-dir", required=True)

    build_receipt = sub.add_parser(
        "build-receipt",
        help="assemble build_identity_receipt.json from retained evidence",
    )
    build_receipt.add_argument("--surface", required=True, choices=SURFACES)
    build_receipt.add_argument("--out-dir", required=True)
    build_receipt.add_argument("--constraint-used-marker", required=True,
                               help="file written by the heavy install step "
                                    "containing BUILD_CONSTRAINT_USED=...")

    bundle = sub.add_parser(
        "bundle", help="assemble the self-contained evidence bundle"
    )
    bundle.add_argument("--surface", required=True, choices=SURFACES)
    bundle.add_argument("--out-dir", required=True)
    bundle.add_argument("--workspace", default=".",
                        help="workspace root containing the actual install "
                             "reports/logs (default .)")

    verify_bundle = sub.add_parser(
        "verify-bundle", help="offline replay gate over a retained bundle"
    )
    verify_bundle.add_argument("--bundle-dir", default=".")

    compare = sub.add_parser("compare", help="compare two fingerprints")
    compare.add_argument("--a", required=True)
    compare.add_argument("--b", required=True)

    canonicalize = sub.add_parser(
        "canonicalize", help="print the canonical payload and digest"
    )
    canonicalize.add_argument("--input", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "verify-installed":
        return cmd_verify_installed(args)
    if args.command == "build-receipt":
        return cmd_build_receipt(args)
    if args.command == "bundle":
        return cmd_bundle(args)
    if args.command == "verify-bundle":
        return cmd_verify_bundle(args)
    if args.command == "compare":
        return cmd_compare(args)
    if args.command == "canonicalize":
        return cmd_canonicalize(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
