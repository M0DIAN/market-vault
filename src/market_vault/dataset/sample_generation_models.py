"""Frozen typed models of the v0.6.0 Sample Generation contract foundation
(PR-2).

Every model is frozen, validates at construction, and normalizes
deterministically at construction (NFC path text, deterministic sorting,
explicit duplicate rejection, UTC microsecond instants), so the strict
generation-plan parser and the semantic content identity layer can trust
their inputs. All failures raise the unified :class:`SampleGenerationError`
(a subclass of :class:`DatasetError`); unknown, future, or old schema
versions fail closed and are never "best-effort" interpreted.

The v1 generation rule fixes the BARS-style research boundary: the feature
window, the label window, and the stride are explicit positive bar counts;
candidate anchors come only from verified Canonical bars
(``anchor_source == VERIFIED_CANONICAL_BARS``); no synthetic bars,
interpolation, or forward-fill is ever fabricated; and cross-day windows
are rejected. The Sample Generator core (PR-3) and the Sample Generation
CLI (PR-4) are not implemented.

This module contains only version constants, the error type, and frozen
models with construction-time normalization and validation. It never
parses JSON, never reads files, and never generates a sample request.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime

from .encoding import DatasetError, normalize_utc_datetime, reject_unsafe_text
from .models import (
    SPEC_KIND_FEATURE,
    SPEC_KIND_LABEL,
    SPEC_KIND_SPLIT,
    CanonicalBuildPin,
    DatasetScope,
    SpecPin,
)

__all__ = [
    "SAMPLE_GENERATION_CONTRACT_VERSION",
    "SAMPLE_GENERATION_CONTENT_ID_VERSION",
    "SAMPLE_GENERATION_PLAN_SCHEMA_VERSION",
    "SAMPLE_GENERATION_RULE_SCHEMA_VERSION",
    "SampleGenerationError",
    "SampleGenerationIdentityInput",
    "SampleGenerationPlan",
    "SampleGenerationRule",
]

#: Version of the whole Sample Generation contract (frozen models, strict
#: plan schema, normalization, and content identity). Changing it changes
#: every generation identity that references it.
SAMPLE_GENERATION_CONTRACT_VERSION = "market-vault-sample-generation-contract-v1"

#: Version of the strict generation-plan JSON document contract consumed by
#: :func:`market_vault.dataset.sample_generation.parse_sample_generation_plan_bytes`.
#: A generation plan is an explicit execution input, never an identity
#: artifact: its raw bytes never enter any Dataset identity.
SAMPLE_GENERATION_PLAN_SCHEMA_VERSION = "market-vault-sample-generation-plan-v1"

#: Version of the generation-rule block of the generation-plan schema.
SAMPLE_GENERATION_RULE_SCHEMA_VERSION = "market-vault-sample-generation-rule-v1"

#: Version of the deterministic semantic content identity of one generation
#: input (:func:`market_vault.dataset.sample_generation.sample_generation_content_id`).
#: Changing it changes every generation content ID.
SAMPLE_GENERATION_CONTENT_ID_VERSION = "market-vault-sample-generation-content-v1"

#: v1 fixed rule values (fail closed; no hidden defaults).
ANCHOR_SOURCE_VERIFIED_CANONICAL_BARS = "VERIFIED_CANONICAL_BARS"
ANCHOR_RULE_FEATURE_WINDOW_CLOSE = "FEATURE_WINDOW_CLOSE"
CROSS_DAY_POLICY_REJECT = "REJECT"

#: v1 fixed scope restriction: only the no-adjusted-price policy exists.
SCOPE_ADJUSTMENT_NONE = "NONE"

#: Characters that mark expansion or glob patterns. They are never expanded
#: and fail closed: ``~`` (home expansion), ``$`` and ``%`` (environment
#: variables), and the glob pattern characters ``* ? [ ]``.
_PATH_EXPANSION_MARKERS = frozenset("~$%*?[]")


class SampleGenerationError(DatasetError):
    """Structured fail-closed failure of the Sample Generation contract
    layer (v0.6.0 PR-2).

    Raised for every invalid contract input: unsupported schema versions,
    invalid frozen models, strict generation-plan JSON violations, invalid
    path strings, and invalid identity inputs. Low-level documented
    validation exceptions (``DatasetError``, ``TypeError``, ``ValueError``,
    ``KeyError``) are always converted to this error; broad ``except
    Exception`` is never used and programming errors are never hidden.
    """


def _normalize_instant(value, label: str) -> datetime:
    """Timezone-aware instant normalized to UTC microseconds; naive fails."""
    try:
        return normalize_utc_datetime(value, label)
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc


def _require_v1_scope(value, label: str) -> DatasetScope:
    """The one model-level v1 scope policy: type check plus
    ``adjustment == NONE``.

    Every frozen model that carries a scope (and every parser path that
    constructs one) must pass through exactly this helper, so the supported
    model set equals the parser-accepted set and no unsupported scope ever
    reaches serialization or the content identity. Only the existing
    :class:`DatasetScope` normalization is trusted (symbols, dates, case,
    and sorting are never re-implemented); the original frozen scope is
    returned unchanged; the filesystem is never accessed.
    """
    if not isinstance(value, DatasetScope):
        raise SampleGenerationError(
            f"{label} must be a DatasetScope, got {type(value).__name__}"
        )
    if value.adjustment != SCOPE_ADJUSTMENT_NONE:
        raise SampleGenerationError(
            f"{label} must use adjustment == {SCOPE_ADJUSTMENT_NONE}, "
            f"got {value.adjustment!r}"
        )
    return value


def _normalize_path_text(value, label: str) -> str:
    """One path string under the contract's safety boundaries.

    The value must be a string; it is NFC-normalized and must not be empty,
    must not carry leading or trailing whitespace, must not contain control
    characters or reserved encoding separators, must not contain any ``.``
    or ``..`` component (checked on both separators on the raw string), and
    must not contain ``~``, environment-variable markers, or glob pattern
    characters. ``~``, environment variables, and globs are never expanded;
    ``resolve()`` is never called; and the filesystem is never accessed.
    """
    if not isinstance(value, str):
        raise SampleGenerationError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    # Control characters and encoding separators are rejected on the raw
    # value: Python treats U+001C-U+001F as whitespace, so strip() below
    # would silently erase them before any safety check.
    try:
        reject_unsafe_text(value, label)
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc
    text = unicodedata.normalize("NFC", value)
    if not text:
        raise SampleGenerationError(f"{label} must not be empty")
    if text != text.strip():
        raise SampleGenerationError(
            f"{label} must not have leading or trailing whitespace"
        )
    for part in text.replace("\\", "/").split("/"):
        if part in (".", ".."):
            raise SampleGenerationError(
                f"{label} must not contain '.' or '..' path components: {value!r}"
            )
    for character in text:
        if character in _PATH_EXPANSION_MARKERS:
            raise SampleGenerationError(
                f"{label} must not contain expansion or glob characters "
                f"('~', '$', '%', '*', '?', '[', ']'): {value!r}"
            )
    return text


def _normalize_path_array(values, label: str) -> tuple[str, ...]:
    """Non-empty unique path array; order is not semantic.

    Every entry passes the path-string safety boundaries and is
    NFC-normalized; entries are deterministically sorted; duplicates fail
    closed after normalization (never silently deduplicated); the input
    order never has semantics.
    """
    if isinstance(values, (str, bytes)):
        raise SampleGenerationError(f"{label} must be an iterable of path strings")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise SampleGenerationError(
            f"{label} must be an iterable of path strings"
        ) from exc
    if not items:
        raise SampleGenerationError(f"{label} must not be empty")
    normalized = tuple(
        sorted(_normalize_path_text(item, f"{label} entry") for item in items)
    )
    if len(set(normalized)) != len(normalized):
        raise SampleGenerationError(
            f"{label} must not contain duplicates after normalization"
        )
    return normalized


def _require_positive_int(value, label: str) -> int:
    """Real positive int; bool and float are never accepted."""
    if type(value) is not int or value <= 0:
        raise SampleGenerationError(
            f"{label} must be a real positive integer, got {value!r}"
        )
    return value


def _normalize_spec_pins(values, expected_kind: str, label: str) -> tuple[SpecPin, ...]:
    """Container-enforced spec pins: every pin must be a SpecPin of the
    expected kind, deterministically sorted by (kind, name, version);
    duplicate (kind, name, version) keys fail closed."""
    if isinstance(values, (str, bytes)):
        raise SampleGenerationError(f"{label} must be an iterable of SpecPin")
    try:
        items = tuple(values)
    except TypeError as exc:
        raise SampleGenerationError(f"{label} must be an iterable of SpecPin") from exc
    for item in items:
        if not isinstance(item, SpecPin):
            raise SampleGenerationError(
                f"{label} must contain SpecPin instances, got {type(item).__name__}"
            )
        if item.kind != expected_kind:
            raise SampleGenerationError(
                f"{label} may only contain {expected_kind} spec pins, "
                f"got kind {item.kind!r}"
            )
    normalized = tuple(sorted(items, key=lambda item: (item.kind, item.name, item.version)))
    keys = [(item.kind, item.name, item.version) for item in normalized]
    if len(set(keys)) != len(keys):
        raise SampleGenerationError(
            f"{label} must not contain duplicate (kind, name, version) keys"
        )
    return normalized


@dataclass(frozen=True)
class SampleGenerationRule:
    """Frozen v1 generation rule (BARS-style windows only).

    ``rule_schema_version`` must equal
    :data:`SAMPLE_GENERATION_RULE_SCHEMA_VERSION`; the three window sizes are
    real positive ints (bool, zero, negative, float, and string values are
    rejected); and the three policy fields accept exactly the fixed v1
    values (``VERIFIED_CANONICAL_BARS`` / ``FEATURE_WINDOW_CLOSE`` /
    ``REJECT``). The rule declares only window geometry and candidate-anchor
    provenance: request generation is PR-3's responsibility.
    """

    rule_schema_version: str
    feature_window_bars: int
    label_window_bars: int
    stride_bars: int
    anchor_source: str
    anchor_rule: str
    cross_day_policy: str

    def __post_init__(self) -> None:
        if self.rule_schema_version != SAMPLE_GENERATION_RULE_SCHEMA_VERSION:
            raise SampleGenerationError(
                f"unsupported rule_schema_version {self.rule_schema_version!r}; "
                f"only {SAMPLE_GENERATION_RULE_SCHEMA_VERSION} is accepted"
            )
        object.__setattr__(
            self,
            "feature_window_bars",
            _require_positive_int(self.feature_window_bars, "feature_window_bars"),
        )
        object.__setattr__(
            self,
            "label_window_bars",
            _require_positive_int(self.label_window_bars, "label_window_bars"),
        )
        object.__setattr__(
            self, "stride_bars", _require_positive_int(self.stride_bars, "stride_bars")
        )
        if self.anchor_source != ANCHOR_SOURCE_VERIFIED_CANONICAL_BARS:
            raise SampleGenerationError(
                f"anchor_source must be {ANCHOR_SOURCE_VERIFIED_CANONICAL_BARS}, "
                f"got {self.anchor_source!r}"
            )
        if self.anchor_rule != ANCHOR_RULE_FEATURE_WINDOW_CLOSE:
            raise SampleGenerationError(
                f"anchor_rule must be {ANCHOR_RULE_FEATURE_WINDOW_CLOSE}, "
                f"got {self.anchor_rule!r}"
            )
        if self.cross_day_policy != CROSS_DAY_POLICY_REJECT:
            raise SampleGenerationError(
                f"cross_day_policy must be {CROSS_DAY_POLICY_REJECT}, "
                f"got {self.cross_day_policy!r}"
            )


@dataclass(frozen=True)
class SampleGenerationPlan:
    """Frozen, strictly parsed v1 generation plan.

    Every input is explicit: ``canonical_build_dirs``, ``feature_spec_files``,
    and ``label_spec_files`` are non-empty unique path arrays (order is not
    semantic and is deterministically sorted); ``split_spec_file`` is exactly
    one explicit path; ``scope`` is the existing :class:`DatasetScope`;
    ``generation_rule`` is a :class:`SampleGenerationRule`; ``dataset_as_of``
    is null or a timezone-aware instant normalized to UTC microseconds;
    ``output_root`` and ``output_plan_path`` are explicit safe path strings;
    ``built_at`` is a required timezone-aware instant normalized to UTC
    microseconds and is never read from the current time.

    The model is deeply immutable and never carries the raw plan bytes or any
    filesystem object: paths are validated as strings only, no directory is
    scanned, no spec or Canonical build is read, and no file is created. The
    path inputs, ``output_root``, ``built_at``, and ``output_plan_path``
    never enter the Sample Generation semantic content identity.
    """

    generation_plan_schema_version: str
    canonical_build_dirs: tuple[str, ...]
    feature_spec_files: tuple[str, ...]
    label_spec_files: tuple[str, ...]
    split_spec_file: str
    scope: DatasetScope
    generation_rule: SampleGenerationRule
    dataset_as_of: datetime | None
    output_root: str
    built_at: datetime
    output_plan_path: str

    def __post_init__(self) -> None:
        if self.generation_plan_schema_version != SAMPLE_GENERATION_PLAN_SCHEMA_VERSION:
            raise SampleGenerationError(
                f"unsupported generation_plan_schema_version "
                f"{self.generation_plan_schema_version!r}; only "
                f"{SAMPLE_GENERATION_PLAN_SCHEMA_VERSION} is accepted"
            )
        object.__setattr__(
            self,
            "canonical_build_dirs",
            _normalize_path_array(self.canonical_build_dirs, "canonical_build_dirs"),
        )
        object.__setattr__(
            self,
            "feature_spec_files",
            _normalize_path_array(self.feature_spec_files, "feature_spec_files"),
        )
        object.__setattr__(
            self,
            "label_spec_files",
            _normalize_path_array(self.label_spec_files, "label_spec_files"),
        )
        object.__setattr__(
            self,
            "split_spec_file",
            _normalize_path_text(self.split_spec_file, "split_spec_file"),
        )
        _require_v1_scope(self.scope, "scope")
        if not isinstance(self.generation_rule, SampleGenerationRule):
            raise SampleGenerationError(
                f"generation_rule must be a SampleGenerationRule, "
                f"got {type(self.generation_rule).__name__}"
            )
        if self.dataset_as_of is not None:
            object.__setattr__(
                self, "dataset_as_of", _normalize_instant(self.dataset_as_of, "dataset_as_of")
            )
        object.__setattr__(
            self, "output_root", _normalize_path_text(self.output_root, "output_root")
        )
        object.__setattr__(self, "built_at", _normalize_instant(self.built_at, "built_at"))
        object.__setattr__(
            self,
            "output_plan_path",
            _normalize_path_text(self.output_plan_path, "output_plan_path"),
        )


@dataclass(frozen=True)
class SampleGenerationIdentityInput:
    """All identity-bearing inputs of one generation.

    Canonical pins must all be :class:`CanonicalBuildPin` and are sorted by
    ``canonical_build_id``; a duplicate ``canonical_build_id`` fails even
    when the objects are identical. Feature and Label pins must all be
    :class:`SpecPin` of the matching kind (FEATURE / LABEL) and are sorted
    by (kind, name, version); a duplicate (kind, name, version) key fails.
    ``split_spec_pin`` must be a :class:`SpecPin` of kind SPLIT. ``scope``
    must be a :class:`DatasetScope`, ``generation_rule`` a
    :class:`SampleGenerationRule`, and ``dataset_as_of`` null or a
    timezone-aware instant normalized to UTC microseconds. Nothing is ever
    silently deduplicated.
    """

    canonical_build_pins: tuple[CanonicalBuildPin, ...]
    feature_spec_pins: tuple[SpecPin, ...]
    label_spec_pins: tuple[SpecPin, ...]
    split_spec_pin: SpecPin
    scope: DatasetScope
    generation_rule: SampleGenerationRule
    dataset_as_of: datetime | None

    def __post_init__(self) -> None:
        if isinstance(self.canonical_build_pins, (str, bytes)):
            raise SampleGenerationError(
                "canonical_build_pins must be an iterable of CanonicalBuildPin"
            )
        try:
            builds = tuple(self.canonical_build_pins)
        except TypeError as exc:
            raise SampleGenerationError(
                "canonical_build_pins must be an iterable of CanonicalBuildPin"
            ) from exc
        for pin in builds:
            if not isinstance(pin, CanonicalBuildPin):
                raise SampleGenerationError(
                    f"canonical_build_pins must contain CanonicalBuildPin "
                    f"instances, got {type(pin).__name__}"
                )
        builds_sorted = tuple(sorted(builds, key=lambda pin: pin.canonical_build_id))
        build_ids = [pin.canonical_build_id for pin in builds_sorted]
        if len(set(build_ids)) != len(build_ids):
            raise SampleGenerationError(
                "canonical_build_pins must not contain duplicate "
                "canonical_build_id values"
            )
        object.__setattr__(self, "canonical_build_pins", builds_sorted)
        object.__setattr__(
            self,
            "feature_spec_pins",
            _normalize_spec_pins(self.feature_spec_pins, SPEC_KIND_FEATURE, "feature_spec_pins"),
        )
        object.__setattr__(
            self,
            "label_spec_pins",
            _normalize_spec_pins(self.label_spec_pins, SPEC_KIND_LABEL, "label_spec_pins"),
        )
        split_pin = self.split_spec_pin
        if not isinstance(split_pin, SpecPin):
            raise SampleGenerationError(
                f"split_spec_pin must be a SpecPin, got {type(split_pin).__name__}"
            )
        if split_pin.kind != SPEC_KIND_SPLIT:
            raise SampleGenerationError(
                f"split_spec_pin may only be a SPLIT spec pin, got kind {split_pin.kind!r}"
            )
        object.__setattr__(self, "split_spec_pin", split_pin)
        _require_v1_scope(self.scope, "scope")
        if not isinstance(self.generation_rule, SampleGenerationRule):
            raise SampleGenerationError(
                f"generation_rule must be a SampleGenerationRule, "
                f"got {type(self.generation_rule).__name__}"
            )
        if self.dataset_as_of is not None:
            object.__setattr__(
                self,
                "dataset_as_of",
                _normalize_instant(self.dataset_as_of, "dataset_as_of"),
            )
