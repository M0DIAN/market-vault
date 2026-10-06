"""Six frozen design vector groups, with 82 literal expected digests."""

from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from market_vault.dataset.specs import feature_label_spec_content_id, feature_label_spec_pin
from market_vault.ts2_feature import identity as ids
from market_vault.ts2_feature.registry import _registry, _registry_for_specs
from ts2_feature_helpers import spec

EXPECTED = {
    "atr.source_sha256": "f0d0540a6d173bcf8e5be36c35fd3ff85a37263e9b872ba33850ab854600988f",
    "atr.fingerprint": "33df32f2a6149bea5000e6558d2b7fb33e2695bc304cb385ba3a37819fccace6",
    "atr.implementation_pin_id": "698228b992aaf59bc278ef514da8d832caa95f328c38ca6b6cb2fad3712dc69c",
    "candle_body.source_sha256": "818beb25bcae1773e64d27ddc9d53d4e7926d43ffc5a6477191602e02aea22ca",
    "candle_body.fingerprint": "f7052b2e5cb8b2698e95e0a7fc3535635c39a2f292423122ea3ad9d1fde565f8",
    "candle_body.implementation_pin_id": "4a9b5e89687fcac6edbbd02e87912c85c64799836af3010ad9297332012217dd",
    "candle_range.source_sha256": "dd9811e764ca4a8b5a2d82335dbcaa88ed6c7a9f4a498544ba63104f49dbf4b0",
    "candle_range.fingerprint": "fd85a80f628d7ecec2f396644c29d48094f3e3cec2375afc1706b94371f466a8",
    "candle_range.implementation_pin_id": "5b85ed91231955b7f0b5ecaa9f3d584210c9e28cd36d2dff0ae19ef3d0a0b687",
    "ema.source_sha256": "c40affba9a8186174733eb5496cd3cea0cc58e4593988ce3ec81308fdb735b84",
    "ema.fingerprint": "329b4c265cde6a050d770c4a422574740eef2f4b3f0e2a697134f66f7e598033",
    "ema.implementation_pin_id": "562071902ed8890dbc2b154cfa12e9be2e81deb74507eaf8860fa7adb7c93690",
    "kdj_d.source_sha256": "ff3ab26c27602b3874e232e27f238f8f56fed7cd2a06f3ce9f809217c4836957",
    "kdj_d.fingerprint": "ef7934ae2e450069a2d67dfaac94d2c1ccac56f9c4fc8ef674495d9f5132f8fd",
    "kdj_d.implementation_pin_id": "d561a22bebfe48b884fad8c0f3f4a11caf2946c10c8cb9ecc76af902cd3af9eb",
    "kdj_j.source_sha256": "3afd9bf3a6e6995c0b14cb20688fbc255e9127427cd1e053b75399cdf1f50eca",
    "kdj_j.fingerprint": "93eab948c3ad4f5370b8537b82e2f2affa592ba1bafe91b76364c319808b9388",
    "kdj_j.implementation_pin_id": "94810ee70fea5ec3faae54dc535ad8024813cc3191ef7013ac58c0d5565d77ae",
    "kdj_k.source_sha256": "9a9535ae1c646b696d4f8904db94bdad7bfeb61aad60d984d867adc79bafeea8",
    "kdj_k.fingerprint": "f4049d8f6010771fc1afc32e7656963668e720ce94757305139c2aff89e9becb",
    "kdj_k.implementation_pin_id": "57966885cffae76f04c679e6b2011d054097f5e90dc29080d0c3e6799fdf94b2",
    "log_return.source_sha256": "4a1d6e4295ad33824020259c4653b74b087176ee5f40d2097f2a1aae7532e3fa",
    "log_return.fingerprint": "3fbdad819ee7d51a995474c94aba16e2333e611778b794c5246885fed66b69f2",
    "log_return.implementation_pin_id": "f938e63f485766459c6b378da97615fdbe5913b8f59cfe5ab734b39b55b0b60f",
    "macd.source_sha256": "3b8fe2b5fb86946205b4c4fde2f463246b39c555925e0f187e89c475546ff0ce",
    "macd.fingerprint": "b04f0738db2b8374fbf63af6d86378ac923de193340abb712a35f5bc65604557",
    "macd.implementation_pin_id": "e6a06892e574abec1b2233bf6a8ccf7565c428c94408ffc13645b584e2be72c4",
    "macd_histogram.source_sha256": "6b245883888b33656a23c5d29e1f6937fb4cf2bab1e047ba4789fe5c3b13290e",
    "macd_histogram.fingerprint": "146e1c7851b316701f2f8cb5d11e6f049aa20062e77d86f6394c5f976595290c",
    "macd_histogram.implementation_pin_id": "b9deb77e46448f3f635503e8a09ae19e729cc688f021b25c22f09fdf014469be",
    "macd_signal.source_sha256": "18df94e6bbd226dff3e4376820a35dd62a4ee5414d437574a2e416971fb4542c",
    "macd_signal.fingerprint": "087470ac56390b1a793e384c9a749f221b3f61be488e7c663c1262d6b13d6322",
    "macd_signal.implementation_pin_id": "978e807fffe1a40d38e5c6f6e09409f6fdf112975636889c1ebd4e3618e59145",
    "obv.source_sha256": "f512a36262d5a84801d2b7cf0e374f4f360c0b2739a073f88dd0d805d005e26f",
    "obv.fingerprint": "46df95e539d332f67cc6d660f2bc808e431c713bbcc21878173a40a276a4af0c",
    "obv.implementation_pin_id": "65459c768046c747a26b0869823e4a97da41a487539017432f0aeeb881a84b48",
    "rolling_mean.source_sha256": "97ee08de1d84e66bf362cd85c6f21aa15b09e5a2289fb5918476eb90bae8633f",
    "rolling_mean.fingerprint": "b1eafd9fd110ab5307bec4d6940a0c16a1eb21c108c38c5eb10c718b61bfafbc",
    "rolling_mean.implementation_pin_id": "f14cef9547f49b28a0b66b7ed41e82454cb7bfb43ad433681f641e02c0d4fb08",
    "rolling_std.source_sha256": "c5b1b4cd5d4a4eff35f3b05b754e41e9ac68968df47bb4f3af03fe711e41d830",
    "rolling_std.fingerprint": "1fa2edafb36ed62c1ed74567f7bfed87a60f46d3dc4bac7b8d98f5d35c584822",
    "rolling_std.implementation_pin_id": "bfcf14f5814a4efabc5737132413a0fb61194ada32720417cf23f48b8b680145",
    "rolling_volume_mean.source_sha256": "617bdd2685cf7485f89336241a2a3b4e6818c006c051ce775b8b6a607c1e81af",
    "rolling_volume_mean.fingerprint": "46ece8f194e40253f2ee527837b4c9be04c6791be5ae34507cf36397aeb14fa0",
    "rolling_volume_mean.implementation_pin_id": "d053c4ae596074cafb41ee53d7743712758fbbee3e232af09ffeb7f124c45491",
    "rsi.source_sha256": "cdc6b6aa0f61f209c9941b13e464ac917c88cd8be1da562dc620616a347e8773",
    "rsi.fingerprint": "e38091714689d1cb234085f9ec34f20d04e08ee56e7c1fe177754693bc2262d2",
    "rsi.implementation_pin_id": "7a78bcea7a872ec642ecd8229beacfa5ab7d99590808bbcc5ba6de8f5765b28a",
    "simple_return.source_sha256": "41345d65d910b01012a909b136dfb8681e33feb55d6b663628e301d3f0bcce32",
    "simple_return.fingerprint": "984589ae4cfe3471d72e1cf0438105dcd29360979ef89eb062a3d5c177c1c70e",
    "simple_return.implementation_pin_id": "55d3885db5b6eccdea45f2ad0baa41d170884c63bcb1bdf2f5bdd9f24f763782",
    "sma.source_sha256": "43ce631f5ca4e4e4f7b7227bb6469f1a7e481f0c40bc253947046538134fd5a1",
    "sma.fingerprint": "51ff0a17138d37c437e6f79207dee5fdcf5bd9f19d3f1ed32292413300022af2",
    "sma.implementation_pin_id": "c73d94c3051b5764a46d0e986ef869491e1bc8d68eb632013d8c037b2e68f12d",
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
        spec_pins_digest=ids.spec_pins_digest((pin,)),
        registry_pins_digest=ids.registry_pins_digest(
            tuple(r.pin for r in _registry_for_specs((feature,)))
        ),
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
    assert len(result) == len(EXPECTED) == 82
    return result


@pytest.mark.parametrize("name", tuple(EXPECTED))
def test_frozen_digest(name, actual):
    assert actual[name] == EXPECTED[name]
