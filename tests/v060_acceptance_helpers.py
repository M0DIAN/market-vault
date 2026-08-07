"""PR-8: shared acceptance helpers for the v0.6.0 integrated E2E tests.

Owns the static reference Canonical artifact (the PyArrow25-produced,
base64-encoded build tree under ``tests/fixtures/v060_portability/``) and
the small fixture builders / CLI runners the two acceptance test modules
(``test_v060_portability.py`` and ``test_v060_integrated_e2e.py``) use.

The static artifact is decoded with strict member checks (no ``.``, ``..``,
absolute prefixes, drive prefixes, or OS separators; every member's byte
size and sha256 must match the bundle line) and reproduces two frozen
regression values on every supported PyArrow version:
``FIXTURE_GENERATION_ID`` and ``FROZEN_RELATIVE_PLAN_SHA256``.

All helpers are fully offline: no settings, no OpenD, no network, no
current time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from market_vault import cli as cli_module
from market_vault.dataset import (
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
)
from market_vault.dataset.cli_models import DATASET_BUILD_PLAN_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

UTC = timezone.utc
NY = "America/New_York"
CREATED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
BUILT_AT = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
BUILT_AT_ISO = "2026-08-05T01:00:00+00:00"
CANONICAL_SCHEMA_VERSION = "market-bars-canonical-schema-v1"
SOURCE_SCHEMA_VERSION = "10.9"

# --- Static reference artifact (frozen at PR-8 time, PyArrow 25.0.0) --------

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v060_portability"
FIXTURE_BUNDLE = FIXTURE_DIR / "canonical_fixture.b64"
FIXTURE_METADATA = FIXTURE_DIR / "fixture_metadata.json"

#: The verified Canonical build id of the static artifact.
FIXTURE_BUILD_ID = (
    "ce939b043010eb3a4c12b063734edd320bb44801bbfa44715010d5330935a124"
)
#: The frozen generation content id reproduced from the static artifact.
FIXTURE_GENERATION_ID = (
    "f70e0c89793a1ccfb51d8a16720a8446a74989415ad7c491608d19e2dd759fb3"
)
#: The frozen sha256 of the relative-path generated build-plan bytes.
FROZEN_RELATIVE_PLAN_SHA256 = (
    "78cd9e895ee966722c83db8d5388a49c635b8fd448fe8de796e2b56dcebf964b"
)

#: Canonical tree member paths (relative to the build directory).
CANONICAL_MANIFEST_REL = "manifest.json"
CANONICAL_RESOLUTION_REL = "resolution.jsonl"
CANONICAL_SUCCESS_REL = "_SUCCESS"
CANONICAL_BARS_REL = (
    "bars/interval=1m/adjustment=NONE/code=US.MU/"
    "market_calendar_date=2026-07-01/part-00000.parquet"
)


def fixture_metadata() -> dict:
    return json.loads(FIXTURE_METADATA.read_text(encoding="utf-8"))


def decode_canonical_fixture(target_root: Path, *, under_dataset: bool = False) -> Path:
    """Decode the static Canonical artifact under ``target_root`` and return
    the build directory.

    Strict member checks reject any member path containing ``.``, ``..``,
    empty parts, a leading ``/``, a drive-letter prefix, or any OS
    separator; every member's byte size and sha256 must match its bundle
    line. With ``under_dataset=True`` the tree is placed at
    ``<target_root>/data/canonical/dataset=market_bars_canonical/`` so the
    copied relative path string in a generation plan stays identical to the
    frozen relative-plan bytes.
    """
    base = target_root
    if under_dataset:
        base = (
            target_root
            / "data"
            / "canonical"
            / "dataset=market_bars_canonical"
        )
    build_dir = base / f"build_id={FIXTURE_BUILD_ID}"
    build_dir.mkdir(parents=True, exist_ok=False)
    for line in FIXTURE_BUNDLE.read_text(encoding="ascii").splitlines():
        member, size_text, digest, encoded = line.split("\t")
        parts = member.split("/")
        assert member and not member.startswith("/"), member
        assert not any(part in (".", "..", "") for part in parts), member
        assert "\\" not in member, member
        assert not (len(member) > 1 and member[1] == ":"), member
        payload = base64.b64decode(encoded)
        assert len(payload) == int(size_text), member
        assert hashlib.sha256(payload).hexdigest() == digest, member
        target = build_dir.joinpath(member)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return build_dir


# --- CLI runners ------------------------------------------------------------


def run_cli(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli_module.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_cli_subprocess(*args: str, cwd=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "market_vault", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def _assert_success_json(code, out, err) -> dict:
    assert code == 0, err
    assert err == ""
    payload = json.loads(out)
    assert payload["result"] == "SUCCESS"
    return payload


def _assert_failed_json(code, out, err) -> dict:
    assert code == 1
    assert out == ""
    failure = json.loads(err)
    assert failure["result"] == "FAILED"
    return failure


# --- Generation-plan / build-plan writers -----------------------------------


def feature_spec_yaml(name="simple_return", window_bars=2, inputs=("close",)) -> str:
    inputs_yaml = "\n".join(f"    - {field}" for field in inputs)
    return f"""\
spec_schema_version: market-vault-feature-spec-v1
kind: FEATURE
name: {name}
version: v1
output:
  name: {name}
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
{inputs_yaml}
transform:
  ref: market_vault.dataset.feature_transforms.{name}:{name}
parameters:
  window_bars: {window_bars}
requirements:
  canonical_schema_versions:
    - {CANONICAL_SCHEMA_VERSION}
  source_schema_versions:
    - "{SOURCE_SCHEMA_VERSION}"
"""


def label_spec_yaml(name="forward_return", horizon=2, inputs=("close",)) -> str:
    inputs_yaml = "\n".join(f"    - {field}" for field in inputs)
    return f"""\
spec_schema_version: market-vault-label-spec-v1
kind: LABEL
name: {name}
version: v1
output:
  name: {name}
  logical_type: float64
  nullable: false
inputs:
  canonical_fields:
{inputs_yaml}
transform:
  ref: market_vault.dataset.label_transforms.{name}:{name}
parameters: {{}}
requirements:
  canonical_schema_versions:
    - {CANONICAL_SCHEMA_VERSION}
  source_schema_versions:
    - "{SOURCE_SCHEMA_VERSION}"
observation_window:
  unit: BARS
  start_offset: {horizon - 1}
  end_offset: {horizon - 1}
horizon:
  unit: BARS
  value: {horizon}
alignment_rule: FEATURE_CLOSE_ALIGNED
missing_data_policy: INCOMPLETE
cross_trading_day:
  allow: false
  boundary_rule: null
"""

#: The core-side split payload (mirrors test_sample_generation_core.py); its
#: content sha256 enters the frozen generation content id.
SPLIT_SPEC_CORE_PAYLOAD = {
    "spec_schema_version": "market-vault-chronological-split-spec-v1",
    "name": "chronological_split",
    "version": "v1",
    "boundary_timezone": NY,
    "train_end_date": "2026-06-30",
    "validation_end_date": "2026-07-15",
    "test_end_date": "2026-07-31",
    "assignment_rule": "FEATURE_WINDOW_CLOSE_DATE",
    "purge_rule": "ACTUAL_LABEL_END",
    "incomplete_label_policy": "EXCLUDE",
    "out_of_range_policy": "EXCLUDE",
}

#: The CLI-side split payload (mirrors test_sample_generation_cli.py); its
#: content sha256 enters the frozen relative build-plan bytes.
SPLIT_SPEC_CLI_PAYLOAD = {
    "spec_schema_version": "market-vault-chronological-split-spec-v1",
    "name": "chrono",
    "version": "v1",
    "boundary_timezone": NY,
    "train_end_date": "2026-06-30",
    "validation_end_date": "2026-07-01",
    "test_end_date": "2026-07-02",
    "assignment_rule": "FEATURE_WINDOW_CLOSE_DATE",
    "purge_rule": "ACTUAL_LABEL_END",
    "incomplete_label_policy": "EXCLUDE",
    "out_of_range_policy": "EXCLUDE",
}


def write_fixture_files(
    tmp_path: Path, *, split_payload: dict | None = None
) -> tuple[str, str, str]:
    """Write the two spec YAML files and one chronological split JSON under
    ``tmp_path/specs/`` and return ``(feature_paths, label_paths,
    split_path)`` as strings."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    feature_path = spec_dir / "simple_return.yaml"
    feature_path.write_text(feature_spec_yaml(), encoding="utf-8")
    label_path = spec_dir / "forward_return.yaml"
    label_path.write_text(label_spec_yaml(horizon=2), encoding="utf-8")
    split_path = spec_dir / "chronological_split.json"
    split_path.write_text(
        json.dumps(
            split_payload or SPLIT_SPEC_CORE_PAYLOAD, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return (str(feature_path),), (str(label_path),), str(split_path)


def generation_plan_dict(
    *,
    build_dirs,
    feature_paths,
    label_paths,
    split_path,
    symbols=("US.MU",),
    trade_dates=("2026-07-01",),
    output_root="datasets",
    output_plan_path="generated-plan.json",
) -> dict:
    """One generation-plan payload (key order = JSON key order), mirroring
    the frozen relative-plan fixture payload."""
    return {
        "generation_plan_schema_version": SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        "canonical_build_dirs": list(build_dirs),
        "feature_spec_files": list(feature_paths),
        "label_spec_files": list(label_paths),
        "split_spec_file": split_path,
        "scope": {
            "symbols": list(symbols),
            "trade_dates": list(trade_dates),
            "interval": "1m",
            "adjustment": "NONE",
            "requested_session": "ALL",
        },
        "generation_rule": {
            "rule_schema_version": SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
            "feature_window_bars": 3,
            "label_window_bars": 2,
            "stride_bars": 2,
            "anchor_source": "VERIFIED_CANONICAL_BARS",
            "anchor_rule": "FEATURE_WINDOW_CLOSE",
            "cross_day_policy": "REJECT",
        },
        "dataset_as_of": None,
        "output_root": output_root,
        "built_at": BUILT_AT_ISO,
        "output_plan_path": output_plan_path,
    }


def relative_payload(build_dir: Path, root: Path, *, output_plan_path: str) -> dict:
    """A generation-plan payload whose copied paths are all POSIX-relative
    to ``root`` (the frozen relative-plan fixture shape)."""
    return generation_plan_dict(
        build_dirs=(build_dir.relative_to(root).as_posix(),),
        feature_paths=("specs/simple_return.yaml",),
        label_paths=("specs/forward_return.yaml",),
        split_path="specs/chronological_split.json",
        output_root="datasets",
        output_plan_path=output_plan_path,
    )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def write_generation_plan(path: Path, payload: dict) -> Path:
    write_json(path, payload)
    return path


def default_build_plan_dict(
    *,
    canonical_dirs,
    output_root="out",
    built_at=BUILT_AT_ISO,
) -> dict:
    """One dataset-build plan payload (mirrors test_dataset_cli.py's
    ``default_plan_dict`` for the corruption / recovery tests)."""
    return {
        "plan_schema_version": DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "canonical_build_dirs": list(canonical_dirs),
        "feature_spec_files": ["specs/feature_sr.yaml"],
        "label_spec_files": ["specs/label_fr.yaml"],
        "requests": [
            {
                "code": "US.MU",
                "interval": "1m",
                "adjustment": "NONE",
                "requested_session": "ALL",
                "anchor_market_calendar_date": "2026-07-01",
                "feature_window_start": "2026-07-01T13:30:00+00:00",
                "feature_window_close": "2026-07-01T13:36:00+00:00",
                "label_window_start": "2026-07-01T13:36:00+00:00",
                "label_window_close": "2026-07-01T13:42:00+00:00",
            }
        ],
        "scope": {
            "symbols": ["US.MU"],
            "trade_dates": ["2026-07-01"],
            "interval": "1m",
            "adjustment": "NONE",
            "requested_session": "ALL",
        },
        "split_spec": SPLIT_SPEC_CLI_PAYLOAD,
        "dataset_as_of": None,
        "output_root": output_root,
        "built_at": built_at,
    }


# --- Corruption / no-write-proof helpers -------------------------------------


def append_bytes(path: Path, junk: bytes = b"\x00CORRUPTED-ACCEPTANCE") -> None:
    with path.open("ab") as handle:
        handle.write(junk)


def corrupt_manifest(build_dir: Path) -> None:
    append_bytes(build_dir / CANONICAL_MANIFEST_REL)


def corrupt_resolution(build_dir: Path) -> None:
    append_bytes(build_dir / CANONICAL_RESOLUTION_REL)


def corrupt_success(build_dir: Path) -> None:
    (build_dir / CANONICAL_SUCCESS_REL).write_bytes(b"not empty")


def corrupt_bars(build_dir: Path) -> None:
    append_bytes(build_dir / CANONICAL_BARS_REL)


def delete_member(build_dir: Path, relative: str) -> None:
    (build_dir / relative).unlink()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(directory: Path) -> dict:
    """Per-entry (size, mtime_ns, sha256) map proving no-write.

    Only regular files are hashed; directory entries contribute their
    lstat facts so entry-set and mtime changes are still detected.
    """
    result = {}
    for root, dirs, files in os.walk(directory):
        for name in sorted(dirs) + sorted(files):
            path = Path(root) / name
            rel = path.relative_to(directory).as_posix()
            st = path.lstat()
            if path.is_file():
                result[rel] = (
                    st.st_size,
                    st.st_mtime_ns,
                    sha256_bytes(path.read_bytes()),
                )
            else:
                result[rel + "/"] = (st.st_size, st.st_mtime_ns, None)
    return result


def _make_symlink_or_skip(target: Path, link: Path) -> None:
    """Create a symlink, falling back to a Windows junction (junctions need
    no elevated privileges); skip when neither is available."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt" and target.is_dir():
        try:
            import _winapi

            _winapi.CreateJunction(str(target.absolute()), str(link.absolute()))
            return
        except (OSError, TypeError, ImportError):
            pass
    pytest.skip(f"cannot create a symlink or junction in this environment: {link}")
