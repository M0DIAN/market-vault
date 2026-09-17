"""Literal corrected L1 section 10 known-answer vectors (53 assertions)."""

from dataclasses import replace
from datetime import timedelta

import pytest

from market_vault.cross_day import identity as ids
from market_vault.cross_day.models import (
    CrossDayLabelSlot, CrossDayLabelRowReference, CrossDayLabelDecision,
    CrossDayLabelSampleBinding, CrossDayLabelValueResult,
)
from market_vault.cross_day.registry import built_in_cross_day_label_registry
from market_vault.dataset.specs import feature_label_spec_pin
from cross_day_helpers import schedule, spec, ARCHIVE, AS_OF

# Copied from the frozen corrected document, not calculated during tests.
EXPECTED = {
    "normal_forward/schedule_content_id": "67ea16fb43732c78e2788b3ffc110fc312adada93d947a9c3a8037502021db97",
    "normal_forward/schedule_pin_id": "f30ca764e588ed71a8c566b5168372b96e9cfd299341153883001d90c9eebf59",
    "normal_forward/decision_id": "77803870ab9ea1421d52cc1048fbae5fa6a922e8effb6be6c112c1986d62e8f8",
    "normal_forward/sample_binding_id": "a8713202ac7a91caef0271a20d3406d0a4b7a3a3a5478db61c79905a76dcf1b6",
    "normal_forward/association_content_id": "e48ce76a7d50260d63b9523a3987e32100ccc197fe75b04bdadbee1f8d0e1496",
    "normal_forward/value_id": "e99f98535617ab49d59837f3b3022127ec71ebf64d4cdae344fe875f4170042e",
    "normal_forward/values_content_id": "f14a39c92faacf484959f01c787678c3153cc2f07b836973349944fd462ce375",
    "weekend_forward/schedule_content_id": "bd32dfce1e05f35cdd9640170e702b85935d73514e0e63f5e225dfec71a4746f",
    "weekend_forward/schedule_pin_id": "c6b7c28974a8782e739604351b14eec8d8c3417f75cccb88ceb75e7294ad4698",
    "weekend_forward/decision_id": "a95200a8ac494e72d1f4682703b13900f055624eaadd9fdbc8cd0083681ea623",
    "weekend_forward/sample_binding_id": "83573d2409740e37e749de1d903efd790a61f83b201d19cfda008aa6e4431246",
    "weekend_forward/association_content_id": "1509cb6490291730fadd83a70203073ecd0f17585b7844074177fb0c552b7849",
    "weekend_forward/value_id": "821bac62ff8b8ada182957c37e9ac1be41d8a0dee42037c5970adb6713b47fb3",
    "weekend_forward/values_content_id": "21b017b87b76474b3df882ffc0d0ceb8dc74c285877d6cff7c247d12bee6bfee",
    "dst_forward/schedule_content_id": "454a7c2d7f5606a4d35ead2e910734ea747803852301a2dd2c4f71f0bf64760a",
    "dst_forward/schedule_pin_id": "7396839cea714c5dd74fe78265cf0c3919b342ecd36e71a27210f26c9364d016",
    "dst_forward/decision_id": "c38a66980cd52455a94f1826e96b7c1ff7179cb6b4f58f9ae8588f544580297f",
    "dst_forward/sample_binding_id": "5c3cd0018fe9b863439621b8a8a8d379ac5c923165a94c6c7c74abcf4807a07b",
    "dst_forward/association_content_id": "740167306227bf0bb550ac2ae3b5fa5ebed27cce155ca1a4eb7d74daf3ac27a8",
    "dst_forward/value_id": "c22426a36bfe3e684ac8a80912bf4802e940a373af9047154c922744faed24f0",
    "dst_forward/values_content_id": "f30a8c6c29ad2a367c79bfc1f136270e014da8ae66941439552e6346c6efba12",
    "early_close_fit/schedule_content_id": "f3abdf136b1eafb13dfde7c282b52b3f4864fc794b2788b520554cae7f45e55b",
    "early_close_fit/schedule_pin_id": "53083b15124ecafaaee848bbbb2c313be017789fd5869c69ad5281006ea741be",
    "early_close_fit/decision_id": "dc563bfb2fa5d46ebd05528240b6b3d388a0e5cbeb0faabc0117c4f0c832223d",
    "early_close_fit/sample_binding_id": "e72b0974ae1a17d6675ce679659066950ec02920d659dbe2e409d494a3bd636d",
    "early_close_fit/association_content_id": "3b40666940ef6c946a021cca338d01f35f5c93b8b66764166bd8f7d241d987d5",
    "early_close_fit/value_id": "67236c30a5b8623c2d26c13c87983f52245defb6c73e5e5cd2abcb0cedf45f32",
    "early_close_fit/values_content_id": "042e5cbdfd936ddd2e12dcc6c1ce5aafdcfe71cc9f2221b08755acd0ef5ff2d6",
    "early_close_outside/schedule_content_id": "f3abdf136b1eafb13dfde7c282b52b3f4864fc794b2788b520554cae7f45e55b",
    "early_close_outside/schedule_pin_id": "53083b15124ecafaaee848bbbb2c313be017789fd5869c69ad5281006ea741be",
    "early_close_outside/decision_id": "891b2a4cb2217413f19de0f0547d53cd92011eb2cd267c79e4597e612c3c9234",
    "early_close_outside/sample_binding_id": "23a6b95c65d3e235e9d0de8730cab7f6aa97d014c8855c826eb06a80858a5e77",
    "early_close_outside/association_content_id": "a16514868565d9292ff26259c9fe70d6419e02cd48960842991e89693a79478c",
    "early_close_outside/value_id": "a78300c94c2b96146e095a75541323861f180c68a5a2502286b03d8168735a78",
    "early_close_outside/values_content_id": "35bbaa011e49c573e0af9b4ab3b7b1736e623937b4a283d0d835f6a54e4989cc",
    "two_day_excursion/schedule_content_id": "8838e4b875dc645d00e5c5c5bce328e8a1d88445aac0edeaa244b56a280d3f9f",
    "two_day_excursion/schedule_pin_id": "eef0dae7db5c40db169faf2b7efb6abc0e1bd32424e210061bbd9f7f67b6b220",
    "two_day_excursion/decision_id": "e1b43ca21246a732277a17ae8c1b2d2b1871d028f26f5d119ae9fcea94c6d695",
    "two_day_excursion/sample_binding_id": "d113ee779d336df4f57eeaa6de2a844bd873eb7514a9e2243d00e9539add04dc",
    "two_day_excursion/association_content_id": "33f61b63bb6dae600e664aa910b01980417f832d6631237f7e609820762fef69",
    "two_day_excursion/value_id": "35667712e0ebefe26c52bb7ce76a569019ac2837b220eb2a60e29529318c6cb2",
    "two_day_excursion/values_content_id": "86f71d44839d550cbb7a8b451232183d51a8f06779c7bf2e94b68d89d642f42a",
    "forward/spec_content_id": "24a51fc0571178f9ec9427f4efb9a11b94203224858c22685f9001472d1e3d3f",
    "forward/spec_pin_id": "e6aa62e8bc6eb55b982726a4705563fdf037f47e2ba764e603cf4121ace32d1b",
    "forward/source_sha256": "1c898213eedfbfa2055d1d8fe0b69174341d0741b616aa6409581fb012efb705",
    "forward/implementation_fingerprint": "01baec853ca344d36c3dcdf6db3a7573cc0c2b7c382ea345cacb05e90345a6c1",
    "forward/implementation_pin_id": "0befd4a9a4d6a1a3b2c47bd13d88d98eedd252dcdc6c88e63035037a9a1aef94",
    "excursion/spec_content_id": "01f5e037321de5658f5663ecb5b32f6dcf43e8a65990befd04974a7e6abe569b",
    "excursion/spec_pin_id": "d3a2019e74a63eb831367b1de0899dcd3d651940127f0d09b211391cf4ad3394",
    "excursion/source_sha256": "5dc08788468c032a842fb4c978f38f7d73672127e159c7002539b373076dcf93",
    "excursion/implementation_fingerprint": "44427fafe75ab0e395f9a277c8b4ec2db42be7887d6e09b70c80495411c16354",
    "excursion/implementation_pin_id": "8d0adca923e88533720d96cb4405c7b40a22f35206b7e1acdbc6970f62ea711c",
    "empty/values_content_id": "09eaf5af35f95b39ceebc880cec24e1f9c15dfbf5176a9b5c18c4e43cb6b0c41"
}

SCENARIOS = (
    ("normal_forward", (("2025-03-03", "N"), ("2025-03-04", "N")), 1, False),
    ("weekend_forward", (("2025-02-07", "N"), ("2025-02-08", "C"), ("2025-02-09", "C"), ("2025-02-10", "N")), 1, False),
    ("dst_forward", (("2025-03-07", "N"), ("2025-03-08", "C"), ("2025-03-09", "C"), ("2025-03-10", "N")), 1, False),
    ("early_close_fit", (("2025-11-26", "N"), ("2025-11-27", "C"), ("2025-11-28", "E")), 1, False),
    ("early_close_outside", (("2025-11-26", "N"), ("2025-11-27", "C"), ("2025-11-28", "E")), 48, False),
    ("two_day_excursion", (("2025-03-03", "N"), ("2025-03-04", "N"), ("2025-03-05", "N")), 1, True),
)


def opaque_case(daily, slot, excursion, registry):
    sched = schedule(daily)
    label = spec(2, "maximum_favorable_excursion") if excursion else spec()
    reg = next(r for r in registry if r.transform_ref == label.transform_ref)
    pin_id = ids.schedule_pin_id(sched.pin)
    anchor_event = sched.daily_records[0].session_open + timedelta(minutes=5 * slot)
    close = anchor_event + timedelta(minutes=5)
    anchor = CrossDayLabelRowReference(-1, "d" * 64, "e" * 64, ("c" * 64,), anchor_event, close, ARCHIVE)
    slots, rows = [], []
    for k, day in enumerate(d for d in sched.daily_records[1:] if d.day_status == "TRADING"):
        event = day.session_open + timedelta(minutes=5 * slot)
        fits = event + timedelta(minutes=5) <= day.session_close
        slots.append(CrossDayLabelSlot(k, day.market_calendar_date, event, day.session_open, day.session_close, fits))
        if fits:
            rows.append(CrossDayLabelRowReference(k, format(100 + k, "064x"), format(200 + k, "064x"),
                                                  ("c" * 64,), event, event + timedelta(minutes=5), ARCHIVE))
    status = "COMPLETE" if all(s.slot_fits for s in slots) else "INCOMPLETE"
    reason = None if status == "COMPLETE" else "ALIGNED_SLOT_OUTSIDE_SESSION"
    end = rows[-1].market_available_at if rows else None
    decision = CrossDayLabelDecision("a" * 64, "b" * 64, ids.label_spec_pin_id(label), pin_id, AS_OF,
        "US.AAPL", "5m", "NONE", "RTH", close, sched.coverage_start_date, anchor_event, slot, anchor,
        tuple(slots), ("c" * 64,), tuple(rows), (), (), status, reason, False, end)
    binding = CrossDayLabelSampleBinding("a" * 64, "b" * 64, None, pin_id, (decision.decision_id,))
    value = CrossDayLabelValueResult("a" * 64, "b" * 64, None, label.name, feature_label_spec_pin(label),
        reg.implementation_pin, pin_id, decision.decision_id, "e" * 64, tuple(rows), status,
        (0.5 if excursion else 0.25) if status == "COMPLETE" else None, reason, end)
    return dict(schedule_content_id=sched.schedule_content_id, schedule_pin_id=pin_id,
        decision_id=decision.decision_id, sample_binding_id=binding.sample_binding_id,
        association_content_id=ids.association_content_id(sched.pin, (label,), ("c" * 64,), (decision,), (binding,)),
        value_id=value.value_id, values_content_id=ids.values_content_id((value,)))


@pytest.fixture(scope="module")
def actual_vectors():
    registry = built_in_cross_day_label_registry()
    actual = {}
    for name, daily, slot, excursion in SCENARIOS:
        actual.update({name + "/" + key: value for key, value in opaque_case(daily, slot, excursion, registry).items()})
    for name, label in (("forward", spec()), ("excursion", spec(2, "maximum_favorable_excursion"))):
        reg = next(r for r in registry if r.transform_ref == label.transform_ref)
        actual.update({name + "/" + k: v for k, v in dict(
            spec_content_id=feature_label_spec_pin(label).content_sha256,
            spec_pin_id=ids.label_spec_pin_id(label), source_sha256=reg.implementation_source_sha256,
            implementation_fingerprint=reg.implementation_pin.content_sha256,
            implementation_pin_id=ids.implementation_pin_id(reg.implementation_pin)).items()})
    actual["empty/values_content_id"] = ids.values_content_id(())
    assert len(actual) == len(EXPECTED) == 53
    return actual


@pytest.mark.parametrize("key", tuple(EXPECTED))
def test_frozen_l1_digest(key, actual_vectors):
    assert actual_vectors[key] == EXPECTED[key]


def test_backing_and_considered_domains_never_alias():
    members = ("a" * 64, "b" * 64)
    assert ids.backing_canonical_build_ids_digest(members) != ids.considered_canonical_build_ids_digest(members)
    assert ids.backing_canonical_build_ids_digest(members[::-1]) == ids.backing_canonical_build_ids_digest(members)
    with pytest.raises(ValueError, match="duplicates"):
        ids.backing_canonical_build_ids_digest((members[0], members[0]))
