"""Focused tests for the permanent Python 3.14 compatibility surface
validator (scripts/ci_python314_surface.py).

The validator is fail-closed: ANY deviation from the sealed PR #74
contract fails the validation. These tests cover the static manifest
contract (shape, counts, order, uniqueness, overlap, hash), the resolved
node contract (collection failures, unresolved selectors, duplicates,
count, digest), the runner-independence contract (CRLF normalization),
and the exact sealed digest derivation. Collection is injected with a
fake runner everywhere except the two end-to-end tests that run the real
pytest collection once (session-scoped, ~2s), which also pins the sealed
294-node digest.

Failure reporting is cumulative (mirroring check_release.py's
_py314_manifest_static_failures): shape/count/order/overlap diagnostics
are all reported, and the sealed-hash check runs last, so a byte
mutation that trips a diagnostic also trips the hash. Tests therefore
assert on fragment presence, with exact counts only where the validator
guarantees a single failure (early-return paths).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_python314_surface.py"
MANIFEST_REL = Path("ci") / "python314_compatibility_surface.txt"
REAL_MANIFEST = ROOT / MANIFEST_REL

SEALED_MANIFEST_SHA256 = (
    "2742853e8e997af8d32d43d6481bdb3f3b7d61df69ab9c2ab6bcdb9219cb5a7a"
)
SEALED_RESOLVED_SHA256 = (
    "7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58"
)
SEALED_SELECTOR_COUNT = 258
SEALED_WHOLE_FILE_COUNT = 2
SEALED_PARTIAL_SELECTOR_COUNT = 256
SEALED_RESOLVED_NODE_COUNT = 294

REAL_SELECTORS = REAL_MANIFEST.read_text(encoding="utf-8").splitlines()


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "ci_python314_surface", str(SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


surface = _load_validator()


@pytest.fixture(scope="session")
def sealed_nodeids():
    """The 294 nodeids of the real manifest, collected once per session
    with the real pytest subprocess (the exact derivation input)."""
    assert len(REAL_SELECTORS) == SEALED_SELECTOR_COUNT
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            *REAL_SELECTORS,
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    assert proc.returncode == 0, proc.stderr
    nodeids = [
        line for line in proc.stdout.splitlines() if line.startswith("tests/")
    ]
    assert len(nodeids) == SEALED_RESOLVED_NODE_COUNT, proc.stdout
    assert (
        hashlib.sha256(
            "\n".join(sorted(nodeids)).encode("utf-8")
        ).hexdigest()
        == SEALED_RESOLVED_SHA256
    )
    return nodeids


def sibling_nodes(selector: str, nodeids: list[str]) -> list[str]:
    """The collected nodes a selector resolves to (verbatim or expanded)."""
    if "::" in selector:
        return [
            n
            for n in nodeids
            if n == selector or n.startswith(selector + "[")
        ]
    return [n for n in nodeids if n.startswith(selector + "::")]


def singleton_node(nodeids: list[str]) -> str:
    """A node whose selector resolves to exactly itself (removing it must
    leave that selector unresolved)."""
    for selector in REAL_SELECTORS:
        siblings = sibling_nodes(selector, nodeids)
        if len(siblings) == 1:
            return siblings[0]
    raise AssertionError("no singleton node found in sealed surface")


def redundant_node(nodeids: list[str]) -> str:
    """A node whose selector still resolves after it is removed."""
    for selector in REAL_SELECTORS:
        siblings = sibling_nodes(selector, nodeids)
        if len(siblings) >= 2:
            return siblings[0]
    raise AssertionError("no redundant node found in sealed surface")


class FakeProc:
    """CompletedProcess stand-in for the injected collection runner."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Records the subprocess command and returns a canned result."""

    def __init__(self, proc):
        self.proc = proc
        self.calls = []

    def __call__(self, command, cwd):
        self.calls.append((command, cwd))
        return self.proc


def make_repo(tmp_path: Path) -> Path:
    """A temporary repo root holding the real manifest at the pinned path."""
    repo = tmp_path / "repo"
    (repo / "ci").mkdir(parents=True)
    shutil.copyfile(REAL_MANIFEST, repo / MANIFEST_REL)
    return repo


def write_manifest(repo: Path, text: str) -> None:
    (repo / MANIFEST_REL).write_text(text, encoding="utf-8")


def nodeids_stdout(nodeids: list[str]) -> str:
    return "\n".join(nodeids) + "\n294 tests collected in 0.1s\n"


def assert_failure(
    failures: list[str], fragment: str, expected_count: int | None = None
) -> None:
    """Assert the diagnostic is present; optionally pin the total count."""
    assert any(fragment in f for f in failures), failures
    if expected_count is not None:
        assert len(failures) == expected_count, failures


# ---------------------------------------------------------------------------
# End-to-end: the real manifest + the real collection.
# ---------------------------------------------------------------------------


def test_real_manifest_static_validation_passes(tmp_path):
    repo = make_repo(tmp_path)
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert failures == []


def test_real_manifest_full_validation_passes_with_real_collection():
    """The permanent manifest + the real pytest collection reproduces the
    sealed 294-node digest exactly (end-to-end). Runs against the real
    repository root: the collection subprocess needs the full source tree."""
    failures = surface.validate(ROOT)
    assert failures == []


def test_main_prints_success_marker(monkeypatch, capsys):
    monkeypatch.setattr(surface, "validate", lambda root: [])
    assert surface.main(["--repo", "."]) == 0
    out = capsys.readouterr().out
    assert out.startswith("PY314_SURFACE_VALIDATION_OK\n")
    assert f"selectors={SEALED_SELECTOR_COUNT}" in out
    assert f"resolved_nodes={SEALED_RESOLVED_NODE_COUNT}" in out
    assert f"resolved_sha256={SEALED_RESOLVED_SHA256}" in out


def test_main_prints_failure_marker_and_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(surface, "validate", lambda root: ["broken"])
    assert surface.main(["--repo", "."]) == 1
    out = capsys.readouterr().out
    assert out.startswith("PY314_SURFACE_VALIDATION_FAILED\n")
    assert "error: broken" in out


# ---------------------------------------------------------------------------
# Static manifest contract (early-return paths: exactly one failure).
# ---------------------------------------------------------------------------


def test_missing_manifest_fails(tmp_path):
    repo = tmp_path / "repo"
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "manifest not found", 1)


def test_symlinked_manifest_fails(tmp_path):
    repo = make_repo(tmp_path)
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(repo / MANIFEST_REL)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    failures = surface.validate_manifest_static(link)
    assert_failure(failures, "must not be a symlink", 1)


def test_empty_manifest_fails(tmp_path):
    repo = make_repo(tmp_path)
    write_manifest(repo, "")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "manifest is empty", 1)


def test_blank_line_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines.insert(100, "")
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "blank selector", 1)


def test_leading_whitespace_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0] = " " + lines[0]
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "leading or trailing whitespace", 1)


def test_trailing_whitespace_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[5] = lines[5] + " "
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "leading or trailing whitespace", 1)


def test_missing_trailing_lf_fails(tmp_path):
    repo = make_repo(tmp_path)
    text = REAL_MANIFEST.read_text(encoding="utf-8").rstrip("\n")
    write_manifest(repo, text)
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "exactly one trailing LF", 1)


def test_trailing_blank_line_fails(tmp_path):
    repo = make_repo(tmp_path)
    write_manifest(repo, REAL_MANIFEST.read_text(encoding="utf-8") + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "trailing blank line", 1)


def test_glob_selector_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0] = "tests/test_canonical_reader.py::test_*"
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "glob pattern is not allowed", 1)


def test_k_flag_selector_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0] = "tests/test_canonical_reader.py -k test_canonical"
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "pytest flag is not allowed", 1)


def test_m_flag_selector_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0] = "tests/test_canonical_reader.py -m slow"
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "pytest flag is not allowed", 1)


def test_directory_selector_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0] = "tests/test_canonical_reader"
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "invalid selector syntax", 1)


def test_nested_node_selector_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0] = "tests/test_canonical_reader.py::test_a::test_b"
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "invalid selector syntax", 1)


# ---------------------------------------------------------------------------
# Static manifest contract (cumulative diagnostics; a byte mutation also
# trips the sealed-hash check, so the specific diagnostic must simply be
# present).
# ---------------------------------------------------------------------------


def test_unsorted_manifest_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[0], lines[1] = lines[1], lines[0]
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "not lexicographically sorted")


def test_duplicate_selector_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines.insert(3, lines[0])
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "duplicate selectors")


def test_whole_file_node_overlap_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    node_index = next(i for i, line in enumerate(lines) if "::" in line)
    lines[node_index] = "tests/test_canonical_reader.py::test_overlap"
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "overlaps whole-file selector")


def test_wrong_selector_count_fails(tmp_path):
    repo = make_repo(tmp_path)
    write_manifest(repo, "\n".join(REAL_SELECTORS[:-1]) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, f"expected {SEALED_SELECTOR_COUNT} selectors")


def test_wrong_whole_file_count_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    lines[2] = lines[2].split("::")[0]
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(
        failures, f"expected {SEALED_WHOLE_FILE_COUNT} whole-file selectors"
    )


def test_wrong_partial_selector_count_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    node_index = next(i for i, line in enumerate(lines) if "::" in line)
    lines[node_index] = "tests/test_wrong_count_surface.py"
    write_manifest(repo, "\n".join(sorted(lines)) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(
        failures, f"expected {SEALED_PARTIAL_SELECTOR_COUNT} node selectors"
    )


def test_manifest_hash_mismatch_fails(tmp_path):
    repo = make_repo(tmp_path)
    lines = list(REAL_SELECTORS)
    # Grow the last line lexicographically: still sorted, still shape-valid,
    # same counts — only the hash changes.
    lines[-1] = lines[-1].replace("test_", "test_z", 1)
    write_manifest(repo, "\n".join(lines) + "\n")
    failures = surface.validate_manifest_static(repo / MANIFEST_REL)
    assert_failure(failures, "SHA-256 mismatch", 1)


def test_crlf_manifest_normalizes_to_lf(tmp_path, sealed_nodeids):
    """A CRLF checkout must validate the same as an LF checkout: CRLF is
    normalized before every static check and before the hash."""
    normalized, error = surface._normalize_manifest(REAL_MANIFEST.read_bytes())
    assert error is None
    lf_data = normalized.encode("utf-8")
    crlf_data = lf_data.replace(b"\n", b"\r\n")

    results = []
    for name, data in (("lf", lf_data), ("crlf", crlf_data)):
        repo = tmp_path / name
        (repo / "ci").mkdir(parents=True)
        (repo / MANIFEST_REL).write_bytes(data)
        runner = FakeRunner(FakeProc(stdout=nodeids_stdout(sealed_nodeids)))
        results.append(surface.validate(repo, runner=runner))
    assert results == [[], []]


# ---------------------------------------------------------------------------
# Resolved node contract (collection injected).
# ---------------------------------------------------------------------------


def test_success_with_mocked_collection(tmp_path, sealed_nodeids):
    """The full validation passes when collection returns exactly the
    sealed 294 nodeids, and the collection command is the pinned
    read-only form."""
    repo = make_repo(tmp_path)
    runner = FakeRunner(FakeProc(stdout=nodeids_stdout(sealed_nodeids)))
    failures = surface.validate(repo, runner=runner)
    assert failures == []
    assert len(runner.calls) == 1
    command, cwd = runner.calls[0]
    expected_prefix = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--collect-only",
        "-q",
    ]
    assert command[: len(expected_prefix)] == expected_prefix
    assert command[len(expected_prefix):] == REAL_SELECTORS
    assert Path(cwd) == repo


def test_collection_failure_fails(tmp_path):
    repo = make_repo(tmp_path)
    runner = FakeRunner(
        FakeProc(returncode=2, stderr="ERROR: file not found: tests/x.py")
    )
    failures = surface.validate(repo, runner=runner)
    assert_failure(failures, "pytest collection failed", 1)


def test_collection_subprocess_crash_fails(tmp_path):
    repo = make_repo(tmp_path)

    def crashing_runner(command, cwd):
        raise OSError("no python")

    failures = surface.validate(repo, runner=crashing_runner)
    assert_failure(failures, "failed to start", 1)


def test_unresolved_node_selector_fails(tmp_path, sealed_nodeids):
    """Removing the ONLY node of a partial selector leaves it unresolved
    (and the count check also fires — both diagnostics are expected)."""
    repo = make_repo(tmp_path)
    nodeids = [n for n in sealed_nodeids if n != singleton_node(sealed_nodeids)]
    runner = FakeRunner(FakeProc(stdout=nodeids_stdout(nodeids)))
    failures = surface.validate(repo, runner=runner)
    assert_failure(failures, "did not resolve")


def test_unresolved_whole_file_selector_fails(tmp_path, sealed_nodeids):
    """Removing every node of the deprecation whole-file selector leaves
    it resolved to no nodes (and the count check also fires)."""
    repo = make_repo(tmp_path)
    nodeids = [
        n
        for n in sealed_nodeids
        if not n.startswith("tests/test_deprecation_compatibility_v051.py::")
    ]
    runner = FakeRunner(FakeProc(stdout=nodeids_stdout(nodeids)))
    failures = surface.validate(repo, runner=runner)
    assert_failure(failures, "resolved to no nodes")


def test_duplicate_resolved_node_fails(tmp_path, sealed_nodeids):
    repo = make_repo(tmp_path)
    nodeids = list(sealed_nodeids)
    nodeids.append(nodeids[-1])
    runner = FakeRunner(FakeProc(stdout=nodeids_stdout(nodeids)))
    failures = surface.validate(repo, runner=runner)
    assert_failure(failures, "duplicate node ids")


def test_wrong_resolved_count_fails(tmp_path, sealed_nodeids):
    """Removing one node that still has a sibling under its selector must
    trip ONLY the count check — every selector still resolves."""
    repo = make_repo(tmp_path)
    nodeids = [
        n for n in sealed_nodeids if n != redundant_node(sealed_nodeids)
    ]
    runner = FakeRunner(FakeProc(stdout=nodeids_stdout(nodeids)))
    failures = surface.validate(repo, runner=runner)
    assert_failure(
        failures,
        f"expected {SEALED_RESOLVED_NODE_COUNT} resolved nodes",
        1,
    )


def test_wrong_resolved_digest_fails(tmp_path, sealed_nodeids):
    """The digest is computed over the SORTED node set, so the mutation
    must CHANGE the multiset (a permutation is a no-op for the digest):
    rewrite one parametrized node's param. Its selector still resolves,
    the count and uniqueness hold — only the digest changes."""
    repo = make_repo(tmp_path)
    nodeids = list(sealed_nodeids)
    i = next(i for i, n in enumerate(nodeids) if "[" in n)
    nodeids[i] = nodeids[i].split("[", 1)[0] + "[zzz_digest_mutation]"
    runner = FakeRunner(FakeProc(stdout=nodeids_stdout(nodeids)))
    failures = surface.validate(repo, runner=runner)
    assert_failure(failures, "resolved node digest mismatch", 1)


def test_digest_derivation_matches_sealed_contract(sealed_nodeids):
    """The exact sealed derivation: sha256 over the LF-joined,
    lexicographically SORTED nodeids, UTF-8, no trailing LF."""
    digest = hashlib.sha256(
        "\n".join(sorted(sealed_nodeids)).encode("utf-8")
    ).hexdigest()
    assert digest == SEALED_RESOLVED_SHA256
