#!/usr/bin/env python3
"""Permanent fail-closed validator for the Python 3.14 compatibility surface.

The Python 3.14 test contract is an AUDITED SUBSET of the product suite:
the exact 294-node surface measured and sealed in PR #74
(docs/python314_compatibility_surface_redesign_canary.md). This script
validates that the permanent manifest ci/python314_compatibility_surface.txt
still describes exactly that surface before the workflow may execute it.

The contract is fully pinned by two hashes:

- manifest hash 2742853e... -- sha256 of the manifest bytes with UTF-8
  encoding, LF line separators, and exactly one trailing LF. A manifest
  mutation changes this hash, so a modified surface fails closed even
  before pytest runs.
- resolved digest 7561b50a... -- sha256 of the LF-joined, lexicographically
  SORTED, expanded pytest nodeids (UTF-8, no trailing LF). The derivation
  is the exact one that reproduced the sealed PR #74 digest; the validator
  refuses to guess a different derivation. Selector lines are NOT digested
  directly: whole-file selectors expand to every node, and parametrized
  selectors expand with [param] suffixes, so the digest is computed over
  the collected pytest nodeids themselves.

Fail-closed behavior: ANY deviation - missing/symlinked/empty manifest,
UTF-8 decode failure, blank selector, leading/trailing whitespace,
unsorted or duplicated selectors, invalid selector syntax, glob patterns,
-k/-m flags, directory selectors, whole-file/node overlap, wrong counts
(258 selectors = 2 whole-file + 256 node selectors), manifest hash
mismatch, pytest collection failure, an unresolved selector, duplicate
resolved nodes, wrong resolved node count (294), or resolved digest
mismatch - makes the validator exit non-zero and the workflow step must
fail without executing any test.

Properties:
- read-only: never modifies the repository (bytecode/cache writes are
  disabled for the collection subprocess)
- deterministic: fixed validation order, fixed marker output
- no network, no shell=True, no eval
- stdlib only, plus one `python -m pytest --collect-only` subprocess
- no lockfile/state: every run validates the manifest from scratch

Usage (run from the repository root, or pass --repo):

    python scripts/ci_python314_surface.py [--repo <PATH>]

Success marker (stdout, deterministic):

    PY314_SURFACE_VALIDATION_OK
    selectors=258
    whole_files=2
    partial_selectors=256
    resolved_nodes=294
    resolved_sha256=7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58

Exit codes:
    0 = manifest validated, surface exactly matches the sealed contract
    1 = validation failure (workflow must not run the 3.14 surface)
    2 = usage error
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_REL = Path("ci") / "python314_compatibility_surface.txt"

# Sealed PR #74 contract (docs/python314_compatibility_surface_redesign_canary.md).
EXPECTED_SELECTOR_COUNT = 258
EXPECTED_WHOLE_FILE_COUNT = 2
EXPECTED_PARTIAL_SELECTOR_COUNT = 256
EXPECTED_RESOLVED_NODE_COUNT = 294
EXPECTED_MANIFEST_SHA256 = (
    "2742853e8e997af8d32d43d6481bdb3f3b7d61df69ab9c2ab6bcdb9219cb5a7a"
)
EXPECTED_RESOLVED_SHA256 = (
    "7561b50a00b03040bdbd8075d0ae3481b668eeb86f5ed687a8ce5df737e37c58"
)

SUCCESS_MARKER = "PY314_SURFACE_VALIDATION_OK"
FAILURE_MARKER = "PY314_SURFACE_VALIDATION_FAILED"

# Strict selector shapes: a file selector is a tests/** python module; a
# node selector adds exactly one test_* node after ::. Everything else
# (directories, globs, flags, nested nodes, whitespace) is invalid.
_WHOLE_FILE_SELECTOR_RE = re.compile(r"^tests/[A-Za-z0-9_/.\-]+\.py$")
_NODE_SELECTOR_RE = re.compile(r"^tests/[A-Za-z0-9_/.\-]+\.py::test_[A-Za-z0-9_]+$")
_GLOB_RE = re.compile(r"[*?\[\]]")
_FLAG_RE = re.compile(r"(\s-k\b|\s-m\b)")
_FLAG_PREFIX = ("-k", "-m", "--ignore", "--deselect", "--collect-only")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest_bytes(manifest_path: Path) -> bytes:
    """Return the raw manifest bytes; raise OSError-style errors directly.

    Missing and symlinked manifests are distinct failures: a missing
    manifest means the contract file vanished; a symlink means the file
    could have been redirected. Both fail closed in validate_manifest_static.
    """
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    if manifest_path.is_symlink():
        raise OSError(f"manifest must not be a symlink: {manifest_path}")
    return manifest_path.read_bytes()


def _normalize_manifest(data: bytes) -> tuple[str, str | None]:
    """Decode and normalize the manifest to LF-only text.

    Returns (text, error). The normalization contract is runner-independent:
    a CRLF checkout must validate the same as an LF checkout, so CRLF is
    normalized to LF BEFORE every static check and before the hash. A lone
    CR (not part of CRLF) is invalid.
    """
    text = data.replace(b"\r\n", b"\n")
    if b"\r" in text:
        return "", "manifest contains a lone CR byte"
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError as exc:
        return "", f"manifest is not valid UTF-8: {exc}"
    return decoded, None


def split_manifest_lines(text: str) -> list[str]:
    """Split normalized text into selector lines.

    Requires exactly one trailing LF (the manifest ends with a newline and
    has no trailing blank line). Blank lines and lines with leading or
    trailing whitespace are invalid and returned as part of the line list;
    they are rejected by validate_manifest_static.
    """
    if not text.endswith("\n"):
        return [f"<missing trailing LF>"]  # placeholder, rejected below
    lines = text[:-1].split("\n")
    return lines


def validate_manifest_static(manifest_path: Path) -> list[str]:
    """Static manifest validation; returns a list of failure messages.

    Empty list means the static contract is fully satisfied. The checks
    run in a fixed order: load, decode/normalize, shape, count, order,
    uniqueness, overlap, hash. A single pass is deterministic.
    """
    failures: list[str] = []
    try:
        data = load_manifest_bytes(manifest_path)
    except FileNotFoundError:
        return [f"manifest not found: {manifest_path}"]
    except OSError as exc:
        return [str(exc)]

    if not data:
        return ["manifest is empty"]

    text, error = _normalize_manifest(data)
    if error is not None:
        return [error]

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
        if not (
            _WHOLE_FILE_SELECTOR_RE.fullmatch(line)
            or _NODE_SELECTOR_RE.fullmatch(line)
        ):
            failures.append(f"line {index}: invalid selector syntax: {line!r}")

    if failures:
        return failures

    whole_files = [
        line for line in lines if _WHOLE_FILE_SELECTOR_RE.fullmatch(line)
    ]
    node_selectors = [
        line for line in lines if _NODE_SELECTOR_RE.fullmatch(line)
    ]

    if len(lines) != EXPECTED_SELECTOR_COUNT:
        failures.append(
            f"expected {EXPECTED_SELECTOR_COUNT} selectors, found {len(lines)}"
        )
    if len(whole_files) != EXPECTED_WHOLE_FILE_COUNT:
        failures.append(
            f"expected {EXPECTED_WHOLE_FILE_COUNT} whole-file selectors, "
            f"found {len(whole_files)}"
        )
    if len(node_selectors) != EXPECTED_PARTIAL_SELECTOR_COUNT:
        failures.append(
            f"expected {EXPECTED_PARTIAL_SELECTOR_COUNT} node selectors, "
            f"found {len(node_selectors)}"
        )

    if lines != sorted(lines):
        failures.append("manifest is not lexicographically sorted")
    if len(set(lines)) != len(lines):
        failures.append("manifest contains duplicate selectors")

    for selector in node_selectors:
        file_part = selector.split("::", 1)[0]
        if file_part in whole_files:
            failures.append(
                f"node selector {selector!r} overlaps whole-file selector "
                f"{file_part!r}"
            )

    normalized = (text + "\n" if not text.endswith("\n") else text).encode("utf-8")
    actual_hash = _sha256_hex(normalized)
    if actual_hash != EXPECTED_MANIFEST_SHA256:
        failures.append(
            "manifest normalized SHA-256 mismatch: "
            f"expected {EXPECTED_MANIFEST_SHA256}, computed {actual_hash}"
        )

    return failures


def _default_runner(command: list[str], cwd: Path):
    """Run the pytest collection subprocess; overridable in tests."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd),
        env=env,
    )


def collect_nodeids(
    repo_root: Path,
    selectors: list[str],
    runner=None,
) -> tuple[list[str] | None, str | None]:
    """Collect pytest nodeids for the given selectors.

    Returns (nodeids, error); exactly one of them is non-None. The
    collection subprocess is the ONLY pytest execution the validator
    performs: `python -m pytest --collect-only -q <selectors>` with
    cache and bytecode writes disabled so the validator stays read-only.
    A non-zero collection exit (missing module, collection error) is a
    hard failure, not a skip.
    """
    if runner is None:
        runner = _default_runner
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--collect-only",
        "-q",
        *selectors,
    ]
    try:
        proc = runner(command, repo_root)
    except OSError as exc:
        return None, f"collection subprocess failed to start: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return None, (
            f"pytest collection failed (exit {proc.returncode})"
            + (f": {detail}" if detail else "")
        )
    nodeids = [
        line for line in proc.stdout.splitlines() if line.startswith("tests/")
    ]
    return nodeids, None


def validate_resolved(
    selectors: list[str], nodeids: list[str]
) -> list[str]:
    """Validate the expanded node set against the sealed contract.

    Every selector must resolve to at least one node (whole-file selectors
    expand to their nodes, node selectors must resolve exactly), resolved
    nodes must be unique, and the count and sorted-node digest must match
    the sealed PR #74 values exactly.
    """
    failures: list[str] = []
    whole_files = [
        line for line in selectors if _WHOLE_FILE_SELECTOR_RE.fullmatch(line)
    ]
    node_selectors = [
        line for line in selectors if _NODE_SELECTOR_RE.fullmatch(line)
    ]

    for selector in whole_files:
        if not any(node.startswith(selector + "::") for node in nodeids):
            failures.append(
                f"whole-file selector resolved to no nodes: {selector}"
            )
    for selector in node_selectors:
        # A node selector resolves verbatim, or as a parametrized
        # expansion: pytest emits nodeids with [param] suffixes, so
        # test_symlinked_artifact_fails resolves as
        # test_symlinked_artifact_fails[param1] etc.
        resolved = selector in nodeids or any(
            node.startswith(selector + "[") for node in nodeids
        )
        if not resolved:
            failures.append(f"node selector did not resolve: {selector}")

    if len(nodeids) != len(set(nodeids)):
        failures.append("collection produced duplicate node ids")

    if len(nodeids) != EXPECTED_RESOLVED_NODE_COUNT:
        failures.append(
            f"expected {EXPECTED_RESOLVED_NODE_COUNT} resolved nodes, "
            f"collected {len(nodeids)}"
        )

    if not failures:
        actual_digest = _sha256_hex(
            "\n".join(sorted(nodeids)).encode("utf-8")
        )
        if actual_digest != EXPECTED_RESOLVED_SHA256:
            failures.append(
                "resolved node digest mismatch: "
                f"expected {EXPECTED_RESOLVED_SHA256}, computed {actual_digest}"
            )

    return failures


def validate(repo_root: Path, runner=None) -> list[str]:
    """Full fail-closed validation; returns a list of failure messages.

    Empty list means the manifest exactly matches the sealed PR #74
    contract and is safe to execute on Python 3.14. The validation is
    read-only and deterministic; there is no state, cache, or lockfile.
    """
    manifest_path = repo_root / MANIFEST_REL
    failures = validate_manifest_static(manifest_path)
    if failures:
        return failures

    data = load_manifest_bytes(manifest_path)
    text, _ = _normalize_manifest(data)
    selectors = text[:-1].split("\n")

    nodeids, error = collect_nodeids(repo_root, selectors, runner=runner)
    if error is not None:
        return [error]

    return validate_resolved(selectors, nodeids)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_python314_surface.py",
        description=(
            "Permanent fail-closed validator for the Python 3.14 "
            "compatibility surface manifest (sealed PR #74 contract)."
        ),
    )
    parser.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo)
    failures = validate(repo_root)
    if failures:
        print(FAILURE_MARKER)
        for failure in failures:
            print(f"error: {failure}")
        return 1
    print(SUCCESS_MARKER)
    print(f"selectors={EXPECTED_SELECTOR_COUNT}")
    print(f"whole_files={EXPECTED_WHOLE_FILE_COUNT}")
    print(f"partial_selectors={EXPECTED_PARTIAL_SELECTOR_COUNT}")
    print(f"resolved_nodes={EXPECTED_RESOLVED_NODE_COUNT}")
    print(f"resolved_sha256={EXPECTED_RESOLVED_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
