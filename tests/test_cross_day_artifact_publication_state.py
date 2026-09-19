"""Real publication orchestration against an in-memory fault model, not OS qualification."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from cross_day_dataset_helpers import fixture, tamper
from cross_day_artifact_memory_fs import MemoryFS
from market_vault.cross_day_dataset import execution, materialization as m, reader as r
from market_vault.cross_day_dataset.artifact_models import MultiSourceCrossDayArtifactError as Error
from market_vault.cross_day_dataset._artifact_encoding import decode_json
from test_cross_day_live_issuance_runtime import forged_result


BUILT_AT = datetime(2026, 1, 2, tzinfo=timezone.utc)


def setup(tmp_path, monkeypatch, case="A", **fixture_options):
    inputs = fixture(tmp_path / "upstream", case, **fixture_options)
    result = execution.join_multi_source_cross_day_dataset(**inputs)
    model = MemoryFS(monkeypatch, tmp_path / "ONLY_IN_MEMORY_NOT_CREATED")
    return inputs, result, model


def publish(result, model):
    return m.materialize_multi_source_cross_day_dataset_build(result, output_root=model.root, built_at=BUILT_AT)


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G"])
def test_simulated_full_orchestration_and_existing_idempotence(tmp_path, monkeypatch, case):
    _, result, model = setup(tmp_path, monkeypatch, case)
    first = publish(result, model)
    assert first.created_new_build is True
    assert first.verified.dataset_id == result.dataset_id
    assert first.verified.rows == result.rows
    assert first.verified.status == result.status
    saved = model.artifact(result.dataset_id)
    mutations = model.mutations
    second = publish(result, model)
    assert second.created_new_build is False
    assert model.artifact(result.dataset_id) == saved
    assert model.mutations == mutations
    assert model.events.count("RENAME") == 1
    assert not model.root.exists(), "simulation must never publish on host D:"


@pytest.mark.parametrize("kind", ["object", "clone", "forged", "facts", "mutated"])
def test_invalid_live_input_has_zero_artifact_access(tmp_path, monkeypatch, kind):
    inputs, result, model = setup(tmp_path, monkeypatch)
    if kind == "object":
        result = object()
    elif kind == "clone":
        result = tamper(result)
    elif kind == "forged":
        result = forged_result(inputs, result)
    elif kind == "facts":
        result = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result)
    else:
        object.__setattr__(result, "dataset_id", "0" * 64)
    with pytest.raises(Error, match="INPUT_AUTHORITY"):
        publish(result, model)
    assert model.events == []


@pytest.mark.parametrize("point", ["bridge_return", "root_preflight"])
def test_pre_first_mutation_gate_rejects_changed_result(tmp_path, monkeypatch, point):
    _, result, model = setup(tmp_path, monkeypatch)
    if point == "bridge_return":
        original = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts
        def bridge(value):
            captured = original(value)
            object.__setattr__(value, "dataset_id", "0" * 64)
            return captured
        monkeypatch.setattr(execution, "_require_live_issued_multi_source_cross_day_dataset_artifact_facts", bridge)
    else:
        model.scope_hook = lambda: object.__setattr__(result, "dataset_id", "0" * 64)
    with pytest.raises(Error, match="INPUT_AUTHORITY"):
        publish(result, model)
    assert model.mutations == ()


def test_post_last_live_gate_mutation_never_enters_bytes(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    original_id = result.dataset_id
    def mutate(_):
        object.__setattr__(result.ts2_features.samples[0].values[0], "value", 999.0)
        object.__setattr__(result, "rows", ())
        object.__setattr__(result, "identity_input", None)
        object.__setattr__(result, "dataset_id", "0" * 64)
    model.create_hook = mutate
    output = publish(result, model)
    assert output.verified.dataset_id == original_id
    assert output.verified.ts2_features.samples[0].values[0].value == 0.25
    assert len(output.verified.rows) == 1


@pytest.mark.parametrize("conflict", [False, True])
def test_simulated_race_verifies_and_never_overwrites_winner(tmp_path, monkeypatch, conflict):
    _, result, model = setup(tmp_path, monkeypatch)
    winner = {}
    def race(staging, final):
        model.copy_winner(staging, final)
        if conflict:
            model.mutate(final / "_SUCCESS", b"bad")
        winner.update(model.artifact(result.dataset_id))
    model.rename_hook = race
    if conflict:
        with pytest.raises(Error, match="EXISTING_FINAL_INVALID"):
            publish(result, model)
    else:
        assert publish(result, model).created_new_build is False
    assert model.artifact(result.dataset_id) == winner
    assert model.events.count("RENAME") == 1
    assert model.events.count("REMOVE") == 1


def test_existing_corrupt_final_has_zero_mutation(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    publish(result, model)
    final = model.root / ("dataset_id=" + result.dataset_id)
    model.mutate(final / "_SUCCESS", b"bad")
    before, events = model.artifact(result.dataset_id), model.mutations
    with pytest.raises(Error, match="EXISTING_FINAL_INVALID"):
        publish(result, model)
    assert model.artifact(result.dataset_id) == before and model.mutations == events


def test_final_verification_failure_never_rolls_back(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    real_existing = m._existing
    def fail(*args):
        assert model.events.count("RENAME") == 1
        raise Error("CONTENT_MISMATCH", "PREFLIGHT", "injected postcommit reader failure")
    monkeypatch.setattr(m, "_existing", fail)
    with pytest.raises(Error) as caught:
        publish(result, model)
    assert caught.value.publication_state == "COMMITTED_INVALID"
    assert caught.value.reason_code == "FINAL_VERIFICATION_FAILED"
    assert "REMOVE" not in model.events
    assert model.artifact(result.dataset_id)
    monkeypatch.setattr(m, "_existing", real_existing)
    assert publish(result, model).created_new_build is False


@pytest.mark.parametrize("committed", [False, True])
def test_ambiguous_primitive_interruption_prohibits_cleanup(tmp_path, monkeypatch, committed):
    _, result, model = setup(tmp_path, monkeypatch)
    def interrupted(staging, final):
        if committed:
            model.copy_winner(staging, final)
        raise KeyboardInterrupt("ambiguous primitive interruption")
    model.rename_hook = interrupted
    with pytest.raises(Error) as caught:
        publish(result, model)
    assert caught.value.publication_state == "PUBLICATION_UNCERTAIN"
    assert "REMOVE" not in model.events
    assert len(model.nodes) > 1


@pytest.mark.parametrize("kind", ["same_size", "replacement", "extra", "manifest", "marker", "seal"])
def test_seal_drift_prevents_publication(tmp_path, monkeypatch, kind):
    _, result, model = setup(tmp_path, monkeypatch)
    original = m._verify_and_seal_staging
    def changed(owner):
        seal = original(owner)
        if kind == "same_size":
            path = owner.path / "dataset.parquet"
            model.mutate(path, b"x" * len(model.nodes[path][2]))
        elif kind == "replacement":
            model.mutate(owner.path / "dataset.parquet", replace=True)
        elif kind == "extra":
            model.nodes[owner.path / ".extra"] = (object(), False, b"")
        elif kind == "seal":
            object.__setattr__(seal, "dataset_id", "0" * 64)
        else:
            model.mutate(owner.path / ("manifest.json" if kind == "manifest" else "_SUCCESS"), b"bad")
        return seal
    monkeypatch.setattr(m, "_verify_and_seal_staging", changed)
    with pytest.raises(Error) as caught:
        publish(result, model)
    assert "RENAME" not in model.events
    if kind in ("replacement", "extra"):
        assert "REMOVE" not in model.events
        assert caught.value.cleanup_failure.reason_code == "CLEANUP_REFUSED"
        assert caught.value.residue_path in model.nodes
    else:
        assert model.events.count("REMOVE") == 1
        assert len(model.nodes) == 1


@pytest.mark.parametrize("denied", [False, True])
def test_partial_staging_cleanup_requires_no_manifest_or_seal(tmp_path, monkeypatch, denied):
    _, result, model = setup(tmp_path, monkeypatch)
    def fail(owner, name):
        raise OSError("injected write error")
    model.write_hook = fail
    if denied:
        def refuse(path):
            raise PermissionError("cleanup denied, no chmod permitted")
        model.remove_hook = refuse
    with pytest.raises(Error) as caught:
        publish(result, model)
    assert "RENAME" not in model.events
    assert model.events.count("REMOVE") == 1
    if denied:
        assert caught.value.cleanup_failure.reason_code == "CLEANUP_REFUSED"
        assert len(model.nodes) > 1
    else:
        assert len(model.nodes) == 1


def test_direct_owner_and_seal_fabrication_never_authorized(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    scope = model.scope(model.root)
    owner = m._Owner(scope, model.root / "fake", model.root / "final", result.dataset_id, (), {}, m.os.getpid())
    with pytest.raises(Error, match="OWNERSHIP_UNPROVEN"):
        m._remove_tree(owner)
    with pytest.raises(TypeError):
        m._PublicationSeal()
    forged = object.__new__(m._PublicationSeal)
    with pytest.raises(Error, match="OWNERSHIP_UNPROVEN"):
        m._publish(owner, forged)
    assert model.mutations == ()


def test_verified_reader_is_ledger_independent(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    published = publish(result, model)
    def forbidden(*args):
        raise AssertionError("reader consulted live issuance")
    monkeypatch.setattr(execution, "_require_live_issued_multi_source_cross_day_dataset_artifact_facts", forbidden)
    monkeypatch.setattr(execution, "_require_live_issued_multi_source_cross_day_dataset_result", forbidden)
    assert r.load_verified_multi_source_cross_day_dataset(published.verified.build_path).dataset_id == result.dataset_id
    with pytest.raises(TypeError):
        replace(published.verified)


@pytest.mark.parametrize("site,reason", [("_NativeScope", "UNSAFE_PATH"), ("_require_qualified", "PLATFORM_UNQUALIFIED")])
def test_preflight_native_failure_has_precise_envelope_and_no_mutation(tmp_path, monkeypatch, site, reason):
    _, result, model = setup(tmp_path, monkeypatch)
    error = PermissionError("native preflight denied")
    def denied(*args, **kwargs):
        raise error
    monkeypatch.setattr(m, site, denied)
    with pytest.raises(Error) as caught:
        publish(result, model)
    assert caught.value.reason_code == reason
    assert caught.value.publication_state == "PREFLIGHT"
    assert caught.value.__cause__ is error
    assert model.mutations == ()


@pytest.mark.parametrize("kind", ["copied", "foreign", "reused"])
def test_seal_is_exact_invocation_bound_and_single_use(tmp_path, monkeypatch, kind):
    _, result, model = setup(tmp_path, monkeypatch)
    original = m._publish
    previous = []
    def checked(owner, seal):
        if kind == "copied":
            clone = tamper(seal)
            with pytest.raises(Error, match="SEAL_AUTHORITY"):
                original(owner, clone)
        elif kind == "foreign":
            with pytest.raises(Error, match="OWNERSHIP_UNPROVEN"):
                original(tamper(owner), seal)
        original(owner, seal)
        previous.append((owner, seal))
        if kind == "reused":
            with pytest.raises(Error, match="OWNERSHIP_UNPROVEN"):
                original(owner, seal)
    monkeypatch.setattr(m, "_publish", checked)
    assert publish(result, model).created_new_build
    assert model.events.count("RENAME") == 1
    with pytest.raises(Error, match="OWNERSHIP_UNPROVEN"):
        m._revalidate_publication_seal(*previous[0])


def test_root_replaced_during_second_live_gate_fails_before_mutation(tmp_path, monkeypatch):
    _, result, model = setup(tmp_path, monkeypatch)
    original = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts
    calls = []
    def replace_root(value):
        facts = original(value)
        calls.append(facts)
        if len(calls) == 2:
            model.mutate(model.root, replace=True)
        return facts
    monkeypatch.setattr(execution, "_require_live_issued_multi_source_cross_day_dataset_artifact_facts", replace_root)
    with pytest.raises(Error, match="UNSAFE_PATH"):
        publish(result, model)
    assert len(calls) == 2 and model.mutations == ()
