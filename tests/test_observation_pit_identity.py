"""Frozen A3 known answers and independent typed payload reconstruction."""

from dataclasses import fields, replace

import pytest

from market_vault.dataset.encoding import encode_identity
from market_vault.observation.models import ObservationContractPin, ObservationDimension
from market_vault.observation import pit_identity as ids
from market_vault.observation.pit_models import (
    ObservationSnapshotPin, ObservationBuildPin, ObservationPITDecision, ObservationSampleBinding,
)
from test_observation_pit_models import artifacts, bar, binding, clock, source
from test_observation_pit import assemble


HASHES = tuple(f"{n:064x}" for n in range(101, 121))


def fixed_inputs():
    h = HASHES
    snapshot = ObservationSnapshotPin(h[0], h[1], "fixture-provider", "fixture-series", "provider-v1", h[2],
                                       h[3], "receipt", h[4], clock(97))
    build = ObservationBuildPin(h[5], h[6], "observation-schema-v1", h[7], clock(100), "COMPLETE", (h[8],),
                                (ObservationContractPin("provider-v1", h[2]),),
                                (ObservationContractPin("normalizer-v1", h[9]),), (snapshot,), (h[10],))
    declared = binding()
    decision = ObservationPITDecision(h[11], h[12], declared.feature_spec_pin_id, declared.observation_source_spec_id,
                                      clock(100), clock(100), ids.considered_observation_builds_digest((build,)),
                                      "COMPLETE", None, False, h[13], h[10], h[5], h[0], h[8],
                                      clock(95), clock(96), clock(97), 1, 0, 0, 1, 1)
    binding_id = ids.observation_binding_id((decision,))
    row = ObservationSampleBinding(h[11], h[12], binding_id,
                                    ids.multi_source_sample_version_id(h[11], h[12], binding_id))
    return snapshot, build, decision, row


def vector_values():
    snapshot, build, decision, row = fixed_inputs()
    sidecar = ids.observation_association_content_id((decision,))
    sample_content = ids.sample_binding_content_id((row,))
    return {
        "source_spec": ids.observation_source_spec_id(source()),
        "feature_pin": ids.feature_spec_pin_id(binding().feature_spec_pin),
        "snapshot_pin": ids.observation_snapshot_pin_id(snapshot),
        "build_pin": ids.observation_build_pin_id(build),
        "decision": ids.observation_decision_id(decision),
        "binding": row.observation_binding_id,
        "multi_source_sample_version": row.multi_source_sample_version_id,
        "sample_binding_content": sample_content,
        "sidecar_content": sidecar,
        "combined_content": ids.combined_association_content_id(HASHES[14], HASHES[15], sidecar, sample_content),
    }


EXPECTED = {
    "source_spec": "708b0e08f0cdbb4ae30bf056230e0b4e7bafc81fd179a7ef76e2905373ea5d0c",
    "feature_pin": "76f9b3cdc5bc559b4f333534416e6fe8a7c225acacdf2a8f58b4bb4527eafefe",
    "snapshot_pin": "5c0148950f1e662931791ed8d994b0d0d6eea51f60f4cb1c65fa65da67a39793",
    "build_pin": "25b482900a817879c427c1bee0a53ab8cd62a4b936d83a818cd3ce895477fdf9",
    "decision": "821944aeb3b3f9b9953d4bbff05013611448dcc42e0f50241935096cdeac79a6",
    "binding": "1c081bcff723a323fe5e86f0a776b208eb96e39e44d677bfa30a3ec86190d1a2",
    "multi_source_sample_version": "eb9996ed0a41b187d27a6b3d9a4715631b26003640010d359625088b672ee0af",
    "sample_binding_content": "efc2a0bde8e497cee19fac8b43d7232f6af0451e9a05e2d2457a304bf00dfe3d",
    "sidecar_content": "1a94b007fc62972b1436defd5c86dd178848ce06ea13773be9c37b925a3b248a",
    "combined_content": "67623968e36c49c9782a9de3f2f07075ff2bcf914ffdd6e3e36431a8dabb41b3",
}


def test_fixed_known_answers():
    assert vector_values() == EXPECTED


def test_source_payload_independently_matches_frozen_design():
    spec = source()
    def sequence(domain, hashes):
        hashes = tuple(hashes)
        return encode_identity(domain, {"count": len(hashes), "members": "".join(hashes)})
    payload = {f.name: getattr(spec, f.name) for f in fields(spec)
               if f.name not in {"dimensions", "input_field_names", "code_entity_map"}}
    payload["dimensions_digest"] = sequence("observation-source-dimensions-v1", (
        encode_identity("observation-source-dimension-v1", {"name": d.name, "logical_type": d.logical_type, "value": d.value})
        for d in spec.dimensions))
    payload["input_field_names_digest"] = sequence("observation-input-fields-v1", (
        encode_identity("observation-input-field-v1", {"name": n}) for n in spec.input_field_names))
    payload["code_entity_map_content_id"] = sequence("observation-entity-map-v1", ())
    assert ids.observation_source_spec_id(spec) == encode_identity("observation-source-spec-v1", payload)


@pytest.mark.parametrize("change", [
    {"provider_id": "other"}, {"source_kind": "other"}, {"observation_name": "other"}, {"entity_id": "other"},
    {"input_field_names": ("count", "rate")}, {"value_schema_id": "a" * 64},
    {"provider_contract_version": "other"}, {"provider_contract_content_id": "a" * 64},
    {"normalization_version": "other"}, {"normalization_content_id": "a" * 64},
    {"known_at_authority_policy_version": "other"}, {"known_at_authority_policy_content_id": "a" * 64},
    {"max_age_us": 11}, {"missing_policy": "FAIL"},
    {"alignment": "EXACT_EVENT_TIME", "exact_target_binding": "FEATURE_WINDOW_CLOSE"},
    {"dimensions": (ObservationDimension("variant", "int64", 2),)},
])
def test_every_source_semantic_affects_identity(change):
    assert ids.observation_source_spec_id(source(**change)) != ids.observation_source_spec_id(source())


def test_exact_target_affects_identity():
    one = source(alignment="EXACT_EVENT_TIME", exact_target_binding="FEATURE_WINDOW_START")
    assert ids.observation_source_spec_id(one) != ids.observation_source_spec_id(replace(one, exact_target_binding="FEATURE_WINDOW_CLOSE"))


@pytest.mark.parametrize("change", [{"max_age_us": 11}, {"missing_policy": "FAIL"}, {"input_field_names": ("count", "rate")}])
def test_canary_33_source_changes_propagate_without_economic_change(artifacts, change):
    build = artifacts()
    one, two = assemble((build,)), assemble((build,), spec=source(**change))
    assert one.decisions[0].selected_observation_version_id == two.decisions[0].selected_observation_version_id
    assert one.sample_bindings[0].multi_source_sample_version_id != two.sample_bindings[0].multi_source_sample_version_id
    assert one.combined_association_content_id != two.combined_association_content_id


def test_canary_33_unused_map_entry_is_identity_bearing(artifacts):
    one = source(entity_binding="SAMPLE_CODE", entity_id=None, code_entity_map=(("US.TEST", "fixture:entity"),))
    two = replace(one, code_entity_map=one.code_entity_map + (("US.UNUSED", "elsewhere"),))
    build = artifacts()
    before, after = assemble((build,), spec=one), assemble((build,), spec=two)
    assert before.decisions[0].selected_observation_key == after.decisions[0].selected_observation_key
    assert before.combined_association_content_id != after.combined_association_content_id
    assert ids.observation_source_spec_id(two) == ids.observation_source_spec_id(replace(two, code_entity_map=two.code_entity_map[::-1]))


def test_proof_clock_and_selected_version_pin_are_identity_bearing():
    snapshot, build, decision, row = fixed_inputs()
    assert ids.observation_build_pin_id(build) != ids.observation_build_pin_id(replace(build, coverage_proof_available_at=clock(101)))
    assert ids.observation_build_pin_id(build) != ids.observation_build_pin_id(replace(build, selected_observation_version_ids=()))
    assert ids.observation_snapshot_pin_id(snapshot) != ids.observation_snapshot_pin_id(replace(snapshot, completed_possession_at=clock(98)))
    assert ids.observation_decision_id(decision) != ids.observation_decision_id(replace(decision, scoped_version_count=2))
    assert len(set(vector_values().values())) == 10


def test_bar_authorities_remain_unchanged(artifacts):
    from market_vault.observation import assemble_observation_pit_sidecar
    bars = bar()
    before = (bars.samples[0].sample_key, bars.samples[0].sample_version_id,
              bars.association_content_id, bars.association_schema_id, bars.association_rows)
    result = assemble_observation_pit_sidecar(bars, (artifacts(),), (binding(),))
    assert before == (bars.samples[0].sample_key, bars.samples[0].sample_version_id,
                      bars.association_content_id, bars.association_schema_id, bars.association_rows)
    assert result.sample_bindings[0].bar_sample_version_id == bars.samples[0].sample_version_id
    assert result.bar_association_content_id == bars.association_content_id
    assert result.bar_association_schema_id == bars.association_schema_id
