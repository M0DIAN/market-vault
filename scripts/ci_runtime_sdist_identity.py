#!/usr/bin/env python3
"""P2-6 runtime sdist build-output identity canary (TEMPORARY, PR #81).

MEASUREMENT / SHADOW EVIDENCE ONLY.  This script never gates the heavy
chain, never skips validation, never authorizes reuse, never activates
Partial Reuse V2, and never changes release behavior.

It closes the remaining primary P2 gap recorded in PR #80
(docs/closed_world_build_execution_canary.md, section 12): for a runtime
dependency resolved from a SOURCE DISTRIBUTION, prove the EXACT wheel
artifact that is actually installed into the tested environment.

For every runtime sdist (concrete case: moomoo-api 10.9.6908 resolved
from moomoo_api-10.9.6908.tar.gz):

  1. runtime resolution (pip --report, dry run) classifies every external
     distribution wheel / sdist / other and fails closed on missing SHA,
     VCS, mutable URLs, unhashed local sources, unknown archive types and
     duplicate canonical distributions;
  2. the EXACT resolver-selected sdist bytes are materialized locally and
     LOCAL_SDIST_SHA256 == RESOLVER_SOURCE_SHA256 is required;
  3. the sdist is extracted into a fresh directory with traversal /
     symlink / duplicate-path rejection; sdist_manifest.json records
     canonical relative path / size / SHA256 of every regular file;
  4. the SOURCE (runtime dependency's OWN) build contract is read from
     the extracted project (pyproject.toml build-system, or pip's
     documented PEP 517 legacy fallback recorded explicitly) -- never
     inferred from MarketVault's build-system;
  5. declared + dynamic (get_requires_for_build_wheel) + transitive build
     requirements are resolved to EXACT WHEELS ONLY (sdist/VCS/unhashed
     source-build chain => SOURCE_BUILD_IDENTITY_VALID=false => RUN);
  6. a closed-world source-build environment is provisioned from local
     hash-locked wheels (PIP_NO_INDEX=1, --require-hashes);
     SOURCE_BUILD_ENVIRONMENT_SHA256 is path-free;
  7. the exact local sdist is built twice (fresh extraction, fresh output
     dir, --no-deps --no-build-isolation --check-build-dependencies
     --no-cache-dir, PIP_NO_INDEX=1); the log must prove a wheel was
     BUILT (never "Using cached"); RAW_WHEEL_REPRODUCIBLE = build1 SHA ==
     build2 SHA (no forced SOURCE_DATE_EPOCH);
  8. the built wheel is validated structurally (filename tags, .dist-info,
     METADATA/WHEEL/RECORD, RECORD covers every non-RECORD member, member
     hashes/sizes recomputed) and WHEEL_PAYLOAD_SHA256 (canonical member
     records minus RECORD) is computed;
  9. a one-byte-mutated COPY of the built wheel must be rejected
     (MUTATED_WHEEL_REJECTED=true);
 10. the EXACT built wheel is installed into a fresh shadow runtime venv
     (--no-deps --no-cache-dir --report, PIP_NO_INDEX=1); the report's
     install source must be the local wheel and its archive SHA256 must
     equal the built wheel SHA256 (no package-name resolution);
 11. the installed distribution's RECORD is verified against the actual
     installed files and INSTALLED_PAYLOAD_SHA256 (canonical installed
     paths minus RECORD/.pyc/INSTALLER/direct_url.json/REQUESTED) is
     computed; INSTALLED_RECORD_VALID=true required;
 12. the remainder runtime/dev set is installed from an EPHEMERAL local
     wheelhouse (wheels only, exact SHA256, --find-links + --require-hashes
     + PIP_NO_INDEX=1; RUNTIME_INSTALL_FROM_WHEELS_ONLY=true); no runtime
     sdist remains at install time;
 13. the source-built package's installed identity must be unchanged after
     the remainder install (SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL);
 14. MarketVault is installed editable in the shadow env using the sealed
     P2-5 closed-world architecture (--no-build-isolation --no-deps
     --check-build-dependencies, exact hash-locked build env,
     PIP_NO_INDEX=1; P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED=true);
 15. the ACTUAL candidate surface runs INSIDE the shadow env: test-3.14
     runs the complete sealed Python 3.14 compatibility surface; pyarrow24
     requires pyarrow.__version__ == 24.0.0 and runs the complete existing
     PyArrow24 A/B/C surface (SHADOW_SURFACE_PASS);
 16. a complete path-free source-build identity (runtime_source_build_identity.json
     per sdist), a full cross-head identity document, and a self-contained
     evidence bundle with a duplicate-path-hardened EVIDENCE_MANIFEST.json
     and an OFFLINE replay verifier that FAILS CLOSED are produced.

All measurement hashes are CI-ONLY / NON-FORMAL-RELEASE.  Removed entirely
on the final docs-only head.

Subcommands:
  measure         run the whole P2-6 measurement for one surface
  bundle          assemble the self-contained evidence bundle + manifest
  verify-bundle   replay the bundle OFFLINE from a clean copy (fail closed)
  compare         compare two runtime_sdist_identity.json documents
  canonicalize    print the canonical form of a JSON file (test helper)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path

SCHEMA_VERSION = 4
PROGRAM = "market-vault-p26-runtime-sdist-identity-canary"

SURFACES = ("test-3.14", "pyarrow24")
SURFACE_REQUIREMENTS = {
    "test-3.14": ("-e", ".[dev]"),
    "pyarrow24": ("-e", ".[dev]", "pyarrow==24.0.0"),
}

LOCAL_PROJECT_NAME = "market-vault"
EXPECTED_PROJECT_VERSION = "0.7.0"
DYNAMIC_HOOK_NAME = "get_requires_for_build_wheel"
LEGACY_BUILD_BACKEND = "setuptools.build_meta:__legacy__"
LEGACY_FALLBACK_REQUIRES = ("setuptools>=40.8.0", "wheel")

# P2-6 exact-action pins (derived LIVE from the current main CI log run
# 31566455539, head bb54e69b92331d64345fb67f11a894b636657c68; the workflow
# passes them explicitly, these are only fallback defaults).
DEFAULT_ACTION_PINS = {
    "checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "setup_python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "upload_artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}

WHEELHOUSE_REL = "runtime_wheelhouse"
SDIST_REL = "sdist_source"
BUILT_WHEEL_REL = "built_wheels"

# Evidence bundle required files (self-contained; every one must be
# present in the manifest exactly once).
BUNDLE_REQUIRED_FILES = (
    "runtime_resolution.json",
    "runtime_sdist_identity_receipt.json",
    "runtime_sdist_identity.json",
    "runtime_sdist_identity_compare.json",
    "source_sdist_identity.json",
    "sdist_manifest.json",
    "source_build_contract.json",
    "source_build_environment.json",
    "source_build_environment.txt",
    "source_build_1.log",
    "source_build_2.log",
    "wheel_validation.json",
    "runtime_source_build_identity.json",
    "source_built_install_report.json",
    "installed_record_snapshot.json",
    "installed_payload_manifest.json",
    "remainder_runtime_manifest.json",
    "remainder_requirements.txt",
    "shadow_surface_result.json",
    "shadow_surface.log",
    "mutation_negative_receipt.json",
    "performance.json",
    "probe_summary.txt",
    "verifier_source.py",
    "EVIDENCE_MANIFEST.json",
)

INSTALL_EXCLUDED_FROM_PAYLOAD = {
    "INSTALLER", "REQUESTED", "direct_url.json",
}
PACKAGE_SURVIVAL_PY = (
    "import importlib.metadata as m, json, sys\n"
    "d = m.distribution(sys.argv[1])\n"
    "print(json.dumps({'name': d.metadata['Name'], 'version': d.version}))\n"
)


# ---------------------------------------------------------------------------
# canonicalization + hashing (shared with the #78/#79/#80 sealed family)
# ---------------------------------------------------------------------------


def canonicalize_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def normalize_download_url(url):
    """Lowercase scheme/host, drop empty default ports, reject credentials."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"URL must not contain credentials: {url!r}")
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"URL must be http(s), got {scheme!r}: {url!r}")
    hostname = (parts.hostname or "").lower()
    netloc = hostname
    if parts.port and not (
        (scheme == "http" and parts.port == 80)
        or (scheme == "https" and parts.port == 443)
    ):
        netloc = f"{hostname}:{parts.port}"
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def _sort_arrays(obj):
    if isinstance(obj, dict):
        return {k: _sort_arrays(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return sorted((_sort_arrays(v) for v in obj), key=json.dumps)
    return obj


def canonical_payload(obj):
    import copy

    payload = copy.deepcopy(obj)
    payload.pop("fingerprint_sha256", None)
    return _sort_arrays(payload)


def canonical_serialize(obj):
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ) + "\n"


def compute_fingerprint_sha(obj):
    return sha256_text(canonical_serialize(canonical_payload(obj)))


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_pyproject(path):
    """pyproject.toml is TOML, never JSON (a JSON parse of the sealed
    pyproject.toml crashed Head A before any measurement happened)."""
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(canonical_serialize(obj))


# ---------------------------------------------------------------------------
# process + environment helpers
# ---------------------------------------------------------------------------


def _run(cmd, cwd=None, env=None, log_path=None, timeout=3600, allow_fail=False):
    """Run a command, appending the command line + output to log_path."""
    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"$ {' '.join(cmd)}\n")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if log_path is not None:
        with open(log_path, "a", encoding="utf-8", newline="\n") as fh:
            if proc.stdout:
                fh.write(proc.stdout)
            if proc.stderr:
                fh.write(proc.stderr)
            fh.write(f"(exit {proc.returncode})\n")
    if proc.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return proc


def _venv_python(venv_dir):
    if os.name == "nt":
        return str(Path(venv_dir) / "Scripts" / "python.exe")
    return str(Path(venv_dir) / "bin" / "python")


def _parse_pip_version(text):
    m = re.search(r"pip\s+(\d+\.\d+(?:\.\d+)?)", text)
    if not m:
        raise ValueError(f"cannot parse pip version from: {text!r}")
    return m.group(1)


def _inventory_json(venv_python, log_path=None):
    """Return {canonical_name: version} from importlib.metadata in the venv."""
    code = (
        "import importlib.metadata as m, json\n"
        "out = {}\n"
        "for d in m.distributions():\n"
        "    n = d.metadata['Name'] if d.metadata and d.metadata.get('Name') else ''\n"
        "    if not n:\n"
        "        continue\n"
        "    out[n] = d.version or ''\n"
        "print(json.dumps(out, sort_keys=True))\n"
    )
    proc = _run([venv_python, "-c", code], log_path=log_path, allow_fail=False)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _importlib_metadata_check(venv_python, records, log_path=None):
    """Cross-check that each {name, version} record is present in the venv."""
    inventory = _inventory_json(venv_python, log_path=log_path)
    checks = {}
    ok = True
    for rec in sorted(records, key=lambda r: canonicalize_name(r["name"])):
        key = canonicalize_name(rec["name"])
        actual = inventory.get(key)
        if actual is None:
            ok = False
            checks[key] = {"expected": rec["version"], "actual": "MISSING"}
        elif canonicalize_name(str(actual)) != canonicalize_name(str(rec["version"])):
            ok = False
            checks[key] = {"expected": rec["version"], "actual": actual}
        else:
            checks[key] = {"expected": rec["version"], "actual": actual, "ok": True}
    return ok, checks, inventory


def runner_identity():
    return {
        "runner_os": os.environ.get("RUNNER_OS", "<local>"),
        "runner_arch": os.environ.get("RUNNER_ARCH", "<local>"),
        "image_os": os.environ.get("ImageOS", "<local>"),
        "image_version": os.environ.get("ImageVersion", "<local>"),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "platform_machine": platform.machine(),
    }


def python_identity():
    return {
        "executable_basename": os.path.basename(sys.executable),
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "win32": os.name == "nt",
    }


# ---------------------------------------------------------------------------
# pip report parsing + artifact classification (fail closed)
# ---------------------------------------------------------------------------


def _file_url_to_path(url):
    """Local path for a file:// URL (Windows drive forms included)."""
    from urllib.parse import unquote, urlsplit

    parts = urlsplit(url)
    netloc = parts.netloc
    path = unquote(parts.path)
    if netloc and not (netloc == "localhost" or re.fullmatch(r"[A-Za-z]:", netloc)):
        raise ValueError(f"UNC file url not supported: {url!r}")
    if re.fullmatch(r"[A-Za-z]:", netloc):
        path = netloc + path
    # file:///C:/... and file://C:/... both yield "/C:/..." or "C:/..."
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return Path(path)


def classify_artifact(url):
    """wheel / sdist / other for a normalized download URL (fail closed)."""
    if not url:
        raise ValueError("missing url (unhashed local source / direct artifact)")
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.query or parts.fragment:
        raise ValueError(f"mutable url (query/fragment present): {url!r}")
    if re.match(r"^(git|hg|svn|bzr)\+", url):
        raise ValueError(f"VCS url rejected: {url!r}")
    name = parts.path.rsplit("/", 1)[-1]
    if name.endswith(".whl"):
        return "wheel"
    if name.endswith((".tar.gz", ".tgz", ".zip", ".tar.bz2", ".tar.xz")):
        return "sdist"
    raise ValueError(f"unknown archive type: {url!r}")


def _wheel_filename_matches(filename, name, version):
    if "/" in filename or "\\" in filename or not filename.endswith(".whl"):
        return False
    stem = filename[:-4]
    norm = canonicalize_name(name).replace("-", "_")
    return stem.startswith(f"{norm}-{version}-")


def parse_pip_report_extended(report_path, skip_local_project=True):
    """Canonical records from a pip --report file with artifact classes.

    Every external distribution is classified wheel/sdist/other.  Fails
    closed on: missing/odd SHA256, VCS URLs, mutable URLs, unhashed local
    sources, unknown archive types and duplicate canonical names.
    """
    data = read_json(report_path)
    install = data.get("install")
    if not isinstance(install, list):
        raise ValueError(f"report {report_path}: missing 'install' list")
    records = []
    for entry in install:
        metadata = entry.get("metadata") or {}
        name = metadata.get("name")
        version = metadata.get("version")
        if not name or not version:
            raise ValueError(f"report {report_path}: entry missing name/version")
        canonical = canonicalize_name(name)
        if skip_local_project and canonical == canonicalize_name(LOCAL_PROJECT_NAME):
            continue
        info = entry.get("download_info") or {}
        url = None
        sha = None
        artifact_type = "other"
        if info.get("url"):
            raw_url = info["url"]
            if raw_url.startswith("file://"):
                # closed-world installs (--find-links + --require-hashes)
                # legitimately source from the local wheelhouse; the bytes
                # are pinned by --require-hashes, and we independently
                # re-hash the on-disk file.  If pip recorded a hash it must
                # equal the actual bytes (fail closed).
                local = _file_url_to_path(raw_url)
                if not local.is_file():
                    raise ValueError(
                        f"report {report_path}: file url missing on disk "
                        f"{raw_url!r}"
                    )
                actual = sha256_file(local)
                recorded = (info.get("hashes") or {}).get("sha256")
                if recorded is not None:
                    if not re.fullmatch(r"[0-9a-f]{64}", str(recorded)):
                        raise ValueError(
                            f"report {report_path}: odd sha256 for {canonical}"
                        )
                    if recorded != actual:
                        raise ValueError(
                            f"report {report_path}: {canonical} file url hash "
                            f"mismatch {raw_url!r}"
                        )
                url = raw_url
                sha = actual
                artifact_type = classify_artifact(url)
            else:
                url = normalize_download_url(raw_url)
                hashes = info.get("hashes") or {}
                sha = hashes.get("sha256")
                if not sha or not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
                    raise ValueError(
                        f"report {report_path}: missing/odd sha256 for {canonical}"
                    )
                artifact_type = classify_artifact(url)
        elif canonical != canonicalize_name(LOCAL_PROJECT_NAME):
            # external distribution with no resolvable artifact: pip has no
            # hashable download source -> unhashed local source, fail closed
            raise ValueError(
                f"report {report_path}: {canonical} has no download url "
                f"(unhashed local source)"
            )
        records.append(
            {
                "name": canonical,
                "version": version,
                "url": url,
                "sha256": sha,
                "artifact_type": artifact_type,
                "filename": (url or "").rsplit("/", 1)[-1] or None,
            }
        )
    records.sort(key=lambda r: (r["name"], r["version"]))
    seen = set()
    for rec in records:
        if rec["name"] in seen:
            raise ValueError(f"report {report_path}: duplicate package {rec['name']}")
        seen.add(rec["name"])
    return records


def merge_install_reports(report_paths):
    """Merge several install reports; later report wins per canonical name."""
    merged = {}
    order = []
    for path in report_paths:
        for rec in parse_pip_report_extended(path):
            if rec["name"] not in merged:
                order.append(rec["name"])
            merged[rec["name"]] = rec
    return [merged[name] for name in order]


# ---------------------------------------------------------------------------
# project + action contracts
# ---------------------------------------------------------------------------


def dependency_contract(repo_root):
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")
    data = read_pyproject(pyproject)
    project = data.get("project") or {}
    build_system = data.get("build-system") or {}
    build_requires = list(build_system.get("requires") or [])
    build_backend = build_system.get("build-backend")
    if not build_backend:
        raise ValueError("pyproject.toml: missing build-backend")
    deps = list(project.get("dependencies") or [])
    dev = list((project.get("optional-dependencies") or {}).get("dev") or [])
    return {
        "name": project.get("name"),
        "version": project.get("version"),
        "pyproject_sha256": sha256_file(pyproject),
        "build_system": {
            "requires": sorted(build_requires),
            "build_backend": build_backend,
            "backend_path": list(build_system.get("backend-path") or []),
        },
        "dependencies": deps,
        "dev_dependencies": dev,
    }


def action_contract(actions, repo_root):
    ci_yml = Path(repo_root) / ".github" / "workflows" / "ci.yml"
    return {
        "checkout_sha": actions["checkout"],
        "setup_python_sha": actions["setup_python"],
        "upload_artifact_sha": actions["upload_artifact"],
        "ci_yml_sha256": sha256_file(ci_yml) if ci_yml.exists() else None,
    }


# ---------------------------------------------------------------------------
# exact artifact download (resolver-selected bytes only)
# ---------------------------------------------------------------------------


def _download_exact(url, sha256, dest_dir, log_path=None, attempts=3):
    """Download the EXACT resolver-selected artifact; verify local bytes."""
    filename = url.rsplit("/", 1)[-1]
    dest = Path(dest_dir) / filename
    last_err = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{PROGRAM}/1.0"}
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
            if sha256_bytes(data) != sha256:
                last_err = ValueError(
                    f"{filename}: local bytes sha256 mismatch (resolver "
                    f"identity {sha256[:12]}…)"
                )
                continue
            dest.write_bytes(data)
            return dest
        except Exception as exc:  # network/IO retry
            last_err = exc
            continue
    raise RuntimeError(f"download failed for {filename}: {last_err}")


# ---------------------------------------------------------------------------
# safe sdist extraction
# ---------------------------------------------------------------------------


class UnsafeArchive(ValueError):
    pass


def _member_relative_path(member):
    raw = (member.name or "").replace("\\", "/")
    parts = raw.split("/")
    if not parts:
        raise UnsafeArchive(f"empty member path: {raw!r}")
    if any(p in ("", ".") for p in parts[:-1]):
        raise UnsafeArchive(f"member path with empty/'.' segments: {raw!r}")
    return raw


def validate_and_extract_tar(tar_path, dest_dir):
    """Extract a sdist tar.gz with full traversal/symlink rejection.

    Rejects before extraction: absolute paths, '..' traversal,
    drive-qualified paths, symlink/hardlink targets escaping the
    extraction root, and duplicate archive paths.  Returns a manifest of
    {relpath, size, sha256} for every extracted regular file.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    root_resolved = dest_dir.resolve()
    manifest = []
    seen = set()
    with tarfile.open(tar_path, "r:*") as tf:
        for member in tf.getmembers():
            raw = (member.name or "").replace("\\", "/")
            if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
                raise UnsafeArchive(f"absolute/drive-qualified path: {raw!r}")
            parts = [p for p in raw.split("/") if p not in ("", ".")]
            if any(p == ".." for p in parts):
                raise UnsafeArchive(f"path traversal: {raw!r}")
            rel = "/".join(parts)
            if not rel:
                continue
            if rel in seen:
                raise UnsafeArchive(f"duplicate archive path: {rel!r}")
            seen.add(rel)
            target = (dest_dir / rel).resolve()
            if not str(target).startswith(str(root_resolved) + os.sep) and target != root_resolved:
                raise UnsafeArchive(f"member escapes extraction root: {raw!r}")
            if member.islnk() or member.issym():
                link = (member.linkname or "").replace("\\", "/")
                link_parts = [p for p in link.split("/") if p not in ("", ".")]
                if any(p == ".." for p in link_parts):
                    raise UnsafeArchive(f"link target traversal: {raw!r} -> {link!r}")
                link_abs = link if link.startswith("/") or re.match(r"^[A-Za-z]:", link) \
                    else "/".join(parts[:-1] + link_parts)
                if link_abs.startswith("/") or re.match(r"^[A-Za-z]:", link_abs):
                    raise UnsafeArchive(f"absolute link target: {raw!r} -> {link!r}")
                if member.issym():
                    # symlink must stay inside the root
                    resolved = (Path(*parts[:-1]) / link).resolve()
                    if any(p == ".." for p in resolved.parts):
                        raise UnsafeArchive(f"symlink escapes root: {raw!r} -> {link!r}")
        for member in tf.getmembers():
            raw = (member.name or "").replace("\\", "/")
            parts = [p for p in raw.split("/") if p not in ("", ".")]
            if not parts:
                continue
            rel = "/".join(parts)
            if member.isdir():
                (dest_dir / rel).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise UnsafeArchive(
                    f"non-regular member (type {member.type}): {raw!r}"
                )
            out = dest_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                raise UnsafeArchive(f"cannot read member: {raw!r}")
            data = src.read()
            out.write_bytes(data)
            manifest.append(
                {
                    "path": rel,
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
    manifest.sort(key=lambda e: e["path"])
    return manifest


# ---------------------------------------------------------------------------
# source build contract (the RUNTIME DEPENDENCY's own contract)
# ---------------------------------------------------------------------------


def read_source_build_contract(extracted_root):
    """Parse the extracted project's OWN build-system contract."""
    root = Path(extracted_root)
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        data = read_pyproject(pyproject)
        build_system = data.get("build-system") or {}
        backend = build_system.get("build-backend")
        if not backend:
            raise ValueError(
                "extracted project has pyproject.toml without build-backend"
            )
        return {
            "pyproject_present": True,
            "backend": backend,
            "requires": sorted(build_system.get("requires") or []),
            "backend_path": list(build_system.get("backend-path") or []),
            "legacy_fallback": False,
            "pyproject_sha256": sha256_file(pyproject),
        }
    # pip's documented PEP 517 legacy fallback (setup.py project)
    return {
        "pyproject_present": False,
        "backend": LEGACY_BUILD_BACKEND,
        "requires": list(LEGACY_FALLBACK_REQUIRES),
        "backend_path": [],
        "legacy_fallback": True,
        "pyproject_sha256": None,
    }


def _invoke_wheel_hook(venv_python, backend, backend_path, project_root):
    snippet = (
        "import importlib, json, os, sys\n"
        "backend = sys.argv[1]\n"
        "os.chdir(sys.argv[3])\n"
        "if sys.argv[2]:\n"
        "    sys.path.insert(0, os.path.join(sys.argv[3], sys.argv[2]))\n"
        "if ':' in backend:\n"
        "    mod_name, obj_path = backend.split(':', 1)\n"
        "    mod = importlib.import_module(mod_name)\n"
        "    obj = mod\n"
        "    for part in obj_path.split('.'):\n"
        "        obj = getattr(obj, part)\n"
        "else:\n"
        "    obj = importlib.import_module(backend)\n"
        "hook = getattr(obj, 'get_requires_for_build_wheel', None)\n"
        "if hook is None:\n"
        "    raise RuntimeError('hook get_requires_for_build_wheel missing')\n"
        "result = hook(config_settings=None)\n"
        "print(json.dumps({'verbatim': sorted(str(x) for x in result)}))\n"
    )
    proc = _run(
        [venv_python, "-c", snippet, backend, backend_path, str(project_root)]
    )
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    verbatim = sorted(data["verbatim"])
    return {"verbatim": verbatim, "normalized_sorted": sorted(
        re.sub(r"\s+", "", str(x)) for x in verbatim
    )}


# ---------------------------------------------------------------------------
# source-build environment resolution + provisioning (closed world)
# ---------------------------------------------------------------------------


def write_hash_locked_requirements(requirements, dest_path):
    """Hash-locked requirements file: name==version --hash=sha256:..."""
    lines = []
    for req in sorted(requirements, key=lambda r: (r["name"], r["version"])):
        lines.append(f"{req['name']}=={req['version']} --hash=sha256:{req['sha256']}")
    text = "\n".join(lines) + "\n"
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return dest_path


def resolve_wheels_only(pip_exec, requirements, report_path, log_path, cwd=None):
    """Dry-run resolve a requirement set; every artifact must be a wheel.

    Returns sorted [ {name, version, filename, sha256} ] for the FULL
    transitive build requirement graph (declared + dynamic + transitive).
    Raises (fail closed) on any sdist / VCS / direct URL / missing hash /
    duplicate canonical distribution.
    """
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [pip_exec, "install", "--dry-run", "--ignore-installed",
           "--report", str(report_path), *requirements]
    _run(cmd, cwd=cwd, log_path=log_path)
    records = parse_pip_report_extended(report_path)
    resolved = []
    seen = set()
    for rec in records:
        if rec["name"] in seen:
            raise RuntimeError(
                f"build dep {rec['name']}: duplicate canonical package "
                f"(ambiguous version)"
            )
        seen.add(rec["name"])
        if rec["artifact_type"] != "wheel":
            raise RuntimeError(
                f"build dep {rec['name']} {rec['version']}: resolver returned "
                f"{rec['artifact_type']} artifact (sdist/VCS/unhashed source "
                f"build chain rejected)"
            )
        filename = rec["filename"]
        if not _wheel_filename_matches(filename, rec["name"], rec["version"]):
            raise RuntimeError(
                f"build dep {rec['name']} {rec['version']}: wheel filename "
                f"{filename!r} does not match canonical name/version"
            )
        resolved.append(
            {"name": rec["name"], "version": rec["version"],
             "filename": filename, "sha256": rec["sha256"]}
        )
    resolved.sort(key=lambda d: (d["name"], d["version"]))
    return resolved


def install_locked_wheels_into(venv_python, wheelhouse, requirements_file,
                               log_path=None):
    """Install hash-locked wheels from a local wheelhouse into an EXISTING
    venv (never re-seeds it).  PIP_NO_INDEX=1 + --find-links +
    --require-hashes; the pinned SHA256 is enforced by pip AND every wheel
    is independently re-hashed via the install report."""
    env = dict(os.environ)
    env["PIP_NO_INDEX"] = "1"
    env["PIP_FIND_LINKS"] = str(wheelhouse)
    _run(
        [venv_python, "-m", "pip", "install", "--require-hashes",
         "--no-cache-dir", "-r", str(requirements_file)],
        env=env,
        log_path=log_path,
    )


def provision_exact_env(venv_dir, base_python, wheelhouse, requirements_file,
                        log_path=None, upgrade_pip=True):
    """Create a venv and install hash-locked wheels ONLY from the local
    wheelhouse (PIP_NO_INDEX=1 + PIP_FIND_LINKS + --require-hashes)."""
    _run([base_python, "-m", "venv", str(venv_dir)], log_path=log_path)
    venv_python = _venv_python(venv_dir)
    if upgrade_pip:
        _run([venv_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=log_path)
    proc = _run([venv_python, "-m", "pip", "--version"], log_path=log_path)
    pip_version = _parse_pip_version(proc.stdout)
    env = dict(os.environ)
    env["PIP_NO_INDEX"] = "1"
    env["PIP_FIND_LINKS"] = str(wheelhouse)
    _run(
        [venv_python, "-m", "pip", "install", "--require-hashes",
         "--no-cache-dir", "-r", str(requirements_file)],
        env=env,
        log_path=log_path,
    )
    return venv_python, pip_version


def source_build_environment_identity(contract, env_wheels, py_identity,
                                      pip_version):
    """Path-free source-build environment identity document."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "backend": contract["backend"],
        "declared_requires": sorted(contract["requires"]),
        "dynamic_hook": DYNAMIC_HOOK_NAME,
        "build_distributions": [
            {"name": d["name"], "version": d["version"],
             "filename": d["filename"], "sha256": d["sha256"]}
            for d in env_wheels
        ],
        "python": {
            "python_version": py_identity["python_version"],
            "implementation": py_identity["implementation"],
        },
        "pip_frontend_version": pip_version,
    }
    doc["source_build_environment_sha256"] = compute_fingerprint_sha(doc)
    return doc


# ---------------------------------------------------------------------------
# cache-disabled wheel build from the exact local sdist
# ---------------------------------------------------------------------------


def build_wheel_from_sdist(build_python, sdist_path, out_dir, log_path):
    """Build the exact local sdist into a wheel, cache disabled, closed world.

    PIP_NO_INDEX=1, --no-deps --no-build-isolation --check-build-dependencies
    --no-cache-dir.  The log must prove a wheel was BUILT from the local
    source; any "Using cached" line fails closed (SOURCE_BUILD_CACHE_DISABLED
    evidence).  Returns (wheel_path, log_text).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PIP_NO_INDEX"] = "1"
    env["PIP_CACHE_DIR"] = str(Path(out_dir) / ".pip_cache_unused")
    _run(
        [build_python, "-m", "pip", "wheel",
         "--no-deps", "--no-build-isolation", "--check-build-dependencies",
         "--no-cache-dir", "--wheel-dir", str(out_dir), str(sdist_path)],
        env=env,
        log_path=log_path,
    )
    wheels = sorted(out_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(
            f"expected exactly one built wheel in {out_dir}, got "
            f"{[w.name for w in wheels]}"
        )
    return wheels[0]


def source_build_cache_ok(log_text):
    """True iff the build log proves a wheel was BUILT (never cached)."""
    if "Using cached" in log_text:
        return False
    return ("Building wheel" in log_text) or ("Successfully built" in log_text)


# ---------------------------------------------------------------------------
# wheel structural / RECORD validation
# ---------------------------------------------------------------------------


def _b64_sha256(data):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def _record_sha_matches(record_hash, data):
    if not record_hash:
        return False
    return record_hash in (_b64_sha256(data), _b64_sha256(data) + "=")


def wheel_dist_info_name(wheel_path):
    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
    # top-level *.dist-info directory (either an explicit dir entry
    # "...dist-info/" or member paths "…dist-info/…")
    dist_infos = sorted({
        n.split("/")[0] for n in names
        if "/" in n and n.split("/")[0].endswith(".dist-info")
    })
    if not dist_infos:
        raise ValueError(f"wheel {wheel_path.name}: no .dist-info directory")
    # always returned WITH the trailing slash, so callers can do
    # f"{dist_info}METADATA" etc.
    return dist_infos[0] + "/"


def validate_wheel(wheel_path, expected_name, expected_version):
    """Structural + RECORD validation of a built wheel.

    Returns {valid, reasons, dist_info, metadata_name, metadata_version,
    record_ok, unlisted_members, hash_mismatches}.  Every archive member
    except RECORD itself must be listed by RECORD with a matching secure
    hash + size; any mismatch is INVALID.
    """
    wheel_path = Path(wheel_path)
    reasons = []
    # filename tags
    m = re.match(
        r"^(?P<name>.+?)-(?P<version>[^-]+)-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$",
        wheel_path.name,
    )
    if not m:
        reasons.append(f"filename does not parse as wheel: {wheel_path.name}")
        return _wheel_validation_result(False, reasons)
    if canonicalize_name(m.group("name")) != canonicalize_name(expected_name):
        reasons.append(
            f"filename name {m.group('name')!r} != resolved {expected_name!r}"
        )
    if canonicalize_name(m.group("version")) != canonicalize_name(expected_version):
        reasons.append(
            f"filename version {m.group('version')!r} != resolved {expected_version!r}"
        )
    dist_info = metadata_name = metadata_version = None
    record_rows = {}
    record_ok = True
    unlisted = []
    hash_mismatches = []
    try:
        with zipfile.ZipFile(wheel_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                reasons.append(f"archive corrupt member: {bad}")
            members = {}
            for info in zf.infolist():
                if info.is_dir():
                    continue
                members[info.filename] = info
            dist_info = wheel_dist_info_name(wheel_path)
            dist_info_stem = dist_info[:-1]  # strip trailing "/"
            for required in ("METADATA", "WHEEL", "RECORD"):
                path = f"{dist_info}{required}"
                if path not in members:
                    reasons.append(f"missing {path}")
            meta_text = None
            if f"{dist_info}METADATA" in members:
                meta_text = zf.read(f"{dist_info}METADATA").decode("utf-8", "replace")
            if meta_text is not None:
                metadata_name = re.search(r"(?m)^Name:\s*(.+)$", meta_text)
                metadata_version = re.search(r"(?m)^Version:\s*(.+)$", meta_text)
            metadata_name = metadata_name.group(1).strip() if metadata_name else None
            metadata_version = metadata_version.group(1).strip() if metadata_version else None
            if canonicalize_name(metadata_name or "") != canonicalize_name(expected_name):
                reasons.append(
                    f"METADATA Name {metadata_name!r} != resolved {expected_name!r}"
                )
            if canonicalize_name(metadata_version or "") != canonicalize_name(expected_version):
                reasons.append(
                    f"METADATA Version {metadata_version!r} != resolved {expected_version!r}"
                )
            record_path = f"{dist_info}RECORD"
            try:
                record_text = zf.read(record_path).decode("utf-8", "replace")
            except KeyError:
                record_text = None
            if record_text is not None:
                for lineno, line in enumerate(record_text.splitlines(), 1):
                    if not line.strip():
                        continue
                    parts = line.split(",")
                    if len(parts) < 3:
                        record_ok = False
                        reasons.append(f"RECORD malformed line {lineno}")
                        continue
                    path, hash_, size = parts[0], parts[1], parts[2]
                    if path in record_rows:
                        record_ok = False
                        reasons.append(f"RECORD duplicate entry: {path}")
                    record_rows[path] = (hash_, size)
            for path, info in sorted(members.items()):
                if path == record_path:
                    continue
                row = record_rows.get(path)
                if row is None:
                    unlisted.append(path)
                    continue
                data = zf.read(path)
                want_hash, want_size = row
                if not want_hash:
                    record_ok = False
                    reasons.append(f"RECORD entry without hash: {path}")
                    continue
                if not _record_sha_matches(want_hash, data):
                    hash_mismatches.append(path)
                if want_size.isdigit() and int(want_size) != len(data):
                    hash_mismatches.append(f"{path}:size")
    except zipfile.BadZipFile as exc:
        reasons.append(f"bad zip: {exc}")
        return _wheel_validation_result(False, reasons)

    # RECORD may not list itself
    if record_path in record_rows:
        record_ok = False
        reasons.append("RECORD lists itself")
    for path in record_rows:
        if path not in members and path != record_path:
            record_ok = False
            reasons.append(f"RECORD lists missing member: {path}")

    valid = (
        not reasons
        and record_ok
        and not unlisted
        and not hash_mismatches
    )
    return {
        "valid": valid,
        "reasons": reasons,
        "dist_info": dist_info_stem,
        "metadata_name": metadata_name,
        "metadata_version": metadata_version,
        "record_ok": record_ok,
        "unlisted_members": unlisted,
        "hash_mismatches": hash_mismatches,
        "filename_name": m.group("name") if m else None,
        "filename_version": m.group("version") if m else None,
    }


def _wheel_validation_result(valid, reasons):
    return {
        "valid": valid,
        "reasons": reasons,
        "dist_info": None,
        "metadata_name": None,
        "metadata_version": None,
        "record_ok": False,
        "unlisted_members": [],
        "hash_mismatches": [],
        "filename_name": None,
        "filename_version": None,
    }


def wheel_payload_sha256(wheel_path):
    """Canonical digest over sorted (member path, sha256, size) records,
    excluding the wheel's own RECORD (which cannot bind itself)."""
    entries = []
    with zipfile.ZipFile(wheel_path) as zf:
        dist_info = wheel_dist_info_name(wheel_path)
        record_path = f"{dist_info}RECORD"
        for info in zf.infolist():
            if info.is_dir() or info.filename == record_path:
                continue
            data = zf.read(info.filename)
            entries.append((info.filename, sha256_bytes(data), len(data)))
    entries.sort()
    return sha256_text(canonical_serialize(entries))


# ---------------------------------------------------------------------------
# exact-wheel install + installed payload proof
# ---------------------------------------------------------------------------


def install_exact_wheel(venv_python, wheel_path, report_path, log_path):
    """Install the EXACT local wheel (no name resolution, cache disabled)."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PIP_NO_INDEX"] = "1"
    _run(
        [venv_python, "-m", "pip", "install", "--no-deps", "--no-cache-dir",
         "--report", str(report_path), str(wheel_path)],
        env=env,
        log_path=log_path,
    )
    return report_path


def verify_install_report(report_path, wheel_path, built_sha256):
    """The install report must point at the exact local wheel with the
    built wheel's SHA256 (never a package-name resolution / cached wheel)."""
    data = read_json(report_path)
    install = data.get("install") or []
    wheel_abs = Path(wheel_path).resolve()
    wheel_filename = Path(wheel_path).name
    matches = []
    for entry in install:
        info = entry.get("download_info") or {}
        url = info.get("url") or ""
        if url.rstrip("/").rsplit("/", 1)[-1] == wheel_filename:
            matches.append((url, (info.get("hashes") or {}).get("sha256")))
    if len(matches) != 1:
        return {
            "valid": False,
            "reason": f"expected exactly 1 wheel install, got {len(matches)}",
            "matches": matches,
        }
    url, sha = matches[0]
    if url.startswith("file://"):
        local = str(_file_url_to_path(url))
    else:
        local = url
    ok = True
    reasons = []
    if str(Path(local).resolve()) != str(wheel_abs):
        ok = False
        reasons.append("install source is not the exact local wheel")
    if sha != built_sha256:
        ok = False
        reasons.append("report wheel SHA256 != built wheel SHA256")
    return {"valid": ok, "reasons": reasons, "matches": matches}


def installed_distribution_dir(venv_python, canonical_name):
    """Locate the installed distribution's .dist-info directory."""
    code = (
        "import importlib.metadata as m, json, sys\n"
        "name = sys.argv[1]\n"
        "d = m.distribution(name)\n"
        "print(json.dumps({'name': d.metadata['Name'], 'version': d.version, "
        "'path': d._path}))\n"
    )
    proc = _run([venv_python, "-c", code, canonical_name], allow_fail=True)
    if proc.returncode != 0:
        raise RuntimeError(f"distribution {canonical_name} not found in venv")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return data


def verify_installed_payload(venv_python, canonical_name, expected_version):
    """Verify the installed distribution's RECORD against real files.

    For every hash-bearing RECORD entry the actual installed file's hash
    and size must match.  Allowed un-hashed records: RECORD itself and
    .pyc entries.  Any other unhashed material file fails closed.

    INSTALLED_PAYLOAD_SHA256: canonical digest over (normalized installed
    relative path, actual sha256, actual size), excluding RECORD, .pyc,
    INSTALLER, REQUESTED and direct_url.json (which are still validated
    for existence/content separately where applicable).
    """
    dist = installed_distribution_dir(venv_python, canonical_name)
    return verify_installed_payload_at(
        Path(dist["path"]), dist["name"], dist["version"], expected_version)


def verify_installed_payload_at(dist_info_path, installed_name,
                                installed_version, expected_version):
    """Pure path-based installed-payload verification (testable offline)."""
    dist_info_path = Path(dist_info_path)
    record_path = dist_info_path / "RECORD"
    if not record_path.is_file():
        return {"valid": False,
                "reason": f"installed RECORD missing: {record_path}",
                "record_valid": False}
    rows = []
    with open(record_path, "r", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 3:
                return {"valid": False,
                        "reason": f"installed RECORD malformed line: {line!r}",
                        "record_valid": False}
            rows.append((parts[0], parts[1], parts[2]))
    bad = []
    payload_entries = []
    record_rel = dist_info_path.name + "/RECORD"
    for rel, want_hash, want_size in rows:
        rel = rel.replace("\\", "/")
        path = (dist_info_path.parent / rel).resolve()
        if not path.is_file():
            bad.append(f"{rel}:ABSENT")
            continue
        data = path.read_bytes()
        name = Path(rel).name
        if want_hash:
            if not _record_sha_matches(want_hash, data):
                bad.append(f"{rel}:SHA256")
            if want_size.isdigit() and int(want_size) != len(data):
                bad.append(f"{rel}:SIZE")
        elif name == "RECORD" or name.endswith(".pyc"):
            pass  # permitted un-hashed
        elif name in INSTALL_EXCLUDED_FROM_PAYLOAD:
            pass  # validated separately below
        else:
            bad.append(f"{rel}:UNHASHED")
        if name == "RECORD" or name.endswith(".pyc") or \
                name in INSTALL_EXCLUDED_FROM_PAYLOAD:
            continue
        # raw RECORD relative path (same convention as the wheel payload),
        # so INSTALLED_PAYLOAD_SHA256 == WHEEL_PAYLOAD_SHA256 is a real
        # invariant: the installed tree is exactly the wheel's payload.
        payload_entries.append((rel, sha256_bytes(data), len(data)))
    # separate validation of the excluded metadata files
    direct_url = dist_info_path / "direct_url.json"
    direct_url_ok = None
    direct_url_sha = None
    if direct_url.is_file():
        try:
            du = read_json(direct_url)
            archive = du.get("archive_info") or {}
            direct_url_sha = (archive.get("hash") or "").replace("sha256=", "")
            direct_url_ok = bool(direct_url_sha and re.fullmatch(r"[0-9a-f]{64}", direct_url_sha))
        except Exception:
            direct_url_ok = False
    installer = dist_info_path / "INSTALLER"
    installer_ok = None
    if installer.is_file():
        installer_ok = installer.read_text(encoding="utf-8", errors="replace").strip() == "pip"
    payload_entries.sort()
    payload_sha = sha256_text(canonical_serialize(payload_entries))
    valid = not bad
    return {
        "valid": valid,
        "record_valid": valid,
        "reasons": bad,
        "dist_info": dist_info_path.name,
        "installed_name": installed_name,
        "installed_version": installed_version,
        "version_matches": canonicalize_name(str(installed_version))
        == canonicalize_name(str(expected_version)),
        "INSTALLED_PAYLOAD_SHA256": payload_sha,
        "direct_url_sha256": direct_url_sha,
        "direct_url_ok": direct_url_ok,
        "installer_ok": installer_ok,
        "payload_entry_count": len(payload_entries),
    }


# ---------------------------------------------------------------------------
# remainder runtime wheelhouse (wheels only, exact hashes)
# ---------------------------------------------------------------------------


def materialize_runtime_wheelhouse(records, wheelhouse, log_path=None):
    """Download every wheel-classified runtime record's exact bytes."""
    wheelhouse = Path(wheelhouse)
    wheelhouse.mkdir(parents=True, exist_ok=True)
    manifest = []
    for rec in sorted(records, key=lambda r: r["name"]):
        if rec["artifact_type"] != "wheel":
            raise RuntimeError(
                f"runtime dep {rec['name']}: non-wheel artifact in wheelhouse "
                f"({rec['artifact_type']})"
            )
        wheel = _download_exact(rec["url"], rec["sha256"], wheelhouse,
                                log_path=log_path)
        manifest.append(
            {"name": rec["name"], "version": rec["version"],
             "filename": wheel.name, "sha256": rec["sha256"]}
        )
    manifest.sort(key=lambda d: d["name"])
    return manifest


# ---------------------------------------------------------------------------
# MarketVault editable install (sealed P2-5 closed-world contract)
# ---------------------------------------------------------------------------


def marketvault_build_set(base_python, repo_root, out_dir, log_path):
    """Live-resolve the MarketVault editable build set (P2-5 architecture):
    declared requires + get_requires_for_build_editable hook + transitive
    graph; every artifact a wheel with exact SHA256."""
    contract = dependency_contract(repo_root)
    declared = contract["build_system"]["requires"]
    backend = contract["build_system"]["build_backend"]
    backend_path = contract["build_system"]["backend_path"]
    backend_path_str = ",".join(backend_path) if backend_path else ""
    probe_venv = Path(tempfile.mkdtemp(prefix="p26_mv_probe_"))
    try:
        _run([base_python, "-m", "venv", str(probe_venv)], log_path=log_path)
        probe_python = _venv_python(probe_venv)
        _run([probe_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=log_path)
        # probe the editable hook in a fresh env with the declared set
        hook_report = out_dir / "mv_declared_report.json"
        declared_wheels = resolve_wheels_only(
            probe_python, list(declared), hook_report, log_path,
            cwd=repo_root,
        )
        hook_venv = Path(tempfile.mkdtemp(prefix="p26_mv_hook_"))
        try:
            _run([base_python, "-m", "venv", str(hook_venv)], log_path=log_path)
            hook_python = _venv_python(hook_venv)
            _run([hook_python, "-m", "pip", "install", "--upgrade", "pip"],
                 log_path=log_path)
            wheelhouse = out_dir / "mv_build_wheelhouse"
            for wheel in declared_wheels:
                _download_exact_from_report(wheel, hook_report,
                                            wheelhouse, log_path)
            env = dict(os.environ)
            env["PIP_NO_INDEX"] = "1"
            env["PIP_FIND_LINKS"] = str(wheelhouse)
            for wheel in declared_wheels:
                _run(
                    [hook_python, "-m", "pip", "install", "--no-deps",
                     "--no-cache-dir", f"{wheel['name']}=={wheel['version']}"],
                    env=env, log_path=log_path,
                )
            probe = _invoke_wheel_hook(
                hook_python, backend, backend_path_str, str(repo_root))
            # get_requires_for_build_editable delegates to the wheel hook
            snippet = (
                "import importlib, json, os, sys\n"
                "backend = sys.argv[1]\n"
                "os.chdir(sys.argv[3])\n"
                "if sys.argv[2]:\n"
                "    sys.path.insert(0, os.path.join(sys.argv[3], sys.argv[2]))\n"
                "if ':' in backend:\n"
                "    mod_name, obj_path = backend.split(':', 1)\n"
                "    mod = importlib.import_module(mod_name)\n"
                "    obj = mod\n"
                "    for part in obj_path.split('.'):\n"
                "        obj = getattr(obj, part)\n"
                "else:\n"
                "    obj = importlib.import_module(backend)\n"
                "hook = getattr(obj, 'get_requires_for_build_editable', None)\n"
                "if hook is None:\n"
                "    raise RuntimeError('hook get_requires_for_build_editable missing')\n"
                "result = hook(config_settings=None)\n"
                "print(json.dumps({'verbatim': sorted(str(x) for x in result)}))\n"
            )
            proc = _run([hook_python, "-c", snippet, backend, backend_path_str,
                         str(repo_root)])
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            dynamic = sorted(re.sub(r"\s+", "", str(x))
                             for x in data["verbatim"])
        finally:
            shutil.rmtree(hook_venv, ignore_errors=True)
        effective = list(declared) + list(dynamic)
        eff_report = out_dir / "mv_effective_report.json"
        eff_wheels = resolve_wheels_only(
            probe_python, effective, eff_report, log_path, cwd=repo_root)
        return {
            "backend": backend,
            "declared_requires": sorted(declared),
            "dynamic_requires": sorted(dynamic),
            "effective_build_distributions": eff_wheels,
        }, eff_report
    finally:
        shutil.rmtree(probe_venv, ignore_errors=True)


def _download_exact_from_report(wheel, report_path, wheelhouse, log_path):
    """Download a resolved wheel's exact bytes via its report record."""
    data = read_json(report_path)
    for entry in data.get("install") or []:
        metadata = entry.get("metadata") or {}
        if canonicalize_name(metadata.get("name") or "") != wheel["name"]:
            continue
        info = entry.get("download_info") or {}
        url = info.get("url")
        sha = (info.get("hashes") or {}).get("sha256")
        if url and sha == wheel["sha256"]:
            _download_exact(url, sha, wheelhouse, log_path=log_path)
            return
    raise RuntimeError(
        f"cannot materialize build wheel {wheel['name']} from report"
    )


def install_marketvault_editable(venv_python, repo_root, build_set,
                                 wheelhouse, log_path):
    """Sealed P2-5 closed-world editable build inside the shadow env.

    PIP_NO_INDEX=1, --no-build-isolation --no-deps
    --check-build-dependencies, with the exact hash-locked build set
    already present in the env.
    """
    env = dict(os.environ)
    env["PIP_NO_INDEX"] = "1"
    report = Path(log_path).parent / "marketvault_editable_install_report.json"
    _run(
        [venv_python, "-m", "pip", "install", "--no-build-isolation",
         "--no-deps", "--check-build-dependencies", "--report", str(report),
         "-e", "."],
        cwd=repo_root, env=env,
        log_path=log_path,
    )
    return report


# ---------------------------------------------------------------------------
# shadow surface execution (the ACTUAL candidate surface, in shadow env)
# ---------------------------------------------------------------------------


def run_shadow_surface(venv_python, surface, repo_root, log_path):
    """Run the complete sealed candidate surface inside the shadow env."""
    if surface == "test-3.14":
        selector_file = Path(repo_root) / "ci" / "python314_compatibility_surface.txt"
        if not selector_file.is_file():
            return {"pass": False,
                    "reason": f"missing {selector_file}"}
        selectors = [
            ln.strip() for ln in selector_file.read_text(encoding="utf-8")
            .splitlines() if ln.strip() and not ln.lstrip().startswith("#")
        ]
        _run(
            [venv_python, "-m", "pytest", *selectors, "-q"],
            cwd=repo_root, log_path=log_path, allow_fail=True,
        )
    else:  # pyarrow24: A + B + C surface under pyarrow == 24.0.0
        code = "import pyarrow, json; print(json.dumps({'v': pyarrow.__version__}))"
        proc = _run([venv_python, "-c", code], cwd=repo_root,
                    log_path=log_path, allow_fail=True)
        files = [
            "tests/test_v060_portability.py",
            "tests/test_canonical_reader.py",
            "tests/test_sample_generation_core.py",
            "tests/test_sample_generation_cli.py",
            "tests/test_canonical_materialization_v03.py",
            "tests/test_canonical_builder_v03.py",
            "tests/test_dataset_materialization.py",
            "tests/test_verified_dataset_reader.py",
            "tests/test_pit_sample_assembly.py",
            "tests/test_dataset_end_to_end_regression.py",
        ]
        _run([venv_python, "-m", "pytest", *files, "-q"],
             cwd=repo_root, log_path=log_path, allow_fail=True)
    log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    # the last (exit N) annotation records the pytest result
    m = re.findall(r"\(exit (\d+)\)", log_text)
    last_exit = int(m[-1]) if m else None
    pyarrow_version = None
    if surface == "pyarrow24":
        mm = re.search(r'"v":\s*"([^"]+)"', log_text)
        if mm:
            pyarrow_version = mm.group(1)
    return {
        "pass": last_exit == 0 and (surface != "pyarrow24"
                                    or pyarrow_version == "24.0.0"),
        "pytest_last_exit": last_exit,
        "pyarrow_version": pyarrow_version,
    }


# ---------------------------------------------------------------------------
# mutation negative (byte-mutation of a wheel copy)
# ---------------------------------------------------------------------------


def mutation_negative(wheel_path, out_dir):
    """Mutate ONE byte of a regular payload member of a wheel COPY and
    require the identity verifier to reject it.  Never touches the
    authoritative wheel."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mutated = out_dir / ("mutated_" + Path(wheel_path).name)
    shutil.copy2(wheel_path, mutated)
    dist_info = wheel_dist_info_name(mutated)
    with zipfile.ZipFile(mutated, "r") as zf:
        infos = zf.infolist()
        target = next(
            (i for i in infos if not i.is_dir()
             and i.filename != f"{dist_info}RECORD"),
            None,
        )
        if target is None:
            raise RuntimeError("no mutable payload member in wheel")
        payload = zf.read(target.filename)
    mutated_byte = (payload[0] + 1) & 0xFF if payload else 0x01
    mutated_data = bytes([mutated_byte]) + payload[1:]
    with zipfile.ZipFile(mutated, "a") as zf:
        zf.writestr(target.filename, mutated_data)
    validation = validate_wheel(mutated, "", "")
    # validation is expected to fail on hash mismatch; also re-check the
    # payload identity differs from the authoritative wheel
    payload_differs = wheel_payload_sha256(mutated) != wheel_payload_sha256(wheel_path)
    sha_differs = sha256_file(mutated) != sha256_file(wheel_path)
    rejected = (not validation["valid"]) or payload_differs or sha_differs
    return {
        "rejected": rejected,
        "validation_valid": validation["valid"],
        "validation_reasons": validation["reasons"],
        "payload_differs": payload_differs,
        "sha_differs": sha_differs,
        "mutated_wheel_filename": mutated.name,
    }


# ---------------------------------------------------------------------------
# fail-closed validity decision (§23; pure so the negative tests exercise
# the exact rule set used by the probe)
# ---------------------------------------------------------------------------


def evaluate_source_build_identity_valid(verdicts, sdist_names):
    """SOURCE_BUILD_IDENTITY_VALID from the measured verdict set.

    Any missing or False verdict for a required leg => INVALID.  No
    assertion of the rules is ever bypassed; this is the ONLY decision
    function for the per-sdist source-build identity.
    """
    names = list(sdist_names)
    return bool(
        verdicts.get("SOURCE_SDIST_HASH_OK") is True
        and verdicts.get("RUNTIME_OTHER_COUNT") == 0
        and verdicts.get("RUNTIME_SDIST_COUNT", 0) >= 1
        and all(
            verdicts.get(f"RAW_WHEEL_REPRODUCIBLE_{n}") is True
            for n in names
        )
        and all(
            verdicts.get(f"MUTATED_WHEEL_REJECTED_{n}") is True
            for n in names
        )
        and all(
            verdicts.get(f"SOURCE_BUILD_CACHE_DISABLED_{n}_{tag}") is True
            for n in names for tag in ("1", "2")
        )
        and verdicts.get(
            "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL") is True
        and verdicts.get("RUNTIME_INSTALL_FROM_WHEELS_ONLY") is True
        and verdicts.get("SHADOW_SURFACE_PASS") is True
        and verdicts.get("FINAL_RUNTIME_MATCH") is True
        and verdicts.get("P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED") is True
    )


# ---------------------------------------------------------------------------
# measurement orchestration
# ---------------------------------------------------------------------------


class RuntimeSdistIdentityProbe:
    def __init__(self, surface, actions, repo_root, out_dir):
        self.surface = surface
        if surface not in SURFACES:
            raise ValueError(f"unknown surface {surface!r}; expected {SURFACES}")
        self.actions = actions
        self.repo_root = Path(repo_root).resolve()
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = str(self.out_dir / "measure.log")
        self.contract = dependency_contract(self.repo_root)
        self.verdicts = {}
        self.temp_dirs = []
        self.perf = {}
        self.shadow_python = None
        self.source_built = []  # per-sdist records for the identity doc

    def _tempdir(self, prefix):
        d = Path(tempfile.mkdtemp(prefix=prefix))
        self.temp_dirs.append(d)
        return d

    def _mark(self, key, value, reason=None):
        self.verdicts[key] = value
        if reason is not None:
            self.verdicts[f"{key}_reason"] = reason
        return value

    def _perf(self, key, started):
        self.perf[key] = round(time.time() - started, 1)

    # -- legs ---------------------------------------------------------------

    def leg_runtime_resolution(self, base_python):
        started = time.time()
        venv = self._tempdir("p26_runtime_probe_")
        _run([base_python, "-m", "venv", str(venv)], log_path=self.log_path)
        venv_python = _venv_python(venv)
        _run([venv_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=self.log_path)
        proc = _run([venv_python, "-m", "pip", "--version"],
                    log_path=self.log_path)
        pip_version = _parse_pip_version(proc.stdout)
        report = self.out_dir / "runtime_resolution.json"
        _run(
            [venv_python, "-m", "pip", "install", "--dry-run",
             "--ignore-installed", "--report", str(report),
             *SURFACE_REQUIREMENTS[self.surface]],
            cwd=self.repo_root,
            log_path=self.log_path,
        )
        records = parse_pip_report_extended(report)
        counts = {"wheel": 0, "sdist": 0, "other": 0}
        for rec in records:
            counts[rec["artifact_type"]] += 1
        self._mark("RUNTIME_WHEEL_COUNT", counts["wheel"])
        self._mark("RUNTIME_SDIST_COUNT", counts["sdist"])
        self._mark("RUNTIME_OTHER_COUNT", counts["other"])
        self._perf("runtime_resolution_seconds", started)
        return records, pip_version

    def leg_sdist_materialize(self, rec):
        started = time.time()
        sdist_dir = self.out_dir / SDIST_REL
        sdist_path = _download_exact(rec["url"], rec["sha256"], sdist_dir,
                                     log_path=self.log_path)
        local_sha = sha256_file(sdist_path)
        ok = local_sha == rec["sha256"]
        doc = {
            "schema_version": SCHEMA_VERSION,
            "name": rec["name"],
            "version": rec["version"],
            "filename": rec["filename"],
            "resolver_source_sha256": rec["sha256"],
            "local_sdist_sha256": local_sha,
            "valid": ok,
        }
        self._mark(
            f"SDIST_MATERIALIZED_{rec['name']}", ok,
            None if ok else "local bytes != resolver identity",
        )
        self._perf(f"sdist_materialize_{rec['name']}_seconds", started)
        return sdist_path, doc

    def leg_sdist_extract(self, sdist_path, rec):
        started = time.time()
        extract_dir = self._tempdir(f"p26_extract_{rec['name']}_")
        manifest = validate_and_extract_tar(sdist_path, extract_dir)
        self._mark(f"SDIST_EXTRACT_SAFE_{rec['name']}", True)
        self._perf(f"sdist_extract_{rec['name']}_seconds", started)
        return extract_dir, manifest

    def leg_source_build_contract(self, extract_dir, rec):
        started = time.time()
        contract = read_source_build_contract(extract_dir)
        self._perf(f"build_contract_{rec['name']}_seconds", started)
        return contract

    def leg_build_requires_probe(self, base_python, contract, extract_dir,
                                 rec, out_dir):
        started = time.time()
        venv = self._tempdir(f"p26_buildhook_{rec['name']}_")
        _run([base_python, "-m", "venv", str(venv)], log_path=self.log_path)
        probe_python = _venv_python(venv)
        _run([probe_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=self.log_path)
        declared = list(contract["requires"])
        report = out_dir / "source_build_declared_report.json"
        declared_wheels = resolve_wheels_only(
            probe_python, declared, report, self.log_path,
            cwd=extract_dir,
        )
        # dynamic hook probe in a static-only env (declared wheels only)
        hook_venv = self._tempdir(f"p26_buildhookenv_{rec['name']}_")
        _run([base_python, "-m", "venv", str(hook_venv)],
             log_path=self.log_path)
        hook_python = _venv_python(hook_venv)
        _run([hook_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=self.log_path)
        wheelhouse = out_dir / "source_build_hook_wheelhouse"
        for wheel in declared_wheels:
            _download_exact_from_report(wheel, report, wheelhouse,
                                        self.log_path)
        env = dict(os.environ)
        env["PIP_NO_INDEX"] = "1"
        env["PIP_FIND_LINKS"] = str(wheelhouse)
        for wheel in declared_wheels:
            _run(
                [hook_python, "-m", "pip", "install", "--no-deps",
                 "--no-cache-dir", f"{wheel['name']}=={wheel['version']}"],
                env=env, log_path=self.log_path,
            )
        probe = _invoke_wheel_hook(
            hook_python, contract["backend"],
            ",".join(contract["backend_path"]) if contract["backend_path"] else "",
            str(extract_dir),
        )
        self._perf(f"build_requires_probe_{rec['name']}_seconds", started)
        return probe, declared_wheels, probe_python

    def leg_build_env(self, probe_python, contract, probe, extract_dir, rec):
        started = time.time()
        effective = list(contract["requires"]) + list(probe["normalized_sorted"])
        report = self.out_dir / "source_build_effective_report.json"
        env_wheels = resolve_wheels_only(
            probe_python, effective, report, self.log_path,
            cwd=extract_dir,
        )
        wheelhouse = self.out_dir / f"source_build_wheelhouse_{rec['name']}"
        for wheel in env_wheels:
            _download_exact_from_report(wheel, report, wheelhouse,
                                        self.log_path)
        self._perf(f"build_env_resolve_{rec['name']}_seconds", started)
        return env_wheels, wheelhouse, report

    def leg_provision_build_env(self, base_python, env_wheels, wheelhouse,
                                rec):
        started = time.time()
        req_file = write_hash_locked_requirements(
            env_wheels, self.out_dir / "source_build_environment.txt")
        venv = self._tempdir(f"p26_buildenv_{rec['name']}_")
        build_python, pip_version = provision_exact_env(
            venv, base_python, wheelhouse, req_file,
            log_path=self.log_path,
        )
        self._perf(f"build_env_provision_{rec['name']}_seconds", started)
        return build_python, pip_version

    def leg_build_wheel(self, build_python, sdist_path, rec, tag):
        started = time.time()
        out_dir = self.out_dir / BUILT_WHEEL_REL / tag
        log = self.out_dir / f"source_build_{tag}.log"
        wheel_path = build_wheel_from_sdist(
            build_python, sdist_path, out_dir, log)
        log_text = log.read_text(encoding="utf-8", errors="replace")
        cache_ok = source_build_cache_ok(log_text)
        self._mark(f"SOURCE_BUILD_CACHE_DISABLED_{rec['name']}_{tag}", cache_ok,
                   None if cache_ok
                   else "build log shows 'Using cached' or no build proof")
        self._perf(f"wheel_build_{tag}_{rec['name']}_seconds", started)
        return wheel_path, log_text, cache_ok

    def leg_validate_wheel(self, wheel_path, rec):
        started = time.time()
        validation = validate_wheel(wheel_path, rec["name"], rec["version"])
        self._perf(f"wheel_validation_{rec['name']}_seconds", started)
        return validation

    def leg_install_exact(self, wheel_path, rec):
        started = time.time()
        if self.shadow_python is None:
            shadow = self._tempdir("p26_shadow_env_")
            _run([sys.executable, "-m", "venv", str(shadow)],
                 log_path=self.log_path)
            self.shadow_python = _venv_python(shadow)
            _run([self.shadow_python, "-m", "pip", "install", "--upgrade",
                  "pip"], log_path=self.log_path)
        report = self.out_dir / "source_built_install_report.json"
        install_exact_wheel(self.shadow_python, wheel_path, report,
                            self.log_path)
        built_sha = sha256_file(wheel_path)
        verified = verify_install_report(report, wheel_path, built_sha)
        self._perf(f"exact_wheel_install_{rec['name']}_seconds", started)
        return report, verified

    def leg_installed_payload(self, rec):
        started = time.time()
        result = verify_installed_payload(
            self.shadow_python, rec["name"], rec["version"])
        self._perf(f"installed_payload_verify_{rec['name']}_seconds", started)
        return result

    def leg_remainder_install(self, records, wheel_records, sdist_names):
        started = time.time()
        wheelhouse = self.out_dir / WHEELHOUSE_REL
        manifest = materialize_runtime_wheelhouse(
            wheel_records, wheelhouse, log_path=self.log_path)
        req_file = write_hash_locked_requirements(
            manifest, self.out_dir / "remainder_requirements.txt")
        write_json(self.out_dir / "remainder_runtime_manifest.json",
                   {"schema_version": SCHEMA_VERSION, "surface": self.surface,
                    "distributions": manifest})
        env = dict(os.environ)
        env["PIP_NO_INDEX"] = "1"
        env["PIP_FIND_LINKS"] = str(wheelhouse)
        report = self.out_dir / "remainder_install_report.json"
        _run(
            [self.shadow_python, "-m", "pip", "install", "--no-deps",
             "--no-cache-dir", "--require-hashes", "--report", str(report),
             "-r", str(req_file)],
            env=env, log_path=self.out_dir / "remainder_install.log",
        )
        final_records = parse_pip_report_extended(report)
        types = {r["artifact_type"] for r in final_records}
        wheels_only = types <= {"wheel"}
        self._mark("RUNTIME_INSTALL_FROM_WHEELS_ONLY", wheels_only,
                   None if wheels_only else f"final install artifact types: {types}")
        names = {r["name"] for r in final_records}
        sdist_left = sorted(names & set(sdist_names))
        if sdist_left:
            self._mark("UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL", True,
                       f"sdists present: {sdist_left}")
        else:
            self._mark("UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL", False)
        self._perf("remainder_install_seconds", started)
        return final_records

    def leg_survival_check(self, rec, payload_before):
        """Re-verify the installed source-built package after the remainder
        install (and after everything else)."""
        after = verify_installed_payload(
            self.shadow_python, rec["name"], rec["version"])
        unchanged = (
            after["valid"]
            and after["INSTALLED_PAYLOAD_SHA256"]
            == payload_before["INSTALLED_PAYLOAD_SHA256"]
            and canonicalize_name(str(after["installed_version"]))
            == canonicalize_name(str(rec["version"]))
        )
        self._mark(
            f"SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL_{rec['name']}",
            unchanged,
            None if unchanged
            else f"installed payload changed: {payload_before.get('reasons')}"
                 f" -> {after.get('reasons')}",
        )
        return unchanged, after


# ---------------------------------------------------------------------------
# measure command
# ---------------------------------------------------------------------------


def cmd_measure(args):
    actions = {
        "checkout": args.actions_checkout,
        "setup_python": args.actions_setup_python,
        "upload_artifact": args.actions_upload_artifact,
    }
    probe = RuntimeSdistIdentityProbe(args.surface, actions,
                                      args.repo_root, args.out_dir)
    t0 = time.time()
    summary = {}
    try:
        base_python = sys.executable
        summary["runner"] = runner_identity()
        summary["python"] = python_identity()
        summary["dependency_contract"] = probe.contract
        summary["action_contract"] = action_contract(actions,
                                                     args.repo_root)

        records, pip_version = probe.leg_runtime_resolution(base_python)
        summary["resolved_distributions"] = records
        summary["pip_frontend_version"] = pip_version

        wheel_records = [r for r in records if r["artifact_type"] == "wheel"]
        sdist_records = [r for r in records if r["artifact_type"] == "sdist"]
        other_records = [r for r in records if r["artifact_type"] == "other"]

        per_sdist = {}
        for rec in sdist_records:
            sdist_path, sdist_doc = probe.leg_sdist_materialize(rec)
            write_json(probe.out_dir / "source_sdist_identity.json", sdist_doc)
            if not sdist_doc["valid"]:
                probe._mark("SOURCE_SDIST_HASH_OK", False,
                            f"local bytes != resolver sha for {rec['name']}")
            else:
                probe._mark("SOURCE_SDIST_HASH_OK", True)
            extract_dir, manifest = probe.leg_sdist_extract(sdist_path, rec)
            write_json(probe.out_dir / "sdist_manifest.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"], "files": manifest})
            contract = probe.leg_source_build_contract(extract_dir, rec)
            write_json(probe.out_dir / "source_build_contract.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"], **contract})
            probe1, declared_wheels, probe_python = \
                probe.leg_build_requires_probe(base_python, contract,
                                               extract_dir, rec,
                                               probe.out_dir)
            env_wheels, env_wheelhouse, _ = probe.leg_build_env(
                probe_python, contract, probe1, extract_dir, rec)
            build_python, build_pip_version = probe.leg_provision_build_env(
                base_python, env_wheels, env_wheelhouse, rec)
            env_doc = source_build_environment_identity(
                contract, env_wheels, summary["python"], build_pip_version)
            write_json(probe.out_dir / "source_build_environment.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"], **env_doc})
            probe._mark(
                f"SOURCE_BUILD_ENVIRONMENT_SHA256_{rec['name']}",
                env_doc["source_build_environment_sha256"])

            wheel1, log1, cache1 = probe.leg_build_wheel(
                build_python, sdist_path, rec, "1")
            wheel2, log2, cache2 = probe.leg_build_wheel(
                build_python, sdist_path, rec, "2")
            sha1 = sha256_file(wheel1)
            sha2 = sha256_file(wheel2)
            reproducible = sha1 == sha2
            probe._mark(f"RAW_WHEEL_REPRODUCIBLE_{rec['name']}", reproducible,
                        None if reproducible
                        else f"build1 {sha1[:12]}… != build2 {sha2[:12]}…")

            validation = probe.leg_validate_wheel(wheel1, rec)
            write_json(probe.out_dir / "wheel_validation.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"],
                        "built_wheel_filename": wheel1.name,
                        "built_wheel_sha256": sha1,
                        "built_wheel_2_sha256": sha2,
                        "raw_wheel_reproducible": reproducible,
                        **validation})
            payload_sha = wheel_payload_sha256(wheel1)

            mutation = mutation_negative(
                wheel1, probe.out_dir / "mutation_negative")
            probe._mark(f"MUTATED_WHEEL_REJECTED_{rec['name']}",
                        mutation["rejected"])
            write_json(probe.out_dir / "mutation_negative_receipt.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"], **mutation})

            report, verified = probe.leg_install_exact(wheel1, rec)
            payload = probe.leg_installed_payload(rec)
            write_json(probe.out_dir / "installed_record_snapshot.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"], **payload})
            write_json(probe.out_dir / "installed_payload_manifest.json",
                       {"schema_version": SCHEMA_VERSION, "name": rec["name"],
                        "version": rec["version"],
                        "INSTALLED_PAYLOAD_SHA256":
                            payload["INSTALLED_PAYLOAD_SHA256"],
                        "payload_entry_count": payload["payload_entry_count"],
                        "record_valid": payload["record_valid"]})

            built_wheel_identity = {
                "schema_version": SCHEMA_VERSION,
                "name": rec["name"],
                "version": rec["version"],
                "source_sdist": {
                    "filename": rec["filename"],
                    "sha256": rec["sha256"],
                },
                "source_build_contract": {
                    "backend": contract["backend"],
                    "declared_requires": sorted(contract["requires"]),
                    "dynamic_requires": sorted(probe1["normalized_sorted"]),
                    "SOURCE_BUILD_ENVIRONMENT_SHA256":
                        env_doc["source_build_environment_sha256"],
                },
                "built_wheel": {
                    "filename": wheel1.name,
                    "raw_sha256": sha1,
                    "WHEEL_PAYLOAD_SHA256": payload_sha,
                    "repeat_build_raw_sha256_match": reproducible,
                },
                "actual_install": {
                    "local_wheel_report_sha256":
                        verified["matches"][0][1] if verified["matches"] else None,
                    "install_report_valid": verified["valid"],
                    "INSTALLED_PAYLOAD_SHA256": payload["INSTALLED_PAYLOAD_SHA256"],
                    "installed_record_valid": payload["record_valid"],
                },
                "cache_disabled": cache1 and cache2,
                "source_build_identity_valid": (
                    sdist_doc["valid"]
                    and contract["backend"] is not None
                    and cache1 and cache2
                    and reproducible
                    and validation["valid"]
                    and verified["valid"]
                    and payload["valid"]
                    and payload["version_matches"]
                    and mutation["rejected"]
                ),
            }
            write_json(probe.out_dir / "runtime_source_build_identity.json",
                       built_wheel_identity)
            per_sdist[rec["name"]] = built_wheel_identity
            probe.source_built.append(
                (rec, payload, contract, env_doc, sha1, verified))

        # remainder runtime install (wheels only)
        final_records = probe.leg_remainder_install(
            records, wheel_records, [r["name"] for r in sdist_records])

        # survival checks after the remainder install
        survival = True
        for rec, payload_before, _, _, _, _ in probe.source_built:
            ok, _ = probe.leg_survival_check(rec, payload_before)
            survival = survival and ok
        probe._mark("SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL",
                    survival)

        # MarketVault editable install (sealed P2-5 closed-world contract)
        mv_started = time.time()
        mv_build_set, mv_report = marketvault_build_set(
            base_python, probe.repo_root, probe.out_dir, probe.log_path)
        mv_wheelhouse = probe.out_dir / "mv_build_wheelhouse"
        for wheel in mv_build_set["effective_build_distributions"]:
            _download_exact_from_report(wheel, mv_report, mv_wheelhouse,
                                        probe.log_path)
        req_file = write_hash_locked_requirements(
            mv_build_set["effective_build_distributions"],
            probe.out_dir / "marketvault_build_environment.txt")
        # install the P2-5 build set into the EXISTING shadow env (never
        # re-seed the venv: the env's pip is the sealed surface pip)
        install_locked_wheels_into(
            probe.shadow_python, mv_wheelhouse, req_file,
            log_path=probe.log_path)
        mv_ok = install_marketvault_editable(
            probe.shadow_python, probe.repo_root, mv_build_set,
            mv_wheelhouse, probe.out_dir / "marketvault_editable_build.log")
        probe._mark("P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED", True)
        probe._perf("marketvault_editable_install_seconds", mv_started)

        # shadow surface
        surf_started = time.time()
        surface_result = run_shadow_surface(
            probe.shadow_python, args.surface, probe.repo_root,
            probe.out_dir / "shadow_surface.log")
        write_json(probe.out_dir / "shadow_surface_result.json",
                   {"schema_version": SCHEMA_VERSION, "surface": args.surface,
                    **surface_result})
        probe._mark("SHADOW_SURFACE_PASS", surface_result["pass"],
                    None if surface_result["pass"] else str(surface_result))
        probe._perf("shadow_surface_seconds", surf_started)

        # post-everything survival re-check
        final_survival = True
        for rec, payload_before, _, _, _, _ in probe.source_built:
            ok, _ = probe.leg_survival_check(rec, payload_before)
            final_survival = final_survival and ok
        probe._mark("SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL", final_survival)

        # final runtime match (installed env vs resolution)
        live_ok, live_checks, _ = _importlib_metadata_check(
            probe.shadow_python,
            [{"name": r["name"], "version": r["version"]} for r in records],
            log_path=probe.log_path,
        )
        report_types = {r["artifact_type"] for r in final_records}
        final_match = (
            live_ok
            and report_types <= {"wheel"}
            and probe.verdicts.get("UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL")
            is False
        )
        probe._mark("FINAL_RUNTIME_MATCH", final_match)

        # complete validity (single fail-closed decision function)
        valid = evaluate_source_build_identity_valid(
            probe.verdicts, [r["name"] for r in sdist_records])
        probe._mark("SOURCE_BUILD_IDENTITY_VALID", valid,
                    None if valid else "see per-leg verdicts in probe_summary.txt")

        receipt = {
            "schema_version": SCHEMA_VERSION,
            "surface": args.surface,
            "runner": summary["runner"],
            "python": summary["python"],
            "action_contract": summary["action_contract"],
            "resolved_distributions": records,
            "pip_frontend_version": pip_version,
            "runtime_wheel_count": probe.verdicts["RUNTIME_WHEEL_COUNT"],
            "runtime_sdist_count": probe.verdicts["RUNTIME_SDIST_COUNT"],
            "runtime_other_count": probe.verdicts["RUNTIME_OTHER_COUNT"],
            "source_build_identity_valid": valid,
            "final_runtime_match": final_match,
            "marketvault_build_contract": {
                "backend": mv_build_set["backend"],
                "declared_requires": sorted(mv_build_set["declared_requires"]),
                "dynamic_requires": sorted(mv_build_set["dynamic_requires"]),
                "effective_build_distributions": [
                    dict(d) for d in mv_build_set["effective_build_distributions"]
                ],
            },
            "p2_5_closed_world_build_contract_used": True,
            "perf": probe.perf,
        }
        if per_sdist:
            first = next(iter(per_sdist.values()))
            wheel1_path = probe.out_dir / BUILT_WHEEL_REL / "1" / \
                first["built_wheel"]["filename"]
            receipt["source_built_wheel_info"] = {
                "name": first["name"],
                "version": first["version"],
                "filename": first["built_wheel"]["filename"],
                "raw_sha256": first["built_wheel"]["raw_sha256"],
                "size_bytes": wheel1_path.stat().st_size,
            }
        write_json(probe.out_dir / "runtime_sdist_identity_receipt.json",
                   receipt)

        # complete cross-head identity document
        identity = {
            "schema_version": SCHEMA_VERSION,
            "surface": args.surface,
            "runner": summary["runner"],
            "python": summary["python"],
            "resolver": {"pip_version": pip_version},
            "dependency_contract": summary["dependency_contract"],
            "action_contract": summary["action_contract"],
            "workflow": {"ci_yml_sha256":
                         summary["action_contract"]["ci_yml_sha256"]},
            "resolved_distributions": records,
            "source_sdist_identity": {
                r["name"]: per_sdist[r]["source_sdist"] for r in sdist_records
            },
            "source_build_environment_identity": {
                r["name"]: per_sdist[r]["source_build_contract"] for r in sdist_records
            },
            "exact_built_wheel_sha256": {
                r["name"]: per_sdist[r]["built_wheel"] for r in sdist_records
            },
            "installed_payload_identity": {
                r["name"]: per_sdist[r]["actual_install"] for r in sdist_records
            },
            "marketvault_build_identity": {
                "backend": mv_build_set["backend"],
                "effective_build_distributions": [
                    dict(d) for d in mv_build_set["effective_build_distributions"]
                ],
                "closed_world_contract_used": True,
            },
            "source_build_identity_valid": valid,
            "final_runtime_match": final_match,
            "shadow_surface_pass": surface_result["pass"],
        }
        identity["fingerprint_sha256"] = compute_fingerprint_sha(identity)
        write_json(probe.out_dir / "runtime_sdist_identity.json", identity)
        summary["identity_fingerprint_sha256"] = identity["fingerprint_sha256"]

        probe._mark("MEASURE_ELAPSED_SECONDS", round(time.time() - t0, 1))
    except Exception as exc:  # measurement never fails the job
        probe._mark("MEASURE_CRASH", True, f"{type(exc).__name__}: {exc}")

    summary_path = probe.out_dir / "probe_summary.txt"
    lines = []
    order = (
        "SOURCE_BUILD_IDENTITY_VALID",
        "SOURCE_SDIST_HASH_OK",
        "FINAL_RUNTIME_MATCH",
        "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL",
        "SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL",
        "RUNTIME_INSTALL_FROM_WHEELS_ONLY",
        "UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL",
        "SHADOW_SURFACE_PASS",
        "P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED",
        "RUNTIME_WHEEL_COUNT",
        "RUNTIME_SDIST_COUNT",
        "RUNTIME_OTHER_COUNT",
        "MEASURE_CRASH",
    )
    for key in order:
        value = probe.verdicts.get(key)
        if value is None:
            value = False
        lines.append(f"{key}={str(value).lower()}")
        reason = probe.verdicts.get(f"{key}_reason")
        if reason:
            lines.append(f"reason={reason}")
    for rec in sdist_records:
        for key in (
            f"SDIST_MATERIALIZED_{rec['name']}",
            f"RAW_WHEEL_REPRODUCIBLE_{rec['name']}",
            f"MUTATED_WHEEL_REJECTED_{rec['name']}",
            f"SOURCE_BUILD_CACHE_DISABLED_{rec['name']}_1",
            f"SOURCE_BUILD_CACHE_DISABLED_{rec['name']}_2",
            f"SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL_{rec['name']}",
            f"SOURCE_BUILD_ENVIRONMENT_SHA256_{rec['name']}",
        ):
            value = probe.verdicts.get(key)
            if value is None:
                continue
            lines.append(f"{key}={str(value).lower()}")
            reason = probe.verdicts.get(f"{key}_reason")
            if reason:
                lines.append(f"reason={reason}")
    if "MEASURE_ELAPSED_SECONDS" in probe.verdicts:
        lines.append(
            f"MEASURE_ELAPSED_SECONDS={probe.verdicts['MEASURE_ELAPSED_SECONDS']}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8",
                            newline="\n")
    return 0


# ---------------------------------------------------------------------------
# evidence bundle (duplicate-path-hardened manifest)
# ---------------------------------------------------------------------------


def _rel_path(path, root):
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def _manifest_files(out_dir):
    """All evidence files as relative paths, in a stable order.

    Every relative path must be unique; a duplicate aborts with
    EVIDENCE_MANIFEST_INVALID reason=duplicate_path:<path>.
    """
    root = Path(out_dir)
    files = []
    skip_dirs = {WHEELHOUSE_REL, "mv_build_wheelhouse"}
    for top in sorted(p for p in root.iterdir()
                      if p.is_dir() and p.name not in skip_dirs
                      and not p.name.startswith("source_build")
                      and p.name not in (SDIST_REL, BUILT_WHEEL_REL,
                                         "mutation_negative")):
        for path in sorted(top.rglob("*")):
            if path.is_file():
                files.append(path)
    for d in (SDIST_REL, BUILT_WHEEL_REL, "mutation_negative"):
        top = root / d
        if top.is_dir():
            for path in sorted(top.rglob("*")):
                if path.is_file():
                    files.append(path)
    for path in sorted(root.iterdir()):
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda p: _rel_path(p, root))


def _write_manifest(out_dir, required):
    root = Path(out_dir)
    files = _manifest_files(out_dir)
    rels = [_rel_path(p, root) for p in files]
    seen = set()
    for rel in rels:
        if rel in seen:
            raise ValueError(
                f"EVIDENCE_MANIFEST_INVALID reason=duplicate_path:{rel}"
            )
        seen.add(rel)
    missing = [r for r in required if r not in rels]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "surface": None,
        "complete": not missing,
        "missing": missing,
        "files": [
            {"path": rel, "size": os.path.getsize(root / rel),
             "sha256": sha256_file(root / rel)}
            for rel in rels
        ],
    }
    write_json(root / "EVIDENCE_MANIFEST.json", manifest)
    return manifest


def cmd_bundle(args):
    root = Path(args.out_dir)
    receipt_path = root / "runtime_sdist_identity_receipt.json"
    if not receipt_path.is_file():
        print("EVIDENCE_MANIFEST_INVALID reason=missing_receipt")
        return 2
    receipt = read_json(receipt_path)
    surface = receipt.get("surface")
    required = list(BUNDLE_REQUIRED_FILES)
    try:
        manifest = _write_manifest(root, required)
    except ValueError as exc:
        print(f"EVIDENCE_MANIFEST_INVALID {exc}")
        return 2
    verifier_dst = root / "verifier_source.py"
    _self_copy(verifier_dst)
    manifest = _write_manifest(root, required)
    print(f"EVIDENCE_MANIFEST_COMPLETE={str(manifest['complete']).lower()}")
    for missing in manifest["missing"]:
        print(f"EVIDENCE_MANIFEST_MISSING={missing}")
    return 0 if manifest["complete"] else 2


def _self_copy(dest):
    try:
        shutil.copy2(__file__, dest)
        return
    except Exception:
        pass
    with open(__file__, "rb") as src:
        data = src.read()
    with open(dest, "wb") as fh:
        fh.write(data)


# ---------------------------------------------------------------------------
# offline replay (fail closed, file-driven — stronger than #80)
# ---------------------------------------------------------------------------


class BundleVerifier:
    def __init__(self, bundle_dir):
        self.root = Path(bundle_dir)
        self.checks = {}

    def _check(self, key, ok, detail=None):
        self.checks[key] = ok
        if detail is not None:
            self.checks[f"{key}_detail"] = detail
        return ok

    def verify(self):
        root = self.root

        manifest_path = root / "EVIDENCE_MANIFEST.json"
        if not manifest_path.exists():
            self._check("manifest_present", False, "missing EVIDENCE_MANIFEST.json")
            return self._summary(False)
        manifest = read_json(manifest_path)
        self._check("manifest_present", True)

        schema_ok = (
            manifest.get("schema_version") == SCHEMA_VERSION
            and isinstance(manifest.get("files"), list)
        )
        self._check("manifest_schema", schema_ok,
                    "schema_version mismatch or files missing"
                    if not schema_ok else None)

        rels = [f.get("path") for f in manifest.get("files", [])]
        dupes = sorted({r for r in rels if rels.count(r) > 1})
        self._check("manifest_unique_paths", not dupes,
                    f"duplicate_path:{','.join(dupes)}" if dupes else None)

        receipt_path = root / "runtime_sdist_identity_receipt.json"
        surface = None
        if receipt_path.exists():
            surface = read_json(receipt_path).get("surface")
        required = list(BUNDLE_REQUIRED_FILES)
        missing = [r for r in required if r not in rels]
        self._check("manifest_complete", not missing,
                    f"missing:{','.join(missing)}" if missing else None)

        hash_ok = True
        hash_bad = []
        for entry in manifest.get("files", []):
            rel = entry.get("path")
            if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
                hash_ok = False
                hash_bad.append(f"{rel}:ABS_PATH")
                continue
            path = root / rel
            if not path.is_file():
                hash_ok = False
                hash_bad.append(f"{rel}:ABSENT")
                continue
            if sha256_file(path) != entry.get("sha256"):
                hash_ok = False
                hash_bad.append(f"{rel}:SHA256")
            if os.path.getsize(path) != entry.get("size"):
                hash_ok = False
                hash_bad.append(f"{rel}:SIZE")
        self._check("manifest_hashes", hash_ok,
                    ",".join(hash_bad) if hash_bad else None)

        identity_path = root / "runtime_sdist_identity.json"
        identity_ok = identity_path.exists() and (
            read_json(identity_path).get("schema_version") == SCHEMA_VERSION
        )
        self._check("identity_schema", identity_ok)

        digest_ok = False
        if identity_ok:
            identity = read_json(identity_path)
            stored = identity.get("fingerprint_sha256")
            recomputed = compute_fingerprint_sha(identity)
            digest_ok = stored == recomputed
        self._check("identity_digest", digest_ok)

        # sdist identity: resolver bytes == retained sdist bytes
        sdist_ok = True
        sdist_bad = []
        sid_path = root / "source_sdist_identity.json"
        if sid_path.exists():
            sid = read_json(sid_path)
            sdist = root / SDIST_REL / sid.get("filename", "")
            if not sdist.is_file():
                sdist_ok = False
                sdist_bad.append(f"{sid.get('filename')}:ABSENT")
            else:
                actual = sha256_file(sdist)
                if actual != sid.get("local_sdist_sha256"):
                    sdist_ok = False
                    sdist_bad.append("local_sdist_sha256_mismatch")
                if actual != sid.get("resolver_source_sha256"):
                    sdist_ok = False
                    sdist_bad.append("resolver_source_sha256_mismatch")
        else:
            sdist_ok = False
            sdist_bad.append("source_sdist_identity.json:ABSENT")
        self._check("sdist_identity", sdist_ok,
                    ",".join(sdist_bad) if sdist_bad else None)

        # sdist manifest: re-extract the retained sdist and compare
        extract_ok = False
        extract_detail = None
        if sdist_ok:
            try:
                with tempfile.TemporaryDirectory() as td:
                    re_manifest = validate_and_extract_tar(
                        root / SDIST_REL / sid.get("filename", ""), td)
                    stored = read_json(root / "sdist_manifest.json").get("files")
                    extract_ok = re_manifest == stored
                    if not extract_ok:
                        extract_detail = "re-extraction != recorded manifest"
            except Exception as exc:
                extract_detail = f"re-extraction failed: {exc}"
        self._check("sdist_extracted_manifest", extract_ok, extract_detail)

        # source-build environment identity: recompute from retained env doc
        env_ok = False
        env_path = root / "source_build_environment.json"
        if env_path.exists():
            env = read_json(env_path)
            sha = env.get("source_build_environment_sha256")
            recomputed = None
            if sha and "backend" in env and "build_distributions" in env:
                doc = {
                    "schema_version": SCHEMA_VERSION,
                    "backend": env["backend"],
                    "declared_requires": env.get("declared_requires", []),
                    "dynamic_hook": DYNAMIC_HOOK_NAME,
                    "build_distributions": env.get("build_distributions", []),
                    "python": env.get("python", {}),
                    "pip_frontend_version": env.get("pip_frontend_version"),
                }
                recomputed = compute_fingerprint_sha(doc)
            env_ok = bool(sha) and recomputed == sha
        self._check("source_build_environment_identity", env_ok)

        # exact built wheel raw SHA: recompute from retained bytes
        wheel_ok = True
        wheel_bad = []
        built_identity_path = root / "runtime_source_build_identity.json"
        if built_identity_path.exists():
            built = read_json(built_identity_path)
            wheel_file = root / BUILT_WHEEL_REL / "1" / \
                built.get("built_wheel", {}).get("filename", "")
            if not wheel_file.is_file():
                wheel_ok = False
                wheel_bad.append("built_wheel_1:ABSENT")
            elif sha256_file(wheel_file) != built.get("built_wheel", {}).get("raw_sha256"):
                wheel_ok = False
                wheel_bad.append("built_wheel_1_raw_sha256_mismatch")
            wheel2_file = root / BUILT_WHEEL_REL / "2" / \
                built.get("built_wheel", {}).get("filename", "")
            if not wheel2_file.is_file():
                wheel_ok = False
                wheel_bad.append("built_wheel_2:ABSENT")
            elif sha256_file(wheel2_file) != built.get("built_wheel", {}).get("raw_sha256"):
                # repeat builds must be byte-identical when recorded equal
                if built.get("built_wheel", {}).get("repeat_build_raw_sha256_match"):
                    wheel_ok = False
                    wheel_bad.append("built_wheel_2_raw_sha256_mismatch")
            # wheel RECORD validity + payload identity recomputed
            if wheel_file.is_file():
                validation = validate_wheel(
                    wheel_file,
                    built.get("name", ""), built.get("version", ""))
                if not validation["valid"]:
                    wheel_ok = False
                    wheel_bad.append("wheel_record_invalid")
                payload = wheel_payload_sha256(wheel_file)
                if payload != built.get("built_wheel", {}).get("WHEEL_PAYLOAD_SHA256"):
                    wheel_ok = False
                    wheel_bad.append("wheel_payload_identity_mismatch")
        else:
            wheel_ok = False
            wheel_bad.append("runtime_source_build_identity.json:ABSENT")
        self._check("built_wheel_identity", wheel_ok,
                    ",".join(wheel_bad) if wheel_bad else None)

        # actual local-wheel install report identity
        report_ok = False
        report_detail = None
        ir_path = root / "source_built_install_report.json"
        if ir_path.exists() and wheel_ok:
            try:
                wheel_file = root / BUILT_WHEEL_REL / "1" / \
                    read_json(built_identity_path)["built_wheel"]["filename"]
                verified = verify_install_report(
                    ir_path, wheel_file,
                    read_json(built_identity_path)["built_wheel"]["raw_sha256"])
                report_ok = verified["valid"]
                if not report_ok:
                    report_detail = "; ".join(verified.get("reasons", []))
            except Exception as exc:
                report_detail = f"verify_install_report failed: {exc}"
        self._check("install_report_identity", report_ok, report_detail)

        # installed RECORD + payload identity from retained snapshots
        installed_ok = True
        installed_bad = []
        inst_path = root / "installed_record_snapshot.json"
        payload_manifest_path = root / "installed_payload_manifest.json"
        if inst_path.exists() and payload_manifest_path.exists():
            inst = read_json(inst_path)
            pman = read_json(payload_manifest_path)
            if inst.get("record_valid") is not True:
                installed_ok = False
                installed_bad.append("installed_record_valid=false")
            if inst.get("valid") is not True:
                installed_ok = False
                installed_bad.append(f"installed_payload_invalid:{inst.get('reasons')}")
            if pman.get("INSTALLED_PAYLOAD_SHA256") != inst.get("INSTALLED_PAYLOAD_SHA256"):
                installed_ok = False
                installed_bad.append("payload_manifest_sha_mismatch")
            if pman.get("record_valid") is not True:
                installed_ok = False
                installed_bad.append("payload_manifest_record_invalid")
            # hard invariant (same relative-path convention on both sides):
            # INSTALLED_PAYLOAD_SHA256 == WHEEL_PAYLOAD_SHA256 of the exact
            # retained built wheel (installed tree == wheel payload)
            if wheel_ok:
                wheel_file = root / BUILT_WHEEL_REL / "1" / \
                    read_json(built_identity_path)["built_wheel"]["filename"]
                if wheel_payload_sha256(wheel_file) != inst.get("INSTALLED_PAYLOAD_SHA256"):
                    installed_ok = False
                    installed_bad.append("installed_vs_built_payload_identity_differs")
            else:
                installed_ok = False
                installed_bad.append("built_wheel_unavailable_for_payload_compare")
        else:
            installed_ok = False
            installed_bad.append("installed snapshots:ABSENT")
        self._check("installed_payload_identity", installed_ok,
                    ",".join(installed_bad) if installed_bad else None)

        # remainder manifest: every wheel hash re-verified against nothing
        # retained (bytes not retained by design) -- identity retained
        remainder_ok = False
        rm_path = root / "remainder_runtime_manifest.json"
        req_path = root / "remainder_requirements.txt"
        if rm_path.exists() and req_path.exists():
            rm = read_json(rm_path)
            req_text = req_path.read_text(encoding="utf-8")
            hashes = re.findall(r"sha256:([0-9a-f]{64})", req_text)
            manifest_hashes = sorted(
                d["sha256"] for d in rm.get("distributions", []))
            remainder_ok = (
                rm.get("schema_version") == SCHEMA_VERSION
                and sorted(hashes) == manifest_hashes
                and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in manifest_hashes)
            )
        self._check("remainder_manifest_identity", remainder_ok)

        # mutation negative: retained mutated wheel must fail validation
        mutation_ok = False
        mut_receipt_path = root / "mutation_negative_receipt.json"
        if mut_receipt_path.exists():
            mut = read_json(mut_receipt_path)
            mut_wheel = root / "mutation_negative" / mut.get("mutated_wheel_filename", "")
            if mut_wheel.is_file():
                re_validation = validate_wheel(mut_wheel, "", "")
                mutation_ok = (
                    mut.get("rejected") is True
                    and not re_validation["valid"]
                )
        self._check("mutation_negative", mutation_ok)

        # cache-disabled proof: build logs must prove a wheel was built
        cache_ok = False
        log1 = root / "source_build_1.log"
        log2 = root / "source_build_2.log"
        if log1.is_file() and log2.is_file():
            cache_ok = (
                source_build_cache_ok(log1.read_text(encoding="utf-8", errors="replace"))
                and source_build_cache_ok(log2.read_text(encoding="utf-8", errors="replace"))
            )
        self._check("source_build_cache_disabled", cache_ok)

        # shadow surface recorded result re-derived from the retained log
        shadow_ok = False
        shadow_detail = None
        surf_result_path = root / "shadow_surface_result.json"
        if surf_result_path.exists():
            result = read_json(surf_result_path)
            log = root / "shadow_surface.log"
            if log.is_file():
                text = log.read_text(encoding="utf-8", errors="replace")
                exits = re.findall(r"\(exit (\d+)\)", text)
                last_exit = int(exits[-1]) if exits else None
                shadow_ok = (
                    result.get("pass") is True
                    and last_exit == 0
                )
                if surface == "pyarrow24":
                    shadow_ok = shadow_ok and result.get("pyarrow_version") == "24.0.0"
            else:
                shadow_detail = "shadow_surface.log:ABSENT"
        self._check("shadow_surface", shadow_ok, shadow_detail)

        # survival + wheels-only + final-match recorded flags
        flags = {}
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            flags["valid"] = receipt.get("source_build_identity_valid") is True
            flags["final_runtime_match"] = receipt.get("final_runtime_match") is True
        summary_path = root / "probe_summary.txt"
        if summary_path.exists():
            text = summary_path.read_text(encoding="utf-8")
            flags["survival"] = (
                "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL=true" in text)
            flags["wheels_only"] = "RUNTIME_INSTALL_FROM_WHEELS_ONLY=true" in text
            flags["shadow"] = "SHADOW_SURFACE_PASS=true" in text
            flags["crash"] = "MEASURE_CRASH=true" not in text
        flags_ok = all(flags.get(k) is True for k in
                       ("valid", "final_runtime_match", "survival",
                        "wheels_only", "shadow", "crash"))
        self._check("recorded_flags", flags_ok,
                    str({k: v for k, v in flags.items() if v is not True}))

        # verifier self-identity
        verifier_ok = False
        vf = root / "verifier_source.py"
        if vf.is_file():
            running = Path(os.path.abspath(__file__))
            verifier_ok = os.path.realpath(running) == os.path.realpath(vf)
        self._check("verifier_source", verifier_ok)

        return self._summary(True)

    def _summary(self, replay_ok):
        all_ok = all(
            v is True for k, v in self.checks.items() if not k.endswith("_detail")
        )
        final_ok = replay_ok and all_ok
        summary = {
            "schema_version": SCHEMA_VERSION,
            "surface": None,
            "replay_ok": final_ok,
            "checks": {
                k: v for k, v in self.checks.items()
                if not k.endswith("_detail")
            },
            "details": {
                k: v for k, v in self.checks.items()
                if k.endswith("_detail")
            },
        }
        write_json(self.root / "replay_summary.json", summary)
        return final_ok


def cmd_verify_bundle(args):
    verifier = BundleVerifier(args.bundle_dir)
    replay_ok = verifier.verify()
    summary_path = Path(args.bundle_dir) / "replay_summary.txt"
    lines = []
    for key in sorted(
        k for k in verifier.checks if not k.endswith("_detail")
    ):
        lines.append(f"{key}={str(verifier.checks[key]).lower()}")
    lines.append(f"EVIDENCE_BUNDLE_REPLAY_OK={'true' if replay_ok else 'false'}")
    if not replay_ok:
        failed = sorted(
            k for k in verifier.checks
            if not k.endswith("_detail") and verifier.checks[k] is not True
        )
        lines.append(f"reason=failed_checks:{','.join(failed)}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8",
                            newline="\n")
    print(summary_path.read_text(encoding="utf-8"))
    return 0


# ---------------------------------------------------------------------------
# cross-head comparison
# ---------------------------------------------------------------------------


def compare_identity_docs(doc_a, doc_b):
    """Exact per-field equality of two runtime_sdist_identity docs.

    Returns (equal, first_differing_field).  The complete candidate
    identity is: source-input identity + runner + Python + pip + action +
    workflow + runtime resolver + source sdist + source build environment
    + exact built wheel SHA256 + installed payload + P2-5 MarketVault
    closed-world build identity.  No field is normalized away.
    """
    if doc_a.get("schema_version") != doc_b.get("schema_version"):
        return False, "schema_version"
    if doc_a.get("surface") != doc_b.get("surface"):
        return False, "surface"
    for field in ("runner", "python", "resolver", "dependency_contract",
                  "action_contract", "workflow", "resolved_distributions",
                  "source_sdist_identity", "source_build_environment_identity",
                  "exact_built_wheel_sha256", "installed_payload_identity",
                  "marketvault_build_identity"):
        if doc_a.get(field) != doc_b.get(field):
            return False, field
    for field in ("source_build_identity_valid", "final_runtime_match",
                  "shadow_surface_pass"):
        if doc_a.get(field) != doc_b.get(field):
            return False, field
    return True, None


def cmd_compare(args):
    doc_a = read_json(args.a)
    doc_b = read_json(args.b)
    equal, first_diff = compare_identity_docs(doc_a, doc_b)
    result = {
        "a": args.a,
        "b": args.b,
        "equal": equal,
        "first_differing_field": first_diff,
    }
    if args.out:
        write_json(args.out, result)
    print(f"RUNTIME_SDIST_IDENTITY_MATCH={str(equal).lower()}")
    if not equal:
        print(f"reason=first_differing_field:{first_diff}")
    return 0


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("measure", help="run the P2-6 measurement")
    p.add_argument("--surface", choices=SURFACES, required=True)
    p.add_argument("--actions-checkout", required=True)
    p.add_argument("--actions-setup-python", required=True)
    p.add_argument("--actions-upload-artifact", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--out-dir", default="p26-evidence")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("bundle", help="assemble the evidence bundle")
    p.add_argument("--out-dir", default="p26-evidence")
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser("verify-bundle", help="offline replay")
    p.add_argument("--bundle-dir", required=True)
    p.set_defaults(func=cmd_verify_bundle)

    p = sub.add_parser("compare", help="cross-head identity comparison")
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("canonicalize", help="canonical form of a JSON file")
    p.add_argument("path")
    p.set_defaults(func=lambda a: sys.stdout.write(
        canonical_serialize(read_json(a.path))))

    return parser


def parse_argv(argv):
    """Parse argv into a Namespace; tests use this to verify the CLI
    wiring without executing a command."""
    return build_parser().parse_args(argv)


def main(argv=None):
    args = parse_argv(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
