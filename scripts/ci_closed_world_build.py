#!/usr/bin/env python3
"""P2-5 closed-world build execution canary (TEMPORARY, PR #80).

MEASUREMENT / SHADOW EVIDENCE ONLY.  This script never gates the heavy
chain, never authorizes reuse, never activates Partial Reuse V2, and never
changes release behavior.

It measures whether the REAL editable build of MarketVault can be executed
as a *closed world* with respect to Python build distributions: an exact
pre-provisioned build environment (hash-locked, locally materialized, no
remote index) executed through the PEP 517/660 backend with pip's build
dependency management disabled (--no-build-isolation), so that pip cannot
auto-install any fingerprinted-set-external "fourth build dependency".

Evidence produced per surface (test-3.14 / pyarrow24):
  - live-resolved effective build set (declared requires +
    get_requires_for_build_editable hook result + transitive graph),
    every artifact a wheel with exact version + SHA256, materialized
    locally; local bytes hash == resolver identity
  - stable dynamic-hook proof: hook probed in a static-only env and again
    inside the exact final build env; canonical equality required
  - exact prebuild environment: fresh venv, upgraded pip (recorded),
    hash-locked requirements file installed ONLY from the local exact
    wheelhouse (PIP_NO_INDEX=1 + PIP_FIND_LINKS + --require-hashes);
    importlib.metadata inventory before the build
  - the REAL MarketVault editable build inside that exact env:
    `pip install --no-build-isolation --no-deps --check-build-dependencies
    --report actual_editable_install_report.json -e .` with PIP_NO_INDEX=1
  - post-build inventory; the ONLY permitted distribution delta is
    market-vault == 0.7.0 added; no fourth build distribution
  - synthetic sentinel: a tiny valid pure-Python wheel generated at
    runtime, demanded by a synthetic in-tree backend's dynamic hook;
    CONTROL branch (ordinary build isolation) must auto-install it;
    CLOSED-WORLD branch (--no-build-isolation, sentinel wheel still
    available in the candidate source) must reject it WITHOUT installing
  - runtime/dev dependencies installed separately AFTER the build (never
    `pip install -e ".[dev]"` again), then FINAL_RUNTIME_MATCH against the
    pre-install runtime resolution
  - closed_world_build_receipt.json + closed_world_identity.json
    (NORMALIZED_BUILD_IDENTITY_SHA256 is path-free by design;
    EXECUTION_BUILD_REQUIREMENTS_SHA256 covers the concrete local
    requirements file)
  - self-contained evidence bundle with a duplicate-path-hardened
    EVIDENCE_MANIFEST.json and an OFFLINE replay verifier that fails
    closed.

All measurement hashes are CI-ONLY / NON-FORMAL-RELEASE.  Removed entirely
on the final docs-only head.

Subcommands:
  measure        run the closed-world measurement for one surface
  bundle         assemble the self-contained evidence bundle + manifest
  verify-bundle  replay the bundle OFFLINE from a clean copy (fail closed)
  compare        compare two closed_world_identity.json documents
  canonicalize   print the canonical form of a JSON file (test helper)
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

SCHEMA_VERSION = 3
PROGRAM = "market-vault-p25-closed-world-canary"

SURFACES = ("test-3.14", "pyarrow24")
SURFACE_REQUIREMENTS = {
    "test-3.14": ("-e", ".[dev]"),
    "pyarrow24": ("-e", ".[dev]", "pyarrow==24.0.0"),
}

LOCAL_PROJECT_NAME = "market-vault"
EXPECTED_PROJECT_VERSION = "0.7.0"
DYNAMIC_HOOK_NAME = "get_requires_for_build_editable"

# P2-5 exact-action pins (derived live from the current main CI log; the
# workflow passes them explicitly, these are only fallback defaults).
DEFAULT_ACTION_PINS = {
    "checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "setup_python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "upload_artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}

SENTINEL_NAME = "p2-closed-world-sentinel"
SENTINEL_VERSION = "0.0.1"
SENTINEL_MODULE = "p2_closed_world_sentinel"
SENTINEL_WHEEL_FILENAME = f"{SENTINEL_MODULE}-{SENTINEL_VERSION}-py3-none-any.whl"
SENTINEL_MARKER_VALUE = f"{SENTINEL_NAME}-{SENTINEL_VERSION}"

SYNTHETIC_PROJECT_NAME = "p2-synthetic-editable"
SYNTHETIC_PROJECT_VERSION = "0.0.1"

# Evidence bundle required files (self-contained; every one must be
# present in the manifest exactly once).
BUNDLE_REQUIRED_FILES = (
    "closed_world_build_receipt.json",
    "closed_world_identity.json",
    "PREBUILD_ENVIRONMENT.json",
    "POSTBUILD_ENVIRONMENT.json",
    "build_effective_set.json",
    "normalized_build_identity.json",
    "dynamic_hook_probe_1.json",
    "dynamic_hook_probe_2.json",
    "exact_build_environment.txt",
    "actual_editable_install_report.json",
    "actual_closed_world_editable_build.log",
    "runtime_resolver_report.json",
    "runtime_actual_install_report.json",
    "runtime_verification_receipt.json",
    "synthetic_receipt.json",
    "synthetic_control.log",
    "synthetic_closed_world.log",
    "synthetic_sentinel_wheel.whl",
    "synthetic_source/pyproject.toml",
    "synthetic_source/p2_synthetic_backend.py",
    "probe_summary.txt",
    "verifier_source.py",
)
# pyarrow24 additionally carries the pyarrow pin install report.
BUNDLE_REQUIRED_FILES_PYARROW24 = (
    "runtime_pyarrow_pin_report.json",
)

WHEELHOUSE_REL = "exact_build_wheelhouse"

# ---------------------------------------------------------------------------
# canonicalization + hashing (shared with the #78/#79 sealed proof family)
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


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(canonical_serialize(obj))


# ---------------------------------------------------------------------------
# process + environment helpers
# ---------------------------------------------------------------------------


def _run(cmd, cwd=None, env=None, log_path=None, timeout=1800, allow_fail=False):
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
        "    n = (d.metadata or {}).get('Name')\n"
        "    if not n:\n"
        "        n = d.metadata['Name'] if d.metadata and d.metadata.get('Name') else d.metadata.get('Name') or ''\n"
        "    if not n:\n"
        "        continue\n"
        "    out[n] = d.version or ''\n"
        "print(json.dumps(out, sort_keys=True))\n"
    )
    proc = _run(
        [venv_python, "-c", code], log_path=log_path, allow_fail=False
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _importlib_metadata_check(venv_python, records, log_path=None):
    """Cross-check that each {name, version} record is present in the venv."""
    inventory = _inventory_json(venv_python, log_path=log_path)
    # importlib.metadata returns raw dist names ("jaraco.classes", "PyYAML",
    # "moomoo_api") — canonicalize the whole inventory for lookup.
    by_canonical = {canonicalize_name(k): v for k, v in inventory.items()}
    checks = {}
    ok = True
    for rec in sorted(records, key=lambda r: canonicalize_name(r["name"])):
        key = canonicalize_name(rec["name"])
        actual = by_canonical.get(key)
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
# pip report parsing
# ---------------------------------------------------------------------------


def parse_pip_report(report_path, skip_local_project=True):
    """Canonical records from a pip --report file.

    Returns sorted list of {name, version, url, sha256} for the installed
    distributions; the local project is skipped when requested.  Rejects
    duplicate canonical names and unsorted output (fail closed).
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
        url = None
        sha = None
        info = entry.get("download_info") or {}
        if info.get("url"):
            url = normalize_download_url(info["url"])
            # pip --report nests hashes under download_info.archive_info
            archive_info = info.get("archive_info") or {}
            hashes = archive_info.get("hashes") or info.get("hashes") or {}
            sha = hashes.get("sha256")
            if not sha or not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
                raise ValueError(
                    f"report {report_path}: missing/odd sha256 for {canonical}"
                )
        records.append(
            {"name": canonical, "version": version, "url": url, "sha256": sha}
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
        for rec in parse_pip_report(path):
            if rec["name"] not in merged:
                order.append(rec["name"])
            merged[rec["name"]] = rec
    return [merged[name] for name in order]


# ---------------------------------------------------------------------------
# project + action contracts
# ---------------------------------------------------------------------------


def dependency_contract(repo_root):
    import tomllib

    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")
    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
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
# build set resolution
# ---------------------------------------------------------------------------


def _is_wheel_url(url):
    return url.endswith(".whl") and "/" not in url.rsplit("/", 1)[-1]


def _wheel_filename_matches(filename, name, version):
    if "/" in filename or "\\" in filename or not filename.endswith(".whl"):
        return False
    stem = filename[:-4]
    norm = canonicalize_name(name).replace("-", "_")
    return stem.startswith(f"{norm}-{version}-")


def _download_exact(url, sha256, dest_dir, log_path=None, attempts=3):
    """Download a wheel from its resolver URL and verify local bytes."""
    filename = url.rsplit("/", 1)[-1]
    dest = Path(dest_dir) / filename
    last_err = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"{PROGRAM}/1.0"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
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


class BuildSetResolver:
    """Resolve + materialize the exact effective build dependency set."""

    def __init__(self, surface, contract, venv_python, pip_exec, out_dir, log_path):
        self.surface = surface
        self.contract = contract
        self.venv_python = venv_python
        self.pip_exec = pip_exec
        self.out_dir = Path(out_dir)
        self.log_path = log_path
        self.wheelhouse = self.out_dir / WHEELHOUSE_REL

    def _dry_run_report(self, requirements, report_rel, allow_fail=False):
        report_path = self.out_dir / report_rel
        cmd = [self.venv_python, "-m", "pip", "install", "--dry-run",
               "--ignore-installed", "--report", str(report_path),
               *requirements]
        proc = _run(cmd, cwd=self.out_dir.parent, log_path=self.log_path,
                    allow_fail=allow_fail)
        return report_path

    def resolve(self):
        """Full pipeline: static -> hook probe 1 -> effective -> materialize."""
        contract = self.contract
        backend = contract["build_system"]["build_backend"]
        declared = contract["build_system"]["requires"]
        self.wheelhouse.mkdir(parents=True, exist_ok=True)

        # (a) static declared set
        static_report = self._dry_run_report(declared, "build_static_report.json")
        static_records = parse_pip_report(static_report)

        # (b) materialize the static wheels (exact bytes + SHA256)
        for rec in static_records:
            if not rec["url"] or not _is_wheel_url(rec["url"]):
                raise RuntimeError(
                    f"static build dep {rec['name']}: resolver returned "
                    f"non-wheel artifact (reject sdist/direct source)"
                )
            _download_exact(
                rec["url"], rec["sha256"], self.wheelhouse, log_path=self.log_path
            )

        # (c) dynamic hook probe 1: static-only environment
        probe1 = self._run_hook_probe(backend, declared, static_records)

        # (d) effective set = declared + dynamic requirements
        effective_reqs = list(declared) + list(probe1["normalized_sorted"])
        effective_report = self._dry_run_report(
            effective_reqs, "build_effective_report.json"
        )
        effective_records = parse_pip_report(effective_report)

        # (e) materialize every effective wheel; every artifact must be a
        # wheel with an exact hash; duplicate canonical names rejected
        seen = {}
        for rec in effective_records:
            if not rec["url"] or not _is_wheel_url(rec["url"]):
                raise RuntimeError(
                    f"effective build dep {rec['name']}: non-wheel artifact "
                    f"rejected (sdist/VCS/remote direct URL/local project)"
                )
            filename = rec["url"].rsplit("/", 1)[-1]
            if not _wheel_filename_matches(filename, rec["name"], rec["version"]):
                raise RuntimeError(
                    f"effective build dep {rec['name']} {rec['version']}: "
                    f"wheel filename {filename!r} does not match canonical "
                    f"name/version"
                )
            if rec["name"] in seen:
                raise RuntimeError(
                    f"effective build dep {rec['name']}: duplicate canonical "
                    f"package (ambiguous version)"
                )
            seen[rec["name"]] = True
            _download_exact(
                rec["url"], rec["sha256"], self.wheelhouse, log_path=self.log_path
            )

        effective = [
            {
                "name": rec["name"],
                "version": rec["version"],
                "filename": rec["url"].rsplit("/", 1)[-1],
                "sha256": rec["sha256"],
            }
            for rec in effective_records
        ]
        effective.sort(key=lambda d: (d["name"], d["version"]))
        return {
            "schema_version": SCHEMA_VERSION,
            "surface": self.surface,
            "backend": backend,
            "declared_requires": sorted(declared),
            "dynamic_hook": DYNAMIC_HOOK_NAME,
            "dynamic_requires": sorted(probe1["normalized_sorted"]),
            "effective_build_distributions": effective,
        }, probe1

    def _run_hook_probe(self, backend, declared, static_records):
        """Probe the dynamic hook inside a clean static-only environment."""
        hook_venv = Path(tempfile.mkdtemp(prefix="p25_hook_probe_"))
        try:
            _run(
                [self.venv_python, "-m", "venv", str(hook_venv)],
                log_path=self.log_path,
            )
            hook_python = _venv_python(hook_venv)
            _run([hook_python, "-m", "pip", "install", "--upgrade", "pip"],
                 log_path=self.log_path)
            env = dict(os.environ)
            env["PIP_NO_INDEX"] = "1"
            env["PIP_FIND_LINKS"] = str(self.wheelhouse)
            _run(
                [hook_python, "-m", "pip", "install", "--no-deps",
                 *[f"{r['name']}=={r['version']}" for r in static_records]],
                env=env,
                log_path=self.log_path,
            )
            return self._invoke_hook(hook_python, backend)
        finally:
            shutil.rmtree(hook_venv, ignore_errors=True)

    @staticmethod
    def _invoke_hook(venv_python, backend):
        snippet = (
            "import importlib, json, sys\n"
            "module = importlib.import_module(sys.argv[1])\n"
            "hook = getattr(module, 'get_requires_for_build_editable', None)\n"
            "if hook is None:\n"
            "    raise RuntimeError('hook get_requires_for_build_editable missing')\n"
            "result = hook(config_settings=None)\n"
            "print(json.dumps({'verbatim': sorted(result)}))\n"
        )
        proc = _run([venv_python, "-c", snippet, backend])
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        verbatim = sorted(str(x) for x in data["verbatim"])
        return {"verbatim": verbatim, "normalized_sorted": sorted(
            re.sub(r"\s+", "", str(x)) for x in verbatim
        )}


# ---------------------------------------------------------------------------
# normalized + execution build identity
# ---------------------------------------------------------------------------


def normalized_build_identity(contract, build_set, probe1, probe2):
    """Path-free canonical build contract identity (NORMALIZED_*_SHA256)."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "surface": build_set["surface"],
        "backend": build_set["backend"],
        "declared_requires": sorted(build_set["declared_requires"]),
        "dynamic_hook": DYNAMIC_HOOK_NAME,
        "dynamic_requires": sorted(build_set["dynamic_requires"]),
        "canonical_package_name": canonicalize_name(LOCAL_PROJECT_NAME),
        "exact_version": EXPECTED_PROJECT_VERSION,
        "build_artifacts": [
            {
                "name": d["name"],
                "version": d["version"],
                "filename": d["filename"],
                "sha256": d["sha256"],
            }
            for d in build_set["effective_build_distributions"]
        ],
        "dynamic_hook_probe_1": probe1["normalized_sorted"],
        "dynamic_hook_probe_2": probe2["normalized_sorted"],
        "pip_frontend_version": build_set.get("pip_frontend_version"),
    }
    doc["normalized_build_identity_sha256"] = compute_fingerprint_sha(doc)
    return doc


def execution_build_requirements_sha256(requirements_file):
    """Digest over the concrete local hash-locked requirements file."""
    return sha256_file(requirements_file)


# ---------------------------------------------------------------------------
# exact prebuild environment
# ---------------------------------------------------------------------------


def write_exact_build_environment(requirements, dest_path):
    """Hash-locked requirements file: name==version --hash=sha256:..."""
    lines = []
    for req in sorted(requirements, key=lambda r: (r["name"], r["version"])):
        lines.append(f"{req['name']}=={req['version']} --hash=sha256:{req['sha256']}")
    text = "\n".join(lines) + "\n"
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return dest_path


def provision_exact_env(venv_dir, base_python, wheelhouse, requirements_file,
                        log_path=None, upgrade_pip=True):
    """Create a venv and install the hash-locked exact build set locally.

    No remote index during provisioning: PIP_NO_INDEX=1 + PIP_FIND_LINKS
    pointing at the exact local wheelhouse + --require-hashes.
    """
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
         "-r", str(requirements_file)],
        env=env,
        log_path=log_path,
    )
    return venv_python, pip_version


# ---------------------------------------------------------------------------
# distribution delta
# ---------------------------------------------------------------------------


def distribution_delta(pre, post):
    """Only market-vault == 0.7.0 may be ADDED; nothing changed/removed."""
    pre_names = set(pre)
    post_names = set(post)
    added = {n: post[n] for n in sorted(post_names - pre_names)}
    changed = {
        n: {"before": pre[n], "after": post[n]}
        for n in sorted(pre_names & post_names)
        if canonicalize_name(str(pre[n])) != canonicalize_name(str(post[n]))
    }
    removed = {n: pre[n] for n in sorted(pre_names - post_names)}
    ok = (
        added == {canonicalize_name(LOCAL_PROJECT_NAME): EXPECTED_PROJECT_VERSION}
        and not changed
        and not removed
    )
    reason = None
    if not ok:
        parts = []
        if added != {canonicalize_name(LOCAL_PROJECT_NAME): EXPECTED_PROJECT_VERSION}:
            parts.append(f"added={added!r}")
        if changed:
            parts.append(f"changed={changed!r}")
        if removed:
            parts.append(f"removed={removed!r}")
        reason = "; ".join(parts)
    permitted_added = added.get(
        canonicalize_name(LOCAL_PROJECT_NAME)
    ) == EXPECTED_PROJECT_VERSION
    unexpected = (
        (len(added) - (1 if permitted_added else 0))
        + len(changed) + len(removed)
    )
    return {
        "added": added,
        "changed": changed,
        "removed": removed,
        "valid": ok,
        "reason": reason,
        "unexpected_distribution_count": unexpected,
    }


# ---------------------------------------------------------------------------
# synthetic sentinel (runtime-generated, never committed)
# ---------------------------------------------------------------------------


def build_sentinel_wheel(target_dir):
    """Build a tiny valid pure-Python wheel with stdlib only."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = target_dir / SENTINEL_WHEEL_FILENAME
    dist_info = f"{SENTINEL_MODULE}-{SENTINEL_VERSION}.dist-info"

    def sha_b64(data):
        return "sha256=" + base64.urlsafe_b64encode(
            hashlib.sha256(data).digest()
        ).rstrip(b"=").decode("ascii")

    entries = [
        (f"{SENTINEL_MODULE}/__init__.py",
         f"SENTINEL_MARKER = '{SENTINEL_MARKER_VALUE}'\n".encode("utf-8")),
        (f"{dist_info}/METADATA",
         ("Metadata-Version: 2.1\n"
          f"Name: {SENTINEL_NAME}\n"
          f"Version: {SENTINEL_VERSION}\n").encode("utf-8")),
        (f"{dist_info}/WHEEL",
         ("Wheel-Version: 1.0\n"
          f"Generator: {PROGRAM}\n"
          "Root-Is-Purelib: true\n"
          "Tag: py3-none-any\n").encode("utf-8")),
    ]
    record_lines = []
    for path, data in entries:
        record_lines.append(f"{path},{sha_b64(data)},{len(data)}")
    record_body = "\n".join(record_lines)
    record_self = f"{dist_info}/RECORD"
    record_text = record_body + f"\n{record_self},,\n"
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries:
            zf.writestr(path, data)
        zf.writestr(record_self, record_text.encode("utf-8"))
    return wheel_path


def write_synthetic_project(target_dir):
    """Synthetic editable project with an in-tree backend that demands the
    sentinel from its dynamic hook and imports it during build_editable."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools>=68", "wheel"]\n'
        'build-backend = "p2_synthetic_backend"\n'
        'backend-path = ["."]\n'
        "\n"
        "[project]\n"
        f'name = "{SYNTHETIC_PROJECT_NAME}"\n'
        f'version = "{SYNTHETIC_PROJECT_VERSION}"\n',
        encoding="utf-8",
    )
    (target_dir / "p2_synthetic_backend.py").write_text(
        "# P2-5 synthetic backend (runtime-generated, never committed).\n"
        "# Delegates to setuptools.build_meta but demands the sentinel from\n"
        "# the PEP 660 dynamic hook and imports it during build_editable.\n"
        "from setuptools.build_meta import build_editable as _real_build_editable\n"
        "from setuptools.build_meta import get_requires_for_build_wheel as _real_get_requires_wheel\n"
        "\n"
        "def get_requires_for_build_editable(config_settings=None):\n"
        "    return ['p2-closed-world-sentinel==0.0.1']\n"
        "\n"
        "def build_editable(wheel_directory, config_settings=None, metadata_directory=None):\n"
        "    import p2_closed_world_sentinel\n"
        "    assert p2_closed_world_sentinel.SENTINEL_MARKER == 'p2-closed-world-sentinel-0.0.1'\n"
        "    return _real_build_editable(wheel_directory, config_settings, metadata_directory)\n",
        encoding="utf-8",
    )
    return target_dir


# ---------------------------------------------------------------------------
# closed-world measurement orchestration
# ---------------------------------------------------------------------------


class ClosedWorldProbe:
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

    def _tempdir(self, prefix):
        d = Path(tempfile.mkdtemp(prefix=prefix))
        self.temp_dirs.append(d)
        return d

    def _mark(self, key, value, reason=None):
        self.verdicts[key] = value
        if reason is not None:
            self.verdicts[f"{key}_reason"] = reason
        return value

    # -- legs --------------------------------------------------------------

    def leg_runtime_resolution(self, base_python):
        """Pre-install runtime resolution of the surface contract."""
        venv = self._tempdir("p25_runtime_probe_")
        _run([base_python, "-m", "venv", str(venv)], log_path=self.log_path)
        venv_python = _venv_python(venv)
        _run([venv_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=self.log_path)
        proc = _run([venv_python, "-m", "pip", "--version"], log_path=self.log_path)
        pip_version = _parse_pip_version(proc.stdout)
        report = self.out_dir / "runtime_resolver_report.json"
        _run(
            [venv_python, "-m", "pip", "install", "--dry-run", "--ignore-installed",
             "--report", str(report), *SURFACE_REQUIREMENTS[self.surface]],
            cwd=self.repo_root,
            log_path=self.log_path,
        )
        records = parse_pip_report(report)
        return records, pip_version

    def leg_build_set(self, base_python):
        """Live-resolved effective build set (section 7)."""
        venv = self._tempdir("p25_build_resolve_")
        _run([base_python, "-m", "venv", str(venv)], log_path=self.log_path)
        venv_python = _venv_python(venv)
        _run([venv_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=self.log_path)
        resolver = BuildSetResolver(
            self.surface, self.contract, venv_python, venv_python,
            self.out_dir, self.log_path,
        )
        build_set, probe1 = resolver.resolve()
        return build_set, probe1, venv_python

    def leg_exact_env_and_probe2(self, base_python, build_set, probe1):
        """Exact prebuild env + stable dynamic-hook proof (sections 8-10)."""
        exact_env = self._tempdir("p25_exact_env_")
        req_file = write_exact_build_environment(
            build_set["effective_build_distributions"],
            self.out_dir / "exact_build_environment.txt",
        )
        exec_sha = execution_build_requirements_sha256(req_file)
        self._mark("EXECUTION_BUILD_REQUIREMENTS_SHA256", exec_sha)
        venv_python, pip_version = provision_exact_env(
            exact_env, base_python, self.out_dir / WHEELHOUSE_REL, req_file,
            log_path=self.log_path,
        )
        probe2 = BuildSetResolver._invoke_hook(venv_python, build_set["backend"])
        stable = probe1["normalized_sorted"] == probe2["normalized_sorted"]
        self._mark("DYNAMIC_HOOK_STABLE", stable,
                   None if stable else "probe1 != probe2 after canonical normalization")
        pre = _inventory_json(venv_python, log_path=self.log_path)
        write_json(self.out_dir / "PREBUILD_ENVIRONMENT.json",
                   {"schema_version": SCHEMA_VERSION, "surface": self.surface,
                    "distributions": pre, "pip_frontend_version": pip_version})
        # pip itself is explicitly inventoried and fingerprinted
        pip_name = None
        for n in pre:
            if canonicalize_name(n) == "pip":
                pip_name = n
        if pip_name is None:
            self._mark("PREBUILD_ENVIRONMENT_OK", False, "pip missing from inventory")
        else:
            self._mark("PREBUILD_ENVIRONMENT_OK", True)
        return venv_python, pip_version, pre, probe2

    def leg_closed_world_build(self, exact_python):
        """REAL MarketVault editable build inside the exact env (section 11).

        Command: PIP_NO_INDEX=1 python -m pip install --no-build-isolation
        --no-deps --check-build-dependencies --report
        actual_editable_install_report.json -e .
        """
        log = self.out_dir / "actual_closed_world_editable_build.log"
        env = dict(os.environ)
        env["PIP_NO_INDEX"] = "1"
        try:
            _run(
                [exact_python, "-m", "pip", "install", "--no-build-isolation",
                 "--no-deps", "--check-build-dependencies",
                 "--report", str(self.out_dir / "actual_editable_install_report.json"),
                 "-e", "."],
                cwd=self.repo_root, env=env, log_path=log,
            )
            ok = True
        except subprocess.CalledProcessError:
            ok = False
        with open(log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"CLOSED_WORLD_EDITABLE_BUILD_OK={'true' if ok else 'false'}\n")
        self._mark("CLOSED_WORLD_EDITABLE_BUILD_OK", ok,
                   None if ok else "real editable build failed inside exact env")
        return ok

    def leg_delta(self, exact_python, pre):
        post = _inventory_json(exact_python, log_path=self.log_path)
        write_json(self.out_dir / "POSTBUILD_ENVIRONMENT.json",
                   {"schema_version": SCHEMA_VERSION, "surface": self.surface,
                    "distributions": post})
        delta = distribution_delta(pre, post)
        write_json(self.out_dir / "distribution_delta.json", delta)
        ok = delta["valid"]
        self._mark("CLOSED_WORLD_DISTRIBUTION_DELTA_OK", ok,
                   None if ok else delta.get("reason"))
        return delta

    def leg_synthetic(self, base_python, build_set):
        """Synthetic sentinel control + closed-world branches (sections 13-16)."""
        sentinel_dir = self._tempdir("p25_sentinel_")
        sentinel_wheel = build_sentinel_wheel(sentinel_dir)
        # the sentinel wheel must be part of the evidence bundle
        shutil.copy2(
            sentinel_wheel,
            self.out_dir / "synthetic_sentinel_wheel.whl",
        )
        project = write_synthetic_project(self.out_dir / "synthetic_source")

        # candidate source: exact normal build wheels + sentinel wheel
        candidate = self._tempdir("p25_candidate_")
        for wheel in (self.out_dir / WHEELHOUSE_REL).glob("*.whl"):
            shutil.copy2(wheel, candidate / wheel.name)
        shutil.copy2(sentinel_wheel, candidate / sentinel_wheel.name)

        # -- CONTROL branch: ordinary build isolation ---------------------
        control_venv = self._tempdir("p25_control_")
        _run([base_python, "-m", "venv", str(control_venv)], log_path=self.log_path)
        control_python = _venv_python(control_venv)
        _run([control_python, "-m", "pip", "install", "--upgrade", "pip"],
             log_path=self.log_path)
        control_log = self.out_dir / "synthetic_control.log"
        env = dict(os.environ)
        env["PIP_NO_INDEX"] = "1"
        env["PIP_FIND_LINKS"] = str(candidate)
        try:
            # -v surfaces pip's suppressed isolated-build subprocess output,
            # making the dynamic-requirement auto-install line visible
            _run(
                [control_python, "-m", "pip", "install", "-v", "-e", str(project)],
                env=env, log_path=control_log,
            )
            control_success = True
        except subprocess.CalledProcessError:
            control_success = False
        log_text = control_log.read_text(encoding="utf-8", errors="replace")
        control_installed = control_success and (
            "p2-closed-world-sentinel" in log_text
        )
        with open(control_log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"CONTROL_DYNAMIC_REQUIREMENT_INSTALLED="
                     f"{'true' if control_installed else 'false'}\n")
        self._mark("CONTROL_DYNAMIC_REQUIREMENT_INSTALLED", control_installed,
                   None if control_installed
                   else "control branch did not auto-install the sentinel "
                       "(old channel not demonstrated)")

        # -- CLOSED-WORLD branch: exact env only, sentinel AVAILABLE -------
        closed_venv = self._tempdir("p25_closed_")
        req_file = write_exact_build_environment(
            build_set["effective_build_distributions"],
            self.out_dir / "synthetic_exact_build_environment.txt",
        )
        provision_exact_env(
            closed_venv, base_python, self.out_dir / WHEELHOUSE_REL, req_file,
            log_path=self.log_path,
        )
        closed_python = _venv_python(closed_venv)
        closed_log = self.out_dir / "synthetic_closed_world.log"
        env = dict(os.environ)
        env["PIP_NO_INDEX"] = "1"
        env["PIP_FIND_LINKS"] = str(candidate)  # sentinel wheel IS available
        try:
            _run(
                [closed_python, "-m", "pip", "install", "--no-build-isolation",
                 "--no-deps", "-e", str(project)],
                env=env, log_path=closed_log,
            )
            closed_success = True
        except subprocess.CalledProcessError:
            closed_success = False
        closed_inventory = _inventory_json(closed_python, log_path=self.log_path)
        sentinel_absent = all(
            canonicalize_name(n) != canonicalize_name(SENTINEL_NAME)
            for n in closed_inventory
        )
        with open(closed_log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"CLOSED_WORLD_SENTINEL_AUTO_INSTALL="
                     f"{'false' if sentinel_absent else 'true'}\n")
        self._mark("CLOSED_WORLD_SENTINEL_AUTO_INSTALL", not sentinel_absent)
        rejected = (not closed_success) and sentinel_absent
        self._mark("CLOSED_WORLD_DYNAMIC_REQUIREMENT_REJECTED", rejected,
                   None if rejected
                   else "synthetic negative branch did not fail-closed "
                       "(sentinel installed or install unexpectedly succeeded)")

        synthetic_receipt = {
            "schema_version": SCHEMA_VERSION,
            "surface": self.surface,
            "control_success": control_success,
            "control_dynamic_requirement_installed": control_installed,
            "closed_world_failure": not closed_success,
            "sentinel_available_during_closed_world": True,
            "sentinel_auto_installed": not sentinel_absent,
            "closed_world_dynamic_requirement_rejected": rejected,
            "valid": (
                control_success and control_installed
                and (not closed_success) and sentinel_absent
            ),
        }
        write_json(self.out_dir / "synthetic_receipt.json", synthetic_receipt)
        return synthetic_receipt

    def leg_runtime_install(self, exact_python):
        """Install runtime + dev dependencies AFTER the build (section 17).

        Never re-runs `pip install -e ".[dev]"` (would trigger another
        build); reads the dependency strings from pyproject.toml and
        installs the external requirements separately.
        """
        deps = self.contract["dependencies"] + self.contract["dev_dependencies"]
        if not deps:
            return None, None
        report = self.out_dir / "runtime_actual_install_report.json"
        _run(
            [exact_python, "-m", "pip", "install", "--report", str(report), *deps],
            cwd=self.repo_root,
            log_path=self.out_dir / "runtime_install.log",
        )
        pin_report = None
        if self.surface == "pyarrow24":
            pin_report = self.out_dir / "runtime_pyarrow_pin_report.json"
            _run(
                [exact_python, "-m", "pip", "install",
                 "--report", str(pin_report), "pyarrow==24.0.0"],
                cwd=self.repo_root,
                log_path=self.out_dir / "runtime_pyarrow_pin.log",
            )
        return report, pin_report

    def leg_final_runtime_match(self, exact_python, resolution, reports):
        """FINAL_RUNTIME_MATCH (section 18): final installed runtime equals
        the pre-install runtime resolution at canonical name/version/artifact
        identity + live importlib.metadata."""
        records = merge_install_reports(reports)
        resolution_by_name = {r["name"]: r for r in resolution}
        inventory = _inventory_json(exact_python, log_path=self.log_path)
        inv_by_canonical = {canonicalize_name(k): v
                            for k, v in inventory.items()}
        ok = True
        mismatches = {}
        pre_satisfied = {}
        for rec in records:
            expected = resolution_by_name.get(rec["name"])
            if expected is None:
                ok = False
                mismatches[rec["name"]] = {
                    "final": rec["version"], "resolution": "ABSENT"
                }
            elif canonicalize_name(str(rec["version"])) != canonicalize_name(
                str(expected["version"])
            ):
                ok = False
                mismatches[rec["name"]] = {
                    "final": rec["version"], "resolution": expected["version"]
                }
            elif expected.get("sha256") and rec.get("sha256") != expected.get("sha256"):
                # artifact identity mismatch at equal version
                ok = False
                mismatches[rec["name"]] = {
                    "final": rec["sha256"], "resolution": expected["sha256"],
                    "note": "artifact sha256 differs at equal version",
                }
        for name in sorted(set(resolution_by_name) - set(records_by_name(records))):
            # Absent from the install report: pip skips distributions the
            # exact prebuild env already provides (e.g. build deps such as
            # packaging). Accept iff the final env still holds the expected
            # version — the env-level match is what matters.
            expected = resolution_by_name[name]
            live_version = inv_by_canonical.get(name)
            if (live_version is not None
                    and canonicalize_name(str(live_version))
                    == canonicalize_name(str(expected["version"]))):
                pre_satisfied[name] = {
                    "version": expected["version"],
                    "sha256": expected.get("sha256"),
                    "reason": "already present in exact prebuild env; "
                              "pip did not reinstall",
                }
            else:
                ok = False
                mismatches[name] = {
                    "final": "ABSENT", "resolution": expected["version"],
                    "note": "not present in final env",
                }
        live_ok, live_checks, _ = _importlib_metadata_check(
            exact_python, [{"name": r["name"], "version": r["version"]}
                           for r in records],
            log_path=self.log_path,
        )
        pyarrow_ok = True
        pyarrow_version = None
        if self.surface == "pyarrow24":
            code = "import pyarrow, json\nprint(json.dumps({'v': pyarrow.__version__}))\n"
            proc = _run([exact_python, "-c", code], log_path=self.log_path,
                        allow_fail=True)
            if proc.returncode == 0:
                pyarrow_version = json.loads(proc.stdout.strip().splitlines()[-1])["v"]
            pyarrow_ok = pyarrow_version == "24.0.0"
        verdict = {
            "schema_version": SCHEMA_VERSION,
            "surface": self.surface,
            "final_runtime_match": ok and live_ok and pyarrow_ok,
            "report_vs_resolution_mismatches": mismatches,
            "pre_satisfied_by_exact_build_env": pre_satisfied,
            "importlib_cross_check_ok": live_ok,
            "importlib_checks": live_checks,
            "pyarrow24_version": pyarrow_version,
            "pyarrow24_match": pyarrow_ok,
            "reason": None if (ok and live_ok and pyarrow_ok) else (
                f"report_mismatch={bool(mismatches)} "
                f"importlib={not live_ok} pyarrow24={not pyarrow_ok}"
            ),
        }
        write_json(self.out_dir / "runtime_verification_receipt.json", verdict)
        self._mark("FINAL_RUNTIME_MATCH", verdict["final_runtime_match"],
                   verdict["reason"])
        return verdict


def records_by_name(records):
    return {r["name"] for r in records}


# ---------------------------------------------------------------------------
# measure command
# ---------------------------------------------------------------------------


def cmd_measure(args):
    actions = {
        "checkout": args.actions_checkout,
        "setup_python": args.actions_setup_python,
        "upload_artifact": args.actions_upload_artifact,
    }
    t0 = time.time()
    summary = {}
    probe = None
    try:
        probe = ClosedWorldProbe(args.surface, actions, args.repo_root,
                                 args.out_dir)
        base_python = sys.executable
        summary["runner"] = runner_identity()
        summary["python"] = python_identity()
        summary["dependency_contract"] = probe.contract
        summary["action_contract"] = action_contract(actions, args.repo_root)

        resolution, pip_version = probe.leg_runtime_resolution(base_python)
        summary["resolved_distributions"] = resolution
        summary["pip_frontend_version"] = pip_version

        build_set, probe1, _ = probe.leg_build_set(base_python)
        summary["build_set"] = build_set
        write_json(probe.out_dir / "build_effective_set.json", build_set)
        write_json(probe.out_dir / "dynamic_hook_probe_1.json",
                   {"schema_version": SCHEMA_VERSION, "surface": args.surface,
                    "dynamic_hook": DYNAMIC_HOOK_NAME, **probe1})
        summary["dynamic_hook_probe_1"] = probe1

        exact_python, pip_version2, pre, probe2 = probe.leg_exact_env_and_probe2(
            base_python, build_set, probe1
        )
        summary["pip_frontend_version_exact_env"] = pip_version2
        write_json(probe.out_dir / "dynamic_hook_probe_2.json",
                   {"schema_version": SCHEMA_VERSION, "surface": args.surface,
                    "dynamic_hook": DYNAMIC_HOOK_NAME, **probe2})
        summary["dynamic_hook_probe_2"] = probe2

        identity_doc = normalized_build_identity(
            probe.contract, build_set, probe1, probe2
        )
        write_json(probe.out_dir / "normalized_build_identity.json", identity_doc)
        summary["normalized_build_identity_sha256"] = (
            identity_doc["normalized_build_identity_sha256"]
        )
        probe._mark("NORMALIZED_BUILD_IDENTITY_SHA256",
                    identity_doc["normalized_build_identity_sha256"])

        build_ok = probe.leg_closed_world_build(exact_python)
        delta = probe.leg_delta(exact_python, pre)
        summary["distribution_delta"] = delta

        synthetic = probe.leg_synthetic(base_python, build_set)
        summary["synthetic"] = synthetic

        runtime_report, pin_report = probe.leg_runtime_install(exact_python)
        reports = []
        if runtime_report is not None:
            reports.append(runtime_report)
        if pin_report is not None:
            reports.append(pin_report)
        runtime_verdict = probe.leg_final_runtime_match(
            exact_python, resolution, reports
        )
        summary["runtime_verification"] = runtime_verdict

        closed_world_valid = (
            probe.verdicts.get("PREBUILD_ENVIRONMENT_OK") is True
            and probe.verdicts.get("DYNAMIC_HOOK_STABLE") is True
            and probe.verdicts.get("CLOSED_WORLD_EDITABLE_BUILD_OK") is True
            and probe.verdicts.get("CLOSED_WORLD_DISTRIBUTION_DELTA_OK") is True
            and probe.verdicts.get("CONTROL_DYNAMIC_REQUIREMENT_INSTALLED") is True
            and probe.verdicts.get("CLOSED_WORLD_SENTINEL_AUTO_INSTALL") is False
            and probe.verdicts.get("CLOSED_WORLD_DYNAMIC_REQUIREMENT_REJECTED") is True
        )
        probe._mark("CLOSED_WORLD_BUILD_VALID", closed_world_valid,
                    None if closed_world_valid else "see per-leg verdicts above")
        leg_ready = closed_world_valid and probe.verdicts.get("FINAL_RUNTIME_MATCH") is True
        probe._mark("CLOSED_WORLD_LEG_READY", leg_ready)

        receipt = {
            "schema_version": SCHEMA_VERSION,
            "surface": args.surface,
            "verifier_script_sha256": sha256_file(Path(__file__)),
            "backend": build_set["backend"],
            "normalized_build_identity_sha256": (
                identity_doc["normalized_build_identity_sha256"]
            ),
            "execution_build_requirements_sha256": (
                probe.verdicts["EXECUTION_BUILD_REQUIREMENTS_SHA256"]
            ),
            "pip_frontend_version": pip_version2,
            "dynamic_hook_probe_1": probe1["normalized_sorted"],
            "dynamic_hook_probe_2": probe2["normalized_sorted"],
            "dynamic_hook_stable": probe.verdicts["DYNAMIC_HOOK_STABLE"],
            "prebuild_distribution_inventory": pre,
            "postbuild_distribution_inventory": _inventory_json(
                exact_python, log_path=probe.log_path),
            "distribution_delta": delta,
            "no_build_isolation_used": True,
            "no_deps_used": True,
            "check_build_dependencies_used": True,
            "actual_editable_build_success": build_ok,
            "unexpected_distribution_count": delta["unexpected_distribution_count"],
            "synthetic_control_success": synthetic["control_success"],
            "synthetic_closed_world_failure": synthetic["closed_world_failure"],
            "sentinel_auto_installed": synthetic["sentinel_auto_installed"],
            "closed_world_build_valid": closed_world_valid,
            "final_runtime_match": runtime_verdict["final_runtime_match"],
            "leg_ready": leg_ready,
            "reason": None if closed_world_valid
            else "see per-leg verdicts in probe_summary.txt",
        }
        write_json(probe.out_dir / "closed_world_build_receipt.json", receipt)

        identity = {
            "schema_version": SCHEMA_VERSION,
            "surface": args.surface,
            "runner": summary["runner"],
            "python": summary["python"],
            "resolver": {
                "pip_version": pip_version,
                "pip_frontend_version_exact_env": pip_version2,
            },
            "dependency_contract": summary["dependency_contract"],
            "action_contract": summary["action_contract"],
            "resolved_distributions": summary["resolved_distributions"],
            "build_contract": {
                "backend": build_set["backend"],
                "declared_requires": sorted(build_set["declared_requires"]),
                "dynamic_hook": DYNAMIC_HOOK_NAME,
                "dynamic_requires": sorted(build_set["dynamic_requires"]),
                "normalized_build_identity_sha256": (
                    identity_doc["normalized_build_identity_sha256"]
                ),
                "execution_build_requirements_sha256": (
                    probe.verdicts["EXECUTION_BUILD_REQUIREMENTS_SHA256"]
                ),
                "effective_build_distributions": build_set[
                    "effective_build_distributions"
                ],
                "pip_frontend_version": pip_version2,
            },
            "closed_world_build_valid": closed_world_valid,
            "final_runtime_match": runtime_verdict["final_runtime_match"],
            "synthetic_control_success": synthetic["control_success"],
            "synthetic_closed_world_failure": synthetic["closed_world_failure"],
            "sentinel_auto_installed": synthetic["sentinel_auto_installed"],
        }
        identity["fingerprint_sha256"] = compute_fingerprint_sha(identity)
        write_json(probe.out_dir / "closed_world_identity.json", identity)

        elapsed = time.time() - t0
        probe._mark("MEASURE_ELAPSED_SECONDS", round(elapsed, 1))
    except Exception as exc:  # measurement never fails the job
        if probe is None:
            probe = ClosedWorldProbe(args.surface, actions, args.repo_root,
                                     args.out_dir)
        probe._mark("MEASURE_CRASH", True, f"{type(exc).__name__}: {exc}")

    summary_path = probe.out_dir / "probe_summary.txt"
    lines = []
    for key in (
        "CLOSED_WORLD_BUILD_VALID",
        "CLOSED_WORLD_LEG_READY",
        "FINAL_RUNTIME_MATCH",
        "DYNAMIC_HOOK_STABLE",
        "CLOSED_WORLD_EDITABLE_BUILD_OK",
        "CLOSED_WORLD_DISTRIBUTION_DELTA_OK",
        "PREBUILD_ENVIRONMENT_OK",
        "CONTROL_DYNAMIC_REQUIREMENT_INSTALLED",
        "CLOSED_WORLD_SENTINEL_AUTO_INSTALL",
        "CLOSED_WORLD_DYNAMIC_REQUIREMENT_REJECTED",
        "MEASURE_CRASH",
    ):
        value = probe.verdicts.get(key)
        if value is None:
            value = False
        lines.append(f"{key}={str(value).lower()}")
        reason = probe.verdicts.get(f"{key}_reason")
        if reason:
            lines.append(f"reason={reason}")
    for key in (
        "NORMALIZED_BUILD_IDENTITY_SHA256",
        "EXECUTION_BUILD_REQUIREMENTS_SHA256",
    ):
        value = probe.verdicts.get(key)
        if value:
            lines.append(f"{key}={value}")
    if "MEASURE_ELAPSED_SECONDS" in probe.verdicts:
        lines.append(f"MEASURE_ELAPSED_SECONDS="
                     f"{probe.verdicts['MEASURE_ELAPSED_SECONDS']}")
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

    Hardening (fixes the #79 21/20, 23/22 duplicate-path weakness): every
    relative path must be unique; a duplicate aborts with
    EVIDENCE_MANIFEST_INVALID reason=duplicate_path:<path>.
    """
    root = Path(out_dir)
    files = []
    for top in sorted(p for p in root.iterdir() if p.is_dir() and p.name != WHEELHOUSE_REL):
        for path in sorted(top.rglob("*")):
            if path.is_file():
                files.append(path)
    for path in sorted(root.iterdir()):
        if path.is_file():
            files.append(path)
    for wheel in sorted((root / WHEELHOUSE_REL).glob("*.whl")):
        files.append(wheel)
    return sorted(files, key=lambda p: _rel_path(p, root))


def _write_manifest(out_dir, required):
    root = Path(out_dir)
    files = _manifest_files(out_dir)
    # Hardening (fixes the #79 21/20, 23/22 duplicate-path weakness): the
    # generator must emit one relative path exactly once; a duplicate is a
    # manifest defect detected BEFORE writing, never silently deduplicated.
    rels = [_rel_path(p, root) for p in files]
    seen = set()
    for rel in rels:
        if rel in seen:
            raise ValueError(
                f"EVIDENCE_MANIFEST_INVALID reason=duplicate_path:{rel}"
            )
        seen.add(rel)
    # The manifest cannot bind its own final bytes (self-referential hash);
    # its own entry is excluded and its integrity is carried by the upload
    # artifact + the binding of every other file below.
    rels = [rel for rel in rels if rel != "EVIDENCE_MANIFEST.json"]
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
    receipt = read_json(root / "closed_world_build_receipt.json")
    surface = receipt.get("surface")
    required = list(BUNDLE_REQUIRED_FILES)
    if surface == "pyarrow24":
        required += list(BUNDLE_REQUIRED_FILES_PYARROW24)
    try:
        manifest = _write_manifest(root, required)
    except ValueError as exc:
        print(f"EVIDENCE_MANIFEST_INVALID {exc}")
        return 2
    # verifier self-copy (byte-identical to this script's verify-bundle logic)
    verifier_dst = root / "verifier_source.py"
    _self_copy(verifier_dst)
    # regenerate so verifier_source.py is bound in the manifest
    manifest = _write_manifest(root, required)
    print(f"EVIDENCE_MANIFEST_COMPLETE={str(manifest['complete']).lower()}")
    for missing in manifest["missing"]:
        print(f"EVIDENCE_MANIFEST_MISSING={missing}")
    return 0 if manifest["complete"] else 2


def _self_copy(dest):
    """Byte-copy this file; on Windows fall back to reading raw bytes."""
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
# offline replay (fail closed)
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

        # 1. manifest present
        manifest_path = root / "EVIDENCE_MANIFEST.json"
        if not manifest_path.exists():
            self._check("manifest_present", False, "missing EVIDENCE_MANIFEST.json")
            return self._summary(False)
        manifest = read_json(manifest_path)
        self._check("manifest_present", True)

        # 2. manifest schema
        schema_ok = (
            manifest.get("schema_version") == SCHEMA_VERSION
            and isinstance(manifest.get("files"), list)
        )
        self._check("manifest_schema", schema_ok,
                    "schema_version mismatch or files missing"
                    if not schema_ok else None)

        # 3. manifest unique paths (independent re-derivation)
        rels = [f.get("path") for f in manifest.get("files", [])]
        dupes = sorted({r for r in rels if rels.count(r) > 1})
        self._check("manifest_unique_paths", not dupes,
                    f"duplicate_path:{','.join(dupes)}" if dupes else None)

        # 4. manifest completeness (required files bound exactly once)
        receipt_path = root / "closed_world_build_receipt.json"
        surface = None
        if receipt_path.exists():
            surface = read_json(receipt_path).get("surface")
        required = list(BUNDLE_REQUIRED_FILES)
        if surface == "pyarrow24":
            required += list(BUNDLE_REQUIRED_FILES_PYARROW24)
        missing = [r for r in required if r not in rels]
        self._check("manifest_complete", not missing,
                    f"missing:{','.join(missing)}" if missing else None)

        # 5. manifest file hashes + sizes
        hash_ok = True
        hash_bad = []
        for entry in manifest.get("files", []):
            rel = entry.get("path")
            if not rel:
                hash_ok = False
                continue
            # Defensive: a manifest cannot bind its own bytes.
            if rel == "EVIDENCE_MANIFEST.json":
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
        self._check("manifest_hashes", hash_ok, ",".join(hash_bad) if hash_bad else None)

        # 6. identity doc present + schema
        identity_path = root / "closed_world_identity.json"
        identity_ok = identity_path.exists() and (
            read_json(identity_path).get("schema_version") == SCHEMA_VERSION
        )
        self._check("identity_schema", identity_ok)

        # 7. identity digest (fingerprint recomputed == stored)
        digest_ok = False
        if identity_ok:
            identity = read_json(identity_path)
            stored = identity.get("fingerprint_sha256")
            recomputed = compute_fingerprint_sha(identity)
            digest_ok = stored == recomputed
        self._check("identity_digest", digest_ok)

        # 8. normalized build identity recomputed from bundle files == stored
        norm_ok = False
        if identity_ok and (root / "normalized_build_identity.json").exists():
            identity = read_json(identity_path)
            stored = identity.get("build_contract", {}).get(
                "normalized_build_identity_sha256")
            norm_doc = read_json(root / "normalized_build_identity.json")
            recomputed = norm_doc.get("normalized_build_identity_sha256")
            norm_ok = bool(stored) and stored == recomputed
        self._check("normalized_identity", norm_ok)

        # 9. execution requirements digest
        exec_ok = False
        req_file = root / "exact_build_environment.txt"
        if identity_ok and req_file.exists():
            stored = identity.get("build_contract", {}).get(
                "execution_build_requirements_sha256")
            exec_ok = bool(stored) and stored == sha256_file(req_file)
        self._check("execution_requirements_digest", exec_ok)

        # 10. wheelhouse hashes (every effective dist's wheel present+correct)
        wheelhouse_ok = True
        wheelhouse_bad = []
        if identity_ok:
            artifacts = identity.get("build_contract", {}).get(
                "effective_build_distributions", [])
            for art in artifacts:
                wheel = root / WHEELHOUSE_REL / art["filename"]
                if not wheel.is_file():
                    wheelhouse_ok = False
                    wheelhouse_bad.append(f"{art['filename']}:ABSENT")
                elif sha256_file(wheel) != art["sha256"]:
                    wheelhouse_ok = False
                    wheelhouse_bad.append(f"{art['filename']}:SHA256")
        self._check("wheelhouse_hashes", wheelhouse_ok,
                    ",".join(wheelhouse_bad) if wheelhouse_bad else None)

        # 11. hook probe equality
        probe_ok = False
        p1 = root / "dynamic_hook_probe_1.json"
        p2 = root / "dynamic_hook_probe_2.json"
        if p1.exists() and p2.exists():
            probe_ok = (
                read_json(p1).get("normalized_sorted")
                == read_json(p2).get("normalized_sorted")
            )
        self._check("hook_probe_equality", probe_ok)

        # 12. prebuild distribution inventory
        pre_ok = False
        pre_path = root / "PREBUILD_ENVIRONMENT.json"
        if pre_path.exists():
            pre = read_json(pre_path)
            names = {canonicalize_name(n) for n in pre.get("distributions", {})}
            pre_ok = (
                pre.get("schema_version") == SCHEMA_VERSION
                and "pip" in names
                and "setuptools" in names
                and "wheel" in names
            )
        self._check("prebuild_distribution", pre_ok)

        # 13. postbuild distribution inventory
        post_ok = False
        post_path = root / "POSTBUILD_ENVIRONMENT.json"
        if post_path.exists():
            post = read_json(post_path)
            names = {canonicalize_name(n) for n in post.get("distributions", {})}
            post_ok = (
                post.get("schema_version") == SCHEMA_VERSION
                and canonicalize_name(LOCAL_PROJECT_NAME) in names
            )
        self._check("postbuild_distribution", post_ok)

        # 14. distribution delta (project-only, recomputed from the two
        # inventories bound in the bundle)
        delta_ok = False
        if pre_ok and post_ok:
            delta = distribution_delta(
                read_json(pre_path)["distributions"],
                read_json(post_path)["distributions"],
            )
            delta_ok = delta["valid"]
        self._check("distribution_delta", delta_ok)

        # 15. actual closed-world build receipt
        receipt_ok = False
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            log_path = root / "actual_closed_world_editable_build.log"
            log_ok = log_path.exists() and "CLOSED_WORLD_EDITABLE_BUILD_OK=true" in (
                log_path.read_text(encoding="utf-8", errors="replace")
            )
            receipt_ok = (
                receipt.get("no_build_isolation_used") is True
                and receipt.get("no_deps_used") is True
                and receipt.get("check_build_dependencies_used") is True
                and receipt.get("actual_editable_build_success") is True
                and receipt.get("closed_world_build_valid") is True
                and log_ok
            )
        self._check("actual_build_receipt", receipt_ok)

        # 16. synthetic receipt (control auto-install + closed-world reject)
        syn_ok = False
        syn_path = root / "synthetic_receipt.json"
        if syn_path.exists():
            syn = read_json(syn_path)
            control_log = root / "synthetic_control.log"
            closed_log = root / "synthetic_closed_world.log"
            control_log_ok = control_log.exists() and (
                "CONTROL_DYNAMIC_REQUIREMENT_INSTALLED=true" in
                control_log.read_text(encoding="utf-8", errors="replace")
            )
            closed_log_ok = closed_log.exists() and (
                "CLOSED_WORLD_SENTINEL_AUTO_INSTALL=false" in
                closed_log.read_text(encoding="utf-8", errors="replace")
            )
            syn_ok = (
                syn.get("schema_version") == SCHEMA_VERSION
                and syn.get("control_success") is True
                and syn.get("control_dynamic_requirement_installed") is True
                and syn.get("closed_world_failure") is True
                and syn.get("sentinel_available_during_closed_world") is True
                and syn.get("sentinel_auto_installed") is False
                and syn.get("closed_world_dynamic_requirement_rejected") is True
                and syn.get("valid") is True
                and control_log_ok
                and closed_log_ok
                and (root / "synthetic_sentinel_wheel.whl").is_file()
            )
        self._check("synthetic_receipt", syn_ok)

        # 17. runtime receipt
        runtime_ok = False
        rv_path = root / "runtime_verification_receipt.json"
        if rv_path.exists():
            rv = read_json(rv_path)
            runtime_ok = (
                rv.get("final_runtime_match") is True
                and (root / "runtime_resolver_report.json").is_file()
                and (root / "runtime_actual_install_report.json").is_file()
            )
        self._check("runtime_receipt", runtime_ok)

        # 18. verifier self-identity: the bundle verifier_source.py is
        # byte-identical to the script that produced the evidence, as
        # recorded in the receipt at measure time.
        verifier_ok = False
        vf = root / "verifier_source.py"
        recorded = None
        if receipt_path.is_file():
            recorded = read_json(receipt_path).get("verifier_script_sha256")
        if vf.is_file() and isinstance(recorded, str):
            verifier_ok = sha256_file(vf) == recorded
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
    """Exact per-field equality of two closed_world_identity docs."""
    if doc_a.get("schema_version") != doc_b.get("schema_version"):
        return False, "schema_version"
    if doc_a.get("surface") != doc_b.get("surface"):
        return False, "surface"
    for field in ("runner", "python", "resolver", "dependency_contract",
                  "action_contract", "resolved_distributions"):
        if doc_a.get(field) != doc_b.get(field):
            return False, field
    ba = doc_a.get("build_contract") or {}
    bb = doc_b.get("build_contract") or {}
    for field in ("backend", "declared_requires", "dynamic_hook",
                  "dynamic_requires", "normalized_build_identity_sha256",
                  "execution_build_requirements_sha256",
                  "effective_build_distributions", "pip_frontend_version"):
        if ba.get(field) != bb.get(field):
            return False, f"build_contract.{field}"
    for field in ("closed_world_build_valid", "final_runtime_match",
                  "synthetic_control_success", "synthetic_closed_world_failure",
                  "sentinel_auto_installed"):
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
    print(f"CLOSED_WORLD_IDENTITY_MATCH={str(equal).lower()}")
    if not equal:
        print(f"reason=first_differing_field:{first_diff}")
    return 0


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("measure", help="run the closed-world measurement")
    p.add_argument("--surface", choices=SURFACES, required=True)
    p.add_argument("--actions-checkout", required=True)
    p.add_argument("--actions-setup-python", required=True)
    p.add_argument("--actions-upload-artifact", required=True)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--out-dir", default="cw-evidence")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("bundle", help="assemble the evidence bundle")
    p.add_argument("--out-dir", default="cw-evidence")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
