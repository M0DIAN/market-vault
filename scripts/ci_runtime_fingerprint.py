"""P2-3 runtime identity fingerprint canary tool (TEMPORARY, PR #78).

Measurement-only shadow evidence for the runtime/dependency identity gap
identified by sealed PR #77. This tool is CANARY-ONLY: it exists only
during the temporary measurement heads, is never wired into any production
skip decision, and is removed entirely on the final docs-only head.

Purpose: a target head, BEFORE running its heavy surface, resolves and
fingerprints the runtime it WOULD use, strongly enough that

    SOURCE_RUNTIME_FINGERPRINT == TARGET_RUNTIME_FINGERPRINT

could become one required gate in a future cross-head reuse proof.

Stdlib only. Deterministic. Fail closed: anything missing, ambiguous,
malformed, or unproven makes the fingerprint INVALID (a future decision
must RUN), never silently downgrades to a weaker identity.

Subcommands:

  probe
      Create the pre-install runtime fingerprint of the environment the
      surface WOULD use. Runs inside a clean temporary venv created from
      the exact surface Python interpreter: upgrade pip inside the venv,
      record the exact pip version, then resolve the surface contract with
      ``pip install --dry-run --ignore-installed --report <json>`` and
      derive the exact remote distribution set (canonical names, versions,
      normalized download URLs, SHA256 archive hashes). NEVER installs the
      MarketVault dependency environment into the probe venv.

  verify-installed
      Verify a pre-install fingerprint against the ACTUAL heavy runtime:
      one or more machine-readable ``pip install --report`` files (later
      reports override earlier entries for the same canonical package) and,
      for the pyarrow24 surface, the live ``pyarrow.__version__`` import.
      Writes verification_receipt.json.

  compare
      Pure comparator over two fingerprint JSON files. Prints
      ``RUNTIME_FINGERPRINT_MATCH=true`` or ``RUNTIME_FINGERPRINT_MATCH=
      false`` with the exact first-mismatch reason. No permissive fallback.

  canonicalize
      Print the canonical payload (deterministic UTF-8 JSON, sort_keys,
      compact separators, newline-terminated, resolved_distributions sorted
      by canonical name) of a fingerprint and its fingerprint_sha256.

Fingerprint schema V1 (owned by this module):

  {
    "schema_version": 1,
    "surface": "test-3.14" | "pyarrow24",
    "runner": {...},               # RUNNER_OS/RUNNER_ARCH/ImageOS/ImageVersion
                                   # + sys.platform, machine, release,
                                   # libc_ver, sysconfig.get_platform()
    "python": {...},               # implementation, exact x.y.z, cache_tag,
                                   # SOABI, pointer width
    "resolver": {...},             # exact pip version
    "dependency_contract": {...},  # project name/version, declared ranges,
                                   # SHA256(pyproject.toml)
    "action_contract": {...},      # exact canary-pinned action SHAs,
                                   # SHA256(.github/workflows/ci.yml)
    "resolved_distributions": [...],  # sorted, deduplicated external set
    "fingerprint_sha256": "..."    # SHA256 of the canonical payload with
                                   # this field omitted
  }

Canonical serialization: UTF-8, JSON, sort_keys=True, separators=(",", ":"),
ensure_ascii=True, newline-terminated. The resolved_distributions array is
sorted by canonical package name before hashing, so array ordering in raw
input never changes the fingerprint. fingerprint_sha256 is the SHA256 of
the canonical payload with the fingerprint_sha256 field omitted.

No timestamps. No run IDs. No job IDs. No head SHA. No absolute workspace
path. No ephemeral runner name. Re-running the probe in the same runtime
must reproduce the same fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
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
import urllib.parse
from pathlib import Path

SCHEMA_VERSION = 1

SURFACES = ("test-3.14", "pyarrow24")

# The exact measured surfaces and their resolution contracts. The probe
# dry-run mirrors the surface's real install command as closely as the
# machine-readable report mechanism allows.
SURFACE_REQUIREMENTS = {
    # The Python 3.14 leg of the test matrix: editable dev install. The
    # requirements are passed as direct argv (no shell), so the quoted
    # shell form is spelled as separate argv tokens.
    "test-3.14": ("-e", ".[dev]"),
    # portability-pyarrow24: the effective FINAL runtime is the dev
    # install followed by the pyarrow==24.0.0 pin, represented as one
    # combined resolution of both constraints.
    "pyarrow24": ("-e", ".[dev]", "pyarrow==24.0.0"),
}

LOCAL_PROJECT_NAME = "market-vault"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

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
    silently stripped: we cannot prove that stripping is safe, so the
    fingerprint must not accept them."""
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
    minus the fingerprint_sha256 field, with resolved_distributions sorted
    by canonical package name so array ordering never changes the
    fingerprint."""
    payload = {
        key: value
        for key, value in doc.items()
        if key != "fingerprint_sha256"
    }
    dists = payload.get("resolved_distributions")
    if isinstance(dists, list):
        payload["resolved_distributions"] = sorted(
            dists, key=lambda entry: str(entry.get("name", ""))
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
    "run_os",        # env RUNNER_OS
    "run_arch",      # env RUNNER_ARCH
    "image_os",      # env ImageOS (GitHub-hosted)
    "image_version", # env ImageVersion (GitHub-hosted)
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
    "version",       # exact x.y.z of the resolved interpreter
    "major",
    "minor",
    "micro",
    "cache_tag",
    "soabi",         # may be null on platforms without a SOABI (Windows)
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


def _missing_reason(fields: tuple[str, ...], block: dict, prefix: str) -> str | None:
    for field in fields:
        value = block.get(field)
        if value is None or value == "" or value == []:
            return f"missing_{prefix}_{field}"
    return None


def validate_fingerprint(doc: object) -> tuple[bool, str | None]:
    """Strict schema validation of a fingerprint document. Returns
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

# The exact comparison order. Every comparison function returns
# (match, reason_or_none); the first failure is reported.
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
    if a.get("fingerprint_sha256") != b.get("fingerprint_sha256"):
        return False, "fingerprint_sha256_unequal"
    return True, "ok"


def compare_distribution_sets(
    map_a: dict, map_b: dict
) -> tuple[bool, str]:
    """Compare two canonical-name -> {version, url, sha256} maps. Returns
    (True, "ok") or (False, exact reason). Used both by the full
    fingerprint comparator and by the probe-vs-actual-install
    verification (which compares only the resolved distribution sets)."""
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
# Probe: identity collection.
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runner_identity(env: dict[str, str]) -> dict | None:
    """Runner identity from the GitHub-hosted environment. Any missing
    required env value makes the fingerprint INVALID (None returned); we
    never substitute "unknown" and still call the fingerprint valid."""
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
    tomllib; the local project's source identity is covered separately by
    the cross-head source-input proof, and SHA256(pyproject.toml) binds
    the declared contract)."""
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
    SHA256(.github/workflows/ci.yml) — an immutable action/runtime
    contract for the experiment because the temporary workflow is
    exact-SHA pinned."""
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
            continue  # the local project's source identity is proven
            # separately by the cross-head source-input proof.
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


def _parse_pip_version(pip_version_output: str) -> str | None:
    """``pip 26.2.1 from ...`` -> ``26.2.1``. Anything else is unparseable
    and fails the probe closed."""
    parts = pip_version_output.strip().split()
    if len(parts) < 2 or parts[0] != "pip":
        return None
    return parts[1]


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


def _run_probe(
    *, surface: str, repo_root: Path, out_dir: Path,
    checkout_sha: str, setup_python_sha: str, upload_artifact_sha: str,
    env: dict[str, str],
) -> tuple[bool, str, str | None]:
    """The full probe pipeline. Returns (valid, reason, fingerprint_sha)
    where fingerprint_sha is None when invalid. Never raises."""
    try:
        runner = runner_identity(env)
        if runner is None:
            return False, "missing_runner_image_version", None
        requirements = SURFACE_REQUIREMENTS[surface]
        work_dir = Path(tempfile.mkdtemp(prefix="mv-fp-probe-"))
        try:
            venv_dir = work_dir / "venv"
            log = out_dir / "probe_pip_dryrun.log"
            proc = _run([sys.executable, "-m", "venv", str(venv_dir)], repo_root, log)
            if proc.returncode != 0:
                return False, "venv_creation_failed", None
            probe_python = _venv_python(venv_dir)
            proc = _run(
                [str(probe_python), "-m", "pip", "install", "--upgrade", "pip"],
                repo_root, log,
            )
            if proc.returncode != 0:
                return False, "resolver_bootstrap_failed", None
            proc = _run([str(probe_python), "-m", "pip", "--version"], repo_root, log)
            if proc.returncode != 0:
                return False, "pip_version_failed", None
            pip_version = _parse_pip_version(proc.stdout)
            if pip_version is None:
                return False, "pip_version_unparseable", None
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
                return False, "pip_dryrun_failed", None
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                return False, "pip_report_unreadable", None
            distributions, report_reason = parse_pip_report(report)
            if report_reason:
                return False, report_reason, None
            contract = dependency_contract(repo_root)
            if contract is None:
                return False, "pyproject_unreadable", None
            actions = action_contract(
                repo_root, checkout_sha, setup_python_sha, upload_artifact_sha
            )
            if actions is None:
                return False, "action_contract_invalid", None
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
            doc["fingerprint_sha256"] = compute_fingerprint_sha(doc)
            ok, reason = validate_fingerprint(doc)
            if not ok:
                return False, f"self_check_{reason}", None
            (out_dir / "runtime_fingerprint.json").write_text(
                canonical_serialize(doc), encoding="utf-8", newline="\n"
            )
            resolver_evidence = {
                "pip_version": pip_version,
                "install": distributions,
            }
            (out_dir / "resolver_report.json").write_text(
                canonical_serialize(resolver_evidence),
                encoding="utf-8", newline="\n",
            )
            return True, "ok", doc["fingerprint_sha256"]
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        return False, "probe_internal_error", None


def _write_invalid_fingerprint(out_dir: Path, surface: str, reason: str) -> None:
    doc = {
        "schema_version": SCHEMA_VERSION,
        "surface": surface,
        "valid": False,
        "invalid_reason": reason,
    }
    (out_dir / "runtime_fingerprint.json").write_text(
        canonical_serialize(doc), encoding="utf-8", newline="\n"
    )


def cmd_probe(args: argparse.Namespace) -> int:
    """Always exits 0 (measurement only): a probe failure must NOT fail the
    heavy surface; the marker line carries validity and the heavy chain
    runs regardless. The script catches everything so the shadow probe can
    never become a production skip gate."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(args.repo).resolve()
    started = time.monotonic()
    valid, reason, fingerprint_sha = _run_probe(
        surface=args.surface, repo_root=repo_root, out_dir=out_dir,
        checkout_sha=args.checkout, setup_python_sha=args.setup_python,
        upload_artifact_sha=args.upload_artifact, env=os.environ,
    )
    elapsed = time.monotonic() - started
    summary = [
        f"RUNTIME_FINGERPRINT_VALID={'true' if valid else 'false'}",
        f"reason={reason}",
    ]
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
    fingerprint_sha = None
    if isinstance(fingerprint, dict):
        ok, _ = validate_fingerprint(fingerprint)
        probe_valid = ok
        fingerprint_sha = fingerprint.get("fingerprint_sha256")
    verified = install_verified and not importlib_mismatches
    verify_reason = install_reason
    if importlib_mismatches:
        verify_reason = f"importlib_cross_check_mismatch:{importlib_mismatches[0]}"
    actual_match = False
    match_reason: str | None = None
    if probe_valid and verified:
        # Probe-vs-actual compares ONLY the resolved distribution sets:
        # the actual install reports do not carry runner/python/resolver
        # identity (those are the probe's own claims and are compared
        # across heads by the full comparator).
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
    effective: dict[str, dict] = {}
    verified = True
    verify_reason: str | None = None
    for report_path in map(Path, args.actual_report):
        records, reason = _parse_actual_report(report_path)
        if reason:
            verified = False
            verify_reason = reason
            continue
        assert records is not None
        effective.update(records)  # later install/pin report overrides earlier
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
    (out_dir / "verification_receipt.json").write_text(
        canonical_serialize(receipt), encoding="utf-8", newline="\n"
    )
    actual_match = receipt["actual_install_match"]
    sys.stdout.write(
        f"PROBE_PREDICTED_RUNTIME_MATCHES_ACTUAL={'true' if actual_match else 'false'}\n"
        f"reason={receipt['reason'] or 'ok'}\n"
    )
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
            "RUNTIME_FINGERPRINT_MATCH=false\n"
            f"reason={'malformed_json_a' if a is None and b is not None else ('malformed_json_b' if b is None and a is not None else 'malformed_json')}\n"
        )
        return 0
    ok_a, reason_a = validate_fingerprint(a)
    ok_b, reason_b = validate_fingerprint(b)
    if not ok_a:
        sys.stdout.write(
            "RUNTIME_FINGERPRINT_MATCH=false\n"
            f"reason=invalid_fingerprint_a:{reason_a}\n"
        )
        return 0
    if not ok_b:
        sys.stdout.write(
            "RUNTIME_FINGERPRINT_MATCH=false\n"
            f"reason=invalid_fingerprint_b:{reason_b}\n"
        )
        return 0
    match, reason = compare_fingerprints(a, b)
    sys.stdout.write(
        f"RUNTIME_FINGERPRINT_MATCH={'true' if match else 'false'}\n"
        f"reason={reason}\n"
    )
    return 0


def cmd_canonicalize(args: argparse.Namespace) -> int:
    """Print the canonical payload of a fingerprint (with the
    fingerprint_sha256 field omitted — the payload that is hashed) and
    verify the stored fingerprint_sha256."""
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
        description="P2-3 runtime identity fingerprint canary tool "
        "(TEMPORARY, measurement only, fail-closed)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="create the pre-install runtime fingerprint")
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
    if args.command == "compare":
        return cmd_compare(args)
    if args.command == "canonicalize":
        return cmd_canonicalize(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
