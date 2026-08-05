"""Frozen models and pure derivation functions of the deterministic Dataset
orchestration contract (v0.5.0 PR-5).

This module defines the pure in-memory Dataset orchestration core's models
and derivation functions:

- the unified fail-closed error :class:`DatasetOrchestrationError` (a
  subclass of :class:`DatasetError`);
- the version constants of the orchestration contract, the only accepted
  dataset kind (SUPERVISED), the fixed physical row-order code, and the
  four fixed Completion reason codes;
- :func:`dataset_orchestration_schema` — the public authoritative logical
  Dataset schema derivation from Feature/Label specs and the conditional
  ``dataset_as_of`` field;
- the private derivation functions the orchestration entry and the result
  model share (spec normalization, PIT / Feature / Label sample binding,
  split-sample construction, ImplementationPin merging, completion
  summary, final logical rows, diagnostics), so construction and
  re-verification can never drift;
- :class:`DatasetOrchestrationDiagnostics` — the deterministic execution
  counts with their fixed matrix invariants;
- :class:`DatasetOrchestrationResult` — the frozen result model that
  independently re-verifies every invariant at construction (fail closed).

No file is written, no Dataset directory is created, no Parquet is
produced, no DatasetManifest is built, no split or purge rule is
reimplemented, nothing touches OpenD or the network, and no current time,
random value, filesystem mtime, absolute path, or local timezone ever
enters an identity or a result. The physical row order is fixed
(``code``, ``feature_window_close``, ``sample_key``) so PR-6 receives a
stable input, while ``logical_dataset_content_id`` stays
row-order-independent per the v0.4 contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .content import dataset_schema_id, logical_dataset_content_id
from .encoding import DatasetError, normalize_utc_datetime
from .feature_models import (
    FEATURE_VALUE_STATUS_COMPLETE,
    FEATURE_VALUE_STATUS_EXCLUDED,
    FeatureExecutionResult,
)
from .identity import dataset_id
from .label_models import LabelExecutionResult
from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    SERIALIZATION_FORMAT_PARQUET,
    SERIALIZATION_FORMAT_VERSION_PARQUET,
    STATUS_COMPLETE,
    STATUS_EMPTY,
    CompletionEntry,
    CompletionSummary,
    DatasetField,
    DatasetIdentityInput,
    DatasetSchema,
    DatasetScope,
    ImplementationPin,
    SpecPin,
)
from .pit_models import PITAssemblyResult
from .spec_models import FeatureSpec, LabelSpec
from .specs import feature_label_spec_pin
from .split_models import (
    LABEL_STATUS_COMPLETE,
    LABEL_STATUS_INCOMPLETE,
    SPLIT_STATUS_ASSIGNED,
    SPLIT_STATUS_EXCLUDED,
    SPLIT_STATUS_PURGED,
    ChronologicalSplitResult,
    ChronologicalSplitSample,
    ChronologicalSplitSpec,
    chronological_split_spec_pin,
)

__all__ = [
    "DATASET_COMPLETION_REASON_FEATURE_EXCLUDED",
    "DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE",
    "DATASET_COMPLETION_REASON_LABEL_INCOMPLETE",
    "DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST",
    "DATASET_KIND_SUPERVISED",
    "DATASET_ORCHESTRATION_CONTRACT_VERSION",
    "DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY",
    "DatasetOrchestrationDiagnostics",
    "DatasetOrchestrationError",
    "DatasetOrchestrationResult",
    "dataset_orchestration_schema",
]

#: Version of the Dataset orchestration contract itself. It is carried on
#: every :class:`DatasetOrchestrationResult` and never enters any existing
#: identity; no new identity input field is introduced.
DATASET_ORCHESTRATION_CONTRACT_VERSION = "market-vault-dataset-orchestration-v1"

#: The only Dataset kind this orchestration executes.
DATASET_KIND_SUPERVISED = "SUPERVISED"

#: Fixed physical row order code of the final logical rows: ``code`` ASC,
#: then ``feature_window_close`` ASC, then ``sample_key`` ASC. The physical
#: sort exists for stable reading / Parquet output and never modifies any
#: identity algorithm.
DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY = "CODE_FEATURE_CLOSE_SAMPLE_KEY"

#: Fixed Completion reason codes (machine codes, never free-form text).
DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST = "NO_SAMPLE_REQUEST"
DATASET_COMPLETION_REASON_FEATURE_EXCLUDED = "FEATURE_EXCLUDED"
DATASET_COMPLETION_REASON_LABEL_INCOMPLETE = "LABEL_INCOMPLETE"
DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE = (
    "FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE"
)

#: Fixed logical Dataset schema field names. Feature and Label output names
#: may never collide with any of these reserved names.
_SAMPLE_IDENTITY_FIELD_NAMES = ("code", "sample_key", "sample_version_id")
_TIMING_FIELD_NAMES = (
    "feature_window_close",
    "actual_label_end_time",
    "label_status",
    "dataset_as_of",
)
_SPLIT_FIELD_NAMES = (
    "feature_window_close_date",
    "nominal_split",
    "final_split",
    "assignment_status",
    "reason_code",
    "purge_boundary",
)
_RESERVED_FIELD_NAMES = frozenset(
    _SAMPLE_IDENTITY_FIELD_NAMES + _TIMING_FIELD_NAMES + _SPLIT_FIELD_NAMES
)


class DatasetOrchestrationError(DatasetError):
    """Structured fail-closed failure of the Dataset orchestration layer.

    Raised for invalid orchestration inputs, scope/request inconsistencies,
    authoritative schema mismatches, PIT / Feature / Label binding
    violations, split handoff violations, completion inconsistencies, and
    result-model inconsistencies. Every documented validation failure of the
    underlying layers (``PITAssemblyError``, ``FeatureExecutionError``,
    ``LabelExecutionError``, ``SplitValidationError``, ``DatasetError``, and
    the documented input ``TypeError`` / ``ValueError`` / ``KeyError``) is
    wrapped here with its ``__cause__`` preserved. There is no "warn and
    continue" path and no partial result is ever returned.
    """


def _as_orchestration_error(exc, context: str) -> None:
    """Convert a documented validation-type exception to
    :class:`DatasetOrchestrationError`.

    A :class:`DatasetOrchestrationError` passes through unchanged (never
    double-wrapped); the contract-listed validation exceptions
    (``DatasetError`` and its layer subclasses, ``TypeError``, ``ValueError``,
    ``KeyError``) are converted with a context prefix and their ``__cause__``
    preserved. Broad ``except Exception`` is never used: programming errors
    are not hidden, only the documented validation failures are converted.
    """
    if isinstance(exc, DatasetOrchestrationError):
        raise exc
    if isinstance(exc, (DatasetError, TypeError, ValueError, KeyError)):
        raise DatasetOrchestrationError(f"{context}: {exc}") from exc
    raise exc


def _require_instance(value, cls: type, label: str):
    if not isinstance(value, cls):
        raise DatasetOrchestrationError(
            f"{label} must be a {cls.__name__}, got {type(value).__name__}"
        )
    return value


def _require_non_negative_int(value, label: str) -> None:
    if type(value) is not int or value < 0:
        raise DatasetOrchestrationError(
            f"{label} must be a non-negative real integer"
        )


def _normalize_specs(values, expected_cls: type, label: str) -> tuple:
    """Tuple-enforced, order-insensitive, duplicate-free spec normalization.

    Every item must be an instance of ``expected_cls`` (a LabelSpec in a
    Feature slot and vice versa fails closed); the tuple is deterministically
    sorted by the stable SpecPin key ``(kind, name, version, content_sha256)``;
    two specs with the same name fail (even when their content hashes
    differ).
    """
    try:
        items = tuple(values)
    except (TypeError, ValueError) as exc:
        raise DatasetOrchestrationError(
            f"{label} must be an iterable of {expected_cls.__name__}"
        ) from exc
    for item in items:
        if not isinstance(item, expected_cls):
            raise DatasetOrchestrationError(
                f"{label} may only contain {expected_cls.__name__} instances, "
                f"got {type(item).__name__}"
            )
    keyed = sorted(
        ((feature_label_spec_pin(item), item) for item in items),
        key=lambda pair: (
            pair[0].kind,
            pair[0].name,
            pair[0].version,
            pair[0].content_sha256,
        ),
    )
    for previous, current in zip(keyed, keyed[1:]):
        if previous[1].name == current[1].name:
            raise DatasetOrchestrationError(
                f"duplicate spec name {current[1].name!r} in {label}"
            )
    return tuple(item for _, item in keyed)


def _derive_schema(
    feature_specs: tuple[FeatureSpec, ...],
    label_specs: tuple[LabelSpec, ...],
    *,
    include_dataset_as_of: bool,
) -> DatasetSchema:
    """Authoritative logical Dataset schema over normalized spec tuples.

    Fixed field order: sample identity (code, sample_key,
    sample_version_id), timing facts (feature_window_close,
    actual_label_end_time, label_status, and dataset_as_of only when
    enabled), Feature outputs in stable SpecPin order (non-nullable),
    Label outputs in stable SpecPin order (nullable=true by contract), and
    the split assignment fields. Feature and Label output names must not
    collide with each other or with the reserved fixed field names.
    """
    if type(include_dataset_as_of) is not bool:
        raise DatasetOrchestrationError(
            "include_dataset_as_of must be a real bool"
        )
    fields: list[DatasetField] = []
    for name, logical_type, nullable in (
        ("code", "string", False),
        ("sample_key", "string", False),
        ("sample_version_id", "string", False),
        ("feature_window_close", "timestamp_us_utc", False),
        ("actual_label_end_time", "timestamp_us_utc", True),
        ("label_status", "string", False),
    ):
        fields.append(DatasetField(name, logical_type, nullable=nullable))
    if include_dataset_as_of:
        fields.append(
            DatasetField("dataset_as_of", "timestamp_us_utc", nullable=False)
        )
    seen_names = {field.name for field in fields}
    for spec in feature_specs:
        if spec.output.name in seen_names:
            raise DatasetOrchestrationError(
                f"Feature output name {spec.output.name!r} collides with a "
                "reserved or already-declared Dataset field"
            )
        if spec.output.nullable is not False:
            raise DatasetOrchestrationError(
                f"Feature spec {spec.name!r} output must be non-nullable; "
                "only Feature COMPLETE samples enter the final rows, so no "
                "null Feature field is ever needed"
            )
        seen_names.add(spec.output.name)
        fields.append(
            DatasetField(
                spec.output.name, spec.output.logical_type, nullable=False
            )
        )
    for spec in label_specs:
        if spec.output.name in seen_names:
            raise DatasetOrchestrationError(
                f"Label output name {spec.output.name!r} collides with a "
                "reserved or already-declared Dataset field"
            )
        seen_names.add(spec.output.name)
        fields.append(
            DatasetField(
                spec.output.name,
                spec.output.logical_type,
                nullable=True,
            )
        )
    for name, logical_type, nullable in (
        ("feature_window_close_date", "date32", False),
        ("nominal_split", "string", True),
        ("final_split", "string", True),
        ("assignment_status", "string", False),
        ("reason_code", "string", True),
        ("purge_boundary", "timestamp_us_utc", True),
    ):
        fields.append(DatasetField(name, logical_type, nullable=nullable))
    return DatasetSchema(tuple(fields))


def dataset_orchestration_schema(
    feature_specs, label_specs, *, include_dataset_as_of: bool
) -> DatasetSchema:
    """Public authoritative logical Dataset schema of one supervised build.

    ``feature_specs`` and ``label_specs`` are order-insensitive, must be
    non-empty, and may contain only FeatureSpec / LabelSpec instances
    respectively (a LabelSpec in a Feature slot and vice versa fails
    closed). Duplicate spec names, cross-kind output name collisions, and
    collisions with the reserved fixed fields (sample identity, timing, and
    split assignment names) fail. Feature outputs are non-nullable (only
    Feature COMPLETE samples enter the final rows); Label outputs are
    ``nullable=true`` by explicit contract so a Feature COMPLETE sample with
    an INCOMPLETE Label stays as an audit row with true nulls. When
    ``include_dataset_as_of`` is false the schema carries no
    ``dataset_as_of`` field at all. All failures raise
    :class:`DatasetOrchestrationError`.
    """
    feature_items = _normalize_specs(feature_specs, FeatureSpec, "feature_specs")
    label_items = _normalize_specs(label_specs, LabelSpec, "label_specs")
    if not feature_items:
        raise DatasetOrchestrationError(
            "feature_specs must contain at least one FeatureSpec"
        )
    if not label_items:
        raise DatasetOrchestrationError(
            "label_specs must contain at least one LabelSpec"
        )
    try:
        return _derive_schema(
            feature_items, label_items, include_dataset_as_of=include_dataset_as_of
        )
    except DatasetError as exc:
        raise DatasetOrchestrationError(str(exc)) from exc


def _spec_pin_keys(specs) -> tuple[SpecPin, ...]:
    """The stable SpecPin tuple of a normalized spec tuple, in the same
    order (``(kind, name, version, content_sha256)``)."""
    return tuple(feature_label_spec_pin(spec) for spec in specs)


def _verify_sample_binding(
    pit_result: PITAssemblyResult,
    feature_result: FeatureExecutionResult,
    label_result: LabelExecutionResult,
    dataset_as_of,
) -> None:
    """Strict PIT / Feature / Label sample binding.

    The three result layers must carry exactly the same ``sample_key`` set;
    for every key, ``sample_version_id``, ``code``, and
    ``feature_window_close`` must be identical across the layers, and the
    PIT sample's ``dataset_as_of`` must equal the orchestration's normalized
    cutoff. No layer may miss, add, replace, or mutate a sample; ``code`` is
    never recovered by parsing ``sample_key``. Any inconsistency fails
    closed before any row, completion, or identity is generated.
    """
    pit_by_key = {sample.sample_key: sample for sample in pit_result.samples}
    feature_by_key = {
        sample.sample_key: sample for sample in feature_result.samples
    }
    label_by_key = {
        sample.sample_key: sample for sample in label_result.samples
    }
    if (
        set(pit_by_key) != set(feature_by_key)
        or set(feature_by_key) != set(label_by_key)
    ):
        raise DatasetOrchestrationError(
            "PIT / Feature / Label sample sets must carry exactly the same "
            f"sample_keys: pit has {len(pit_by_key)}, feature has "
            f"{len(feature_by_key)}, label has {len(label_by_key)}; missing, "
            "extra, or substituted samples fail closed"
        )
    for key in sorted(pit_by_key):
        pit = pit_by_key[key]
        feature = feature_by_key[key]
        label = label_by_key[key]
        if (
            feature.sample_version_id != pit.sample_version_id
            or label.sample_version_id != pit.sample_version_id
        ):
            raise DatasetOrchestrationError(
                f"sample {key} has inconsistent sample_version_id across "
                "PIT / Feature / Label results"
            )
        if (
            feature.code != pit.request.code
            or label.code != pit.request.code
        ):
            raise DatasetOrchestrationError(
                f"sample {key} has an inconsistent code across PIT / "
                "Feature / Label results; code is never recovered by "
                "parsing sample_key"
            )
        if (
            feature.feature_window_close != pit.request.feature_window_close
            or label.feature_window_close != pit.request.feature_window_close
        ):
            raise DatasetOrchestrationError(
                f"sample {key} has an inconsistent feature_window_close "
                "across PIT / Feature / Label results"
            )
        if pit.dataset_as_of != dataset_as_of:
            raise DatasetOrchestrationError(
                f"sample {key} PIT dataset_as_of {pit.dataset_as_of!r} must "
                f"equal the orchestration dataset_as_of {dataset_as_of!r}"
            )


def _build_split_samples(
    feature_result: FeatureExecutionResult,
    label_result: LabelExecutionResult,
) -> tuple[ChronologicalSplitSample, ...]:
    """Explicit ChronologicalSplitSample construction for every Feature
    COMPLETE sample.

    ``label_status`` and ``actual_label_end_time`` are taken from the
    same-key Label sample result — never inferred, never derived from a
    nominal horizon, never replaced by a label-window close or a target
    event time. Feature EXCLUDED samples never enter the split input.
    """
    label_by_key = {
        sample.sample_key: sample for sample in label_result.samples
    }
    samples = []
    for feature in feature_result.samples:
        if feature.status != FEATURE_VALUE_STATUS_COMPLETE:
            continue
        label = label_by_key[feature.sample_key]
        samples.append(
            ChronologicalSplitSample(
                sample_key=feature.sample_key,
                sample_version_id=feature.sample_version_id,
                feature_window_close=feature.feature_window_close,
                label_status=label.status,
                actual_label_end_time=label.actual_label_end_time,
            )
        )
    return tuple(samples)


def _merge_implementation_pins(
    feature_result: FeatureExecutionResult,
    label_result: LabelExecutionResult,
) -> tuple[ImplementationPin, ...]:
    """Deterministic merge of Feature and Label ImplementationPins.

    Only actually resolved implementation pins are merged; identical pins
    deduplicate deterministically; two pins with the same ``(name, version)``
    identity but different content hashes fail closed; content hashes must be
    non-null. No orchestration pseudo-pin, splitter pin, or PIT assembler pin
    is ever added.
    """
    merged: dict[tuple[str, str], ImplementationPin] = {}
    for pin in (
        *feature_result.implementation_pins,
        *label_result.implementation_pins,
    ):
        if pin.content_sha256 is None:
            raise DatasetOrchestrationError(
                f"implementation pin {pin.name!r} must carry a non-null "
                "content hash"
            )
        existing = merged.get((pin.name, pin.version))
        if existing is None:
            merged[(pin.name, pin.version)] = pin
        elif existing != pin:
            raise DatasetOrchestrationError(
                f"implementation pin identity {(pin.name, pin.version)} has "
                "conflicting content hashes across Feature and Label "
                "execution; identical pins deduplicate, conflicting pins fail"
            )
    return tuple(
        sorted(
            merged.values(),
            key=lambda pin: (pin.name, pin.version, pin.content_sha256),
        )
    )


def _build_completion(
    scope: DatasetScope,
    pit_result: PITAssemblyResult,
    feature_result: FeatureExecutionResult,
    label_result: LabelExecutionResult,
) -> CompletionSummary:
    """Scope-wide CompletionSummary over the full ``symbols x trade_dates``
    Cartesian product.

    Request ownership is keyed by ``(PITSample.request.code,
    PITSample.request.anchor_market_calendar_date)``. A key with no request /
    sample is MISSING with ``NO_SAMPLE_REQUEST``; any Feature EXCLUDED or any
    Label INCOMPLETE under a key makes the whole key INCOMPLETE with the
    matching fixed reason code; split ASSIGNED / PURGED / EXCLUDED states
    never change completion. Completion describes data-computation
    completeness, never training eligibility.
    """
    feature_by_key = {
        sample.sample_key: sample for sample in feature_result.samples
    }
    label_by_key = {
        sample.sample_key: sample for sample in label_result.samples
    }
    samples_by_ownership: dict[tuple[str, date], list] = {}
    for sample in pit_result.samples:
        ownership = (
            sample.request.code,
            sample.request.anchor_market_calendar_date,
        )
        samples_by_ownership.setdefault(ownership, []).append(sample)

    entries = []
    for code in scope.symbols:
        for trade_date in scope.trade_dates:
            ownership = (code, trade_date)
            key_samples = samples_by_ownership.get(ownership, ())
            if not key_samples:
                entries.append(
                    CompletionEntry(
                        code,
                        trade_date,
                        "MISSING",
                        DATASET_COMPLETION_REASON_NO_SAMPLE_REQUEST,
                    )
                )
                continue
            feature_excluded = any(
                feature_by_key[sample.sample_key].status
                == FEATURE_VALUE_STATUS_EXCLUDED
                for sample in key_samples
            )
            label_incomplete = any(
                label_by_key[sample.sample_key].status
                == LABEL_STATUS_INCOMPLETE
                for sample in key_samples
            )
            if feature_excluded and label_incomplete:
                entries.append(
                    CompletionEntry(
                        code,
                        trade_date,
                        "INCOMPLETE",
                        DATASET_COMPLETION_REASON_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE,
                    )
                )
            elif feature_excluded:
                entries.append(
                    CompletionEntry(
                        code,
                        trade_date,
                        "INCOMPLETE",
                        DATASET_COMPLETION_REASON_FEATURE_EXCLUDED,
                    )
                )
            elif label_incomplete:
                entries.append(
                    CompletionEntry(
                        code,
                        trade_date,
                        "INCOMPLETE",
                        DATASET_COMPLETION_REASON_LABEL_INCOMPLETE,
                    )
                )
            else:
                entries.append(
                    CompletionEntry(code, trade_date, "COMPLETE", None)
                )
    return CompletionSummary(
        complete_count=sum(
            1 for entry in entries if entry.status == "COMPLETE"
        ),
        incomplete_count=sum(
            1 for entry in entries if entry.status == "INCOMPLETE"
        ),
        missing_count=sum(
            1 for entry in entries if entry.status == "MISSING"
        ),
        entries=tuple(entries),
    )


def _row_mappings(
    rows: tuple[tuple[object, ...], ...], schema: DatasetSchema
) -> tuple[dict[str, object], ...]:
    """Temporary schema-ordered row mappings for content identity only.

    The returned dicts are ephemeral: they never become identity caches or
    internal mutable state of any result model.
    """
    names = tuple(field.name for field in schema.fields)
    return tuple(dict(zip(names, row)) for row in rows)


def _build_logical_rows(
    pit_result: PITAssemblyResult,
    feature_result: FeatureExecutionResult,
    label_result: LabelExecutionResult,
    split_result: ChronologicalSplitResult,
    schema: DatasetSchema,
) -> tuple[tuple[object, ...], ...]:
    """Final logical Dataset rows over every Feature COMPLETE sample.

    One immutable tuple per sample in the authoritative schema field order:
    sample identity (``code``, ``sample_key``, ``sample_version_id``),
    timing facts (``feature_window_close``, ``actual_label_end_time``,
    ``label_status``, and ``dataset_as_of`` when the schema carries it),
    Feature values copied from the Feature value results, Label values
    copied when COMPLETE and true ``None`` when INCOMPLETE, and the split
    assignment fields copied exactly from the
    :class:`ChronologicalSplitAssignment`. Feature values are never
    re-run, re-rounded, reformatted, or float-converted; Feature EXCLUDED
    samples produce no row; NaN / Infinity never enter a row. Rows are then
    fixed-sorted by ``code``, ``feature_window_close``, ``sample_key``.
    """
    field_indexes = {
        field.name: index for index, field in enumerate(schema.fields)
    }
    include_dataset_as_of = "dataset_as_of" in field_indexes
    pit_by_key = {sample.sample_key: sample for sample in pit_result.samples}
    label_by_key = {
        sample.sample_key: sample for sample in label_result.samples
    }
    split_by_key = {
        assignment.sample_key: assignment for assignment in split_result.assignments
    }
    rows: list[tuple[object, ...]] = []
    for feature in feature_result.samples:
        if feature.status != FEATURE_VALUE_STATUS_COMPLETE:
            continue
        label = label_by_key.get(feature.sample_key)
        assignment = split_by_key.get(feature.sample_key)
        if label is None or assignment is None:
            raise DatasetOrchestrationError(
                f"Feature COMPLETE sample {feature.sample_key} has no bound "
                "Label result or split assignment; row construction fails "
                "closed"
            )
        row: dict[str, object] = {
            "code": feature.code,
            "sample_key": feature.sample_key,
            "sample_version_id": feature.sample_version_id,
            "feature_window_close": feature.feature_window_close,
            "actual_label_end_time": label.actual_label_end_time,
            "label_status": label.status,
        }
        if include_dataset_as_of:
            pit_sample = pit_by_key.get(feature.sample_key)
            if pit_sample is None:
                raise DatasetOrchestrationError(
                    f"Feature COMPLETE sample {feature.sample_key} has no "
                    "bound PIT sample; row construction fails closed"
                )
            row["dataset_as_of"] = pit_sample.dataset_as_of
        for value in feature.values:
            if value.status != FEATURE_VALUE_STATUS_COMPLETE:
                raise DatasetOrchestrationError(
                    f"Feature COMPLETE sample {feature.sample_key} carries a "
                    "non-COMPLETE Feature value; row construction fails closed"
                )
            row[value.feature_name] = value.value
        for value in label.values:
            row[value.label_name] = (
                value.value
                if value.status == LABEL_STATUS_COMPLETE
                else None
            )
        for name in _SPLIT_FIELD_NAMES:
            row[name] = getattr(assignment, name)
        rows.append(tuple(row[field.name] for field in schema.fields))

    code_index = field_indexes["code"]
    close_index = field_indexes["feature_window_close"]
    key_index = field_indexes["sample_key"]
    rows.sort(
        key=lambda row: (row[code_index], row[close_index], row[key_index])
    )
    return tuple(rows)


def _build_diagnostics(
    scope: DatasetScope,
    request_count: int,
    pit_result: PITAssemblyResult,
    feature_result: FeatureExecutionResult,
    label_result: LabelExecutionResult,
    split_result: ChronologicalSplitResult,
    rows: tuple[tuple[object, ...], ...],
    completion: CompletionSummary,
) -> "DatasetOrchestrationDiagnostics":
    """Deterministic diagnostics recomputed from the actual results."""
    feature_complete = sum(
        1
        for sample in feature_result.samples
        if sample.status == FEATURE_VALUE_STATUS_COMPLETE
    )
    label_complete = sum(
        1
        for sample in label_result.samples
        if sample.status == LABEL_STATUS_COMPLETE
    )
    return DatasetOrchestrationDiagnostics(
        scope=scope,
        request_count=request_count,
        pit_sample_count=len(pit_result.samples),
        feature_complete_sample_count=feature_complete,
        feature_excluded_sample_count=len(feature_result.samples) - feature_complete,
        label_complete_sample_count=label_complete,
        label_incomplete_sample_count=len(label_result.samples) - label_complete,
        split_sample_count=len(split_result.assignments),
        assigned_sample_count=sum(
            1
            for assignment in split_result.assignments
            if assignment.assignment_status == SPLIT_STATUS_ASSIGNED
        ),
        purged_sample_count=sum(
            1
            for assignment in split_result.assignments
            if assignment.assignment_status == SPLIT_STATUS_PURGED
        ),
        excluded_sample_count=sum(
            1
            for assignment in split_result.assignments
            if assignment.assignment_status == SPLIT_STATUS_EXCLUDED
        ),
        logical_row_count=len(rows),
        completion_complete_key_count=completion.complete_count,
        completion_incomplete_key_count=completion.incomplete_count,
        completion_missing_key_count=completion.missing_count,
    )


@dataclass(frozen=True)
class DatasetOrchestrationDiagnostics:
    """Deterministic Dataset orchestration counts (no free text).

    Construction verifies the fixed count matrix:

    - ``pit_sample_count == feature_complete_sample_count +
      feature_excluded_sample_count``;
    - ``pit_sample_count == label_complete_sample_count +
      label_incomplete_sample_count``;
    - ``split_sample_count == feature_complete_sample_count``;
    - ``split_sample_count == assigned_sample_count + purged_sample_count +
      excluded_sample_count``;
    - ``logical_row_count == split_sample_count``;
    - ``completion_*_key_count`` sums to ``len(scope.symbols) *
      len(scope.trade_dates)``.

    ``scope`` is carried so the completion-key equation is verifiable from
    the model itself; the result model additionally recomputes the whole
    diagnostics from the actual sub-results and requires exact equality.
    """

    scope: DatasetScope
    request_count: int
    pit_sample_count: int
    feature_complete_sample_count: int
    feature_excluded_sample_count: int
    label_complete_sample_count: int
    label_incomplete_sample_count: int
    split_sample_count: int
    assigned_sample_count: int
    purged_sample_count: int
    excluded_sample_count: int
    logical_row_count: int
    completion_complete_key_count: int
    completion_incomplete_key_count: int
    completion_missing_key_count: int

    def __post_init__(self) -> None:
        _require_instance(self.scope, DatasetScope, "scope")
        for name in (
            "request_count",
            "pit_sample_count",
            "feature_complete_sample_count",
            "feature_excluded_sample_count",
            "label_complete_sample_count",
            "label_incomplete_sample_count",
            "split_sample_count",
            "assigned_sample_count",
            "purged_sample_count",
            "excluded_sample_count",
            "logical_row_count",
            "completion_complete_key_count",
            "completion_incomplete_key_count",
            "completion_missing_key_count",
        ):
            _require_non_negative_int(getattr(self, name), name)
        if (
            self.pit_sample_count
            != self.feature_complete_sample_count
            + self.feature_excluded_sample_count
        ):
            raise DatasetOrchestrationError(
                "orchestration diagnostics must satisfy pit_sample_count == "
                "feature_complete_sample_count + "
                "feature_excluded_sample_count"
            )
        if (
            self.pit_sample_count
            != self.label_complete_sample_count
            + self.label_incomplete_sample_count
        ):
            raise DatasetOrchestrationError(
                "orchestration diagnostics must satisfy pit_sample_count == "
                "label_complete_sample_count + label_incomplete_sample_count"
            )
        if self.split_sample_count != self.feature_complete_sample_count:
            raise DatasetOrchestrationError(
                "orchestration diagnostics must satisfy split_sample_count == "
                "feature_complete_sample_count"
            )
        if (
            self.split_sample_count
            != self.assigned_sample_count
            + self.purged_sample_count
            + self.excluded_sample_count
        ):
            raise DatasetOrchestrationError(
                "orchestration diagnostics must satisfy split_sample_count == "
                "assigned_sample_count + purged_sample_count + "
                "excluded_sample_count"
            )
        if self.logical_row_count != self.split_sample_count:
            raise DatasetOrchestrationError(
                "orchestration diagnostics must satisfy logical_row_count == "
                "split_sample_count"
            )
        expected_key_count = (
            len(self.scope.symbols) * len(self.scope.trade_dates)
        )
        if (
            self.completion_complete_key_count
            + self.completion_incomplete_key_count
            + self.completion_missing_key_count
            != expected_key_count
        ):
            raise DatasetOrchestrationError(
                "orchestration diagnostics completion key counts must sum to "
                f"len(scope.symbols) * len(scope.trade_dates) == "
                f"{expected_key_count}"
            )


@dataclass(frozen=True)
class DatasetOrchestrationResult:
    """Deterministic pure in-memory output of one Dataset orchestration.

    Carries every identity-bearing fact (``dataset_schema_id``,
    ``logical_dataset_content_id``, ``DatasetIdentityInput``,
    ``dataset_id``), the authoritative schema, the final logical rows, the
    sub-results of the PIT / Feature / Label / Split layers, the
    completion summary, and deterministic diagnostics. Construction
    independently re-verifies every invariant from the carried raw inputs
    (fail closed): contract and row-order constants, dataset kind, the
    manifest / serialization contract values, spec types and pins, the
    PIT / Feature / Label sample binding, the split-handoff equality, the
    re-derived authoritative schema, the rebuilt final rows (including
    field count, schema type/nullability via the identity encoding, and the
    fixed physical sort), every identity recomputation, the completion
    summary, the diagnostics matrix, and the status / row-count
    consistency. A manually constructed or ``dataclasses.replace``-modified
    inconsistent object fails. The result never carries ``built_at``, an
    output path, a DatasetManifest, Parquet bytes, a temporary directory,
    ``created_new_build``, current time, or filesystem facts.
    """

    status: str
    dataset_kind: str
    scope: DatasetScope
    dataset_as_of: datetime | None
    feature_specs: tuple[FeatureSpec, ...]
    label_specs: tuple[LabelSpec, ...]
    split_spec: ChronologicalSplitSpec
    pit_result: PITAssemblyResult
    feature_result: FeatureExecutionResult
    label_result: LabelExecutionResult
    split_result: ChronologicalSplitResult
    schema: DatasetSchema
    rows: tuple[tuple[object, ...], ...]
    dataset_schema_id: str
    logical_dataset_content_id: str
    identity_input: DatasetIdentityInput
    dataset_id: str
    completion: CompletionSummary
    diagnostics: DatasetOrchestrationDiagnostics
    manifest_schema_version: str
    serialization_format: str
    serialization_format_version: str
    row_order: str
    orchestration_contract_version: str

    def logical_row_mappings(self) -> tuple[dict[str, object], ...]:
        """Temporary schema-ordered row mappings (read-only convenience).

        The returned dicts are generated on demand in the authoritative
        schema field order and never become identity caches or internal
        mutable state.
        """
        return _row_mappings(self.rows, self.schema)

    def __post_init__(self) -> None:
        try:
            self._revalidate()
        except (DatasetError, TypeError, ValueError, KeyError) as exc:
            _as_orchestration_error(
                exc, "invalid DatasetOrchestrationResult"
            )

    def _revalidate(self) -> None:
        if (
            self.orchestration_contract_version
            != DATASET_ORCHESTRATION_CONTRACT_VERSION
        ):
            raise DatasetOrchestrationError(
                f"orchestration_contract_version must be "
                f"{DATASET_ORCHESTRATION_CONTRACT_VERSION}, got "
                f"{self.orchestration_contract_version!r}"
            )
        if self.dataset_kind != DATASET_KIND_SUPERVISED:
            raise DatasetOrchestrationError(
                f"dataset_kind must be {DATASET_KIND_SUPERVISED}, got "
                f"{self.dataset_kind!r}"
            )
        if (
            self.row_order
            != DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY
        ):
            raise DatasetOrchestrationError(
                f"row_order must be "
                f"{DATASET_ROW_ORDER_CODE_FEATURE_CLOSE_SAMPLE_KEY}, got "
                f"{self.row_order!r}"
            )
        if (
            self.manifest_schema_version
            != DATASET_MANIFEST_SCHEMA_VERSION
        ):
            raise DatasetOrchestrationError(
                f"manifest_schema_version must be "
                f"{DATASET_MANIFEST_SCHEMA_VERSION}, got "
                f"{self.manifest_schema_version!r}"
            )
        if self.serialization_format != SERIALIZATION_FORMAT_PARQUET:
            raise DatasetOrchestrationError(
                f"serialization_format must be "
                f"{SERIALIZATION_FORMAT_PARQUET}, got "
                f"{self.serialization_format!r}"
            )
        if (
            self.serialization_format_version
            != SERIALIZATION_FORMAT_VERSION_PARQUET
        ):
            raise DatasetOrchestrationError(
                f"serialization_format_version must be "
                f"{SERIALIZATION_FORMAT_VERSION_PARQUET}, got "
                f"{self.serialization_format_version!r}"
            )
        _require_instance(self.scope, DatasetScope, "scope")
        dataset_as_of = self.dataset_as_of
        if dataset_as_of is not None:
            dataset_as_of = normalize_utc_datetime(
                dataset_as_of, "dataset_as_of"
            )
        feature_specs = _normalize_specs(
            self.feature_specs, FeatureSpec, "feature_specs"
        )
        label_specs = _normalize_specs(
            self.label_specs, LabelSpec, "label_specs"
        )
        if not feature_specs:
            raise DatasetOrchestrationError(
                "feature_specs must contain at least one FeatureSpec"
            )
        if not label_specs:
            raise DatasetOrchestrationError(
                "label_specs must contain at least one LabelSpec"
            )
        object.__setattr__(self, "dataset_as_of", dataset_as_of)
        object.__setattr__(self, "feature_specs", feature_specs)
        object.__setattr__(self, "label_specs", label_specs)
        _require_instance(
            self.split_spec, ChronologicalSplitSpec, "split_spec"
        )
        _require_instance(self.pit_result, PITAssemblyResult, "pit_result")
        _require_instance(
            self.feature_result, FeatureExecutionResult, "feature_result"
        )
        _require_instance(
            self.label_result, LabelExecutionResult, "label_result"
        )
        _require_instance(
            self.split_result, ChronologicalSplitResult, "split_result"
        )
        _require_instance(self.schema, DatasetSchema, "schema")
        _require_instance(
            self.identity_input, DatasetIdentityInput, "identity_input"
        )
        _require_instance(
            self.completion, CompletionSummary, "completion"
        )
        _require_instance(
            self.diagnostics, DatasetOrchestrationDiagnostics, "diagnostics"
        )
        if not isinstance(self.rows, tuple):
            raise DatasetOrchestrationError(
                "rows must be a tuple of schema-ordered immutable tuples"
            )
        rows = tuple(tuple(row) for row in self.rows)
        for row in rows:
            if len(row) != len(self.schema.fields):
                raise DatasetOrchestrationError(
                    "every row must carry exactly the schema field count, got "
                    f"{len(row)} for a schema with {len(self.schema.fields)} "
                    "fields"
                )
        object.__setattr__(self, "rows", rows)

        # Spec pins must equal the pins of the carried execution results.
        if _spec_pin_keys(feature_specs) != self.feature_result.feature_spec_pins:
            raise DatasetOrchestrationError(
                "feature_specs pins must equal feature_result.feature_spec_pins"
            )
        if _spec_pin_keys(label_specs) != self.label_result.label_spec_pins:
            raise DatasetOrchestrationError(
                "label_specs pins must equal label_result.label_spec_pins"
            )
        if (
            self.split_result.split_spec_pin
            != chronological_split_spec_pin(self.split_spec)
        ):
            raise DatasetOrchestrationError(
                "split_result.split_spec_pin must match the split spec content"
            )

        # Cross-layer sample binding (keys, version IDs, code, close, cutoff).
        _verify_sample_binding(
            self.pit_result, self.feature_result, self.label_result, dataset_as_of
        )

        # Split handoff equality: assignments exactly the Feature COMPLETE
        # set, and every assignment's facts exactly the bound Label facts.
        complete_keys = {
            sample.sample_key
            for sample in self.feature_result.samples
            if sample.status == FEATURE_VALUE_STATUS_COMPLETE
        }
        if {a.sample_key for a in self.split_result.assignments} != complete_keys:
            raise DatasetOrchestrationError(
                "split_result assignments must equal the Feature COMPLETE "
                "sample set exactly; Feature EXCLUDED samples never enter "
                "the split result"
            )
        label_by_key = {
            sample.sample_key: sample for sample in self.label_result.samples
        }
        feature_by_key = {
            sample.sample_key: sample for sample in self.feature_result.samples
        }
        for assignment in self.split_result.assignments:
            label = label_by_key[assignment.sample_key]
            feature = feature_by_key[assignment.sample_key]
            if (
                assignment.sample_version_id != feature.sample_version_id
                or assignment.feature_window_close
                != feature.feature_window_close
                or assignment.label_status != label.status
                or assignment.actual_label_end_time
                != label.actual_label_end_time
            ):
                raise DatasetOrchestrationError(
                    f"split assignment for sample {assignment.sample_key} "
                    "does not match the bound Feature / Label facts; "
                    "label_status and actual_label_end_time are never "
                    "inferred or recomputed by the orchestrator"
                )

        # Authoritative schema re-derivation.
        expected_schema = _derive_schema(
            feature_specs,
            label_specs,
            include_dataset_as_of=dataset_as_of is not None,
        )
        if self.schema != expected_schema:
            raise DatasetOrchestrationError(
                "schema must exactly equal the authoritative schema derived "
                "from the specs and dataset_as_of"
            )

        # Final rows rebuilt from the sub-results and compared exactly.
        expected_rows = _build_logical_rows(
            self.pit_result,
            self.feature_result,
            self.label_result,
            self.split_result,
            expected_schema,
        )
        if rows != expected_rows:
            raise DatasetOrchestrationError(
                "rows must exactly equal the rows rebuilt from the PIT / "
                "Feature / Label / Split results under the authoritative "
                "schema, in the fixed physical order (code, "
                "feature_window_close, sample_key)"
            )
        if len({row[2] for row in rows}) != len(rows):
            # sample_key is the third schema field (index 2).
            raise DatasetOrchestrationError(
                "rows must not contain duplicate sample_key values"
            )

        # Identity recomputation.
        expected_schema_id = dataset_schema_id(expected_schema)
        if self.dataset_schema_id != expected_schema_id:
            raise DatasetOrchestrationError(
                "dataset_schema_id does not match the carried schema"
            )
        expected_content_id = logical_dataset_content_id(
            expected_schema, _row_mappings(rows, expected_schema)
        )
        if self.logical_dataset_content_id != expected_content_id:
            raise DatasetOrchestrationError(
                "logical_dataset_content_id does not match the carried rows"
            )

        # Completion and diagnostics recomputation.
        expected_completion = _build_completion(
            self.scope, self.pit_result, self.feature_result, self.label_result
        )
        if self.completion != expected_completion:
            raise DatasetOrchestrationError(
                "completion does not match the summary recomputed from the "
                "scope and the PIT / Feature / Label results"
            )
        expected_diagnostics = _build_diagnostics(
            self.scope,
            len(self.pit_result.samples),
            self.pit_result,
            self.feature_result,
            self.label_result,
            self.split_result,
            rows,
            expected_completion,
        )
        if self.diagnostics != expected_diagnostics:
            raise DatasetOrchestrationError(
                "diagnostics do not match the counts recomputed from the "
                "orchestration results"
            )

        # Identity input and dataset id recomputation.
        expected_implementations = _merge_implementation_pins(
            self.feature_result, self.label_result
        )
        if (
            self.identity_input.implementations
            != expected_implementations
        ):
            raise DatasetOrchestrationError(
                "identity_input.implementations must be the merged Feature "
                "and Label implementation pins"
            )
        expected_identity_input = DatasetIdentityInput(
            dataset_kind=self.dataset_kind,
            scope=self.scope,
            dataset_as_of=dataset_as_of,
            schema=expected_schema,
            dataset_schema_id=self.dataset_schema_id,
            logical_dataset_content_id=self.logical_dataset_content_id,
            canonical_builds=self.pit_result.canonical_build_pins,
            canonical_row_version_ids=self.pit_result.canonical_row_version_ids,
            feature_specs=self.feature_result.feature_spec_pins,
            label_specs=self.label_result.label_spec_pins,
            split_spec=self.split_result.split_spec_pin,
            implementations=expected_implementations,
            completion=self.completion,
            gap_references=self.pit_result.gap_references,
            manifest_schema_version=self.manifest_schema_version,
            serialization_format=self.serialization_format,
            serialization_format_version=self.serialization_format_version,
        )
        if self.identity_input != expected_identity_input:
            raise DatasetOrchestrationError(
                "identity_input does not exactly match the identity input "
                "reconstructed from the orchestration results"
            )
        expected_dataset_id = dataset_id(self.identity_input)
        if self.dataset_id != expected_dataset_id:
            raise DatasetOrchestrationError(
                "dataset_id does not match the recomputed dataset_id of the "
                "carried identity input"
            )

        # Status / row-count consistency.
        expected_status = STATUS_EMPTY if not rows else STATUS_COMPLETE
        if self.status != expected_status:
            raise DatasetOrchestrationError(
                f"status must be {expected_status} for a result with "
                f"{len(rows)} logical rows, got {self.status!r}"
            )
