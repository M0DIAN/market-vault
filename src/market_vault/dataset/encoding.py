"""Versioned canonical scalar encoding for derived-dataset identities.

Every derived identity (``dataset_schema_id``, ``logical_dataset_content_id``,
``dataset_id``) is a versioned SHA-256 over this one private canonical
serialization:

- UTF-8 with NFC-normalized strings;
- sorted object keys (insertion order never matters);
- compact separators with an explicit tagged representation per scalar;
- floats encoded as explicit IEEE-754 binary64 big-endian hex
  (``struct.pack(">d", value).hex()``), never ``repr()`` or locale-dependent
  display formatting;
- timestamps converted to UTC and truncated to microseconds;
- dates encoded as ISO date;
- integers and booleans stay distinct;
- null has an explicit representation;
- ``allow_nan=False``: float NaN and positive/negative infinity are rejected
  and negative zero is normalized to ordinary zero.

Python's process-randomized builtin ``hash()``, dict insertion order, local
timezones, locale, platform path formatting, pandas display formatting, and
PyArrow serializer metadata are never used. All strings reaching this
serializer must first pass :func:`reject_unsafe_text` (enforced by the model
and content validators), so control characters and reserved encoding
separators cannot corrupt the payload.
"""

from __future__ import annotations

import hashlib
import math
import struct
import unicodedata
from datetime import date, datetime, timezone
from typing import Mapping

import pandas as pd

#: Explicit identity encoding version; bumping it changes every derived
#: Dataset identity (schema ID, content ID, dataset ID).
DATASET_IDENTITY_ENCODING_VERSION = "v1"

#: Separators reserved by the versioned serializer (mirrors the Canonical
#: layer's reserved set).
_RESERVED_SEPARATORS = ("\x1e", "\x1f", "|")


class DatasetError(ValueError):
    """Structured validation failure of the derived-dataset layer (fail-closed)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def reject_unsafe_text(value: str, label: str) -> None:
    """Fail on full Unicode Cc control characters (U+0000-U+001F, U+007F,
    U+0080-U+009F) and reserved encoding separators."""
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x1F or 0x7F <= codepoint <= 0x9F:
            raise DatasetError(f"control character in {label}: {value!r}")
    for separator in _RESERVED_SEPARATORS:
        if separator in value:
            raise DatasetError(f"encoding separator in {label}: {value!r}")


def normalize_nfc(value: str) -> str:
    """Normalize Unicode consistently to NFC before any identity use."""
    return unicodedata.normalize("NFC", value)


def normalize_utc_datetime(value, label: str) -> datetime:
    """Normalize one timezone-aware instant to UTC, truncated to microseconds.

    Naive timestamps fail; sub-microsecond precision is truncated. Two
    representations of the same instant normalize to the same datetime.
    """
    if isinstance(value, pd.Timestamp):
        stamp = value
    elif isinstance(value, datetime):
        stamp = pd.Timestamp(value)
    else:
        raise DatasetError(
            f"{label} must be a timezone-aware datetime, got {type(value).__name__}"
        )
    if stamp.tzinfo is None:
        raise DatasetError(f"{label} must be timezone-aware, got a naive timestamp")
    return stamp.tz_convert("UTC").as_unit("us").to_pydatetime()


def _float_text(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        raise DatasetError(
            f"float NaN and positive/negative infinity are rejected, got {value!r}"
        )
    if value == 0.0:
        value = 0.0  # normalize negative zero to ordinary zero for identity
    # Explicit IEEE-754 binary64 big-endian hex: deterministic across
    # platforms, locales, and Python display formatting. Equal binary64
    # values always encode identically.
    return struct.pack(">d", value).hex()


def _utc_timestamp_text(value) -> str:
    if isinstance(value, pd.Timestamp):
        stamp = value
    else:
        stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise DatasetError(f"naive timestamp cannot be canonically encoded: {value!r}")
    return stamp.tz_convert("UTC").as_unit("us").isoformat()


def encode_scalar(value) -> str:
    """Explicit tagged scalar encoding: ``n``, ``b:``, ``i:``, ``f:``, ``s:``,
    ``d:``, ``t:``. ``None`` is explicit; bool and int are distinct; datetime
    must be timezone-aware (UTC-normalized to microseconds); date and
    datetime are never confused; float NaN/infinity fail, -0.0 normalizes,
    and floats encode as fixed IEEE-754 binary64 hex.
    """
    if value is None:
        return "n"
    if type(value) is bool:
        return "b:true" if value else "b:false"
    if isinstance(value, str):
        return "s:" + normalize_nfc(value)
    if isinstance(value, int):
        return f"i:{value}"
    if isinstance(value, float):
        return "f:" + _float_text(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return "t:" + _utc_timestamp_text(value)
    if isinstance(value, date):
        return "d:" + value.isoformat()
    raise DatasetError(
        f"unsupported scalar type for canonical encoding: {type(value).__name__}"
    )


def _payload(fields: Mapping[str, object]) -> str:
    """Sorted-key payload of tagged scalar values joined by the record
    separator; insertion order never matters."""
    return "\x1f".join(
        f"{key}:{encode_scalar(value)}" for key, value in sorted(fields.items())
    )


def encode_identity(prefix: str, fields: Mapping[str, object]) -> str:
    """Versioned SHA-256 over the canonical serialization of ``fields``.

    SHA-256 is used as a collision-resistant digest; it is not claimed to be
    collision-free. Bumping ``DATASET_IDENTITY_ENCODING_VERSION`` changes every
    digest produced by this function.
    """
    text = f"{DATASET_IDENTITY_ENCODING_VERSION}|{prefix}|{_payload(fields)}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
