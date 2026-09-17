"""Recorded TS2 outcome verification, not Feature execution or PIT selection."""

from datetime import timedelta

from ..cross_day._authority import INTERVAL_MINUTES
from ..dataset.specs import feature_label_spec_pin
from ..ts2_feature import identity as ids
from ..ts2_feature.models import TS2FeatureExecutionResult, TS2FeatureSampleResult, TS2FeatureValueResult
from ..ts2_feature._validation import finite_float
from ..ts2_feature.registry import TS2_FEATURE_EXECUTION_CONTRACT_VERSION, TS2_FEATURE_REGISTRY_CONTRACT_VERSION
from ._validation import digest, numeric, records, require


def verify_ts2(result, pit, builds, rows, resolved, registrations, cutoff):
    code = "TS2_FEATURE_BINDING"
    require(type(result) is TS2FeatureExecutionResult, code, "issued TS2 result required")
    specs = tuple(s for s, _, _ in resolved)
    pins = tuple(feature_label_spec_pin(s) for s in specs)
    registry_pins = tuple(sorted((r.pin for r in registrations), key=ids.implementation_pin_id))
    require(result.registry_implementation_pins == registry_pins,
            "IMPLEMENTATION_BINDING", "all eight real TS2 pins required")
    build_ids = tuple(b.canonical_build_id for b in builds)
    require((result.execution_contract_version, result.registry_contract_version,
             result.feature_association_schema_id, result.feature_association_content_id,
             result.dataset_as_of, result.considered_canonical_build_ids, result.feature_specs,
             result.feature_spec_pins) ==
            (TS2_FEATURE_EXECUTION_CONTRACT_VERSION, TS2_FEATURE_REGISTRY_CONTRACT_VERSION,
             pit.association_schema_id, pit.association_content_id, cutoff, build_ids, specs, pins),
            code, "TS2 input closure mismatch")
    samples = records(result.samples, TS2FeatureSampleResult, lambda s: s.sample_key, code)
    require(samples == result.samples and tuple(s.sample_key for s in samples) ==
            tuple(s.sample_key for s in pit.samples), code, "TS2 sample closure mismatch")
    for sample, upstream in zip(samples, pit.samples):
        require(sample.bar_sample_version_id == upstream.sample_version_id, code, "bar version mismatch")
        values = records(sample.values, TS2FeatureValueResult, lambda v: ids.spec_pin_id(v.spec_pin), code)
        require(values == sample.values and tuple(v.spec_pin for v in values) == pins,
                code, "TS2 sample/spec cross-product mismatch")
        full = upstream.feature_canonical_row_version_ids
        for value, (spec, registration, count) in zip(values, resolved):
            # Full PIT admission is independent of this spec-specific recorded projection.
            available = min(count, len(full))
            candidates = full[-available:] if available else ()
            reason = "INSUFFICIENT_ROWS" if len(full) < count else None
            interval = timedelta(minutes=INTERVAL_MINUTES[upstream.request.interval])
            if reason is None and any(rows[b].bar.event_time - rows[a].bar.event_time != interval
                                      for a, b in zip(candidates, candidates[1:])):
                reason = "NON_CONTIGUOUS_ROWS"
            for version in full:
                for field in registration.contract.fields:
                    finite_float(getattr(rows[version].bar, field), "CANONICAL_AUTHORITY")
            require((value.sample_key, value.bar_sample_version_id, value.feature_name,
                     value.spec_pin, value.implementation_pin, value.feature_window_close,
                     value.dataset_as_of, value.considered_canonical_build_ids,
                     value.candidate_canonical_row_version_ids, value.consumed_canonical_row_version_ids,
                     value.status, value.reason_code) ==
                    (sample.sample_key, upstream.sample_version_id, spec.name, feature_label_spec_pin(spec),
                     registration.pin, upstream.request.feature_window_close, cutoff, build_ids,
                     candidates, candidates if reason is None else (),
                     "COMPLETE" if reason is None else "EXCLUDED", reason), code, "TS2 recorded value closure mismatch")
            if reason is None:
                numeric(value.value, "float64", code)
            else:
                require(value.value is None, code, "excluded TS2 value must be null")
            digest(value.value_id)
        require(sample.status == ("COMPLETE" if all(v.status == "COMPLETE" for v in values) else "EXCLUDED"),
                code, "TS2 aggregate status mismatch")
        digest(sample.sample_id)
        digest(sample.values_content_id)
    require(result.status == ("EMPTY" if not samples else "COMPLETE"
                             if all(s.status == "COMPLETE" for s in samples) else "EXCLUDED"),
            code, "TS2 execution status mismatch")
    digest(result.execution_id)
    digest(result.values_content_id)
    digest(result.samples_content_id)
    return samples
