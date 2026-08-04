"""Frozen point-in-time sample assembly models.

Every model is frozen and validates at construction: strings normalize the
same way as :class:`market_vault.dataset.models.DatasetScope` and the
Canonical request (strip, deterministic case, NFC, control characters and
reserved encoding separators rejected), instants must be timezone-aware and
normalize to UTC microseconds, and window ordering constraints are enforced.
No Feature or Label value is computed here and no Canonical file is read.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime, reject_unsafe_text
from .models import CanonicalBuildPin, DatasetSchema, GapReference

__all__ = [
    "PIT_ASSEMBLER_VERSION",
    "PIT_ASSOCIATION_SCHEMA_VERSION",
    "PIT_ROLE_FEATURE",
    "PIT_ROLE_LABEL",
    "PIT_SAMPLE_KEY_VERSION",
    "PIT_SAMPLE_VERSION_ID_VERSION",
    "PITAssemblyDiagnostics",
    "PITAssemblyError",
    "PITAssemblyResult",
    "PITDiagnostics",
    "PITObservationWindow",
    "PITSample",
    "PITSampleRequest",
]

#: Explicit version constants; changing one changes the identities that
#: reference it. The association schema and content IDs themselves use the
#: existing PR-12 ``dataset_schema_id`` / ``logical_dataset_content_id``
#: encodings; these constants identify the association contract and
#: participate in the sample identities.
PIT_ASSEMBLER_VERSION = "market-vault-pit-assembler-v1"
PIT_SAMPLE_KEY_VERSION = "pit-sample-key-v1"
PIT_SAMPLE_VERSION_ID_VERSION = "pit-sample-version-id-v1"
PIT_ASSOCIATION_SCHEMA_VERSION = "pit-association-schema-v1"

#: Association role values.
PIT_ROLE_FEATURE = "FEATURE"
PIT_ROLE_LABEL = "LABEL"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class PITAssemblyError(ValueError):
    """Structured fail-closed failure of the point-in-time assembly layer.

    Raised for invalid requests, invalid assembly inputs, conflicting or
    uncovered canonical rows, and cross-day label violations. Low-level
    exceptions from the identity layer are always converted to this error.
    """


def _normalize_text(value, label: str, *, upper: bool = False, lower: bool = False) -> str:
    if not isinstance(value, str):
        raise PITAssemblyError(f"{label} must be a string, got {type(value).__name__}")
    text = unicodedata.normalize("NFC", value).strip()
    if upper:
        text = text.upper()
    if lower:
        text = text.lower()
    if not text:
        raise PITAssemblyError(f"{label} must not be empty")
    try:
        reject_unsafe_text(text, label)
    except DatasetError as exc:
        raise PITAssemblyError(str(exc)) from exc
    return text


def _normalize_instant(value, label: str) -> datetime:
    try:
        return normalize_utc_datetime(value, label)
    except DatasetError as exc:
        raise PITAssemblyError(str(exc)) from exc


def _normalize_date(value, label: str = "date") -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise PITAssemblyError(f"invalid {label}: {value!r}") from exc
    raise PITAssemblyError(f"invalid {label}: {value!r}")


def _require_sha256(value, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value):
        raise PITAssemblyError(f"{label} must be a 64-character SHA-256 hex string, got {value!r}")
    return value.lower()


def _require_non_negative_int(value, label: str) -> None:
    if type(value) is not int or value < 0:
        raise PITAssemblyError(f"{label} must be a non-negative integer")


@dataclass(frozen=True)
class PITObservationWindow:
    """One half-open observation window ``[start, close)``.

    Both boundaries must be timezone-aware; they are normalized to UTC
    microseconds, so equivalent representations of the same instants compare
    and hash identically. Naive timestamps fail closed.
    """

    start: datetime
    close: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _normalize_instant(self.start, "window start"))
        object.__setattr__(self, "close", _normalize_instant(self.close, "window close"))
        if self.start >= self.close:
            raise PITAssemblyError(
                "observation window start must be strictly before its close"
            )


@dataclass(frozen=True)
class PITSampleRequest:
    """One logical point-in-time sample definition.

    ``code`` normalizes strip + uppercase, ``interval`` strip + lowercase,
    ``adjustment`` and ``requested_session`` strip + uppercase; empty strings
    and control characters fail. ``anchor_market_calendar_date`` is the
    market-calendar date the sample is anchored to. The feature window is a
    half-open observation window; the label window is either absent or
    complete, must not start before the feature window close, and may look
    past it (label rows are future observations and never enter the feature
    row set).

    This PR's default policy allows ``adjustment == "NONE"`` only: the
    corporate-action as-of policy for adjusted prices is not implemented yet,
    and there is deliberately no temporary override.
    """

    code: str
    interval: str
    adjustment: str
    requested_session: str
    anchor_market_calendar_date: date
    feature_window_start: datetime
    feature_window_close: datetime
    label_window_start: datetime | None = None
    label_window_close: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _normalize_text(self.code, "code", upper=True))
        object.__setattr__(self, "interval", _normalize_text(self.interval, "interval", lower=True))
        object.__setattr__(self, "adjustment", _normalize_text(self.adjustment, "adjustment", upper=True))
        object.__setattr__(
            self,
            "requested_session",
            _normalize_text(self.requested_session, "requested_session", upper=True),
        )
        if self.adjustment != "NONE":
            raise PITAssemblyError(
                "adjusted-price as-of policy is not implemented; adjustment must be NONE"
            )
        object.__setattr__(
            self,
            "anchor_market_calendar_date",
            _normalize_date(self.anchor_market_calendar_date, "anchor_market_calendar_date"),
        )
        feature = PITObservationWindow(self.feature_window_start, self.feature_window_close)
        object.__setattr__(self, "feature_window_start", feature.start)
        object.__setattr__(self, "feature_window_close", feature.close)
        object.__setattr__(self, "feature_window", feature)
        if (self.label_window_start is None) != (self.label_window_close is None):
            raise PITAssemblyError(
                "label window must have both boundaries or neither"
            )
        if self.label_window_start is not None:
            label = PITObservationWindow(self.label_window_start, self.label_window_close)
            if label.start < feature.close:
                raise PITAssemblyError(
                    "label_window_start must be >= feature_window_close"
                )
            object.__setattr__(self, "label_window_start", label.start)
            object.__setattr__(self, "label_window_close", label.close)
            object.__setattr__(self, "label_window", label)
        else:
            object.__setattr__(self, "label_window", None)


@dataclass(frozen=True)
class PITDiagnostics:
    """Deterministic per-sample assembly counts (no free text).

    Candidate counts cover only rows that already match the requested
    code/interval/adjustment/requested_session and the corresponding event
    window; wrong-symbol or unrelated rows are never counted. Market-clock
    exclusions are counted before archive-clock exclusions, so
    ``<role>_candidate_count == <role>_selected_count +
    <role>_market_future_excluded_count + <role>_archive_future_excluded_count``.
    Known gap IDs are the sorted, deduplicated internal gap ranges that
    overlap the window; their absence never implies a complete session.
    """

    feature_candidate_count: int
    feature_selected_count: int
    feature_market_future_excluded_count: int
    feature_archive_future_excluded_count: int
    label_candidate_count: int
    label_selected_count: int
    label_market_future_excluded_count: int
    label_archive_future_excluded_count: int
    known_feature_gap_ids: tuple[str, ...]
    known_label_gap_ids: tuple[str, ...]
    empty_observation_window: bool

    def __post_init__(self) -> None:
        for name in (
            "feature_candidate_count",
            "feature_selected_count",
            "feature_market_future_excluded_count",
            "feature_archive_future_excluded_count",
            "label_candidate_count",
            "label_selected_count",
            "label_market_future_excluded_count",
            "label_archive_future_excluded_count",
        ):
            _require_non_negative_int(getattr(self, name), name)
        feature_invariant = (
            self.feature_candidate_count
            == self.feature_selected_count
            + self.feature_market_future_excluded_count
            + self.feature_archive_future_excluded_count
        )
        if not feature_invariant:
            raise PITAssemblyError(
                "feature diagnostic counts do not satisfy the candidate invariant"
            )
        label_invariant = (
            self.label_candidate_count
            == self.label_selected_count
            + self.label_market_future_excluded_count
            + self.label_archive_future_excluded_count
        )
        if not label_invariant:
            raise PITAssemblyError(
                "label diagnostic counts do not satisfy the candidate invariant"
            )
        known_feature_gap_ids = tuple(
            sorted({_require_sha256(value, "known feature gap id") for value in self.known_feature_gap_ids})
        )
        known_label_gap_ids = tuple(
            sorted({_require_sha256(value, "known label gap id") for value in self.known_label_gap_ids})
        )
        object.__setattr__(self, "known_feature_gap_ids", known_feature_gap_ids)
        object.__setattr__(self, "known_label_gap_ids", known_label_gap_ids)
        if type(self.empty_observation_window) is not bool:
            raise PITAssemblyError("empty_observation_window must be a real bool")


@dataclass(frozen=True)
class PITSample:
    """One assembled sample: stable logical definition plus physical binding.

    ``sample_key`` is the stable logical sample definition (no provenance);
    ``sample_version_id`` binds it to the normalized ``dataset_as_of``, the
    ordered feature/label canonical row-version IDs, and the considered
    Canonical build IDs under the current assembler version. Feature and
    label row-version IDs are in deterministic position order. This PR never
    claims a label horizon is COMPLETE: only observed rows, known gaps, and
    clock-exclusion counts are recorded.
    """

    sample_key: str
    sample_version_id: str
    request: PITSampleRequest
    dataset_as_of: datetime | None
    feature_canonical_row_version_ids: tuple[str, ...]
    label_canonical_row_version_ids: tuple[str, ...]
    considered_canonical_build_ids: tuple[str, ...]
    diagnostics: PITDiagnostics

    def __post_init__(self) -> None:
        if not isinstance(self.sample_key, str) or not self.sample_key:
            raise PITAssemblyError("sample_key must be a non-empty string")
        if not isinstance(self.sample_version_id, str) or not self.sample_version_id:
            raise PITAssemblyError("sample_version_id must be a non-empty string")
        if not isinstance(self.request, PITSampleRequest):
            raise PITAssemblyError(
                f"request must be a PITSampleRequest, got {type(self.request).__name__}"
            )
        if self.dataset_as_of is not None:
            object.__setattr__(
                self, "dataset_as_of", _normalize_instant(self.dataset_as_of, "dataset_as_of")
            )
        feature_versions = tuple(
            _require_sha256(value, "feature canonical row version id")
            for value in self.feature_canonical_row_version_ids
        )
        if len(set(feature_versions)) != len(feature_versions):
            raise PITAssemblyError("feature canonical row version IDs must be unique")
        label_versions = tuple(
            _require_sha256(value, "label canonical row version id")
            for value in self.label_canonical_row_version_ids
        )
        if len(set(label_versions)) != len(label_versions):
            raise PITAssemblyError("label canonical row version IDs must be unique")
        considered_build_ids = tuple(
            _require_sha256(value, "considered canonical build id")
            for value in self.considered_canonical_build_ids
        )
        if len(set(considered_build_ids)) != len(considered_build_ids):
            raise PITAssemblyError("considered canonical build IDs must be unique")
        object.__setattr__(self, "feature_canonical_row_version_ids", feature_versions)
        object.__setattr__(self, "label_canonical_row_version_ids", label_versions)
        object.__setattr__(self, "considered_canonical_build_ids", considered_build_ids)
        if not isinstance(self.diagnostics, PITDiagnostics):
            raise PITAssemblyError(
                f"diagnostics must be a PITDiagnostics, got {type(self.diagnostics).__name__}"
            )


@dataclass(frozen=True)
class PITAssemblyDiagnostics:
    """Deterministic result-level assembly counts."""

    sample_count: int
    total_feature_rows: int
    total_label_rows: int
    feature_market_future_excluded_count: int
    feature_archive_future_excluded_count: int
    label_market_future_excluded_count: int
    label_archive_future_excluded_count: int
    considered_canonical_build_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "sample_count",
            "total_feature_rows",
            "total_label_rows",
            "feature_market_future_excluded_count",
            "feature_archive_future_excluded_count",
            "label_market_future_excluded_count",
            "label_archive_future_excluded_count",
        ):
            _require_non_negative_int(getattr(self, name), name)
        considered = tuple(
            sorted(
                {
                    _require_sha256(value, "considered canonical build id")
                    for value in self.considered_canonical_build_ids
                }
            )
        )
        object.__setattr__(self, "considered_canonical_build_ids", considered)


@dataclass(frozen=True)
class PITAssemblyResult:
    """Deterministic output of one point-in-time sample assembly.

    Provides everything a future Dataset builder needs without building the
    final DatasetManifest: canonical build pins, the selected canonical
    row-version IDs, gap references, the fixed association schema, the
    deterministic association rows, the association schema/content IDs, the
    samples, and deterministic diagnostics. The association schema and
    content IDs are recomputed at construction and must match the carried
    rows, so a manually assembled inconsistent result fails closed.
    """

    samples: tuple[PITSample, ...]
    canonical_build_pins: tuple[CanonicalBuildPin, ...]
    canonical_row_version_ids: tuple[str, ...]
    gap_references: tuple[GapReference, ...]
    association_schema: DatasetSchema
    association_rows: tuple[dict, ...]
    association_schema_id: str
    association_content_id: str
    diagnostics: PITAssemblyDiagnostics

    def __post_init__(self) -> None:
        samples = tuple(self.samples)
        for sample in samples:
            if not isinstance(sample, PITSample):
                raise PITAssemblyError(
                    f"samples must contain PITSample instances, got {type(sample).__name__}"
                )
        pins = tuple(self.canonical_build_pins)
        for pin in pins:
            if not isinstance(pin, CanonicalBuildPin):
                raise PITAssemblyError(
                    f"canonical_build_pins must contain CanonicalBuildPin instances, "
                    f"got {type(pin).__name__}"
                )
        gap_references = tuple(self.gap_references)
        for ref in gap_references:
            if not isinstance(ref, GapReference):
                raise PITAssemblyError(
                    f"gap_references must contain GapReference instances, "
                    f"got {type(ref).__name__}"
                )
        if not isinstance(self.association_schema, DatasetSchema):
            raise PITAssemblyError(
                f"association_schema must be a DatasetSchema, "
                f"got {type(self.association_schema).__name__}"
            )
        if self.association_schema_id != dataset_schema_id(self.association_schema):
            raise PITAssemblyError(
                "association_schema_id does not match the carried association schema"
            )
        if self.association_content_id != logical_dataset_content_id(
            self.association_schema, self.association_rows
        ):
            raise PITAssemblyError(
                "association_content_id does not match the carried association rows"
            )
        if not isinstance(self.diagnostics, PITAssemblyDiagnostics):
            raise PITAssemblyError(
                f"diagnostics must be a PITAssemblyDiagnostics, "
                f"got {type(self.diagnostics).__name__}"
            )
