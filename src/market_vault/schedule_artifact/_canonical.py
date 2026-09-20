"""Strict L4 canonical JSON and RFC 4648 base64, entirely in memory."""

import base64
import json
import unicodedata

from ..dataset.encoding import reject_unsafe_text


def _text(value: str) -> None:
    if type(value) is not str:
        raise TypeError("exact string required")
    reject_unsafe_text(value, "schedule artifact text")
    value.encode("utf-8", errors="strict")
    if not unicodedata.is_normalized("NFC", value):
        raise ValueError("schedule artifact text must already be NFC")


def _json_value(value: object, active: set[int]) -> None:
    cls = type(value)
    if value is None or cls is bool or cls is int:
        return
    if cls is str:
        _text(value)
        return
    if cls is not list and cls is not dict:
        raise TypeError("unsupported canonical JSON value")
    key = id(value)
    if key in active:
        raise ValueError("cyclic canonical JSON value")
    active.add(key)
    try:
        if cls is dict:
            for name, member in value.items():
                _text(name)
                _json_value(member, active)
        else:
            for member in value:
                _json_value(member, active)
    finally:
        active.remove(key)


def _canonical_json(value: object) -> bytes:
    """Encode C(value), rejecting coercion, unsafe text and normalization."""
    _json_value(value, set())
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate canonical JSON key")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise ValueError("floating-point and non-standard JSON numbers are forbidden")


def _parse_canonical_json(data: bytes) -> object:
    """Accept only the unique C(value) bytes; schema validation is separate."""
    if type(data) is not bytes:
        raise TypeError("exact JSON bytes required")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("JSON BOM is forbidden")
    value = json.loads(data.decode("utf-8", errors="strict"),
                       object_pairs_hook=_pairs, parse_float=_reject_number,
                       parse_constant=_reject_number)
    if _canonical_json(value) != data:
        raise ValueError("noncanonical JSON bytes")
    return value


def _encode_base64(data: bytes) -> str:
    if type(data) is not bytes:
        raise TypeError("exact base64 input bytes required")
    return base64.b64encode(data).decode("ascii")


def _decode_base64(text: str) -> bytes:
    if type(text) is not str:
        raise TypeError("exact base64 text required")
    data = base64.b64decode(text.encode("ascii", errors="strict"), validate=True)
    if _encode_base64(data) != text:
        raise ValueError("noncanonical base64 text")
    return data
