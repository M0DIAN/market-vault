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
  Canonical build IDs, the assembler version, and the version-ID version.
  Changing any actual row version, ``dataset_as_of``, or build pin changes
  the version ID.

Both use the existing versioned canonical identity encoding of the PR-12
manifest core (:mod:`market_vault.dataset.encoding`); Python's builtin
``hash()``, ``repr()``, locale formatting, insertion order, and filesystem
paths are never used. Equivalent logical inputs in any input order or
timezone representation produce the same IDs.
"""

from __future__ import annotations

from .encoding import DatasetError, encode_identity, normalize_utc_datetime
from .pit_models import (
    PIT_ASSEMBLER_VERSION,
    PIT_SAMPLE_KEY_VERSION,
    PIT_SAMPLE_VERSION_ID_VERSION,
    PITAssemblyError,
    PITSampleRequest,
)

__all__ = [
    "pit_sample_key",
    "pit_sample_version_id",
]

_SAMPLE_KEY_PREFIX = "pit-sample-key"
_SAMPLE_VERSION_ID_PREFIX = "pit-sample-version-id"


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


def pit_sample_version_id(
    *,
    sample_key: str,
    dataset_as_of,
    feature_canonical_row_version_ids,
    label_canonical_row_version_ids,
    considered_canonical_build_ids,
    assembler_version: str = PIT_ASSEMBLER_VERSION,
) -> str:
    """Physical binding identity of one assembled sample.

    Feature and label row-version IDs keep their deterministic position
    order; considered build IDs are sorted, so the same logical inputs in
    any input order produce the same ID while any actual row version,
    ``dataset_as_of``, or build pin change changes the ID.
    """
    if not isinstance(sample_key, str) or not sample_key:
        raise PITAssemblyError("sample_key must be a non-empty string")
    if dataset_as_of is not None:
        try:
            dataset_as_of = normalize_utc_datetime(dataset_as_of, "dataset_as_of")
        except DatasetError as exc:
            raise PITAssemblyError(str(exc)) from exc
    feature_versions = tuple(feature_canonical_row_version_ids)
    label_versions = tuple(label_canonical_row_version_ids)
    considered = tuple(sorted(set(considered_canonical_build_ids)))
    return encode_identity(
        _SAMPLE_VERSION_ID_PREFIX,
        {
            "version": PIT_SAMPLE_VERSION_ID_VERSION,
            "sample_key": sample_key,
            "dataset_as_of": dataset_as_of,
            "feature_row_versions": "\x1e".join(feature_versions),
            "label_row_versions": "\x1e".join(label_versions),
            "considered_build_ids": "\x1e".join(considered),
            "assembler_version": assembler_version,
        },
    )
