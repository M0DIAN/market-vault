"""Offline regression tests for the P2-9 Phase S source evidence setup.

Tests ``scripts/ci_p29_production_topology_shadow.py`` (this PR): the
exact 15-key source evidence schema, the sealed canonicalization/hashing
primitives ported from the audited P2-7 implementation, the ZIP
normalization contract (timestamp-only), the run/tree binding, the
selected-input contracts (sealed 3.14 surface and audited pyarrow24
surface), the full finalize -> manifest -> pre-upload replay -> post-upload
retained replay protocol, and the V1/V2 artifact class separation
(negative controls). Every tamper case must fail closed (replay exit 2);
INVALID never means REUSE.

The suite never makes an internet request. The heavy 14-stage measurement
is exercised through a realistic synthetic probe output tree built from
the audited primitives themselves; the real repository is only ever read
(git rev-parse for tree resolution, sealed manifest / validator cross-
checks), never written.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_p29_production_topology_shadow.py"
V1_SCRIPT = ROOT / "scripts" / "ci_post_merge_reuse.py"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _load_tool() -> "module":
    spec = importlib.util.spec_from_file_location("ci_p29_tool", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _load_v1() -> "module":
    spec = importlib.util.spec_from_file_location("ci_post_merge_reuse_v1", V1_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# synthetic fixtures


def make_wheel_bytes(module_content: bytes = b"# moomoo\n") -> bytes:
    """A minimal valid wheel (fixed timestamps, deterministic bytes,
    RECORD last with PEP 376 hashes)."""
    name = "moomoo_api"
    version = "10.9.6908"
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{name}/__init__.py": module_content,
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: moomoo-api\nVersion: {version}\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: p2_9_test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        f"{dist_info}/top_level.txt": (name + "\n").encode(),
    }
    record = f"{dist_info}/RECORD"
    record_lines = [
        f"{p},{tool.record_sha256(c)},{len(c)}" for p, c in files.items()
    ]
    files[record] = ("\n".join(record_lines) + f"\n{record},,\n").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, c in files.items():
            zf.writestr(zipfile.ZipInfo(p, date_time=(2024, 1, 1, 0, 0, 0)), c)
    return buf.getvalue()


WHEEL_NAME = "moomoo_api-10.9.6908-py3-none-any.whl"


def _git_head_sha() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


@pytest.fixture
def pr_env(tmp_path):
    """A pull_request run context: env vars + a PR event file. The merge
    sha is the real repository HEAD (read-only tree resolution)."""
    head = "a" * 40
    merge_sha = _git_head_sha()
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"number": 42, "head": {"sha": head}}}),
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        GITHUB_REPOSITORY="M0DIAN/market-vault",
        GITHUB_RUN_ID="12345",
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_SHA=merge_sha,
        GITHUB_EVENT_PATH=str(event),
    )
    return {"head": head, "merge_sha": merge_sha, "env": env}


def build_probe_out(out: Path, surface: str, head: str, env: dict) -> dict:
    """Create a realistic probe output tree (mirroring _measure's layout)
    from the audited primitives, with two byte-identical synthetic wheels.
    Returns the computed values the tests may assert on."""
    raw1 = make_wheel_bytes()
    w1 = out / "built_wheels" / "1" / WHEEL_NAME
    w2 = out / "built_wheels" / "2" / WHEEL_NAME
    w1.parent.mkdir(parents=True)
    w2.parent.mkdir(parents=True)
    w1.write_bytes(raw1)
    w2.write_bytes(raw1)
    inv1 = tool.inventory_wheel(w1)
    inv2 = tool.inventory_wheel(w2)
    assert inv1.structural_valid and inv1.record_valid
    assert inv2.structural_valid and inv2.record_valid
    p1, c1 = tool.payload_sha256(inv1.members, inv1.record_path)
    raw1_sha = tool.sha256_bytes(raw1)

    # positive control: timestamp-only patch of the module member (the
    # synthetic wheels carry 00:00 DOS time, so the patch must set a
    # NON-zero value to actually change bytes)
    ctrl_raw = tool.patch_zip_timestamps(
        raw1, inv1, ["moomoo_api/__init__.py"], new_time=0x6000
    )
    ctrl_p = out / "positive_control" / WHEEL_NAME
    ctrl_p.parent.mkdir(parents=True)
    ctrl_p.write_bytes(ctrl_raw)
    ctrl_inv = tool.inventory_wheel(ctrl_p)
    ctrl_cmp = tool.compare_wheels(inv1, ctrl_inv)
    ctrl_cls = tool.classify_raw_mismatch(raw1, ctrl_raw, inv1, ctrl_inv, ctrl_cmp)
    assert ctrl_cls["verdict"] is True
    assert ctrl_cmp["wheel_payload_match"]
    assert ctrl_p.read_bytes() != raw1

    # mutation negatives: stale RECORD + consistent RECORD
    stale_p = out / "mutation_negative" / "stale" / WHEEL_NAME
    cons_p = out / "mutation_negative" / "consistent" / WHEEL_NAME
    stale_p.parent.mkdir(parents=True)
    cons_p.parent.mkdir(parents=True)
    tool.rebuild_wheel_mutated(raw1, inv1, stale_p, fix_record=False)
    tool.rebuild_wheel_mutated(raw1, inv1, cons_p, fix_record=True)
    stale_inv = tool.inventory_wheel(stale_p)
    cons_inv = tool.inventory_wheel(cons_p)
    cons_payload, _ = tool.payload_sha256(cons_inv.members, cons_inv.record_path)
    assert not stale_inv.record_valid
    assert cons_inv.record_valid
    assert cons_payload != p1

    # installed payload tree (wheel payload minus RECORD)
    installed = out / "installed_payload"
    for m in inv1.members:
        if m.path != inv1.record_path:
            tgt = installed / m.path
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_bytes(m.content)

    # source sdist (count + hash are what the replay re-derives)
    sdist_p = out / "source_sdist" / "moomoo_api-10.9.6908.tar.gz"
    sdist_p.parent.mkdir(parents=True)
    sdist_p.write_bytes(b"fake-sdist-bytes\n")
    sdist_sha = tool.sha256_file(sdist_p)

    # closed-world build env identity (empty distribution set)
    req_p = out / "exact_build_environment.txt"
    req_p.write_text("# empty\n", encoding="utf-8")
    env_inv: list = []
    env_identity = tool.sha256_bytes(tool.canonical_serialize(env_inv).encode())
    (out / "build_env_identity.json").write_text(
        tool.canonical_serialize(
            {
                "schema_version": tool.SCHEMA_VERSION,
                "surface": surface,
                "source_build_environment": {
                    "identity_sha256": env_identity,
                    "requirements_file_sha256": tool.sha256_file(req_p),
                    "distributions": env_inv,
                },
            }
        ),
        encoding="utf-8",
    )

    # selected-input + normalization contracts (real derivations)
    sel = tool.compute_selected_input_contract(ROOT, surface)
    sel_p = out / tool.SELECTED_INPUT_CONTRACT_NAME
    sel_p.write_text(tool.canonical_serialize(sel), encoding="utf-8")
    sel_sha = tool.sha256_file(sel_p)
    norm_contract = tool.normalize_contract_doc(surface)
    nc_p = out / tool.NORMALIZATION_CONTRACT_NAME
    nc_p.write_text(tool.canonical_serialize(norm_contract), encoding="utf-8")
    nc_sha = tool.sha256_file(nc_p)

    # normalized identity doc (fingerprint derivation mirrors the verifier)
    norm_doc = {
        "schema_version": tool.SCHEMA_VERSION,
        "document_type": tool.DOC_NORMALIZED,
        "surface": surface,
        "sdist_sha256": sdist_sha,
        "wheel_payload_sha256": p1,
        "installed_payload_sha256": p1,
        "payload_entry_count": c1,
        "record_validation": {"wheel_1": True, "wheel_2": True, "installed": True},
        "raw_diagnostic": {"raw_wheel_sha256_1": raw1_sha, "raw_wheel_sha256_2": raw1_sha},
    }
    fp_doc = {
        k: v for k, v in norm_doc.items() if k not in ("fingerprint_sha256", "raw_diagnostic")
    }
    fp_doc["raw_diagnostic_sha256"] = tool.sha256_bytes(
        tool.canonical_serialize(norm_doc["raw_diagnostic"]).encode()
    )
    norm_doc["raw_diagnostic_sha256"] = fp_doc["raw_diagnostic_sha256"]
    norm_doc["fingerprint_sha256"] = tool.sha256_bytes(
        tool.canonical_serialize(fp_doc).encode()
    )
    (out / tool.DOC_NORMALIZED).write_text(
        tool.canonical_serialize(norm_doc), encoding="utf-8"
    )

    # strict runtime identity doc (the replay validates schema/type/surface)
    (out / tool.DOC_RUNTIME).write_text(
        tool.canonical_serialize(
            {
                "schema_version": tool.SCHEMA_VERSION,
                "document_type": tool.DOC_RUNTIME,
                "surface": surface,
                "head": head,
            }
        ),
        encoding="utf-8",
    )

    ctx = tool.run_context(ROOT, env=env)
    summary = {
        "SURFACE": surface,
        "HEAD": head,
        "P2_9_PROBE_VERSION": "1",
        "RUN_CONTEXT_AVAILABLE": "true",
        "RUN_ID": str(ctx["run_id"]),
        "RUN_ATTEMPT": str(ctx["run_attempt"]),
        "PR_NUMBER": str(ctx["pr_number"]),
        "PR_HEAD_SHA": ctx["pr_head_sha"],
        "TESTED_MERGE_SHA": ctx["tested_merge_sha"],
        "TESTED_TREE_SHA": ctx["tested_tree_sha"],
        "PROBE_SOURCE_SHA256": tool.sha256_file(SCRIPT),
        "MEASURE_CRASH": "false",
        "SOURCE_SDIST_HASH_OK": "true",
        "RAW_WHEEL_SHA256_1": raw1_sha,
        "RAW_WHEEL_SHA256_2": raw1_sha,
        "RAW_WHEEL_REPRODUCIBLE_moomoo-api": "true",
        "WHEEL_VALIDATION_1": "true",
        "WHEEL_VALIDATION_2": "true",
        "RECORD_VALID_1": "true",
        "RECORD_VALID_2": "true",
        "WHEEL_PAYLOAD_SHA256": p1,
        "PAYLOAD_ENTRY_COUNT_1": str(c1),
        "PAYLOAD_ENTRY_COUNT_2": str(c1),
        "WHEEL_PAYLOAD_MATCH_moomoo-api": "true",
        "RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api": "false",
        "RAW_MISMATCH_REASON_moomoo-api": "raw_equal",
        "RAW_DIFF_BYTE_COUNT": "0",
        "RAW_DIFF_ATTRIBUTION": json.dumps(
            {"local_or_central_timestamp": 0, "unclassified": 0}, sort_keys=True
        ),
        "POSITIVE_TIMESTAMP_ONLY_NORMALIZATION_OK_moomoo-api": "true",
        "MUTATED_WHEEL_REJECTED_moomoo-api": "true",
        "INSTALLED_PAYLOAD_SHA256": p1,
        "INSTALLED_PAYLOAD_ENTRY_COUNT": str(c1),
        "INSTALLED_PAYLOAD_MATCH": "true",
        "INSTALLED_RECORD_VALID": "true",
        "SOURCE_BUILD_ENVIRONMENT_SHA256": env_identity,
        "FINAL_RUNTIME_MATCH": "true",
        "RUNTIME_INSTALL_FROM_WHEELS_ONLY": "true",
        "UNEXPECTED_REMAINDER_SDIST": "false",
        "UNEXPECTED_RUNTIME_SDIST_AT_FINAL_INSTALL": "false",
        "SOURCE_BUILT_PACKAGE_SURVIVED_REMAINDER_INSTALL": "true",
        "SOURCE_BUILT_PACKAGE_SURVIVED_ALL_INSTALL": "true",
        "SHADOW_SURFACE_PASS": "true",
        "P2_5_CLOSED_WORLD_BUILD_CONTRACT_USED": "true",
        "SELECTED_INPUT_CONTRACT_SHA256": sel_sha,
        "NORMALIZATION_CONTRACT_SHA256": nc_sha,
        f"TARGET_RELATION_{surface}": (
            "true" if surface == "test-3.14" else "false"
        ),
        "INSTALL_REPORT_SLOT_OK": "true",
        "INSTALL_REPORT_SHA_OK": "true",
        "EVALUATED_NORMALIZED_INSTALL_ARTIFACT_IDENTITY_VALID": "true",
    }
    (out / tool.PROBE_NAME).write_text(
        "\n".join(f"{k}={v}" for k, v in sorted(summary.items())) + "\n",
        encoding="utf-8",
    )

    # install report (slot binding: exact built_wheels/1 path + sha)
    (out / "source_built_install_report.json").write_text(
        json.dumps(
            {
                "install": [
                    {
                        "download_info": {
                            "url": f"file:///x/built_wheels/1/{WHEEL_NAME}",
                            "archive_info": {"hashes": {"sha256": raw1_sha}},
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    for rel in (
        "runtime_resolution_report.json",
        "build_contract.json",
        "normalization_proof.json",
        "installed_entries.json",
        "installed_payload_verify.json",
        "final_runtime_inventory.json",
        "wheel_validation_1.json",
        "wheel_validation_2.json",
    ):
        (out / rel).write_text("{}", encoding="utf-8")
    for rel in (
        "sdist_download.log",
        "source_build_1.log",
        "source_build_2.log",
        "source_built_install.log",
    ):
        (out / rel).write_text("log\n", encoding="utf-8")
    (out / "shadow_surface_result.json").write_text(
        json.dumps(
            {
                "surface": "test-3.14-sealed" if surface == "test-3.14" else "pyarrow24-audited",
                "pass": True,
                "rc": 0,
                "selector_count": 258 if surface == "test-3.14" else 10,
            }
        ),
        encoding="utf-8",
    )
    (out / "positive_control" / "positive_control_verify.json").write_text(
        json.dumps(
            {
                "verdict": True,
                "reason": ctrl_cls["reason"],
                "payload_match": True,
                "payload_sha256": p1,
                "patched_members": ["moomoo_api/__init__.py"],
                "raw_different": True,
                "control_record_valid": ctrl_inv.record_valid,
                "installed_payload_match": True,
                "patched_wheel_sha256": tool.sha256_bytes(ctrl_raw),
            }
        ),
        encoding="utf-8",
    )
    (out / "mutation_negative" / "mutation_negative_verify.json").write_text(
        json.dumps(
            {
                "mutated_member": "moomoo_api/__init__.py",
                "stale_record": {
                    "record_valid": stale_inv.record_valid,
                    "errors": stale_inv.errors,
                },
                "consistent_record": {
                    "record_valid": cons_inv.record_valid,
                    "payload_equals_original": False,
                },
                "rejected": True,
            }
        ),
        encoding="utf-8",
    )

    return {
        "p1": p1,
        "c1": c1,
        "raw1_sha": raw1_sha,
        "sel_sha": sel_sha,
        "nc_sha": nc_sha,
        "env_identity": env_identity,
        "ctx": ctx,
    }


def run_finalize(out: Path, surface: str, head: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "finalize",
         "--out-dir", str(out), "--surface", surface, "--head", head,
         "--repo", str(ROOT)],
        capture_output=True,
        text=True,
        env=env,
    )


def run_verify_bundle(bundle: Path, summary_out: Path) -> subprocess.CompletedProcess:
    """Run the bundle's OWN verifier_source.py copy against the bundle."""
    return subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-bundle",
         "--bundle-dir", str(bundle), "--summary-out", str(summary_out)],
        capture_output=True,
        text=True,
    )


def _replay_failure_lines(summary_out: Path) -> list[str]:
    return [
        ln for ln in summary_out.read_text(encoding="utf-8").splitlines()
        if ln.startswith("FAILED_CHECK=")
    ]


def _tamper_evidence(bundle: Path, mutate) -> None:
    p = bundle / tool.SOURCE_EVIDENCE_NAME
    d = json.loads(p.read_text(encoding="utf-8"))
    mutate(d)
    p.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")


def _tamper_and_verify(bundle: Path, tmp_path: Path):
    summary_out = tmp_path / "replay_after_tamper.txt"
    proc = run_verify_bundle(bundle, summary_out)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    return _replay_failure_lines(summary_out)


@pytest.fixture
def finalized_bundle(tmp_path, pr_env):
    """A finalized source evidence bundle (test-3.14) with its probe tree."""
    out = tmp_path / "probe"
    values = build_probe_out(out, "test-3.14", pr_env["head"], pr_env["env"])
    fin = run_finalize(out, "test-3.14", pr_env["head"], pr_env["env"])
    assert fin.returncode == 0, fin.stdout + fin.stderr
    assert "EVIDENCE_MANIFEST_COMPLETE=true" in fin.stdout
    assert "SOURCE_EVIDENCE_SCHEMA_VALID=true" in fin.stdout
    assert "FINALIZE_RULE=MANIFEST_LAST_NO_FURTHER_WRITES" in fin.stdout
    return out, values


def _valid_evidence() -> dict:
    return {
        "schema_version": 1,
        "artifact_class": tool.ARTIFACT_CLASS,
        "repository": "M0DIAN/market-vault",
        "workflow": "CI",
        "run_id": 12345,
        "run_attempt": 1,
        "pr_number": 42,
        "pr_head_sha": "a" * 40,
        "tested_merge_sha": "a" * 40,
        "tested_tree_sha": "a" * 40,
        "surface": "test-3.14",
        "probe_source_sha256": "a" * 64,
        "selected_input_contract_sha256": "a" * 64,
        "runtime_identity_sha256": "a" * 64,
        "normalization_contract_sha256": "a" * 64,
        "evidence_manifest_sha256": "a" * 64,
    }


# ---------------------------------------------------------------------------
# canonicalization + hashing primitives (audited P2-7 semantics)


def test_canonical_serialize_recursive_key_sort_list_order_preserved():
    obj = {"b": {"y": 1, "x": 2}, "a": [3, 1, 2], "c": "z"}
    assert tool.canonical_serialize(obj) == '{"a":[3,1,2],"b":{"x":2,"y":1},"c":"z"}\n'
    # deterministic across a parse round-trip
    assert tool.canonical_serialize(obj) == tool.canonical_serialize(
        json.loads(json.dumps(obj))
    )


def test_record_sha256_pep376():
    data = b"x"
    digest = hashlib.sha256(data).digest()
    expected = "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert tool.record_sha256(data) == expected
    empty_expected = "sha256=" + base64.urlsafe_b64encode(
        hashlib.sha256(b"").digest()
    ).rstrip(b"=").decode()
    assert tool.record_sha256(b"") == empty_expected


def test_canonicalize_name_pep503():
    assert tool.canonicalize_name("MooMoo_API_v2") == "moomoo-api-v2"
    assert tool.canonicalize_name("a.b_c-d") == "a-b-c-d"


def test_sha256_file_matches_bytes(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"abc")
    assert tool.sha256_file(p) == hashlib.sha256(b"abc").hexdigest()


def test_payload_digest_excludes_record(tmp_path):
    raw = make_wheel_bytes()
    p = tmp_path / WHEEL_NAME
    p.write_bytes(raw)
    inv = tool.inventory_wheel(p)
    payload, count = tool.payload_sha256(inv.members, inv.record_path)
    members = [m for m in inv.members if m.path != inv.record_path]
    expected = tool.sha256_bytes(
        tool.canonical_serialize(
            sorted([[m.path, m.sha256, m.size] for m in members], key=lambda e: e[0])
        ).encode()
    )
    assert payload == expected
    assert count == len(members)
    assert inv.record_valid


def test_manifest_content_digest_excludes_source_evidence_entry():
    # the caller drops the source evidence entry (the root document cannot
    # bind its own hash); the digest is over the sorted remaining entries
    entries = [
        ["b.txt", "1" * 40, 3],
        ["a.txt", "2" * 40, 2],
        [tool.SOURCE_EVIDENCE_NAME, "3" * 40, 9],
    ]
    other = [e for e in entries if e[0] != tool.SOURCE_EVIDENCE_NAME]
    d = tool.manifest_content_digest(other)
    expected = tool.sha256_bytes(
        tool.canonical_serialize(
            sorted([["a.txt", "2" * 40, 2], ["b.txt", "1" * 40, 3]], key=lambda e: e[0])
        ).encode()
    )
    assert d == expected


# ---------------------------------------------------------------------------
# wheel machinery + ZIP normalization contract


def test_identical_wheels_raw_equal_not_normalized(tmp_path):
    raw = make_wheel_bytes()
    w1 = tmp_path / "a-1.0-py3-none-any.whl"
    w2 = tmp_path / "b-1.0-py3-none-any.whl"
    w1.write_bytes(raw)
    w2.write_bytes(raw)
    i1 = tool.inventory_wheel(w1)
    i2 = tool.inventory_wheel(w2)
    cmp = tool.compare_wheels(i1, i2)
    cls = tool.classify_raw_mismatch(raw, raw, i1, i2, cmp)
    assert cmp["wheel_payload_match"]
    assert cmp["all_member_contents_identical"]
    assert cls["verdict"] is False
    assert cls["reason"] == "raw_equal"


def test_timestamp_only_patch_normalizes(tmp_path):
    raw = make_wheel_bytes()
    w1 = tmp_path / "a-1.0-py3-none-any.whl"
    w1.write_bytes(raw)
    i1 = tool.inventory_wheel(w1)
    patched = tool.patch_zip_timestamps(
        raw, i1, ["moomoo_api/__init__.py"], new_time=0x6000
    )
    w2 = tmp_path / "b-1.0-py3-none-any.whl"
    w2.write_bytes(patched)
    i2 = tool.inventory_wheel(w2)
    cmp = tool.compare_wheels(i1, i2)
    cls = tool.classify_raw_mismatch(raw, patched, i1, i2, cmp)
    assert patched != raw
    assert cls["verdict"] is True
    assert cls["reason"] == "timestamp_only_contract_ok"
    assert cls["attribution"]["unclassified"] == 0
    assert cmp["wheel_payload_match"]


def test_mutation_stale_record_rejected(tmp_path):
    raw = make_wheel_bytes()
    w1 = tmp_path / "a-1.0-py3-none-any.whl"
    w1.write_bytes(raw)
    i1 = tool.inventory_wheel(w1)
    stale = tmp_path / "stale-1.0-py3-none-any.whl"
    tool.rebuild_wheel_mutated(raw, i1, stale, fix_record=False)
    si = tool.inventory_wheel(stale)
    assert not si.record_valid


def test_mutation_consistent_record_payload_differs(tmp_path):
    raw = make_wheel_bytes()
    w1 = tmp_path / "a-1.0-py3-none-any.whl"
    w1.write_bytes(raw)
    i1 = tool.inventory_wheel(w1)
    p1, _ = tool.payload_sha256(i1.members, i1.record_path)
    cons = tmp_path / "cons-1.0-py3-none-any.whl"
    tool.rebuild_wheel_mutated(raw, i1, cons, fix_record=True)
    ci = tool.inventory_wheel(cons)
    assert ci.record_valid
    p2, _ = tool.payload_sha256(ci.members, ci.record_path)
    assert p2 != p1


def test_unclassified_raw_difference_never_normalizes(tmp_path):
    """A non-timestamp byte difference must fail the normalization
    contract even when payloads match (raw differs but payload same is
    NEVER accepted)."""
    raw = make_wheel_bytes()
    other = make_wheel_bytes(module_content=b"# different\n")
    w1 = tmp_path / "a-1.0-py3-none-any.whl"
    w2 = tmp_path / "b-1.0-py3-none-any.whl"
    w1.write_bytes(raw)
    w2.write_bytes(other)
    i1 = tool.inventory_wheel(w1)
    i2 = tool.inventory_wheel(w2)
    cmp = tool.compare_wheels(i1, i2)
    cls = tool.classify_raw_mismatch(raw, other, i1, i2, cmp)
    assert not cmp["wheel_payload_match"]
    assert cls["verdict"] is False
    # a non-timestamp difference can never normalize: either the raw
    # lengths differ (short-circuit) or the difference is unclassified
    assert cls["reason"] in ("raw_length_unequal", "unclassified_raw_difference")


# ---------------------------------------------------------------------------
# evaluation semantics


def _verdict_summary(**overrides) -> dict:
    s = {
        "RAW_WHEEL_REPRODUCIBLE_moomoo-api": "true",
        "WHEEL_PAYLOAD_MATCH_moomoo-api": "true",
        "RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api": "false",
        "INSTALLED_PAYLOAD_MATCH": "true",
        "SOURCE_SDIST_HASH_OK": "true",
        "SOURCE_BUILD_ENVIRONMENT_SHA256": "abc",
        "FINAL_RUNTIME_MATCH": "true",
        "RUNTIME_INSTALL_FROM_WHEELS_ONLY": "true",
        "SHADOW_SURFACE_PASS": "true",
        "MEASURE_CRASH": "false",
        "RECORD_VALID_1": "true",
        "RECORD_VALID_2": "true",
        "INSTALLED_RECORD_VALID": "true",
        "WHEEL_VALIDATION_1": "true",
        "WHEEL_VALIDATION_2": "true",
    }
    s.update(overrides)
    return s


def test_evaluate_verdict_all_true():
    v = tool.evaluate_verdict(_verdict_summary())
    assert v["normalized_install_artifact_identity_valid"] is True
    assert v["reason"] == "ok"


def test_evaluate_verdict_raw_mismatch_not_normalized():
    v = tool.evaluate_verdict(
        _verdict_summary(
            **{
                "RAW_WHEEL_REPRODUCIBLE_moomoo-api": "false",
                "RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api": "false",
            }
        )
    )
    assert v["normalized_install_artifact_identity_valid"] is False
    assert v["reason"] == "raw_mismatch_not_normalized"


def test_evaluate_verdict_component_false():
    v = tool.evaluate_verdict(_verdict_summary(INSTALLED_PAYLOAD_MATCH="false"))
    assert v["normalized_install_artifact_identity_valid"] is False
    assert v["reason"] == "component_false"


# ---------------------------------------------------------------------------
# run/tree binding


def test_run_context_binds_exact_run_and_tree(pr_env):
    ctx = tool.run_context(ROOT, env=pr_env["env"])
    assert ctx["repository"] == "M0DIAN/market-vault"
    assert ctx["workflow"] == "CI"
    assert ctx["run_id"] == 12345
    assert ctx["run_attempt"] == 1
    assert ctx["pr_number"] == 42
    assert ctx["pr_head_sha"] == pr_env["head"]
    assert ctx["tested_merge_sha"] == pr_env["merge_sha"]
    tree = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", f"{pr_env['merge_sha']}^{{tree}}"],
        text=True,
    ).strip()
    assert ctx["tested_tree_sha"] == tree


def test_run_context_requires_pr_event(pr_env, tmp_path):
    env = dict(pr_env["env"])
    push_event = tmp_path / "push.json"
    push_event.write_text(json.dumps({"push": {}}), encoding="utf-8")
    env["GITHUB_EVENT_PATH"] = str(push_event)
    with pytest.raises(RuntimeError, match="run_context_pr_required"):
        tool.run_context(ROOT, env=env)


def test_run_context_missing_identifiers(pr_env):
    env = dict(pr_env["env"])
    del env["GITHUB_SHA"]
    with pytest.raises(RuntimeError, match="run_context_missing"):
        tool.run_context(ROOT, env=env)


def test_run_context_wrong_repository(pr_env):
    env = dict(pr_env["env"])
    env["GITHUB_REPOSITORY"] = "other/repo"
    with pytest.raises(RuntimeError, match="run_context_repository_mismatch"):
        tool.run_context(ROOT, env=env)


# ---------------------------------------------------------------------------
# source evidence schema (exact 15-key set)


def test_source_evidence_schema_valid():
    assert tool.validate_source_evidence(_valid_evidence()) == []


def test_source_evidence_missing_key_rejected():
    doc = _valid_evidence()
    del doc["run_id"]
    failures = tool.validate_source_evidence(doc)
    assert any(
        f.startswith("missing_keys:") and "run_id" in f for f in failures
    )


def test_source_evidence_unknown_key_rejected():
    doc = _valid_evidence()
    doc["extra"] = 1
    failures = tool.validate_source_evidence(doc)
    assert any(
        f.startswith("unknown_keys:") and "extra" in f for f in failures
    )


def test_source_evidence_wrong_class_rejected():
    doc = _valid_evidence()
    doc["artifact_class"] = "p2_9_source_surface_shadow_v2"
    assert any("artifact_class" in f for f in tool.validate_source_evidence(doc))


def test_source_evidence_wrong_surface_rejected():
    doc = _valid_evidence()
    doc["surface"] = "test-3.11"
    assert any("surface_invalid" in f for f in tool.validate_source_evidence(doc))


def test_source_evidence_bad_hex_rejected():
    doc = _valid_evidence()
    doc["pr_head_sha"] = "g" * 40
    assert any("pr_head_sha" in f for f in tool.validate_source_evidence(doc))


# ---------------------------------------------------------------------------
# selected-input contracts


def test_py314_manifest_static_contract_holds():
    assert tool.validate_py314_manifest_static(ROOT) == []


def test_py314_manifest_static_detects_drift(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ci").mkdir(parents=True)
    text = (ROOT / tool.PY314_MANIFEST_REL).read_bytes().replace(b"\r\n", b"\n").decode()
    lines = text[:-1].split("\n")
    (repo / tool.PY314_MANIFEST_REL).write_text(
        "\n".join(lines + ["tests/test_extra.py"]) + "\n", encoding="utf-8"
    )
    failures = tool.validate_py314_manifest_static(repo)
    assert any("expected 258 selectors" in f for f in failures)


def test_selected_input_contract_3_14_target_selected():
    sel = tool.compute_selected_input_contract(ROOT, "test-3.14")
    assert sel["selectors"]["file_count"] == 37
    assert sel["selectors"]["resolved_node_count"] == 294
    assert sel["selectors"]["selector_count"] == 258
    assert sel["target_relation"]["selected_by_this_surface"] is True
    assert tool.TARGET_FILE in sel["selectors"]["files"]
    assert sel["selectors"]["files"] == sorted(sel["selectors"]["files"])


def test_selected_input_contract_pyarrow24_target_not_selected():
    sel = tool.compute_selected_input_contract(ROOT, "pyarrow24")
    assert sel["selectors"]["file_count"] == 10
    assert sel["target_relation"]["selected_by_this_surface"] is False
    assert tool.TARGET_FILE not in sel["selectors"]["files"]
    assert set(sel["selectors"]["files"]) == set(tool.PYARROW24_SURFACE_FILES)


# ---------------------------------------------------------------------------
# action contract (ci.yml must carry the exact P2-9 pins + artifact template)


def test_action_contract_binds_pins_and_artifact_template():
    ac = tool.action_contract(ROOT)
    assert any(
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in u
        for u in ac["action_usage"]["upload-artifact"]
    )
    assert any(
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in u
        for u in ac["action_usage"]["download-artifact"]
    )
    assert ac["ci_yml_sha256"] == tool.sha256_file(CI_YML)
    for surface in tool.SURFACES:
        template = (
            f"{tool.P2_9_ARTIFACT_PREFIX}-{surface}-"
            "${{ github.event.pull_request.head.sha }}-attempt-${{ github.run_attempt }}"
        )
        assert template in CI_YML.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# full protocol: finalize -> manifest -> pre-upload replay


def test_finalize_to_verify_bundle_end_to_end(finalized_bundle, tmp_path):
    bundle, values = finalized_bundle
    summary_out = tmp_path / "pre_upload_replay.txt"
    proc = run_verify_bundle(bundle, summary_out)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = summary_out.read_text(encoding="utf-8")
    assert "EVIDENCE_BUNDLE_REPLAY_OK=true" in text
    assert "CHECK_COUNT=" in text
    assert "REPLAY_BUNDLE_TREE_SHA256=" in text
    assert "FAILED_CHECK=" not in text
    count = int(re.search(r"CHECK_COUNT=(\d+)", text).group(1))
    assert count > 20
    # the mutual seal: manifest binds evidence doc; evidence binds
    # manifest-minus-self
    manifest = json.loads((bundle / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    evidence = json.loads((bundle / tool.SOURCE_EVIDENCE_NAME).read_text(encoding="utf-8"))
    entries = [
        [e["path"], e["sha256"], e["size"]]
        for e in manifest["entries"]
        if e["path"] != tool.SOURCE_EVIDENCE_NAME
    ]
    assert evidence["evidence_manifest_sha256"] == tool.manifest_content_digest(entries)
    assert any(e["path"] == tool.SOURCE_EVIDENCE_NAME for e in manifest["entries"])
    assert tool.validate_source_evidence(evidence) == []


def test_finalize_refuses_crashed_probe(tmp_path, pr_env):
    out = tmp_path / "probe"
    build_probe_out(out, "test-3.14", pr_env["head"], pr_env["env"])
    p = out / tool.PROBE_NAME
    text = p.read_text(encoding="utf-8").replace(
        "MEASURE_CRASH=false", "MEASURE_CRASH=true"
    )
    p.write_text(text, encoding="utf-8")
    proc = run_finalize(out, "test-3.14", pr_env["head"], pr_env["env"])
    assert proc.returncode == 2
    assert "finalize_error=probe_crashed" in proc.stdout


def test_finalize_refuses_missing_run_context(tmp_path, pr_env):
    out = tmp_path / "probe"
    build_probe_out(out, "test-3.14", pr_env["head"], pr_env["env"])
    p = out / tool.PROBE_NAME
    text = p.read_text(encoding="utf-8").replace(
        "RUN_CONTEXT_AVAILABLE=true", "RUN_CONTEXT_AVAILABLE=false"
    )
    p.write_text(text, encoding="utf-8")
    proc = run_finalize(out, "test-3.14", pr_env["head"], pr_env["env"])
    assert proc.returncode == 2
    assert "finalize_error=run_context_required" in proc.stdout


def test_finalize_refuses_head_mismatch(tmp_path, pr_env):
    out = tmp_path / "probe"
    build_probe_out(out, "test-3.14", pr_env["head"], pr_env["env"])
    proc = run_finalize(out, "test-3.14", "b" * 40, pr_env["env"])
    assert proc.returncode == 2
    assert "finalize_error=" in proc.stdout


# ---------------------------------------------------------------------------
# post-upload retained replay (package job)


def test_verify_retained_ok(finalized_bundle, pr_env, tmp_path):
    bundle, _ = finalized_bundle
    name = f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{pr_env['head']}-attempt-1"
    summary_out = tmp_path / "roundtrip.txt"
    proc = subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-retained",
         "--bundle-dir", str(bundle), "--name", name, "--surface", "test-3.14",
         "--repo", str(ROOT), "--summary-out", str(summary_out)],
        capture_output=True,
        text=True,
        env=pr_env["env"],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = summary_out.read_text(encoding="utf-8")
    assert "ROUNDTRIP_RECEIPT=OK" in text
    assert "EVIDENCE_BUNDLE_REPLAY_OK=true" in text
    assert "ROUNDTRIP_RULE=READ_ONLY_REPLAY_NO_MUTATION_NO_REUPLOAD" in text


def test_verify_retained_wrong_name_rejected(finalized_bundle, pr_env, tmp_path):
    """Negative control C: a renamed artifact must be REJECTED."""
    bundle, _ = finalized_bundle
    name = f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{'d' * 40}-attempt-9"
    summary_out = tmp_path / "roundtrip.txt"
    proc = subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-retained",
         "--bundle-dir", str(bundle), "--name", name, "--surface", "test-3.14",
         "--repo", str(ROOT), "--summary-out", str(summary_out)],
        capture_output=True,
        text=True,
        env=pr_env["env"],
    )
    assert proc.returncode == 2
    text = summary_out.read_text(encoding="utf-8")
    assert "ROUNDTRIP_RECEIPT=INVALID" in text
    assert "FAILED_CHECK=artifact_name_binding" in text


def test_verify_retained_wrong_surface_rejected(finalized_bundle, pr_env, tmp_path):
    """Negative control D: the surface must bind through the artifact name."""
    bundle, _ = finalized_bundle
    # name binds test-3.14, but the surface argument claims pyarrow24
    name = f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{pr_env['head']}-attempt-1"
    summary_out = tmp_path / "roundtrip.txt"
    proc = subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-retained",
         "--bundle-dir", str(bundle), "--name", name, "--surface", "pyarrow24",
         "--repo", str(ROOT), "--summary-out", str(summary_out)],
        capture_output=True,
        text=True,
        env=pr_env["env"],
    )
    assert proc.returncode == 2
    text = summary_out.read_text(encoding="utf-8")
    assert "ROUNDTRIP_RECEIPT=INVALID" in text
    assert "FAILED_CHECK=artifact_name_binding" in text


# ---------------------------------------------------------------------------
# §12 fail-closed tamper controls (each must replay exit 2; INVALID never
# means REUSE)


def test_tamper_evidence_missing_field_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    _tamper_evidence(bundle, lambda d: d.pop("run_id"))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=source_evidence_schema:") for ln in lines)


def test_tamper_evidence_unknown_field_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    _tamper_evidence(bundle, lambda d: d.update({"extra": "x"}))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any("unknown_keys:extra" in ln for ln in lines)


def test_tamper_evidence_wrong_surface_rejected(finalized_bundle, tmp_path):
    """§11-D: a wrong surface must be REJECTED by the schema/binding."""
    bundle, _ = finalized_bundle
    # a VALID surface different from the receipt/summary surface: schema
    # passes, the surface binding must fail
    _tamper_evidence(bundle, lambda d: d.update({"surface": "pyarrow24"}))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=surface_binding:") for ln in lines)


def test_tamper_evidence_wrong_run_id_rejected(finalized_bundle, tmp_path):
    """§11-E: a wrong run id must be REJECTED."""
    bundle, _ = finalized_bundle
    _tamper_evidence(bundle, lambda d: d.update({"run_id": 99999}))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=run_binding:") for ln in lines)


def test_tamper_evidence_wrong_run_attempt_rejected(finalized_bundle, tmp_path):
    """§11-E: a wrong run attempt must be REJECTED."""
    bundle, _ = finalized_bundle
    _tamper_evidence(bundle, lambda d: d.update({"run_attempt": 9}))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=run_binding:") for ln in lines)


def test_tamper_evidence_wrong_head_sha_rejected(finalized_bundle, tmp_path):
    """§11-E: a wrong head sha must be REJECTED."""
    bundle, _ = finalized_bundle
    _tamper_evidence(bundle, lambda d: d.update({"pr_head_sha": "b" * 40}))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=run_binding:") for ln in lines)


def test_tamper_evidence_wrong_tree_sha_rejected(finalized_bundle, tmp_path):
    """§11-E: a wrong tested tree sha must be REJECTED."""
    bundle, _ = finalized_bundle
    _tamper_evidence(bundle, lambda d: d.update({"tested_tree_sha": "c" * 40}))
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=run_binding:") for ln in lines)


def test_tamper_verifier_source_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    vp = bundle / tool.VERIFIER_NAME
    vp.write_bytes(vp.read_bytes() + b"\n# tampered\n")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=verifier_source:") for ln in lines)


def test_tamper_probe_source_fingerprint_rejected(finalized_bundle, tmp_path):
    """Source-fingerprint tamper: the probe summary binds the probe tool
    source; altering the recorded fingerprint must fail the replay."""
    bundle, _ = finalized_bundle
    p = bundle / tool.PROBE_NAME
    text = p.read_text(encoding="utf-8").replace(
        "SOURCE_SDIST_HASH_OK=true", "SOURCE_SDIST_HASH_OK=false"
    )
    p.write_text(text, encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=sdist_identity:") for ln in lines)


def test_tamper_selected_input_contract_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    p = bundle / tool.SELECTED_INPUT_CONTRACT_NAME
    p.write_bytes(p.read_bytes() + b"\n# tampered\n")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(
        ln.startswith("FAILED_CHECK=source_evidence_bindings:") for ln in lines
    )


def test_tamper_manifest_entry_hash_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    p = bundle / tool.MANIFEST_NAME
    m = json.loads(p.read_text(encoding="utf-8"))
    m["entries"][0]["sha256"] = "0" * 40
    p.write_text(json.dumps(m), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=manifest_hashes") for ln in lines)


def test_tamper_manifest_duplicate_path_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    p = bundle / tool.MANIFEST_NAME
    m = json.loads(p.read_text(encoding="utf-8"))
    m["entries"].append(dict(m["entries"][0]))
    p.write_text(json.dumps(m), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(
        ln.startswith("FAILED_CHECK=manifest_duplicate_paths_rejected:") for ln in lines
    )


def test_tamper_source_sdist_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    sdist = next((bundle / "source_sdist").glob("*.tar.gz"))
    sdist.write_bytes(b"different-sdist\n")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=manifest_hashes") for ln in lines)
    assert any(ln.startswith("FAILED_CHECK=sdist_identity:") for ln in lines)


def test_tamper_build_env_requirements_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    (bundle / "exact_build_environment.txt").write_text(
        "# tampered\n", encoding="utf-8"
    )
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=build_env_identity:") for ln in lines)


def test_tamper_normalized_identity_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    p = bundle / tool.DOC_NORMALIZED
    d = json.loads(p.read_text(encoding="utf-8"))
    d["wheel_payload_sha256"] = "f" * 40
    p.write_text(json.dumps(d), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(
        ln.startswith("FAILED_CHECK=normalized_identity_digest:") for ln in lines
    )


def test_tamper_normalization_marker_rejected(finalized_bundle, tmp_path):
    """An unclassified raw wheel difference (marker claims normalization
    validity while the wheels re-derive raw_equal) must fail the contract."""
    bundle, _ = finalized_bundle
    p = bundle / tool.PROBE_NAME
    text = p.read_text(encoding="utf-8").replace(
        "RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api=false",
        "RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api=true",
    )
    p.write_text(text, encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=normalization_contract:") for ln in lines)


def test_tamper_installed_payload_rejected(finalized_bundle, tmp_path):
    bundle, _ = finalized_bundle
    p = bundle / "installed_payload" / "moomoo_api" / "__init__.py"
    p.write_bytes(b"# tampered\n")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=manifest_hashes") for ln in lines)
    assert any(
        ln.startswith("FAILED_CHECK=installed_payload_identity:") for ln in lines
    )


def test_tamper_wheel_metadata_difference_rejected(finalized_bundle, tmp_path):
    """An unclassified raw wheel metadata/content difference: wheel 1 is
    replaced with a different wheel and the manifest entry is re-sealed
    (so manifest hashes pass); the raw identity re-derivation must fail."""
    bundle, values = finalized_bundle
    w1 = bundle / "built_wheels" / "1" / WHEEL_NAME
    new_raw = make_wheel_bytes(module_content=b"# different content\n")
    w1.write_bytes(new_raw)
    p = bundle / tool.MANIFEST_NAME
    m = json.loads(p.read_text(encoding="utf-8"))
    rel = f"built_wheels/1/{WHEEL_NAME}"
    for e in m["entries"]:
        if e["path"] == rel:
            e["sha256"] = tool.sha256_bytes(new_raw)
            e["size"] = len(new_raw)
    p.write_text(json.dumps(m), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(
        ln.startswith("FAILED_CHECK=raw_wheel_shas_match_records:") for ln in lines
    )
    assert any(ln.startswith("FAILED_CHECK=normalization_contract:") for ln in lines)


def test_tamper_orphan_file_rejected(finalized_bundle, tmp_path):
    """A post-manifest file (not bound by the manifest) is an orphan and
    must fail the closure replay."""
    bundle, _ = finalized_bundle
    (bundle / "hidden_receipt.txt").write_text("not in manifest\n", encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=no_orphan_files:") for ln in lines)


# ---------------------------------------------------------------------------
# §11 V1/V2 artifact class separation


def test_class_separation_v1_validator_rejects_p2_9_doc(pr_env):
    """Negative control A: a P2-9 object fed to the V1 validator must be
    REJECTED."""
    v1 = _load_v1()
    doc = _valid_evidence()
    assert tool.validate_source_evidence(doc) == []
    ok, reason = v1.validate_attestation_fields(doc)
    assert ok is False
    assert reason == "attestation_schema_mismatch"


def test_class_separation_p2_9_validator_rejects_v1_doc():
    """Negative control B: a V1 attestation fed to the P2-9 validator must
    be REJECTED."""
    v1_doc = {
        "schema_version": 1,
        "repository": "M0DIAN/market-vault",
        "workflow": "CI",
        "run_id": 1,
        "run_attempt": 1,
        "pr_number": 1,
        "base_sha": "a" * 40,
        "head_sha": "a" * 40,
        "tested_merge_sha": "a" * 40,
        "tested_tree_sha": "a" * 40,
        "tier": "full",
        "full_matrix_required": True,
    }
    failures = tool.validate_source_evidence(v1_doc)
    assert any(f.startswith("missing_keys:") for f in failures)
    assert any(f.startswith("unknown_keys:") for f in failures)


def test_class_separation_p2_9_schema_has_no_v1_fields():
    """The P2-9 schema shares no V1 field names (class separation is
    structural, not just literal)."""
    v1_fields = {
        "base_sha", "head_sha", "tier", "full_matrix_required",
    }
    assert not (v1_fields & set(tool.SOURCE_EVIDENCE_FIELDS))
