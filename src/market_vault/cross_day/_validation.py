"""Pure validation shared by the parallel Cross-Day Label authority."""

import math
import re
from dataclasses import fields, replace
from datetime import date

from ..dataset.encoding import DatasetError, normalize_utc_datetime


class CrossDayLabelError(DatasetError):
    """Cross-Day Label admission or execution failed closed."""


def require(condition, message):
    if not condition:
        raise CrossDayLabelError(message)


def sha256(value, name):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            name + " must be a lowercase SHA256 digest")
    return value


def civil_date(value, name):
    require(type(value) is date, name + " must be an exact civil date")
    return value


def integer(value, name, *, minimum=0):
    require(type(value) is int and value >= minimum,
            name + " must be an integer within the admitted range")
    return value


def scalar(value, logical_type):
    if logical_type == "float64":
        require(type(value) is float and math.isfinite(value),
                "float64 requires an actual finite float")
        return 0.0 if value == 0.0 else value
    require(logical_type == "int64", "unsupported Cross-Day scalar type")
    require(type(value) is int and -(2 ** 63) <= value < 2 ** 63,
            "int64 requires an actual signed int64 value")
    return value


def digest_set(values, name):
    require(type(values) in (tuple, list), name + " must be an explicit sequence")
    normalized = tuple(sorted(sha256(value, name) for value in values))
    require(len(set(normalized)) == len(normalized), name + " contains duplicates")
    return normalized


def instant(value, name):
    normalized = normalize_utc_datetime(value, name)
    require(normalized == normalized, name + " must not be NaT")
    return normalized


def record(value):
    return {f.name: getattr(value, f.name) for f in fields(value) if f.init}


def typed_tuple(values, cls, name):
    require(type(values) in (tuple, list), name + " must be an explicit sequence")
    require(all(type(v) is cls for v in values), name + " has an invalid record type")
    return tuple(replace(v) for v in values)
