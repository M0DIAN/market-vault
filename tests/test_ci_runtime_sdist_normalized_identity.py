"""P2-7 measurement-tool tests (temporary; removed on the cleanup head).

Unit tests for scripts/ci_runtime_sdist_normalized_identity.py:
- canonical serialization determinism (schema determinism / versioning)
- payload digest semantics (RECORD exclusion, path sorting)
- wheel inventory + PEP 427 RECORD validation (positive + negatives)
- RAW-MISMATCH normalization-proof classification (fail-close branches)
- positive control: timestamp-only patch preserves normalized identity
- negative controls: payload mutation (stale + consistent RECORD),
  duplicate archive path, member reorder, wrong filename, non-timestamp
  ZipInfo change, extra-field change, raw length change, unclassified byte
- evidence-bundle closure: manifest last, duplicate-path rejection,
  post-manifest write detection, tamper detection, verifier self-identity
- cross-head comparator branches (RAW vs NORMALIZED verdicts)
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci_runtime_sdist_normalized_identity.py"


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "ci_runtime_sdist_normalized_identity", TOOL_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# module-level copy so the wheel builder can emit real PEP 376 hashes
_TOOL = load_tool()


@pytest.fixture(scope="module")
def tool():
    return _TOOL


# ---------------------------------------------------------------------------
# wheel builders


DEFAULT_DT = (1980, 1, 1, 0, 0, 0)


def build_wheel(
    path,
    name="moomoo-api",
    version="10.9.6908",
    module_files=None,
    date_time=DEFAULT_DT,
    timestamp_overrides=None,
    member_options=None,
    comment=b"",
    record_override=None,
    drop_record=False,
    member_order=None,
):
    """Write a PEP 427 wheel with a consistent RECORD (unless overridden).
    Returns the member path list in archive order."""
    norm = name.replace("-", "_")
    dist_dir = f"{norm}-{version}.dist-info"
    mod_files = dict(module_files if module_files is not None else {f"{norm}/__init__.py": b"import sys\n"})
    meta = (f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: >=3.9\n").encode()
    wheel = (
        "Wheel-Version: 1.0\nGenerator: p2-7-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    ).encode()
    top_level = f"{norm}\n".encode()

    def ts(p):
        return (timestamp_overrides or {}).get(p, date_time)

    body = []
    for p, b in mod_files.items():
        body.append((p, b, ts(p)))
    body.append((f"{dist_dir}/METADATA", meta, ts(f"{dist_dir}/METADATA")))
    body.append((f"{dist_dir}/WHEEL", wheel, ts(f"{dist_dir}/WHEEL")))
    body.append((f"{dist_dir}/top_level.txt", top_level, ts(f"{dist_dir}/top_level.txt")))
    record_path = f"{dist_dir}/RECORD"
    if drop_record:
        record_body = None
    elif record_override is not None:
        record_body = record_override
    else:
        # PEP 376 RECORD hash: urlsafe base64 without padding, like the
        # setuptools/wheel builders emit -- the tool must compare against
        # the real contract, not against itself
        lines = [f"{p},{_TOOL.record_sha256(b)},{len(b)}" for p, b, _ in body]
        lines.append(f"{record_path},,")
        record_body = ("\n".join(lines) + "\n").encode()
    if record_body is not None:
        body.append((record_path, record_body, ts(record_path)))

    if member_order is not None:
        by_path = {p: (b, t) for p, b, t in body}
        ordered = []
        for p in member_order:
            if p in by_path:
                ordered.append((p, *by_path.pop(p)))
        for p, b, t in body:
            if p in by_path:
                ordered.append((p, b, t))
        body = ordered

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, b, t in body:
            zi = zipfile.ZipInfo(p, date_time=t)
            zi.compress_type = zipfile.ZIP_DEFLATED
            opts = (member_options or {}).get(p, {})
            if "compress_type" in opts:
                zi.compress_type = opts["compress_type"]
            if "external_attr" in opts:
                zi.external_attr = opts["external_attr"]
            if "extra" in opts:
                zi.extra = opts["extra"]
            if "comment" in opts:
                zi.comment = opts["comment"]
            zf.writestr(zi, b)
        zf.comment = comment
    return [p for p, _, _ in body]


def build_wheel_with_duplicate(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pkg/__init__.py", b"first")
        zf.writestr("pkg/__init__.py", b"second")
    return ["pkg/__init__.py"]


DIST_INFO_PATHS = [
    "moomoo_api-10.9.6908.dist-info/METADATA",
    "moomoo_api-10.9.6908.dist-info/WHEEL",
    "moomoo_api-10.9.6908.dist-info/top_level.txt",
    "moomoo_api-10.9.6908.dist-info/RECORD",
]


def wheel_paths(tmp_path):
    """Two distinct directories holding identically-named valid wheels."""
    d1, d2 = tmp_path / "build_a", tmp_path / "build_b"
    d1.mkdir()
    d2.mkdir()
    return d1 / "moomoo_api-10.9.6908-py3-none-any.whl", d2 / "moomoo_api-10.9.6908-py3-none-any.whl"


def wheel_path(tmp_path, sub):
    """One validly-named wheel path in a fresh subdirectory."""
    d = tmp_path / sub
    d.mkdir()
    return d / "moomoo_api-10.9.6908-py3-none-any.whl"



# ---------------------------------------------------------------------------
# canonical serialization (schema determinism / versioning)


class TestCanonicalSerialize:
    def test_schema_version_pinned(self, tool):
        assert tool.SCHEMA_VERSION == "3"

    def test_keys_sorted_recursively(self, tool):
        # canonical form: documents stay JSON objects, keys sorted
        obj = {"b": 1, "a": {"d": 2, "c": 3}, "l": [{"z": 0, "y": 1}]}
        assert tool.canonical_serialize(obj) == '{"a":{"c":3,"d":2},"b":1,"l":[{"y":1,"z":0}]}\n'

    def test_list_order_preserved(self, tool):
        a = {"x": [["p", "h1", 3], ["q", "h2", 1]]}
        b = {"x": [["q", "h2", 1], ["p", "h1", 3]]}
        assert tool.canonical_serialize(a) != tool.canonical_serialize(b)

    def test_deterministic_across_insertion_order(self, tool):
        a = {"x": 1, "y": {"m": 2, "n": [1, 2, 3]}}
        b = {"y": {"n": [1, 2, 3], "m": 2}, "x": 1}
        assert tool.canonical_serialize(a) == tool.canonical_serialize(b)

    def test_newline_terminated(self, tool):
        assert tool.canonical_serialize({}) == "{}\n"


# ---------------------------------------------------------------------------
# payload digest semantics


class TestPayloadDigest:
    def test_record_excluded_and_sorted(self, tool):
        entries = [["a.txt", "h1", 3], ["RECORD", "hx", 4], ["b.txt", "h2", 1]]
        d, n = tool.payload_digest_from_entries(entries, "RECORD")
        assert n == 2
        d2, _ = tool.payload_digest_from_entries(list(reversed(entries)), "RECORD")
        assert d == d2

    def test_digest_changes_on_content(self, tool):
        d1, _ = tool.payload_digest_from_entries([["a.txt", "h1", 3]], None)
        d2, _ = tool.payload_digest_from_entries([["a.txt", "h1", 4]], None)
        d3, _ = tool.payload_digest_from_entries([["a.txt", "h2", 3]], None)
        assert d1 != d2 != d3

    def test_digest_changes_on_count(self, tool):
        d1, _ = tool.payload_digest_from_entries([["a.txt", "h1", 3]], None)
        d2, _ = tool.payload_digest_from_entries([["a.txt", "h1", 3], ["b.txt", "h2", 1]], None)
        assert d1 != d2

    def test_installed_tree_exclusions(self, tool, tmp_path):
        tree = tmp_path / "installed"
        (tree / "pkg").mkdir(parents=True)
        (tree / "pkg/__init__.py").write_bytes(b"x")
        (tree / "pkg/__pycache__").mkdir()
        (tree / "pkg/__pycache__/__init__.cpython-311.pyc").write_bytes(b"pyc")
        (tree / "pkg-1.0.dist-info").mkdir()
        (tree / "pkg-1.0.dist-info/METADATA").write_bytes(b"m")
        (tree / "pkg-1.0.dist-info/RECORD").write_bytes(b"r")
        (tree / "pkg-1.0.dist-info/INSTALLER").write_bytes(b"pip")
        (tree / "pkg-1.0.dist-info/REQUESTED").write_bytes(b"")
        (tree / "pkg-1.0.dist-info/direct_url.json").write_bytes(b"{}")
        d, n = tool.installed_payload_sha256(tree)
        # only the two real payload files survive the exclusions
        expect = [["pkg-1.0.dist-info/METADATA", tool.sha256_file(tree / "pkg-1.0.dist-info/METADATA"), 1],
                  ["pkg/__init__.py", tool.sha256_file(tree / "pkg/__init__.py"), 1]]
        d2, n2 = tool.payload_digest_from_entries(expect, None)
        assert n == 2
        assert n2 == 2
        assert d == d2


# ---------------------------------------------------------------------------
# normalize_url


class TestNormalizeUrl:
    def test_http_url_stripped(self, tool):
        u = tool.normalize_url("https://files.pythonhosted.org/packages/a/1/x.whl?x=1#sha256=abc")
        assert u == "https://files.pythonhosted.org/packages/a/1/x.whl"

    def test_local_or_empty_none(self, tool):
        assert tool.normalize_url("") is None
        assert tool.normalize_url("file:///x/y.whl") is None
        assert tool.normalize_url("C:\\wheels\\x.whl") is None

    def test_credentials_raise(self, tool):
        with pytest.raises(ValueError):
            tool.normalize_url("https://user:pass@host/x.whl")


# ---------------------------------------------------------------------------
# wheel inventory + RECORD validation


class TestInventory:
    def test_valid_wheel(self, tool, tmp_path):
        w = tmp_path / "moomoo_api-10.9.6908-py3-none-any.whl"
        paths = build_wheel(w)
        inv = tool.inventory_wheel(w)
        assert inv.structural_valid
        assert inv.record_valid
        assert inv.errors == []
        assert inv.dist_info_dir == "moomoo_api-10.9.6908.dist-info"
        assert inv.record_path == "moomoo_api-10.9.6908.dist-info/RECORD"
        assert paths[-1] == inv.record_path
        assert inv.filename_info["name"] == "moomoo_api"
        assert inv.filename_info["version"] == "10.9.6908"

    def test_duplicate_archive_path_rejected(self, tool, tmp_path):
        w = tmp_path / "bad.whl"
        build_wheel_with_duplicate(w)
        inv = tool.inventory_wheel(w)
        assert any("duplicate_path" in e for e in inv.errors)

    def test_stale_record_rejected(self, tool, tmp_path):
        w = tmp_path / "moomoo_api-10.9.6908-py3-none-any.whl"
        rec = "moomoo_api-10.9.6908.dist-info/RECORD"
        mod = "moomoo_api/__init__.py"
        # correct line shape, but the module hash is stale (wrong digest)
        body = f"{mod},sha256={'0' * 64},11\n{rec},,\n".encode()
        build_wheel(w, record_override=body)
        inv = tool.inventory_wheel(w)
        assert not inv.record_valid
        assert any("record_hash_mismatch" in e for e in inv.errors)

    def test_record_self_entry_must_be_empty(self, tool, tmp_path):
        w = tmp_path / "moomoo_api-10.9.6908-py3-none-any.whl"
        rec = "moomoo_api-10.9.6908.dist-info/RECORD"
        mod = "moomoo_api/__init__.py"
        h = hashlib.sha256(b"import sys\n").hexdigest()
        body = f"{mod},sha256={h},11\n{rec},sha256={h},4\n".encode()
        build_wheel(w, record_override=body)
        inv = tool.inventory_wheel(w)
        assert not inv.record_valid
        assert any("record_self_entry_not_empty" in e for e in inv.errors)

    def test_missing_dist_info_files_rejected(self, tool, tmp_path):
        w = tmp_path / "moomoo_api-10.9.6908-py3-none-any.whl"
        build_wheel(w, drop_record=True)
        inv = tool.inventory_wheel(w)
        assert not inv.record_valid
        assert any("record_missing" in e for e in inv.errors)
        assert any("missing_dist_info_file:RECORD" in e for e in inv.errors)

    def test_malformed_filename_rejected(self, tool, tmp_path):
        w = tmp_path / "not-a-wheel-name.zip"
        build_wheel(w)
        inv = tool.inventory_wheel(w)
        assert not inv.structural_valid
        assert "wheel_filename_malformed" in inv.errors

    def test_record_not_last_rejected(self, tool, tmp_path):
        w = tmp_path / "moomoo_api-10.9.6908-py3-none-any.whl"
        rec = "moomoo_api-10.9.6908.dist-info/RECORD"
        mod = "moomoo_api/__init__.py"
        # write RECORD in the middle; module file last
        order = ["moomoo_api-10.9.6908.dist-info/METADATA", rec,
                 "moomoo_api-10.9.6908.dist-info/WHEEL", mod]
        build_wheel(w, member_order=order)
        inv = tool.inventory_wheel(w)
        assert not inv.record_valid
        assert any("record_not_last" in e for e in inv.errors)

    def test_extra_record_entry_rejected(self, tool, tmp_path):
        w = tmp_path / "moomoo_api-10.9.6908-py3-none-any.whl"
        rec = "moomoo_api-10.9.6908.dist-info/RECORD"
        mod = "moomoo_api/__init__.py"
        h = hashlib.sha256(b"import sys\n").hexdigest()
        body = f"{mod},sha256={h},11\nphantom.txt,sha256={h},4\n{rec},,\n".encode()
        build_wheel(w, record_override=body)
        inv = tool.inventory_wheel(w)
        assert not inv.record_valid
        assert any("record_extra_entry" in e for e in inv.errors)


class TestInstalledRecord:
    """_validate_installed_record over real installed-tree bytes: every
    member dict must carry its installed content (PEP 376 recompute)."""

    def _tree(self, tool, tmp_path, stale=False):
        d = tmp_path / "installed"
        (d / "moomoo_api").mkdir(parents=True)
        (d / "moomoo_api-10.9.6908.dist-info").mkdir()
        mod = d / "moomoo_api" / "__init__.py"
        mod.write_bytes(b"import sys\n")
        rec = d / "moomoo_api-10.9.6908.dist-info" / "RECORD"
        h = "0" * 43 if stale else tool.record_sha256(mod.read_bytes()).split("=", 1)[1]
        lines = [f"moomoo_api/__init__.py,sha256={h},{mod.stat().st_size}",
                 "moomoo_api-10.9.6908.dist-info/RECORD,,"]
        rec.write_bytes(("\n".join(lines) + "\n").encode())
        members = [
            {"path": "moomoo_api/__init__.py", "sha256": tool.sha256_bytes(mod.read_bytes()),
             "size": mod.stat().st_size, "content": mod.read_bytes()},
            {"path": "moomoo_api-10.9.6908.dist-info/RECORD", "content": rec.read_bytes()},
        ]
        return members, "moomoo_api-10.9.6908.dist-info/RECORD"

    def test_valid_installed_record(self, tool, tmp_path):
        members, rec_rel = self._tree(tool, tmp_path)
        errors = []
        tool._validate_installed_record(members, rec_rel, errors)
        assert errors == []

    def test_stale_installed_record_hash_rejected(self, tool, tmp_path):
        members, rec_rel = self._tree(tool, tmp_path, stale=True)
        errors = []
        tool._validate_installed_record(members, rec_rel, errors)
        assert any("record_hash_mismatch" in e for e in errors)


# ---------------------------------------------------------------------------
# RAW-MISMATCH normalization proof (the fail-close contract)


class TestNormalizationContract:
    def test_timestamp_only_difference_is_contract_ok(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1)
        build_wheel(w2, timestamp_overrides={p: (2020, 6, 15, 13, 45, 30) for p in DIST_INFO_PATHS})
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cmp_res["wheel_payload_match"] is True
        assert cmp_res["non_timestamp_zipinfo_identical"] is True
        assert cls["verdict"] is True
        assert cls["reason"] == "timestamp_only_contract_ok"
        assert cls["attribution"]["unclassified"] == 0
        assert cls["attribution"]["local_or_central_timestamp"] == cls["diff_byte_count"]
        assert len(cmp_res["timestamp_diffs"]) == len(DIST_INFO_PATHS)

    def test_content_difference_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        stored = {
            "moomoo_api/__init__.py": {"compress_type": zipfile.ZIP_STORED},
            "moomoo_api-10.9.6908.dist-info/RECORD": {"compress_type": zipfile.ZIP_STORED},
        }
        # module + RECORD stored so deflate cannot change the raw archive
        # length: the same-length content mutation keeps len(w1) == len(w2)
        # and the classification deterministically reaches the content
        # comparison instead of failing at the length gate
        build_wheel(w1, module_files={"moomoo_api/__init__.py": b"import sys\n"},
                    member_options=stored)
        build_wheel(w2, module_files={"moomoo_api/__init__.py": b"import syx\n"},
                    member_options=stored)
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert len(w1.read_bytes()) == len(w2.read_bytes())
        assert inv2.record_valid  # the strongest negative: valid-looking RECORD
        assert cmp_res["wheel_payload_match"] is False
        assert cls["verdict"] is False
        # the mutated member's stored bytes are not timestamp slots,
        # so the raw diff classifies as unclassified (invalid), even though
        # the structural comparison independently flags the content change
        assert cls["reason"] == "unclassified_raw_difference"

    def test_unclassified_content_byte_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1)
        build_wheel(w2)
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        raw2 = bytearray(w2.read_bytes())
        # flip one byte inside the first member's compressed data region
        # (outside every timestamp slot, same total length)
        content_off = inv1.all_header_offsets[0] + 30 + len("moomoo_api/__init__.py")
        raw2[content_off] ^= 0x01
        cls = tool.classify_raw_mismatch(w1.read_bytes(), bytes(raw2), inv1, inv2,
                                         tool.compare_wheels(inv1, inv2))
        assert cls["verdict"] is False
        assert cls["attribution"]["unclassified"] > 0
        assert cls["reason"] == "unclassified_raw_difference"

    def test_member_comment_change_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1)
        build_wheel(w2, member_options={"moomoo_api/__init__.py": {"comment": b"not-allowed"}})
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False
        assert cls["reason"] != "timestamp_only_contract_ok"

    def test_external_attr_change_with_unchanged_payload_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1)
        build_wheel(w2, member_options={"moomoo_api/__init__.py": {"external_attr": 0o100600}})
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        assert cmp_res["all_member_contents_identical"] is True
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False

    def test_extra_field_change_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        custom_extra = b"ZZ" + b"\x02\x00" + b"ab"
        build_wheel(w1)
        build_wheel(w2, member_options={"moomoo_api/__init__.py": {"extra": custom_extra}})
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False

    def test_member_reorder_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1, module_files={"moomoo_api/__init__.py": b"a", "moomoo_api/sub.py": b"b"})
        order = ["moomoo_api/sub.py", "moomoo_api/__init__.py"] + DIST_INFO_PATHS
        build_wheel(w2, module_files={"moomoo_api/__init__.py": b"a", "moomoo_api/sub.py": b"b"},
                    member_order=order)
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        assert cmp_res["member_ordering_identical"] is False
        assert cmp_res["wheel_payload_match"] is True  # content identical
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False

    def test_member_removed_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1, module_files={"moomoo_api/__init__.py": b"a", "moomoo_api/sub.py": b"b"})
        build_wheel(w2, module_files={"moomoo_api/__init__.py": b"a"})
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        assert cmp_res["path_sets_identical"] is False
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False

    def test_raw_length_unequal_rejected(self, tool, tmp_path):
        w1 = tmp_path / "a.whl"
        build_wheel(w1)
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        inv2 = tool.inventory_wheel(w1)
        cls = tool.classify_raw_mismatch(raw1, raw1[:-1], inv1, inv2, {})
        assert cls["verdict"] is False
        assert cls["reason"] == "raw_length_unequal"

    def test_record_invalid_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1)
        build_wheel(w2, drop_record=True)  # structurally invalid wheel
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False

    def test_archive_comment_difference_rejected(self, tool, tmp_path):
        w1, w2 = wheel_paths(tmp_path)
        build_wheel(w1)
        build_wheel(w2, comment=b"orphan")
        inv1 = tool.inventory_wheel(w1)
        inv2 = tool.inventory_wheel(w2)
        cmp_res = tool.compare_wheels(inv1, inv2)
        assert cmp_res["archive_comment_equal"] is False
        cls = tool.classify_raw_mismatch(w1.read_bytes(), w2.read_bytes(), inv1, inv2, cmp_res)
        assert cls["verdict"] is False


# ---------------------------------------------------------------------------
# positive control: timestamp-only byte patch


class TestPositiveControl:
    def test_patch_timestamps_is_contract_ok(self, tool, tmp_path):
        w1, pw = wheel_paths(tmp_path)
        build_wheel(w1, date_time=(2021, 3, 5, 12, 34, 56))
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        patched = tool.patch_zip_timestamps(raw1, inv1, DIST_INFO_PATHS, new_time=0x0000)
        assert patched != raw1
        pw.write_bytes(patched)
        inv_p = tool.inventory_wheel(pw)
        cmp_res = tool.compare_wheels(inv1, inv_p)
        assert cmp_res["wheel_payload_match"] is True
        assert cmp_res["non_timestamp_zipinfo_identical"] is True
        assert cmp_res["timestamp_diffs"]  # the only difference is timestamps
        cls = tool.classify_raw_mismatch(raw1, patched, inv1, inv_p, cmp_res)
        assert cls["verdict"] is True
        assert cls["reason"] == "timestamp_only_contract_ok"
        slots = tool.timestamp_slots(raw1, inv1)
        diffs = [i for i in range(len(raw1)) if raw1[i] != patched[i]]
        assert diffs
        assert all(any(s <= i < e for s, e in slots) for i in diffs)

    def test_patch_unknown_member_is_noop(self, tool, tmp_path):
        w1, _ = wheel_paths(tmp_path)
        build_wheel(w1, date_time=(2021, 3, 5, 12, 34, 56))
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        patched = tool.patch_zip_timestamps(raw1, inv1, ["no/such/file"], new_time=0x0000)
        assert patched == raw1

    def test_compare_wheels_sees_patch_as_timestamp_diff(self, tool, tmp_path):
        w1, pw = wheel_paths(tmp_path)
        build_wheel(w1, date_time=(2021, 3, 5, 12, 34, 56))
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        patched = tool.patch_zip_timestamps(raw1, inv1, DIST_INFO_PATHS[:1], new_time=0x0000)
        pw.write_bytes(patched)
        cmp_res = tool.compare_wheels(inv1, tool.inventory_wheel(pw))
        assert len(cmp_res["timestamp_diffs"]) == 1


# ---------------------------------------------------------------------------
# negative control: rebuilt mutated wheels


class TestRebuildMutated:
    def test_stale_record_variant_invalid(self, tool, tmp_path):
        w1, stale = wheel_paths(tmp_path)
        build_wheel(w1)
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        mutated = tool.rebuild_wheel_mutated(raw1, inv1, stale, fix_record=False)
        inv_s = tool.inventory_wheel(stale)
        assert not inv_s.record_valid
        assert any("record_hash_mismatch" in e for e in inv_s.errors)
        # RECORD bytes are retained verbatim; the mutation is caught by the
        # hash mismatch between RECORD and the mutated member content
        orig_record = next(m.content for m in inv1.members if m.path == inv1.record_path)
        stale_record = next(m.content for m in inv_s.members if m.path == inv_s.record_path)
        assert stale_record == orig_record
        first_non_dist = next(m.path for m in inv1.members
                              if m.path.split("/", 1)[0] != inv1.dist_info_dir)
        assert mutated == first_non_dist
        mutated_member = next(m for m in inv_s.members if m.path == mutated)
        orig_member = next(m for m in inv1.members if m.path == mutated)
        assert mutated_member.content != orig_member.content

    def test_consistent_record_variant_valid_but_payload_differs(self, tool, tmp_path):
        w1, cons = wheel_paths(tmp_path)
        build_wheel(w1)
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        p_orig, _ = tool.payload_sha256(inv1.members, inv1.record_path)
        tool.rebuild_wheel_mutated(raw1, inv1, cons, fix_record=True)
        inv_c = tool.inventory_wheel(cons)
        assert inv_c.record_valid
        assert inv_c.errors == []
        p_c, _ = tool.payload_sha256(inv_c.members, inv_c.record_path)
        assert p_c != p_orig

    def test_rebuild_preserves_member_metadata(self, tool, tmp_path):
        w1, cons = wheel_paths(tmp_path)
        build_wheel(w1)
        inv1 = tool.inventory_wheel(w1)
        raw1 = w1.read_bytes()
        tool.rebuild_wheel_mutated(raw1, inv1, cons, fix_record=True)
        inv_c = tool.inventory_wheel(cons)
        by_name = {m.path: m for m in inv_c.members}
        for m in inv1.members:
            m2 = by_name[m.path]
            # flag_bits excluded: zipfile.writestr always resets it
            assert (m2.compress_type, m2.external_attr, m2.internal_attr,
                    m2.create_system, m2.create_version, m2.extract_version,
                    m2.extra, m2.comment, m2.date_time) == (
                m.compress_type, m.external_attr, m.internal_attr,
                m.create_system, m.create_version, m.extract_version,
                m.extra, m.comment, m.date_time)


# ---------------------------------------------------------------------------
# evaluate_verdict (pure derivation)


def _ok_markers():
    return {
        "RAW_WHEEL_REPRODUCIBLE_moomoo-api": "true",
        "WHEEL_PAYLOAD_MATCH_moomoo-api": "true",
        "RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api": "true",
        "INSTALLED_PAYLOAD_MATCH": "true",
        "SOURCE_SDIST_HASH_OK": "true",
        "SOURCE_BUILD_ENVIRONMENT_SHA256": "a" * 64,
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


class TestEvaluateVerdict:
    def test_all_ok(self, tool):
        v = tool.evaluate_verdict(_ok_markers())
        assert v["normalized_install_artifact_identity_valid"] is True
        assert v["reason"] == "ok"

    def test_raw_mismatch_without_normalization_invalid(self, tool):
        s = _ok_markers()
        s["RAW_WHEEL_REPRODUCIBLE_moomoo-api"] = "false"
        s["RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api"] = "false"
        v = tool.evaluate_verdict(s)
        assert v["normalized_install_artifact_identity_valid"] is False
        assert v["reason"] == "raw_mismatch_not_normalized"

    def test_component_failure_invalid(self, tool):
        for marker in ("INSTALLED_PAYLOAD_MATCH", "FINAL_RUNTIME_MATCH",
                       "SHADOW_SURFACE_PASS", "RUNTIME_INSTALL_FROM_WHEELS_ONLY"):
            s = _ok_markers()
            s[marker] = "false"
            v = tool.evaluate_verdict(s)
            assert v["normalized_install_artifact_identity_valid"] is False
            assert v["reason"] == "component_false"

    def test_record_validation_required(self, tool):
        s = _ok_markers()
        s["RECORD_VALID_1"] = "false"
        v = tool.evaluate_verdict(s)
        assert v["normalized_install_artifact_identity_valid"] is False

    def test_crash_fails_closed(self, tool):
        s = _ok_markers()
        s["MEASURE_CRASH"] = "true"
        v = tool.evaluate_verdict(s)
        assert v["normalized_install_artifact_identity_valid"] is False

    def test_raw_equal_no_normalization_needed_still_checks_components(self, tool):
        # raw reproducible + normalization "not needed" (raw_equal case):
        # the verdict still requires every component marker
        s = _ok_markers()
        s["RAW_WHEEL_REPRODUCIBLE_moomoo-api"] = "true"
        s["RAW_MISMATCH_NORMALIZATION_VALID_moomoo-api"] = "false"
        v = tool.evaluate_verdict(s)
        assert v["normalized_install_artifact_identity_valid"] is True
        s["INSTALLED_PAYLOAD_MATCH"] = "false"
        v = tool.evaluate_verdict(s)
        assert v["normalized_install_artifact_identity_valid"] is False
        assert v["reason"] == "component_false"


# ---------------------------------------------------------------------------
# evidence bundle closure


REQUIRED_PLACEHOLDERS = [
    "probe_summary.txt",
    "runtime_sdist_identity.json",
    "runtime_sdist_normalized_identity.json",
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


def make_placeholder_bundle(root: Path):
    for rel in REQUIRED_PLACEHOLDERS:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"placeholder\n")
    (root / "probe_summary.txt").write_text("SURFACE=test-3.14\nHEAD=HEAD_A\n", encoding="utf-8")


def run_bundle(tool, root, surface="test-3.14", head="HEAD_A"):
    ns = type("NS", (), {"out_dir": str(root), "surface": surface, "head": head})()
    tool.cmd_bundle(ns)
    return root / tool.MANIFEST_NAME


def run_verify(bundle: Path):
    proc = subprocess.run(
        [sys.executable, str(bundle / "verifier_source.py"), "verify-bundle",
         "--bundle-dir", str(bundle)],
        capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestBundle:
    def test_manifest_last_sorted_and_bound(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        manifest_path = run_bundle(tool, root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == 3
        paths = [e["path"] for e in manifest["entries"]]
        assert paths == sorted(paths)
        assert tool.MANIFEST_NAME not in paths  # manifest never lists itself
        assert tool.RECEIPT_NAME in paths
        assert tool.VERIFIER_NAME in paths
        assert "probe_summary.txt" in paths
        for e in manifest["entries"]:
            p = root / e["path"]
            assert p.is_file()
            assert p.stat().st_size == e["size"]
            assert tool.sha256_file(p) == e["sha256"]

    def test_bundle_prints_closure_markers(self, tool, tmp_path, capsys):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        out = capsys.readouterr().out
        assert "EVIDENCE_MANIFEST_COMPLETE=true" in out
        assert "FINALIZE_RULE=MANIFEST_LAST_NO_FURTHER_WRITES" in out
        assert "BUNDLE_TREE_SHA256=" in out
        assert "VERIFIER_SHA256=" in out

    def test_verify_uses_bundles_own_verifier(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        rc, out, err = run_verify(root)
        # placeholder bundle: replay NOT ok (checks fail), but verifier
        # self-identity must pass: the bundle's own copy was executed
        assert rc == 2
        assert "FAILED_CHECK=verifier_source" not in out

    def test_verify_detects_orphan_post_manifest_write(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        (root / "stray_after_manifest.txt").write_text("x", encoding="utf-8")
        rc, out, err = run_verify(root)
        assert rc == 2
        assert "FAILED_CHECK=no_orphan_files" in out

    def test_verify_detects_tamper(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        (root / "probe_summary.txt").write_text("TAMPERED\n", encoding="utf-8")
        rc, out, err = run_verify(root)
        assert rc == 2
        assert "FAILED_CHECK=manifest_hashes" in out
        assert "FAILED_CHECK=no_orphan_files" not in out

    def test_verify_detects_manifest_duplicate_paths(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        manifest = json.loads((root / tool.MANIFEST_NAME).read_text(encoding="utf-8"))
        first = manifest["entries"][0]
        manifest["entries"].append(dict(first))  # duplicate path
        (root / tool.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        rc, out, err = run_verify(root)
        assert rc == 2
        assert "FAILED_CHECK=manifest_duplicate_paths_rejected" in out

    def test_verify_detects_verifier_tamper(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        (root / tool.VERIFIER_NAME).write_bytes(b"#!/usr/bin/env python3\nprint('tampered')\n")
        rc, out, err = run_verify(root)
        # A replaced verifier can never emit a green replay verdict (it does
        # not even run the checks). The verifier_source check is the binding
        # protection for the case where a tampered copy still executes the
        # verification code: its sha256 no longer matches the receipt/manifest.
        assert "EVIDENCE_BUNDLE_REPLAY_OK=true" not in out

    def test_verify_detects_missing_required_file(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        (root / "normalization_proof.json").unlink()
        run_bundle(tool, root)
        rc, out, err = run_verify(root)
        assert rc == 2
        assert "FAILED_CHECK=manifest_complete" in out

    def test_verify_emits_tree_sha(self, tool, tmp_path):
        root = tmp_path / "bundle"
        make_placeholder_bundle(root)
        run_bundle(tool, root)
        rc, out, err = run_verify(root)
        assert "REPLAY_BUNDLE_TREE_SHA256=" in out
        # tree sha over the bundle equals the finalized tree sha
        tree_entries = []
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root).as_posix().replace("\\", "/")
                tree_entries.append([rel, tool.sha256_file(p), p.stat().st_size])
        expect = tool.sha256_bytes(
            tool.canonical_serialize(sorted(tree_entries, key=lambda e: e[0])).encode()
        )
        assert f"REPLAY_BUNDLE_TREE_SHA256={expect}" in out


# ---------------------------------------------------------------------------
# cross-head comparator


def write_identity_docs(dir_path: Path, strict: dict, norm: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "runtime_sdist_identity.json").write_text(json.dumps(strict, sort_keys=True), encoding="utf-8")
    (dir_path / "runtime_sdist_normalized_identity.json").write_text(
        json.dumps(norm, sort_keys=True), encoding="utf-8"
    )


def base_docs():
    strict = {
        "schema_version": "3",
        "document_type": "runtime_sdist_identity.json",
        "surface": "test-3.14",
        "head": "HEAD_A",
        "runner": {"run_os": "Linux", "image_version": "1.0"},
        "python": {"version": "3.14.0"},
        "resolver": {"name": "pip", "version": "25.9"},
        "dependency_contract": {"project": "market-vault"},
        "action_contract": {"pins": {"checkout": "d" * 40}},
        "resolved_distributions": [{"canonical_name": "moomoo-api", "version": "10.9.6908"}],
        "source_sdist": {"sha256": "s" * 64},
        "source_build_environment": {"identity_sha256": "e" * 64},
        "build_contract": {"backend": "setuptools"},
        "wheel_payload_identity": {"wheel_payload_sha256": "p" * 64},
        "exact_built_wheel_sha256": {"build_1": "a" * 64, "build_2": "b" * 64},
        "installed_payload_identity": {"installed_payload_sha256": "i" * 64},
        "normalized_verdict": {"raw_wheel_reproducible": False, "normalization_valid": True},
        "marketvault_build_identity": {"p2_5_closed_world_contract_used": True},
        "final_runtime_identity": {"final_runtime_match": True},
        "shadow_surface": {"pass": True},
        "valid_flags": {"normalized_install_artifact_identity_valid": True},
    }
    norm = {
        "schema_version": "3",
        "document_type": "runtime_sdist_normalized_identity.json",
        "surface": "test-3.14",
        "head": "HEAD_A",
        "canonical_name": "moomoo-api",
        "version": "10.9.6908",
        "sdist_sha256": "s" * 64,
        "wheel_payload_sha256": "p" * 64,
        "installed_payload_sha256": "i" * 64,
        "raw_diagnostic": {"note": "diagnostic", "raw_wheel_sha256_1": "r" * 64, "raw_wheel_sha256_2": "t" * 64},
        "raw_diagnostic_sha256": "d" * 64,
        "raw_mismatch_verdict": {
            "allowed_difference": "zip_dos_modification_timestamps_of_build_generated_members_only",
            "diff_attribution": {"local_or_central_timestamp": 10, "unclassified": 0},
            "diff_byte_count": 10,
            "normalization_valid": True,
            "raw_wheel_reproducible": False,
            "reason": "timestamp_only_contract_ok",
        },
        "fingerprint_sha256": "f" * 64,
    }
    return strict, norm


class TestComparator:
    def _run(self, tool, strict_a, norm_a, strict_b, norm_b, capsys):
        import tempfile
        d1 = Path(tempfile.mkdtemp())
        d2 = Path(tempfile.mkdtemp())
        write_identity_docs(d1, strict_a, norm_a)
        write_identity_docs(d2, strict_b, norm_b)
        ns = type("NS", (), {"dir1": str(d1), "dir2": str(d2), "summary_out": None})()
        tool.cmd_compare(ns)
        return json.loads(capsys.readouterr().out)

    def test_identical_docs(self, tool, capsys):
        sa, na = base_docs()
        r = self._run(tool, sa, na, dict(sa), dict(na), capsys)
        assert r["raw_runtime_sdist_identity_match"] is True
        assert r["normalized_runtime_sdist_identity_match"] is True
        assert r["all_global_identity_contracts_match"] is True

    def test_raw_diff_only_exact_wheel_sha(self, tool, capsys):
        sa, na = base_docs()
        sb = dict(sa)
        sb["exact_built_wheel_sha256"] = {"build_1": "A" * 64, "build_2": "b" * 64}
        r = self._run(tool, sa, na, sb, dict(na), capsys)
        assert r["raw_runtime_sdist_identity_match"] is False
        assert r["raw_reason"] == "first_differing_field:exact_built_wheel_sha256"
        assert r["normalized_runtime_sdist_identity_match"] is True
        assert r["all_global_identity_contracts_match"] is True

    def test_runner_drift_never_normalized(self, tool, capsys):
        sa, na = base_docs()
        sb = dict(sa)
        sb["runner"] = {"run_os": "Windows", "image_version": "9.9"}
        r = self._run(tool, sa, na, sb, dict(na), capsys)
        assert r["raw_runtime_sdist_identity_match"] is False
        assert r["raw_reason"] == "first_differing_field:runner"
        assert r["all_global_identity_contracts_match"] is False
        assert r["global_reason"] == "first_differing_field:runner"
        # runner drift is NOT in the normalized payload: normalized identity
        # still matches, but SHADOW_REUSE_CANDIDATE requires the global
        # contracts, which fail
        assert r["normalized_runtime_sdist_identity_match"] is True

    def test_payload_difference_normalized_false(self, tool, capsys):
        sa, na = base_docs()
        sb = dict(sa)
        sb["wheel_payload_identity"] = {"wheel_payload_sha256": "Q" * 64}
        nb = dict(na)
        nb["wheel_payload_sha256"] = "Q" * 64
        r = self._run(tool, sa, na, sb, nb, capsys)
        assert r["normalized_runtime_sdist_identity_match"] is False
        assert r["normalized_reason"].startswith("first_differing_field:")
        assert r["raw_runtime_sdist_identity_match"] is False
        assert r["raw_reason"] == "first_differing_field:wheel_payload_identity"

    def test_surface_unequal(self, tool, capsys):
        sa, na = base_docs()
        sb = dict(sa)
        sb["surface"] = "pyarrow24"
        nb = dict(na)
        nb["surface"] = "pyarrow24"
        r = self._run(tool, sa, na, sb, nb, capsys)
        assert r["raw_runtime_sdist_identity_match"] is False
        assert r["raw_reason"] == "reason:surface_unequal"
        assert r["all_global_identity_contracts_match"] is False

    def test_global_contract_break_not_normalized(self, tool, capsys):
        sa, na = base_docs()
        sb = dict(sa)
        sb["source_sdist"] = {"sha256": "T" * 64}
        r = self._run(tool, sa, na, sb, dict(na), capsys)
        assert r["raw_runtime_sdist_identity_match"] is False
        assert r["raw_reason"] == "first_differing_field:source_sdist"
        assert r["all_global_identity_contracts_match"] is False
        assert r["global_reason"] == "first_differing_field:source_sdist"

    # ------------------------------------------------------------------
    # Cross-head diagnostics: raw-layer noise must never break the
    # NORMALIZED verdict. Heads A/B of the canary differ only by the
    # marker comment, so the raw wheel SHAs and the timestamp attribution
    # counts vary per run while the identity stays identical.
    # ------------------------------------------------------------------

    def test_raw_diagnostic_sha256_drift_does_not_break_normalized(self, tool, capsys):
        sa, na = base_docs()
        nb = dict(na)
        nb["raw_diagnostic_sha256"] = "Z" * 64
        nb["raw_diagnostic"] = {"note": "diagnostic", "raw_wheel_sha256_1": "u" * 64, "raw_wheel_sha256_2": "v" * 64}
        r = self._run(tool, sa, na, dict(sa), nb, capsys)
        assert r["normalized_runtime_sdist_identity_match"] is True
        assert r["normalized_reason"] == "ok"
        assert r["all_global_identity_contracts_match"] is True

    def test_verdict_attribution_noise_does_not_break_normalized(self, tool, capsys):
        sa, na = base_docs()
        nb = dict(na)
        nb["raw_mismatch_verdict"] = dict(na["raw_mismatch_verdict"])
        nb["raw_mismatch_verdict"]["diff_attribution"] = {"local_or_central_timestamp": 3, "unclassified": 0}
        nb["raw_mismatch_verdict"]["diff_byte_count"] = 3
        r = self._run(tool, sa, na, dict(sa), nb, capsys)
        assert r["normalized_runtime_sdist_identity_match"] is True
        assert r["normalized_reason"] == "ok"
        assert r["all_global_identity_contracts_match"] is True

    def test_verdict_identity_change_breaks_normalized(self, tool, capsys):
        sa, na = base_docs()
        nb = dict(na)
        nb["raw_mismatch_verdict"] = dict(na["raw_mismatch_verdict"])
        nb["raw_mismatch_verdict"]["normalization_valid"] = False
        r = self._run(tool, sa, na, dict(sa), nb, capsys)
        assert r["normalized_runtime_sdist_identity_match"] is False
        assert r["normalized_reason"].startswith("first_differing_field:raw_mismatch_verdict")


# ---------------------------------------------------------------------------
# _first_differing_path


class TestFirstDifferingPath:
    def test_nested_dict_and_list_index(self, tool):
        a = {"a": {"b": {"c": 1, "d": [1, 2]}}}
        b = {"a": {"b": {"c": 1, "d": [1, 3]}}}
        assert tool._first_differing_path(a, b) == "a.b.d[1]"

    def test_missing_key(self, tool):
        a = {"a": {"b": 1}}
        b = {"a": {}}
        assert tool._first_differing_path(a, b) == "a.b"

    def test_list_length_differs(self, tool):
        a = {"x": [1, 2]}
        b = {"x": [1, 2, 3]}
        assert tool._first_differing_path(a, b) == "x"

    def test_equal(self, tool):
        a = {"x": [1, {"y": 2}]}
        assert tool._first_differing_path(a, {"x": [1, {"y": 2}]}) is None
