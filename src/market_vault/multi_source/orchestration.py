"""A4.2 explicit in-memory orchestration; inherited registry reads only."""

from dataclasses import replace

from ..canonical.reader import VerifiedCanonicalBuild
from ..dataset.encoding import DatasetError, normalize_utc_datetime
from ..dataset.feature_execution import execute_builtin_features, _validate_callable_contract as _feature_contract
from ..dataset.feature_registry import built_in_feature_registry
from ..dataset.label_execution import (
    execute_builtin_labels, _validate_callable_contract as _label_contract, _validate_builtin_label_spec_contract,
)
from ..dataset.label_registry import built_in_label_registry
from ..dataset.models import DatasetScope
from ..dataset.orchestration_models import _verify_scope_request_binding
from ..dataset.pit import assemble_point_in_time_samples
from ..dataset.pit_identity import pit_sample_key
from ..dataset.pit_models import PITSampleRequest
from ..dataset.split_models import ChronologicalSplitSpec
from ..dataset.splits import assign_chronological_splits
from ..observation.artifact_models import VerifiedObservationBuild
from ..observation.pit import assemble_observation_pit_sidecar
from ._orchestration_closure import close_layers, normalize_spec_families, represented_builds, split_samples
from ._orchestration_validation import MultiSourceDatasetError, canonical_copy, items, require
from .feature_execution import execute_observation_features
from .feature_registry import _preflight_registry, _resolve
from .feature_specs import observation_feature_binding
from .orchestration_models import MultiSourceDatasetOrchestrationResult


def orchestrate_multi_source_dataset_build(*, canonical_builds, observation_builds, requests,
        bar_feature_specs, observation_feature_specs, label_specs, split_spec, scope, dataset_as_of,
        dataset_kind="SUPERVISED") -> MultiSourceDatasetOrchestrationResult:
    """Execute each frozen layer once. No paths, callbacks, registry or ID overrides."""
    try:
        return _orchestrate(canonical_builds, observation_builds, requests, bar_feature_specs,
            observation_feature_specs, label_specs, split_spec, scope, dataset_as_of, dataset_kind)
    except MultiSourceDatasetError:
        raise
    except (DatasetError, ValueError, TypeError, KeyError) as exc:
        raise MultiSourceDatasetError(f"multi-source orchestration failed: {exc}") from exc


def _orchestrate(canonical, observation, requests, bar_specs, observation_specs, label_specs, split, scope, cutoff, kind):
    require(kind == "SUPERVISED", "only SUPERVISED is supported")
    items(canonical, VerifiedCanonicalBuild, "Canonical builds", nonempty=True)
    items(observation, VerifiedObservationBuild, "Observation builds", nonempty=True)
    requests = tuple(replace(r) for r in items(requests, PITSampleRequest, "requests"))
    require(len({pit_sample_key(r) for r in requests}) == len(requests), "duplicate requests")
    scope = canonical_copy(scope, DatasetScope, "scope")
    split = canonical_copy(split, ChronologicalSplitSpec, "split spec")
    cutoff = None if cutoff is None else normalize_utc_datetime(cutoff, "dataset_as_of")
    bar_specs, observation_specs, label_specs = normalize_spec_families(bar_specs, observation_specs, label_specs)
    # The only inherited I/O is construction of the frozen legacy registries.
    feature_registry, label_registry = built_in_feature_registry(), built_in_label_registry()
    expected_bar, expected_labels = {}, {}
    for s in bar_specs:
        resolved = feature_registry.resolve_feature_spec(s)
        _feature_contract(resolved.registration)
        expected_bar[s.name] = resolved.pin
    for s in label_specs:
        resolved = label_registry.resolve_label_spec(s)
        _label_contract(resolved.registration)
        _validate_builtin_label_spec_contract(s, resolved.registration)
        expected_labels[s.name] = resolved.pin
    _preflight_registry()
    expected_observation = {s.name: _resolve(s).implementation_pin for s in observation_specs}
    _verify_scope_request_binding(scope, requests)
    bar_pit = assemble_point_in_time_samples(canonical, requests, dataset_as_of=cutoff)
    bindings = tuple(observation_feature_binding(s) for s in observation_specs)
    observation_pit = assemble_observation_pit_sidecar(bar_pit, observation, bindings)
    features = execute_builtin_features(canonical, bar_pit, bar_specs)
    observation_features = execute_observation_features(observation_pit, represented_builds(observation_pit, observation), observation_specs)
    labels = execute_builtin_labels(canonical, bar_pit, label_specs)
    for result, expected in ((features, expected_bar), (observation_features, expected_observation), (labels, expected_labels)):
        require(set(result.implementation_pins) == set(expected.values()), "execution implementation pins differ from preflight")
        for sample in result.samples:
            require(all(v.implementation_pin == expected[v.spec_pin.name] for v in sample.values), "spec implementation mismatch")
    close_layers(bar_pit, observation_pit, observation, bar_specs, observation_specs, label_specs,
                 features, observation_features, labels, cutoff)
    samples = split_samples(bar_pit, observation_pit, features, observation_features, labels)
    split_result = assign_chronological_splits(samples, split)
    return MultiSourceDatasetOrchestrationResult(scope, cutoff, bar_specs, observation_specs, label_specs, split,
        canonical, observation, bar_pit, observation_pit, features, observation_features, labels, split_result, kind)
