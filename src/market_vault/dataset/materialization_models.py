"""Frozen models and constants of the Dataset materialization contract
(v0.5.0 PR-6).

This module defines the materialization layer's own contract surface:

- the version constants of the materializer, the build report, and the
  spec artifacts;
- the fixed artifact file names, the two spec directories, the five fixed
  ``DatasetOutputFile`` ``file_role`` values, and the five fixed
  ``content_role`` values (recorded facts that never enter any existing
  identity algorithm);
- the unified fail-closed error :class:`DatasetMaterializationError` (a
  subclass of :class:`DatasetError`);
- :class:`DatasetMaterializationResult` — the frozen result model of one
  committed Dataset build directory, which independently re-verifies every
  invariant at construction (fail closed).

Nothing here reads or writes the filesystem. ``dataset_id`` is the only
identity input; all constants of this module are artifact record contracts
and never enter ``dataset_id``, ``dataset_schema_id``, or
``logical_dataset_content_id``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .encoding import DatasetError
from .models import STATUS_COMPLETE, STATUS_EMPTY

__all__ = [
    "DATASET_BUILD_REPORT_FILENAME",
    "DATASET_BUILD_REPORT_SCHEMA_VERSION",
    "DATASET_CONTENT_ROLE_BUILD_REPORT",
    "DATASET_CONTENT_ROLE_FEATURE_SPEC",
    "DATASET_CONTENT_ROLE_LABEL_SPEC",
    "DATASET_CONTENT_ROLE_LOGICAL_ROWS",
    "DATASET_CONTENT_ROLE_SPLIT_SPEC",
    "DATASET_FEATURE_SPECS_DIRNAME",
    "DATASET_LABEL_SPECS_DIRNAME",
    "DATASET_MANIFEST_FILENAME",
    "DATASET_MATERIALIZER_VERSION",
    "DATASET_OUTPUT_ROLE_BUILD_REPORT",
    "DATASET_OUTPUT_ROLE_DATASET",
    "DATASET_OUTPUT_ROLE_FEATURE_SPEC",
    "DATASET_OUTPUT_ROLE_LABEL_SPEC",
    "DATASET_OUTPUT_ROLE_SPLIT_SPEC",
    "DATASET_PARQUET_FILENAME",
    "DATASET_SPEC_ARTIFACT_VERSION",
    "DATASET_SPLIT_SPEC_FILENAME",
    "DATASET_SUCCESS_FILENAME",
    "DatasetMaterializationError",
    "DatasetMaterializationResult",
]

#: Version of the Dataset materializer implementation itself. It is carried
#: on every :class:`DatasetMaterializationResult` and recorded in the build
#: report and the Parquet metadata; it never enters ``dataset_id``.
DATASET_MATERIALIZER_VERSION = "market-vault-dataset-materializer-v1"

#: Fixed schema version of ``build_report.json`` (a recorded, non-identity
#: fact).
DATASET_BUILD_REPORT_SCHEMA_VERSION = "market-vault-dataset-build-report-v1"

#: Fixed version of the deterministic Dataset spec artifact format (Feature,
#: Label, and Split artifacts share one canonical format).
DATASET_SPEC_ARTIFACT_VERSION = "market-vault-dataset-spec-artifact-v1"

#: Fixed artifact file names of one Dataset build directory.
DATASET_PARQUET_FILENAME = "dataset.parquet"
DATASET_MANIFEST_FILENAME = "manifest.json"
DATASET_BUILD_REPORT_FILENAME = "build_report.json"
DATASET_SPLIT_SPEC_FILENAME = "split_spec.yaml"
DATASET_SUCCESS_FILENAME = "_SUCCESS"

#: Fixed spec artifact directories.
DATASET_FEATURE_SPECS_DIRNAME = "feature_specs"
DATASET_LABEL_SPECS_DIRNAME = "label_specs"

#: Fixed ``DatasetOutputFile.file_role`` values.
DATASET_OUTPUT_ROLE_DATASET = "dataset"
DATASET_OUTPUT_ROLE_BUILD_REPORT = "build_report"
DATASET_OUTPUT_ROLE_FEATURE_SPEC = "feature_spec"
DATASET_OUTPUT_ROLE_LABEL_SPEC = "label_spec"
DATASET_OUTPUT_ROLE_SPLIT_SPEC = "split_spec"

#: Fixed ``DatasetOutputFile.content_role`` values (artifact record
#: contracts; never identity-bearing). The build report record carries the
#: build-report schema version; every spec artifact record carries the spec
#: artifact version.
DATASET_CONTENT_ROLE_LOGICAL_ROWS = "logical_rows"
DATASET_CONTENT_ROLE_BUILD_REPORT = DATASET_BUILD_REPORT_SCHEMA_VERSION
DATASET_CONTENT_ROLE_FEATURE_SPEC = DATASET_SPEC_ARTIFACT_VERSION
DATASET_CONTENT_ROLE_LABEL_SPEC = DATASET_SPEC_ARTIFACT_VERSION
DATASET_CONTENT_ROLE_SPLIT_SPEC = DATASET_SPEC_ARTIFACT_VERSION

_DATASET_ID_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetMaterializationError(DatasetError):
    """Structured fail-closed failure of the Dataset materialization layer.

    Raised for invalid materialization inputs, staging residue and concurrent
    staging conflicts, write / hash / readback verification failures,
    manifest or build-report inconsistencies, unexpected files, symlink /
    junction rejections, existing-build verification failures, and result-
    model inconsistencies. Every documented failure of the underlying layers
    (``DatasetError``, ``OSError``, ``UnicodeError``, JSON validation errors,
    documented PyArrow validation / write / read errors, and the documented
    ``TypeError`` / ``ValueError`` / ``KeyError``) is wrapped here with its
    ``__cause__`` preserved. There is no "warn and continue" path, no partial
    result is ever returned, and broad ``except Exception`` is never used:
    real programming errors are not hidden, only the documented failures are
    converted.
    """


def _as_materialization_error(exc, context: str) -> None:
    """Convert a documented materialization failure to
    :class:`DatasetMaterializationError`.

    A :class:`DatasetMaterializationError` passes through unchanged (never
    double-wrapped); the contract-listed exceptions (``DatasetError``,
    ``OSError``, ``UnicodeError``, JSON / PyArrow validation errors, and the
    documented ``TypeError`` / ``ValueError`` / ``KeyError``) are converted
    with a context prefix and their ``__cause__`` preserved. Broad
    ``except Exception`` is never used: programming errors are not hidden.
    """
    if isinstance(exc, DatasetMaterializationError):
        raise exc
    if isinstance(
        exc,
        (
            DatasetError,
            OSError,
            UnicodeError,
            TypeError,
            ValueError,
            KeyError,
        ),
    ):
        raise DatasetMaterializationError(f"{context}: {exc}") from exc
    raise exc


def _require_materialization_error(exc, context: str) -> None:
    """Wrap *any* documented materialization failure, including failures
    raised by validation code that already reports bare ``DatasetError``.

    ``_as_materialization_error`` is used at the public entry; this helper
    is used inside the layer so every internal failure is already a
    :class:`DatasetMaterializationError` when it reaches the entry."""
    _as_materialization_error(exc, context)


def _require_absolute_artifact_path(path: Path, build_path: Path, label: str) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        raise DatasetMaterializationError(
            f"{label} must be an absolute Path, got {path!r}"
        )
    if not path.is_relative_to(build_path):
        raise DatasetMaterializationError(
            f"{label} {path} escapes the build directory {build_path}"
        )


@dataclass(frozen=True)
class DatasetMaterializationResult:
    """Deterministic output of one committed Dataset materialization.

    Carries the immutable fact paths of the committed build directory, the
    dataset identity and status, the logical row count, the recorded output
    file count, whether a new build directory was created by this call, and
    the materializer version. Construction independently re-verifies every
    invariant (fail closed): ``dataset_id`` is strict lowercase 64-hex;
    ``status`` is COMPLETE or EMPTY and consistent with the row count (EMPTY
    requires zero rows, COMPLETE requires at least one); every path is an
    absolute :class:`pathlib.Path` whose final name is the fixed artifact
    name; every artifact path lies inside ``build_path`` and
    ``build_path.name`` is exactly ``dataset_id``; counts are real
    non-negative integers; ``created_new_build`` is a real bool; and
    ``materializer_version`` is the current constant.

    The model never carries a mutable dict, a temporary path, elapsed time,
    current time, arbitrary metadata, or Parquet bytes.
    """

    dataset_id: str
    status: str
    build_path: Path
    dataset_path: Path
    manifest_path: Path
    build_report_path: Path
    success_path: Path
    logical_row_count: int
    output_file_count: int
    created_new_build: bool
    materializer_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not _DATASET_ID_RE.fullmatch(
            self.dataset_id
        ):
            raise DatasetMaterializationError(
                f"dataset_id must be a 64-character lowercase SHA-256 hex "
                f"string, got {self.dataset_id!r}"
            )
        if self.status not in (STATUS_COMPLETE, STATUS_EMPTY):
            raise DatasetMaterializationError(
                f"status must be {STATUS_COMPLETE} or {STATUS_EMPTY}, got "
                f"{self.status!r}"
            )
        for name in ("logical_row_count", "output_file_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise DatasetMaterializationError(
                    f"{name} must be a non-negative real integer, got {value!r}"
                )
        if type(self.created_new_build) is not bool:
            raise DatasetMaterializationError(
                "created_new_build must be a real bool, got "
                f"{self.created_new_build!r}"
            )
        if self.materializer_version != DATASET_MATERIALIZER_VERSION:
            raise DatasetMaterializationError(
                f"materializer_version must be {DATASET_MATERIALIZER_VERSION}, "
                f"got {self.materializer_version!r}"
            )
        build_path = self.build_path
        if not isinstance(build_path, Path) or not build_path.is_absolute():
            raise DatasetMaterializationError(
                f"build_path must be an absolute Path, got {build_path!r}"
            )
        if build_path.name != self.dataset_id:
            raise DatasetMaterializationError(
                f"build_path.name must be exactly {self.dataset_id!r}, got "
                f"{build_path.name!r}"
            )
        _require_absolute_artifact_path(
            self.dataset_path, build_path, "dataset_path"
        )
        _require_absolute_artifact_path(
            self.manifest_path, build_path, "manifest_path"
        )
        _require_absolute_artifact_path(
            self.build_report_path, build_path, "build_report_path"
        )
        _require_absolute_artifact_path(
            self.success_path, build_path, "success_path"
        )
        if self.dataset_path.name != DATASET_PARQUET_FILENAME:
            raise DatasetMaterializationError(
                f"dataset_path.name must be {DATASET_PARQUET_FILENAME}, got "
                f"{self.dataset_path.name!r}"
            )
        if self.manifest_path.name != DATASET_MANIFEST_FILENAME:
            raise DatasetMaterializationError(
                f"manifest_path.name must be {DATASET_MANIFEST_FILENAME}, got "
                f"{self.manifest_path.name!r}"
            )
        if self.build_report_path.name != DATASET_BUILD_REPORT_FILENAME:
            raise DatasetMaterializationError(
                f"build_report_path.name must be "
                f"{DATASET_BUILD_REPORT_FILENAME}, got "
                f"{self.build_report_path.name!r}"
            )
        if self.success_path.name != DATASET_SUCCESS_FILENAME:
            raise DatasetMaterializationError(
                f"success_path.name must be {DATASET_SUCCESS_FILENAME}, got "
                f"{self.success_path.name!r}"
            )
        if self.status == STATUS_EMPTY and self.logical_row_count != 0:
            raise DatasetMaterializationError(
                "status EMPTY requires logical_row_count == 0"
            )
        if self.status == STATUS_COMPLETE and self.logical_row_count == 0:
            raise DatasetMaterializationError(
                "status COMPLETE requires at least one logical row; zero "
                "rows must be EMPTY"
            )
