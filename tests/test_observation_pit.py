"""Numbered canaries map directly to the 42 frozen A3 design requirements."""

import ast
import builtins
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import shutil
import socket

import pytest

from market_vault.observation import assemble_observation_pit_sidecar, load_verified_observation_build
from market_vault.observation import pit, pit_identity, pit_models, _pit_validation
from market_vault.observation.pit_models import ObservationPITError
from test_observation_pit_models import artifacts, bar, binding, clock, observation, source


def assemble(builds, *, spec=None, A=None, bindings=None):
    return assemble_observation_pit_sidecar(bar(A=A), tuple(builds),
                                           (binding(spec),) if bindings is None else tuple(bindings))


def correction(row, *, known=99, archive=99, revision="correction", **changes):
    return replace(row, known_at=clock(known), archive_available_at=clock(archive),
                   revision_id=revision, supersedes_revision_id=row.revision_id, **changes)


@pytest.mark.parametrize("target,event", [("FEATURE_WINDOW_START", 90), ("FEATURE_WINDOW_CLOSE", 100)])
def test_canary_01_exact_targets_use_close_visibility(artifacts, target, event):
    row = observation(event=event, known=100, archive=100)
    d = assemble((artifacts((row,)),), spec=source(alignment="EXACT_EVENT_TIME", exact_target_binding=target)).decisions[0]
    assert d.status == "COMPLETE" and d.selected_observation_version_id == row.observation_version_id
    assert d.T == clock(100)


def test_canary_02_exact_absence(artifacts):
    d = assemble((artifacts(()),), spec=source(alignment="EXACT_EVENT_TIME",
                                             exact_target_binding="FEATURE_WINDOW_CLOSE")).decisions[0]
    assert d.reason == "NO_ELIGIBLE_OBSERVATION" and d.selected_observation_key is None


@pytest.mark.parametrize("mode,number", [("EXACT_EVENT_TIME", 3), ("LATEST_EFFECTIVE_AT_OR_BEFORE", 12)])
def test_canaries_03_12_cross_key_tie_fails(artifacts, mode, number):
    one = observation(event=100)
    two = replace(one, event_period_start=clock(99))
    assert one.observation_key != two.observation_key
    with pytest.raises(ObservationPITError, match="tie"):
        assemble((artifacts((one, two)),), spec=source(alignment=mode,
                  exact_target_binding="FEATURE_WINDOW_CLOSE" if number == 3 else None))


def test_canary_04_latest_effective_not_latest_publication(artifacts):
    old, new = observation(event=90, known=99), observation(event=95, known=96)
    d = assemble((artifacts((old, new)),)).decisions[0]
    assert d.selected_observation_key == new.observation_key and d.alignment_candidate_count == 2


def test_canary_05_old_event_late_revision_does_not_displace_newer_effective(artifacts):
    old, new = observation(event=50, known=60), observation(event=95, known=96)
    fixed = correction(old)
    build = artifacts((old, fixed, new))
    assert assemble((build,)).decisions[0].selected_observation_key == new.observation_key
    exact_bar = bar(start=50)
    exact = source(alignment="EXACT_EVENT_TIME", exact_target_binding="FEATURE_WINDOW_START", max_age_us=60)
    result = assemble_observation_pit_sidecar(exact_bar, (build,), (binding(exact),))
    assert result.decisions[0].selected_observation_version_id == fixed.observation_version_id


def test_canary_06_future_known_correction_retains_old_revision(artifacts):
    old = observation()
    fixed = correction(old, known=101, archive=102)
    d = assemble((artifacts((old, fixed)),)).decisions[0]
    assert d.selected_observation_version_id == old.observation_version_id
    assert d.future_known_excluded_count == 1


def test_canary_07_archive_future_correction_independent_proof(artifacts):
    old = observation()
    fixed = correction(old, archive=101)
    d = assemble((artifacts((old, fixed)), artifacts((), created=100)), A=100).decisions[0]
    assert d.selected_observation_version_id == old.observation_version_id and d.archive_limited
    assert d.archive_future_excluded_count == 1


def test_canary_08_repeated_capture_representative(artifacts):
    row = observation()
    late = replace(row, archive_available_at=clock(99))
    result = assemble((artifacts((late, row)),))
    assert result.decisions[0].selected_observation_version_id == row.observation_version_id
    assert result.decisions[0].scoped_version_count == 2 and result.decisions[0].eligible_key_count == 1


def test_canary_09_stale_retains_all_selected_references(artifacts):
    old = observation(event=50)
    d = assemble((artifacts((old,), effective=(50, 100)),)).decisions[0]
    assert (d.status, d.reason) == ("EXCLUDED", "STALE")
    assert d.selected_observation_version_id == old.observation_version_id
    assert all(getattr(d, name) is not None for name in d.__dataclass_fields__ if name.startswith("selected_"))


def test_canary_10_not_reported_newer_no_substitution(artifacts):
    old = observation(event=90)
    new = observation(value_status="NOT_REPORTED", values=None)
    d = assemble((artifacts((old, new)),)).decisions[0]
    assert d.reason == "NOT_REPORTED" and d.selected_observation_key == new.observation_key


def test_canary_11_withdrawn_revision_no_resurrection_even_stale(artifacts):
    old = observation(event=50)
    withdrawn = correction(old, value_status="WITHDRAWN", values=None)
    d = assemble((artifacts((old, withdrawn)),)).decisions[0]
    assert d.reason == "WITHDRAWN" and d.selected_observation_version_id == withdrawn.observation_version_id


def test_canary_13_archive_equality(artifacts):
    row = observation(archive=100)
    d = assemble((artifacts((row,), created=100),), A=100).decisions[0]
    assert d.status == "COMPLETE" and d.selected_archive_available_at == clock(100)


def test_canary_14_known_equality(artifacts):
    d = assemble((artifacts((observation(known=100),)),)).decisions[0]
    assert d.status == "COMPLETE" and d.selected_known_at == clock(100)


def test_canary_15_freshness_equality(artifacts):
    d = assemble((artifacts((observation(event=90),)),)).decisions[0]
    assert d.status == "COMPLETE" and d.selected_event_time == clock(90)


@pytest.mark.parametrize("policy", ["FAIL", "EXCLUDE_SAMPLE"])
def test_canary_16_closed_intervals_microsecond_gap_and_adjacency(artifacts, policy):
    left = artifacts((), effective=(90, 94))
    gap = artifacts((observation(event=96),), effective=(96, 100))
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((left, gap), spec=source(missing_policy=policy))
    adjacent = artifacts((), effective=(95, 95))
    assert assemble((left, gap, adjacent), spec=source(missing_policy=policy)).decisions[0].status == "COMPLETE"


@pytest.mark.parametrize("empty,number", [(False, 17), (True, 18)])
def test_canaries_17_18_late_proof_cannot_prove_history(artifacts, empty, number):
    build = artifacts(() if empty else (observation(),), created=101)
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((build,), A=100)


def test_canary_19_fresh_domain_absence_not_all_history(artifacts):
    d = assemble((artifacts((), effective=(90, 100)),)).decisions[0]
    assert d.reason == "NO_ELIGIBLE_OBSERVATION" and d.scoped_version_count == 0


def test_canary_20_build_order_irrelevant(artifacts):
    one, two = artifacts((observation(),)), artifacts((), effective=(80, 120))
    assert assemble((one, two)) == assemble((two, one))


def test_canary_21_duplicate_version_provenance_all_builds_retained(artifacts):
    row = observation()
    one, two = artifacts((row,)), artifacts((row,), effective=(80, 120))
    result = assemble((one, two))
    d = result.decisions[0]
    assert d.selected_observation_build_id == min(one.observation_build_id, two.observation_build_id)
    assert d.scoped_version_count == 1 and d.selected_observation_version_id == row.observation_version_id
    assert len(result.evidence[0].build_pins) == 2
    assert all(p.selected_observation_version_ids == (row.observation_version_id,) for p in result.evidence[0].build_pins)
    assert result.observation_association_content_id != assemble((one,)).observation_association_content_id


def test_canary_22_conflicting_stored_version_rejected_before_visibility(artifacts):
    one, tampered = artifacts(), artifacts()
    object.__setattr__(tampered.rows[0], "known_at", clock(150))
    with pytest.raises(ObservationPITError):
        assemble((one, tampered))


def test_canary_23_binding_order_and_conflicting_duplicate(artifacts):
    builds = (artifacts(),)
    one, two = binding(), binding(name="other")
    assert assemble(builds, bindings=(one, two)) == assemble(builds, bindings=(two, one, one))
    with pytest.raises(ObservationPITError, match="conflicting Feature"):
        assemble(builds, bindings=(one, binding(source(max_age_us=11))))


def test_canary_24_record_all_decisions_or_fail_entire_assembly(artifacts):
    build = artifacts()
    exact = source(alignment="EXACT_EVENT_TIME", exact_target_binding="FEATURE_WINDOW_CLOSE")
    result = assemble((build,), bindings=(binding(), binding(exact, name="exact")))
    assert {d.status for d in result.decisions} == {"COMPLETE", "EXCLUDED"}
    assert len(result.sample_bindings) == 1
    with pytest.raises(ObservationPITError, match="missing policy FAIL"):
        assemble((build,), bindings=(binding(), binding(replace(exact, missing_policy="FAIL"), name="exact")))


def test_canary_26_same_logical_build_distinct_physical_proofs(artifacts):
    one, two = artifacts(created=100), artifacts(created=101)
    assert one.observation_build_id == two.observation_build_id
    result = assemble((one, two), A=100)
    assert len(result.evidence[0].build_pins) == 2
    assert {p.coverage_proof_available_at for p in result.evidence[0].build_pins} == {clock(100), clock(101)}
    assert result != assemble((one,), A=100)


def test_canary_27_proof_archive_equality_and_independent_row_clock(artifacts):
    assert assemble((artifacts(created=100),), A=100).decisions[0].status == "COMPLETE"
    row = observation(archive=101)
    d = assemble((artifacts((row,)), artifacts((), created=100)), A=100).decisions[0]
    assert d.reason == "ARCHIVE_FUTURE"


def test_canary_28_knowledge_end_must_reach_T(artifacts):
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((artifacts(knowledge=(0, 99)),))


@pytest.mark.parametrize("kind", ["fork", "conflict", "missing"])
def test_canary_29_cross_build_revision_structure_before_clocks(artifacts, kind):
    row = observation()
    one = artifacts((row, correction(row, known=101, revision="a")))
    if kind == "fork":
        two = artifacts((row, correction(row, known=102, revision="b")))
    elif kind == "conflict":
        two = artifacts((replace(row, values=(8.25, 12)),))
    else:
        two = artifacts((row, correction(row, known=102, revision="b")))
        object.__setattr__(two.rows[-1], "supersedes_revision_id", "missing-predecessor")
    with pytest.raises(ObservationPITError):
        assemble((one, two))


@pytest.mark.parametrize("change", [dict(known_at_authority_policy_content_id="f" * 64),
                                     dict(normalization_content_id="f" * 64), dict(value_schema_id="f" * 64),
                                     dict(input_field_names=("unknown",)), dict(provider_contract_content_id="f" * 64)])
def test_canary_30_contract_schema_policy_fail_closed(artifacts, change):
    with pytest.raises(ObservationPITError):
        assemble((artifacts(),), spec=source(**change))


def test_canary_30_unknown_code_no_inference(artifacts):
    spec = source(entity_binding="SAMPLE_CODE", entity_id=None, code_entity_map=(("US.OTHER", "fixture:entity"),))
    with pytest.raises(ObservationPITError, match="unknown sample code"):
        assemble((artifacts(),), spec=spec)


def test_canary_31_archive_future_precedence_disjoint_counts(artifacts):
    archive = observation(event=94, known=95, archive=101)
    future = observation(event=95, known=101, archive=102)
    d = assemble((artifacts((archive, future)), artifacts((), created=100)), A=100).decisions[0]
    assert d.reason == "ARCHIVE_FUTURE" and d.archive_limited and d.selected_observation_key is None
    assert (d.scoped_version_count, d.future_known_excluded_count, d.archive_future_excluded_count) == (2, 1, 1)


def test_canary_32_future_effective_alone_not_future_known(artifacts):
    d = assemble((artifacts((observation(event=101, known=101),)),)).decisions[0]
    assert d.reason == "NO_ELIGIBLE_OBSERVATION"


def test_canary_34_duplicate_proof_and_relocation_irrelevant(artifacts, tmp_path):
    one = artifacts()
    copied = tmp_path / "relocated" / one.build_dir.name
    shutil.copytree(one.build_dir, copied)
    relocated = load_verified_observation_build(copied)
    assert assemble((one,)) == assemble((one, one, relocated))


def test_canary_35_late_proof_row_facts_do_not_use_build_clock(artifacts):
    late = artifacts(created=300)
    proof = artifacts((), created=100)
    assert assemble((late, proof), A=100).decisions[0].status == "COMPLETE"
    hole = artifacts((), created=100, effective=(96, 100))
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((late, hole), A=100)


def test_independent_revision_proof_must_cover_contributed_known_history(artifacts):
    row = observation(event=95, known=60, archive=97)
    late = artifacts((row,))
    incomplete_history = artifacts((), created=100, knowledge=(90, 100))
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((late, incomplete_history), A=100)
    full_history = artifacts((), created=100, knowledge=(60, 100))
    assert assemble((late, full_history), A=100).decisions[0].status == "COMPLETE"


def test_canary_36_irrelevant_older_archive_correction_no_archive_flag(artifacts):
    old, new = observation(event=50, known=60), observation()
    build = artifacts((old, correction(old, archive=101), new))
    d = assemble((build, artifacts((), created=100)), A=100).decisions[0]
    assert d.selected_observation_key == new.observation_key and not d.archive_limited


def test_canary_37_future_only_empty_knowledge_fails(artifacts):
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((artifacts((), knowledge=(101, 300)),))


@pytest.mark.parametrize("policy", ["FAIL", "EXCLUDE_SAMPLE"])
def test_canary_41_unproven_stale_latest_is_authority_failure(artifacts, policy):
    fresh, old = artifacts((), effective=(90, 100)), artifacts((observation(event=50),), effective=(50, 50))
    with pytest.raises(ObservationPITError, match="coverage authority"):
        assemble((fresh, old), spec=source(missing_policy=policy))


def test_canary_42_extended_stale_proof_pins_all_evidence(artifacts):
    fresh = artifacts((), effective=(90, 100))
    old = artifacts((observation(event=50),), effective=(50, 50))
    extension = artifacts((), effective=(51, 89))
    result = assemble((fresh, old, extension))
    d = result.decisions[0]
    assert d.reason == "STALE" and d.selected_event_time == clock(50)
    assert len(result.evidence[0].build_pins) == len(result.evidence[0].coverages) == 3
    assert {p.observation_build_id for p in result.evidence[0].build_pins} == {
        fresh.observation_build_id, old.observation_build_id, extension.observation_build_id}


def test_chain_reachability_across_archive_ineligible_intermediate(artifacts):
    first = observation(known=91, archive=92)
    middle = correction(first, known=93, archive=105)
    last = correction(middle, known=94, archive=98, revision="terminal")
    d = assemble((artifacts((first, middle, last)), artifacts((), created=100)), A=100).decisions[0]
    assert d.selected_observation_version_id == last.observation_version_id and not d.archive_limited


def test_assembly_is_deeply_immutable(artifacts):
    result = assemble((artifacts(),))
    for value, name in ((result, "decisions"), (result.decisions[0], "reason"),
                        (result.evidence[0], "coverages"), (result.evidence[0].build_pins[0], "status"),
                        (result.evidence[0].coverages[0], "knowledge_end")):
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, None)
    assert isinstance(result.evidence[0].build_pins[0].authority_evidence_ids, tuple)


def test_input_types_and_bar_identity_admission(artifacts):
    build = artifacts()
    for bad in (build.build_dir, {}, build.rows, build.observation_build_id):
        with pytest.raises(ObservationPITError, match="VerifiedObservationBuild"):
            assemble((bad,))
    for field, bad in (("association_content_id", "f" * 64), ("association_schema_id", "f" * 64)):
        value = bar()
        object.__setattr__(value, field, bad)
        with pytest.raises(ObservationPITError, match="association"):
            assemble_observation_pit_sidecar(value, (build,), (binding(),))
    for field in ("sample_key", "sample_version_id"):
        value = bar()
        object.__setattr__(value.samples[0], field, "f" * 64)
        with pytest.raises(ObservationPITError):
            assemble_observation_pit_sidecar(value, (build,), (binding(),))


def test_nonempty_bar_association_reference_validation(artifacts):
    from market_vault.dataset.models import CanonicalBuildPin
    from market_vault.dataset.content import logical_dataset_content_id
    from market_vault.dataset.pit_identity import pit_sample_version_id
    from test_observation_models import H
    bars = bar()
    sample = bars.samples[0]
    version = pit_sample_version_id(sample_key=sample.sample_key, dataset_as_of=None,
                                   feature_canonical_row_version_ids=(H[11],), label_canonical_row_version_ids=(),
                                   considered_canonical_build_ids=(H[12],))
    sample = replace(sample, sample_version_id=version, feature_canonical_row_version_ids=(H[11],),
                     considered_canonical_build_ids=(H[12],))
    pin = CanonicalBuildPin(H[12], H[13], "builder-v1", "schema-v1", "materializer-v1", "gap-v1", H[14],
                            "COMPLETE", (H[11],), ())
    row = dict(sample_key=sample.sample_key, sample_version_id=version, role="FEATURE", position=0,
               canonical_build_id=H[12], canonical_bar_key=H[15], canonical_row_version_id=H[11],
               code=sample.request.code, event_time=clock(95), market_available_at=clock(96), archive_available_at=clock(97))
    bars = replace(bars, samples=(sample,), canonical_build_pins=(pin,), canonical_row_version_ids=(H[11],),
                   association_rows=(row,), association_content_id=logical_dataset_content_id(bars.association_schema, (row,)))
    build = artifacts()
    assert assemble_observation_pit_sidecar(bars, (build,), (binding(),)).decisions[0].bar_sample_version_id == version
    for field, bad in (("sample_version_id", H[18]), ("sample_key", H[18]), ("position", 1),
                       ("canonical_build_id", H[18]), ("canonical_row_version_id", H[18]), ("code", "US.OTHER")):
        corrupt = row | {field: bad}
        inconsistent = replace(bars, association_rows=(corrupt,),
                               association_content_id=logical_dataset_content_id(bars.association_schema, (corrupt,)))
        with pytest.raises(ObservationPITError, match="association"):
            assemble_observation_pit_sidecar(inconsistent, (build,), (binding(),))
    with pytest.raises(ObservationPITError, match="references"):
        assemble_observation_pit_sidecar(replace(bars, canonical_build_pins=(replace(pin, canonical_row_version_ids=()),)),
                                         (build,), (binding(),))


def test_multiple_samples_keep_independent_cutoffs_and_sorted_identity(artifacts):
    one, two = bar(), bar(close=101, A=100)
    combined = replace(one, samples=one.samples + two.samples)
    builds = (artifacts(created=100),)
    result = assemble_observation_pit_sidecar(combined, builds, (binding(),))
    permuted = assemble_observation_pit_sidecar(replace(combined, samples=combined.samples[::-1]), builds, (binding(),))
    assert result == permuted
    assert {(d.T, d.A) for d in result.decisions} == {(clock(100), None), (clock(101), clock(100))}
    assert len(result.sample_bindings) == 2


def test_no_io_or_time_side_channels(artifacts, monkeypatch):
    build, bars, bindings = artifacts(), bar(), (binding(),)
    def forbidden(*args, **kwargs):
        raise AssertionError("A3 attempted I/O")
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "cwd", forbidden)
        patch.setattr(socket, "socket", forbidden)
        result = assemble_observation_pit_sidecar(bars, (build,), bindings)
    assert result.decisions[0].status == "COMPLETE"
    forbidden_calls = {"open", "read_bytes", "read_text", "write_bytes", "write_text", "mkdir", "unlink",
                       "rename", "replace", "rmtree", "now", "utcnow", "today", "cwd", "getenv"}
    for module in (pit, pit_models, pit_identity, _pit_validation):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls
            if isinstance(node, ast.Import):
                assert not any(n.name.split(".")[0] in {"os", "pathlib", "socket", "requests", "httpx", "time"}
                               for n in node.names)
