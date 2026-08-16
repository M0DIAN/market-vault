"""Offline regression tests for the P2-9 Phase S source evidence setup.

Tests ``scripts/ci_p29_production_topology_shadow.py`` (this PR): the
exact 16-field source evidence schema, the sealed canonicalization/hashing
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

import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_p29_production_topology_shadow.py"
V1_SCRIPT = ROOT / "scripts" / "ci_post_merge_reuse.py"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"

# Frozen Phase-S commit pair: the original setup commit on top of the
# frozen base. The main-push tests must NOT derive the target from the
# checked-out HEAD — on CI the default pull_request checkout is the
# GitHub PR MERGE commit (two parents: base first, PR head second), a
# merge topology the main-push contract correctly fails closed on. Both
# SHAs exist in every fetch-depth: 0 checkout, so the pair resolves
# identically on any runner.
MAIN_PUSH_TARGET_SHA = "a12694fff7f99e61ec34b787d7147655c81d9008"
MAIN_PUSH_PARENT_SHA = "8b3d789c2445bf3d5b62bfe0e43a5ab9ae18b0ee"

# Phase-S auth contract: a distinctive mocked gh-CLI token used to pin
# that the token VALUE never appears in aggregate log, target evidence,
# source evidence, replay receipt, or exception output.
SENSITIVE_TEST_TOKEN = "ghp_P2_9_SENSITIVE_TOKEN_VALUE_0001"


def _ci_step_regions(ci: str) -> list[tuple[str, str]]:
    """[(step name, step region)] over every '- name:' step of ci.yml."""
    anchors = [(m.start(), m.group(1))
               for m in re.finditer(r"(?m)^      - name: (.+)$", ci)]
    return [
        (name, ci[pos:(anchors[i + 1][0] if i + 1 < len(anchors) else len(ci))])
        for i, (pos, name) in enumerate(anchors)
    ]


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
# source evidence schema (exact 16-field set)


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


def test_class_separation_p2_9_schema_excludes_v1_only_fields():
    """The P2-9 source evidence schema EXCLUDES the V1-only fields
    (base_sha, head_sha, tier, full_matrix_required): class separation is
    structural. Bidirectional rejection is proven by the two tests above
    (a P2-9 object fed to the V1 validator is REJECTED; a V1 attestation
    fed to the P2-9 validator is REJECTED)."""
    v1_only_fields = {
        "base_sha", "head_sha", "tier", "full_matrix_required",
    }
    assert not (v1_only_fields & set(tool.SOURCE_EVIDENCE_FIELDS))


# ---------------------------------------------------------------------------
# independent-review correction: exact schema sets + wording pins


def test_source_evidence_schema_exact_16_field_set():
    """The source evidence schema is the exact 16-field set enumerated in
    Section 4 of the P2-9 Phase S spec. Regression pin for the field set
    (do NOT alter the field set to make the count different)."""
    assert len(tool.SOURCE_EVIDENCE_FIELDS) == 16
    assert set(tool.SOURCE_EVIDENCE_FIELDS) == {
        "schema_version", "artifact_class", "repository", "workflow",
        "run_id", "run_attempt", "pr_number", "pr_head_sha",
        "tested_merge_sha", "tested_tree_sha", "surface",
        "probe_source_sha256", "selected_input_contract_sha256",
        "runtime_identity_sha256", "normalization_contract_sha256",
        "evidence_manifest_sha256",
    }


def test_target_shadow_evidence_schema_exact_25_field_set():
    """The pre-staged target shadow evidence class is the exact 25-field
    set (p2_9_target_shadow_v1), distinct from the V1 FULL attestation and
    from the source evidence class."""
    assert len(tool.TARGET_SHADOW_FIELDS) == 25
    assert set(tool.TARGET_SHADOW_FIELDS) == {
        "schema_version", "artifact_class", "repository", "workflow",
        "run_id", "run_attempt", "target_sha", "parent_sha",
        "target_tree_sha", "parent_tree_sha", "surface", "verdict",
        "reason", "source_pr_number", "source_pr_head_sha", "source_run_id",
        "source_run_attempt", "source_artifact_name", "source_tested_tree_sha",
        "target_runtime_identity_sha256", "delta_identity_sha256",
        "selected_input_verdict", "global_runtime_match",
        "retained_replay_state", "evidence_manifest_sha256",
    }


def test_target_probe_payload_schema_exact_16_field_set():
    assert len(tool.TARGET_PROBE_PAYLOAD_FIELDS) == 16


def _valid_target_evidence(available: bool = False, verdict: str | None = None,
                           runtime_match: bool = False,
                           sel_verdict: str = "affected") -> dict:
    doc = {
        "schema_version": 1,
        "artifact_class": tool.TARGET_ARTIFACT_CLASS,
        "repository": "M0DIAN/market-vault",
        "workflow": "CI",
        "run_id": 42,
        "run_attempt": 1,
        "target_sha": "d" * 40,
        "parent_sha": "e" * 40,
        "target_tree_sha": "f" * 40,
        "parent_tree_sha": "0" * 40,
        "surface": "test-3.14",
        "verdict": verdict or tool.VERDICT_RUN,
        "reason": "run:source_unavailable:source_pr_none",
        "source_pr_number": 0,
        "source_pr_head_sha": "0" * 40,
        "source_run_id": 0,
        "source_run_attempt": 0,
        "source_artifact_name": "",
        "source_tested_tree_sha": "0" * 40,
        "target_runtime_identity_sha256": "1" * 64,
        "delta_identity_sha256": "2" * 64,
        "selected_input_verdict": sel_verdict,
        "global_runtime_match": runtime_match,
        "retained_replay_state": tool.TARGET_RETAINED_REPLAY_STATE,
        "evidence_manifest_sha256": "3" * 64,
    }
    if available:
        doc.update({
            "source_pr_number": 84,
            "source_pr_head_sha": "b" * 40,
            "source_run_id": 777,
            "source_run_attempt": 1,
            "source_artifact_name": (
                f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{'b' * 40}-attempt-1"
            ),
            "source_tested_tree_sha": "c" * 40,
        })
    return doc


def _valid_target_payload() -> dict:
    return {
        "schema_version": 1,
        "artifact_class": tool.TARGET_PROBE_ARTIFACT_CLASS,
        "repository": "M0DIAN/market-vault",
        "workflow": "CI",
        "run_id": 42,
        "run_attempt": 1,
        "surface": "test-3.14",
        "target_sha": "d" * 40,
        "parent_sha": "e" * 40,
        "target_tree_sha": "f" * 40,
        "parent_tree_sha": "0" * 40,
        "runtime_identity_sha256": "1" * 64,
        "runtime_environment_sha256": "2" * 64,
        "normalized_identity_sha256": "3" * 64,
        "selected_input_contract_sha256": "4" * 64,
        "probe_source_sha256": "5" * 64,
    }


def test_target_probe_payload_schema_valid_and_fail_closed():
    assert tool.validate_target_probe_payload(_valid_target_payload()) == []
    missing = _valid_target_payload()
    del missing["normalized_identity_sha256"]
    failures = tool.validate_target_probe_payload(missing)
    assert any(f.startswith("missing_keys:") and "normalized_identity_sha256" in f for f in failures)
    unknown = _valid_target_payload()
    unknown["bogus_field"] = 1
    failures = tool.validate_target_probe_payload(unknown)
    assert any(f.startswith("unknown_keys:") for f in failures)
    bad_class = _valid_target_payload()
    bad_class["artifact_class"] = tool.ARTIFACT_CLASS
    failures = tool.validate_target_probe_payload(bad_class)
    assert any(f.startswith("artifact_class_expected_") for f in failures)


def test_target_shadow_evidence_schema_valid_and_fail_closed():
    # source unavailable (zeroed pattern) + run verdict: valid
    assert tool.validate_target_shadow_evidence(_valid_target_evidence()) == []
    # source available pattern + run verdict: valid
    doc = _valid_target_evidence(available=True, runtime_match=True, sel_verdict="unaffected")
    doc["reason"] = "run:selected_input_affected:runtime_mismatch"
    assert tool.validate_target_shadow_evidence(doc) == []
    # REUSED only when every predicate proves true
    reused = _valid_target_evidence(
        available=True, verdict=tool.VERDICT_REUSED, runtime_match=True,
        sel_verdict="unaffected",
    )
    reused["reason"] = "reused:all_predicates_valid"
    assert tool.validate_target_shadow_evidence(reused) == []
    reused_bad_match = _valid_target_evidence(
        available=True, verdict=tool.VERDICT_REUSED, runtime_match=False,
        sel_verdict="unaffected",
    )
    failures = tool.validate_target_shadow_evidence(reused_bad_match)
    assert any(f == "reused_requires_all_predicates" for f in failures)
    # missing / unknown keys => INVALID
    missing = _valid_target_evidence()
    del missing["delta_identity_sha256"]
    failures = tool.validate_target_shadow_evidence(missing)
    assert any(f.startswith("missing_keys:") and "delta_identity_sha256" in f for f in failures)
    unknown = _valid_target_evidence()
    unknown["bogus_field"] = 1
    failures = tool.validate_target_shadow_evidence(unknown)
    assert any(f.startswith("unknown_keys:") for f in failures)
    # mixed source identity pattern => INVALID
    mixed = _valid_target_evidence(available=True)
    mixed["source_run_id"] = 0
    failures = tool.validate_target_shadow_evidence(mixed)
    assert any(f == "source_identity_pattern_invalid" for f in failures)
    # invalid verdict literal => INVALID
    bad_verdict = _valid_target_evidence()
    bad_verdict["verdict"] = "reuse"
    failures = tool.validate_target_shadow_evidence(bad_verdict)
    assert any(f.startswith("verdict_invalid:") for f in failures)


# ---------------------------------------------------------------------------
# Phase-T pre-stage: main-push target context (fail-closed)


def _main_push_env() -> dict:
    return dict(
        os.environ,
        GITHUB_REPOSITORY="M0DIAN/market-vault",
        GITHUB_WORKFLOW="CI",
        GITHUB_RUN_ID="42",
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_EVENT_NAME="push",
        GITHUB_REF="refs/heads/main",
        GITHUB_SHA=MAIN_PUSH_TARGET_SHA,
    )


def _pr_env_custom(merge_sha: str, run_id: int, attempt: int,
                   pr_number: int, head_sha: str, tmp_path: Path) -> dict:
    event = tmp_path / f"event_{run_id}.json"
    event.write_text(
        json.dumps({"pull_request": {"number": pr_number, "head": {"sha": head_sha}}}),
        encoding="utf-8",
    )
    return dict(
        os.environ,
        GITHUB_REPOSITORY="M0DIAN/market-vault",
        GITHUB_RUN_ID=str(run_id),
        GITHUB_RUN_ATTEMPT=str(attempt),
        GITHUB_SHA=merge_sha,
        GITHUB_EVENT_PATH=str(event),
    )


def test_main_push_context_fails_closed_on_non_push():
    with pytest.raises(RuntimeError, match="main_push_event_required"):
        tool.main_push_context(ROOT, {"GITHUB_EVENT_NAME": "pull_request"})


def test_main_push_context_fails_closed_on_wrong_ref():
    env = _main_push_env()
    env["GITHUB_REF"] = "refs/heads/ci/x"
    with pytest.raises(RuntimeError, match="main_push_ref_required"):
        tool.main_push_context(ROOT, env)


def test_main_push_context_fails_closed_missing_env():
    env = {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "M0DIAN/market-vault",
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "1",
        # GITHUB_SHA missing
    }
    with pytest.raises(RuntimeError, match="main_push_context_missing:.*GITHUB_SHA"):
        tool.main_push_context(ROOT, env)


def test_main_push_context_fails_closed_wrong_repository():
    env = _main_push_env()
    env["GITHUB_REPOSITORY"] = "other/repo"
    with pytest.raises(RuntimeError, match="main_push_repository_mismatch"):
        tool.main_push_context(ROOT, env)


def test_main_push_context_ok_exact_single_parent():
    env = _main_push_env()
    ctx = tool.main_push_context(ROOT, env)
    assert ctx["target_sha"] == MAIN_PUSH_TARGET_SHA
    assert ctx["parent_sha"] == MAIN_PUSH_PARENT_SHA
    assert ctx["parent_sha"] == subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", MAIN_PUSH_TARGET_SHA + "^"],
        text=True,
    ).strip()
    assert ctx["target_tree_sha"] == subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", MAIN_PUSH_TARGET_SHA + "^{tree}"],
        text=True,
    ).strip()
    assert ctx["parent_tree_sha"] == subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", MAIN_PUSH_PARENT_SHA + "^{tree}"],
        text=True,
    ).strip()
    assert ctx["run_id"] == 42 and ctx["run_attempt"] == 1


def test_main_push_context_rejects_merge_topology(tmp_path):
    """A merge commit (two parents) under a single-parent contract must
    fail closed: main_push_parent_expected_single."""
    repo = tmp_path / "r"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "t"],
        check=True, capture_output=True,
    )
    for f in ("a", "b"):
        (repo / f).write_text(f + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", f], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", f], check=True, capture_output=True
        )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", "side", "HEAD~1"],
        check=True, capture_output=True,
    )
    (repo / "c").write_text("c\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "c"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "c"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "master"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "merge", "--no-ff", "-m", "merge", "side"],
        check=True, capture_output=True,
    )
    merge_sha = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    env = _main_push_env()
    env["GITHUB_SHA"] = merge_sha
    with pytest.raises(RuntimeError, match="main_push_parent_expected_single"):
        tool.main_push_context(repo, env)


# ---------------------------------------------------------------------------
# Phase-T pre-stage: P..M delta evaluator


def test_main_push_delta_exact_paths():
    env = _main_push_env()
    ctx = tool.main_push_context(ROOT, env)
    paths = tool.main_push_delta(ROOT, ctx["target_sha"], ctx["parent_sha"])
    # the frozen Phase-S setup delta (a12694f -> 8b3d789) is exactly the
    # 3-file temporary scope
    assert paths == [
        ".github/workflows/ci.yml",
        "scripts/ci_p29_production_topology_shadow.py",
        "tests/test_ci_p29_production_topology_shadow.py",
    ]


def test_classify_delta_paths_sealed_contract_semantics():
    c314 = tool.compute_selected_input_contract(ROOT, "test-3.14")
    cpa = tool.compute_selected_input_contract(ROOT, "pyarrow24")
    # the future Phase-T target file: selected by test-3.14 (affected),
    # audited known-benign for pyarrow24 (unaffected candidate)
    r314 = tool.classify_delta_paths([tool.TARGET_FILE], "test-3.14", c314)
    assert r314["selected_input_verdict"] == "affected"
    assert r314["affected"] == [tool.TARGET_FILE]
    rpa = tool.classify_delta_paths([tool.TARGET_FILE], "pyarrow24", cpa)
    assert rpa["selected_input_verdict"] == "unaffected"
    assert rpa["benign"] == [tool.TARGET_FILE]
    # invalidators + unknown paths invalidate
    r3 = tool.classify_delta_paths(
        ["ci/components.toml", "src/foo.py", "docs/x.md"], "pyarrow24", cpa
    )
    assert r3["selected_input_verdict"] == "affected"
    assert r3["invalidated"] == ["ci/components.toml", "src/foo.py"]
    assert r3["unknown"] == ["docs/x.md"]
    # selected-input change invalidates
    r4 = tool.classify_delta_paths(["tests/test_v060_portability.py"], "pyarrow24", cpa)
    assert r4["selected_input_verdict"] == "affected"
    assert r4["affected"] == ["tests/test_v060_portability.py"]
    # P2-9 machinery changes invalidate both surfaces (the measurement
    # stack is part of the sealed fail-close contract). git diff emits
    # forward-slash paths; the Windows-local Path form must be normalized.
    script_rel = str(SCRIPT.relative_to(ROOT)).replace("\\", "/")
    r5 = tool.classify_delta_paths([script_rel], "pyarrow24", cpa)
    assert r5["selected_input_verdict"] == "affected"
    assert r5["invalidated"] == [script_rel]
    # empty delta is the only unaffected candidate for pyarrow24
    r6 = tool.classify_delta_paths([], "pyarrow24", cpa)
    assert r6["selected_input_verdict"] == "unaffected"


def test_delta_identity_sha256_deterministic():
    a = tool.delta_identity_sha256(["x/a.py", "b.py"], "test-3.14", "affected")
    b = tool.delta_identity_sha256(["b.py", "x/a.py"], "test-3.14", "affected")
    c = tool.delta_identity_sha256(["x/a.py", "b.py"], "test-3.14", "unaffected")
    assert a == b
    assert a != c


def test_runtime_environment_sha256_head_insensitive(tmp_path):
    """DOC_RUNTIME embeds the run-specific head literal; the environment
    identity used for cross-run comparison must be head-insensitive."""
    env = _pr_env_custom(_git_head_sha(), 42, 1, 42, "a" * 40, tmp_path)
    out = tmp_path / "probe"
    build_probe_out(out, "test-3.14", "a" * 40, env)
    doc = json.loads((out / tool.DOC_RUNTIME).read_text(encoding="utf-8"))
    assert "head" in doc
    other = dict(doc)
    other["head"] = "f" * 40
    assert tool._runtime_environment_sha256(other) == tool._runtime_environment_sha256(doc)


# ---------------------------------------------------------------------------
# Phase-T pre-stage: source evidence locator (mocked read-only GitHub API)


def _locator_canned(tmp_path, monkeypatch, *, pulls, runs, jobs, art_names,
                    att_doc, bundles=None, att_missing=False,
                    bundle_missing=(), bundle_transform=None):
    """Monkeypatch tool._gh_api / tool._gh_run_download with canned
    read-only API responses. bundles maps artifact name -> finalized bundle
    dir for download simulation.

    The simulated download models the REAL single-artifact --dir layout
    (proven by real main-push run 31929326960): the artifact's contents
    are written DIRECTLY into dest — never under dest/<artifact_name>.
    Reverting this fixture to the old synthetic nested layout must fail
    the direct-layout positive regression.

    Failure-mode hooks (fail-closed on the locator side):
      att_missing         — the attestation download yields content that is
                            NOT the expected ci_full_attestation.json;
      bundle_missing      — surfaces whose downloaded bundle is missing
                            source_evidence.json;
      bundle_transform    — callable(surface, dest) applied to a downloaded
                            bundle before the locator consumes it (tamper)."""
    head_sha = "b" * 40

    def fake_api(path, env=None):
        if path.startswith("repos/M0DIAN/market-vault/commits/"):
            return pulls
        if path.startswith("repos/M0DIAN/market-vault/actions/runs?head_sha="):
            return runs
        if "/jobs?" in path:
            return jobs
        if "/artifacts?" in path:
            return {"artifacts": [{"name": n} for n in art_names]}
        raise AssertionError(f"unexpected api path: {path}")

    def fake_download(run_id, name, dest, repo_slug, env=None):
        if name == f"market-vault-full-ci-attestation-{head_sha}-attempt-1":
            if att_missing:
                # downloaded artifact present, expected exact content absent
                (dest / "unexpected.txt").write_text(
                    "not the attestation\n", encoding="utf-8"
                )
            else:
                (dest / "ci_full_attestation.json").write_text(
                    json.dumps(att_doc, sort_keys=True), encoding="utf-8"
                )
        else:
            surface = next(
                s for s in tool.SURFACES
                if name == f"{tool.P2_9_ARTIFACT_PREFIX}-{s}-{head_sha}-attempt-1"
            )
            shutil.copytree(bundles[surface], dest, dirs_exist_ok=True)
            if surface in bundle_missing:
                (dest / tool.SOURCE_EVIDENCE_NAME).unlink()
            if bundle_transform is not None:
                bundle_transform(surface, dest)
        # direct-layout contract: the resolved bundle root is the
        # destination itself (same return contract as _gh_run_download)
        return dest

    monkeypatch.setattr(tool, "_gh_api", fake_api)
    monkeypatch.setattr(tool, "_gh_run_download", fake_download)


def _locator_tamper_evidence_schema(surface, dest):
    p = dest / tool.SOURCE_EVIDENCE_NAME
    d = json.loads(p.read_text(encoding="utf-8"))
    d["unexpected_key"] = "x"
    p.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")


def _locator_tamper_evidence_binding(surface, dest):
    p = dest / tool.SOURCE_EVIDENCE_NAME
    d = json.loads(p.read_text(encoding="utf-8"))
    d["tested_tree_sha"] = "9" * 40
    p.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")


def _locator_tamper_wheel_bytes(surface, dest):
    (dest / "built_wheels" / "1" / WHEEL_NAME).write_bytes(
        make_wheel_bytes(module_content=b"# tampered\n")
    )


class _FakeGhDownload:
    """Simulates the REAL gh run download single-artifact behavior: a
    successful gh process writes the artifact's contents DIRECTLY under
    the --dir destination (the layout proven by real main-push run
    31929326960); the artifact-name subdirectory is never created.
    layout: "direct" | "nested" | "mixed" | "empty"."""

    def __init__(self, layout, rc, real_run):
        self.layout = layout
        self.rc = rc
        self._real_run = real_run

    def __call__(self, cmd, *args, **kwargs):
        if cmd[0] != "gh":
            return self._real_run(cmd, *args, **kwargs)
        assert cmd[1:3] == ["run", "download"], cmd
        dest = Path(cmd[cmd.index("--dir") + 1])
        name = cmd[cmd.index("--name") + 1]
        dest.mkdir(parents=True, exist_ok=True)
        if self.layout == "direct":
            (dest / "ci_full_attestation.json").write_text("{}\n", encoding="utf-8")
            # legitimate top-level subdirectory content survives the direct
            # extraction (the real bundle carries positive_control/ etc.)
            (dest / "positive_control").mkdir(exist_ok=True)
            (dest / "positive_control" / "verify.json").write_text("{}\n", encoding="utf-8")
        elif self.layout == "nested":
            (dest / name).mkdir(parents=True, exist_ok=True)
            (dest / name / "ci_full_attestation.json").write_text("{}\n", encoding="utf-8")
        elif self.layout == "mixed":
            (dest / "ci_full_attestation.json").write_text("{}\n", encoding="utf-8")
            (dest / name).mkdir(parents=True, exist_ok=True)
            (dest / name / "extra.json").write_text("{}\n", encoding="utf-8")
        elif self.layout == "empty":
            pass
        else:
            raise AssertionError(f"unknown layout: {self.layout}")
        return subprocess.CompletedProcess(
            cmd, self.rc, stdout="", stderr="gh: download failed" if self.rc else ""
        )


def _gh_run_download_with(monkeypatch, layout, rc=0):
    monkeypatch.setattr(tool.subprocess, "run", _FakeGhDownload(layout, rc, subprocess.run))


class _FakeGhError:
    """Simulates gh failing with rc=1 whose raw stderr carries the
    sensitive token value — the exact leak vector the rc-only error
    contract must neutralize (token must never reach the exception)."""

    def __init__(self, real_run):
        self._real_run = real_run

    def __call__(self, cmd, *args, **kwargs):
        if cmd[0] != "gh":
            return self._real_run(cmd, *args, **kwargs)
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr=f"fatal: {SENSITIVE_TEST_TOKEN}"
        )


def _locator_ctx() -> dict:
    return tool.main_push_context(ROOT, _main_push_env())


def _locator_ok_bundles(tmp_path, head_sha, parent):
    """Build real finalized source bundles for the one-generation-back
    'source PR' run (merge = parent of the main-push HEAD)."""
    src_env = _pr_env_custom(parent, 777, 1, 84, head_sha, tmp_path)
    bundles = {}
    for surface in tool.SURFACES:
        out = tmp_path / f"src_{surface}"
        build_probe_out(out, surface, head_sha, src_env)
        fin = run_finalize(out, surface, head_sha, src_env)
        assert fin.returncode == 0, fin.stdout + fin.stderr
        bundles[surface] = out
    return bundles


def _locator_att_doc(head_sha, parent, parent_tree, run_id=777):
    return {
        "schema_version": 1,
        "repository": "M0DIAN/market-vault",
        "workflow": "CI",
        "run_id": run_id,
        "run_attempt": 1,
        "pr_number": 84,
        "base_sha": "0" * 40,
        "head_sha": head_sha,
        "tested_merge_sha": parent,
        "tested_tree_sha": parent_tree,
        "tier": "full",
        "full_matrix_required": True,
    }


def test_gh_run_download_direct_layout_positive(monkeypatch, tmp_path):
    """Dedicated layout regression for _gh_run_download itself: a
    SUCCESSFUL gh process that writes files DIRECTLY under the --dir
    destination must resolve the bundle root as the destination itself
    (the layout proven by real main-push run 31929326960). This test
    fails if the fixture is changed back to the old synthetic nested
    layout (dest/<artifact_name>/...)."""
    _gh_run_download_with(monkeypatch, "direct", rc=0)
    dest = tmp_path / "att_dest"
    name = f"market-vault-full-ci-attestation-{'b' * 40}-attempt-1"
    root = tool._gh_run_download(777, name, dest, "M0DIAN/market-vault")
    # returned / resolved bundle root == the direct destination
    assert root == dest
    assert (root / "ci_full_attestation.json").is_file()
    # legitimate top-level subdirectory content survives the direct layout
    assert (root / "positive_control" / "verify.json").is_file()
    # the artifact-name subdirectory never exists under the direct layout
    assert not (root / name).exists()


def test_gh_run_download_fails_closed_empty(monkeypatch, tmp_path):
    # successful gh process but zero downloaded entries => fail closed
    _gh_run_download_with(monkeypatch, "empty", rc=0)
    with pytest.raises(tool.SourceLocatorError, match="gh_run_download_empty"):
        tool._gh_run_download(777, "att-name", tmp_path / "d", "M0DIAN/market-vault")


def test_gh_run_download_fails_closed_nested_only(monkeypatch, tmp_path):
    # old unexpected nested-only layout (dest/<artifact_name>/...) must
    # NOT be silently interpreted as the direct layout => fail closed
    _gh_run_download_with(monkeypatch, "nested", rc=0)
    with pytest.raises(tool.SourceLocatorError, match="gh_run_download_layout_unexpected"):
        tool._gh_run_download(777, "att-name", tmp_path / "d", "M0DIAN/market-vault")


def test_gh_run_download_fails_closed_mixed_direct_nested(monkeypatch, tmp_path):
    # mixed direct + nested layout => fail closed (no first-match
    # ambiguity, never silently preferred over the direct layout)
    _gh_run_download_with(monkeypatch, "mixed", rc=0)
    with pytest.raises(tool.SourceLocatorError, match="gh_run_download_layout_unexpected"):
        tool._gh_run_download(777, "att-name", tmp_path / "d", "M0DIAN/market-vault")


def test_gh_run_download_fails_closed_gh_error(monkeypatch, tmp_path):
    # gh return code != 0 => existing download error
    _gh_run_download_with(monkeypatch, "direct", rc=1)
    with pytest.raises(tool.SourceLocatorError, match="gh_run_download_error"):
        tool._gh_run_download(777, "att-name", tmp_path / "d", "M0DIAN/market-vault")


def test_gh_run_download_fails_closed_dest_not_empty(monkeypatch, tmp_path):
    # destination must be fresh / empty before the download
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "stale.txt").write_text("stale\n", encoding="utf-8")
    _gh_run_download_with(monkeypatch, "direct", rc=0)
    with pytest.raises(tool.SourceLocatorError, match="gh_run_download_dest_not_empty"):
        tool._gh_run_download(777, "att-name", dest, "M0DIAN/market-vault")


def test_gh_run_download_error_omits_stderr_and_token(monkeypatch, tmp_path):
    """Token-safe error path: a FAILING gh run download whose raw stderr
    would echo the token must raise the stable rc-only reason
    gh_run_download_error:<name>:rc=<N> — raw stderr is never
    interpolated, so the token cannot reach the exception (or anything
    the exception is later propagated into: aggregate output/evidence)."""
    monkeypatch.setenv("GH_TOKEN", SENSITIVE_TEST_TOKEN)
    monkeypatch.setattr(tool.subprocess, "run", _FakeGhError(subprocess.run))
    with pytest.raises(tool.SourceLocatorError) as exc:
        tool._gh_run_download(777, "att-name", tmp_path / "d", "M0DIAN/market-vault")
    assert str(exc.value) == "gh_run_download_error:att-name:rc=1"
    assert SENSITIVE_TEST_TOKEN not in str(exc.value)


def test_gh_api_error_omits_stderr_and_token(monkeypatch):
    """Token-safe error path: a FAILING gh api whose raw stderr would
    echo the token must raise the stable rc-only reason
    gh_api_error:<api-path>:rc=<N> — raw stderr is never interpolated,
    so the token cannot reach the exception."""
    monkeypatch.setenv("GH_TOKEN", SENSITIVE_TEST_TOKEN)
    monkeypatch.setattr(tool.subprocess, "run", _FakeGhError(subprocess.run))
    with pytest.raises(tool.SourceLocatorError) as exc:
        tool._gh_api("repos/M0DIAN/market-vault/actions/runs/777")
    assert str(exc.value) == "gh_api_error:repos/M0DIAN/market-vault/actions/runs/777:rc=1"
    assert SENSITIVE_TEST_TOKEN not in str(exc.value)


def test_locate_source_evidence_ok(tmp_path, monkeypatch):
    # Phase-S auth contract: with a mocked gh-CLI auth source the locator
    # passes the auth gate and reaches the existing positive locator path.
    monkeypatch.setenv("GH_TOKEN", SENSITIVE_TEST_TOKEN)
    head_sha = "b" * 40
    parent = MAIN_PUSH_PARENT_SHA
    parent_tree = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", f"{parent}^{{tree}}"], text=True
    ).strip()
    bundles = _locator_ok_bundles(tmp_path, head_sha, parent)
    att_doc = _locator_att_doc(head_sha, parent, parent_tree)
    art_names = (
        [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"]
        + [f"{tool.P2_9_ARTIFACT_PREFIX}-{s}-{head_sha}-attempt-1" for s in tool.SURFACES]
    )
    _locator_canned(
        tmp_path, monkeypatch,
        pulls=[{
            "number": 84, "merged_at": "2026-08-15T00:00:00Z", "state": "closed",
            "merge_commit_sha": parent, "head": {"sha": head_sha},
        }],
        runs={"workflow_runs": [{
            "event": "pull_request", "head_sha": head_sha,
            "path": ".github/workflows/ci.yml", "status": "completed",
            "conclusion": "success", "id": 777, "run_attempt": 1,
        }]},
        jobs={"jobs": [
            {"name": n, "conclusion": "success"}
            for n in ["test (3.11)", "test (3.14)", "portability-pyarrow24", "package"]
        ]},
        art_names=art_names,
        att_doc=att_doc,
        bundles=bundles,
    )
    loc = tool.locate_source_evidence(ROOT, _locator_ctx())
    # Section-5 direct-layout positive: exact bindings for the single prior
    # merged PR — exact PR association, exact successful FULL run/attempt,
    # exact four jobs (fixture), one V1 FULL attestation, both source
    # bundles, tested_tree == parent tree, source_available == true.
    assert loc["source_available"] is True
    assert loc["reason"] == "ok"
    assert loc["pr_number"] == 84
    assert loc["pr_head_sha"] == head_sha
    assert loc["run_id"] == 777
    assert loc["run_attempt"] == 1
    assert loc["attestation"]["valid"] is True
    assert loc["attestation"]["sha256"] == tool.sha256_bytes(
        json.dumps(att_doc, sort_keys=True).encode()
    )
    for surface in tool.SURFACES:
        b = loc["bundles"][surface]
        assert b["evidence"]["tested_tree_sha"] == parent_tree
        assert b["evidence"]["pr_head_sha"] == head_sha
        assert int(b["replay_check_count"]) > 0
        assert b["normalized_fingerprint_sha256"]
        # DIRECT-layout contract: the resolved bundle root IS the download
        # destination — source_evidence.json sits at the root and no
        # artifact-name subdirectory exists. If the fake_download fixture
        # is reverted to the old synthetic nested layout
        # (dest/<artifact_name>/...), the locator's resolution (and these
        # assertions) must fail.
        root = b["bundle_dir"]
        assert root.name.startswith("p29_loc_")
        assert (root / tool.SOURCE_EVIDENCE_NAME).is_file()
        assert not (root / b["artifact_name"]).exists()
    # Phase-S auth contract: the token VALUE never appears in locator
    # output or in the produced source evidence / attestation / replay
    # state — presence is asserted, contents are never persisted.
    assert SENSITIVE_TEST_TOKEN not in json.dumps(loc, sort_keys=True, default=str)
    for surface in tool.SURFACES:
        b = loc["bundles"][surface]
        for p in b["bundle_dir"].rglob("*"):
            if p.is_file():
                assert SENSITIVE_TEST_TOKEN not in p.read_text(
                    encoding="utf-8", errors="replace"
                ), p


def test_locate_source_evidence_fail_closed_cases(tmp_path, monkeypatch):
    # Phase-S auth contract: every retained none/duplicate/ambiguous/
    # tamper negative is still reached behind a mocked gh-CLI auth source.
    monkeypatch.setenv("GH_TOKEN", "test-token")
    head_sha = "b" * 40
    parent = MAIN_PUSH_PARENT_SHA
    parent_tree = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", f"{parent}^{{tree}}"], text=True
    ).strip()
    bundles = _locator_ok_bundles(tmp_path, head_sha, parent)
    att_doc = _locator_att_doc(head_sha, parent, parent_tree)
    art_names = (
        [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"]
        + [f"{tool.P2_9_ARTIFACT_PREFIX}-{s}-{head_sha}-attempt-1" for s in tool.SURFACES]
    )
    pull = {
        "number": 84, "merged_at": "2026-08-15T00:00:00Z", "state": "closed",
        "merge_commit_sha": parent, "head": {"sha": head_sha},
    }
    run = {
        "event": "pull_request", "head_sha": head_sha,
        "path": ".github/workflows/ci.yml", "status": "completed",
        "conclusion": "success", "id": 777, "run_attempt": 1,
    }
    jobs_ok = {"jobs": [
        {"name": n, "conclusion": "success"}
        for n in ["test (3.11)", "test (3.14)", "portability-pyarrow24", "package"]
    ]}

    cases = [
        ("source_pr_none", [], {"workflow_runs": [run]}, jobs_ok, art_names, att_doc),
        ("source_pr_ambiguous",
         [pull, dict(pull, number=85)], {"workflow_runs": [run]}, jobs_ok, art_names, att_doc),
        ("source_run_not_found", [pull], {"workflow_runs": []}, jobs_ok, art_names, att_doc),
        ("source_run_ambiguous", [pull],
         {"workflow_runs": [run, dict(run, id=778)]}, jobs_ok, art_names, att_doc),
        ("source_jobs_not_exact_four", [pull], {"workflow_runs": [run]},
         {"jobs": [{"name": "test (3.11)", "conclusion": "success"}]}, art_names, att_doc),
        ("source_jobs_not_all_success", [pull], {"workflow_runs": [run]},
         {"jobs": [{"name": n, "conclusion": "failure"}
                   for n in ["test (3.11)", "test (3.14)", "portability-pyarrow24", "package"]]},
         art_names, att_doc),
        ("v1_attestation_not_found", [pull], {"workflow_runs": [run]}, jobs_ok,
         [f"{tool.P2_9_ARTIFACT_PREFIX}-{s}-{head_sha}-attempt-1" for s in tool.SURFACES],
         att_doc),
        ("v1_attestation_invalid", [pull], {"workflow_runs": [run]}, jobs_ok, art_names,
         dict(att_doc, tested_tree_sha="9" * 40)),
        ("v1_attestation_invalid", [pull], {"workflow_runs": [run]}, jobs_ok, art_names,
         dict(att_doc, tier="control_plane")),
        ("source_bundle_test-3.14_not_found", [pull], {"workflow_runs": [run]}, jobs_ok,
         [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"]
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-pyarrow24-{head_sha}-attempt-1"],
         att_doc),
        ("source_bundle_pyarrow24_not_found", [pull], {"workflow_runs": [run]}, jobs_ok,
         [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"]
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{head_sha}-attempt-1"],
         att_doc),
        # duplicate/ambiguous artifact => fail closed
        ("v1_attestation_ambiguous", [pull], {"workflow_runs": [run]}, jobs_ok,
         [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"] * 2
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-{s}-{head_sha}-attempt-1" for s in tool.SURFACES],
         att_doc),
        ("source_bundle_test-3.14_ambiguous", [pull], {"workflow_runs": [run]}, jobs_ok,
         [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"]
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{head_sha}-attempt-1"] * 2
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-pyarrow24-{head_sha}-attempt-1"],
         att_doc),
        ("source_bundle_pyarrow24_ambiguous", [pull], {"workflow_runs": [run]}, jobs_ok,
         [f"market-vault-full-ci-attestation-{head_sha}-attempt-1"]
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{head_sha}-attempt-1"]
         + [f"{tool.P2_9_ARTIFACT_PREFIX}-pyarrow24-{head_sha}-attempt-1"] * 2,
         att_doc),
        # V1 attestation downloaded but the expected exact content is
        # absent => fail closed (no recursive first-match search)
        ("v1_attestation_content_missing", [pull], {"workflow_runs": [run]}, jobs_ok,
         art_names, att_doc, {"att_missing": True}),
        # source bundle downloaded but missing source_evidence.json =>
        # fail closed
        ("source_bundle_test-3.14_evidence_missing", [pull], {"workflow_runs": [run]},
         jobs_ok, art_names, att_doc, {"bundle_missing": ("test-3.14",)}),
        ("source_bundle_pyarrow24_evidence_missing", [pull], {"workflow_runs": [run]},
         jobs_ok, art_names, att_doc, {"bundle_missing": ("pyarrow24",)}),
        # downloaded bundle tampered => schema / binding / replay fail
        # closed (evidence validation is never weakened)
        ("source_bundle_test-3.14_schema_invalid", [pull], {"workflow_runs": [run]},
         jobs_ok, art_names, att_doc,
         {"bundle_transform": _locator_tamper_evidence_schema}),
        ("source_bundle_test-3.14_binding_mismatch", [pull], {"workflow_runs": [run]},
         jobs_ok, art_names, att_doc,
         {"bundle_transform": _locator_tamper_evidence_binding}),
        ("source_bundle_test-3.14_replay_failed", [pull], {"workflow_runs": [run]},
         jobs_ok, art_names, att_doc,
         {"bundle_transform": _locator_tamper_wheel_bytes}),
    ]
    for case in cases:
        expect, pulls, runs, jobs, names, att = case[:6]
        kwargs = case[6] if len(case) > 6 else {}
        _locator_canned(
            tmp_path, monkeypatch, pulls=pulls, runs=runs, jobs=jobs,
            art_names=names, att_doc=att, bundles=bundles, **kwargs,
        )
        with pytest.raises(tool.SourceLocatorError, match=expect):
            tool.locate_source_evidence(ROOT, _locator_ctx())


def test_locate_source_evidence_fails_closed_without_auth(monkeypatch):
    """Phase-S auth contract: without an explicit gh-CLI auth source
    (GH_TOKEN or its gh-CLI-documented GITHUB_TOKEN alias) the locator
    fail-closes with the stable source_auth_missing reason BEFORE any
    positive locator work — it must never silently assume
    unauthenticated public-repository gh access, and the failure is a
    bare stable reason (no token, no environment dump)."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    env = {k: v for k, v in _main_push_env().items()
           if k not in ("GH_TOKEN", "GITHUB_TOKEN")}

    def unexpected_gh_call(*args, **kwargs):
        raise AssertionError("locator must fail closed before any gh call")

    monkeypatch.setattr(tool, "_gh_api", unexpected_gh_call)
    with pytest.raises(tool.SourceLocatorError) as exc:
        tool.locate_source_evidence(ROOT, _locator_ctx(), env=env)
    assert str(exc.value) == "source_auth_missing"


def test_locate_source_evidence_accepts_gh_cli_token_alias(monkeypatch):
    """Phase-S auth contract: the gh-CLI-documented GITHUB_TOKEN alias is
    an explicitly supported equivalent auth source — with it set the
    locator passes the auth gate into positive locator work instead of
    failing source_auth_missing."""
    env = {k: v for k, v in _main_push_env().items()
           if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    env["GITHUB_TOKEN"] = "test-token-alias"

    def first_gh_call_is_auth_past(*args, **kwargs):
        raise tool.SourceLocatorError("source_pr_none")

    monkeypatch.setattr(tool, "_gh_api", first_gh_call_is_auth_past)
    with pytest.raises(tool.SourceLocatorError, match="source_pr_none"):
        tool.locate_source_evidence(ROOT, _locator_ctx(), env=env)


# ---------------------------------------------------------------------------
# Phase-T pre-stage: aggregate (main-push target shadow, fail-close to RUN)


def _build_target_payload(pdir: Path, surface: str, main_env: dict) -> dict:
    """Build a synthetic target probe payload dir mirroring cmd_target_probe
    exactly (payload doc + DOC_RUNTIME + DOC_NORMALIZED), from the synthetic
    probe tree. No network, no heavy measurement."""
    work = pdir.parent / f"probe_{surface}"
    ctx = tool.main_push_context(ROOT, main_env)
    pdir.parent.mkdir(parents=True, exist_ok=True)
    probe_env = _pr_env_custom(
        ctx["target_sha"], ctx["run_id"], ctx["run_attempt"], 84, "a" * 40,
        pdir.parent,
    )
    build_probe_out(work, surface, "a" * 40, probe_env)
    runtime_doc = json.loads((work / tool.DOC_RUNTIME).read_text(encoding="utf-8"))
    norm_doc = json.loads((work / tool.DOC_NORMALIZED).read_text(encoding="utf-8"))
    contract = tool.compute_selected_input_contract(ROOT, surface)
    payload = {
        "schema_version": 1,
        "artifact_class": tool.TARGET_PROBE_ARTIFACT_CLASS,
        "repository": "M0DIAN/market-vault",
        "workflow": "CI",
        "run_id": ctx["run_id"],
        "run_attempt": ctx["run_attempt"],
        "surface": surface,
        "target_sha": ctx["target_sha"],
        "parent_sha": ctx["parent_sha"],
        "target_tree_sha": ctx["target_tree_sha"],
        "parent_tree_sha": ctx["parent_tree_sha"],
        "runtime_identity_sha256": tool.sha256_file(work / tool.DOC_RUNTIME),
        "runtime_environment_sha256": tool._runtime_environment_sha256(runtime_doc),
        "normalized_identity_sha256": norm_doc["fingerprint_sha256"],
        "selected_input_contract_sha256": tool.sha256_bytes(
            tool.canonical_serialize(contract).encode()
        ),
        "probe_source_sha256": tool.sha256_file(SCRIPT),
    }
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / tool.TARGET_PROBE_PAYLOAD_NAME).write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )
    shutil.copyfile(work / tool.DOC_RUNTIME, pdir / tool.DOC_RUNTIME)
    shutil.copyfile(work / tool.DOC_NORMALIZED, pdir / tool.DOC_NORMALIZED)
    return payload


def _run_aggregate(tmp_path, monkeypatch, capsys, token="test-token"):
    main_env = _main_push_env()
    probe_dir = tmp_path / "probe"
    for surface in tool.SURFACES:
        _build_target_payload(probe_dir / surface, surface, main_env)
    for k, v in main_env.items():
        if k.startswith("GITHUB_"):
            monkeypatch.setenv(k, v)
    # Phase-S auth contract: a mocked gh-CLI auth source is required to
    # reach the locator path (token=None exercises the no-auth fail-close).
    if token is not None:
        monkeypatch.setenv("GH_TOKEN", token)

    def source_unavailable(*args, **kwargs):
        raise tool.SourceLocatorError("source_pr_none")

    monkeypatch.setattr(tool, "_gh_api", source_unavailable)
    out = tmp_path / "out"
    ns = argparse.Namespace(out_dir=str(out), probe_dir=str(probe_dir), repo=str(ROOT))
    rc = tool.cmd_aggregate(ns)
    out_lines = capsys.readouterr().out
    return rc, out_lines, out, main_env


def test_aggregate_fail_closes_to_all_run_on_source_unavailable(tmp_path, monkeypatch, capsys):
    """On the Phase-S merge push itself the evaluator legitimately
    fail-closes: source unavailable => every surface RUN, never REUSE, and
    the target evidence is produced with the P2-7 closure."""
    rc, out_lines, out, main_env = _run_aggregate(tmp_path, monkeypatch, capsys)
    assert rc == 0
    assert "TARGET_EVIDENCE_OK=true" in out_lines
    assert "SOURCE_LOCATOR_AVAILABLE=false" in out_lines
    assert "SOURCE_LOCATOR_REASON=source_pr_none" in out_lines
    assert "DELTA_CHANGED_PATH_COUNT=3" in out_lines
    for surface in tool.SURFACES:
        assert f"TARGET_VERDICT_{surface}=run" in out_lines
        assert f"TARGET_REASON_{surface}=run:source_unavailable:source_pr_none" in out_lines
        assert f"SELECTED_INPUT_VERDICT_{surface}=affected" in out_lines
        assert f"GLOBAL_RUNTIME_MATCH_{surface}=false" in out_lines
        assert f"TARGET_EVIDENCE_BUNDLE_REPLAY_OK_{surface}=true" in out_lines
        assert f"CHECK_COUNT_{surface}" in out_lines
        # the bundle must replay offline with its OWN verifier copy
        bundle = out / surface
        summary_out = tmp_path / f"replay_{surface}.txt"
        proc = run_verify_bundle(bundle, summary_out)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        # evidence doc: exact 25 fields, zeroed source identity, run verdict
        ev = json.loads((bundle / tool.TARGET_EVIDENCE_NAME).read_text(encoding="utf-8"))
        assert tool.validate_target_shadow_evidence(ev) == []
        assert ev["source_pr_number"] == 0
        assert ev["source_artifact_name"] == ""
        assert ev["verdict"] == tool.VERDICT_RUN
        assert ev["retained_replay_state"] == tool.TARGET_RETAINED_REPLAY_STATE
        # mutual seal
        manifest = json.loads((bundle / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
        entries = [
            [e["path"], e["sha256"], e["size"]]
            for e in manifest["entries"]
            if e["path"] != tool.TARGET_EVIDENCE_NAME
        ]
        assert tool.manifest_content_digest(entries) == ev["evidence_manifest_sha256"]


def _run_aggregate_gh_token_failure(tmp_path, monkeypatch, capsys, fail_gh):
    """Run cmd_aggregate with GH_TOKEN=SENSITIVE_TEST_TOKEN where gh
    invocations selected by fail_gh(cmd) return rc=1 with raw stderr
    carrying the token value. Returns (rc, out_lines, out_dir)."""
    main_env = _main_push_env()
    probe_dir = tmp_path / "probe"
    for surface in tool.SURFACES:
        _build_target_payload(probe_dir / surface, surface, main_env)
    for k, v in main_env.items():
        if k.startswith("GITHUB_"):
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("GH_TOKEN", SENSITIVE_TEST_TOKEN)
    real_run = subprocess.run  # capture BEFORE the monkeypatch below

    def gh_or_real(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            if fail_gh(cmd):
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr=f"fatal: {SENSITIVE_TEST_TOKEN}"
                )
            raise AssertionError(f"unexpected gh invocation: {cmd}")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(tool.subprocess, "run", gh_or_real)
    out = tmp_path / "out"
    ns = argparse.Namespace(out_dir=str(out), probe_dir=str(probe_dir), repo=str(ROOT))
    rc = tool.cmd_aggregate(ns)
    out_lines = capsys.readouterr().out
    return rc, out_lines, out


def _assert_aggregate_token_fail_closed(rc, out_lines, out, tmp_path, reason):
    """Shared assertions: the failing locator must leave the aggregate
    RUN-never-REUSED on every surface, with the STABLE rc-only reason in
    the aggregate output and the token absent from every stdout line and
    every on-disk evidence byte."""
    assert rc == 0
    assert "SOURCE_LOCATOR_AVAILABLE=false" in out_lines
    assert f"SOURCE_LOCATOR_REASON={reason}" in out_lines
    assert SENSITIVE_TEST_TOKEN not in out_lines
    for surface in tool.SURFACES:
        assert f"TARGET_VERDICT_{surface}=run" in out_lines
        assert f"TARGET_REASON_{surface}=run:source_unavailable:{reason}" in out_lines
        # per-surface retained bundle still replays offline with its own
        # verifier copy (the closure must not be poisoned by the failure)
        summary_out = tmp_path / f"replay_{surface}.txt"
        proc = run_verify_bundle(out / surface, summary_out)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    # the token is absent from EVERY captured output line and EVERY file
    # the aggregate wrote (target evidence, source reference, receipts)
    for p in sorted(out.rglob("*")):
        if p.is_file():
            assert SENSITIVE_TEST_TOKEN.encode() not in p.read_bytes(), p


def test_aggregate_gh_run_download_error_token_not_leaked(tmp_path, monkeypatch, capsys):
    """End-to-end token safety for the gh run download failure path: the
    locator reaches the download stage, gh fails with rc=1 and token-
    carrying stderr, the locator fail-closes with the stable rc-only
    reason gh_run_download_error:<name>:rc=1, the aggregate stays RUN on
    every surface (never REUSE), and the token is absent from the
    aggregate stdout AND from every on-disk evidence file."""
    head_sha = "b" * 40
    parent = MAIN_PUSH_PARENT_SHA
    att_name = f"market-vault-full-ci-attestation-{head_sha}-attempt-1"

    def canned_api(path, env=None):
        if path.startswith(f"repos/M0DIAN/market-vault/commits/"):
            return [{
                "number": 84, "merged_at": "2026-08-15T00:00:00Z",
                "state": "closed", "merge_commit_sha": parent,
                "head": {"sha": head_sha},
            }]
        if "actions/runs?head_sha=" in path:
            return {"workflow_runs": [{
                "event": "pull_request", "head_sha": head_sha,
                "path": ".github/workflows/ci.yml", "status": "completed",
                "conclusion": "success", "id": 777, "run_attempt": 1,
            }]}
        if "/jobs?" in path:
            return {"jobs": [
                {"name": n, "conclusion": "success"}
                for n in ["test (3.11)", "test (3.14)", "portability-pyarrow24", "package"]
            ]}
        if "/artifacts?" in path:
            return {"artifacts": [{"name": att_name}]}
        raise AssertionError(f"unexpected api path: {path}")

    monkeypatch.setattr(tool, "_gh_api", canned_api)
    rc, out_lines, out = _run_aggregate_gh_token_failure(
        tmp_path, monkeypatch, capsys,
        fail_gh=lambda cmd: cmd[1:3] == ["run", "download"],
    )
    _assert_aggregate_token_fail_closed(
        rc, out_lines, out, tmp_path,
        f"gh_run_download_error:{att_name}:rc=1",
    )


def test_aggregate_gh_api_error_token_not_leaked(tmp_path, monkeypatch, capsys):
    """End-to-end token safety for the gh api failure path: the FIRST gh
    api call fails with rc=1 and token-carrying stderr, the locator
    fail-closes with the stable rc-only reason gh_api_error:<api-path>:rc=1
    before any download, the aggregate stays RUN on every surface (never
    REUSE), and the token is absent from the aggregate stdout AND from
    every on-disk evidence file."""
    main_env = _main_push_env()
    ctx = tool.main_push_context(ROOT, main_env)
    api_path = f"repos/M0DIAN/market-vault/commits/{ctx['parent_sha']}/pulls"
    rc, out_lines, out = _run_aggregate_gh_token_failure(
        tmp_path, monkeypatch, capsys,
        fail_gh=lambda cmd: cmd[1:3] == ["api", api_path],
    )
    _assert_aggregate_token_fail_closed(
        rc, out_lines, out, tmp_path, f"gh_api_error:{api_path}:rc=1",
    )


def test_aggregate_fails_closed_on_missing_auth(tmp_path, monkeypatch, capsys):
    """Phase-S auth contract end-to-end: with no gh-CLI auth source the
    aggregator fail-closes to source unavailable (SOURCE_LOCATOR_REASON=
    source_auth_missing) and every surface RUNs — never REUSE, and the
    target evidence closure still completes."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    rc, out_lines, out, _ = _run_aggregate(tmp_path, monkeypatch, capsys, token=None)
    assert rc == 0
    assert "SOURCE_LOCATOR_AVAILABLE=false" in out_lines
    assert "SOURCE_LOCATOR_REASON=source_auth_missing" in out_lines
    assert "TARGET_EVIDENCE_OK=true" in out_lines
    for surface in tool.SURFACES:
        assert f"TARGET_VERDICT_{surface}=run" in out_lines
        assert f"TARGET_REASON_{surface}=run:source_unavailable:source_auth_missing" in out_lines
        assert f"TARGET_EVIDENCE_BUNDLE_REPLAY_OK_{surface}=true" in out_lines


def test_aggregate_never_leaks_token_value(tmp_path, monkeypatch, capsys):
    """Phase-S auth contract: the step-scoped token VALUE never appears in
    the aggregate log, the target evidence / source reference / manifest
    docs, or the post-upload replay receipt — presence is asserted,
    contents are never printed or persisted."""
    monkeypatch.setenv("GH_TOKEN", SENSITIVE_TEST_TOKEN)
    rc, out_lines, out, _ = _run_aggregate(
        tmp_path, monkeypatch, capsys, token=SENSITIVE_TEST_TOKEN
    )
    assert rc == 0
    assert "SOURCE_LOCATOR_REASON=source_pr_none" in out_lines
    assert SENSITIVE_TEST_TOKEN not in out_lines
    for p in out.rglob("*"):
        if p.is_file():
            assert SENSITIVE_TEST_TOKEN not in p.read_text(
                encoding="utf-8", errors="replace"
            ), p
    for surface in tool.SURFACES:
        summary = tmp_path / f"leak_replay_{surface}.txt"
        proc = run_verify_bundle(out / surface, summary)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert SENSITIVE_TEST_TOKEN not in summary.read_text(encoding="utf-8")


def test_aggregate_target_evidence_cross_doc_consistency(tmp_path, monkeypatch, capsys):
    """delta_evaluator + source_reference + evidence are cross-doc
    consistent and the delta identity is re-derived."""
    rc, out_lines, out, main_env = _run_aggregate(tmp_path, monkeypatch, capsys)
    assert rc == 0
    for surface in tool.SURFACES:
        bundle = out / surface
        ev = json.loads((bundle / tool.TARGET_EVIDENCE_NAME).read_text(encoding="utf-8"))
        dd = json.loads((bundle / tool.DELTA_EVALUATOR_NAME).read_text(encoding="utf-8"))
        ref = json.loads((bundle / tool.SOURCE_REFERENCE_NAME).read_text(encoding="utf-8"))
        assert dd["changed_paths"] == [
            ".github/workflows/ci.yml",
            "scripts/ci_p29_production_topology_shadow.py",
            "tests/test_ci_p29_production_topology_shadow.py",
        ]
        assert dd["invalidated"] == dd["changed_paths"]
        assert dd["selected_input_verdict"] == ev["selected_input_verdict"]
        assert dd["delta_identity_sha256"] == tool.delta_identity_sha256(
            dd["changed_paths"], surface, ev["selected_input_verdict"]
        )
        assert dd["delta_identity_sha256"] == ev["delta_identity_sha256"]
        assert dd["surface"] == ev["surface"]
        assert dd["target_sha"] == ev["target_sha"]
        assert dd["parent_sha"] == ev["parent_sha"]
        assert ref["source_available"] is False
        assert ref["reason"] == "source_pr_none"
        assert ref["source_pr_number"] == ev["source_pr_number"] == 0
        assert ref["runtime_match"] is False
        # payload identity docs are bound
        payload = json.loads(
            (bundle / tool.TARGET_PROBE_PAYLOAD_NAME).read_text(encoding="utf-8")
        )
        assert payload["runtime_identity_sha256"] == ev["target_runtime_identity_sha256"]
        assert tool.sha256_file(bundle / tool.DOC_RUNTIME) == payload["runtime_identity_sha256"]


def test_verify_retained_target_bundle_ok(tmp_path, monkeypatch, capsys):
    """A retained TARGET bundle verified under its exact target name passes
    the post-upload roundtrip (main-push context binding)."""
    rc, out_lines, out, main_env = _run_aggregate(tmp_path, monkeypatch, capsys)
    assert rc == 0
    bundle = out / "test-3.14"
    name = f"{tool.P2_9_TARGET_ARTIFACT_PREFIX}-test-3.14-{MAIN_PUSH_TARGET_SHA}-attempt-1"
    summary_out = tmp_path / "rt_target.txt"
    proc = subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-retained",
         "--bundle-dir", str(bundle), "--name", name,
         "--surface", "test-3.14", "--repo", str(ROOT),
         "--summary-out", str(summary_out)],
        capture_output=True, text=True, env=main_env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = summary_out.read_text(encoding="utf-8")
    assert "ROUNDTRIP_RECEIPT=OK" in lines
    assert "ROUNDTRIP_RULE=READ_ONLY_REPLAY_NO_MUTATION_NO_REUPLOAD" in lines


def test_verify_retained_rejects_v1_lookalike_name(finalized_bundle, pr_env, tmp_path):
    """Independent-review correction: a valid P2-9 retained source bundle
    passed with a V1-style attestation name must be REJECTED by the exact
    name binding (distinct from wrong-head/attempt P2-9-name cases)."""
    bundle, _ = finalized_bundle
    v1_name = f"market-vault-full-ci-attestation-{pr_env['head']}-attempt-1"
    summary_out = tmp_path / "rt_v1.txt"
    proc = subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-retained",
         "--bundle-dir", str(bundle), "--name", v1_name,
         "--surface", "test-3.14", "--repo", str(ROOT),
         "--summary-out", str(summary_out)],
        capture_output=True, text=True, env=pr_env["env"],
    )
    assert proc.returncode == 2
    lines = summary_out.read_text(encoding="utf-8")
    assert "ROUNDTRIP_RECEIPT=INVALID" in lines
    assert "FAILED_CHECK=artifact_name_binding:" in lines


def test_verify_retained_rejects_wrong_attempt_p2_9_name(finalized_bundle, pr_env, tmp_path):
    """A P2-9-style name with the wrong run attempt is rejected by the
    exact name binding."""
    bundle, _ = finalized_bundle
    wrong = f"{tool.P2_9_ARTIFACT_PREFIX}-test-3.14-{pr_env['head']}-attempt-99"
    summary_out = tmp_path / "rt_att.txt"
    proc = subprocess.run(
        [sys.executable, str(bundle / tool.VERIFIER_NAME), "verify-retained",
         "--bundle-dir", str(bundle), "--name", wrong,
         "--surface", "test-3.14", "--repo", str(ROOT),
         "--summary-out", str(summary_out)],
        capture_output=True, text=True, env=pr_env["env"],
    )
    assert proc.returncode == 2
    lines = summary_out.read_text(encoding="utf-8")
    assert "ROUNDTRIP_RECEIPT=INVALID" in lines
    assert "FAILED_CHECK=artifact_name_binding:" in lines


def test_target_bundle_tamper_rejected(tmp_path, monkeypatch, capsys):
    """Target evidence tampering fails closed: a verdict/reason inconsistency
    and an invalid verdict literal both fail the replay."""
    rc, out_lines, out, main_env = _run_aggregate(tmp_path, monkeypatch, capsys)
    assert rc == 0
    bundle = out / "test-3.14"
    ev_p = bundle / tool.TARGET_EVIDENCE_NAME
    # tamper 1: verdict run but reason claims reused => verdict consistency
    d = json.loads(ev_p.read_text(encoding="utf-8"))
    d["reason"] = "reused:all_predicates_valid"
    ev_p.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=target_verdict_consistency:") for ln in lines)
    # tamper 2: invalid verdict literal => schema failure
    d = json.loads(ev_p.read_text(encoding="utf-8"))
    d["verdict"] = "reuse"
    ev_p.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=target_evidence_schema:") for ln in lines)
    # tamper 3: unknown field => schema failure
    d = json.loads(ev_p.read_text(encoding="utf-8"))
    d["bogus_field"] = 1
    ev_p.write_text(json.dumps(d, sort_keys=True), encoding="utf-8")
    lines = _tamper_and_verify(bundle, tmp_path)
    assert any(ln.startswith("FAILED_CHECK=target_evidence_schema:") for ln in lines)


# ---------------------------------------------------------------------------
# Phase-T pre-stage: main-push shadow steps pre-staged in ci.yml


def test_main_push_shadow_steps_prestaged_in_ci_yml():
    """The main-push shadow steps are pre-staged NOW: target probes in the
    test-3.14 and pyarrow24 jobs, aggregator + target bundle upload/replay
    in the package job. The steps MUST run on main pushes even when
    POST_MERGE_REUSE=true (no reuse guard), must not add any skip
    conditions, must not add any job, and the artifact names use the exact
    main-push templates."""
    ci = CI_YML.read_text(encoding="utf-8")
    guard = (
        "github.event_name == 'push' && github.ref == 'refs/heads/main' "
        "&& env.CI_TIER != 'docs_fast' && env.CI_TIER != 'package_docs' "
        "&& env.CI_TIER != 'control_plane'"
    )
    assert guard in ci
    # the main-push P2-9 guards must NOT carry POST_MERGE_REUSE
    idx = ci.index("Run P2-9 main-push target probe (test-3.14)")
    chunk = ci[idx:idx + 600]
    assert "POST_MERGE_REUSE" not in chunk
    assert "target-probe" in chunk
    assert "matrix.python-version == '3.14'" in chunk
    # no new job: the P2-9 main-push steps live inside existing jobs
    assert ci.count("Run P2-9 main-push target probe (") == 2
    for surface in tool.SURFACES:
        assert f"{tool.P2_9_TARGET_PROBE_ARTIFACT_PREFIX}-{surface}-" in ci
        assert f"{tool.P2_9_TARGET_ARTIFACT_PREFIX}-{surface}-${{{{ github.sha }}}}-attempt-${{{{ github.run_attempt }}}}" in ci
    assert "Run P2-9 main-push target shadow aggregation" in ci
    # the aggregate output feeds exact target bundle uploads + retained replays
    for action in ("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
                   "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"):
        assert action in ci
    # Phase-S auth contract: the aggregation step is the ONLY step
    # carrying the step-scoped GH_TOKEN binding (official GitHub Actions
    # guidance requires GH_TOKEN for each workflow step using the GitHub
    # CLI), and the sealed v061 contract stays byte-semantically intact —
    # exactly three GITHUB_TOKEN bindings, each inside a "Post-merge FULL
    # reuse proof" step only. The P2-9 step must not add a fourth
    # GITHUB_TOKEN.
    gh_binding = "GH_TOKEN: ${{ github.token }}"
    v1_binding = "GITHUB_TOKEN: ${{ github.token }}"
    steps = _ci_step_regions(ci)
    gh_steps = [name for name, region in steps if gh_binding in region]
    assert gh_steps == ["Run P2-9 main-push target shadow aggregation"]
    agg_region = next(
        region for name, region in steps
        if name == "Run P2-9 main-push target shadow aggregation"
    )
    assert gh_binding in agg_region
    assert v1_binding not in agg_region
    assert ci.count(v1_binding) == 3
    for name, region in steps:
        if v1_binding in region:
            assert name == "Post-merge FULL reuse proof", name


def test_main_push_aggregation_step_mkdir_before_tee():
    """Phase-S plumbing repair (P0 main-push run 31923040590 failed here):
    the aggregation step tees its log into p2_9_target_out/aggregate.log,
    but on main pushes nothing created p2_9_target_out before tee opened
    the file, so the step died with 'tee: p2_9_target_out/aggregate.log:
    No such file or directory' (pipefail => package job failure). The step
    must mkdir the output directory BEFORE the pipeline; tee must keep the
    same path; pipefail must stay; no '|| true', no output moves, no new
    POST_MERGE_REUSE guard; the GH_TOKEN binding stays step-scoped; the
    push-only guard stays unchanged; downstream upload / retained replay
    steps stay unchanged."""
    ci = CI_YML.read_text(encoding="utf-8")
    guard = (
        "github.event_name == 'push' && github.ref == 'refs/heads/main' "
        "&& env.CI_TIER != 'docs_fast' && env.CI_TIER != 'package_docs' "
        "&& env.CI_TIER != 'control_plane'"
    )
    steps = _ci_step_regions(ci)
    agg = next(region for name, region in steps
               if name == "Run P2-9 main-push target shadow aggregation")

    # guard + auth contract unchanged
    assert f"if: {guard}" in agg
    assert "POST_MERGE_REUSE" not in agg
    assert "GH_TOKEN: ${{ github.token }}" in agg
    assert "GITHUB_TOKEN: ${{ github.token }}" not in agg

    # exact ordering contract: pipefail -> mkdir -> pipeline that tees the
    # same path. mkdir MUST precede the pipeline so the directory exists
    # before tee opens aggregate.log.
    assert "set -o pipefail" in agg
    assert "mkdir -p p2_9_target_out" in agg
    assert agg.index("set -o pipefail") < agg.index("mkdir -p p2_9_target_out")
    assert agg.index("mkdir -p p2_9_target_out") < agg.index(
        "| tee p2_9_target_out/aggregate.log"
    )
    assert "--out-dir p2_9_target_out" in agg
    # no failure hiding, no output relocation
    assert "|| true" not in agg

    # the mkdir exists in exactly one place: the aggregation step (a second
    # site would decouple the ordering contract this test pins)
    assert ci.count("mkdir -p p2_9_target_out") == 1

    # downstream upload + retained replay steps unchanged: same guard, same
    # artifact templates, same upload globs, same retained replay
    # invocation, same receipt grep
    for surface in tool.SURFACES:
        up = next(region for name, region in steps
                  if name == f"Upload P2-9 main-push target shadow evidence ({surface})")
        assert f"if: {guard}" in up
        assert f"path: p2_9_target_out/{surface}/**" in up
        assert (
            f"name: {tool.P2_9_TARGET_ARTIFACT_PREFIX}-{surface}-"
            f"${{{{ github.sha }}}}-attempt-${{{{ github.run_attempt }}}}"
        ) in up
        dl = next(region for name, region in steps
                  if name == f"Download retained P2-9 main-push target bundle ({surface})")
        assert f"path: p2_9_target_retained/{surface}" in dl
        rp = next(region for name, region in steps
                  if name == f"Replay retained P2-9 main-push target bundle ({surface})")
        assert f"if: {guard}" in rp
        assert "verify-retained" in rp
        assert "ROUNDTRIP_RECEIPT=OK" in rp
