"""Frozen result models of the v0.6.0 Sample Generator core (PR-3).

Every model is frozen, validates at construction, and normalizes
deterministically at construction, so the generator output can be trusted
by PR-4 (CLI and build-plan output). All failures raise the unified
:class:`SampleGenerationError` of the PR-2 contract layer; no new error
type is introduced.

``SAMPLE_GENERATOR_CORE_VERSION`` identifies the generator core
implementation. It never enters ``sample_generation_content_id``, never
enters ``dataset_id``, never enters a sample request, and never changes any
existing identity: it only records which core version produced a result.

``SampleGenerationResult`` is the only output of
:func:`market_vault.dataset.sample_generation_core.generate_sample_requests`.
It is deeply immutable: tuples, frozen nested models, no dicts or lists, no
raw JSON or YAML bytes, no ``Path`` objects, no ``build_path``, no
``output_root``, no ``built_at``, no ``output_plan_path``, and no machine,
working-directory, mtime, or current-time facts. The result carries the
generated request sequence, the verified pins, the scope, the generation
rule, ``dataset_as_of``, and deterministic diagnostics; it never claims a
sample is COMPLETE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..intraday_audit import parse_intraday_interval
from .encoding import DatasetError, normalize_utc_datetime
from .models import CanonicalBuildPin, DatasetScope, SpecPin
from .pit_identity import pit_sample_key
from .pit_models import PITSampleRequest
from .sample_generation import sample_generation_content_id
from .sample_generation_models import (
    SampleGenerationError,
    SampleGenerationIdentityInput,
    SampleGenerationRule,
)

__all__ = [
    "SAMPLE_GENERATOR_CORE_VERSION",
    "SampleGenerationDiagnostics",
    "SampleGenerationResult",
]

#: Version of the deterministic Sample Generator core implementation.
#: Changing it changes results recorded against it; it never enters the
#: Generation content identity, ``dataset_id``, or any sample request.
SAMPLE_GENERATOR_CORE_VERSION = "market-vault-sample-generator-core-v1"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_non_negative_int(value, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SampleGenerationError(
            f"{label} must be a real non-negative integer, got {value!r}"
        )
    return value


def _require_lower_sha256(value, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value):
        raise SampleGenerationError(
            f"{label} must be a 64-character lowercase SHA-256 hex string, "
            f"got {value!r}"
        )
    return value


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise SampleGenerationError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


def _validate_request_bindings(
    requests: tuple,
    scope: DatasetScope,
    rule: SampleGenerationRule,
) -> None:
    """Every request must bind to the carried scope and rule exactly.

    Each request's code / anchor market-calendar date / interval /
    adjustment / requested_session must equal the scope's dimensions;
    ``label_window_start == feature_window_close``; and the feature and
    label spans must equal the rule's window sizes times the nominal
    interval. All arithmetic failures are converted to
    :class:`SampleGenerationError`; programming errors are never swallowed.
    """
    try:
        interval_delta = parse_intraday_interval(scope.interval)
    except ValueError as exc:
        raise SampleGenerationError(
            f"cannot parse scope interval {scope.interval!r}: {exc}"
        ) from exc
    for request in requests:
        if request.code not in scope.symbols:
            raise SampleGenerationError(
                f"request code {request.code!r} is not in the scope symbols"
            )
        if request.anchor_market_calendar_date not in scope.trade_dates:
            raise SampleGenerationError(
                "request anchor_market_calendar_date "
                f"{request.anchor_market_calendar_date} is not in the scope "
                "trade dates"
            )
        if request.interval != scope.interval:
            raise SampleGenerationError(
                f"request interval {request.interval!r} does not match the "
                f"scope interval {scope.interval!r}"
            )
        if request.adjustment != scope.adjustment:
            raise SampleGenerationError(
                f"request adjustment {request.adjustment!r} does not match "
                f"the scope adjustment {scope.adjustment!r}"
            )
        if request.requested_session != scope.requested_session:
            raise SampleGenerationError(
                f"request requested_session {request.requested_session!r} "
                "does not match the scope requested_session "
                f"{scope.requested_session!r}"
            )
        if request.label_window_start != request.feature_window_close:
            raise SampleGenerationError(
                "request label_window_start must equal feature_window_close"
            )
        # Every window computation — including the expected-span timedelta
        # multiplication, which can overflow for huge positive window
        # counts — lies inside one controlled arithmetic boundary, so a raw
        # OverflowError can never cross the public model boundary.
        try:
            feature_span = (
                request.feature_window_close - request.feature_window_start
            )
            label_span = request.label_window_close - request.label_window_start
            expected_feature_span = rule.feature_window_bars * interval_delta
            expected_label_span = rule.label_window_bars * interval_delta
        except (OverflowError, ValueError, TypeError, ZeroDivisionError) as exc:
            raise SampleGenerationError(
                f"request window arithmetic failed: {exc}"
            ) from exc
        if feature_span != expected_feature_span:
            raise SampleGenerationError(
                f"request feature window span {feature_span} does not equal "
                f"feature_window_bars ({rule.feature_window_bars}) times the "
                f"nominal interval ({interval_delta})"
            )
        if label_span != expected_label_span:
            raise SampleGenerationError(
                f"request label window span {label_span} does not equal "
                f"label_window_bars ({rule.label_window_bars}) times the "
                f"nominal interval ({interval_delta})"
            )


def _request_sort_key(request: PITSampleRequest):
    """The one canonical stable request order (B13): code,
    anchor_market_calendar_date, feature_window_close, feature_window_start,
    label_window_start, label_window_close, interval, adjustment,
    requested_session. Both the generator and the result model use exactly
    this key, so the order can never drift between generation and
    validation."""
    return (
        request.code,
        request.anchor_market_calendar_date,
        request.feature_window_close,
        request.feature_window_start,
        request.label_window_start,
        request.label_window_close,
        request.interval,
        request.adjustment,
        request.requested_session,
    )


@dataclass(frozen=True)
class SampleGenerationDiagnostics:
    """Deterministic per-generation counts (no free text).

    ``canonical_bar_count`` counts every bar of every loaded build;
    ``in_scope_bar_count`` counts only the bars matching the plan scope;
    ``contiguous_segment_count`` is the number of contiguous segments found
    after the stable sort; ``candidate_anchor_count`` counts the anchors
    whose feature slice is complete; ``insufficient_feature_history_count``
    counts segments too short to establish the first anchor;
    ``insufficient_label_future_count`` counts anchors whose label slice is
    incomplete; ``generated_request_count`` is the final request count. The
    invariant ``candidate_anchor_count == generated_request_count +
    insufficient_label_future_count`` always holds.
    """

    canonical_build_count: int
    canonical_bar_count: int
    in_scope_bar_count: int
    contiguous_segment_count: int
    candidate_anchor_count: int
    generated_request_count: int
    insufficient_feature_history_count: int
    insufficient_label_future_count: int

    def __post_init__(self) -> None:
        for name in (
            "canonical_build_count",
            "canonical_bar_count",
            "in_scope_bar_count",
            "contiguous_segment_count",
            "candidate_anchor_count",
            "generated_request_count",
            "insufficient_feature_history_count",
            "insufficient_label_future_count",
        ):
            object.__setattr__(self, name, _require_non_negative_int(getattr(self, name), name))
        if (
            self.candidate_anchor_count
            != self.generated_request_count + self.insufficient_label_future_count
        ):
            raise SampleGenerationError(
                "generation diagnostics must satisfy candidate_anchor_count "
                "== generated_request_count + insufficient_label_future_count"
            )


@dataclass(frozen=True)
class SampleGenerationResult:
    """The frozen, deeply immutable output of one deterministic generation.

    ``generator_core_version`` must equal
    :data:`SAMPLE_GENERATOR_CORE_VERSION`; ``generation_content_id`` must be
    a 64-character lowercase SHA-256 hex string; every request must be a
    formal :class:`PITSampleRequest` with a complete label window, no
    duplicate ``pit_sample_key``, and the canonical stable request order;
    the pins must be the verified, normalized pins of the generation
    identity input (canonical build pins sorted by ``canonical_build_id``
    without duplicates, Feature pins of kind FEATURE, Label pins of kind
    LABEL, split pin of kind SPLIT); the scope must pass the model-level v1
    scope policy; the diagnostics must be consistent with the requests
    (``generated_request_count == len(requests)``). The result never claims
    a sample is COMPLETE: future PIT market/archive clocks may still make an
    executed sample INCOMPLETE.
    """

    generator_core_version: str
    generation_content_id: str
    requests: tuple[PITSampleRequest, ...]
    canonical_build_pins: tuple[CanonicalBuildPin, ...]
    feature_spec_pins: tuple[SpecPin, ...]
    label_spec_pins: tuple[SpecPin, ...]
    split_spec_pin: SpecPin
    scope: DatasetScope
    generation_rule: SampleGenerationRule
    dataset_as_of: datetime | None
    diagnostics: SampleGenerationDiagnostics

    def __post_init__(self) -> None:
        if self.generator_core_version != SAMPLE_GENERATOR_CORE_VERSION:
            raise SampleGenerationError(
                f"unsupported generator_core_version {self.generator_core_version!r}; "
                f"only {SAMPLE_GENERATOR_CORE_VERSION} is accepted"
            )
        _require_lower_sha256(self.generation_content_id, "generation_content_id")

        # Semantic self-validation through the formal identity input model:
        # the pins, scope, rule, and dataset_as_of are normalized exactly as
        # the generation identity normalizes them (sorting, duplicate and
        # kind rejection, v1 scope policy, UTC microseconds).
        identity_input = SampleGenerationIdentityInput(
            canonical_build_pins=self.canonical_build_pins,
            feature_spec_pins=self.feature_spec_pins,
            label_spec_pins=self.label_spec_pins,
            split_spec_pin=self.split_spec_pin,
            scope=self.scope,
            generation_rule=self.generation_rule,
            dataset_as_of=self.dataset_as_of,
        )
        object.__setattr__(
            self, "canonical_build_pins", identity_input.canonical_build_pins
        )
        object.__setattr__(self, "feature_spec_pins", identity_input.feature_spec_pins)
        object.__setattr__(self, "label_spec_pins", identity_input.label_spec_pins)
        object.__setattr__(self, "split_spec_pin", identity_input.split_spec_pin)
        object.__setattr__(self, "scope", identity_input.scope)
        object.__setattr__(self, "generation_rule", identity_input.generation_rule)
        object.__setattr__(self, "dataset_as_of", identity_input.dataset_as_of)

        # The Generation content ID is recomputed from the carried identity
        # fields; a format-valid but content-mismatching ID fails closed.
        expected_id = sample_generation_content_id(identity_input)
        if self.generation_content_id != expected_id:
            raise SampleGenerationError(
                "generation_content_id does not match the carried identity "
                "fields"
            )

        # Request validation: types, complete label windows, the canonical
        # stable order, duplicate sample keys, scope binding, and exact rule
        # window geometry.
        requests = tuple(self.requests)
        for request in requests:
            if not isinstance(request, PITSampleRequest):
                raise SampleGenerationError(
                    f"requests must contain PITSampleRequest instances, "
                    f"got {type(request).__name__}"
                )
            if request.label_window_start is None or request.label_window_close is None:
                raise SampleGenerationError(
                    "generated requests must always carry a complete label window"
                )
        if len({pit_sample_key(request) for request in requests}) != len(requests):
            raise SampleGenerationError(
                "requests must not contain duplicate pit_sample_key values"
            )
        ordered = tuple(sorted(requests, key=_request_sort_key))
        if ordered != requests:
            raise SampleGenerationError(
                "requests must be in the canonical stable request order"
            )
        object.__setattr__(self, "requests", ordered)
        _validate_request_bindings(
            requests, self.scope, self.generation_rule
        )

        if not isinstance(self.diagnostics, SampleGenerationDiagnostics):
            raise SampleGenerationError(
                f"diagnostics must be a SampleGenerationDiagnostics, "
                f"got {type(self.diagnostics).__name__}"
            )
        # Verifiable model-internal diagnostics bindings. Bar / segment
        # counts that cannot be re-derived from the result fields alone are
        # never fabricated.
        if self.diagnostics.canonical_build_count != len(
            identity_input.canonical_build_pins
        ):
            raise SampleGenerationError(
                "diagnostics.canonical_build_count must equal "
                "len(canonical_build_pins)"
            )
        if self.diagnostics.generated_request_count != len(requests):
            raise SampleGenerationError(
                "diagnostics.generated_request_count must equal len(requests)"
            )
