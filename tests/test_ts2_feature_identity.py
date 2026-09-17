"""Six frozen design vector groups, with 49 literal expected digests."""

from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from market_vault.dataset.specs import feature_label_spec_content_id, feature_label_spec_pin
from market_vault.ts2_feature import identity as ids
from market_vault.ts2_feature.registry import _registry
from ts2_feature_helpers import spec

EXPECTED = {
    "candle_body.source_sha256": "818beb25bcae1773e64d27ddc9d53d4e7926d43ffc5a6477191602e02aea22ca",
    "candle_body.fingerprint": "f7052b2e5cb8b2698e95e0a7fc3535635c39a2f292423122ea3ad9d1fde565f8",
    "candle_body.implementation_pin_id": "4a9b5e89687fcac6edbbd02e87912c85c64799836af3010ad9297332012217dd",
    "candle_range.source_sha256": "dd9811e764ca4a8b5a2d82335dbcaa88ed6c7a9f4a498544ba63104f49dbf4b0",
    "candle_range.fingerprint": "fd85a80f628d7ecec2f396644c29d48094f3e3cec2375afc1706b94371f466a8",
    "candle_range.implementation_pin_id": "5b85ed91231955b7f0b5ecaa9f3d584210c9e28cd36d2dff0ae19ef3d0a0b687",
    "log_return.source_sha256": "4a1d6e4295ad33824020259c4653b74b087176ee5f40d2097f2a1aae7532e3fa",
    "log_return.fingerprint": "3fbdad819ee7d51a995474c94aba16e2333e611778b794c5246885fed66b69f2",
    "log_return.implementation_pin_id": "f938e63f485766459c6b378da97615fdbe5913b8f59cfe5ab734b39b55b0b60f",
    "rolling_mean.source_sha256": "97ee08de1d84e66bf362cd85c6f21aa15b09e5a2289fb5918476eb90bae8633f",
    "rolling_mean.fingerprint": "b1eafd9fd110ab5307bec4d6940a0c16a1eb21c108c38c5eb10c718b61bfafbc",
    "rolling_mean.implementation_pin_id": "f14cef9547f49b28a0b66b7ed41e82454cb7bfb43ad433681f641e02c0d4fb08",
    "rolling_std.source_sha256": "c5b1b4cd5d4a4eff35f3b05b754e41e9ac68968df47bb4f3af03fe711e41d830",
    "rolling_std.fingerprint": "1fa2edafb36ed62c1ed74567f7bfed87a60f46d3dc4bac7b8d98f5d35c584822",
    "rolling_std.implementation_pin_id": "bfcf14f5814a4efabc5737132413a0fb61194ada32720417cf23f48b8b680145",
    "rolling_volume_mean.source_sha256": "617bdd2685cf7485f89336241a2a3b4e6818c006c051ce775b8b6a607c1e81af",
    "rolling_volume_mean.fingerprint": "46ece8f194e40253f2ee527837b4c9be04c6791be5ae34507cf36397aeb14fa0",
    "rolling_volume_mean.implementation_pin_id": "d053c4ae596074cafb41ee53d7743712758fbbee3e232af09ffeb7f124c45491",
    "simple_return.source_sha256": "41345d65d910b01012a909b136dfb8681e33feb55d6b663628e301d3f0bcce32",
    "simple_return.fingerprint": "984589ae4cfe3471d72e1cf0438105dcd29360979ef89eb062a3d5c177c1c70e",
    "simple_return.implementation_pin_id": "55d3885db5b6eccdea45f2ad0baa41d170884c63bcb1bdf2f5bdd9f24f763782",
    "volume_ratio.source_sha256": "3a10650c63f2acf64912ad6bd2959ec0ba14f84f09cbfaa40f023f84e74ac919",
    "volume_ratio.fingerprint": "9dbad62831815638ba82d51608c9efc99b6131332c1b1c03d3670c2108c0da46",
    "volume_ratio.implementation_pin_id": "435f28696559ca2204997e76260403228a65cf6c150109bcf04afab6d5281d3b",
    "spec_content_id": "73dc26da80653a4959ff8a8f733cda416235f19e404fc6f995327d94fa387a40",
    "spec_pin_id": "908e88052dabd17e6efd045a1e8af5ebe4f5b97560fb7bbb193918ac3c0ee600",
    "spec_pins_digest": "b57a6f8a51d1e65780d44a980bfb7f86262a85b6dae6cbff9895cc80af95356c",
    "registry_pins_digest": "2f59d9a2d8b01316f46d97ad084b924ae6b97fbee40506c114c31b982f2fbd5f",
    "considered_builds_digest": "ee9387846c20f93cb412b1ad8a6bf586f15dbe721eac2847407581a180d501ec",
    "input_rows_digest": "e74426c75d468d6b851c6099950e4f284b09397b7bab9af11b80f284e63f4965",
    "empty.ts2-feature-considered-builds-v1": "a208644d37cfbf0cfd3afd066ea2cbe6a2c93b4be8167bdbd725a2e3ed3a4340",
    "empty.ts2-feature-input-rows-v1": "8fd862f5fd4d753d0fc7ffb490f799f0d3232e31f91f8fde2e8c17575975d3da",
    "empty.ts2-feature-spec-pins-v1": "c2f913489fa2030d0e9ac6440e6c34ed3932f93bacdd7c0d9f2052d8b3caee0e",
    "empty.ts2-feature-values-v1": "14abd339a978e6be2dc75f032ac8aca36b70b90cc33d8258662fb15a680a9e7e",
    "empty.ts2-feature-samples-v1": "db9e774d9acf4aba198070e96acd55e85a5bf6bc76aea2bc9180128986d1b389",
    "complete.value_id": "73d10788fec5259e94b3494172b32cf716042d84f83f60415426c3e9d70f8e6f",
    "complete.values_content_id": "5fd7745f3d1699d2313753d26b8de05f4fee82f85ca4d090aa875bafb7713f43",
    "complete.sample_id": "b869236fbc5bae51803d1a6d6210d3c620e6b448d5536e0b15ea5abcfd06d9f2",
    "complete.samples_content_id": "3c0060e325ebf0cbfe4edb7f3d95b206838c0cc946ef5fed66019259a430809b",
    "complete.execution_id": "b29d49174d4ebcac5ead385dc94e98c3400066b90f24928889a3d7d8b3af798e",
    "excluded.value_id": "070b2c1665a469a2c454d8fac2e837246fb543c1e32df9c9c60ff76df4de9823",
    "excluded.values_content_id": "a8207e7a3eb557a17c7ea0103b47dee7f2715e808e17d13a3a9625a3edaf01d5",
    "excluded.sample_id": "c868cae29df9b5c94e013475ef93cabf15ab878c8d61eeace9dc4d45f19288db",
    "excluded.samples_content_id": "04cd1c4a69a663781c23db5925d3c5e397e31192e073340a78e2594d252310ae",
    "excluded.execution_id": "afb4da567c49a0ff073b8901952c8e4d8ec33efcd87b828886c636fb57333ef9",
    "zero_samples.execution_id": "eedfdac0687b129851023361fad9fdc8e8add3d0851fe25df6f98f9b78f4077c",
    "zero_specs.sample_id": "fa873cbb61d1ac0d277dc84a325aa67547bae4d74e758a379613c15239963d9a",
    "zero_specs.samples_content_id": "5d2595b6454d0e2f228b999c4229c0827934fafefcf5247d7a43a9928ea893e2",
    "zero_specs.execution_id": "437f0a8f954bc13bee9f756ea960dc6e2c3654b315f16c72b0586eae2698ec2e",
}


@pytest.fixture(scope="module")
def actual():
    result = {}
    regs = _registry()
    for reg in regs:
        name = reg.contract.name
        result[name + ".source_sha256"] = reg.source_sha256
        result[name + ".fingerprint"] = reg.pin.content_sha256
        result[name + ".implementation_pin_id"] = ids.implementation_pin_id(reg.pin)
    feature = spec(name="ts2_return")
    pin = feature_label_spec_pin(feature)
    result.update(spec_content_id=feature_label_spec_content_id(feature), spec_pin_id=ids.spec_pin_id(pin),
        spec_pins_digest=ids.spec_pins_digest((pin,)), registry_pins_digest=ids.registry_pins_digest(tuple(r.pin for r in regs)),
        considered_builds_digest=ids.considered_builds_digest(("1" * 64, "2" * 64)),
        input_rows_digest=ids.input_rows_digest(("3" * 64, "4" * 64)))
    for domain in ("ts2-feature-considered-builds-v1", "ts2-feature-input-rows-v1", "ts2-feature-spec-pins-v1",
                   "ts2-feature-values-v1", "ts2-feature-samples-v1"):
        result["empty." + domain] = ids.sequence_id(domain, ())
    common = dict(execution_contract_version="ts2-feature-execution-v1", sample_key="5" * 64,
        bar_sample_version_id="6" * 64, feature_name="ts2_return", feature_spec_pin_id=result["spec_pin_id"],
        implementation_pin_id=result["simple_return.implementation_pin_id"],
        feature_window_close=datetime(2026, 1, 5, 14, 32, tzinfo=timezone.utc),
        dataset_as_of=datetime(2026, 1, 6, 22, tzinfo=timezone.utc),
        considered_canonical_build_ids_digest=result["considered_builds_digest"])
    for case in ("complete", "excluded"):
        complete = case == "complete"
        value = dict(common, status="COMPLETE" if complete else "EXCLUDED", value=0.25 if complete else None,
            reason_code=None if complete else "INSUFFICIENT_ROWS",
            candidate_row_version_ids_digest=ids.input_rows_digest(("3" * 64, "4" * 64) if complete else ("3" * 64,)),
            consumed_row_version_ids_digest=ids.input_rows_digest(("3" * 64, "4" * 64) if complete else ()))
        vid = ids.value_id(value)
        values = ids.sequence_id("ts2-feature-values-v1", (vid,))
        sid = ids.sample_id(dict(sample_key="5" * 64, bar_sample_version_id="6" * 64,
                                 status=value["status"], values_content_id=values))
        samples = ids.sequence_id("ts2-feature-samples-v1", (sid,))
        execution = dict(execution_contract_version="ts2-feature-execution-v1", registry_contract_version="ts2-feature-registry-v1",
            feature_association_content_id="7" * 64, feature_association_schema_id="8" * 64,
            dataset_as_of=common["dataset_as_of"], considered_canonical_build_ids_digest=result["considered_builds_digest"],
            feature_spec_pins_digest=result["spec_pins_digest"], registry_implementation_pins_digest=result["registry_pins_digest"],
            sample_count=1, feature_count=1, status=value["status"], values_content_id=values, samples_content_id=samples)
        result.update({case + ".value_id": vid, case + ".values_content_id": values, case + ".sample_id": sid,
                       case + ".samples_content_id": samples, case + ".execution_id": ids.execution_id(execution)})
    execution.update(status="EMPTY", sample_count=0, values_content_id=result["empty.ts2-feature-values-v1"],
                     samples_content_id=result["empty.ts2-feature-samples-v1"])
    result["zero_samples.execution_id"] = ids.execution_id(execution)
    sid = ids.sample_id(dict(sample_key="5" * 64, bar_sample_version_id="6" * 64, status="COMPLETE",
                             values_content_id=result["empty.ts2-feature-values-v1"]))
    result["zero_specs.sample_id"] = sid
    result["zero_specs.samples_content_id"] = ids.sequence_id("ts2-feature-samples-v1", (sid,))
    execution.update(status="COMPLETE", sample_count=1, feature_count=0,
        feature_spec_pins_digest=result["empty.ts2-feature-spec-pins-v1"], samples_content_id=result["zero_specs.samples_content_id"])
    result["zero_specs.execution_id"] = ids.execution_id(execution)
    assert len(result) == len(EXPECTED) == 49
    return result


@pytest.mark.parametrize("name", tuple(EXPECTED))
def test_frozen_digest(name, actual):
    assert actual[name] == EXPECTED[name]
