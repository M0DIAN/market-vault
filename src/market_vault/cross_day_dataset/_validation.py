"""Pure admission primitives for the parallel Cross-Day Dataset cohort."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from math import copysign, isfinite
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import MappingProxyType

REASON_CODES = frozenset((
    "INPUT_TYPE", "SCOPE", "DUPLICATE_INPUT", "PIT_BINDING", "A3_BINDING",
    "TS2_FEATURE_BINDING", "OBSERVATION_FEATURE_BINDING", "CROSS_DAY_BINDING",
    "SCHEDULE_BINDING", "CLOCK_AUTHORITY", "SPEC_CONTRACT", "IMPLEMENTATION_BINDING",
    "MATRIX_ELIGIBILITY", "SPLIT_BINDING", "IDENTITY_AUTHORITY", "RESULT_AUTHORITY",
))


class MultiSourceCrossDayDatasetError(ValueError):
    def __init__(self, reason_code, message):
        if reason_code not in REASON_CODES:
            raise ValueError("unknown Cross-Day Dataset authority reason")
        self.reason_code = reason_code
        super().__init__(reason_code + ": " + message)


def require(condition, code, message):
    if not condition:
        raise MultiSourceCrossDayDatasetError(code, message)


@contextmanager
def stage(code):
    try:
        yield
    except MultiSourceCrossDayDatasetError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError) as exc:
        raise MultiSourceCrossDayDatasetError(code, str(exc)) from exc


def records(value, cls, key, code="INPUT_TYPE"):
    require(type(value) is tuple and all(type(v) is cls for v in value), code,
            "exact immutable " + cls.__name__ + " tuple required")
    keys = tuple(key(v) for v in value)
    require(len(set(keys)) == len(keys), "DUPLICATE_INPUT", "duplicate " + cls.__name__)
    return tuple(sorted(value, key=key))


def checked_record(value, cls, code):
    require(type(value) is cls, code, "exact " + cls.__name__ + " required")
    copy = replace(value)
    require(copy == value, code, "record normalization mismatch")
    return copy


def cutoff(value):
    if value is None:
        return None
    require(type(value) is datetime and value.utcoffset() is not None,
            "CLOCK_AUTHORITY", "explicit aware datetime or null required")
    return value.astimezone(timezone.utc)


def digest(value):
    require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
            "IDENTITY_AUTHORITY", "lowercase SHA256 required")
    return value


def numeric(value, logical_type, code):
    if logical_type == "float64":
        require(type(value) is float and isfinite(value) and
                (value != 0.0 or copysign(1.0, value) > 0), code, "finite normalized float64 required")
    else:
        require(logical_type == "int64" and type(value) is int and -(2**63) <= value < 2**63,
                code, "exact signed int64 required")
    return value


def require_immutable(value):
    """Reject mutable nested caller containers before they can enter issued output."""
    require(not isinstance(value, (list, dict, set, bytearray)), "RESULT_AUTHORITY", "mutable recorded authority")
    if is_dataclass(value) and not isinstance(value, type):
        require(value.__dataclass_params__.frozen, "RESULT_AUTHORITY", "mutable record")
        for field in fields(value):
            require_immutable(getattr(value, field.name))
    elif isinstance(value, Mapping):
        require(type(value) is MappingProxyType, "RESULT_AUTHORITY", "immutable mapping projection required")
        for key, member in value.items():
            require_immutable(key)
            require_immutable(member)
    elif type(value) in (tuple, frozenset):
        for member in value:
            require_immutable(member)
