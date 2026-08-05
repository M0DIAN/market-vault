"""Frozen models and version constants of the Dataset CLI contract
(v0.5.0 PR-8).

This module defines the Dataset CLI layer's own contract surface:

- :data:`DATASET_CLI_CONTRACT_VERSION` — the version of the Dataset CLI
  input/output contract. It describes the CLI only; it never enters
  ``dataset_id``, the manifest, the Parquet metadata, any spec pin, or any
  artifact;
- :data:`DATASET_BUILD_PLAN_SCHEMA_VERSION` — the version of the strict
  Dataset build-plan JSON contract consumed by ``dataset-build``;
- :data:`DATASET_CLI_RESULT_SCHEMA_VERSION` — the version of the
  deterministic CLI result JSON contract (success and failure outputs);
- :class:`DatasetCLIError` — the unified documented error of the Dataset
  command layer;
- the frozen internal build-plan models (:class:`BuildPlan`,
  :class:`PlanRequest`, :class:`PlanScope`, :class:`PlanSplitSpec`) parsed
  from one strict build-plan JSON document.

The CLI constants and models are internal to the command layer: they are
never exported from :mod:`market_vault.dataset` and never enter any
identity. Nothing here reads or writes the filesystem and no current time
is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

__all__ = [
    "DATASET_BUILD_PLAN_SCHEMA_VERSION",
    "DATASET_CLI_CONTRACT_VERSION",
    "DATASET_CLI_RESULT_SCHEMA_VERSION",
    "BuildPlan",
    "DatasetCLIError",
    "PlanRequest",
    "PlanScope",
    "PlanSplitSpec",
]

#: Version of the Dataset CLI input/output contract (described in
#: ``docs/contracts/dataset_cli.md``). It records the CLI contract only and
#: never enters ``dataset_id``, the Dataset manifest, the Parquet metadata,
#: any spec pin, or any artifact.
DATASET_CLI_CONTRACT_VERSION = "market-vault-dataset-cli-v1"

#: Version of the strict Dataset build-plan JSON contract consumed by
#: ``market-vault dataset-build --plan``. A build plan is an execution
#: input, never an identity artifact: its raw bytes never enter
#: ``dataset_id`` or any artifact.
DATASET_BUILD_PLAN_SCHEMA_VERSION = "market-vault-dataset-build-plan-v1"

#: Version of the deterministic Dataset CLI result JSON contract (success
#: and failure outputs of the three Dataset commands).
DATASET_CLI_RESULT_SCHEMA_VERSION = "market-vault-dataset-cli-result-v1"


class DatasetCLIError(Exception):
    """Unified documented failure of the Dataset command layer.

    Raised for strict build-plan validation failures, path / symlink /
    junction rejections, and every documented failure of the underlying
    formal layers (``DatasetError`` and its subclasses, Canonical
    verification errors, PIT / Feature / Label / Split errors,
    ``DatasetOrchestrationError``, ``DatasetMaterializationError``,
    ``DatasetArtifactValidationError``, ``OSError``, ``UnicodeError``,
    ``json.JSONDecodeError``, and the documented ``TypeError`` /
    ``ValueError`` / ``KeyError``), each converted with its ``__cause__``
    preserved and never double-wrapped. The command layer never uses broad
    ``except Exception``: real programming errors (``RuntimeError``,
    ``AssertionError``, and friends) are not disguised as user input
    errors and are never converted.
    """


@dataclass(frozen=True)
class PlanRequest:
    """One typed sample request parsed from the build plan.

    Field values are validated for type and timestamp-format at plan parse
    time (all instants timezone-aware and normalized to UTC microseconds,
    the label window complete or absent); semantic validation (adjustment
    policy, label window ordering, scope binding) is performed by the
    existing :class:`market_vault.dataset.pit_models.PITSampleRequest` and
    the existing orchestrator preflight when the typed model is
    constructed. Request facts never enter any Dataset identity except
    through the scope and the PIT sample assembly the request drives.
    """

    code: str
    interval: str
    adjustment: str
    requested_session: str
    anchor_market_calendar_date: date
    feature_window_start: datetime
    feature_window_close: datetime
    label_window_start: datetime | None
    label_window_close: datetime | None


@dataclass(frozen=True)
class PlanScope:
    """The explicit scope block of one build plan.

    ``symbols`` is a non-empty unique list of strings; ``trade_dates`` is a
    non-empty unique list of strict ``YYYY-MM-DD`` strings (semantic
    normalization, deduplication, and sorting are performed by the existing
    :class:`market_vault.dataset.models.DatasetScope` construction). The
    scope is never silently narrowed to the request set: keys without a
    request produce MISSING completion entries.
    """

    symbols: tuple[str, ...]
    trade_dates: tuple[str, ...]
    interval: str
    adjustment: str
    requested_session: str


@dataclass(frozen=True)
class PlanSplitSpec:
    """The explicit ``split_spec`` block of one build plan.

    Dates are parsed to strict ``YYYY-MM-DD`` dates at plan parse time;
    timezone existence, date ordering, and the fixed rule values are
    validated by the existing :class:`market_vault.dataset.split_models.
    ChronologicalSplitSpec` construction.
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


@dataclass(frozen=True)
class BuildPlan:
    """One strictly parsed, versioned Dataset build plan.

    Carries every explicit execution input of one ``dataset-build``:
    ``canonical_build_dirs``, ``feature_spec_files``, ``label_spec_files``
    (raw path strings resolved against the plan file's parent directory),
    the typed ``requests``, the ``scope``, the ``split_spec``,
    ``dataset_as_of`` (None or a timezone-aware datetime normalized to UTC
    microseconds), ``output_root``, and ``built_at`` (required,
    timezone-aware, normalized to UTC microseconds; never current time).

    The model is deeply immutable and never carries the raw plan bytes:
    plan path, plan parent directory, JSON whitespace and key order,
    source file paths, ``output_root``, ``built_at``, and the CLI version
    constants never enter any Dataset identity.
    """

    plan_schema_version: str
    canonical_build_dirs: tuple[str, ...]
    feature_spec_files: tuple[str, ...]
    label_spec_files: tuple[str, ...]
    requests: tuple[PlanRequest, ...]
    scope: PlanScope
    split_spec: PlanSplitSpec
    dataset_as_of: datetime | None
    output_root: str
    built_at: datetime
