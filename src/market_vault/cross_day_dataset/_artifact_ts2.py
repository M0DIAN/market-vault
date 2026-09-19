"""Recorded TS2 closure and exact sealed identities, never TS2 issuance/execution."""

from datetime import timedelta

from ..dataset.specs import feature_label_spec_pin
from ..ts2_feature import identity as ids
from ..ts2_feature.execution import _specs, _resolve
from ..ts2_feature.registry import _registry, TS2_FEATURE_EXECUTION_CONTRACT_VERSION, TS2_FEATURE_REGISTRY_CONTRACT_VERSION
from ..ts2_feature._validation import finite_float
from ._artifact_canonical import _check, _ordered, _view, _INTERVALS
from ._artifact_records import _encode_record
from ._artifact_values import _value
from ._validation import numeric


def _ts2_closure(record, pit, builds, rows, cutoff):
    _encode_record(record, "TS2Features")
    specs = tuple(_value(s) for s in record.feature_specs)
    _check(specs == _specs(specs) and bool(specs), "TS2 canonical nonempty specs required")
    registrations = _registry()
    resolved = _resolve(specs, registrations)
    expected_hashes = tuple((r.contract.transform_ref, r.source_sha256)
                            for r in sorted(registrations, key=lambda r: r.contract.transform_ref))
    _check(tuple((p.transform_ref, p.source_sha256) for p in record.implementation_source_hashes) == expected_hashes,
           "TS2 implementation source hashes differ")
    pins = tuple(feature_label_spec_pin(s) for s in specs)
    registry_pins = tuple(sorted((r.pin for r in registrations), key=ids.implementation_pin_id))
    _check(tuple(_value(p) for p in record.feature_spec_pins) == pins
           and tuple(_value(p) for p in record.registry_implementation_pins) == registry_pins, "TS2 fixed spec/registry pins differ")
    build_ids = tuple(b.canonical_build_id for b in builds)
    _check((record.execution_contract_version, record.registry_contract_version,
            record.feature_association_schema_id, record.feature_association_content_id,
            record.dataset_as_of, record.considered_canonical_build_ids) ==
           (TS2_FEATURE_EXECUTION_CONTRACT_VERSION, TS2_FEATURE_REGISTRY_CONTRACT_VERSION,
            pit.association_schema_id, pit.association_content_id, cutoff, build_ids), "TS2 input/PIT linkage mismatch")
    _ordered(record.samples, lambda s: s.sample_key, "TS2 samples")
    _check(tuple(s.sample_key for s in record.samples) == tuple(s.sample_key for s in pit.samples), "TS2 sample set differs")
    samples = []
    for sample, upstream in zip(record.samples, pit.samples):
        _check(sample.bar_sample_version_id == upstream.sample_version_id and len(sample.values) == len(pins),
               "TS2 sample version/value cardinality mismatch")
        values = []
        full = upstream.feature_canonical_row_version_ids
        for value, (spec, registration, count), pin in zip(sample.values, resolved, pins):
            available = min(len(full), count)
            candidates = full[-available:] if available else ()
            reason = "INSUFFICIENT_ROWS" if len(full) < count else None
            interval = timedelta(minutes=_INTERVALS[upstream.request.interval])
            if reason is None and any(rows[b].bar.event_time - rows[a].bar.event_time != interval
                                      for a, b in zip(candidates, candidates[1:])):
                reason = "NON_CONTIGUOUS_ROWS"
            # Rows outside a shorter spec tail still belong to full Feature authority.
            for version in full:
                for field in registration.contract.fields:
                    finite_float(getattr(rows[version].bar, field), "CANONICAL_AUTHORITY")
            spec_pin, implementation_pin = _value(value.spec_pin), _value(value.implementation_pin)
            _check((value.sample_key, value.bar_sample_version_id, value.feature_name, spec_pin, implementation_pin,
                    value.feature_window_close, value.dataset_as_of, value.considered_canonical_build_ids,
                    value.candidate_canonical_row_version_ids, value.consumed_canonical_row_version_ids,
                    value.status, value.reason_code) ==
                   (sample.sample_key, upstream.sample_version_id, spec.name, pin, registration.pin,
                    upstream.request.feature_window_close, cutoff, build_ids, candidates,
                    candidates if reason is None else (), "COMPLETE" if reason is None else "EXCLUDED", reason),
                   "TS2 recorded candidate/consumed/status closure mismatch")
            if reason is None:
                numeric(value.value, "float64", "TS2_FEATURE_BINDING")
            else:
                _check(value.value is None, "excluded TS2 value is not null")
            payload = dict(execution_contract_version=TS2_FEATURE_EXECUTION_CONTRACT_VERSION,
                sample_key=value.sample_key, bar_sample_version_id=value.bar_sample_version_id,
                feature_name=value.feature_name, feature_spec_pin_id=ids.spec_pin_id(spec_pin),
                implementation_pin_id=ids.implementation_pin_id(implementation_pin),
                feature_window_close=value.feature_window_close, dataset_as_of=value.dataset_as_of,
                considered_canonical_build_ids_digest=ids.considered_builds_digest(build_ids),
                candidate_row_version_ids_digest=ids.input_rows_digest(candidates),
                consumed_row_version_ids_digest=ids.input_rows_digest(value.consumed_canonical_row_version_ids),
                status=value.status, value=value.value, reason_code=value.reason_code)
            values.append(_view(**{k: v for k, v in value._items if k not in ("spec_pin", "implementation_pin")},
                                spec_pin=spec_pin, implementation_pin=implementation_pin, value_id=ids.value_id(payload)))
        values = tuple(values)
        status = "COMPLETE" if all(v.status == "COMPLETE" for v in values) else "EXCLUDED"
        _check(sample.status == status, "TS2 sample aggregate status mismatch")
        content_id = ids.values_content_id(values)
        sample_id = ids.sample_id(dict(sample_key=sample.sample_key, bar_sample_version_id=sample.bar_sample_version_id,
                                      status=status, values_content_id=content_id))
        samples.append(_view(sample_key=sample.sample_key, bar_sample_version_id=sample.bar_sample_version_id,
                             values=values, status=status, values_content_id=content_id, sample_id=sample_id))
    samples = tuple(samples)
    status = "EMPTY" if not samples else "COMPLETE" if all(s.status == "COMPLETE" for s in samples) else "EXCLUDED"
    _check(record.status == status, "TS2 execution aggregate status mismatch")
    values_id = ids.values_content_id(tuple(v for s in samples for v in s.values))
    samples_id = ids.samples_content_id(samples)
    execution_id = ids.execution_id(dict(execution_contract_version=record.execution_contract_version,
        registry_contract_version=record.registry_contract_version, feature_association_content_id=record.feature_association_content_id,
        feature_association_schema_id=record.feature_association_schema_id, dataset_as_of=cutoff,
        considered_canonical_build_ids_digest=ids.considered_builds_digest(build_ids),
        feature_spec_pins_digest=ids.spec_pins_digest(pins), registry_implementation_pins_digest=ids.registry_pins_digest(registry_pins),
        sample_count=len(samples), feature_count=len(specs), status=status, values_content_id=values_id, samples_content_id=samples_id))
    return _view(execution_contract_version=record.execution_contract_version, registry_contract_version=record.registry_contract_version,
        feature_association_content_id=record.feature_association_content_id, feature_association_schema_id=record.feature_association_schema_id,
        dataset_as_of=cutoff, considered_canonical_build_ids=build_ids, feature_specs=specs, feature_spec_pins=pins,
        registry_implementation_pins=registry_pins, samples=samples, status=status,
        execution_id=execution_id, values_content_id=values_id, samples_content_id=samples_id)
