"""Literal final-path admission before any filesystem access or normalization."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from ._errors import _require
from ._canonical import _text


_FINAL = re.compile(r"schedule_artifact_id=[0-9a-f]{64}")
_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])(?:\.|$)", re.I)
_MEMBERS = ("_SUCCESS", "coverage_evidence.json", "manifest.json", "schedule.json",
            "source_snapshot.json", "verification_receipt.json")


def _component(text):
    _require(type(text) is str and text not in ("", ".", "..")
             and not text.endswith((".", " ")) and not _DEVICE.match(text)
             and not any(char in text for char in '<>:"/\\|?*'),
             "UNSAFE_PATH", "ambiguous path component")
    try:
        _text(text)
    except (TypeError, ValueError) as exc:
        _require(False, "UNSAFE_PATH", str(exc))


def _final_path(value, *, windows=None):
    # Only literal text preserves dot/empty components erased by Path constructors.
    _require(type(value) is str, "UNSAFE_PATH", "exact explicit path string required")
    windows = os.name == "nt" if windows is None else windows
    if windows:
        _require(re.match(r"^[A-Z]:[\\/]", value) is not None,
                 "UNSAFE_PATH", "absolute local DOS path required")
        parts = re.split(r"[\\/]", value[3:])
        cls = PureWindowsPath
    else:
        _require(value.startswith("/") and not value.startswith("//"),
                 "UNSAFE_PATH", "absolute local path required")
        parts, cls = value[1:].split("/"), PurePosixPath
    for part in parts:
        _component(part)
    _require(bool(_FINAL.fullmatch(parts[-1])), "UNSAFE_PATH", "exact final artifact name required")
    _require(not any(_FINAL.fullmatch(part) for part in parts[:-1]),
             "UNSAFE_PATH", "nested artifact path")
    return cls(value)


def _native_final_path(value):
    return Path(_final_path(value))
