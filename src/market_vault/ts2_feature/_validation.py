"""Fail-closed scalar checks for the parallel TS2 Feature authority."""

import math

from ..dataset.encoding import DatasetError, normalize_utc_datetime

REASON_CODES = (
    "SOURCE_COHORT", "SCOPE", "DUPLICATE_INPUT", "CANONICAL_AUTHORITY",
    "CANONICAL_CONFLICT", "PIT_AUTHORITY", "CLOCK_AUTHORITY", "SPEC_CONTRACT",
    "REGISTRY_AUTHORITY", "SOURCE_FINGERPRINT", "TRANSFORM_DOMAIN",
    "TRANSFORM_OUTPUT", "RESULT_AUTHORITY",
)


class TS2FeatureError(DatasetError):
    """An invocation failure, never a Feature EXCLUDED outcome."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in REASON_CODES:
            raise ValueError("unknown TS2 Feature authority reason")
        self.reason_code = reason_code
        super().__init__(reason_code + (": " + detail if detail else ""))


def require(condition, code, detail):
    if not condition:
        raise TS2FeatureError(code, detail)


def instant(value):
    try:
        return normalize_utc_datetime(value, "TS2 Feature instant")
    except (ValueError, TypeError, OverflowError) as exc:
        raise TS2FeatureError("CLOCK_AUTHORITY", "invalid aware instant") from exc


def finite_float(value, code):
    require(type(value) is float and math.isfinite(value), code, "actual finite float64 required")
    return 0.0 if value == 0.0 else value


def digest(value):
    require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
            "RESULT_AUTHORITY", "invalid identity digest")
    return value
