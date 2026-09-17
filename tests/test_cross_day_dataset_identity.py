"""98 literal expectations copied from frozen design section 24.2, never regenerated."""

import pytest

from cross_day_dataset_helpers import fixture
from market_vault.cross_day import identity as label_ids
from market_vault.cross_day_dataset import (
    join_multi_source_cross_day_dataset, cross_day_dataset_sequence_id,
    multi_source_cross_day_sample_audit_id, multi_source_cross_day_completion_entry_id,
    multi_source_cross_day_dataset_id,
)
from market_vault.cross_day_dataset.identity import _payload

EXPECTED = {
    "A.dataset_id": "2f5355e7cc30ab7a984f9ff959b10e8d8b949e89e453b0e43c0d88a6a36f06c8",
    "A.sample_audit_content_id": "05141d26027d39234fd8d3fa63ef7ca88db1770088750880d61a02bb47d7fa84",
    "A.completion_content_id": "c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7",
    "A.logical_dataset_content_id": "d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da",
    "A.completion_entry_id": "5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379",
    "A.audit_id": "bb473bdc63666c47f90176f5b079e4052c64c2396952fe7a81090327f87f8b87",
    "B.dataset_id": "7bb8903e54e7c3203deb9c1d2bf63cef16202ed5b2807c9c20a6eb4ed0c7f1af",
    "B.sample_audit_content_id": "3d67dd7cd8ef2bfb8a355d2a1def438fc4cf144d54db2f9b4e475c18d69547f7",
    "B.completion_content_id": "6c6dcfabb4a8c32bbbdb6be0c1a8831e25e6ebb2e2886a9063bfc74521510d67",
    "B.logical_dataset_content_id": "c04f288a1ed7124ecc8720e07fb57eced3dbcbd4e4161d684d12eeaaaec11cd4",
    "B.completion_entry_id": "e95e19f95ff8113112b397e3aa3b8fb51258e26cda5b5a5151a337a6254f3d76",
    "B.audit_id": "a7f37ef7284048d5f0a2e45053c1433578bc99b8db5bc3795aa6f9e01f5a0c8c",
    "C.dataset_id": "b0223c6eac1186590ea3a967b35780b3e043e8dbf4f46bee976c728bffff4bc8",
    "C.sample_audit_content_id": "93160daf0413839e49acb5f543445e5eaef4d376b9aa579e238806cd64cb7f27",
    "C.completion_content_id": "88e72332af570ec7f2dea8a5c2051b75b91650b4a862185450c731b36fe0da84",
    "C.logical_dataset_content_id": "cbd1556a06c724f3c11e0d9b9c72689114e6cc6906d0c3a648cdc69b92bf7b25",
    "C.completion_entry_id": "ada02cf8ae2ab180d9c64d003235ec91c6c24c9af2bb23ea253138d5715092cd",
    "C.audit_id": "bbe96e12455a6fc5c6ee61194430b5c8ea50be1272d510278fa0861ca30b9707",
    "D.dataset_id": "047f51f7ccb41ed97e7b682cd2432dc135921fead1904e6028e24faf60344ce6",
    "D.sample_audit_content_id": "1c9fd5710c9209594185de348a27fa1e69a27670c9d6086f248e91aa806912bd",
    "D.completion_content_id": "d4289b1ae8462a9951431802303f06595271ac61c953e9f9db0dc783064a9b5b",
    "D.logical_dataset_content_id": "cbd1556a06c724f3c11e0d9b9c72689114e6cc6906d0c3a648cdc69b92bf7b25",
    "D.completion_entry_id": "85225f05d4f81f4909f312fc3a41a3554ef293e88d53e468d26ef4cf29f8813e",
    "D.audit_id": "79beef4e9b5dd57ae972d0905c49f0899b9f66cd886266ddd220b0a83677487c",
    "E.dataset_id": "dcdd12857a9278d6c1008e70b9ec0b8a0bb4b16f8afb0d7173c2ef5cbd9f191f",
    "E.sample_audit_content_id": "4d40e8649193ec70a93870c726053db8951176d5c83488da6736370afbf96ab3",
    "E.completion_content_id": "3d32a36f77055ef3378d019bdbaaf02d7c9df7726db5c29502daa2696273065f",
    "E.logical_dataset_content_id": "cbd1556a06c724f3c11e0d9b9c72689114e6cc6906d0c3a648cdc69b92bf7b25",
    "E.completion_entry_id": "54ea47c41449b97ff38e204415e8b3bf22431c5c948231f6e08e9c997d1185f1",
    "F.dataset_id": "1d20617d872c9d93c924435e9f3bfb7226a381e9f834cd9e70e7c2abc69cd802",
    "F.sample_audit_content_id": "a0d1362ebd277b1a4e5778b8cabf36fbd63ac60ce895bf59f1c9f0ef47e4f0dd",
    "F.completion_content_id": "c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7",
    "F.logical_dataset_content_id": "d8306f69619ff0697ec80f193108a7d459fda109bc5886938e4c6298b9357180",
    "F.completion_entry_id": "5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379",
    "F.audit_id": "fa9c1821167340b2f206d83e2a5ba45bc46334b0fad1d546a65b70e8c0ff7e2b",
    "G.dataset_id": "07da04ab3ccdca4cdf42a60e0e828d197d3047370148d994a789753116ab02d9",
    "G.sample_audit_content_id": "011d6c7c1c1370723a148ee208c2df1dcb1ae64715d2180c404d3d1c72bd9414",
    "G.completion_content_id": "c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7",
    "G.logical_dataset_content_id": "d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da",
    "G.completion_entry_id": "5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379",
    "G.audit_id": "a9515d8999c184b39d7224e42f55d8f59b25bd573db55e90ef84cd5419f67ba5",
    "H_considered.dataset_id": "5900736e6a44db736497d74ebcfd3db32f3cf336d45fb90bdda7d6ae0fb61111",
    "H_considered.sample_audit_content_id": "ed6e8b4caaaf8152527394c693edf677b24e29e11f7a95d76414d9ca9db2c029",
    "H_considered.completion_content_id": "c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7",
    "H_considered.logical_dataset_content_id": "d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da",
    "H_considered.completion_entry_id": "5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379",
    "H_considered.audit_id": "9db8326863cb9f78c8ad9dd2b2d8477a611a6d2ffa57c4efe8434e6e57695bd5",
    "H_backing.dataset_id": "36c731b512ca8c5a75cdb0ef11b2cab4f4e5eaff74f1669a819a9fbb87228b9e",
    "H_backing.sample_audit_content_id": "aab2ac1c6b8dda8c0d20300136a14732f6474214a00a17bb634ecb0615f39f99",
    "H_backing.completion_content_id": "c9ae1e7e5350ccbfd4b975c3a72587c479470100ff27d1997a685829f8bfc1a7",
    "H_backing.logical_dataset_content_id": "d9ac0132dee1f3915cf75529fc9e160c5614d3e2db302a2c4a57d3fd2862a3da",
    "H_backing.completion_entry_id": "5f0d3eddd90aea0a19fef267bc5995ae82219c89d993dd8a93aab537e9872379",
    "H_backing.audit_id": "af8e0e889479ec1bd914b8bb2c65422e78fe977425c7006bb8bc07e27ac9c597",
    "A.selected_row_reference_id": "6644f2c9764231d1b737825d912b80d8f795f8241d606a81d2e2de377be8f1b1",
    "A.considered_builds_digest": "c67791675c4f93de16c179a996e4d01a05a7879ce7a10f4ea049ced9a25272a3",
    "H_considered.selected_row_reference_id": "6644f2c9764231d1b737825d912b80d8f795f8241d606a81d2e2de377be8f1b1",
    "H_considered.considered_builds_digest": "4b2ecd5785215f00990d7d3a51a5ea36279e9f436553799eb73e0de3077493c1",
    "H_backing.selected_row_reference_id": "d47f063f57238fc079c839a7340cb88a44d290d42432cd2f015796e6ee44dc0d",
    "H_backing.considered_builds_digest": "8979a802da972f53387078fc4b2e72607830f20652bd9c838b03d09a75adebce",
    "A.ts2_execution_id": "a9bacbdcfa334a544b32ff906d0698f571c0e1b8ef17bf6a7c603dfbc5d0bf74",
    "A.a3_combined_association_content_id": "b2128bf1daf366e4bc1583e60778bfcbf90973152d363f29da6a82cbaf2370a1",
    "A.multi_source_sample_version_id": "c2f13818c6c7938d0d93fdba114dfb0f440afc9f8fac1e3f4bebaaa91587548a",
    "F.reversed_dataset_id": "1d20617d872c9d93c924435e9f3bfb7226a381e9f834cd9e70e7c2abc69cd802",
    "H_backing.reversed_dataset_id": "36c731b512ca8c5a75cdb0ef11b2cab4f4e5eaff74f1669a819a9fbb87228b9e",
    "Q.CANONICAL_BUILD_PINS.empty": "f92877ca8dc1c8cb00653ae93a170b30db8842372f924b896909693017b41dbb",
    "Q.CANONICAL_BUILD_PINS.two": "f3f24d0301f03436a47aa5661347d199ac9d3d500047b191b267d765ebb843f5",
    "Q.CANONICAL_ROW_VERSIONS.empty": "4d312df170f3da112040ffd72cc464e7095e47b02c5e42092f60e2a1a040481a",
    "Q.CANONICAL_ROW_VERSIONS.two": "d4f8c22588c8f36bb8bc04a2f75aea3d2074ca30b14fb91a7a6cb6ceb0647971",
    "Q.COMPLETION_ENTRIES.empty": "0e1100eaadbadbe35dfbc1799304893f09666af8311cb287146cb01770f545b6",
    "Q.COMPLETION_ENTRIES.two": "d0c1b86f0ba3d9eded95b3ef471823aa275523f22b5b47f42c96c901fba94bac",
    "Q.CROSS_DAY_DECISIONS.empty": "a342a47a93784dfa115a41626ceb8b07e3a5e1931061ecf0f857f4f2689a11f7",
    "Q.CROSS_DAY_DECISIONS.two": "833d38205e848d374ef58e105d18be64c8b2446d2c1ed43a93288216662d5b01",
    "Q.CROSS_DAY_IMPLEMENTATION_PINS.empty": "a7a1f179bef1d39c1fddcb115ca47bc97df23a51c296d4be48aa57b0b4e72c8c",
    "Q.CROSS_DAY_IMPLEMENTATION_PINS.two": "cd4400e2e21e401e9344ba7e699d61aa39e59ed8064d9c4fb0c776d78f95d4d1",
    "Q.CROSS_DAY_SAMPLE_BINDINGS.empty": "9a170a4312b71159fe3d399684e6df2b255274760ca9eca3507e2d210359192d",
    "Q.CROSS_DAY_SAMPLE_BINDINGS.two": "d0127b591d05bdc8e97483f2887e14ec732353a71f7fe5098fcdfb2cb4375669",
    "Q.CROSS_DAY_SPEC_PINS.empty": "8bd3acc4d89f06911fa81f406ac5ab32e7abaf2408538f5134f79fd99d773df7",
    "Q.CROSS_DAY_SPEC_PINS.two": "4549ef8b16607e5dfd442aa7fd7f930ca8a18fef24b9dec1f4712dab74389ed7",
    "Q.GAP_REFERENCES.empty": "46e056f39d099675057ce5b330bbd513a412602e155f4fc58f69f9d503448079",
    "Q.GAP_REFERENCES.two": "84267b5c48bdb85759f62deb3df884595803e5701a6ffc18e4b592a63cfbeb96",
    "Q.MULTI_SOURCE_SAMPLE_VERSIONS.empty": "905093f9f420b3b80525479e7f273512a72be7ec0b6110e576147abd556ba209",
    "Q.MULTI_SOURCE_SAMPLE_VERSIONS.two": "665022bf4d8d86f7458abe7710851c6cdd279cc4122ca7d19096353cf7d04e6d",
    "Q.OBSERVATION_BUILDPIN_IDS.empty": "6488e8fcfd4d90ffe02cda0084720a268fe3ceedc15b90a7f0b902f9e6e52bb4",
    "Q.OBSERVATION_BUILDPIN_IDS.two": "a4cbd53398063be5d0d53df51ff81449c71bacff3af9f7c1bdc17626026ec380",
    "Q.OBSERVATION_COVERAGE_IDS.empty": "1d930d5cb2d881e10290aea6337b34caaf62c2f74e37af60ea2ff162c8c99ddc",
    "Q.OBSERVATION_COVERAGE_IDS.two": "ca1b4105860ae31fd45be4a01810eea24a2c97d8ae27a8e1810fd0c445399673",
    "Q.OBSERVATION_IMPLEMENTATION_PINS.empty": "f978e1cc9f04c1bf2ace7f0d805078d63558a70c7f0ec905bc0e1577ec120efa",
    "Q.OBSERVATION_IMPLEMENTATION_PINS.two": "58075738ea2f8a09400e2582ce6b0dfe3b60438ba99ac2b2dc69ac2fd379ea60",
    "Q.OBSERVATION_INPUT_PROOFS.empty": "65a8b8d4848470ec2fc9ace812a6c838f0922118f4cf62c00706093f120b6d5e",
    "Q.OBSERVATION_INPUT_PROOFS.two": "9681f508260ea64e29447bbcba58d557ced945eea16eb4a78ded95b39d6eb16e",
    "Q.OBSERVATION_SPEC_PINS.empty": "50fe9740b97c4f91a722044b60ebcfb859c1dbe3c8eae03b1801d9e6938f280c",
    "Q.OBSERVATION_SPEC_PINS.two": "d08e0b770b9bdb80a2336196123852288bf6362a9c86c49b494dac5353e6c680",
    "Q.SAMPLE_AUDIT.empty": "4d40e8649193ec70a93870c726053db8951176d5c83488da6736370afbf96ab3",
    "Q.SAMPLE_AUDIT.two": "5cc34532d7b000e5e38bee5d0b76f810542e6c16f2b3a2cc4e2f76372c5b3368",
    "Q.TS2_REGISTRY_PINS.empty": "7206c5228de5c5a362cd71271d6037c97a9bb8a4dbe158064460c91618f8c88a",
    "Q.TS2_REGISTRY_PINS.two": "c8427951944bd6f327b04974d3d7f19572b95c17e1d6596062e0ecc49d06ff69",
    "Q.TS2_SPEC_PINS.empty": "43e7dcdff66fbfa191abc7214efae4f0477796d42bff93a120ec840556722a02",
    "Q.TS2_SPEC_PINS.two": "fe3e0ba8c269c26e2dfdc4ccba7a3348d319e3e32c779ef3aad098385bc48704",
}


@pytest.fixture(scope="module")
def vector_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("cross-day-dataset-kat")
    values = {case: join_multi_source_cross_day_dataset(**fixture(root / case, case))
              for case in ("A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing")}
    for case in ("F", "H_backing"):
        values[case + "_reversed"] = join_multi_source_cross_day_dataset(
            **fixture(root / (case + "_reversed"), case, reverse=True))
    return values


@pytest.mark.parametrize("name,expected", tuple(EXPECTED.items()))
def test_literal_known_answer(name, expected, vector_results):
    if name.startswith("Q."):
        _, role, shape = name.split(".")
        actual = cross_day_dataset_sequence_id(role, () if shape == "empty" else ("a" * 64, "b" * 64))
    else:
        case, field = name.split(".")
        value = vector_results[case]
        payload = _payload(value.identity_input)
        if field == "dataset_id":
            actual = value.dataset_id
        elif field == "audit_id":
            actual = multi_source_cross_day_sample_audit_id(value.sample_audit[0])
        elif field == "completion_entry_id":
            actual = multi_source_cross_day_completion_entry_id(value.completion.entries[0])
        elif field == "selected_row_reference_id":
            actual = label_ids.row_reference_id(value.cross_day_association.decisions[0].selected_rows[0])
        elif field == "considered_builds_digest":
            actual = payload["cross_day_considered_canonical_builds_digest"]
        elif field == "a3_combined_association_content_id":
            actual = value.observation_pit.combined_association_content_id
        elif field == "multi_source_sample_version_id":
            actual = value.observation_pit.sample_bindings[0].multi_source_sample_version_id
        elif field == "reversed_dataset_id":
            actual = vector_results[case + "_reversed"].dataset_id
        else:
            actual = payload[field]
    assert actual == expected, name


def test_literal_inventory_and_closed_root(vector_results):
    assert len(EXPECTED) == 98
    assert len({key.split(".")[0].split("_")[0] for key in EXPECTED if not key.startswith("Q.")}) == 8
    for value in vector_results.values():
        assert len(_payload(value.identity_input)) == 49
        assert multi_source_cross_day_dataset_id(value.identity_input) == value.dataset_id


def test_closed_sequence_role_order_semantics():
    from market_vault.cross_day_dataset import MultiSourceCrossDayDatasetError
    from market_vault.cross_day_dataset.identity import SEQUENCE_ROLES, ORDERED_ROLES
    for role in SEQUENCE_ROLES:
        first = cross_day_dataset_sequence_id(role, ("a" * 64, "b" * 64))
        second = cross_day_dataset_sequence_id(role, ("b" * 64, "a" * 64))
        assert (first != second) == (role in ORDERED_ROLES)
    with pytest.raises(MultiSourceCrossDayDatasetError):
        cross_day_dataset_sequence_id("CALLER_NEW_ROLE", ())
