"""Strict read-only Cross-Day artifact reader; independent of live issuance."""

from pathlib import Path
from types import MappingProxyType

from ..dataset.encoding import DatasetError
from ._artifact_io import _NativeScope, _PhysicalCapture
from ._artifact_paths import _absolute_path, _FINAL
from .artifact_models import MultiSourceCrossDayArtifactError, VerifiedMultiSourceCrossDayDataset, _require
from .manifest import _validate_manifest_content


def _freeze_json(value):
    if type(value) is dict:
        return MappingProxyType({k: _freeze_json(v) for k, v in value.items()})
    if type(value) is list:
        return tuple(_freeze_json(v) for v in value)
    _require(type(value) in (str, bool, int, float) or value is None, "ARTIFACT_DECODE", "invalid manifest scalar")
    return value


def _verify_capture(capture):
    _require("manifest.json" in capture.data, "MANIFEST_BINDING", "missing manifest")
    content = {name: data for name, data in capture.data.items() if name not in ("manifest.json", "_SUCCESS")}
    declaration, payload = _validate_manifest_content(capture.data["manifest.json"], content)
    capture.recheck()
    return declaration, payload


def load_verified_multi_source_cross_day_dataset(build_dir: str | Path) -> VerifiedMultiSourceCrossDayDataset:
    """Verify only this exact artifact; never select, execute, repair or enroll."""
    try:
        path = _absolute_path(build_dir)
        _require(_FINAL.fullmatch(path.name) is not None, "UNSAFE_PATH", "exact final Dataset directory name required")
        with _NativeScope(path.parent) as scope, _PhysicalCapture(scope, path, require_success=True) as capture:
            declaration, payload = _verify_capture(capture)
            _require(path.name == "dataset_id=" + payload["dataset_id"], "MANIFEST_BINDING", "final directory/Dataset ID differs")
            manifest = _freeze_json(payload)
            # No caller/live object is reconstructed. Every component is a validated recorded view.
            result = object.__new__(VerifiedMultiSourceCrossDayDataset)
            values = dict(dataset_id=payload["dataset_id"], identity_input=declaration,
                manifest_payload=manifest, build_path=Path(path), status=payload["status"])
            for name in ("scope", "dataset_as_of", "schema", "rows", "sample_audit", "completion", "split_result",
                         "feature_pit", "ts2_features", "observation_pit", "observation_features", "cross_day_association",
                         "cross_day_labels", "schedule"):
                values[name] = getattr(declaration, name)
            for name, value in values.items():
                object.__setattr__(result, name, value)
            capture.recheck()
            return result
    except MultiSourceCrossDayArtifactError:
        raise
    except OSError as exc:
        raise MultiSourceCrossDayArtifactError("UNSAFE_PATH", "PREFLIGHT", exc) from exc
    except (DatasetError, UnicodeError, ValueError) as exc:
        raise MultiSourceCrossDayArtifactError("ARTIFACT_AUTHORITY", "PREFLIGHT", exc) from exc
