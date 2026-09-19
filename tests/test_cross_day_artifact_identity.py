"""Artifact recorded identities must equal the frozen live identities."""

import pytest

from market_vault.cross_day_dataset._artifact_identity import _recorded_payload, _recorded_dataset_id
from market_vault.cross_day_dataset.identity import _payload
from test_cross_day_artifact_canonical import prepared
from test_cross_day_artifact_join import validate


@pytest.mark.parametrize("case,expected", [
    ("A", "2f5355e7cc30ab7a984f9ff959b10e8d8b949e89e453b0e43c0d88a6a36f06c8"),
    ("B", "7bb8903e54e7c3203deb9c1d2bf63cef16202ed5b2807c9c20a6eb4ed0c7f1af"),
    ("C", "b0223c6eac1186590ea3a967b35780b3e043e8dbf4f46bee976c728bffff4bc8"),
    ("D", "047f51f7ccb41ed97e7b682cd2432dc135921fead1904e6028e24faf60344ce6"),
    ("E", "dcdd12857a9278d6c1008e70b9ec0b8a0bb4b16f8afb0d7173c2ef5cbd9f191f"),
    ("F", "1d20617d872c9d93c924435e9f3bfb7226a381e9f834cd9e70e7c2abc69cd802"),
    ("G", "07da04ab3ccdca4cdf42a60e0e828d197d3047370148d994a789753116ab02d9"),
    ("H_considered", "5900736e6a44db736497d74ebcfd3db32f3cf336d45fb90bdda7d6ae0fb61111"),
    ("H_backing", "36c731b512ca8c5a75cdb0ef11b2cab4f4e5eaff74f1669a819a9fbb87228b9e"),
])
def test_artifact_exact_frozen_dataset_id_and_all_49_fields(tmp_path, case, expected):
    original, data = prepared(tmp_path, case)
    recorded = validate(original, data)
    payload = _recorded_payload(recorded)
    assert len(payload) == 49
    assert payload == _payload(original.identity_input)
    assert _recorded_dataset_id(recorded) == expected == original.dataset_id
