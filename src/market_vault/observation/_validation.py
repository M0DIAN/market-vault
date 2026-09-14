"""Pure construction checks shared by Observation schemas and records."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime

from ..dataset.encoding import (
    DatasetError,
    normalize_nfc,
    normalize_utc_datetime,
    reject_unsafe_text,
)


class ObservationError(ValueError):
    """Invalid Observation semantic input; not proof of artifact verification."""


def text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ObservationError(f"{label} must be nonempty text without surrounding whitespace")
    value = normalize_nfc(value)
    try:
        reject_unsafe_text(value, label)
    except DatasetError as exc:
        raise ObservationError(str(exc)) from exc
    if any(unicodedata.category(c) in {"Cf", "Cs"} for c in value):
        raise ObservationError(f"unsafe Unicode in {label}")
    return value


def sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ObservationError(f"{label} must be lowercase 64-hex SHA-256")
    return value


def instant(value: datetime, label: str) -> datetime:
    try:
        result = normalize_utc_datetime(value, label)
        if not isinstance(result, datetime) or result.utcoffset() is None:
            raise ValueError("invalid instant")
        return result
    except (ValueError, TypeError, OverflowError) as exc:
        raise ObservationError(f"{label} must be a representable timezone-aware instant") from exc


def items(value, item_type: type, label: str, *, nonempty: bool = False) -> tuple:
    if not isinstance(value, (tuple, list)):
        raise ObservationError(f"{label} must be a tuple or list")
    result = tuple(value)
    if nonempty and not result:
        raise ObservationError(f"{label} must not be empty")
    if any(type(item) is not item_type for item in result):
        raise ObservationError(f"{label} must contain {item_type.__name__} instances")
    return result


def hashes(value, label: str) -> tuple[str, ...]:
    result = items(value, str, label, nonempty=True)
    for item in result:
        sha256(item, label)
    if len(set(result)) != len(result):
        raise ObservationError(f"duplicate {label}")
    return tuple(sorted(result))


def numeric(value, logical_type: str):
    if logical_type == "int64":
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise ObservationError("int64 requires an exact signed 64-bit integer, not bool")
    elif logical_type == "float64":
        if type(value) is not float or not math.isfinite(value):
            raise ObservationError("float64 requires a finite float, without type inference")
        if value == 0.0:
            value = 0.0
    else:
        raise ObservationError(f"unsupported numeric logical type {logical_type!r}")
    return value
