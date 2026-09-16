"""Small in-memory validation primitives for the separate A4.2 cohort."""

from dataclasses import fields, is_dataclass, replace
from collections.abc import Mapping
from types import MappingProxyType

from ..dataset.encoding import DatasetError, encode_identity
from ..observation._validation import sha256


class MultiSourceDatasetError(DatasetError):
    """Fail-closed admission or closure failure; no partial Dataset result."""


def require(condition, message):
    if not condition:
        raise MultiSourceDatasetError(message)


def exact(value, cls, label):
    require(type(value) is cls, f"{label} requires exact {cls.__name__}")
    return value


def items(value, cls, label, *, nonempty=False):
    require(type(value) is tuple, f"{label} requires an explicit tuple")
    require(not nonempty or bool(value), f"{label} must be nonempty")
    for item in value:
        exact(item, cls, label)
    return value


def hashes(value, label, *, distinct=False):
    items(value, str, label)
    for item in value:
        sha256(item, label)
    require(distinct or len(set(value)) == len(value), f"duplicate {label}")
    return tuple(sorted(set(value) if distinct else value))


def pin_key(pin):
    return pin.kind, pin.name, pin.version, pin.content_sha256


def sequence(domain, ids):
    for item in ids:
        sha256(item, domain)
    return encode_identity(domain, {"count": len(ids), "members": "".join(ids)})


def record(value):
    """Exact named dataclass fields only; exclude derived dynamic attributes."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: record(getattr(value, f.name)) for f in fields(value)}
    if type(value) is tuple:
        return tuple(record(v) for v in value)
    return value


def flatten(prefix, value):
    """Frozen F encoding. Call only on validated exact-schema records."""
    if isinstance(value, Mapping):
        require(all(type(k) is str and k and "." not in k for k in value), "invalid F record key")
        if not value:
            return {prefix + ".count": 0}
        result = {}
        for key in sorted(value):
            result.update(flatten(prefix + "." + key, value[key]))
        return result
    if type(value) is tuple:
        result = {prefix + ".count": len(value)}
        for index, member in enumerate(value):
            result.update(flatten(f"{prefix}.{index:04d}", member))
        return result
    return {prefix: value}


def freeze_copy(value):
    """Detach mutable mapping leaves in inherited frozen result dataclasses."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze_copy(v) for k, v in value.items()})
    if type(value) in (tuple, list):
        return tuple(freeze_copy(v) for v in value)
    if is_dataclass(value) and not isinstance(value, type):
        # These are already admitted result models; never modify caller objects.
        clone = object.__new__(type(value))
        names = set()
        for f in fields(value):
            names.add(f.name)
            object.__setattr__(clone, f.name, freeze_copy(getattr(value, f.name)))
        for name, member in getattr(value, "__dict__", {}).items():
            if name not in names:
                object.__setattr__(clone, name, freeze_copy(member))
        return clone
    return value


def canonical_copy(value, cls, label):
    exact(value, cls, label)
    copy = replace(value)
    require(record(copy) == record(value), f"noncanonical {label}")
    return copy
