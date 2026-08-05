"""Strict JSON parsing, canonical serialization, and deterministic semantic
content identity of the v0.6.0 Sample Generation contract (PR-2).

``parse_sample_generation_plan_bytes`` strictly parses one generation-plan
JSON document (UTF-8 without BOM; duplicate JSON keys at any depth, unknown
and missing fields, wrong types, and ``null`` in fields that do not accept
it all fail closed; JSON whitespace and key order never matter) into the
frozen :class:`SampleGenerationPlan`. ``serialize_sample_generation_plan``
regenerates the deterministic canonical JSON of one plan (UTF-8 without
BOM, ``ensure_ascii``, sorted keys, compact separators, exactly one
trailing newline, UTC microsecond timestamps with the explicit ``+00:00``
offset). ``sample_generation_content_id`` is the versioned SHA-256 semantic
content identity of one generation input, computed only over the normalized
canonical build pins, spec pins, scope, generation rule, and
``dataset_as_of`` with the existing versioned canonical encoding
(:func:`market_vault.dataset.encoding.encode_identity`); path inputs,
``output_root``, ``built_at``, ``output_plan_path``, raw JSON bytes, key
order, and filesystem facts never enter it, and it never enters any Dataset
identity.

All failures surface as :class:`SampleGenerationError`; no un-wrapped
``json.JSONDecodeError``, ``UnicodeDecodeError``, ``KeyError``, or
``TypeError`` leaks. This module never reads or writes files, never reads
spec documents or Canonical builds, never loads settings, never accesses
the network, never uses the current time, never constructs a sample
request, and never orchestrates a Dataset build: those responsibilities
belong to PR-3 (generator core) and PR-4 (CLI and build-plan output).
"""

from __future__ import annotations

import codecs
import json
import re
import unicodedata
from datetime import date, datetime, timezone

from .encoding import DatasetError, encode_identity, normalize_utc_datetime, reject_unsafe_text
from .models import DatasetScope, SpecPin
from .sample_generation_models import (
    ANCHOR_RULE_FEATURE_WINDOW_CLOSE,
    ANCHOR_SOURCE_VERIFIED_CANONICAL_BARS,
    CROSS_DAY_POLICY_REJECT,
    SAMPLE_GENERATION_CONTENT_ID_VERSION,
    SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
    SAMPLE_GENERATION_RULE_SCHEMA_VERSION,
    SCOPE_ADJUSTMENT_NONE,
    SampleGenerationError,
    SampleGenerationIdentityInput,
    SampleGenerationPlan,
    SampleGenerationRule,
)

__all__ = [
    "parse_sample_generation_plan_bytes",
    "sample_generation_content_id",
    "serialize_sample_generation_plan",
]

#: The exact root field set of one strict generation-plan JSON document.
_ROOT_FIELDS = frozenset(
    {
        "generation_plan_schema_version",
        "canonical_build_dirs",
        "feature_spec_files",
        "label_spec_files",
        "split_spec_file",
        "scope",
        "generation_rule",
        "dataset_as_of",
        "output_root",
        "built_at",
        "output_plan_path",
    }
)

#: The exact field set of the scope object.
_SCOPE_FIELDS = frozenset(
    {"symbols", "trade_dates", "interval", "adjustment", "requested_session"}
)

#: The exact field set of the generation_rule object.
_RULE_FIELDS = frozenset(
    {
        "rule_schema_version",
        "feature_window_bars",
        "label_window_bars",
        "stride_bars",
        "anchor_source",
        "anchor_rule",
        "cross_day_policy",
    }
)

_STRICT_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Strict JSON reading.
# ---------------------------------------------------------------------------


def _no_duplicate_pairs(pairs) -> dict:
    """``object_pairs_hook`` rejecting duplicate JSON keys at any depth."""
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise SampleGenerationError(
                f"duplicate JSON key {key!r} in generation plan"
            )
        result[key] = value
    return result


def _require_string(value, label: str) -> str:
    if not isinstance(value, str):
        raise SampleGenerationError(f"{label} must be a string, got {type(value).__name__}")
    if not value:
        raise SampleGenerationError(f"{label} must not be empty")
    return value


def _require_string_array(value, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SampleGenerationError(
            f"{label} must be a JSON array, got {type(value).__name__}"
        )
    if not value:
        raise SampleGenerationError(f"{label} must not be empty")
    return tuple(_require_string(item, f"{label} entry") for item in value)


def _require_exact_fields(mapping: dict, allowed: frozenset, path: str) -> None:
    unknown = sorted(key for key in mapping if key not in allowed)
    if unknown:
        raise SampleGenerationError(
            f"unknown field(s) at {path}: {', '.join(unknown)}"
        )
    missing = sorted(allowed - set(mapping))
    if missing:
        raise SampleGenerationError(
            f"missing required field(s) at {path}: {', '.join(missing)}"
        )


def _require_object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise SampleGenerationError(
            f"{label} must be a JSON object, got {type(value).__name__}"
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


def _require_positive_int(value, label: str) -> int:
    """Real positive int; bool and float are never accepted as ints."""
    if type(value) is not int or value <= 0:
        raise SampleGenerationError(
            f"{label} must be a real positive integer, got {value!r}"
        )
    return value


def _require_enum(value, allowed: tuple[str, ...], label: str) -> str:
    text = _require_string(value, label)
    if text not in allowed:
        raise SampleGenerationError(
            f"{label} must be one of {', '.join(allowed)}, got {value!r}"
        )
    return text


def _require_datetime(value, label: str) -> datetime:
    """Timezone-aware ISO datetime, normalized to UTC microseconds.

    Naive datetimes are rejected; the system local timezone is never used.
    """
    text = _require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SampleGenerationError(
            f"{label} must be an ISO 8601 datetime, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise SampleGenerationError(
            f"{label} must be timezone-aware, got a naive value {value!r}"
        )
    try:
        return normalize_utc_datetime(parsed, label)
    except DatasetError as exc:
        raise SampleGenerationError(f"{label}: {exc}") from exc


def _require_nullable_datetime(value, label: str) -> datetime | None:
    if value is None:
        return None
    return _require_datetime(value, label)


# ---------------------------------------------------------------------------
# Nested objects.
# ---------------------------------------------------------------------------


def _normalize_symbol(value, label: str) -> str:
    """One scope symbol pre-normalized for the duplicate check.

    The raw value must be a string free of control characters and reserved
    encoding separators; the normalized form is strip + NFC + uppercase,
    which must not be empty. The final normalization and sorting remain the
    responsibility of the existing :class:`DatasetScope` construction.
    """
    if not isinstance(value, str):
        raise SampleGenerationError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    try:
        reject_unsafe_text(value, label)
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc
    text = unicodedata.normalize("NFC", value).strip().upper()
    if not text:
        raise SampleGenerationError(f"{label} must not be empty")
    return text


def _parse_scope(value) -> DatasetScope:
    mapping = _require_object(value, "scope")
    _require_exact_fields(mapping, _SCOPE_FIELDS, "scope")
    symbols = tuple(
        _normalize_symbol(item, "scope symbols entry")
        for item in _require_string_array(mapping["symbols"], "scope symbols")
    )
    if len(set(symbols)) != len(symbols):
        raise SampleGenerationError(
            "scope symbols must not contain duplicates after normalization"
        )
    trade_dates = tuple(
        _require_date(item, "scope trade_dates entry")
        for item in _require_string_array(mapping["trade_dates"], "scope trade_dates")
    )
    if len(set(trade_dates)) != len(trade_dates):
        raise SampleGenerationError(
            "scope trade_dates must not contain duplicates"
        )
    try:
        scope = DatasetScope(
            symbols=symbols,
            trade_dates=trade_dates,
            interval=_require_string(mapping["interval"], "scope interval"),
            adjustment=_require_string(mapping["adjustment"], "scope adjustment"),
            requested_session=_require_string(
                mapping["requested_session"], "scope requested_session"
            ),
        )
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc
    if scope.adjustment != SCOPE_ADJUSTMENT_NONE:
        raise SampleGenerationError(
            f"v1 generation plans accept only adjustment == "
            f"{SCOPE_ADJUSTMENT_NONE}, got {scope.adjustment!r}"
        )
    return scope


def _parse_generation_rule(value) -> SampleGenerationRule:
    mapping = _require_object(value, "generation_rule")
    _require_exact_fields(mapping, _RULE_FIELDS, "generation_rule")
    try:
        return SampleGenerationRule(
            rule_schema_version=_require_string(
                mapping["rule_schema_version"], "rule_schema_version"
            ),
            feature_window_bars=_require_positive_int(
                mapping["feature_window_bars"], "feature_window_bars"
            ),
            label_window_bars=_require_positive_int(
                mapping["label_window_bars"], "label_window_bars"
            ),
            stride_bars=_require_positive_int(
                mapping["stride_bars"], "stride_bars"
            ),
            anchor_source=_require_enum(
                mapping["anchor_source"],
                (ANCHOR_SOURCE_VERIFIED_CANONICAL_BARS,),
                "anchor_source",
            ),
            anchor_rule=_require_enum(
                mapping["anchor_rule"],
                (ANCHOR_RULE_FEATURE_WINDOW_CLOSE,),
                "anchor_rule",
            ),
            cross_day_policy=_require_enum(
                mapping["cross_day_policy"],
                (CROSS_DAY_POLICY_REJECT,),
                "cross_day_policy",
            ),
        )
    except SampleGenerationError:
        raise
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Public parsing API.
# ---------------------------------------------------------------------------


def parse_sample_generation_plan_bytes(payload: bytes) -> SampleGenerationPlan:
    """Strictly parse one generation-plan JSON document into a frozen
    :class:`SampleGenerationPlan`.

    The payload must be bytes of a single UTF-8 JSON object without BOM;
    duplicate JSON keys are rejected through ``object_pairs_hook``; unknown
    and missing fields fail at every level; bools never substitute for ints;
    strings never substitute for arrays; ``null`` is rejected in every field
    that does not accept it. JSON whitespace and key order never matter, no
    canonical JSON form is required, and the raw plan bytes never enter any
    identity. The parser never reads files, specs, or Canonical builds,
    never loads settings, never accesses the network, and never uses the
    current time.
    """
    if not isinstance(payload, bytes):
        raise SampleGenerationError(
            f"generation plan payload must be bytes, got {type(payload).__name__}"
        )
    if payload.startswith(codecs.BOM_UTF8):
        raise SampleGenerationError("generation plan must not carry a UTF-8 BOM")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SampleGenerationError(
            f"generation plan is not valid UTF-8: {exc}"
        ) from exc
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except json.JSONDecodeError as exc:
        raise SampleGenerationError(
            f"generation plan is not valid JSON: {exc}"
        ) from exc
    root = _require_object(data, "generation plan root")
    _require_exact_fields(root, _ROOT_FIELDS, "generation plan root")
    plan_schema_version = _require_string(
        root["generation_plan_schema_version"], "generation_plan_schema_version"
    )
    if plan_schema_version != SAMPLE_GENERATION_PLAN_SCHEMA_VERSION:
        raise SampleGenerationError(
            f"unsupported generation_plan_schema_version {plan_schema_version!r}; "
            f"only {SAMPLE_GENERATION_PLAN_SCHEMA_VERSION} is accepted"
        )
    try:
        return SampleGenerationPlan(
            generation_plan_schema_version=plan_schema_version,
            canonical_build_dirs=_require_string_array(
                root["canonical_build_dirs"], "canonical_build_dirs"
            ),
            feature_spec_files=_require_string_array(
                root["feature_spec_files"], "feature_spec_files"
            ),
            label_spec_files=_require_string_array(
                root["label_spec_files"], "label_spec_files"
            ),
            split_spec_file=_require_string(root["split_spec_file"], "split_spec_file"),
            scope=_parse_scope(root["scope"]),
            generation_rule=_parse_generation_rule(root["generation_rule"]),
            dataset_as_of=_require_nullable_datetime(
                root["dataset_as_of"], "dataset_as_of"
            ),
            output_root=_require_string(root["output_root"], "output_root"),
            built_at=_require_datetime(root["built_at"], "built_at"),
            output_plan_path=_require_string(
                root["output_plan_path"], "output_plan_path"
            ),
        )
    except SampleGenerationError:
        raise
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Canonical generation-plan serialization.
# ---------------------------------------------------------------------------


def _iso_utc_micros(value: datetime) -> str:
    """UTC microsecond ISO string with the explicit ``+00:00`` offset."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def serialize_sample_generation_plan(plan: SampleGenerationPlan) -> bytes:
    """Deterministic canonical JSON bytes of one generation plan.

    The JSON is regenerated from the frozen model only: UTF-8 without BOM,
    ``ensure_ascii=True``, sorted keys, compact separators, exactly one
    trailing newline, and UTC microsecond timestamps with the explicit
    ``+00:00`` offset (never ``Z``). Arrays use the model's deterministic
    sorted order and the scope is serialized from its normalized result, so
    the same model always serializes byte-identically and
    ``parse_sample_generation_plan_bytes(serialize_sample_generation_plan(
    plan))`` equals the plan field by field. This is the canonical form of
    the generation plan itself; it is not a Dataset build plan, not a
    Dataset artifact, and not an identity.
    """
    if not isinstance(plan, SampleGenerationPlan):
        raise SampleGenerationError(
            f"serialize_sample_generation_plan requires a SampleGenerationPlan, "
            f"got {type(plan).__name__}"
        )
    payload = {
        "generation_plan_schema_version": plan.generation_plan_schema_version,
        "canonical_build_dirs": list(plan.canonical_build_dirs),
        "feature_spec_files": list(plan.feature_spec_files),
        "label_spec_files": list(plan.label_spec_files),
        "split_spec_file": plan.split_spec_file,
        "scope": {
            "symbols": list(plan.scope.symbols),
            "trade_dates": [trade_date.isoformat() for trade_date in plan.scope.trade_dates],
            "interval": plan.scope.interval,
            "adjustment": plan.scope.adjustment,
            "requested_session": plan.scope.requested_session,
        },
        "generation_rule": {
            "rule_schema_version": plan.generation_rule.rule_schema_version,
            "feature_window_bars": plan.generation_rule.feature_window_bars,
            "label_window_bars": plan.generation_rule.label_window_bars,
            "stride_bars": plan.generation_rule.stride_bars,
            "anchor_source": plan.generation_rule.anchor_source,
            "anchor_rule": plan.generation_rule.anchor_rule,
            "cross_day_policy": plan.generation_rule.cross_day_policy,
        },
        "dataset_as_of": (
            _iso_utc_micros(plan.dataset_as_of)
            if plan.dataset_as_of is not None
            else None
        ),
        "output_root": plan.output_root,
        "built_at": _iso_utc_micros(plan.built_at),
        "output_plan_path": plan.output_plan_path,
    }
    return (
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


# ---------------------------------------------------------------------------
# Deterministic semantic content identity.
# ---------------------------------------------------------------------------

#: Domain-separated sub-digest prefixes of the content identity (fixed-length
#: 64-character SHA-256 hex, so the ``\\x1e`` sequence encoding is
#: unambiguous; all strings reaching the encoding are safe text that can
#: never contain the separator).
_CANONICAL_PIN_DIGEST_PREFIX = "sample-generation-canonical-pin"
_SPEC_PIN_DIGEST_PREFIX = "sample-generation-spec-pin"


def _canonical_pin_digest(pin) -> str:
    """Sub-digest of one canonical build pin.

    Only the verified, path-independent ``canonical_build_id`` is bound:
    that identity is already the formal Canonical identity and no path or
    filesystem fact may enter it.
    """
    return encode_identity(
        _CANONICAL_PIN_DIGEST_PREFIX,
        {"canonical_build_id": pin.canonical_build_id},
    )


def _spec_pin_digest(pin: SpecPin) -> str:
    """Sub-digest of one spec pin: kind, name, version, content SHA-256."""
    return encode_identity(
        _SPEC_PIN_DIGEST_PREFIX,
        {
            "kind": pin.kind,
            "name": pin.name,
            "version": pin.version,
            "content_sha256": pin.content_sha256,
        },
    )


def sample_generation_content_id(
    identity_input: SampleGenerationIdentityInput,
) -> str:
    """64-character lowercase SHA-256 of the deterministic semantic content
    of one generation input.

    The identity binds the content-ID version, the generation-plan schema
    version, the generation-rule schema version, the normalized canonical
    build identities (``canonical_build_id``), the normalized Feature /
    Label / Split spec pins (``kind``, ``name``, ``version``,
    ``content_sha256``), the normalized scope, every generation-rule field,
    and the normalized ``dataset_as_of``, all through the existing versioned
    canonical encoding (:func:`market_vault.dataset.encoding.encode_identity`);
    no second generic scalar encoder and no unversioned hashing scheme is
    introduced. Input order never matters (the identity input normalizes its
    sequences deterministically at construction) and equivalent timezone
    representations of the same instant produce the same ID.

    The identity excludes ``canonical_build_dirs``, ``feature_spec_files``,
    ``label_spec_files``, ``split_spec_file``, ``output_root``, ``built_at``,
    ``output_plan_path``, the generation-plan file path, raw JSON bytes,
    JSON whitespace and key order, path order, the machine name, the working
    directory, filesystem separator representation, mtimes, and the current
    time. It identifies only the semantic generation inputs under the
    versioned generation contract; it never enters ``dataset_id``, never
    enters a sample request, and never changes the Canonical or Dataset
    identities.
    """
    if not isinstance(identity_input, SampleGenerationIdentityInput):
        raise SampleGenerationError(
            f"sample_generation_content_id requires a SampleGenerationIdentityInput, "
            f"got {type(identity_input).__name__}"
        )
    scope = identity_input.scope
    rule = identity_input.generation_rule
    # ``rule_schema_version`` binds the versioned generation-rule schema
    # constant: the frozen rule validates it equals
    # ``SAMPLE_GENERATION_RULE_SCHEMA_VERSION`` at construction, so the model
    # value is the constant by construction.
    fields = {
        "version": SAMPLE_GENERATION_CONTENT_ID_VERSION,
        "plan_schema_version": SAMPLE_GENERATION_PLAN_SCHEMA_VERSION,
        "rule_schema_version": rule.rule_schema_version,
        "canonical_build_count": len(identity_input.canonical_build_pins),
        "canonical_build_ids": "\x1e".join(
            _canonical_pin_digest(pin)
            for pin in identity_input.canonical_build_pins
        ),
        "feature_spec_count": len(identity_input.feature_spec_pins),
        "feature_spec_pins": "\x1e".join(
            _spec_pin_digest(pin) for pin in identity_input.feature_spec_pins
        ),
        "label_spec_count": len(identity_input.label_spec_pins),
        "label_spec_pins": "\x1e".join(
            _spec_pin_digest(pin) for pin in identity_input.label_spec_pins
        ),
        "split_spec_pin": _spec_pin_digest(identity_input.split_spec_pin),
        "scope_symbols": "\x1e".join(scope.symbols),
        "scope_trade_dates": "\x1e".join(
            trade_date.isoformat() for trade_date in scope.trade_dates
        ),
        "scope_interval": scope.interval,
        "scope_adjustment": scope.adjustment,
        "scope_requested_session": scope.requested_session,
        "feature_window_bars": rule.feature_window_bars,
        "label_window_bars": rule.label_window_bars,
        "stride_bars": rule.stride_bars,
        "anchor_source": rule.anchor_source,
        "anchor_rule": rule.anchor_rule,
        "cross_day_policy": rule.cross_day_policy,
        "dataset_as_of": identity_input.dataset_as_of,
    }
    try:
        return encode_identity(SAMPLE_GENERATION_CONTENT_ID_VERSION, fields)
    except DatasetError as exc:
        raise SampleGenerationError(str(exc)) from exc
