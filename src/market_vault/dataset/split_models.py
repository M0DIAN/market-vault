"""Frozen typed models and deterministic identities of the chronological
split and actual-label-end purge foundation (v0.4.0 PR-8).

Every model is frozen, validates at construction, and normalizes
deterministically at construction (UTC microsecond instants, NFC text, strict
64-character lowercase SHA-256 sample identities), so the assignment layer and
the identity layer can trust their inputs. All failures raise the unified
:class:`SplitValidationError` (a subclass of :class:`DatasetError`); unknown,
future, or old schema versions fail closed and are never "best-effort"
interpreted.

This module defines the frozen contract models and the deterministic
identities of the split layer:

- ``chronological_split_spec_content_id`` / ``chronological_split_spec_pin``:
  the versioned semantic content identity of a :class:`ChronologicalSplitSpec`
  and its conversion to the existing :class:`SpecPin` (kind SPLIT);
- ``split_assignment_schema`` / ``split_assignment_schema_id`` /
  ``split_assignment_content_id``: the fixed logical assignment schema and
  its existing PR-12 ``dataset_schema_id`` / ``logical_dataset_content_id``
  identities;
- ``chronological_split_result_id``: the versioned identity of one complete
  split result, binding the splitter version, the assignment schema contract
  version, the split spec content ID, the assignment schema and content IDs,
  and the sample count.

No Feature or Label value is computed here, no LabelSpec horizon is ever read,
no sample is assembled, no PIT behavior is touched, and nothing accesses the
filesystem, OpenD, or the network. ``actual_label_end_time`` is the only purge
time fact; nominal horizons are never used for purging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import (
    DatasetError,
    encode_identity,
    normalize_nfc,
    normalize_utc_datetime,
    reject_unsafe_text,
)
from .models import SPEC_KIND_SPLIT, DatasetField, DatasetSchema, SpecPin

__all__ = [
    "CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION",
    "CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION",
    "CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION",
    "CHRONOLOGICAL_SPLITTER_VERSION",
    "LABEL_STATUS_COMPLETE",
    "LABEL_STATUS_INCOMPLETE",
    "REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY",
    "REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY",
    "REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END",
    "REASON_CODE_INCOMPLETE_LABEL",
    "SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE",
    "SPLIT_ASSIGNMENT_SCHEMA_VERSION",
    "SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE",
    "SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE",
    "SPLIT_PURGE_RULE_ACTUAL_LABEL_END",
    "SPLIT_STATUS_ASSIGNED",
    "SPLIT_STATUS_EXCLUDED",
    "SPLIT_STATUS_PURGED",
    "SPLIT_TEST",
    "SPLIT_TRAIN",
    "SPLIT_VALIDATION",
    "ChronologicalSplitAssignment",
    "ChronologicalSplitDiagnostics",
    "ChronologicalSplitResult",
    "ChronologicalSplitSample",
    "ChronologicalSplitSpec",
    "SplitValidationError",
    "chronological_split_result_id",
    "chronological_split_spec_content_id",
    "chronological_split_spec_pin",
    "split_assignment_content_id",
    "split_assignment_schema",
    "split_assignment_schema_id",
]

# ---------------------------------------------------------------------------
# Version constants (explicit; every one enters the identities that use it).
# ---------------------------------------------------------------------------

#: Version of the ChronologicalSplitSpec schema accepted by the v1 layer.
CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION = "market-vault-chronological-split-spec-v1"

#: Version of the deterministic semantic content identity of a split spec.
CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION = (
    "market-vault-chronological-split-spec-content-v1"
)

#: Version of the deterministic chronological splitter implementation.
CHRONOLOGICAL_SPLITTER_VERSION = "market-vault-chronological-splitter-v1"

#: Version of the fixed split-assignment logical schema contract.
SPLIT_ASSIGNMENT_SCHEMA_VERSION = "market-vault-split-assignment-schema-v1"

#: Version of the deterministic split result identity.
CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION = (
    "market-vault-chronological-split-result-id-v1"
)

# ---------------------------------------------------------------------------
# Stable machine values (never free-form text).
# ---------------------------------------------------------------------------

#: Nominal split values.
SPLIT_TRAIN = "TRAIN"
SPLIT_VALIDATION = "VALIDATION"
SPLIT_TEST = "TEST"

#: Explicit caller-provided label status values.
LABEL_STATUS_COMPLETE = "COMPLETE"
LABEL_STATUS_INCOMPLETE = "INCOMPLETE"

#: Assignment status values.
SPLIT_STATUS_ASSIGNED = "ASSIGNED"
SPLIT_STATUS_PURGED = "PURGED"
SPLIT_STATUS_EXCLUDED = "EXCLUDED"

#: v1 fixed rule values.
SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE = "FEATURE_WINDOW_CLOSE_DATE"
SPLIT_PURGE_RULE_ACTUAL_LABEL_END = "ACTUAL_LABEL_END"
SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE = "EXCLUDE"
SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE = "EXCLUDE"

#: Stable reason codes (machine codes, never free-form error stacks).
REASON_CODE_INCOMPLETE_LABEL = "INCOMPLETE_LABEL"
REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END = "FEATURE_CLOSE_AFTER_TEST_END"
REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY = (
    "ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY"
)
REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY = (
    "ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY"
)

_NOMINAL_SPLITS = (SPLIT_TRAIN, SPLIT_VALIDATION, SPLIT_TEST)
_REASON_CODES = (
    REASON_CODE_INCOMPLETE_LABEL,
    REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY,
    REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY,
)

# ---------------------------------------------------------------------------
# Validation helpers (every failure surfaces as SplitValidationError).
# ---------------------------------------------------------------------------

_SHA256_LOWER_RE = re.compile(r"^[0-9a-f]{64}$")
_SPEC_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SPEC_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SplitValidationError(DatasetError):
    """Structured fail-closed failure of the chronological split layer.

    Raised for invalid split specs, invalid sample facts, inconsistent
    assignments, and any identity mismatch of a manually constructed or
    ``dataclasses.replace``-modified result. Low-level ``ZoneInfoNotFoundError``,
    ``TypeError``, ``ValueError``, and ``KeyError`` exceptions are always
    converted to this error and never leak.
    """


def _reject_unsafe_split_text(value: str, label: str) -> None:
    try:
        reject_unsafe_text(value, label)
    except DatasetError as exc:
        raise SplitValidationError(str(exc)) from exc


def _require_spec_name(value) -> str:
    """lower_snake_case split spec name; identity-bearing, never silently
    changed."""
    if not isinstance(value, str):
        raise SplitValidationError(
            f"spec name must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _SPEC_NAME_RE.fullmatch(text):
        raise SplitValidationError(
            f"spec name must match ^[a-z][a-z0-9_]*$: {value!r}"
        )
    return text


def _require_spec_version(value) -> str:
    """``vN`` spec version; identity-bearing, never silently changed."""
    if not isinstance(value, str):
        raise SplitValidationError(
            f"spec version must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not _SPEC_VERSION_RE.fullmatch(text):
        raise SplitValidationError(
            f"spec version must match ^v[1-9][0-9]*$: {value!r}"
        )
    return text


def _require_version_text(value, label: str) -> str:
    """Non-empty safe version string without leading/trailing whitespace."""
    if not isinstance(value, str):
        raise SplitValidationError(
            f"{label} must be a non-empty safe string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not text or text != text.strip():
        raise SplitValidationError(
            f"{label} must be a non-empty safe string without leading or "
            "trailing whitespace"
        )
    _reject_unsafe_split_text(text, label)
    return text


def _require_boundary_timezone(value) -> str:
    """Explicit IANA timezone name; must be loadable by ``zoneinfo.ZoneInfo``.

    There is no system-local-timezone fallback and no implicit naive
    interpretation: the raw explicit timezone name (NFC-normalized, stripped)
    is what enters the identity.
    """
    if not isinstance(value, str):
        raise SplitValidationError(
            f"boundary_timezone must be a string, got {type(value).__name__}"
        )
    text = normalize_nfc(value)
    if not text or text != text.strip():
        raise SplitValidationError(
            "boundary_timezone must be a non-empty safe string without leading "
            "or trailing whitespace"
        )
    _reject_unsafe_split_text(text, "boundary_timezone")
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SplitValidationError(
            f"unknown boundary_timezone {text!r}; no system-local-timezone "
            "fallback is applied"
        ) from exc
    return text


def _require_split_date(value, label: str) -> date:
    """``datetime.date`` or strict ISO ``YYYY-MM-DD`` string.

    ``datetime`` is explicitly rejected: it is never silently truncated to
    its date. Strict ISO means exactly ``YYYY-MM-DD``; basic-format ISO forms
    such as ``YYYYMMDD`` are rejected.
    """
    if isinstance(value, datetime):
        raise SplitValidationError(
            f"{label} must be a date or strict ISO YYYY-MM-DD string; "
            "datetime is rejected and never silently converted to its date"
        )
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = normalize_nfc(value).strip()
        if not _ISO_DATE_RE.fullmatch(text):
            raise SplitValidationError(
                f"invalid {label}: {value!r}; strict ISO YYYY-MM-DD required"
            )
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise SplitValidationError(f"invalid {label}: {value!r}") from exc
    raise SplitValidationError(f"invalid {label}: {value!r}")


def _require_lower_sha256(value, label: str) -> str:
    """Strict 64-character lowercase SHA-256 hex.

    Uppercase hex is rejected, never silently lowercased: sample identities
    are fixed-length lowercase-hash contracts.
    """
    if not isinstance(value, str) or not _SHA256_LOWER_RE.fullmatch(value):
        raise SplitValidationError(
            f"{label} must be a 64-character lowercase SHA-256 hex string, "
            f"got {value!r}"
        )
    return value


def _normalize_instant(value, label: str) -> datetime:
    """Timezone-aware instant normalized to UTC microseconds; naive fails."""
    try:
        return normalize_utc_datetime(value, label)
    except DatasetError as exc:
        raise SplitValidationError(str(exc)) from exc


def _require_fixed_rule(value, allowed: tuple[str, ...], label: str) -> str:
    """v1 accepts exactly the declared fixed rule values; fail closed."""
    if value not in allowed:
        raise SplitValidationError(
            f"{label} must be one of {', '.join(allowed)}, got {value!r}"
        )
    return value


def _next_local_midnight_utc(end_date: date, boundary_timezone: str) -> datetime:
    """Exclusive split boundary: the UTC instant of local midnight on the day
    after ``end_date`` in ``boundary_timezone``.

    The next calendar date is constructed first and then its local midnight
    is converted to UTC, never a fixed ``timedelta(hours=24)``: a DST day is
    not 24 hours, and the local calendar date is the contract. For
    fold-ambiguous midnights the first (fold=0) occurrence is used
    deterministically.
    """
    tz = ZoneInfo(boundary_timezone)
    next_day = end_date + timedelta(days=1)
    local_midnight = datetime(
        next_day.year, next_day.month, next_day.day, tzinfo=tz
    )
    return local_midnight.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Models.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChronologicalSplitSpec:
    """Frozen chronological split definition (v1).

    ``kind`` is fixed to SPLIT and is not constructible or forgeable.
    Boundaries are dates with ``train_end_date < validation_end_date <
    test_end_date``. Nominal assignment is decided by the local-market date of
    the feature window close in the explicitly declared ``boundary_timezone``;
    purge is decided exclusively by the caller-provided
    ``actual_label_end_time`` (never by a nominal horizon). Every field enters
    the content identity; there are no hidden defaults.
    """

    spec_schema_version: str
    name: str
    version: str
    boundary_timezone: str
    train_end_date: date
    validation_end_date: date
    test_end_date: date
    assignment_rule: str
    purge_rule: str
    incomplete_label_policy: str
    out_of_range_policy: str
    kind: str = field(default=SPEC_KIND_SPLIT, init=False)

    def __post_init__(self) -> None:
        if self.kind != SPEC_KIND_SPLIT:
            raise SplitValidationError(
                f"split spec kind is fixed to {SPEC_KIND_SPLIT} and cannot be forged"
            )
        if self.spec_schema_version != CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION:
            raise SplitValidationError(
                f"unsupported split spec schema version {self.spec_schema_version!r}; "
                f"only {CHRONOLOGICAL_SPLIT_SPEC_SCHEMA_VERSION} is accepted"
            )
        name = _require_spec_name(self.name)
        version = _require_spec_version(self.version)
        boundary_timezone = _require_boundary_timezone(self.boundary_timezone)
        train_end_date = _require_split_date(self.train_end_date, "train_end_date")
        validation_end_date = _require_split_date(
            self.validation_end_date, "validation_end_date"
        )
        test_end_date = _require_split_date(self.test_end_date, "test_end_date")
        if not (train_end_date < validation_end_date < test_end_date):
            raise SplitValidationError(
                "split boundaries must satisfy train_end_date < "
                "validation_end_date < test_end_date, got "
                f"{train_end_date.isoformat()} < {validation_end_date.isoformat()} "
                f"< {test_end_date.isoformat()}"
            )
        assignment_rule = _require_fixed_rule(
            self.assignment_rule,
            (SPLIT_ASSIGNMENT_RULE_FEATURE_WINDOW_CLOSE_DATE,),
            "assignment_rule",
        )
        purge_rule = _require_fixed_rule(
            self.purge_rule, (SPLIT_PURGE_RULE_ACTUAL_LABEL_END,), "purge_rule"
        )
        incomplete_label_policy = _require_fixed_rule(
            self.incomplete_label_policy,
            (SPLIT_INCOMPLETE_LABEL_POLICY_EXCLUDE,),
            "incomplete_label_policy",
        )
        out_of_range_policy = _require_fixed_rule(
            self.out_of_range_policy,
            (SPLIT_OUT_OF_RANGE_POLICY_EXCLUDE,),
            "out_of_range_policy",
        )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "boundary_timezone", boundary_timezone)
        object.__setattr__(self, "train_end_date", train_end_date)
        object.__setattr__(self, "validation_end_date", validation_end_date)
        object.__setattr__(self, "test_end_date", test_end_date)
        object.__setattr__(self, "assignment_rule", assignment_rule)
        object.__setattr__(self, "purge_rule", purge_rule)
        object.__setattr__(self, "incomplete_label_policy", incomplete_label_policy)
        object.__setattr__(self, "out_of_range_policy", out_of_range_policy)


@dataclass(frozen=True)
class ChronologicalSplitSample:
    """One split input fact: the sample identities, the feature window close,
    the explicit caller-provided label status, and the actual label end.

    ``label_status`` is never inferred from PIT rows: the caller explicitly
    declares COMPLETE or INCOMPLETE. ``actual_label_end_time`` is the only
    purge time fact; there is no nominal horizon and no fixed purge length in
    this model.
    """

    sample_key: str
    sample_version_id: str
    feature_window_close: datetime
    label_status: str
    actual_label_end_time: datetime | None

    def __post_init__(self) -> None:
        sample_key = _require_lower_sha256(self.sample_key, "sample_key")
        sample_version_id = _require_lower_sha256(
            self.sample_version_id, "sample_version_id"
        )
        feature_window_close = _normalize_instant(
            self.feature_window_close, "feature_window_close"
        )
        if self.label_status not in (LABEL_STATUS_COMPLETE, LABEL_STATUS_INCOMPLETE):
            raise SplitValidationError(
                f"label_status must be COMPLETE or INCOMPLETE, got {self.label_status!r}"
            )
        actual_label_end_time = self.actual_label_end_time
        if actual_label_end_time is not None:
            actual_label_end_time = _normalize_instant(
                actual_label_end_time, "actual_label_end_time"
            )
            if actual_label_end_time < feature_window_close:
                raise SplitValidationError(
                    "actual_label_end_time must not be before feature_window_close"
                )
        if self.label_status == LABEL_STATUS_COMPLETE and actual_label_end_time is None:
            raise SplitValidationError(
                "a COMPLETE label requires actual_label_end_time"
            )
        object.__setattr__(self, "sample_key", sample_key)
        object.__setattr__(self, "sample_version_id", sample_version_id)
        object.__setattr__(self, "feature_window_close", feature_window_close)
        object.__setattr__(self, "actual_label_end_time", actual_label_end_time)


@dataclass(frozen=True)
class ChronologicalSplitAssignment:
    """One deterministic split assignment row.

    ``feature_window_close_date`` is the local-market date of the feature
    window close under the spec's declared boundary timezone. The status
    combinations are strictly enforced so that a manually constructed or
    ``dataclasses.replace``-modified inconsistent assignment fails closed:

    - ASSIGNED: ``final_split == nominal_split`` (never None), no reason, no
      purge boundary, label COMPLETE;
    - PURGED: nominal TRAIN or VALIDATION only, ``final_split`` None, the
      matching actual-label-end crossing reason, a purge boundary, label
      COMPLETE;
    - EXCLUDED: ``final_split`` None, a stable exclusion reason
      (``INCOMPLETE_LABEL`` with a nominal split and an INCOMPLETE label, or
      ``FEATURE_CLOSE_AFTER_TEST_END`` with no nominal split).
    """

    sample_key: str
    sample_version_id: str
    feature_window_close: datetime
    feature_window_close_date: date
    label_status: str
    actual_label_end_time: datetime | None
    nominal_split: str | None
    final_split: str | None
    assignment_status: str
    reason_code: str | None
    purge_boundary: datetime | None

    def __post_init__(self) -> None:
        sample_key = _require_lower_sha256(self.sample_key, "sample_key")
        sample_version_id = _require_lower_sha256(
            self.sample_version_id, "sample_version_id"
        )
        feature_window_close = _normalize_instant(
            self.feature_window_close, "feature_window_close"
        )
        if isinstance(self.feature_window_close_date, datetime):
            raise SplitValidationError(
                "feature_window_close_date must be a date, not a datetime"
            )
        if not isinstance(self.feature_window_close_date, date):
            raise SplitValidationError(
                f"feature_window_close_date must be a date, "
                f"got {type(self.feature_window_close_date).__name__}"
            )
        feature_window_close_date = self.feature_window_close_date
        if self.label_status not in (LABEL_STATUS_COMPLETE, LABEL_STATUS_INCOMPLETE):
            raise SplitValidationError(
                f"label_status must be COMPLETE or INCOMPLETE, got {self.label_status!r}"
            )
        actual_label_end_time = self.actual_label_end_time
        if actual_label_end_time is not None:
            actual_label_end_time = _normalize_instant(
                actual_label_end_time, "actual_label_end_time"
            )
            if actual_label_end_time < feature_window_close:
                raise SplitValidationError(
                    "actual_label_end_time must not be before feature_window_close"
                )
        if self.label_status == LABEL_STATUS_COMPLETE and actual_label_end_time is None:
            raise SplitValidationError(
                "a COMPLETE label requires actual_label_end_time"
            )
        if self.nominal_split not in (None, *(_NOMINAL_SPLITS)):
            raise SplitValidationError(
                f"nominal_split must be TRAIN, VALIDATION, TEST, or None, "
                f"got {self.nominal_split!r}"
            )
        if self.final_split not in (None, *(_NOMINAL_SPLITS)):
            raise SplitValidationError(
                f"final_split must be TRAIN, VALIDATION, TEST, or None, "
                f"got {self.final_split!r}"
            )
        if self.assignment_status not in (
            SPLIT_STATUS_ASSIGNED,
            SPLIT_STATUS_PURGED,
            SPLIT_STATUS_EXCLUDED,
        ):
            raise SplitValidationError(
                f"assignment_status must be ASSIGNED, PURGED, or EXCLUDED, "
                f"got {self.assignment_status!r}"
            )
        reason_code = self.reason_code
        if reason_code is not None and reason_code not in _REASON_CODES:
            raise SplitValidationError(
                f"reason_code must be a stable split reason code, got {reason_code!r}"
            )
        purge_boundary = self.purge_boundary
        if purge_boundary is not None:
            purge_boundary = _normalize_instant(purge_boundary, "purge_boundary")

        # Status consistency: an inconsistent combination must never survive
        # into a result, whether hand-built or produced by dataclasses.replace.
        if self.assignment_status == SPLIT_STATUS_ASSIGNED:
            if (
                self.nominal_split is None
                or self.final_split != self.nominal_split
            ):
                raise SplitValidationError(
                    "an ASSIGNED assignment requires nominal_split and "
                    "final_split == nominal_split"
                )
            if self.label_status != LABEL_STATUS_COMPLETE:
                raise SplitValidationError(
                    "an ASSIGNED assignment requires a COMPLETE label under "
                    "the v1 EXCLUDE incomplete-label policy"
                )
            if reason_code is not None or purge_boundary is not None:
                raise SplitValidationError(
                    "an ASSIGNED assignment must have reason_code None and "
                    "purge_boundary None"
                )
        elif self.assignment_status == SPLIT_STATUS_PURGED:
            if self.nominal_split not in (SPLIT_TRAIN, SPLIT_VALIDATION):
                raise SplitValidationError(
                    "a PURGED assignment requires a TRAIN or VALIDATION "
                    "nominal split (TEST has no fourth split to purge into)"
                )
            if self.final_split is not None:
                raise SplitValidationError(
                    "a PURGED assignment requires final_split None"
                )
            if self.label_status != LABEL_STATUS_COMPLETE or actual_label_end_time is None:
                raise SplitValidationError(
                    "a PURGED assignment requires a COMPLETE label with an "
                    "actual_label_end_time"
                )
            if self.nominal_split == SPLIT_TRAIN:
                expected_reason = REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
            else:
                expected_reason = REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
            if reason_code != expected_reason:
                raise SplitValidationError(
                    f"a PURGED {self.nominal_split} assignment requires reason_code "
                    f"{expected_reason}, got {reason_code!r}"
                )
            if purge_boundary is None:
                raise SplitValidationError(
                    "a PURGED assignment requires a purge_boundary"
                )
        else:  # EXCLUDED
            if self.final_split is not None:
                raise SplitValidationError(
                    "an EXCLUDED assignment requires final_split None"
                )
            if reason_code not in (
                REASON_CODE_INCOMPLETE_LABEL,
                REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END,
            ):
                raise SplitValidationError(
                    f"an EXCLUDED assignment requires reason_code "
                    f"{REASON_CODE_INCOMPLETE_LABEL} or "
                    f"{REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END}, got {reason_code!r}"
                )
            if purge_boundary is not None:
                raise SplitValidationError(
                    "an EXCLUDED assignment must have purge_boundary None"
                )
            if reason_code == REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END:
                if self.nominal_split is not None:
                    raise SplitValidationError(
                        "FEATURE_CLOSE_AFTER_TEST_END requires nominal_split None"
                    )
            else:  # INCOMPLETE_LABEL
                if self.nominal_split is None:
                    raise SplitValidationError(
                        "INCOMPLETE_LABEL requires a nominal split"
                    )
                if self.label_status != LABEL_STATUS_INCOMPLETE:
                    raise SplitValidationError(
                        "INCOMPLETE_LABEL requires label_status INCOMPLETE"
                    )

        object.__setattr__(self, "sample_key", sample_key)
        object.__setattr__(self, "sample_version_id", sample_version_id)
        object.__setattr__(self, "feature_window_close", feature_window_close)
        object.__setattr__(self, "feature_window_close_date", feature_window_close_date)
        object.__setattr__(self, "actual_label_end_time", actual_label_end_time)
        object.__setattr__(self, "purge_boundary", purge_boundary)


@dataclass(frozen=True)
class ChronologicalSplitDiagnostics:
    """Deterministic result-level split counts with strict invariants.

    Invariants (all counts are real ints, never bools):

    - ``sample_count == assigned_count + purged_count + excluded_count``
    - ``assigned_count == train + validation + test assigned``
    - ``purged_count == train_purged_count + validation_purged_count``
    - ``excluded_count == incomplete_label_excluded_count
      + out_of_range_excluded_count``
    """

    sample_count: int
    assigned_count: int
    train_assigned_count: int
    validation_assigned_count: int
    test_assigned_count: int
    purged_count: int
    train_purged_count: int
    validation_purged_count: int
    excluded_count: int
    incomplete_label_excluded_count: int
    out_of_range_excluded_count: int

    def __post_init__(self) -> None:
        for name in (
            "sample_count",
            "assigned_count",
            "train_assigned_count",
            "validation_assigned_count",
            "test_assigned_count",
            "purged_count",
            "train_purged_count",
            "validation_purged_count",
            "excluded_count",
            "incomplete_label_excluded_count",
            "out_of_range_excluded_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise SplitValidationError(
                    f"{name} must be a non-negative real integer"
                )
        if (
            self.sample_count
            != self.assigned_count + self.purged_count + self.excluded_count
        ):
            raise SplitValidationError(
                "split diagnostics must satisfy sample_count == assigned_count "
                "+ purged_count + excluded_count"
            )
        if (
            self.assigned_count
            != self.train_assigned_count
            + self.validation_assigned_count
            + self.test_assigned_count
        ):
            raise SplitValidationError(
                "split diagnostics must satisfy assigned_count == train + "
                "validation + test assigned counts"
            )
        if self.purged_count != self.train_purged_count + self.validation_purged_count:
            raise SplitValidationError(
                "split diagnostics must satisfy purged_count == train + "
                "validation purged counts"
            )
        if (
            self.excluded_count
            != self.incomplete_label_excluded_count + self.out_of_range_excluded_count
        ):
            raise SplitValidationError(
                "split diagnostics must satisfy excluded_count == incomplete "
                "label + out of range excluded counts"
            )


@dataclass(frozen=True)
class ChronologicalSplitResult:
    """Deterministic output of one chronological split assignment.

    Every identity is recomputed at construction and must match the carried
    values; assignments must be unique and sorted by ``sample_key``; the
    assignment rows must exactly match the assignments; the local
    ``feature_window_close_date`` is re-derived from the spec's boundary
    timezone; PURGED purge boundaries are re-derived from the spec dates; and
    the diagnostics must match the actual assignment states. A manually
    assembled or ``dataclasses.replace``-modified inconsistent result fails
    closed.
    """

    split_spec: ChronologicalSplitSpec
    split_spec_pin: SpecPin
    splitter_version: str
    assignments: tuple[ChronologicalSplitAssignment, ...]
    assignment_schema: DatasetSchema
    assignment_rows: tuple[dict, ...]
    assignment_schema_id: str
    assignment_content_id: str
    split_result_id: str
    diagnostics: ChronologicalSplitDiagnostics

    def __post_init__(self) -> None:
        spec = self.split_spec
        if not isinstance(spec, ChronologicalSplitSpec):
            raise SplitValidationError(
                f"split_spec must be a ChronologicalSplitSpec, "
                f"got {type(spec).__name__}"
            )
        if not isinstance(self.split_spec_pin, SpecPin):
            raise SplitValidationError(
                f"split_spec_pin must be a SpecPin, "
                f"got {type(self.split_spec_pin).__name__}"
            )
        computed_pin = chronological_split_spec_pin(spec)
        if self.split_spec_pin != computed_pin:
            raise SplitValidationError(
                "split_spec_pin does not match the split spec content"
            )
        splitter_version = _require_version_text(
            self.splitter_version, "splitter_version"
        )

        assignments = tuple(self.assignments)
        for assignment in assignments:
            if not isinstance(assignment, ChronologicalSplitAssignment):
                raise SplitValidationError(
                    f"assignments must contain ChronologicalSplitAssignment "
                    f"instances, got {type(assignment).__name__}"
                )
        keys = [assignment.sample_key for assignment in assignments]
        if len(set(keys)) != len(keys):
            raise SplitValidationError(
                "assignments contain a duplicate sample_key: the same logical "
                "sample may not appear twice in one split result"
            )
        assignments_sorted = tuple(
            sorted(assignments, key=lambda assignment: assignment.sample_key)
        )

        # Re-derive the boundary-timezone facts from the spec so a tampered
        # feature_window_close_date or purge_boundary fails closed.
        train_boundary = _next_local_midnight_utc(
            spec.train_end_date, spec.boundary_timezone
        )
        validation_boundary = _next_local_midnight_utc(
            spec.validation_end_date, spec.boundary_timezone
        )
        tz = ZoneInfo(spec.boundary_timezone)
        for assignment in assignments_sorted:
            expected_date = assignment.feature_window_close.astimezone(tz).date()
            if assignment.feature_window_close_date != expected_date:
                raise SplitValidationError(
                    f"feature_window_close_date of sample "
                    f"{assignment.sample_key} does not match the split spec "
                    "boundary timezone"
                )
            if assignment.assignment_status == SPLIT_STATUS_PURGED:
                expected_boundary = (
                    train_boundary
                    if assignment.nominal_split == SPLIT_TRAIN
                    else validation_boundary
                )
                if assignment.purge_boundary != expected_boundary:
                    raise SplitValidationError(
                        f"purge_boundary of sample {assignment.sample_key} "
                        "does not match the split spec boundary"
                    )

        schema = self.assignment_schema
        if not isinstance(schema, DatasetSchema):
            raise SplitValidationError(
                f"assignment_schema must be a DatasetSchema, "
                f"got {type(schema).__name__}"
            )
        if schema != split_assignment_schema():
            raise SplitValidationError(
                "assignment_schema must exactly match split_assignment_schema()"
            )
        if self.assignment_schema_id != dataset_schema_id(schema):
            raise SplitValidationError(
                "assignment_schema_id does not match the carried assignment schema"
            )
        rows = tuple(self.assignment_rows)
        if rows != _assignment_rows(assignments_sorted):
            raise SplitValidationError(
                "assignment_rows do not match the carried assignments"
            )
        if self.assignment_content_id != logical_dataset_content_id(schema, rows):
            raise SplitValidationError(
                "assignment_content_id does not match the carried assignment rows"
            )
        expected_result_id = chronological_split_result_id(
            splitter_version=splitter_version,
            split_spec_content_id=computed_pin.content_sha256,
            assignment_schema_version=SPLIT_ASSIGNMENT_SCHEMA_VERSION,
            assignment_schema_id=self.assignment_schema_id,
            assignment_content_id=self.assignment_content_id,
            sample_count=len(assignments_sorted),
        )
        if self.split_result_id != expected_result_id:
            raise SplitValidationError(
                "split_result_id does not match the carried identities"
            )
        if not isinstance(self.diagnostics, ChronologicalSplitDiagnostics):
            raise SplitValidationError(
                f"diagnostics must be a ChronologicalSplitDiagnostics, "
                f"got {type(self.diagnostics).__name__}"
            )
        if self.diagnostics != _derive_diagnostics(assignments_sorted):
            raise SplitValidationError(
                "diagnostics do not match the actual assignment states"
            )


# ---------------------------------------------------------------------------
# Fixed assignment logical schema (existing PR-12 schema/content identities).
# ---------------------------------------------------------------------------

#: Fixed authoritative column order of the split assignment schema.
SPLIT_ASSIGNMENT_COLUMNS = (
    ("sample_key", "string", False),
    ("sample_version_id", "string", False),
    ("feature_window_close", "timestamp_us_utc", False),
    ("feature_window_close_date", "date32", False),
    ("label_status", "string", False),
    ("actual_label_end_time", "timestamp_us_utc", True),
    ("nominal_split", "string", True),
    ("final_split", "string", True),
    ("assignment_status", "string", False),
    ("reason_code", "string", True),
    ("purge_boundary", "timestamp_us_utc", True),
)


def split_assignment_schema() -> DatasetSchema:
    """Fixed logical Dataset schema of the split assignment rows.

    Uses the existing :class:`DatasetField` / :class:`DatasetSchema` model;
    the schema ID is the existing ``dataset_schema_id`` encoding. Field order
    is authoritative.
    """
    return DatasetSchema(
        tuple(
            DatasetField(name, logical_type, nullable=nullable)
            for name, logical_type, nullable in SPLIT_ASSIGNMENT_COLUMNS
        )
    )


def split_assignment_schema_id() -> str:
    """Deterministic schema ID of the split assignment schema (PR-12
    encoding)."""
    return dataset_schema_id(split_assignment_schema())


def split_assignment_content_id(rows) -> str:
    """Deterministic logical content ID of split assignment rows (PR-12
    encoding).

    Row order is irrelevant and row multiplicity is preserved; zero rows
    produce a deterministic, request-independent content ID tied to the
    schema; no placeholder row is fabricated.
    """
    return logical_dataset_content_id(split_assignment_schema(), rows)


def _assignment_rows(
    assignments: tuple[ChronologicalSplitAssignment, ...],
) -> tuple[dict, ...]:
    """Deterministic assignment rows in the fixed schema field order."""
    return tuple(
        {
            "sample_key": assignment.sample_key,
            "sample_version_id": assignment.sample_version_id,
            "feature_window_close": assignment.feature_window_close,
            "feature_window_close_date": assignment.feature_window_close_date,
            "label_status": assignment.label_status,
            "actual_label_end_time": assignment.actual_label_end_time,
            "nominal_split": assignment.nominal_split,
            "final_split": assignment.final_split,
            "assignment_status": assignment.assignment_status,
            "reason_code": assignment.reason_code,
            "purge_boundary": assignment.purge_boundary,
        }
        for assignment in assignments
    )


def _derive_diagnostics(
    assignments: tuple[ChronologicalSplitAssignment, ...],
) -> ChronologicalSplitDiagnostics:
    """Deterministic diagnostics derived from the actual assignment states."""
    return ChronologicalSplitDiagnostics(
        sample_count=len(assignments),
        assigned_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_ASSIGNED
        ),
        train_assigned_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_ASSIGNED
            and assignment.final_split == SPLIT_TRAIN
        ),
        validation_assigned_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_ASSIGNED
            and assignment.final_split == SPLIT_VALIDATION
        ),
        test_assigned_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_ASSIGNED
            and assignment.final_split == SPLIT_TEST
        ),
        purged_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_PURGED
        ),
        train_purged_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_PURGED
            and assignment.reason_code
            == REASON_CODE_ACTUAL_LABEL_END_CROSSES_TRAIN_BOUNDARY
        ),
        validation_purged_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_PURGED
            and assignment.reason_code
            == REASON_CODE_ACTUAL_LABEL_END_CROSSES_VALIDATION_BOUNDARY
        ),
        excluded_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_EXCLUDED
        ),
        incomplete_label_excluded_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_EXCLUDED
            and assignment.reason_code == REASON_CODE_INCOMPLETE_LABEL
        ),
        out_of_range_excluded_count=sum(
            1
            for assignment in assignments
            if assignment.assignment_status == SPLIT_STATUS_EXCLUDED
            and assignment.reason_code == REASON_CODE_FEATURE_CLOSE_AFTER_TEST_END
        ),
    )


# ---------------------------------------------------------------------------
# Deterministic identities.
# ---------------------------------------------------------------------------


def chronological_split_spec_content_id(spec: ChronologicalSplitSpec) -> str:
    """64-character lowercase SHA-256 of the deterministic semantic content
    of a :class:`ChronologicalSplitSpec`.

    The typed model is expanded into a flat mapping of scalar values and
    passed to the existing versioned identity encoding
    (:func:`market_vault.dataset.encoding.encode_identity`); no new or
    unversioned hashing scheme is introduced. The ID contains the content-ID
    version, the spec kind and schema version, and every semantic field
    (name, spec version, boundary timezone, the three boundary dates, and the
    four fixed rule values). It never contains file paths, mtimes, current
    time, Python object addresses, insertion order, local timezone,
    ``repr()``, or build directories.
    """
    if not isinstance(spec, ChronologicalSplitSpec):
        raise SplitValidationError(
            f"chronological_split_spec_content_id requires a "
            f"ChronologicalSplitSpec, got {type(spec).__name__}"
        )
    try:
        return encode_identity(
            CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION,
            {
                "version": CHRONOLOGICAL_SPLIT_SPEC_CONTENT_ID_VERSION,
                "kind": spec.kind,
                "spec_schema_version": spec.spec_schema_version,
                "name": spec.name,
                "spec_version": spec.version,
                "boundary_timezone": spec.boundary_timezone,
                "train_end_date": spec.train_end_date,
                "validation_end_date": spec.validation_end_date,
                "test_end_date": spec.test_end_date,
                "assignment_rule": spec.assignment_rule,
                "purge_rule": spec.purge_rule,
                "incomplete_label_policy": spec.incomplete_label_policy,
                "out_of_range_policy": spec.out_of_range_policy,
            },
        )
    except DatasetError as exc:
        raise SplitValidationError(str(exc)) from exc


def chronological_split_spec_pin(spec: ChronologicalSplitSpec) -> SpecPin:
    """Convert a :class:`ChronologicalSplitSpec` to the existing
    :class:`SpecPin` (kind SPLIT) using its semantic content ID.

    No new pin model is introduced and :class:`SpecPin` is not modified. Pins
    produced this way enter ``DatasetIdentityInput.split_spec`` directly.
    """
    if not isinstance(spec, ChronologicalSplitSpec):
        raise SplitValidationError(
            f"chronological_split_spec_pin requires a ChronologicalSplitSpec, "
            f"got {type(spec).__name__}"
        )
    return SpecPin(
        kind=spec.kind,
        name=spec.name,
        version=spec.version,
        content_sha256=chronological_split_spec_content_id(spec),
    )


def chronological_split_result_id(
    *,
    splitter_version: str = CHRONOLOGICAL_SPLITTER_VERSION,
    split_spec_content_id: str,
    assignment_schema_version: str = SPLIT_ASSIGNMENT_SCHEMA_VERSION,
    assignment_schema_id: str,
    assignment_content_id: str,
    sample_count: int,
) -> str:
    """Versioned SHA-256 identity of one complete chronological split result.

    Binds the result-ID version, the splitter version, the assignment schema
    contract version, the split spec content ID, the split assignment schema
    ID, the split assignment content ID, and the sample count. It never
    contains input order, ``built_at``, current time, local timezone, file
    paths, manifest paths, or Python ``repr()``.
    """
    splitter_version = _require_version_text(splitter_version, "splitter_version")
    split_spec_content_id = _require_lower_sha256(
        split_spec_content_id, "split_spec_content_id"
    )
    assignment_schema_version = _require_version_text(
        assignment_schema_version, "assignment_schema_version"
    )
    assignment_schema_id = _require_lower_sha256(
        assignment_schema_id, "assignment_schema_id"
    )
    assignment_content_id = _require_lower_sha256(
        assignment_content_id, "assignment_content_id"
    )
    if type(sample_count) is not int or sample_count < 0:
        raise SplitValidationError(
            "sample_count must be a non-negative real integer"
        )
    try:
        return encode_identity(
            CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION,
            {
                "version": CHRONOLOGICAL_SPLIT_RESULT_ID_VERSION,
                "splitter_version": splitter_version,
                "assignment_schema_version": assignment_schema_version,
                "split_spec_content_id": split_spec_content_id,
                "assignment_schema_id": assignment_schema_id,
                "assignment_content_id": assignment_content_id,
                "sample_count": sample_count,
            },
        )
    except DatasetError as exc:
        raise SplitValidationError(str(exc)) from exc
