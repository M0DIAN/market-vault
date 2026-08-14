#!/usr/bin/env python3
"""P2-9 PRODUCTION-TOPOLOGY SHADOW SOURCE EVIDENCE — temporary measurement tool.

Source-side measurement for the P2-9 Phase S source evidence setup (this
PR). Shadow / measurement only: nothing here gates production, and no
production step is skipped or altered. The tool produces REAL source
evidence for a future P2-9 Phase T — closing the source-side preconditions
for GAP-P2-8-T0 (source evidence locator / one-generation-back assembly)
and GAP-P2-8-T1 (schema-bound source-head runtime identity) — without
claiming T2/T3.

The artifact class is ``p2_9_source_surface_shadow_v1`` (distinct from the
V1 FULL CI attestation class in scripts/ci_post_merge_reuse.py; the two
class families are kept strictly separated, see class-separation negative
controls below).

Subcommands:
  probe             — full per-surface source measurement: schema-bound
                      runtime identity (runner / python / pip / resolver /
                      resolver-selected distributions / exact runtime sdist
                      / source-build contract / closed-world build env /
                      two cache-disabled closed-world builds / normalized
                      wheel identity / installed payload identity) plus the
                      selected-input contract doc, the normalization
                      contract doc, and the probe summary. The candidate
                      surface (sealed 3.14 surface or audited pyarrow24
                      surface) is executed inside the shadow source-built
                      runtime.
  finalize          — assemble the source evidence bundle: verifier
                      self-copy FIRST, receipt, source evidence doc (the
                      exact 15-key schema), then EVIDENCE_MANIFEST.json
                      LAST. No writes are allowed after the manifest.
  verify-bundle     — offline replay of a bundle. Run the bundle's OWN
                      verifier_source.py copy against that bundle; replay
                      verdicts go to --summary-out (OUTSIDE the bundle).
  verify-retained   — package-job post-upload replay: verifies the artifact
                      name binds exact head / run / attempt / surface,
                      replays the downloaded bundle read-only, and records
                      a separate roundtrip receipt outside the bundle.
                      The downloaded original bundle is never mutated or
                      re-uploaded.
  validate-evidence — validate a source evidence doc against the exact
                      15-key schema (fail-closed).

Closure rule (P2-7 discipline, retained verbatim): FINALIZE -> MANIFEST ->
PRE-UPLOAD REPLAY -> NO FURTHER WRITES -> UPLOAD -> DOWNLOAD RETAINED
ARTIFACT -> POST-UPLOAD REPLAY. The verifier never writes into the bundle
directory. Post-upload replay results live OUTSIDE the manifest-bound
original bundle.

Normalization contract (P2-7 semantics, sealed): two built wheels may
differ ONLY in the ZIP DOS modification timestamps of build-generated
members. Every other raw/container property must be identical (fail-close):
member path sets, ordering, all decompressed member bytes, CRC, file/
compressed sizes, compression method, flag bits, external/internal
attributes, create/extract versions, extra fields, member comments, archive
comment, duplicate paths. "Raw differs but payload same => accept" is NEVER
implemented: an unexplained raw/container difference => INVALID => RUN.

Source evidence schema (exact key set; unknown or missing keys => INVALID):
  schema_version, artifact_class, repository, workflow, run_id,
  run_attempt, pr_number, pr_head_sha, tested_merge_sha, tested_tree_sha,
  surface, probe_source_sha256, selected_input_contract_sha256,
  runtime_identity_sha256, normalization_contract_sha256,
  evidence_manifest_sha256

Tree/run binding: identity is bound to the exact GitHub run (run_id /
run_attempt), PR number, PR head SHA, tested merge checkout SHA and tested
merge tree SHA (git rev-parse <merge-sha>^{tree}) of the run that produced
the evidence. Identity is never inferred from a branch name. On non-PR
runs the tool fails closed: source evidence requires PR context.

Credits: the measurement primitives are ported from the audited historical
P2-7 implementation (commit 614f5a5e38ec61c2883a1504fdcff66fb9fc37cd,
"P2-7 runtime sdist normalized payload identity canary", PR #82) with
regression tests; the P2-7 workflow files are never executed and PR #82 is
never reopened/mutated.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import traceback
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# constants

SCHEMA_VERSION = 1
ARTIFACT_CLASS = "p2_9_source_surface_shadow_v1"
# The exact 15-key source evidence schema (Section 4 of the P2-9 Phase S
# spec). Unknown or missing keys => INVALID. Field ORDER is not identity
# (canonical_serialize sorts keys); the KEY SET is.
SOURCE_EVIDENCE_FIELDS = (
    "schema_version",
    "artifact_class",
    "repository",
    "workflow",
    "run_id",
    "run_attempt",
    "pr_number",
    "pr_head_sha",
    "tested_merge_sha",
    "tested_tree_sha",
    "surface",
    "probe_source_sha256",
    "selected_input_contract_sha256",
    "runtime_identity_sha256",
    "normalization_contract_sha256",
    "evidence_manifest_sha256",
)

SURFACES = ("test-3.14", "pyarrow24")

DOC_RUNTIME = "runtime_sdist_identity.json"
DOC_NORMALIZED = "runtime_sdist_normalized_identity.json"
MANIFEST_NAME = "EVIDENCE_MANIFEST.json"
RECEIPT_NAME = "evidence_receipt.json"
VERIFIER_NAME = "verifier_source.py"
PROBE_NAME = "probe_summary.txt"
SOURCE_EVIDENCE_NAME = "source_evidence.json"
SELECTED_INPUT_CONTRACT_NAME = "selected_input_contract.json"
NORMALIZATION_CONTRACT_NAME = "normalization_contract.json"

# P2-9 action pins (independent: resolved from the frozen base CI logs for
# checkout/setup-python; upload-artifact@v7 = 043fb46d...; the P2-9
# download step uses download-artifact@v8 = 3e5f45b2...). No mutable
# action label is accepted as authoritative evidence for the NEW P2-9
# steps; the existing tag-pinned production steps are recorded verbatim.
ACTION_PINS = {
    "checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
}
P2_9_ARTIFACT_PREFIX = "market-vault-p2-9-source"

PROJECT_NAME = "market-vault"
EXPECTED_REPOSITORY = "M0DIAN/market-vault"
EXPECTED_WORKFLOW = "CI"
RUNTIME_SDIST_EXPECTED = {"moomoo-api"}  # candidate surfaces resolve exactly this sdist
PYARROW24_PIN = "pyarrow==24.0.0"

TARGET_FILE = "tests/test_calendar_v03.py"

# Sealed PR #74 Python 3.14 surface contract (must match
# scripts/ci_python314_surface.py; the contract doc cross-binds that
# validator's source identity at probe time).
PY314_MANIFEST_REL = "ci/python314_compatibility_surface.txt"
PY314_VALIDATOR_REL = "scripts/ci_python314_surface.py"
PY314_EXPECTED_SELECTOR_COUNT = 258
PY314_EXPECTED_WHOLE_FILE_COUNT = 2
PY314_EXPECTED_PARTIAL_SELECTOR_COUNT = 256
PY314_EXPECTED_RESOLVED_NODE_COUNT = 294
PY314_EXPECTED_MANIFEST_SHA256 = (
    "2742853e8e997af8d32d43d6481bdb3f3b7d61df69ab9c2ab6bcdb9219cb5a7a"
)
PY314_EXPECTED_RESOLVED_SHA256 = (
    "7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58"
)

# The audited PyArrow 24 surface: the literal ten-file list executed by the
# portability-pyarrow24 job (A: portability; B: canonical reader + frozen
# regression; C: sensitive regression). Pinned by scripts/check_release.py.
PYARROW24_SURFACE_FILES = (
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
)

# Mandatory conservative invalidators (P2-8 binding): any change to these
# paths, or any changed path outside the selected-input allowlist
# (selectors.files), invalidates the selected-input contract. This list
# covers src/**, pyproject.toml, the relevant CI/control-plane inputs
# (mirroring the classifier's control-plane scope), the 3.14 surface
# machinery, and the repo-wide conftest patterns. Sorted for determinism.
INVALIDATOR_GLOB_PATTERNS = [
    ".github/workflows/**",
    "ci/components.toml",
    "ci/python314_compatibility_surface.txt",
    "conftest.py",
    "pyproject.toml",
    "scripts/audit_pr.py",
    "scripts/check_release.py",
    "scripts/ci_post_merge_reuse.py",
    "scripts/ci_python314_surface.py",
    "scripts/ci_risk_tier.py",
    "src/**",
    "tests/conftest.py",
    "tests/test_audit_pr.py",
    "tests/test_ci_post_merge_reuse.py",
    "tests/test_ci_risk_tier.py",
    "tests/test_component_aware_tiers.py",
    "tests/test_python314_compatibility_surface.py",
    "tests/test_v061_ci_auditability.py",
]

# Top-level dirs never bound into the evidence bundle (venvs / scratch /
# remainder downloads are reconstruction inputs, not evidence).
BUNDLE_EXCLUDED_TOPS = {"venvs", "sdist_extract_1", "sdist_extract_2", "remainder_wheelhouse"}

# ---------------------------------------------------------------------------
# canonicalization + hashing (port of the audited P2-7 primitives)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def record_sha256(b: bytes) -> str:
    """PEP 376 RECORD hash value: 'sha256=' + urlsafe base64, unpadded
    (the encoding setuptools/wheel/pip write into RECORD)."""
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(b).digest()).decode().rstrip("=")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonicalize_name(name: str) -> str:
    # PEP 503 canonicalization (importlib.metadata.canonicalize_name is
    # absent on pythoncore 3.14, so inline).
    return re.sub(r"[-_.]+", "-", name).lower()


def _norm(v):
    """Recursive key sorting ONLY (emits plain dicts; sort_keys=True keeps
    the serialization deterministic). Lists are NEVER reordered — any
    order-sensitive list must be explicitly sorted by the caller before
    serialization (ordering is identity-bearing data)."""
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    return v


def canonical_serialize(obj) -> str:
    """Deterministic canonical JSON: recursive key sorting, compact
    separators, newline-terminated. List order is preserved verbatim."""
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":")) + "\n"


def normalize_url(url: str) -> str | None:
    """Normalize a download URL: http(s) only, no credentials, no query.
    Returns None for non-index (local/editable) URLs."""
    import urllib.parse

    if not url:
        return None
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https"):
        return None
    if u.username or u.password:
        raise ValueError("url_credentials")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def b64sha256(b: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b"=").decode()


def run(
    cmd,
    cwd=None,
    env=None,
    log_path=None,
    check=True,
    timeout=1800,
):
    """Run a subprocess; optionally tee to a log file; return (rc, stdout)."""
    full_env = os.environ.copy()
    full_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    if env:
        full_env.update(env)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    combined = proc.stdout + proc.stderr
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(combined, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{combined[-4000:]}")
    return proc.returncode, combined


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ---------------------------------------------------------------------------
# wheel inventory + RECORD validation (port of the audited P2-7 primitives)


class WheelMember:
    __slots__ = (
        "path", "content", "sha256", "size", "compress_size", "crc",
        "compress_type", "flag_bits", "external_attr", "internal_attr",
        "create_system", "create_version", "extract_version", "extra",
        "comment", "date_time", "header_offset",
    )

    def __init__(self, zinfo: zipfile.ZipInfo, content: bytes):
        self.path = zinfo.filename
        self.content = content
        self.sha256 = sha256_bytes(content)
        self.size = zinfo.file_size
        self.compress_size = zinfo.compress_size
        self.crc = zinfo.CRC
        self.compress_type = zinfo.compress_type
        self.flag_bits = zinfo.flag_bits
        self.external_attr = zinfo.external_attr
        self.internal_attr = zinfo.internal_attr
        self.create_system = zinfo.create_system
        self.create_version = zinfo.create_version
        self.extract_version = zinfo.extract_version
        self.extra = zinfo.extra
        self.comment = zinfo.comment
        self.date_time = tuple(zinfo.date_time)
        self.header_offset = zinfo.header_offset

    def non_time_identity(self) -> tuple:
        return (
            self.path, self.sha256, self.size, self.compress_size, self.crc,
            self.compress_type, self.flag_bits, self.external_attr,
            self.internal_attr, self.create_system, self.create_version,
            self.extract_version, self.extra, self.comment,
        )


class WheelInventory:
    def __init__(self, members, record_path, errors, dist_info_dir, filename_info, archive_comment,
                 all_header_offsets):
        self.members = members  # file members only, archive order
        self.record_path = record_path
        self.errors = errors
        self.dist_info_dir = dist_info_dir
        self.filename_info = filename_info
        self.archive_comment = archive_comment
        # header offsets of EVERY entry (incl. directory entries), so the
        # raw-diff attribution covers directory-entry timestamp slots too
        self.all_header_offsets = all_header_offsets

    @property
    def record_valid(self) -> bool:
        return not self.errors

    @property
    def structural_valid(self) -> bool:
        return self.filename_info is not None and self.dist_info_dir is not None


WHEEL_FILENAME_RE = re.compile(
    r"^(?P<name>.+?)-(?P<version>.+?)-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl$"
)


def parse_wheel_filename(path: Path):
    m = WHEEL_FILENAME_RE.match(path.name)
    if not m:
        return None
    return {
        "filename": path.name,
        "name": m.group("name"),
        "version": m.group("version"),
        "python_tag": m.group("python"),
        "abi_tag": m.group("abi"),
        "platform_tag": m.group("platform"),
    }


def inventory_wheel(path: Path) -> WheelInventory:
    errors = []
    with zipfile.ZipFile(path) as zf:
        archive_comment = zf.comment
        infos = zf.infolist()
        seen = {}
        members = []
        all_header_offsets = []
        for zinfo in infos:
            all_header_offsets.append(zinfo.header_offset)
            if zinfo.is_dir():
                continue
            if zinfo.filename in seen:
                errors.append(f"duplicate_path:{zinfo.filename}")
                continue
            seen[zinfo.filename] = True
            content = zf.read(zinfo)  # CRC verified by zipfile on read
            if len(content) != zinfo.file_size:
                errors.append(f"size_mismatch:{zinfo.filename}")
            members.append(WheelMember(zinfo, content))

    dist_info_dirs = {p.split("/", 1)[0] for p in seen if ".dist-info" in p.split("/", 1)[0]}
    dist_info_dir = None
    if len(dist_info_dirs) == 1:
        dist_info_dir = next(iter(dist_info_dirs))
    else:
        errors.append(f"dist_info_dir_count:{len(dist_info_dirs)}")

    record_path = None
    if dist_info_dir:
        record_path = f"{dist_info_dir}/RECORD"
        for required in ("METADATA", "WHEEL", "RECORD"):
            if f"{dist_info_dir}/{required}" not in seen:
                errors.append(f"missing_dist_info_file:{required}")

    finfo = parse_wheel_filename(path)
    if finfo is None:
        errors.append("wheel_filename_malformed")

    if record_path is not None:
        validate_record(members, record_path, errors)

    return WheelInventory(members, record_path, errors, dist_info_dir, finfo, archive_comment,
                          all_header_offsets)


def validate_record(members, record_path, errors) -> None:
    record_members = [m for m in members if m.path == record_path]
    if not record_members:
        errors.append("record_missing")
        return
    if members[-1].path != record_path:
        errors.append("record_not_last")
    record = record_members[0]
    lines = record.content.decode("utf-8").splitlines()
    listed = {}
    for ln in lines:
        parts = ln.split(",")
        if len(parts) != 3:
            errors.append("record_line_malformed")
            continue
        rpath, rhash, rsize = parts
        if rpath in listed:
            errors.append(f"record_duplicate:{rpath}")
        listed[rpath] = (rhash, rsize)

    self_ok = False
    member_paths = {m.path for m in members}
    for m in members:
        if m.path == record_path:
            rhash, rsize = listed.get(m.path, (None, None))
            if rhash != "" or rsize != "":
                errors.append("record_self_entry_not_empty")
            else:
                self_ok = True
            continue
        if m.path not in listed:
            errors.append(f"record_missing_entry:{m.path}")
            continue
        rhash, rsize = listed[m.path]
        if rhash != record_sha256(m.content):
            errors.append(f"record_hash_mismatch:{m.path}")
        if rsize != str(m.size):
            errors.append(f"record_size_mismatch:{m.path}")

    for rpath in listed:
        if rpath != record_path and rpath not in member_paths:
            errors.append(f"record_extra_entry:{rpath}")
    if not self_ok:
        errors.append("record_self_entry_missing")


def payload_digest_from_entries(entries, record_rel: str | None):
    """Canonical digest over [[relpath, sha256, size], ...] entries, sorted
    by path; the RECORD entry is excluded. Shared by wheel payload identity
    and installed payload identity so both compare equal when the installed
    files match the wheel members."""
    entries = sorted((e for e in entries if e[0] != record_rel), key=lambda e: e[0])
    return sha256_bytes(canonical_serialize(entries).encode()), len(entries)


def payload_sha256(members, record_path: str | None):
    """WHEEL_PAYLOAD_SHA256: canonical sorted (relative path, member SHA256,
    size), excluding the wheel's own RECORD."""
    return payload_digest_from_entries([[m.path, m.sha256, m.size] for m in members], record_path)


def installed_payload_sha256(tree_root: Path):
    """Digest over an installed tree: excludes RECORD, INSTALLER, REQUESTED,
    direct_url.json, *.pyc, __pycache__ (the pip-generated files never part
    of a wheel payload)."""
    entries = []
    for p in sorted(tree_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(tree_root).as_posix()
        if rel.endswith(".pyc") or "__pycache__" in rel:
            continue
        base = Path(rel).name
        if base in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json"):
            continue
        entries.append([rel, sha256_file(p), p.stat().st_size])
    return payload_digest_from_entries(entries, None)


# ---------------------------------------------------------------------------
# ZIP container comparison (the normalization contract; audited P2-7 port)


def _eocd(raw: bytes):
    for i in range(len(raw) - 22, max(-1, len(raw) - 22 - 65557), -1):
        if raw[i : i + 4] == b"PK\x05\x06":
            cd_size = int.from_bytes(raw[i + 12 : i + 16], "little")
            cd_offset = int.from_bytes(raw[i + 16 : i + 20], "little")
            return cd_offset, cd_size
    raise ValueError("EOCD not found")


def _walk_cd(raw: bytes, cd_offset: int, cd_size: int):
    pos = cd_offset
    end = cd_offset + cd_size
    while pos < end:
        if raw[pos : pos + 4] != b"PK\x01\x02":
            raise ValueError("bad central-directory signature")
        nlen = int.from_bytes(raw[pos + 28 : pos + 30], "little")
        elen = int.from_bytes(raw[pos + 30 : pos + 32], "little")
        clen = int.from_bytes(raw[pos + 32 : pos + 34], "little")
        yield pos
        pos += 46 + nlen + elen + clen


def _cd_name(raw: bytes, pos: int, flag_bits: int) -> str:
    nlen = int.from_bytes(raw[pos + 28 : pos + 30], "little")
    name_b = raw[pos + 46 : pos + 46 + nlen]
    if flag_bits & 0x800:
        return name_b.decode("utf-8", errors="replace")
    return name_b.decode("cp437", errors="replace")


def timestamp_slots(raw: bytes, inv: WheelInventory):
    """(start, end) byte ranges of every DOS timestamp field (4 bytes at
    +10) in the raw archive: local headers and central-directory entries."""
    slots = []
    for off in inv.all_header_offsets:
        slots.append((off + 10, off + 14))
    cd_offset, cd_size = _eocd(raw)
    for cd_pos in _walk_cd(raw, cd_offset, cd_size):
        # central-directory header layout differs from the local header:
        # sig(4) made-by(2) needed(2) flags(2) method(2) time(2) date(2)
        # -> DOS time at +12, DOS date at +14
        slots.append((cd_pos + 12, cd_pos + 16))
    return slots


def compare_wheels(inv1: WheelInventory, inv2: WheelInventory) -> dict:
    """Per-member comparison. Returns the full comparison record; the caller
    derives the normalization verdict. Fail-close on EVERY non-timestamp
    property."""
    paths1 = [m.path for m in inv1.members]
    paths2 = [m.path for m in inv2.members]
    result = {
        "path_sets_identical": set(paths1) == set(paths2),
        "member_ordering_identical": paths1 == paths2,
        "archive_comment_equal": inv1.archive_comment == inv2.archive_comment,
        "duplicate_paths_1": sorted({p for p in paths1 if paths1.count(p) > 1}),
        "duplicate_paths_2": sorted({p for p in paths2 if paths2.count(p) > 1}),
        "member_count": (len(paths1), len(paths2)),
    }
    by_name2 = {}
    for m in inv2.members:
        by_name2.setdefault(m.path, m)
    content_ok = True
    non_time_ok = True
    time_diffs = []
    content_diffs = []
    for m1 in inv1.members:
        m2 = by_name2.get(m1.path)
        if m2 is None:
            content_ok = False
            continue
        if m1.content != m2.content:
            content_ok = False
            content_diffs.append(m1.path)
        if m1.non_time_identity() != m2.non_time_identity():
            non_time_ok = False
        if m1.date_time != m2.date_time:
            time_diffs.append({"path": m1.path, "date_time_1": list(m1.date_time),
                               "date_time_2": list(m2.date_time)})
    result["all_member_contents_identical"] = content_ok
    result["content_diff_members"] = content_diffs
    result["non_timestamp_zipinfo_identical"] = non_time_ok
    result["timestamp_diffs"] = time_diffs
    result["record_valid_1"] = inv1.record_valid
    result["record_valid_2"] = inv2.record_valid
    result["structural_valid_1"] = inv1.structural_valid
    result["structural_valid_2"] = inv2.structural_valid
    payload1, count1 = payload_sha256(inv1.members, inv1.record_path)
    payload2, count2 = payload_sha256(inv2.members, inv2.record_path)
    result["payload_sha256_1"] = payload1
    result["payload_sha256_2"] = payload2
    result["payload_entry_count"] = (count1, count2)
    result["wheel_payload_match"] = payload1 == payload2
    return result


def classify_raw_mismatch(raw1: bytes, raw2: bytes, inv1: WheelInventory, inv2: WheelInventory, cmp_result: dict) -> dict:
    """Prove that every raw byte difference is a ZIP DOS timestamp field.
    Any unexplained difference => normalization INVALID."""
    result = {"raw_equal": raw1 == raw2}
    if len(raw1) != len(raw2):
        result["verdict"] = False
        result["reason"] = "raw_length_unequal"
        result["diff_byte_count"] = None
        return result

    diffs = [i for i in range(len(raw1)) if raw1[i] != raw2[i]]
    result["diff_byte_count"] = len(diffs)
    if not diffs:
        result["verdict"] = False
        result["reason"] = "raw_equal"
        result["attribution"] = {"local_or_central_timestamp": 0, "unclassified": 0}
        return result

    slots = timestamp_slots(raw1, inv1)
    attribution = {"local_or_central_timestamp": 0, "unclassified": 0}
    unclassified = []
    for i in diffs:
        if any(s <= i < e for s, e in slots):
            attribution["local_or_central_timestamp"] += 1
        else:
            attribution["unclassified"] += 1
            unclassified.append(i)
    result["attribution"] = attribution
    result["first_differing_offset"] = diffs[0]
    result["first_differing_offset_in_timestamp_slot"] = any(s <= diffs[0] < e for s, e in slots)
    result["unclassified_offsets"] = unclassified[:20]

    contract_ok = (
        cmp_result["path_sets_identical"]
        and cmp_result["member_ordering_identical"]
        and cmp_result["archive_comment_equal"]
        and not cmp_result["duplicate_paths_1"]
        and not cmp_result["duplicate_paths_2"]
        and cmp_result["all_member_contents_identical"]
        and cmp_result["non_timestamp_zipinfo_identical"]
        and cmp_result["record_valid_1"]
        and cmp_result["record_valid_2"]
        and cmp_result["structural_valid_1"]
        and cmp_result["structural_valid_2"]
    )
    if attribution["unclassified"] == 0 and contract_ok:
        result["verdict"] = True
        result["reason"] = "timestamp_only_contract_ok"
    else:
        result["verdict"] = False
        if attribution["unclassified"]:
            result["reason"] = "unclassified_raw_difference"
        elif not cmp_result["all_member_contents_identical"]:
            result["reason"] = "member_content_difference"
        elif not cmp_result["non_timestamp_zipinfo_identical"]:
            result["reason"] = "non_timestamp_zipinfo_difference"
        elif not cmp_result["path_sets_identical"] or not cmp_result["member_ordering_identical"]:
            result["reason"] = "member_set_or_ordering_difference"
        elif not cmp_result["record_valid_1"] or not cmp_result["record_valid_2"]:
            result["reason"] = "record_invalid"
        elif not cmp_result["archive_comment_equal"]:
            result["reason"] = "archive_comment_difference"
        else:
            result["reason"] = "archive_metadata_difference"
    return result


def patch_zip_timestamps(raw: bytes, inv: WheelInventory, member_names, new_time: int) -> bytes:
    """Byte-level timestamp patch (positive control): replace the 2-byte DOS
    TIME field in the local header and central-directory entry of each named
    member. Everything else stays bit-identical."""
    out = bytearray(raw)
    wanted = set(member_names)
    for m in inv.members:
        if m.path in wanted:
            # local header: time at +10 (2 bytes)
            out[m.header_offset + 10 : m.header_offset + 12] = new_time.to_bytes(2, "little")
    for cd_pos in _walk_cd(raw, *_eocd(raw)):
        flag_bits = int.from_bytes(raw[cd_pos + 8 : cd_pos + 10], "little")
        name = _cd_name(raw, cd_pos, flag_bits)
        if name in wanted:
            # central directory: time at +12 (2 bytes); date stays
            out[cd_pos + 12 : cd_pos + 14] = new_time.to_bytes(2, "little")
    return bytes(out)


def rebuild_wheel_mutated(raw: bytes, inv: WheelInventory, out_path: Path, fix_record: bool) -> str:
    """Negative-control wheel: recompress the archive with one payload byte
    of the first non-dist-info member flipped. ZipInfo metadata (timestamps,
    attrs, extra, flags) is preserved member-for-member. With fix_record the
    RECORD hashes are recomputed for the mutated content (the strongest
    negative: valid-looking RECORD but different payload). Returns the
    mutated member path."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        infos = zf.infolist()
        contents = {}
        for zinfo in infos:
            if zinfo.is_dir():
                continue
            contents[zinfo.filename] = zf.read(zinfo)
    member_names = [m.path for m in inv.members if m.path.split("/", 1)[0] != inv.dist_info_dir]
    mutated = member_names[0]
    contents[mutated] = bytes([contents[mutated][0] ^ 0x01]) + contents[mutated][1:]

    if fix_record:
        record_path = f"{inv.dist_info_dir}/RECORD"
        # recompute over EVERY file member (module + dist-info files),
        # excluding the RECORD itself
        lines = []
        for m in inv.members:
            if m.path == record_path:
                continue
            c = contents[m.path]
            lines.append(f"{m.path},{record_sha256(c)},{len(c)}")
        record_content = ("\n".join(sorted(lines)) + f"\n{record_path},,\n").encode()
        contents[record_path] = record_content

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for m in inv.members:
            zi = zipfile.ZipInfo(m.path, date_time=m.date_time)
            zi.compress_type = m.compress_type
            zi.external_attr = m.external_attr
            zi.internal_attr = m.internal_attr
            zi.create_system = m.create_system
            zi.create_version = m.create_version
            zi.extract_version = m.extract_version
            zi.comment = m.comment
            zi.extra = m.extra
            # note: zipfile.writestr always resets flag_bits (0x800 is
            # re-applied only for non-ASCII names); the mutated wheel is a
            # negative control, so this cosmetic difference is irrelevant
            zout.writestr(zi, contents[m.path])
    return mutated


# ---------------------------------------------------------------------------
# identity blocks (audited P2-7 ports)


def runner_block() -> dict:
    required = {"RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion"}
    env = {k: os.environ.get(k) for k in required}
    missing = sorted(k for k, v in env.items() if not v)
    if missing:
        # local measurement only — never authoritative; documented as such
        return {
            "local": True,
            "run_os": None, "run_arch": None, "image_os": None, "image_version": None,
            "sys_platform": sys.platform, "machine": platform.machine(),
            "release": platform.release(), "libc_ver": list(platform.libc_ver()),
        }
    return {
        "run_os": env["RUNNER_OS"], "run_arch": env["RUNNER_ARCH"],
        "image_os": env["ImageOS"], "image_version": env["ImageVersion"],
        "sys_platform": sys.platform, "machine": platform.machine(),
        "release": platform.release(), "libc_ver": list(platform.libc_ver()),
    }


def python_block() -> dict:
    v = platform.python_version_tuple()
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "major": int(v[0]),
        "minor": int(v[1]),
        "micro": int(v[2]),
        "cache_tag": sys.implementation.cache_tag,
        "soabi": getattr(getattr(sys.implementation, "_multiarch", None), "value", None)
        if hasattr(sys.implementation, "_multiarch") else None,
        "pointer_width": str(64 if sys.maxsize > 2**32 else 32),
    }


def pip_version(venv: Path) -> str:
    rc, out = run([str(venv_python(venv)), "-m", "pip", "--version"], check=False)
    if rc != 0:
        raise RuntimeError("pip version probe failed")
    m = re.search(r"pip (\S+)", out.splitlines()[0])
    return m.group(1) if m else "unknown"


def dependency_contract(repo: Path) -> dict:
    pyproject = repo / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})

    def names(lst):
        out = []
        for d in lst:
            m = re.match(r"^([A-Za-z0-9_.-]+)", d)
            if m:
                out.append(canonicalize_name(m.group(1)))
        return sorted(out)

    return {
        "project": project.get("name"),
        "version": project.get("version"),
        "pyproject_sha256": sha256_file(pyproject),
        "requires_python": project.get("requires-python"),
        "dependencies": names(project.get("dependencies", [])),
        "dev_dependencies": names(project.get("optional-dependencies", {}).get("dev", [])),
    }


def action_contract(repo: Path) -> dict:
    """Bind the workflow's action usage. The existing production steps keep
    their tag pins (recorded verbatim, not authoritative); the NEW P2-9
    upload/download steps must use the exact full-SHA pins (fail-closed),
    and the P2-9 artifact names must bind exact head / run_attempt /
    surface (the template the workflow uses)."""
    ci = repo / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")

    usage = {}
    for name, sha in ACTION_PINS.items():
        marker = f"actions/{name}@"
        refs = sorted({ln.strip() for ln in text.splitlines() if marker in ln})
        usage[name] = refs
        if sha not in text:
            if name in ("upload-artifact", "download-artifact"):
                # the P2-9 steps must carry the exact pin; the existing
                # package steps may keep their tag pins
                if f"actions/{name}@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" not in text and \
                        f"actions/{name}@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" not in text:
                    raise RuntimeError(f"action_pin_not_exact:{name}")
            else:
                raise RuntimeError(f"action_pin_not_exact:{name}")

    # P2-9 artifact-name template: the upload steps must bind exact
    # head / run_attempt / surface in the artifact name.
    for surface in SURFACES:
        template = (
            f"{P2_9_ARTIFACT_PREFIX}-{surface}-"
            "${{ github.event.pull_request.head.sha }}-attempt-${{ github.run_attempt }}"
        )
        if template not in text:
            raise RuntimeError(f"p2_9_artifact_name_template_missing:{surface}")

    return {
        "action_usage": usage,
        "p2_9_upload_pin": ACTION_PINS["upload-artifact"],
        "p2_9_download_pin": ACTION_PINS["download-artifact"],
        "artifact_name_template": f"{P2_9_ARTIFACT_PREFIX}-<surface>-<head_sha>-attempt-<run_attempt>",
        "ci_yml_sha256": sha256_file(ci),
    }


def report_distributions(report_path: Path) -> list:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    out = []
    for item in data.get("install", []):
        meta = item.get("metadata", {})
        dl = item.get("download_info", {}) or {}
        info = dl.get("archive_info", {}) or {}
        hashes = info.get("hashes", {}) or {}
        name = canonicalize_name(meta.get("name", ""))
        if not name or not meta.get("version"):
            raise RuntimeError("report_distribution_malformed")
        url = dl.get("url", "") or ""
        norm = normalize_url(url)
        out.append(
            {
                "canonical_name": name,
                "version": meta["version"],
                "url": norm,
                "sha256": hashes.get("sha256", ""),
                "is_sdist": url.endswith(".tar.gz") or url.endswith(".zip"),
                "is_local": norm is None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# venv-side installed-payload enumeration (must run INSIDE the target venv;
# audited P2-7 port)


INSTALLED_ENTRIES_SOURCE = r"""
import hashlib, importlib.metadata, json, shutil, sys
from pathlib import Path

name = sys.argv[1]
out_json = Path(sys.argv[2])
copy_to = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None

d = importlib.metadata.distribution(name)
files = d.files or []
entries = []
record_rel = None
for f in files:
    n = f.as_posix()
    if f.name in ('INSTALLER', 'REQUESTED', 'direct_url.json') or n.endswith('.pyc'):
        continue
    if f.name == 'RECORD':
        record_rel = n
    p = Path(d.locate_file(f))
    if not p.is_file():
        continue
    entries.append([n, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size])
    if copy_to is not None:
        dst = copy_to / n
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
entries.sort(key=lambda e: e[0])
json.dump({'entries': entries, 'record_rel': record_rel}, open(out_json, 'w'), sort_keys=True)
"""


def installed_entries(venv: Path, name: str, out_json: Path, copy_to: Path | None = None) -> tuple:
    """Enumerate an installed distribution's payload (path, sha256, size)
    INSIDE the target venv. Optionally copies the payload files (incl.
    RECORD) into copy_to. Returns (entries, record_rel)."""
    args = [str(venv_python(venv)), "-c", INSTALLED_ENTRIES_SOURCE, name, str(out_json)]
    if copy_to is not None:
        args.append(str(copy_to))
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    rc, out = run(args, env=env, check=False)
    if rc != 0:
        raise RuntimeError(f"installed_entries failed for {name}: {out[-1000:]}")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    return data["entries"], data["record_rel"]


def installed_payload_digest(venv: Path, name: str) -> str:
    """Current live installed-payload digest inside a venv (survival checks)."""
    tmp = Path(tempfile.mkdtemp(prefix="mv_p2_9_"))
    try:
        entries, record_rel = installed_entries(venv, name, tmp / "entries.json")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    digest, _ = payload_digest_from_entries(entries, record_rel)
    return digest


def _final_runtime_inventory(venv: Path) -> dict:
    code = (
        "import importlib.metadata, re, json\n"
        "d = {}\n"
        "for x in importlib.metadata.distributions():\n"
        "    try: d[re.sub(r'[-_.]+', '-', x.metadata['Name'] or '').lower()] = x.version\n"
        "    except Exception: pass\n"
        "print(json.dumps(d, sort_keys=True))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    rc, out = run([str(venv_python(venv)), "-c", code], env=env, check=False)
    if rc != 0:
        raise RuntimeError("final_runtime_inventory failed")
    return json.loads(out.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# evaluation (pure, unit-tested; P2-7 semantics: any unexplained raw/
# container difference => INVALID)


def evaluate_verdict(summary: dict) -> dict:
    """Derive the normalized-install-artifact identity verdict from the raw
    probe markers. Any unexplained raw/container difference => INVALID."""
    raw_reproducible = summary.get("RAW_WHEEL_REPRODUCIBLE_moomoo-api") == "true"
    payload_match = summary.get("WHEEL_PAYLOAD_MATCH_moomoo-api") == "true"
    normalization_valid = summary.get("RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api") == "true"
    installed_match = summary.get("INSTALLED_PAYLOAD_MATCH") == "true"
    sdist_ok = summary.get("SOURCE_SDIST_HASH_OK") == "true"
    env_ok = bool(summary.get("SOURCE_BUILD_ENVIRONMENT_SHA256"))
    runtime_match = summary.get("FINAL_RUNTIME_MATCH") == "true"
    wheels_only = summary.get("RUNTIME_INSTALL_FROM_WHEELS_ONLY") == "true"
    surface_pass = summary.get("SHADOW_SURFACE_PASS") == "true"
    no_crash = summary.get("MEASURE_CRASH") == "false"
    record_ok = summary.get("RECORD_VALID_1") == "true" and summary.get("RECORD_VALID_2") == "true"
    inst_record_ok = summary.get("INSTALLED_RECORD_VALID") == "true"
    wheel_ok = summary.get("WHEEL_VALIDATION_1") == "true" and summary.get("WHEEL_VALIDATION_2") == "true"

    if not raw_reproducible and not normalization_valid:
        normalized_install_artifact_identity_valid = False
        reason = "raw_mismatch_not_normalized"
    else:
        normalized_install_artifact_identity_valid = (
            payload_match and installed_match and sdist_ok and env_ok
            and runtime_match and wheels_only and surface_pass and no_crash
            and record_ok and inst_record_ok and wheel_ok
        )
        reason = "ok" if normalized_install_artifact_identity_valid else "component_false"

    return {
        "raw_wheel_reproducible": raw_reproducible,
        "wheel_payload_match": payload_match,
        "raw_mismatch_normalization_valid": normalization_valid,
        "installed_payload_match": installed_match,
        "normalized_install_artifact_identity_valid": normalized_install_artifact_identity_valid,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# source-side surface contracts (selected-input contract)

_WHOLE_FILE_SELECTOR_RE = re.compile(r"^tests/[A-Za-z0-9_/.\-]+\.py$")
_NODE_SELECTOR_RE = re.compile(r"^tests/[A-Za-z0-9_/.\-]+\.py::test_[A-Za-z0-9_]+$")
_GLOB_RE = re.compile(r"[*?\[\]]")
_FLAG_RE = re.compile(r"(\s-k\b|\s-m\b)")
_FLAG_PREFIX = ("-k", "-m", "--ignore", "--deselect", "--collect-only")


def validate_py314_manifest_static(repo: Path) -> list:
    """Static validation of the sealed 3.14 selector manifest (port of the
    static half of scripts/ci_python314_surface.py). Returns failure
    messages; empty list means the static contract is fully satisfied."""
    failures = []
    manifest_path = repo / PY314_MANIFEST_REL
    if not manifest_path.is_file():
        return [f"manifest not found: {manifest_path}"]
    if manifest_path.is_symlink():
        return [f"manifest must not be a symlink: {manifest_path}"]
    data = manifest_path.read_bytes()
    if not data:
        return ["manifest is empty"]

    text = data.replace(b"\r\n", b"\n")
    if b"\r" in text:
        return ["manifest contains a lone CR byte"]
    try:
        text = text.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"manifest is not valid UTF-8: {exc}"]

    if not text.endswith("\n"):
        return ["manifest must end with exactly one trailing LF"]
    if text.endswith("\n\n"):
        return ["manifest has a trailing blank line"]
    lines = text[:-1].split("\n")

    for index, line in enumerate(lines, start=1):
        if not line:
            failures.append(f"line {index}: blank selector")
            continue
        if line != line.strip():
            failures.append(f"line {index}: leading or trailing whitespace")
            continue
        if _GLOB_RE.search(line):
            failures.append(f"line {index}: glob pattern is not allowed: {line!r}")
            continue
        if line.startswith(_FLAG_PREFIX) or _FLAG_RE.search(line):
            failures.append(f"line {index}: pytest flag is not allowed: {line!r}")
            continue
        if not (_WHOLE_FILE_SELECTOR_RE.fullmatch(line) or _NODE_SELECTOR_RE.fullmatch(line)):
            failures.append(f"line {index}: invalid selector syntax: {line!r}")

    if failures:
        return failures

    whole_files = [ln for ln in lines if _WHOLE_FILE_SELECTOR_RE.fullmatch(ln)]
    node_selectors = [ln for ln in lines if _NODE_SELECTOR_RE.fullmatch(ln)]
    if len(lines) != PY314_EXPECTED_SELECTOR_COUNT:
        failures.append(
            f"expected {PY314_EXPECTED_SELECTOR_COUNT} selectors, found {len(lines)}"
        )
    if len(whole_files) != PY314_EXPECTED_WHOLE_FILE_COUNT:
        failures.append(
            f"expected {PY314_EXPECTED_WHOLE_FILE_COUNT} whole-file selectors, "
            f"found {len(whole_files)}"
        )
    if len(node_selectors) != PY314_EXPECTED_PARTIAL_SELECTOR_COUNT:
        failures.append(
            f"expected {PY314_EXPECTED_PARTIAL_SELECTOR_COUNT} node selectors, "
            f"found {len(node_selectors)}"
        )
    if lines != sorted(lines):
        failures.append("manifest is not lexicographically sorted")
    if len(set(lines)) != len(lines):
        failures.append("manifest contains duplicate selectors")
    for selector in node_selectors:
        if selector.split("::", 1)[0] in whole_files:
            failures.append(
                f"node selector {selector!r} overlaps whole-file selector "
                f"{selector.split('::', 1)[0]!r}"
            )
    actual_hash = sha256_bytes((text).encode("utf-8"))
    if actual_hash != PY314_EXPECTED_MANIFEST_SHA256:
        failures.append(
            "manifest normalized SHA-256 mismatch: "
            f"expected {PY314_EXPECTED_MANIFEST_SHA256}, computed {actual_hash}"
        )
    return failures


def selected_input_file_set(surface: str) -> list:
    if surface == "pyarrow24":
        return sorted(PYARROW24_SURFACE_FILES)
    raise ValueError(f"file set not static for surface {surface}")


def compute_selected_input_contract(repo: Path, surface: str) -> dict:
    """Compute (and validate) the schema-bound selected-input contract for a
    candidate surface. Fail-closed: any deviation from the sealed constants
    raises. The returned doc's sha256 is selected_input_contract_sha256."""
    if surface not in SURFACES:
        raise ValueError(f"unknown surface: {surface}")

    if surface == "test-3.14":
        failures = validate_py314_manifest_static(repo)
        if failures:
            raise RuntimeError("py314_manifest_invalid:" + ";".join(failures[:5]))
        manifest_path = repo / PY314_MANIFEST_REL
        text = manifest_path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        lines = text[:-1].split("\n")
        files = sorted({ln.split("::", 1)[0] for ln in lines})
        if len(files) != 37:
            raise RuntimeError(f"py314_file_count_expected_37_found_{len(files)}")

        validator_path = repo / PY314_VALIDATOR_REL
        if not validator_path.is_file():
            raise RuntimeError(f"validator script not found: {validator_path}")
        validator_text = validator_path.read_text(encoding="utf-8")
        validator_sha = sha256_bytes(validator_text.encode("utf-8"))
        # cross-bind the sealed resolved contract constants: they must still
        # appear verbatim in the validator source (a drift fails closed).
        for needle in (
            f"EXPECTED_SELECTOR_COUNT = {PY314_EXPECTED_SELECTOR_COUNT}",
            f"EXPECTED_WHOLE_FILE_COUNT = {PY314_EXPECTED_WHOLE_FILE_COUNT}",
            f"EXPECTED_PARTIAL_SELECTOR_COUNT = {PY314_EXPECTED_PARTIAL_SELECTOR_COUNT}",
            f"EXPECTED_RESOLVED_NODE_COUNT = {PY314_EXPECTED_RESOLVED_NODE_COUNT}",
            f'"{PY314_EXPECTED_MANIFEST_SHA256}"',
            f'"{PY314_EXPECTED_RESOLVED_SHA256}"',
        ):
            if needle not in validator_text:
                raise RuntimeError(f"validator_contract_constant_drift:{needle}")

        selectors = {
            "kind": "pytest_node_selector_manifest",
            "manifest_rel": PY314_MANIFEST_REL,
            "manifest_sha256": PY314_EXPECTED_MANIFEST_SHA256,
            "selector_count": PY314_EXPECTED_SELECTOR_COUNT,
            "whole_file_count": PY314_EXPECTED_WHOLE_FILE_COUNT,
            "node_selector_count": PY314_EXPECTED_PARTIAL_SELECTOR_COUNT,
            "resolved_node_count": PY314_EXPECTED_RESOLVED_NODE_COUNT,
            "resolved_sha256": PY314_EXPECTED_RESOLVED_SHA256,
            "file_count": len(files),
            "files": files,
            "validator_script_rel": PY314_VALIDATOR_REL,
            "validator_script_sha256": validator_sha,
        }
        file_set = files
    else:
        selectors = {
            "kind": "literal_file_list",
            "file_count": len(PYARROW24_SURFACE_FILES),
            "files": sorted(PYARROW24_SURFACE_FILES),
            "source": ".github/workflows/ci.yml portability-pyarrow24 surface "
                      "(pinned by scripts/check_release.py)",
        }
        file_set = sorted(PYARROW24_SURFACE_FILES)

    ci = repo / ".github" / "workflows" / "ci.yml"
    contract = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "selected_input_contract",
        "surface": surface,
        "selectors": selectors,
        "change_classification": {
            "selected_inputs": "selectors.files (the exact schema-bound surface)",
            "invalidators": INVALIDATOR_GLOB_PATTERNS,
            "unknown_paths": "INVALIDATE (conservative)",
        },
        "target_relation": {
            "target_file": TARGET_FILE,
            "selected_by_this_surface": TARGET_FILE in file_set,
        },
        "workflow_identity": {"ci_yml_sha256": sha256_file(ci)},
    }
    return contract


def normalize_contract_doc(surface: str) -> dict:
    """The sealed normalization contract document. Its sha256 is
    normalization_contract_sha256 (bound by source_evidence.json; the doc
    itself never carries its own hash)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "document_type": "normalization_contract",
        "surface": surface,
        "allowed_difference": "zip_dos_modification_timestamps_of_build_generated_members_only",
        "fail_close_fields": [
            "filename", "crc", "file_size", "compressed_size", "compression_method",
            "flag_bits", "external_attributes", "internal_attributes",
            "create_system_version", "extract_version", "extra_fields",
            "member_comments", "archive_comment", "member_ordering", "duplicate_paths",
        ],
        "unclassified_raw_difference_required_zero": True,
        "raw_differs_but_payload_same_never_accepted": True,
        "verdict_on_any_raw_inexplicability": "INVALID",
        "invalidate_never_means_reuse": True,
        "digest_derivations": {
            "sha256_bytes": "hex sha256 of the raw bytes",
            "record_sha256": "PEP 376 'sha256=' + urlsafe base64, unpadded",
            "canonical_serialize": "recursive key-sort compact JSON + one trailing LF; list order preserved",
            "payload_digest_from_entries": "sha256 of canonical_serialize over sorted [[rel, sha256, size], ...] excluding the RECORD entry",
            "probe_source_sha256": "sha256 of the probe tool source bytes (the bundle's verifier_source.py copy)",
            "runtime_identity_sha256": "sha256 of the strict runtime_sdist_identity.json bytes",
            "selected_input_contract_sha256": "sha256 of selected_input_contract.json bytes",
            "normalization_contract_sha256": "sha256 of this document's bytes (bound by source_evidence.json; never self-referential)",
            "evidence_manifest_sha256": "sha256 of canonical_serialize over the sorted [[path, sha256, size], ...] entries of EVIDENCE_MANIFEST.json EXCLUDING the source_evidence.json entry",
        },
    }


# ---------------------------------------------------------------------------
# run context (tree/run binding; never inferred from branch names)


def run_context(repo: Path, env=None) -> dict:
    """Derive the exact run/tree binding from the GitHub runner environment
    and the checkout git state. Fails closed on any missing or inconsistent
    identifier. Never infers identity from a branch name."""
    if env is None:
        env = os.environ

    repository = env.get("GITHUB_REPOSITORY", "")
    workflow = env.get("GITHUB_WORKFLOW", "") or EXPECTED_WORKFLOW
    run_id = env.get("GITHUB_RUN_ID", "")
    run_attempt = env.get("GITHUB_RUN_ATTEMPT", "")
    merge_sha = env.get("GITHUB_SHA", "")
    event_path = env.get("GITHUB_EVENT_PATH", "")

    missing = sorted(
        k for k, v in {
            "GITHUB_REPOSITORY": repository,
            "GITHUB_RUN_ID": run_id,
            "GITHUB_RUN_ATTEMPT": run_attempt,
            "GITHUB_SHA": merge_sha,
            "GITHUB_EVENT_PATH": event_path,
        }.items() if not v
    )
    if missing:
        raise RuntimeError("run_context_missing:" + ",".join(missing))
    if repository != EXPECTED_REPOSITORY:
        raise RuntimeError(f"run_context_repository_mismatch:{repository}")
    if workflow != EXPECTED_WORKFLOW:
        raise RuntimeError(f"run_context_workflow_mismatch:{workflow}")
    if not re.fullmatch(r"[0-9a-f]{40}", merge_sha):
        raise RuntimeError(f"run_context_merge_sha_malformed:{merge_sha}")
    try:
        run_id_i = int(run_id)
        run_attempt_i = int(run_attempt)
    except ValueError as exc:
        raise RuntimeError(f"run_context_id_malformed:{exc}") from exc
    if run_id_i <= 0 or run_attempt_i <= 0:
        raise RuntimeError("run_context_id_nonpositive")

    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"run_context_event_unreadable:{exc}") from exc
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        raise RuntimeError("run_context_pr_required: source evidence is PR-bound")
    pr_number = pr.get("number")
    pr_head_sha = pr.get("head", {}).get("sha")
    if not isinstance(pr_number, int) or pr_number <= 0:
        raise RuntimeError(f"run_context_pr_number_malformed:{pr_number}")
    if not re.fullmatch(r"[0-9a-f]{40}", pr_head_sha or ""):
        raise RuntimeError(f"run_context_pr_head_sha_malformed:{pr_head_sha}")

    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{merge_sha}^{{tree}}"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"run_context_tree_unresolvable:{merge_sha}:{proc.stderr.strip()[-400:]}"
        )
    tested_tree_sha = proc.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tested_tree_sha):
        raise RuntimeError(f"run_context_tree_sha_malformed:{tested_tree_sha}")

    return {
        "repository": repository,
        "workflow": workflow,
        "run_id": run_id_i,
        "run_attempt": run_attempt_i,
        "pr_number": pr_number,
        "pr_head_sha": pr_head_sha,
        "tested_merge_sha": merge_sha,
        "tested_tree_sha": tested_tree_sha,
    }


def _probe_context_markers(ctx: dict | None) -> dict:
    if ctx is None:
        return {
            "RUN_CONTEXT_AVAILABLE": "false",
        }
    return {
        "RUN_CONTEXT_AVAILABLE": "true",
        "RUN_ID": str(ctx["run_id"]),
        "RUN_ATTEMPT": str(ctx["run_attempt"]),
        "PR_NUMBER": str(ctx["pr_number"]),
        "PR_HEAD_SHA": ctx["pr_head_sha"],
        "TESTED_MERGE_SHA": ctx["tested_merge_sha"],
        "TESTED_TREE_SHA": ctx["tested_tree_sha"],
    }


# ---------------------------------------------------------------------------
# measure (probe)


def _safe_extract(tar_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as tf:
        for member in tf.getmembers():
            name = member.name
            if name.startswith("/") or "\\" in name or ".." in name.split("/"):
                raise RuntimeError(f"unsafe_tar_member:{name}")
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise RuntimeError(f"tar_escape:{name}")
            if member.issym() or member.islnk():
                raise RuntimeError(f"tar_link_member:{name}")
            tf.extract(member, dest)


def _sdist_project_root(extract_dir: Path) -> Path:
    """Resolve the buildable project root inside a safe-extracted sdist."""
    if (extract_dir / "setup.py").is_file() or (extract_dir / "pyproject.toml").is_file():
        return extract_dir
    tops = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(tops) == 1:
        inner = tops[0]
        if (inner / "setup.py").is_file() or (inner / "pyproject.toml").is_file():
            return inner
    raise RuntimeError(f"sdist_project_root_unresolved:{extract_dir}")


def _fresh_venv(venv: Path, upgrade_pip: bool = True, index: bool = True) -> None:
    venv.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "venv", str(venv)])
    if upgrade_pip:
        env = {} if index else {"PIP_NO_INDEX": "1"}
        run([str(venv_python(venv)), "-m", "pip", "install", "--upgrade", "pip"], env=env)


def _shadow_surface_selectors(repo: Path, surface: str) -> list:
    if surface == "test-3.14":
        failures = validate_py314_manifest_static(repo)
        if failures:
            raise RuntimeError("py314_manifest_invalid:" + ";".join(failures[:5]))
        text = (repo / PY314_MANIFEST_REL).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        return text[:-1].split("\n")
    return list(PYARROW24_SURFACE_FILES)


def cmd_probe(args) -> int:
    out = Path(args.out_dir).resolve()
    repo = Path(args.repo).resolve()
    surface = args.surface
    head = args.head
    if out.exists():
        # the probe creates a fresh measurement dir; stale partial outputs
        # from a previous attempt would mix with the current measurement
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    summary: dict[str, str] = {
        "SURFACE": surface,
        "HEAD": head,
        "P2_9_PROBE_VERSION": "1",
    }
    ctx = None
    try:
        ctx = run_context(repo)
    except RuntimeError:
        ctx = None
    for k, v in _probe_context_markers(ctx).items():
        summary[k] = v

    summary["PROBE_SOURCE_SHA256"] = sha256_file(Path(__file__).resolve())

    t0 = time.monotonic()
    try:
        _measure(out, repo, surface, head, summary)
    except BaseException:  # fail-closed crash report; evidence invalid
        (out / "measure_crash.log").write_text(
            traceback.format_exc(), encoding="utf-8", errors="replace"
        )
        summary["MEASURE_CRASH"] = "true"
    else:
        summary["MEASURE_CRASH"] = "false"
    summary["MEASURE_ELAPSED_SECONDS"] = f"{time.monotonic() - t0:.1f}"

    verdict = evaluate_verdict(summary)
    for k, v in verdict.items():
        summary[f"EVALUATED_{k.upper()}"] = str(v).lower()
    lines = [f"{k}={v}" for k, v in sorted(summary.items())]
    (out / PROBE_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if summary["MEASURE_CRASH"] == "true" else 0


def _measure(out: Path, repo: Path, surface: str, head: str, summary: dict) -> None:
    venvs = out / "venvs"
    resolver_venv = venvs / "resolver"
    build_env = venvs / "build_env"
    shadow_venv = venvs / "shadow"

    # 1. runtime resolution -------------------------------------------------
    _fresh_venv(resolver_venv)
    report_path = out / "runtime_resolution_report.json"
    spec = ["-e", ".[dev]"]
    if surface == "pyarrow24":
        spec.append(PYARROW24_PIN)
    run(
        [str(venv_python(resolver_venv)), "-m", "pip", "install",
         "--dry-run", "--ignore-installed", "--report", str(report_path)] + spec,
        cwd=repo,
        log_path=out / "runtime_resolution.log",
    )
    summary["RESOLVER_PIP_VERSION"] = pip_version(resolver_venv)
    dists = report_distributions(report_path)
    for d in dists:
        if d["is_local"] and d["canonical_name"] != PROJECT_NAME:
            raise RuntimeError(f"unexpected_local_entry:{d['canonical_name']}")
    runtime_dists = sorted(
        (d for d in dists if d["canonical_name"] != PROJECT_NAME),
        key=lambda d: d["canonical_name"],
    )
    sdists = [d for d in runtime_dists if d["is_sdist"]]
    non_wheels = [d for d in runtime_dists if not d["is_sdist"] and not (d["url"] or "").endswith(".whl")]
    summary["RUNTIME_WHEEL_COUNT"] = str(len(runtime_dists) - len(sdists) - len(non_wheels))
    summary["RUNTIME_SDIST_COUNT"] = str(len(sdists))
    summary["RUNTIME_OTHER_COUNT"] = str(len(non_wheels))
    if len(sdists) != 1 or canonicalize_name(sdists[0]["canonical_name"]) not in RUNTIME_SDIST_EXPECTED:
        raise RuntimeError(f"unexpected_runtime_sdist_set:{sdists}")
    sdist_meta = sdists[0]

    # 2. sdist materialization + hash ----------------------------------------
    sdist_dir = out / "source_sdist"
    sdist_dir.mkdir(parents=True, exist_ok=True)
    run(
        [str(venv_python(resolver_venv)), "-m", "pip", "download",
         f"{sdist_meta['canonical_name']}=={sdist_meta['version']}",
         "--no-deps", "--no-binary", ":all:", "-d", str(sdist_dir)],
        log_path=out / "sdist_download.log",
    )
    tar_files = list(sdist_dir.glob("*.tar.gz")) + list(sdist_dir.glob("*.zip"))
    if len(tar_files) != 1:
        raise RuntimeError(f"sdist_download_count:{len(tar_files)}")
    sdist_path = tar_files[0]
    sdist_sha = sha256_file(sdist_path)
    summary[f"SDIST_MATERIALIZED_{sdist_meta['canonical_name']}"] = "true"
    summary["SOURCE_SDIST_HASH_OK"] = "true" if sdist_sha == sdist_meta["sha256"] else "false"
    if sdist_sha != sdist_meta["sha256"]:
        raise RuntimeError("sdist_sha_mismatch")

    # 3. safe extraction (two fresh trees) -----------------------------------
    extract1 = out / "sdist_extract_1"
    extract2 = out / "sdist_extract_2"
    _safe_extract(sdist_path, extract1)
    _safe_extract(sdist_path, extract2)
    root1 = _sdist_project_root(extract1)
    root2 = _sdist_project_root(extract2)
    summary["SDIST_PROJECT_ROOT_FOUND"] = "true"

    # 4. build contract -------------------------------------------------------
    pyproject_files = list(extract1.rglob("pyproject.toml"))
    bs = None
    if pyproject_files:
        bs = tomllib.loads(pyproject_files[0].read_text(encoding="utf-8")).get("build-system")
    backend = "setuptools.build_meta:__legacy__"
    declared = ["setuptools>=40.8.0", "wheel"]
    if bs is not None:
        if "build-backend" in bs:
            backend = bs["build-backend"]
        if "requires" in bs:
            declared = list(bs["requires"])
    summary["BUILD_CONTRACT_SOURCE"] = "pyproject.toml" if bs is not None else "legacy_fallback"
    probe_venv = venvs / "probe"
    _fresh_venv(probe_venv)
    run(
        [str(venv_python(probe_venv)), "-m", "pip", "install", "--no-deps"] + declared,
        log_path=out / "build_probe_install.log",
    )
    module_name, _, obj_path = backend.partition(":")
    hook_script = (
        "import importlib; m = importlib.import_module(%r); "
        "o = getattr(m, %r) if %r else m; "
        "o = o() if isinstance(o, type) else o; "
        "print(o.get_requires_for_build_wheel())"
        % (module_name, obj_path, obj_path)
    )
    rc, hook_out = run(
        [str(venv_python(probe_venv)), "-c", hook_script],
        cwd=root1,
        log_path=out / "build_hook_probe.log",
        check=False,
    )
    dynamic = []
    if rc == 0:
        try:
            dynamic = json.loads(hook_out.strip().splitlines()[-1])
        except Exception:
            dynamic = []
    build_contract = {
        "backend": backend,
        "declared_requires": declared,
        "dynamic_requires": dynamic,
    }
    (out / "build_contract.json").write_text(
        canonical_serialize({"schema_version": SCHEMA_VERSION, "build_contract": build_contract}),
        encoding="utf-8",
    )
    effective_requires = declared + dynamic

    # 5. closed-world build environment --------------------------------------
    _fresh_venv(build_env)
    build_resolve_report = out / "build_deps_resolve_report.json"
    run(
        [str(venv_python(build_env)), "-m", "pip", "install", "--dry-run",
         "--ignore-installed", "--report", str(build_resolve_report)] + effective_requires,
        log_path=out / "build_deps_resolve.log",
    )
    build_dists = sorted(
        (d for d in report_distributions(build_resolve_report) if not d["is_sdist"]),
        key=lambda d: d["canonical_name"],
    )
    if any(d["is_sdist"] for d in report_distributions(build_resolve_report)):
        raise RuntimeError("build_dep_sdist_rejected")
    wheelhouse = out / "exact_build_wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    env_lines = []
    env_inventory = []
    for d in build_dists:
        run(
            [str(venv_python(build_env)), "-m", "pip", "download",
             f"{d['canonical_name']}=={d['version']}", "--no-deps", "-d", str(wheelhouse)],
            log_path=out / f"build_wheel_download_{d['canonical_name']}.log",
        )
        wheels = list(wheelhouse.glob(f"{d['canonical_name'].replace('-', '_')}-{d['version']}*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"build_wheel_materialize_count:{d['canonical_name']}")
        wh = wheels[0]
        wh_sha = sha256_file(wh)
        if wh_sha != d["sha256"]:
            raise RuntimeError(f"build_wheel_sha_mismatch:{d['canonical_name']}")
        env_lines.append(f"{d['canonical_name']}=={d['version']} --hash=sha256:{wh_sha}")
        env_inventory.append(
            {"canonical_name": d["canonical_name"], "version": d["version"],
             "filename": wh.name, "sha256": wh_sha}
        )
    req_path = out / "exact_build_environment.txt"
    req_path.write_text("\n".join(sorted(env_lines)) + "\n", encoding="utf-8")
    env_identity = sha256_bytes(canonical_serialize(env_inventory).encode())
    summary["SOURCE_BUILD_ENVIRONMENT_SHA256"] = env_identity
    env_identity_doc = {
        "schema_version": SCHEMA_VERSION,
        "surface": surface,
        "source_build_environment": {
            "identity_sha256": env_identity,
            "requirements_file_sha256": sha256_file(req_path),
            "distributions": env_inventory,
        },
    }
    (out / "build_env_identity.json").write_text(canonical_serialize(env_identity_doc), encoding="utf-8")
    closed_world_env = {
        "PIP_NO_INDEX": "1",
        "PIP_FIND_LINKS": os.pathsep.join([str(wheelhouse)]),
    }
    run(
        [str(venv_python(build_env)), "-m", "pip", "install", "--require-hashes", "-r", str(req_path)],
        env=closed_world_env,
        log_path=out / "build_env_install.log",
    )

    # 6. two cache-disabled closed-world builds ------------------------------
    built = {}
    for i, proj_root in ((1, root1), (2, root2)):
        bdir = out / "built_wheels" / str(i)
        bdir.mkdir(parents=True, exist_ok=True)
        run(
            [str(venv_python(build_env)), "-m", "pip", "wheel",
             str(proj_root), "--no-deps", "--no-build-isolation",
             "--check-build-dependencies", "--no-cache-dir", "-w", str(bdir)],
            env=closed_world_env,
            log_path=out / f"source_build_{i}.log",
        )
        log_text = (out / f"source_build_{i}.log").read_text(encoding="utf-8", errors="replace")
        built_wheels = list(bdir.glob("*.whl"))
        if len(built_wheels) != 1:
            raise RuntimeError(f"built_wheel_count_{i}:{len(built_wheels)}")
        built[i] = built_wheels[0]
        summary[f"SOURCE_BUILD_CACHE_DISABLED_moomoo-api_{i}"] = (
            "true" if "Using cached" not in log_text and "Building wheel" in log_text else "false"
        )

    raw1 = built[1].read_bytes()
    raw2 = built[2].read_bytes()
    summary["RAW_WHEEL_SHA256_1"] = sha256_bytes(raw1)
    summary["RAW_WHEEL_SHA256_2"] = sha256_bytes(raw2)
    raw_reproducible = raw1 == raw2
    summary["RAW_WHEEL_REPRODUCIBLE_moomoo-api"] = "true" if raw_reproducible else "false"

    # 7. wheel validation -----------------------------------------------------
    inv1 = inventory_wheel(built[1])
    inv2 = inventory_wheel(built[2])
    summary["WHEEL_VALIDATION_1"] = "true" if inv1.structural_valid and inv1.record_valid else "false"
    summary["WHEEL_VALIDATION_2"] = "true" if inv2.structural_valid and inv2.record_valid else "false"
    summary["RECORD_VALID_1"] = "true" if inv1.record_valid else "false"
    summary["RECORD_VALID_2"] = "true" if inv2.record_valid else "false"
    for i, inv in ((1, inv1), (2, inv2)):
        (out / f"wheel_validation_{i}.json").write_text(
            canonical_serialize(
                {"members": [m.path for m in inv.members],
                 "record_valid": inv.record_valid,
                 "errors": inv.errors,
                 "filename": inv.filename_info}
            ),
            encoding="utf-8",
        )
    if inv1.filename_info is None or inv2.filename_info is None:
        raise RuntimeError("wheel_filename_malformed")

    # 8. payload identity + RAW-MISMATCH NORMALIZATION PROOF (A-F) ------------
    p1, c1 = payload_sha256(inv1.members, inv1.record_path)
    p2, c2 = payload_sha256(inv2.members, inv2.record_path)
    summary["WHEEL_PAYLOAD_SHA256"] = p1
    summary["PAYLOAD_ENTRY_COUNT_1"] = str(c1)
    summary["PAYLOAD_ENTRY_COUNT_2"] = str(c2)
    payload_match = p1 == p2
    summary["WHEEL_PAYLOAD_MATCH_moomoo-api"] = "true" if payload_match else "false"

    cmp_result = compare_wheels(inv1, inv2)
    classify = classify_raw_mismatch(raw1, raw2, inv1, inv2, cmp_result)
    normalization_valid = classify["verdict"]
    summary["RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api"] = "true" if normalization_valid else "false"
    summary["RAW_MISMATCH_REASON_moomoo-api"] = classify["reason"]
    summary["RAW_DIFF_BYTE_COUNT"] = str(classify.get("diff_byte_count"))
    summary["RAW_DIFF_ATTRIBUTION"] = json.dumps(classify.get("attribution"), sort_keys=True)
    normalization_proof = {
        "schema_version": SCHEMA_VERSION,
        "surface": surface,
        "wheel_payload_sha256_1": p1,
        "wheel_payload_sha256_2": p2,
        "wheel_payload_match": payload_match,
        "raw_wheel_reproducible": raw_reproducible,
        "raw_mismatch_normalization_valid": normalization_valid,
        "raw_mismatch_reason": classify["reason"],
        "raw_diff_byte_count": classify.get("diff_byte_count"),
        "raw_diff_attribution": classify.get("attribution"),
        "first_differing_offset": classify.get("first_differing_offset"),
        "first_differing_offset_in_timestamp_slot": classify.get("first_differing_offset_in_timestamp_slot"),
        "comparison": cmp_result,
        "contract": {
            "allowed_difference": "zip_dos_modification_timestamps_of_build_generated_members_only",
            "fail_close_fields": [
                "filename", "crc", "file_size", "compressed_size", "compression_method",
                "flag_bits", "external_attributes", "internal_attributes",
                "create_system_version", "extract_version", "extra_fields",
                "member_comments", "archive_comment", "member_ordering", "duplicate_paths",
            ],
        },
    }
    (out / "normalization_proof.json").write_text(canonical_serialize(normalization_proof), encoding="utf-8")

    # positive control: timestamp-only mutation ------------------------------
    time_diff_members = [d["path"] for d in cmp_result.get("timestamp_diffs", [])]
    if not time_diff_members:
        time_diff_members = [
            m.path for m in inv1.members
            if m.path.split("/", 1)[0] == inv1.dist_info_dir
        ]
    control_raw = patch_zip_timestamps(raw1, inv1, time_diff_members, new_time=0x0000)
    control_path = out / "positive_control" / built[1].name
    control_path.parent.mkdir(parents=True, exist_ok=True)
    control_path.write_bytes(control_raw)
    control_inv = inventory_wheel(control_path)
    ctl_cmp = compare_wheels(inv1, control_inv)
    ctl_classify = classify_raw_mismatch(raw1, control_raw, inv1, control_inv, ctl_cmp)
    ctl_payload, _ = payload_sha256(control_inv.members, control_inv.record_path)
    pos_patch_ok = (
        ctl_classify["verdict"] and ctl_cmp["wheel_payload_match"]
        and ctl_payload == p1 and control_raw != raw1 and control_inv.record_valid
    )
    summary["POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK_moomoo-api"] = "true" if pos_patch_ok else "false"
    pos_venv = venvs / "pos_control"
    _fresh_venv(pos_venv, upgrade_pip=False, index=False)
    pos_install_ok = False
    if pos_patch_ok:
        pos_report = out / "positive_control" / "positive_control_install_report.json"
        run(
            [str(venv_python(pos_venv)), "-m", "pip", "install", "--no-deps",
             "--no-cache-dir", "--report", str(pos_report), str(control_path)],
            env={"PIP_NO_INDEX": "1"},
            log_path=out / "positive_control" / "positive_control_install.log",
        )
        pos_digest = installed_payload_digest(pos_venv, "moomoo-api")
        pos_install_ok = pos_digest == p1
        summary["POSITIVE_CONTROL_INSTALLED_PAYLOAD_MATCH"] = "true" if pos_install_ok else "false"
    else:
        summary["POSITIVE_CONTROL_INSTALLED_PAYLOAD_MATCH"] = "false"
    pos_ok = pos_patch_ok and pos_install_ok
    summary["POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK_moomoo-api"] = "true" if pos_ok else "false"
    (out / "positive_control" / "positive_control_verify.json").write_text(
        canonical_serialize(
            {"verdict": ctl_classify["verdict"], "reason": ctl_classify["reason"],
             "payload_match": ctl_cmp["wheel_payload_match"], "payload_sha256": ctl_payload,
             "patched_members": time_diff_members, "raw_different": control_raw != raw1,
             "control_record_valid": control_inv.record_valid,
             "installed_payload_match": pos_install_ok,
             "patched_wheel_sha256": sha256_bytes(control_raw)}
        ),
        encoding="utf-8",
    )

    # negative control: payload byte mutation (stale + consistent RECORD) -----
    mut_dir = out / "mutation_negative"
    stale_path = mut_dir / "stale" / built[1].name
    consistent_path = mut_dir / "consistent" / built[1].name
    stale_path.parent.mkdir(parents=True, exist_ok=True)
    consistent_path.parent.mkdir(parents=True, exist_ok=True)
    mutated_member = rebuild_wheel_mutated(raw1, inv1, stale_path, fix_record=False)
    rebuild_wheel_mutated(raw1, inv1, consistent_path, fix_record=True)
    stale_inv = inventory_wheel(stale_path)
    consistent_inv = inventory_wheel(consistent_path)
    consistent_payload, _ = payload_sha256(consistent_inv.members, consistent_inv.record_path)
    mut_rejected = (
        (not stale_inv.record_valid) and consistent_inv.record_valid
        and consistent_payload != p1
    )
    summary["MUTATED_WHEEL_REJECTED_moomoo-api"] = "true" if mut_rejected else "false"
    (out / "mutation_negative" / "mutation_negative_verify.json").write_text(
        canonical_serialize(
            {"mutated_member": mutated_member,
             "stale_record": {"record_valid": stale_inv.record_valid, "errors": stale_inv.errors},
             "consistent_record": {"record_valid": consistent_inv.record_valid,
                                   "payload_equals_original": consistent_payload == p1},
             "rejected": mut_rejected}
        ),
        encoding="utf-8",
    )

    # 9. exact-wheel install ---------------------------------------------------
    install_report = out / "source_built_install_report.json"
    _fresh_venv(shadow_venv)
    run(
        [str(venv_python(shadow_venv)), "-m", "pip", "install", "--no-deps",
         "--no-cache-dir", "--report", str(install_report), str(built[1])],
        env={"PIP_NO_INDEX": "1"},
        log_path=out / "source_built_install.log",
    )
    irep = json.loads(install_report.read_text(encoding="utf-8"))
    install_items = [it for it in irep.get("install", [])]
    if len(install_items) != 1:
        raise RuntimeError(f"install_report_count:{len(install_items)}")
    dl = install_items[0].get("download_info", {}) or {}
    arch = dl.get("archive_info", {}) or {}
    report_sha = (arch.get("hashes", {}) or {}).get("sha256", "")
    report_url = (dl.get("url", "") or "").split("#", 1)[0]
    slot_ok = report_url.endswith(f"built_wheels/1/{built[1].name}")
    sha_ok = report_sha == summary["RAW_WHEEL_SHA256_1"]
    summary["INSTALL_REPORT_SLOT_OK"] = "true" if slot_ok else "false"
    summary["INSTALL_REPORT_SHA_OK"] = "true" if sha_ok else "false"

    # 10. installed payload proof ----------------------------------------------
    installed_payload_dir = out / "installed_payload"
    entries_json = out / "installed_entries.json"
    entries, record_rel = installed_entries(
        shadow_venv, "moomoo-api", entries_json, copy_to=installed_payload_dir
    )
    inst_payload, inst_count = payload_digest_from_entries(entries, record_rel)
    summary["INSTALLED_PAYLOAD_SHA256"] = inst_payload
    summary["INSTALLED_PAYLOAD_ENTRY_COUNT"] = str(inst_count)
    installed_match = inst_payload == p1
    summary["INSTALLED_PAYLOAD_MATCH"] = "true" if installed_match else "false"

    inst_record_valid = False
    if record_rel:
        record_path = installed_payload_dir / record_rel
        if record_path.exists():
            errors = []
            members = [
                {"path": e[0], "sha256": e[1], "size": e[2],
                 "content": (installed_payload_dir / e[0]).read_bytes()}
                for e in entries if e[0] != record_rel
            ]
            members.append({"path": record_rel, "content": record_path.read_bytes()})
            _validate_installed_record(members, record_rel, errors)
            inst_record_valid = not errors
    summary["INSTALLED_RECORD_VALID"] = "true" if inst_record_valid else "false"
    (out / "installed_payload_verify.json").write_text(
        canonical_serialize(
            {"installed_payload_sha256": inst_payload, "entry_count": inst_count,
             "installed_payload_match": installed_match,
             "wheel_payload_sha256": p1, "installed_record_valid": inst_record_valid,
             "record_rel": record_rel}
        ),
        encoding="utf-8",
    )

    # 11. remainder runtime provisioning (wheels only, exact versions) ---------
    remainder_dir = out / "remainder_wheelhouse"
    remainder_dir.mkdir(parents=True, exist_ok=True)
    unexpected = []
    for d in runtime_dists:
        if d["canonical_name"] == "moomoo-api":
            continue
        if d["is_sdist"]:
            unexpected.append(d["canonical_name"])
            continue
        run(
            [str(venv_python(resolver_venv)), "-m", "pip", "download",
             f"{d['canonical_name']}=={d['version']}", "--no-deps", "-d", str(remainder_dir)],
            log_path=out / f"remainder_download_{d['canonical_name']}.log",
        )
    summary["UNEXPECTED_REMAINDER_SDIST"] = "true" if unexpected else "false"
    rem_wheels = sorted(remainder_dir.glob("*.whl"))
    rem_report = out / "remainder_install_report.json"
    run(
        [str(venv_python(shadow_venv)), "-m", "pip", "install", "--no-deps",
         "--no-cache-dir", "--report", str(rem_report)] + [str(w) for w in rem_wheels],
        env={"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(remainder_dir)},
        log_path=out / "remainder_install.log",
    )
    survived = installed_payload_digest(shadow_venv, "moomoo-api") == p1
    summary["SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL"] = "true" if survived else "false"
    if not survived:
        raise RuntimeError("source_built_package_replaced_during_remainder")

    # 12. MarketVault editable install under the closed-world contract ---------
    run(
        [str(venv_python(shadow_venv)), "-m", "pip", "install",
         "--require-hashes", "-r", str(req_path)],
        env=closed_world_env,
        log_path=out / "shadow_exact_build_env_install.log",
    )
    mv_report = out / "marketvault_editable_install_report.json"
    run(
        [str(venv_python(shadow_venv)), "-m", "pip", "install", "--no-deps",
         "--no-build-isolation", "--check-build-dependencies", "--no-cache-dir",
         "--report", str(mv_report), "-e", str(repo)],
        env={"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": os.pathsep.join([str(wheelhouse)])},
        log_path=out / "marketvault_editable_install.log",
    )
    summary["P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED"] = "true"
    survived_all = installed_payload_digest(shadow_venv, "moomoo-api") == p1
    summary["SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL"] = "true" if survived_all else "false"
    if not survived_all:
        raise RuntimeError("source_built_package_replaced_during_all_install")

    # 13. candidate surface execution in the shadow env ------------------------
    surface_selectors = _shadow_surface_selectors(repo, surface)
    rc, _ = run(
        [str(venv_python(shadow_venv)), "-m", "pytest", *surface_selectors, "-q"],
        cwd=repo,
        check=False,
        log_path=out / "shadow_surface_run.log",
        timeout=3600,
    )
    surface_pass = rc == 0
    summary["SHADOW_SURFACE_PASS"] = "true" if surface_pass else "false"
    audited_surface = "pyarrow24-audited" if surface == "pyarrow24" else "test-3.14-sealed"
    (out / "shadow_surface_result.json").write_text(
        canonical_serialize(
            {"surface": audited_surface, "pass": surface_pass, "rc": rc,
             "selector_count": len(surface_selectors)}
        ),
        encoding="utf-8",
    )

    # 14. final runtime match ---------------------------------------------------
    final_inv = _final_runtime_inventory(shadow_venv)
    (out / "final_runtime_inventory.json").write_text(
        canonical_serialize(final_inv), encoding="utf-8"
    )
    runtime_ok = True
    for d in runtime_dists:
        if d["canonical_name"] == "moomoo-api":
            continue
        if final_inv.get(d["canonical_name"]) != d["version"]:
            runtime_ok = False
            break
    if final_inv.get("moomoo-api") != sdist_meta["version"]:
        runtime_ok = False
    summary["FINAL_RUNTIME_MATCH"] = "true" if runtime_ok else "false"
    summary["RUNTIME_INSTALL_FROM_WHEELS_ONLY"] = "true" if not unexpected else "false"
    summary["UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL"] = "true" if unexpected else "false"
    summary["SOURCE_BUILD_IDENTITY_VALID"] = "true" if raw_reproducible else "false"

    # selected-input contract + normalization contract docs --------------------
    sel_contract = compute_selected_input_contract(repo, surface)
    sel_rel = out / SELECTED_INPUT_CONTRACT_NAME
    sel_rel.write_text(canonical_serialize(sel_contract), encoding="utf-8")
    summary["SELECTED_INPUT_CONTRACT_SHA256"] = sha256_file(sel_rel)
    summary[f"TARGET_RELATION_{surface}"] = (
        "true" if sel_contract["target_relation"]["selected_by_this_surface"] else "false"
    )
    norm_contract = normalize_contract_doc(surface)
    norm_rel = out / NORMALIZATION_CONTRACT_NAME
    norm_rel.write_text(canonical_serialize(norm_contract), encoding="utf-8")
    summary["NORMALIZATION_CONTRACT_SHA256"] = sha256_file(norm_rel)

    # normalized identity document ---------------------------------------------
    fi = inv1.filename_info
    wheel_metadata_identity = sha256_bytes(
        canonical_serialize(
            {
                "dist_info_dir": inv1.dist_info_dir,
                "metadata_sha256": sha256_bytes(
                    next(m.content for m in inv1.members if m.path == f"{inv1.dist_info_dir}/METADATA")
                ),
                "wheel_file_sha256": sha256_bytes(
                    next(m.content for m in inv1.members if m.path == f"{inv1.dist_info_dir}/WHEEL")
                ),
                "top_level_sha256": sha256_bytes(
                    next(m.content for m in inv1.members if m.path == f"{inv1.dist_info_dir}/top_level.txt")
                ),
            }
        ).encode()
    )
    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "document_type": DOC_NORMALIZED,
        "surface": surface,
        "canonical_name": "moomoo-api",
        "version": sdist_meta["version"],
        "resolver_identity": {"name": "pip", "version": summary["RESOLVER_PIP_VERSION"]},
        "sdist_sha256": sdist_sha,
        "build_contract": build_contract,
        "closed_world_build_env": {
            "identity_sha256": env_identity,
            "requirements_file_sha256": sha256_file(req_path),
        },
        "wheel_tags": {
            "python_tag": fi["python_tag"], "abi_tag": fi["abi_tag"],
            "platform_tag": fi["platform_tag"],
        },
        "wheel_metadata_identity": wheel_metadata_identity,
        "wheel_payload_sha256": p1,
        "installed_payload_sha256": inst_payload,
        "payload_entry_count": c1,
        "record_validation": {
            "wheel_1": inv1.record_valid, "wheel_2": inv2.record_valid,
            "installed": inst_record_valid,
        },
        "raw_mismatch_verdict": {
            "raw_wheel_reproducible": raw_reproducible,
            "normalization_valid": normalization_valid,
            "reason": classify["reason"],
            "diff_byte_count": classify.get("diff_byte_count"),
            "diff_attribution": classify.get("attribution"),
            "allowed_difference": "zip_dos_modification_timestamps_of_build_generated_members_only",
        },
        "final_installed_identity": {
            "installed_payload_sha256": inst_payload,
            "installed_record_valid": inst_record_valid,
            "survived_remainder": survived,
            "survived_all": survived_all,
        },
        "final_runtime_identity": {
            "final_runtime_match": runtime_ok,
            "wheels_only": not unexpected,
            "wheel_count": len(runtime_dists) - len(sdists) - len(non_wheels),
            "sdist_count": len(sdists),
        },
        "marketvault_build_identity": {
            "p2_5_closed_world_contract_used": True,
            "editable_install_ok": True,
        },
        "shadow_surface": {"pass": surface_pass, "audited_surface": audited_surface},
        "raw_diagnostic": {
            "raw_wheel_sha256_1": summary["RAW_WHEEL_SHA256_1"],
            "raw_wheel_sha256_2": summary["RAW_WHEEL_SHA256_2"],
            "note": "retained diagnostic only; never normalized away",
        },
    }
    fp_doc = {k: v for k, v in identity_payload.items() if k != "raw_diagnostic"}
    fp_doc["raw_diagnostic_sha256"] = sha256_bytes(
        canonical_serialize(identity_payload["raw_diagnostic"]).encode()
    )
    identity_payload["raw_diagnostic_sha256"] = fp_doc["raw_diagnostic_sha256"]
    fingerprint = sha256_bytes(canonical_serialize(fp_doc).encode())
    identity_payload["fingerprint_sha256"] = fingerprint
    summary["NORMALIZED_SOURCE_BUILD_IDENTITY_SHA256"] = fingerprint
    (out / DOC_NORMALIZED).write_text(canonical_serialize(identity_payload), encoding="utf-8")

    # strict raw identity document (the schema-bound source runtime identity) --
    # the crash marker is only ever final after the whole probe exits; inside
    # the measurement the probe has not crashed yet.
    summary["MEASURE_CRASH"] = "false"
    verdict = evaluate_verdict(summary)
    for k, v in verdict.items():
        summary[f"EVALUATED_{k.upper()}"] = str(v).lower()
    strict_doc = {
        "schema_version": SCHEMA_VERSION,
        "document_type": DOC_RUNTIME,
        "surface": surface,
        "head": head,
        "runner": runner_block(),
        "python": python_block(),
        "resolver": {"name": "pip", "version": summary["RESOLVER_PIP_VERSION"]},
        "dependency_contract": dependency_contract(repo),
        "action_contract": action_contract(repo),
        "resolved_distributions": runtime_dists,
        "source_sdist": {
            "canonical_name": sdist_meta["canonical_name"],
            "version": sdist_meta["version"],
            "artifact": sdist_path.name,
            "sha256": sdist_sha,
        },
        "source_build_environment": {
            "identity_sha256": env_identity,
            "distributions": env_inventory,
        },
        "build_contract": build_contract,
        "exact_built_wheel_sha256": {
            "build_1": summary["RAW_WHEEL_SHA256_1"],
            "build_2": summary["RAW_WHEEL_SHA256_2"],
        },
        "wheel_payload_identity": {
            "wheel_payload_sha256": p1,
            "entry_count": c1,
            "record_valid": inv1.record_valid and inv2.record_valid,
        },
        "installed_payload_identity": {
            "installed_payload_sha256": inst_payload,
            "record_valid": inst_record_valid,
        },
        "normalized_verdict": {
            "raw_wheel_reproducible": raw_reproducible,
            "normalization_valid": normalization_valid,
            "reason": classify["reason"],
        },
        "marketvault_build_identity": {
            "p2_5_closed_world_contract_used": True,
            "editable_install_ok": True,
        },
        "final_runtime_identity": {
            "final_runtime_match": runtime_ok,
            "wheels_only": not unexpected,
            "unexpected_sdist": bool(unexpected),
            "wheel_count": len(runtime_dists) - len(sdists) - len(non_wheels),
            "sdist_count": len(sdists),
        },
        "shadow_surface": {"pass": surface_pass, "audited_surface": audited_surface},
        "selected_input_contract_sha256": summary["SELECTED_INPUT_CONTRACT_SHA256"],
        "normalization_contract_sha256": summary["NORMALIZATION_CONTRACT_SHA256"],
        "probe_source_sha256": summary["PROBE_SOURCE_SHA256"],
        "valid_flags": {
            "source_build_identity_valid": raw_reproducible,
            "normalized_install_artifact_identity_valid": verdict["normalized_install_artifact_identity_valid"],
            "final_runtime_match": runtime_ok,
            "shadow_surface_pass": surface_pass,
            "measure_crash": False,
        },
    }
    (out / DOC_RUNTIME).write_text(canonical_serialize(strict_doc), encoding="utf-8")


def _validate_installed_record(members, record_rel, errors) -> None:
    record_member = next(m for m in members if m["path"] == record_rel)
    lines = record_member["content"].decode("utf-8").splitlines()
    listed = {}
    for ln in lines:
        parts = ln.split(",")
        if len(parts) != 3:
            errors.append("record_line_malformed")
            continue
        listed[parts[0]] = (parts[1], parts[2])
    for m in members:
        if m["path"] == record_rel:
            if listed.get(record_rel) != ("", ""):
                errors.append("record_self_entry_not_empty")
            continue
        rhash, rsize = listed.get(m["path"], (None, None))
        if rhash != record_sha256(m["content"]):
            errors.append(f"record_hash_mismatch:{m['path']}")
        if rsize != str(m["size"]):
            errors.append(f"record_size_mismatch:{m['path']}")


# ---------------------------------------------------------------------------
# source evidence schema (Section 4; exact key set; INVALID on any drift)

_HEX40_RE = re.compile(r"[0-9a-f]{40}")  # git SHAs
_HEX64_RE = re.compile(r"[0-9a-f]{64}")  # sha256 digests


def validate_source_evidence(doc) -> list:
    """Validate a source evidence document against the exact 15-key schema.
    Returns failure messages; empty list means VALID. Unknown or missing
    keys, wrong types, wrong class literal, or wrong literals => INVALID.
    No permissive fallback exists."""
    failures = []
    if not isinstance(doc, dict):
        return ["source_evidence_not_object"]
    keys = set(doc)
    expected = set(SOURCE_EVIDENCE_FIELDS)
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing:
        failures.append("missing_keys:" + ",".join(missing))
    if unknown:
        failures.append("unknown_keys:" + ",".join(unknown))

    if doc.get("schema_version") != SCHEMA_VERSION:
        failures.append(
            f"schema_version_expected_{SCHEMA_VERSION}_got:{doc.get('schema_version')!r}"
        )
    if doc.get("artifact_class") != ARTIFACT_CLASS:
        failures.append(
            f"artifact_class_expected_{ARTIFACT_CLASS}_got:{doc.get('artifact_class')!r}"
        )
    if doc.get("repository") != EXPECTED_REPOSITORY:
        failures.append(f"repository_mismatch:{doc.get('repository')!r}")
    if doc.get("workflow") != EXPECTED_WORKFLOW:
        failures.append(f"workflow_mismatch:{doc.get('workflow')!r}")
    if doc.get("surface") not in SURFACES:
        failures.append(f"surface_invalid:{doc.get('surface')!r}")
    for key in ("run_id", "run_attempt", "pr_number"):
        v = doc.get(key)
        if not isinstance(v, int) or v <= 0:
            failures.append(f"{key}_expected_positive_int:{v!r}")
    for key in ("pr_head_sha", "tested_merge_sha", "tested_tree_sha"):
        v = doc.get(key)
        if not isinstance(v, str) or not _HEX40_RE.fullmatch(v):
            failures.append(f"{key}_expected_40_lower_hex:{v!r}")
    for key in (
        "probe_source_sha256", "selected_input_contract_sha256",
        "runtime_identity_sha256", "normalization_contract_sha256",
        "evidence_manifest_sha256",
    ):
        v = doc.get(key)
        if not isinstance(v, str) or not _HEX64_RE.fullmatch(v):
            failures.append(f"{key}_expected_64_lower_hex:{v!r}")
    return failures


# ---------------------------------------------------------------------------
# bundle (finalize)


def _walk_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix().replace("\\", "/")
            top = rel.split("/", 1)[0]
            if top in BUNDLE_EXCLUDED_TOPS:
                continue
            yield rel


def manifest_content_digest(entries) -> str:
    """sha256 of canonical_serialize over the sorted [[path, sha256, size],
    ...] entries of EVIDENCE_MANIFEST.json EXCLUDING the source evidence
    entry (the root document cannot bind its own hash). This is the
    evidence_manifest_sha256 derivation defined in the normalization
    contract."""
    entries = sorted(entries, key=lambda e: e[0])
    return sha256_bytes(canonical_serialize(entries).encode())


def cmd_finalize(args) -> int:
    root = Path(args.out_dir).resolve()
    repo = Path(args.repo).resolve()
    surface = args.surface
    head = args.head

    summary = {}
    summary_p = root / PROBE_NAME
    if not summary_p.is_file():
        print(f"finalize_error=probe_summary_missing:{summary_p}")
        return 2
    for ln in summary_p.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in ln:
            k, _, v = ln.partition("=")
            summary[k] = v
    if summary.get("MEASURE_CRASH") != "false":
        print("finalize_error=probe_crashed")
        return 2
    if summary.get("RUN_CONTEXT_AVAILABLE") != "true":
        print("finalize_error=run_context_required")
        return 2
    if summary.get("SURFACE") != surface or summary.get("HEAD") != head:
        print("finalize_error=surface_or_head_mismatch")
        return 2

    ctx = run_context(repo)
    for k, v in {
        "RUN_ID": ctx["run_id"], "RUN_ATTEMPT": ctx["run_attempt"],
        "PR_NUMBER": ctx["pr_number"], "PR_HEAD_SHA": ctx["pr_head_sha"],
        "TESTED_MERGE_SHA": ctx["tested_merge_sha"], "TESTED_TREE_SHA": ctx["tested_tree_sha"],
    }.items():
        if summary.get(k) != str(v):
            print(f"finalize_error=run_context_mismatch:{k}")
            return 2
    if ctx["pr_head_sha"] != head:
        print("finalize_error=pr_head_sha_mismatch")
        return 2

    # 1. verifier self-copy first (must be manifest-bound)
    script_src = Path(__file__).resolve()
    verifier_dst = root / VERIFIER_NAME
    verifier_dst.write_bytes(script_src.read_bytes())
    verifier_sha = sha256_file(verifier_dst)
    probe_source_sha = summary.get("PROBE_SOURCE_SHA256")
    if probe_source_sha != verifier_sha:
        print("finalize_error=probe_source_sha_mismatch")
        return 2

    # 2. receipt (finalize stage; must precede the manifest)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "evidence_receipt",
        "surface": surface,
        "head": head,
        "verifier_script_sha256": verifier_sha,
        "repository": ctx["repository"],
        "workflow": ctx["workflow"],
        "run_id": ctx["run_id"],
        "run_attempt": ctx["run_attempt"],
        "pr_number": ctx["pr_number"],
        "pr_head_sha": ctx["pr_head_sha"],
        "tested_merge_sha": ctx["tested_merge_sha"],
        "tested_tree_sha": ctx["tested_tree_sha"],
        "generated": "bundle_finalize_stage",
    }
    (root / RECEIPT_NAME).write_text(canonical_serialize(receipt), encoding="utf-8")

    # 3. source evidence doc (root document; binds the manifest content
    # digest over all OTHER entries, so the mutual seal is acyclic and
    # one-pass: manifest binds evidence doc by listing it; evidence doc
    # binds the manifest minus its own entry)
    def entry(rel):
        p = root / rel
        return [rel, sha256_file(p), p.stat().st_size]

    other_entries = sorted(
        entry(rel) for rel in _walk_files(root)
        if rel not in (MANIFEST_NAME, SOURCE_EVIDENCE_NAME)
    )
    evidence_doc = {
        "schema_version": SCHEMA_VERSION,
        "artifact_class": ARTIFACT_CLASS,
        "repository": ctx["repository"],
        "workflow": ctx["workflow"],
        "run_id": ctx["run_id"],
        "run_attempt": ctx["run_attempt"],
        "pr_number": ctx["pr_number"],
        "pr_head_sha": ctx["pr_head_sha"],
        "tested_merge_sha": ctx["tested_merge_sha"],
        "tested_tree_sha": ctx["tested_tree_sha"],
        "surface": surface,
        "probe_source_sha256": verifier_sha,
        "selected_input_contract_sha256": sha256_file(root / SELECTED_INPUT_CONTRACT_NAME),
        "runtime_identity_sha256": sha256_file(root / DOC_RUNTIME),
        "normalization_contract_sha256": sha256_file(root / NORMALIZATION_CONTRACT_NAME),
        "evidence_manifest_sha256": manifest_content_digest(other_entries),
    }
    schema_failures = validate_source_evidence(evidence_doc)
    if schema_failures:
        print("finalize_error=source_evidence_invalid:" + ";".join(schema_failures[:5]))
        return 2
    (root / SOURCE_EVIDENCE_NAME).write_text(canonical_serialize(evidence_doc), encoding="utf-8")

    # 4. manifest LAST (P2-6 gap #2 hardening: no writes after this point)
    entries = []
    seen = set()
    for rel in _walk_files(root):
        if rel == MANIFEST_NAME:
            continue
        if rel in seen:
            raise RuntimeError(f"EVIDENCE_MANIFEST_INVALID reason=duplicate_path:{rel}")
        seen.add(rel)
        e = entry(rel)
        entries.append({"path": e[0], "size": e[2], "sha256": e[1]})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "document_type": "EVIDENCE_MANIFEST",
        "entries": entries,
    }
    (root / MANIFEST_NAME).write_bytes(canonical_serialize(manifest).encode())

    tree_entries = []
    for rel in _walk_files(root):
        e = entry(rel)
        tree_entries.append(e)
    tree_sha = sha256_bytes(canonical_serialize(sorted(tree_entries, key=lambda e: e[0])).encode())
    print("EVIDENCE_MANIFEST_COMPLETE=true")
    print(f"MANIFEST_ENTRY_COUNT={len(entries)}")
    print(f"BUNDLE_TREE_SHA256={tree_sha}")
    print(f"VERIFIER_SHA256={verifier_sha}")
    print(f"SOURCE_EVIDENCE_SHA256={sha256_file(root / SOURCE_EVIDENCE_NAME)}")
    print("SOURCE_EVIDENCE_SCHEMA_VALID=true")
    print("FINALIZE_RULE=MANIFEST_LAST_NO_FURTHER_WRITES")
    return 0


# ---------------------------------------------------------------------------
# verify-bundle (offline replay; run the bundle's OWN verifier_source.py)


REQUIRED_BUNDLE_FILES = [
    PROBE_NAME,
    RECEIPT_NAME,
    SOURCE_EVIDENCE_NAME,
    DOC_RUNTIME,
    DOC_NORMALIZED,
    SELECTED_INPUT_CONTRACT_NAME,
    NORMALIZATION_CONTRACT_NAME,
    "runtime_resolution_report.json",
    "build_contract.json",
    "build_env_identity.json",
    "exact_build_environment.txt",
    "normalization_proof.json",
    "source_built_install_report.json",
    "installed_payload_verify.json",
    "final_runtime_inventory.json",
    "shadow_surface_result.json",
    "wheel_validation_1.json",
    "wheel_validation_2.json",
    "positive_control/positive_control_verify.json",
    "mutation_negative/mutation_negative_verify.json",
    "sdist_download.log",
    "source_build_1.log",
    "source_build_2.log",
    "source_built_install.log",
    "installed_entries.json",
]


class BundleVerifier:
    def __init__(self, root: Path):
        self.root = root
        self.checks = {}
        self.errors = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks[name] = bool(ok)
        if not ok:
            self.errors.append(f"{name}:{detail}".rstrip(":"))

    def run(self) -> dict:
        summary_p = self.root / PROBE_NAME
        s = {}
        if summary_p.is_file():
            for ln in summary_p.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in ln:
                    k, _, v = ln.partition("=")
                    s[k] = v
        self.check("summary_present", bool(s), PROBE_NAME)

        # manifest gates
        manifest_p = self.root / MANIFEST_NAME
        self.check("manifest_present", manifest_p.is_file())
        manifest = None
        if manifest_p.is_file():
            try:
                manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
                self.check(
                    "manifest_schema",
                    manifest.get("schema_version") == SCHEMA_VERSION
                    and isinstance(manifest.get("entries"), list),
                    "schema_version",
                )
            except Exception as exc:
                self.check("manifest_schema", False, str(exc))

        by_path = {}
        if manifest is not None:
            dup = False
            for e in manifest.get("entries", []):
                path = e.get("path")
                if path in by_path:
                    dup = True
                by_path[path] = e
            self.check("manifest_duplicate_paths_rejected", not dup, "duplicate_path")
            missing = sorted(f for f in REQUIRED_BUNDLE_FILES if f not in by_path)
            self.check("manifest_complete", not missing, ",".join(missing))
            hashes_ok = True
            for path, e in by_path.items():
                p = self.root / path
                if not p.is_file() or p.stat().st_size != e.get("size") or sha256_file(p) != e.get("sha256"):
                    hashes_ok = False
                    break
            self.check("manifest_hashes", hashes_ok)
        else:
            # fail closed: no parsed manifest means no trust anchor at all
            self.check("manifest_duplicate_paths_rejected", False, "no_manifest")
            self.check("manifest_complete", False, "no_manifest")
            self.check("manifest_hashes", False, "no_manifest")

        # verifier self-identity
        verifier = self.root / VERIFIER_NAME
        receipt = {}
        if (self.root / RECEIPT_NAME).is_file():
            try:
                receipt = json.loads((self.root / RECEIPT_NAME).read_text(encoding="utf-8"))
            except Exception:
                receipt = {}
        v_self_ok = (
            Path(__file__).resolve() == verifier.resolve()
            and verifier.is_file()
            and receipt.get("verifier_script_sha256") == sha256_file(verifier)
            and VERIFIER_NAME in by_path
            and by_path.get(VERIFIER_NAME, {}).get("sha256") == sha256_file(verifier)
        )
        self.check("verifier_source", v_self_ok, "realpath_or_sha")

        # receipt consistency
        rcpt_ok = (
            receipt.get("schema_version") == SCHEMA_VERSION
            and receipt.get("surface") == s.get("SURFACE")
            and receipt.get("head") == s.get("HEAD")
            and receipt.get("verifier_script_sha256") == sha256_file(verifier)
        )
        self.check("receipt_consistency", bool(rcpt_ok), "surface_head_or_verifier_sha")

        # identity docs
        norm_doc = {}
        doc_present = (self.root / DOC_RUNTIME).is_file() and (self.root / DOC_NORMALIZED).is_file()
        self.check("identity_docs_present", doc_present)
        runtime_doc_ok = False
        if (self.root / DOC_RUNTIME).is_file():
            try:
                runtime_doc = json.loads((self.root / DOC_RUNTIME).read_text(encoding="utf-8"))
                runtime_doc_ok = (
                    runtime_doc.get("schema_version") == SCHEMA_VERSION
                    and runtime_doc.get("document_type") == DOC_RUNTIME
                    and runtime_doc.get("surface") == s.get("SURFACE")
                )
            except Exception as exc:
                runtime_doc_ok = False
        self.check("runtime_identity_doc", runtime_doc_ok, "schema_or_doc_type_or_surface")
        if (self.root / DOC_NORMALIZED).is_file():
            try:
                norm_doc = json.loads((self.root / DOC_NORMALIZED).read_text(encoding="utf-8"))
                schema_ok = norm_doc.get("schema_version") == SCHEMA_VERSION
                fp = norm_doc.get("fingerprint_sha256")
                self.check("identity_doc_schema", schema_ok and bool(fp), "schema_or_fingerprint")
                payload = {k: v for k, v in norm_doc.items() if k not in ("fingerprint_sha256", "raw_diagnostic")}
                payload["raw_diagnostic_sha256"] = norm_doc.get("raw_diagnostic_sha256")
                recomputed = sha256_bytes(canonical_serialize(payload).encode())
                self.check("normalized_identity_digest", bool(fp) and recomputed == fp, "digest_mismatch")
            except Exception as exc:
                self.check("identity_doc_schema", False, str(exc))
                self.check("normalized_identity_digest", False, str(exc))
        else:
            self.check("identity_doc_schema", False, "missing")
            self.check("normalized_identity_digest", False, "missing")

        # crash-free + verdict markers
        self.check("summary_crash_free", s.get("MEASURE_CRASH") == "false", s.get("MEASURE_CRASH", ""))
        self.check(
            "normalized_verdict_recorded",
            s.get("EVALUATED_NORMALIZED_INSTALL_ARTIFACT_IDENTITY_VALID") in ("true", "false"),
        )

        # sdist identity
        sdist_ok = s.get("SOURCE_SDIST_HASH_OK") == "true"
        sdist_files = list((self.root / "source_sdist").glob("*.tar.gz")) + list((self.root / "source_sdist").glob("*.zip"))
        sdist_file_ok = len(sdist_files) == 1
        if sdist_file_ok and norm_doc:
            sdist_file_ok = sha256_file(sdist_files[0]) == norm_doc.get("sdist_sha256")
        self.check("sdist_identity", sdist_ok and sdist_file_ok, "hash_or_count")

        # build-env identity
        env_ok = False
        if (self.root / "build_env_identity.json").is_file() and (self.root / "exact_build_environment.txt").is_file():
            try:
                env_doc = json.loads((self.root / "build_env_identity.json").read_text(encoding="utf-8"))
                env_inv = env_doc.get("source_build_environment", {}).get("distributions", [])
                recomputed = sha256_bytes(canonical_serialize(env_inv).encode())
                req_sha = sha256_file(self.root / "exact_build_environment.txt")
                env_ok = (
                    recomputed == env_doc["source_build_environment"]["identity_sha256"]
                    and req_sha == env_doc["source_build_environment"]["requirements_file_sha256"]
                    and s.get("SOURCE_BUILD_ENVIRONMENT_SHA256") == env_doc["source_build_environment"]["identity_sha256"]
                )
            except Exception:
                env_ok = False
        self.check("build_env_identity", env_ok, "recompute_or_requirements")

        # raw wheel bytes + validation + payload + normalization (re-derive)
        raws = {}
        invs = {}
        for i in (1, 2):
            wheels = list((self.root / "built_wheels" / str(i)).glob("*.whl"))
            if len(wheels) == 1:
                try:
                    raws[i] = wheels[0].read_bytes()
                    invs[i] = inventory_wheel(wheels[0])
                except Exception:
                    invs[i] = None
        self.check(
            "built_wheels_present",
            len(raws) == 2
            and all(inv is not None and inv.structural_valid and inv.record_valid for inv in invs.values()),
            "count_or_validate",
        )
        raw_ok = (
            raw_shas_match("1", raws, s)
            and raw_shas_match("2", raws, s)
            and norm_doc.get("raw_diagnostic", {}).get("raw_wheel_sha256_1") == sha256_bytes(raws.get(1, b""))
        )
        self.check("raw_wheel_shas_match_records", bool(raw_ok), "sha_mismatch")
        if len(invs) == 2 and all(invs.values()):
            payloads = {}
            for i, inv in invs.items():
                payloads[i], _ = payload_sha256(inv.members, inv.record_path)
            pay_ok = (
                payloads[1] == payloads[2]
                and payloads[1] == s.get("WHEEL_PAYLOAD_SHA256")
                and payloads[1] == norm_doc.get("wheel_payload_sha256")
            )
            self.check("payload_identity", pay_ok, "payload_sha_mismatch")
            cmp_res = compare_wheels(invs[1], invs[2])
            cls = classify_raw_mismatch(raws[1], raws[2], invs[1], invs[2], cmp_res)
            norm_ok = (
                cls["verdict"] == (s.get("RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api") == "true")
                and cls["reason"] == s.get("RAW_MISMATCH_REASON_moomoo-api")
                and cmp_res["wheel_payload_match"]
            )
            self.check("normalization_contract", norm_ok, cls["reason"])
        else:
            self.check("normalization_contract", False, "missing_wheels")

        # install report slot binding
        slot_ok = False
        irp = self.root / "source_built_install_report.json"
        if irp.is_file():
            try:
                irep = json.loads(irp.read_text(encoding="utf-8"))
                items = irep.get("install", [])
                if len(items) == 1:
                    dl = items[0].get("download_info", {}) or {}
                    url = (dl.get("url", "") or "").split("#", 1)[0]
                    arch = dl.get("archive_info", {}) or {}
                    w1 = list((self.root / "built_wheels" / "1").glob("*.whl"))
                    slot_ok = (
                        len(w1) == 1
                        and url.endswith(f"built_wheels/1/{w1[0].name}")
                        and (arch.get("hashes", {}) or {}).get("sha256") == sha256_bytes(raws.get(1, b""))
                    )
            except Exception:
                slot_ok = False
        self.check("install_report_slot", slot_ok, "url_or_sha")

        # installed payload identity (recompute from retained tree)
        inst_ok = False
        if (self.root / "installed_payload").is_dir():
            try:
                ip, ic = installed_payload_sha256(self.root / "installed_payload")
                inst_ok = (
                    ip == s.get("INSTALLED_PAYLOAD_SHA256")
                    and ip == s.get("WHEEL_PAYLOAD_SHA256")
                    and ip == norm_doc.get("installed_payload_sha256")
                )
            except Exception:
                inst_ok = False
        self.check("installed_payload_identity", inst_ok, "recompute_mismatch")

        # positive control (re-derive: patched wheel within contract)
        pos_ok = False
        pos_verify = self.root / "positive_control" / "positive_control_verify.json"
        if pos_verify.is_file():
            try:
                pv = json.loads(pos_verify.read_text(encoding="utf-8"))
                cw = list((self.root / "positive_control").glob("*.whl"))
                pos_ok = (
                    len(cw) == 1
                    and pv.get("verdict") is True
                    and pv.get("payload_match") is True
                    and pv.get("raw_different") is True
                    and pv.get("installed_payload_match") is True
                    and s.get("POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK_moomoo-api") == "true"
                )
            except Exception:
                pos_ok = False
        self.check("positive_control", pos_ok, "verdict_or_payload")

        # mutation negative (re-derive: both variants rejected)
        mut_ok = False
        mut_verify = self.root / "mutation_negative" / "mutation_negative_verify.json"
        if mut_verify.is_file():
            try:
                mv = json.loads(mut_verify.read_text(encoding="utf-8"))
                stale = list((self.root / "mutation_negative" / "stale").glob("*.whl"))
                consistent = list((self.root / "mutation_negative" / "consistent").glob("*.whl"))
                try:
                    stale_inv = inventory_wheel(stale[0]) if len(stale) == 1 else None
                except Exception:
                    stale_inv = None
                try:
                    consistent_inv = inventory_wheel(consistent[0]) if len(consistent) == 1 else None
                except Exception:
                    consistent_inv = None
                con_payload = None
                if consistent_inv is not None:
                    con_payload, _ = payload_sha256(consistent_inv.members, consistent_inv.record_path)
                mut_ok = (
                    stale_inv is not None and not stale_inv.record_valid
                    and consistent_inv is not None and consistent_inv.record_valid
                    and con_payload != norm_doc.get("wheel_payload_sha256")
                    and mv.get("rejected") is True
                    and s.get("MUTATED_WHEEL_REJECTED_moomoo-api") == "true"
                )
            except Exception:
                mut_ok = False
        self.check("mutation_negative", mut_ok, "record_or_payload")

        # runtime closure
        runtime_ok = (
            s.get("FINAL_RUNTIME_MATCH") == "true"
            and s.get("RUNTIME_INSTALL_FROM_WHEELS_ONLY") == "true"
            and s.get("UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL") == "false"
            and s.get("SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL") == "true"
            and s.get("SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL") == "true"
        )
        self.check("runtime_closure", runtime_ok, "runtime_markers")

        # shadow surface
        shadow_ok = s.get("SHADOW_SURFACE_PASS") == "true"
        if (self.root / "shadow_surface_result.json").is_file():
            try:
                sr = json.loads((self.root / "shadow_surface_result.json").read_text(encoding="utf-8"))
                shadow_ok = shadow_ok and sr.get("pass") is True
            except Exception:
                shadow_ok = False
        self.check("shadow_surface", shadow_ok, "surface_marker")

        # closed-world contract marker
        self.check(
            "closed_world_contract",
            s.get("P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED") == "true",
            "contract_marker",
        )

        # raw-mismatch reason is always recorded (diagnostic continuity)
        self.check(
            "raw_mismatch_reason_recorded",
            bool(s.get("RAW_MISMATCH_REASON_moomoo-api")),
            "reason_missing",
        )

        # ---------------------------------------------------------------
        # P2-9 source evidence gates (Section 4/5/8/10 of the spec)

        # source evidence doc: exact 15-key schema
        evidence = {}
        self.check("source_evidence_present", (self.root / SOURCE_EVIDENCE_NAME).is_file())
        if (self.root / SOURCE_EVIDENCE_NAME).is_file():
            try:
                evidence = json.loads((self.root / SOURCE_EVIDENCE_NAME).read_text(encoding="utf-8"))
            except Exception as exc:
                self.check("source_evidence_schema", False, str(exc))
            else:
                schema_failures = validate_source_evidence(evidence)
                self.check("source_evidence_schema", not schema_failures, ";".join(schema_failures[:5]))
        else:
            self.check("source_evidence_schema", False, "missing")

        # digest bindings (mutual seal): probe source, contracts, runtime
        # identity doc, and the manifest content digest
        binding_ok = (
            evidence.get("probe_source_sha256") == sha256_file(verifier)
            and evidence.get("selected_input_contract_sha256") == sha256_file(self.root / SELECTED_INPUT_CONTRACT_NAME)
            and evidence.get("runtime_identity_sha256") == sha256_file(self.root / DOC_RUNTIME)
            and evidence.get("normalization_contract_sha256") == sha256_file(self.root / NORMALIZATION_CONTRACT_NAME)
            and evidence.get("probe_source_sha256") == s.get("PROBE_SOURCE_SHA256")
            and evidence.get("selected_input_contract_sha256") == s.get("SELECTED_INPUT_CONTRACT_SHA256")
            and evidence.get("normalization_contract_sha256") == s.get("NORMALIZATION_CONTRACT_SHA256")
        )
        self.check("source_evidence_bindings", bool(binding_ok), "digest_binding_mismatch")

        # manifest content digest (evidence_manifest_sha256 derivation)
        ev_manifest_ok = False
        if manifest is not None:
            entries = [
                [e.get("path"), e.get("sha256"), e.get("size")]
                for e in manifest.get("entries", [])
                if e.get("path") != SOURCE_EVIDENCE_NAME
            ]
            try:
                ev_manifest_ok = manifest_content_digest(entries) == evidence.get("evidence_manifest_sha256")
            except Exception:
                ev_manifest_ok = False
        self.check("evidence_manifest_binding", bool(ev_manifest_ok), "manifest_content_digest_mismatch")

        # run binding (tree/run): evidence <-> receipt <-> probe summary
        run_ok = (
            receipt.get("repository") == evidence.get("repository") == EXPECTED_REPOSITORY
            and receipt.get("workflow") == evidence.get("workflow") == EXPECTED_WORKFLOW
            and receipt.get("run_id") == evidence.get("run_id")
            and receipt.get("run_attempt") == evidence.get("run_attempt")
            and receipt.get("pr_number") == evidence.get("pr_number")
            and receipt.get("pr_head_sha") == evidence.get("pr_head_sha")
            and receipt.get("tested_merge_sha") == evidence.get("tested_merge_sha")
            and receipt.get("tested_tree_sha") == evidence.get("tested_tree_sha")
            and str(receipt.get("run_id")) == s.get("RUN_ID")
            and str(receipt.get("run_attempt")) == s.get("RUN_ATTEMPT")
            and str(receipt.get("pr_number")) == s.get("PR_NUMBER")
            and receipt.get("pr_head_sha") == s.get("PR_HEAD_SHA")
            and receipt.get("tested_merge_sha") == s.get("TESTED_MERGE_SHA")
            and receipt.get("tested_tree_sha") == s.get("TESTED_TREE_SHA")
        )
        self.check("run_binding", bool(run_ok), "run_tree_identifier_mismatch")

        # surface binding across evidence / receipt / summary / contract docs
        surface_ok = (
            evidence.get("surface") == receipt.get("surface")
            == s.get("SURFACE") == surface_of(summary_p)
            and norm_doc.get("surface") == s.get("SURFACE")
        )
        self.check("surface_binding", bool(surface_ok), "surface_mismatch")

        # selected-input contract doc self-consistency
        sel_ok = False
        if (self.root / SELECTED_INPUT_CONTRACT_NAME).is_file():
            try:
                sel = json.loads((self.root / SELECTED_INPUT_CONTRACT_NAME).read_text(encoding="utf-8"))
                files = sel.get("selectors", {}).get("files")
                sel_ok = (
                    sel.get("schema_version") == SCHEMA_VERSION
                    and sel.get("document_type") == "selected_input_contract"
                    and sel.get("surface") == s.get("SURFACE")
                    and isinstance(files, list)
                    and files == sorted(files)
                    and len(files) == len(set(files))
                    and sel.get("selectors", {}).get("file_count") == len(files)
                    and sel["target_relation"].get("target_file") == TARGET_FILE
                    and sel["target_relation"].get("selected_by_this_surface")
                    == (TARGET_FILE in files)
                )
            except Exception:
                sel_ok = False
        self.check("selected_input_contract", bool(sel_ok), "schema_or_relation")

        # normalization contract doc self-consistency (P2-7 semantics)
        norm_contract_ok = False
        if (self.root / NORMALIZATION_CONTRACT_NAME).is_file():
            try:
                nc = json.loads((self.root / NORMALIZATION_CONTRACT_NAME).read_text(encoding="utf-8"))
                norm_contract_ok = (
                    nc.get("schema_version") == SCHEMA_VERSION
                    and nc.get("document_type") == "normalization_contract"
                    and nc.get("surface") == s.get("SURFACE")
                    and nc.get("allowed_difference")
                    == "zip_dos_modification_timestamps_of_build_generated_members_only"
                    and isinstance(nc.get("fail_close_fields"), list) and len(nc["fail_close_fields"]) >= 15
                    and nc.get("unclassified_raw_difference_required_zero") is True
                    and nc.get("raw_differs_but_payload_same_never_accepted") is True
                    and isinstance(nc.get("digest_derivations"), dict)
                    and "evidence_manifest_sha256" in nc["digest_derivations"]
                )
            except Exception:
                norm_contract_ok = False
        self.check("normalization_contract_doc", bool(norm_contract_ok), "contract_literal")

        # closure: every file on disk must be manifest-bound, and every
        # manifest entry must match disk (post-manifest writes are orphans).
        # The manifest file itself is the seal and cannot list itself, so it
        # is excluded from the disk side (its own integrity is covered by
        # manifest_hashes over the other entries + the replay tree sha).
        # BUNDLE_EXCLUDED_TOPS are reconstruction inputs, never evidence.
        disk_rels = set()
        for p in self.root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix().replace("\\", "/")
                if rel == MANIFEST_NAME:
                    continue
                if rel.split("/", 1)[0] in BUNDLE_EXCLUDED_TOPS:
                    continue
                disk_rels.add(rel)
        self.check(
            "no_orphan_files",
            manifest is not None and disk_rels == set(by_path),
            "post_manifest_write_or_untracked_file",
        )

        ok = all(self.checks.values())
        return {
            "EVIDENCE_BUNDLE_REPLAY_OK": ok,
            "failed_checks": self.errors,
            "check_count": len(self.checks),
            "checks": self.checks,
        }


def surface_of(summary_p: Path) -> str | None:
    if not summary_p.is_file():
        return None
    for ln in summary_p.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("SURFACE="):
            return ln.split("=", 1)[1]
    return None


def raw_shas_match(key: str, raws: dict, s: dict) -> bool:
    raw = raws.get(int(key))
    if raw is None:
        return False
    return sha256_bytes(raw) == s.get(f"RAW_WHEEL_SHA256_{key}")


def _replay_summary(root: Path, result: dict) -> list:
    tree_entries = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix().replace("\\", "/")
            if rel.split("/", 1)[0] in BUNDLE_EXCLUDED_TOPS:
                continue
            tree_entries.append([rel, sha256_file(p), p.stat().st_size])
    tree_sha = sha256_bytes(canonical_serialize(sorted(tree_entries, key=lambda e: e[0])).encode())
    lines = [
        f"EVIDENCE_BUNDLE_REPLAY_OK={'true' if result['EVIDENCE_BUNDLE_REPLAY_OK'] else 'false'}",
        f"CHECK_COUNT={result['check_count']}",
        f"REPLAY_BUNDLE_TREE_SHA256={tree_sha}",
    ]
    for err in result["failed_checks"]:
        lines.append(f"FAILED_CHECK={err}")
    return lines


def _write_summary(lines: list, summary_out: str | None) -> None:
    if summary_out:
        p = Path(summary_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        for ln in lines:
            print(ln)


def cmd_verify_bundle(args) -> int:
    root = Path(args.bundle_dir).resolve()
    v = BundleVerifier(root)
    result = v.run()
    lines = _replay_summary(root, result)
    _write_summary(lines, args.summary_out)
    return 0 if result["EVIDENCE_BUNDLE_REPLAY_OK"] else 2


def cmd_verify_retained(args) -> int:
    """Package-job post-upload replay: the downloaded artifact must bind
    exact head / run / attempt / surface by name, replay read-only, and
    record a roundtrip receipt OUTSIDE the bundle. The downloaded original
    bundle is never mutated or re-uploaded."""
    root = Path(args.bundle_dir).resolve()
    ctx = run_context(Path(args.repo).resolve())
    expected_name = (
        f"{P2_9_ARTIFACT_PREFIX}-{args.surface}-"
        f"{ctx['pr_head_sha']}-attempt-{ctx['run_attempt']}"
    )
    name_ok = args.name == expected_name
    if not name_ok:
        lines = [
            "ROUNDTRIP_RECEIPT=INVALID",
            f"FAILED_CHECK=artifact_name_binding:expected_{expected_name}_got:{args.name}",
        ]
        _write_summary(lines, args.summary_out)
        return 2
    if args.surface not in SURFACES:
        lines = ["ROUNDTRIP_RECEIPT=INVALID", f"FAILED_CHECK=surface_invalid:{args.surface}"]
        _write_summary(lines, args.summary_out)
        return 2

    v = BundleVerifier(root)
    result = v.run()
    lines = _replay_summary(root, result)
    lines.append(f"ROUNDTRIP_RECEIPT={'OK' if result['EVIDENCE_BUNDLE_REPLAY_OK'] else 'INVALID'}")
    lines.append(f"ARTIFACT_NAME={args.name}")
    lines.append("ROUNDTRIP_RULE=READ_ONLY_REPLAY_NO_MUTATION_NO_REUPLOAD")
    _write_summary(lines, args.summary_out)
    return 0 if result["EVIDENCE_BUNDLE_REPLAY_OK"] else 2


def cmd_validate_evidence(args) -> int:
    doc = json.loads(Path(args.doc).read_text(encoding="utf-8"))
    failures = validate_source_evidence(doc)
    if failures:
        print("SOURCE_EVIDENCE_VALID=false")
        for f in failures:
            print(f"error: {f}")
        return 1
    print("SOURCE_EVIDENCE_VALID=true")
    return 0


# ---------------------------------------------------------------------------
# CLI


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ci_p29_production_topology_shadow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe", help="full per-surface source measurement")
    p_probe.add_argument("--out-dir", required=True)
    p_probe.add_argument("--surface", required=True, choices=list(SURFACES))
    p_probe.add_argument("--head", required=True)
    p_probe.add_argument("--repo", required=True)
    p_probe.set_defaults(func=cmd_probe)

    p_fin = sub.add_parser("finalize", help="assemble source evidence bundle (manifest last)")
    p_fin.add_argument("--out-dir", required=True)
    p_fin.add_argument("--surface", required=True, choices=list(SURFACES))
    p_fin.add_argument("--head", required=True)
    p_fin.add_argument("--repo", required=True)
    p_fin.set_defaults(func=cmd_finalize)

    p_verify = sub.add_parser("verify-bundle", help="offline replay of a source evidence bundle")
    p_verify.add_argument("--bundle-dir", required=True)
    p_verify.add_argument("--summary-out")
    p_verify.set_defaults(func=cmd_verify_bundle)

    p_ret = sub.add_parser("verify-retained", help="package-job post-upload replay")
    p_ret.add_argument("--bundle-dir", required=True)
    p_ret.add_argument("--name", required=True)
    p_ret.add_argument("--surface", required=True, choices=list(SURFACES))
    p_ret.add_argument("--repo", required=True)
    p_ret.add_argument("--summary-out")
    p_ret.set_defaults(func=cmd_verify_retained)

    p_val = sub.add_parser("validate-evidence", help="validate a source evidence doc")
    p_val.add_argument("--doc", required=True)
    p_val.set_defaults(func=cmd_validate_evidence)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
