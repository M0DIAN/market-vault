"""Design-only guards for retained live issuance; no ledger runtime is implemented."""

from dataclasses import fields, make_dataclass
import gc
from pathlib import Path
import re
import weakref

import pytest

from market_vault.cross_day_dataset.models import MultiSourceCrossDayDatasetResult
from test_cross_day_dataset_identity import EXPECTED
from test_cross_day_dataset_canary_coverage import CANARIES as L31_CANARIES
from test_cross_day_generator_canaries import CANARIES as L32_CANARIES


DESIGN = Path(__file__).resolve().parents[1] / "docs/multi_source_cross_day_dataset_v1.md"
PUBLIC_FIELDS = (
    "identity_input", "dataset_id", "scope", "dataset_as_of", "schema", "rows",
    "sample_audit", "completion", "split_result", "feature_pit", "ts2_features",
    "observation_pit", "observation_builds", "observation_feature_specs",
    "observation_features", "cross_day_association", "cross_day_labels",
    "schedule", "status",
)


def addendum():
    text = DESIGN.read_text(encoding="utf-8")
    return " ".join(text.split("### 4.1 ", 1)[1].split("## 5. ", 1)[0].split())


@pytest.mark.parametrize("required", [
    "SELECTED_ISSUANCE_ARCHITECTURE=PROCESS_PRIVATE_ISSUANCE_LEDGER",
    "LOGICAL_VALIDITY AND LIVE_ISSUANCE",
    "remain pure logical/recorded validators",
    "ledger is NOT an issuer",
    "Only the join's final private issuance block may insert an entry",
    "weakref to the exact result",
    "exact original identity_input object",
    "original status and issuer contract",
    "independent immutable snapshot",
    "Original references alone are NOT a snapshot",
    "Original node references permit `is` comparison",
    "weakref_slot=True",
    "__weakref__ is a slot, NOT a dataclass field",
    "PUBLIC_RESULT_FIELD_COUNT=19",
    "ledger has no strong reference to the result",
    "weakref IS the callback's weakref",
    "stale callbacks and id reuse (ABA)",
    "private reentrant lock",
    "Fork must not inherit usable proof",
    "Module reload starts empty",
    "_require_live_issued_multi_source_cross_day_dataset_result(result)",
    "entry.weakref() IS result",
    "result.identity_input IS the recorded original declaration",
    "recomputed Dataset ID equals BOTH",
    "Repeat entry identity, projection bindings and independent snapshot",
    "Never update the issuance baseline after mutation",
    "BEFORE any artifact filesystem access or mutation",
    "output_root to ALREADY EXIST",
    "filesystem mutation count is zero",
    "Reader LIVE_ISSUANCE dependency is false",
    "no persisted live capability",
    "zero filesystem reads/writes, network/provider/OpenD or current-time calls",
    "LOGICAL_IDENTITY_VALIDATION_NE_LIVE_RESULT_ISSUANCE_AUTHORITY",
    "COORDINATED_INTERNALLY_VALID_UNISSUED_RESULT_REJECTED_BY_LIVE_BOUNDARY",
    "REQUIRED_FUTURE_RUNTIME_TEST",
    "SUPPLEMENTAL_LIVE_ISSUANCE_RUNTIME_CANARIES_IMPLEMENTED=0",
    "L3_1_LIVE_RESULT_ISSUANCE_REMEDIATION_IMPLEMENTATION_AUTHORIZED=false",
    "L3_3_CROSS_DAY_ARTIFACT_IMPLEMENTATION_AUTHORIZED=false",
    "L4_IMPLEMENTATION_AUTHORIZED=false",
])
def test_closed_issuance_design_obligation(required):
    assert required in addendum()


@pytest.mark.parametrize("entry", [
    "register_live_result(result)", "mark_issued(result)", "trust_result(result)",
    "from_verified(...)", "deserialize_and_register(...)", "caller nonce/hash",
    "test-only production bypass", "public issuance-context constructor",
])
def test_no_caller_registration_contract(entry):
    text = addendum()
    forbidden = text.split("No public or importable registration/minting helper", 1)[1]
    assert entry in forbidden.split("This is an in-process API", 1)[0]


def test_weakref_slot_adds_no_logical_fields_preflight():
    assert tuple(f.name for f in fields(MultiSourceCrossDayDatasetResult)) == PUBLIC_FIELDS
    assert len(PUBLIC_FIELDS) == 19
    # Language-mechanism probe, not an implementation of the production result/ledger.
    probe_type = make_dataclass("WeakrefFieldProbe", [(name, object) for name in PUBLIC_FIELDS],
                               frozen=True, slots=True, weakref_slot=True)
    assert tuple(f.name for f in fields(probe_type)) == PUBLIC_FIELDS
    assert "__weakref__" in probe_type.__slots__
    probe = probe_type(*(None for _ in PUBLIC_FIELDS))
    reference = weakref.ref(probe)
    assert reference() is probe
    del probe
    gc.collect()
    assert reference() is None


def test_history_and_reproduction_are_not_reclassified_vectors():
    text = addendum()
    for fact in (
        "PR173_L3_1_RUNTIME_REVIEW=PASS",
        "L3_1_IMPLEMENTATION_ATTEMPT_2=PASS",
        "L3_1_LOGICAL_JOIN_RUNTIME=CLOSED_ON_MAIN",
        "L3_3_IMPLEMENTATION_ATTEMPT_1=FAIL",
        "L3_3_IMPLEMENTATION_ATTEMPT_1_REPOSITORY_MUTATION=false",
        "LIVE_JOIN_ISSUANCE_NOT_REVALIDATABLE_UNDER_UPSTREAM_FREEZE",
        "NOT new frozen known-answer vectors",
        "0.25", "999.0",
        "REPRODUCTION_GENUINE_DATASET_ID=2f5355e7cc30ab7a984f9ff959b10e8d8b949e89e453b0e43c0d88a6a36f06c8",
        "REPRODUCTION_FORGED_DATASET_ID=97ecb5d9951e6685475e73d273b44605dcd67fb60d3e724c6c8263d4711e5a9d",
    ):
        assert fact in text


def test_existing_98_literals_and_80_canary_accounting_unchanged():
    text = DESIGN.read_text(encoding="utf-8")
    vectors = text.split("### 24.2 Frozen Expected Digests", 1)[1].split("## 25.", 1)[0]
    pairs = re.findall(r"^([A-Za-z0-9_.]+)=([0-9a-f]{64})$", vectors, re.MULTILINE)
    assert len(pairs) == len(dict(pairs)) == len(EXPECTED) == 98
    assert dict(pairs) == EXPECTED
    expected_deferred = {2, 3, 38, 39, 40, 61, 75, 76, 77}
    for table in (L31_CANARIES, L32_CANARIES):
        assert len(table) == 80
        assert {n for n, phase, _, _ in table if phase == "L3_3_DEFERRED"} == expected_deferred
    assert "DESIGN_CANARY_COUNT=80" in text
    assert "HISTORICAL_DATASET_DESIGN_CANARY_COUNT=80" in addendum()
    assert "SUPPLEMENTAL_LIVE_ISSUANCE_CANARY_COUNT=1" in addendum()
    assert "SUPPLEMENTAL_LIVE_ISSUANCE_RUNTIME_CANARIES_DEFERRED=1" in addendum()
