"""Point-in-time sample identities.

- ``pit_sample_key``: the stable logical sample definition — code, interval,
  adjustment, requested_session, anchor market-calendar date, feature window
  boundaries, optional label window boundaries, and the sample key version.
  It never contains canonical build paths, manifest paths, ``built_at`` /
  ``created_at``, filesystem metadata, input list order, or any local
  timezone representation.
- ``pit_sample_version_id``: the physical binding of one sample — the sample
  key, the normalized ``dataset_as_of``, the ordered feature and label
  canonical row-version IDs (deterministic position order), the considered
  Canonical build IDs, the association schema contract version, the assembler
  version, and the version-ID version. Changing any actual row version,
  ``dataset_as_of``, build pin, or association schema contract version
  changes the version ID.

Both use the existing versioned canonical identity encoding of the PR-12
manifest core (:mod:`market_vault.dataset.encoding`); Python's builtin
``hash()``, ``repr()``, locale formatting, insertion order, and filesystem
paths are never used. Equivalent logical inputs in any input order or
timezone representation produce the same IDs.

``pit_sample_version_id`` is a public API and fails closed independently: the
sample key, every feature/label row-version ID, and every considered build ID
must be a 64-character lowercase SHA-256 hex string; duplicates inside any
list and the same row version appearing in both feature and label lists
fail; ``assembler_version`` and ``association_schema_version`` must be
non-empty safe strings. Fixed-length hash validation makes the ``\\x1e``
sequence encoding unambiguous.
"""

from __future__ import annotations

import re

from .encoding import DatasetError, encode_identity, normalize_utc_datetime
from .pit_models import (
    PIT_ASSEMBLER_VERSION,
    PIT_ASSOCIATION_SCHEMA_VERSION,
    PIT_SAMPLE_KEY_VERSION,
    PIT_SAMPLE_VERSION_ID_VERSION,
    PITAssemblyError,
    PITSampleRequest,
    _normalize_text,
)

__all__ = [
    "pit_sample_key",
    "pit_sample_version_id",
]

_SAMPLE_KEY_PREFIX = "pit-sample-key"
_SAMPLE_VERSION_ID_PREFIX = "pit-sample-version-id"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def pit_sample_key(request: PITSampleRequest) -> str:
    """Stable logical identity of one sample definition.

    Two equivalent requests (any input construction order, equivalent
    timezone representations of the same instants) produce the same key.
    """
    if not isinstance(request, PITSampleRequest):
        raise PITAssemblyError(
            f"pit_sample_key requires a PITSampleRequest, got {type(request).__name__}"
        )
    return encode_identity(
        _SAMPLE_KEY_PREFIX,
        {
            "version": PIT_SAMPLE_KEY_VERSION,
            "code": request.code,
            "interval": request.interval,
            "adjustment": request.adjustment,
            "requested_session": request.requested_session,
            "anchor_market_calendar_date": request.anchor_market_calendar_date,
            "feature_window_start": request.feature_window.start,
            "feature_window_close": request.feature_window.close,
            "label_window_start": (
                request.label_window.start if request.label_window is not None else None
            ),
            "label_window_close": (
                request.label_window.close if request.label_window is not None else None
            ),
        },
    )


def _require_hash_list(values, label: str) -> list[str]:
    """Strict 64-character lowercase SHA-256 sequence validation.

    Any iterable is accepted, but every value must be a 64-character lowercase
    SHA-256 hex string and the sequence must not contain duplicates; iterable
    and generator failures are converted to :class:`PITAssemblyError`.
    """
    try:
        items = list(values)
    except (TypeError, ValueError) as exc:
        raise PITAssemblyError(
            f"{label} must be an iterable of 64-character SHA-256 hex strings"
        ) from exc
    result = []
    for value in items:
        if not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value):
            raise PITAssemblyError(
                f"{label} contains a value that is not a 64-character lowercase "
                f"SHA-256 hex string: {value!r}"
            )
        result.append(value)
    if len(set(result)) != len(result):
        raise PITAssemblyError(f"{label} contains duplicate IDs")
    return result


def _require_version_text(value, label: str) -> str:
    try:
        return _normalize_text(value, label)
    except PITAssemblyError:
        raise
    except Exception as exc:
        raise PITAssemblyError(f"{label} must be a non-empty safe string") from exc


def pit_sample_version_id(
    *,
    sample_key: str,
    dataset_as_of,
    feature_canonical_row_version_ids,
    label_canonical_row_version_ids,
    considered_canonical_build_ids,
    assembler_version: str = PIT_ASSEMBLER_VERSION,
    association_schema_version: str = PIT_ASSOCIATION_SCHEMA_VERSION,
) -> str:
    """Physical binding identity of one assembled sample.

    Feature and label row-version IDs keep their deterministic position
    order; considered build IDs are sorted, so the same logical inputs in
    any input order produce the same ID while any actual row version,
    ``dataset_as_of``, build pin, or association schema contract version
    change changes the ID. All inputs fail closed independently.
    """
    if not isinstance(sample_key, str) or not _SHA256_HEX_RE.fullmatch(sample_key):
        raise PITAssemblyError(
            "sample_key must be a 64-character lowercase SHA-256 hex string"
        )
    if dataset_as_of is not None:
        try:
            dataset_as_of = normalize_utc_datetime(dataset_as_of, "dataset_as_of")
        except DatasetError as exc:
            raise PITAssemblyError(str(exc)) from exc
    feature_versions = _require_hash_list(
        feature_canonical_row_version_ids, "feature_canonical_row_version_ids"
    )
    label_versions = _require_hash_list(
        label_canonical_row_version_ids, "label_canonical_row_version_ids"
    )
    considered = _require_hash_list(
        considered_canonical_build_ids, "considered_canonical_build_ids"
    )
    overlap = set(feature_versions) & set(label_versions)
    if overlap:
        raise PITAssemblyError(
            f"a canonical row version id appears in both the feature and label "
            f"lists: {sorted(overlap)[0]}"
        )
    considered_sorted = sorted(considered)
    assembler_version = _require_version_text(assembler_version, "assembler_version")
    association_schema_version = _require_version_text(
        association_schema_version, "association_schema_version"
    )
    return encode_identity(
        _SAMPLE_VERSION_ID_PREFIX,
        {
            "version": PIT_SAMPLE_VERSION_ID_VERSION,
            "sample_key": sample_key,
            "dataset_as_of": dataset_as_of,
            "feature_row_versions": "\x1e".join(feature_versions),
            "label_row_versions": "\x1e".join(label_versions),
            "considered_build_ids": "\x1e".join(considered_sorted),
            "association_schema_version": association_schema_version,
            "assembler_version": assembler_version,
        },
    )
