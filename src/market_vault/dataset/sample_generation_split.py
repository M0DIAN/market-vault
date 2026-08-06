"""Shared strict split-spec loading authority of the v0.6.0 Sample
Generation contract (PR-4).

This module is the single strict JSON reader of one split-spec document into
the formal :class:`ChronologicalSplitSpec`. It is extracted verbatim from the
PR-3 generator core so that both the generator core
(:func:`market_vault.dataset.sample_generation_core.generate_sample_requests`)
and the PR-4 build-plan writer (the Sample Generation CLI) consume exactly
the same loader: the strict UTF-8 rule, the BOM rejection, the
any-depth duplicate-key rejection, the exact field set, the strict
``YYYY-MM-DD`` dates, and the formal :class:`ChronologicalSplitSpec`
validation never exist in two places. No second split JSON parser and no
second split identity is introduced anywhere.

All failures surface exactly as before the extraction: strict JSON and field
violations raise :class:`SampleGenerationError` with the unchanged messages,
and the formal model validation raises :class:`SplitValidationError` from
:class:`ChronologicalSplitSpec` construction. This module never reads the
current time, never loads settings, and never accesses the network.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .encoding import DatasetError
from .sample_generation_models import SampleGenerationError
from .split_models import (
    ChronologicalSplitSpec,
    SplitValidationError,
)

__all__ = [
    "load_sample_generation_split_spec",
]

#: The exact field set of one strict split-spec JSON document. It mirrors
#: the formal :class:`ChronologicalSplitSpec` model exactly; no second split
#: identity or second schema is introduced.
_SPLIT_FIELDS = frozenset(
    {
        "spec_schema_version",
        "name",
        "version",
        "boundary_timezone",
        "train_end_date",
        "validation_end_date",
        "test_end_date",
        "assignment_rule",
        "purge_rule",
        "incomplete_label_policy",
        "out_of_range_policy",
    }
)

_STRICT_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _no_duplicate_pairs(pairs) -> dict:
    """``object_pairs_hook`` rejecting duplicate JSON keys at any depth."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise SampleGenerationError(
                f"duplicate JSON key {key!r} in split spec"
            )
        result[key] = value
    return result


def _require_string(value, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SampleGenerationError(
            f"{label} must be a non-empty string, got {value!r}"
        )
    return value


def _require_date(value, label: str) -> date:
    text = _require_string(value, label)
    if not _STRICT_ISO_DATE_RE.fullmatch(text):
        raise SampleGenerationError(
            f"{label} must be a strict ISO YYYY-MM-DD string, got {value!r}"
        )
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SampleGenerationError(
            f"{label} must be a valid calendar date, got {value!r}"
        ) from exc


def load_sample_generation_split_spec(path: Path) -> ChronologicalSplitSpec:
    """Strictly read one split-spec JSON document into the formal
    :class:`ChronologicalSplitSpec`.

    The document must be a single UTF-8 JSON object without BOM; duplicate
    keys fail at any depth; the root must be an object with exactly the
    formal split-spec field set; unknown and missing fields fail; dates are
    strict ``YYYY-MM-DD``. Final semantics (schema version, timezone,
    boundary ordering, fixed rule values) are validated by the formal
    :class:`ChronologicalSplitSpec` construction. The split pin is produced
    by the existing :func:`chronological_split_spec_pin`; no second split
    identity exists. Both the Sample Generator core (PR-3) and the Sample
    Generation CLI build-plan writer (PR-4) consume exactly this loader.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        raise SampleGenerationError(f"cannot read split spec file {path}: {exc}") from exc
    if text.startswith("﻿"):
        raise SampleGenerationError("split spec file must not carry a UTF-8 BOM")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except json.JSONDecodeError as exc:
        raise SampleGenerationError(f"split spec is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SampleGenerationError(
            f"split spec root must be a JSON object, got {type(data).__name__}"
        )
    unknown = sorted(key for key in data if key not in _SPLIT_FIELDS)
    if unknown:
        raise SampleGenerationError(
            f"unknown field(s) in split spec: {', '.join(unknown)}"
        )
    missing = sorted(_SPLIT_FIELDS - set(data))
    if missing:
        raise SampleGenerationError(
            f"missing required field(s) in split spec: {', '.join(missing)}"
        )
    try:
        spec = ChronologicalSplitSpec(
            spec_schema_version=_require_string(
                data["spec_schema_version"], "split spec spec_schema_version"
            ),
            name=_require_string(data["name"], "split spec name"),
            version=_require_string(data["version"], "split spec version"),
            boundary_timezone=_require_string(
                data["boundary_timezone"], "split spec boundary_timezone"
            ),
            train_end_date=_require_date(
                data["train_end_date"], "split spec train_end_date"
            ),
            validation_end_date=_require_date(
                data["validation_end_date"], "split spec validation_end_date"
            ),
            test_end_date=_require_date(
                data["test_end_date"], "split spec test_end_date"
            ),
            assignment_rule=_require_string(
                data["assignment_rule"], "split spec assignment_rule"
            ),
            purge_rule=_require_string(data["purge_rule"], "split spec purge_rule"),
            incomplete_label_policy=_require_string(
                data["incomplete_label_policy"], "split spec incomplete_label_policy"
            ),
            out_of_range_policy=_require_string(
                data["out_of_range_policy"], "split spec out_of_range_policy"
            ),
        )
    except SplitValidationError:
        raise
    except (DatasetError, TypeError, ValueError, KeyError) as exc:
        raise SampleGenerationError(f"invalid split spec: {exc}") from exc
    return spec
