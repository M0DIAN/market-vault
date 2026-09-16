"""Observation-only Feature execution; A3 selections are verified, never rerun."""

from ..dataset.encoding import DatasetError
from ..observation._validation import ObservationError
from ..observation.artifact_models import VerifiedObservationBuild
from ..observation.pit_models import ObservationPITAssemblyResult
from ..observation.pit_identity import feature_spec_pin_id, observation_decision_id
from ._feature_validation import verify_execution_inputs
from .feature_spec_models import ObservationFeatureSpec, normalize_specs
from .feature_specs import observation_feature_spec_pin
from .feature_models import (
    ObservationFeatureExecutionError, ObservationFeatureTransformInput,
    ObservationFeatureValueResult, ObservationFeatureSampleResult, ObservationFeatureExecutionResult,
)
from .feature_registry import _preflight_registry, _resolve


def execute_observation_features(
    pit_result: ObservationPITAssemblyResult,
    observation_builds: tuple[VerifiedObservationBuild, ...],
    feature_specs: tuple[ObservationFeatureSpec, ...],
) -> ObservationFeatureExecutionResult:
    """Execute declared static transforms against exact verified in-memory evidence."""
    try:
        specs = normalize_specs(feature_specs)
        _preflight_registry()
        registrations = tuple(_resolve(s) for s in specs)
        decisions, samples, selected = verify_execution_inputs(pit_result, observation_builds, specs)
        decisions = {(d.sample_key, d.feature_spec_pin_id): d for d in decisions}
        pins = tuple(observation_feature_spec_pin(s) for s in specs)
        # Validate every invocation before any transform, including later samples.
        inputs = {}
        for sample in samples:
            for spec, pin, registration in zip(specs, pins, registrations):
                key = (sample.sample_key, feature_spec_pin_id(pin))
                decision = decisions[key]
                row = selected[key]
                if row is None:
                    continue
                fields = {f.name: (index, f.logical_type) for index, f in enumerate(row.value_schema.fields)}
                names = spec.source_spec.input_field_names
                if any(n not in fields for n in names):
                    raise ObservationFeatureExecutionError("missing input field")
                types = tuple(fields[n][1] for n in names)
                if types != registration.input_logical_types:
                    raise ObservationFeatureExecutionError("input field logical type mismatch")
                if decision.status == "COMPLETE":
                    inputs[key] = ObservationFeatureTransformInput(
                        names, types, tuple(row.values[fields[n][0]] for n in names), spec.parameters)
        result_samples = []
        for sample in samples:
            values = []
            for spec, pin, registration in zip(specs, pins, registrations):
                key = (sample.sample_key, feature_spec_pin_id(pin))
                decision = decisions[key]
                complete = decision.status == "COMPLETE"
                value = registration.implementation(inputs[key]) if complete else None
                values.append(ObservationFeatureValueResult(
                    sample.sample_key, sample.multi_source_sample_version_id, spec.name, pin,
                    registration.implementation_pin, observation_decision_id(decision), decision.status,
                    value, decision.reason, decision.selected_observation_version_id if complete else None))
            status = "COMPLETE" if all(v.status == "COMPLETE" for v in values) else "EXCLUDED"
            result_samples.append(ObservationFeatureSampleResult(
                sample.sample_key, sample.multi_source_sample_version_id, status, tuple(values)))
        impls = tuple(sorted({r.implementation_pin for r in registrations}, key=lambda p: (p.name, p.version, p.content_sha256)))
        return ObservationFeatureExecutionResult(tuple(result_samples), pins, impls)
    except ObservationFeatureExecutionError:
        raise
    except (DatasetError, ObservationError, TypeError, ValueError, ArithmeticError) as exc:
        raise ObservationFeatureExecutionError(str(exc)) from exc
