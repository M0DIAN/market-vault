"""Pure ordinary Dataset build-plan serializer of the v0.6.0 Sample
Generation CLI (PR-4).

:func:`serialize_generated_dataset_build_plan` deterministically renders one
frozen :class:`SampleGenerationPlan` plus one frozen
:class:`SampleGenerationResult` into the canonical JSON bytes of an ordinary
``market-vault-dataset-build-plan-v1`` document, with the full formal
:class:`ChronologicalSplitSpec` embedded as the ``split_spec`` object.

The function is pure and fail-closed:

1. every input must be the formal model type;
2. the embedded ``split_spec`` must carry exactly the result's
   ``split_spec_pin`` (``chronological_split_spec_pin(split_spec) ==
   result.split_spec_pin``), so the writer can never embed a split spec
   that differs from the one the generator core validated;
3. the output root carries exactly the existing build-plan field set
   (``plan_schema_version``, ``canonical_build_dirs``,
   ``feature_spec_files``, ``label_spec_files``, ``requests``, ``scope``,
   ``split_spec``, ``dataset_as_of``, ``output_root``, ``built_at``) and
   nothing else: no ``generation_content_id``, no
   ``generator_core_version``, no ``generation_rule``, no
   ``output_plan_path``, no Sample Generation CLI version, no ``path_base``,
   no ``cwd``, no machine, no mtime, no diagnostics;
4. paths are copied verbatim from the plan (relative paths stay relative —
   the Sample Generation contract requires the copied strings to remain
   unchanged, and the CLI enforces the same-parent output policy separately);
5. instants serialize as UTC microsecond ISO strings with the explicit
   ``+00:00`` offset (never ``Z``); dates serialize as strict
   ``YYYY-MM-DD``;
6. the bytes are UTF-8 without BOM, ``ensure_ascii=True``,
   ``sort_keys=True``, ``separators=(",", ":")``, no indent, exactly one
   trailing newline — the same normalized model always serializes
   byte-identically.

This module never reads a file, never writes a file, never reads the
current time, never uses path metadata, never calls the generator core,
never calls any Dataset build / orchestration / materialization entry, and
never constructs a second build-plan validator. All failures surface as
:class:`SampleGenerationCLIError`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .cli_models import DATASET_BUILD_PLAN_SCHEMA_VERSION
from .sample_generation_cli_models import SampleGenerationCLIError
from .sample_generation_core_models import SampleGenerationResult
from .sample_generation_models import SampleGenerationPlan
from .split_models import (
    ChronologicalSplitSpec,
    chronological_split_spec_pin,
)

__all__ = [
    "serialize_generated_dataset_build_plan",
]


def _iso_utc_micros(value: datetime) -> str:
    """UTC microsecond ISO string with the explicit ``+00:00`` offset
    (never ``Z``); naive datetimes can never reach this function."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise SampleGenerationCLIError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


def _request_payload(request) -> dict:
    """One generated request in the exact build-plan request field set.

    Generated requests always carry a complete label window (enforced by
    the formal :class:`SampleGenerationResult`); a label-window gap fails
    closed here rather than silently serializing ``null``.
    """
    if request.label_window_start is None or request.label_window_close is None:
        raise SampleGenerationCLIError(
            "generated requests must always carry a complete label window"
        )
    return {
        "code": request.code,
        "interval": request.interval,
        "adjustment": request.adjustment,
        "requested_session": request.requested_session,
        "anchor_market_calendar_date": request.anchor_market_calendar_date.isoformat(),
        "feature_window_start": _iso_utc_micros(request.feature_window_start),
        "feature_window_close": _iso_utc_micros(request.feature_window_close),
        "label_window_start": _iso_utc_micros(request.label_window_start),
        "label_window_close": _iso_utc_micros(request.label_window_close),
    }


def _scope_payload(scope) -> dict:
    """The normalized scope of the result (never re-derived)."""
    return {
        "symbols": list(scope.symbols),
        "trade_dates": [trade_date.isoformat() for trade_date in scope.trade_dates],
        "interval": scope.interval,
        "adjustment": scope.adjustment,
        "requested_session": scope.requested_session,
    }


def _split_spec_payload(spec: ChronologicalSplitSpec) -> dict:
    """The full formal :class:`ChronologicalSplitSpec` object embedded into
    the ordinary build plan (dates as strict ``YYYY-MM-DD``)."""
    return {
        "spec_schema_version": spec.spec_schema_version,
        "name": spec.name,
        "version": spec.version,
        "boundary_timezone": spec.boundary_timezone,
        "train_end_date": spec.train_end_date.isoformat(),
        "validation_end_date": spec.validation_end_date.isoformat(),
        "test_end_date": spec.test_end_date.isoformat(),
        "assignment_rule": spec.assignment_rule,
        "purge_rule": spec.purge_rule,
        "incomplete_label_policy": spec.incomplete_label_policy,
        "out_of_range_policy": spec.out_of_range_policy,
    }


def serialize_generated_dataset_build_plan(
    plan: SampleGenerationPlan,
    result: SampleGenerationResult,
    *,
    split_spec: ChronologicalSplitSpec,
) -> bytes:
    """Deterministic ordinary Dataset build-plan bytes of one generation.

    The output root carries exactly the existing
    ``market-vault-dataset-build-plan-v1`` field set:
    ``plan_schema_version`` (= :data:`DATASET_BUILD_PLAN_SCHEMA_VERSION`),
    ``canonical_build_dirs`` / ``feature_spec_files`` / ``label_spec_files``
    (copied verbatim from the plan in the model's deterministic sorted
    order), ``requests`` (the result's canonical stable request order),
    ``scope`` (the result's normalized scope), ``split_spec`` (the full
    formal :class:`ChronologicalSplitSpec`, pinned to
    ``result.split_spec_pin``), ``dataset_as_of`` (the result's normalized
    value), ``output_root`` (copied verbatim from the plan), and
    ``built_at`` (the plan's execution-record instant). The generated bytes
    are accepted by the existing strict
    :func:`market_vault.dataset.cli.parse_build_plan_bytes` — that parser,
    not this serializer, is the format authority of the ordinary build plan.
    """
    _require_instance(plan, SampleGenerationPlan, "plan")
    _require_instance(result, SampleGenerationResult, "result")
    _require_instance(split_spec, ChronologicalSplitSpec, "split_spec")
    if chronological_split_spec_pin(split_spec) != result.split_spec_pin:
        raise SampleGenerationCLIError(
            "split_spec does not match the result split_spec_pin"
        )
    payload = {
        "plan_schema_version": DATASET_BUILD_PLAN_SCHEMA_VERSION,
        "canonical_build_dirs": list(plan.canonical_build_dirs),
        "feature_spec_files": list(plan.feature_spec_files),
        "label_spec_files": list(plan.label_spec_files),
        "requests": [_request_payload(request) for request in result.requests],
        "scope": _scope_payload(result.scope),
        "split_spec": _split_spec_payload(split_spec),
        "dataset_as_of": (
            _iso_utc_micros(result.dataset_as_of)
            if result.dataset_as_of is not None
            else None
        ),
        "output_root": plan.output_root,
        "built_at": _iso_utc_micros(plan.built_at),
    }
    return (
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )
