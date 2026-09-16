"""A4.2 offline orchestration over actual verified artifacts."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta

import pytest

from market_vault.multi_source import (
    MultiSourceDatasetError, orchestrate_multi_source_dataset_build, multi_source_dataset_id,
)
from test_dataset_orchestration import fixtures, feature_spec, label_spec, chronological_spec, request, dataset_scope
from test_observation_pit_models import artifacts, observation, T
from test_multi_source_feature_execution import spec


def offset(instant):
    delta = instant - T
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


@pytest.fixture
def observation_factory(artifacts):
    def make(*, rows=None, shift=0, created_shift=300, **kwargs):
        n = offset(request().feature_window_close)
        rows = (observation(event=n-5+shift, known=n-4+shift, archive=n-3+shift),) if rows is None else rows
        return artifacts(rows, effective=(n-86400000000, n+86400000000), knowledge=(0, n+86400000000),
                         created=n+created_shift, **kwargs)
    return make


def inputs(fixtures, observation_build, **changes):
    return dict(canonical_builds=(fixtures.a, fixtures.f), observation_builds=(observation_build,),
                requests=(request(),), bar_feature_specs=(feature_spec(),), observation_feature_specs=(spec(),),
                label_specs=(label_spec(),), split_spec=chronological_spec(), scope=dataset_scope(),
                dataset_as_of=None) | changes


def test_complete_roundtrip(fixtures, observation_factory):
    result = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory()))
    assert result.status == "COMPLETE" and len(result.rows) == 1
    row = result.logical_row_mappings()[0]
    assert row["sample_key"] == result.bar_pit_result.samples[0].sample_key
    assert row["sample_version_id"] == result.observation_pit_result.sample_bindings[0].multi_source_sample_version_id
    assert row["sample_version_id"] != result.bar_pit_result.samples[0].sample_version_id
    assert row["obs_rate"] == result.observation_feature_result.samples[0].values[0].value
    assert result.dataset_id == multi_source_dataset_id(result.identity_input)
    assert replace(result).dataset_id == result.dataset_id
    from market_vault.multi_source.identity import _identity_payload
    from test_multi_source_identity import encoder_payload
    assert set(_identity_payload(result.identity_input)) == set(encoder_payload())


@pytest.mark.parametrize("case", ["bar", "observation", "both", "label", "excluded_label", "zero"])
def test_exclusion_and_empty_provenance(fixtures, observation_factory, case):
    changes = {}
    if case in ("bar", "both", "excluded_label"):
        changes["bar_feature_specs"] = (feature_spec(window_bars=100),)
    if case in ("observation", "both"):
        changes["observation_feature_specs"] = (spec(max_age_us=1),)
    if case in ("label", "excluded_label"):
        changes["canonical_builds"] = (fixtures.a,)
    if case == "zero":
        changes["requests"] = ()
    result = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(), **changes))
    count = 0 if case == "zero" else 1
    assert len(result.sample_audit) == len(result.observation_evidence) == count
    if case == "label":
        assert len(result.rows) == 1
        assert result.logical_row_mappings()[0]["fr"] is None
        assert result.completion.entries[0].reason_code == "LABEL_INCOMPLETE"
    else:
        assert result.status == "EMPTY" and not result.rows
        assert result.completion.entries[0].reason_code == (
            "NO_SAMPLE_REQUEST" if case == "zero" else "MULTI_SOURCE_FEATURE_EXCLUDED_AND_LABEL_INCOMPLETE"
            if case == "excluded_label" else "MULTI_SOURCE_FEATURE_EXCLUDED")


def test_deeply_immutable_result(fixtures, observation_factory):
    r = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory()))
    with pytest.raises(FrozenInstanceError):
        r.dataset_id = "0" * 64
    with pytest.raises(TypeError):
        r.bar_pit_result.association_rows[0]["code"] = "US.OTHER"
    with pytest.raises(TypeError):
        r.split_result.assignment_rows[0]["sample_key"] = "0" * 64
    with pytest.raises(TypeError):
        r.diagnostics["request_count"] = 99


@pytest.mark.parametrize("name,value", [
    ("canonical_builds", ()), ("observation_builds", ()), ("bar_feature_specs", ()),
    ("observation_feature_specs", ()), ("label_specs", ()), ("requests", []),
    ("dataset_kind", "UNSUPERVISED"), ("dataset_as_of", "latest"), ("scope", None), ("split_spec", None),
])
def test_invalid_input_fails(fixtures, observation_factory, name, value):
    with pytest.raises(MultiSourceDatasetError):
        orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(), **{name: value}))


@pytest.mark.parametrize("family,name", [("bar_feature_specs", "obs_rate"), ("label_specs", "obs_rate"),
    ("observation_feature_specs", "dataset_as_of"), ("observation_feature_specs", "sample_key")])
def test_canaries_23_24_output_collisions(fixtures, observation_factory, family, name):
    factory = {"bar_feature_specs": feature_spec, "label_specs": label_spec, "observation_feature_specs": spec}[family]
    with pytest.raises(MultiSourceDatasetError, match="collide"):
        orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(), **{family: (factory(name=name),)}))


@pytest.mark.parametrize("empty", [False, True])
def test_zero_and_nonzero_preflight_remains_strict(fixtures, observation_factory, empty):
    bad = replace(spec(), transform_ref="evil.module:identity")
    with pytest.raises(MultiSourceDatasetError, match="unknown"):
        orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(),
            observation_feature_specs=(bad,), requests=() if empty else (request(),)))


def test_canaries_25_26_unused_proof_and_clock(fixtures, observation_factory):
    selected = observation_factory()
    unused = observation_factory(rows=())
    first = orchestrate_multi_source_dataset_build(**inputs(fixtures, selected))
    extra = orchestrate_multi_source_dataset_build(**inputs(fixtures, selected, observation_builds=(selected, unused)))
    later_clock = observation_factory(created_shift=400)
    later = orchestrate_multi_source_dataset_build(**inputs(fixtures, later_clock))
    assert selected.observation_build_id == later_clock.observation_build_id
    assert first.dataset_id != extra.dataset_id != later.dataset_id != first.dataset_id
    assert first.observation_feature_result.samples[0].values[0].value == extra.observation_feature_result.samples[0].values[0].value
    assert len(extra.observation_evidence[0].build_pins) == 2


def test_A3_canary_26_same_logical_build_distinct_physical_proofs(fixtures, observation_factory):
    from market_vault.observation.pit_identity import observation_build_pin_id

    one, two = observation_factory(created_shift=300), observation_factory(created_shift=400)
    assert one.observation_build_id == two.observation_build_id
    data = inputs(fixtures, one)
    result = orchestrate_multi_source_dataset_build(**(data | dict(observation_builds=(one, two))))
    evidence, = result.observation_evidence
    assert evidence == result.observation_pit_result.evidence[0]
    assert len(evidence.build_pins) == len(evidence.coverages) == 2
    assert {p.observation_build_id for p in evidence.build_pins} == {one.observation_build_id}
    assert {p.coverage_proof_available_at for p in evidence.build_pins} == {one.created_at, two.created_at}
    pin_ids = tuple(sorted(observation_build_pin_id(p) for p in evidence.build_pins))
    assert len(set(pin_ids)) == 2
    assert result.identity_input.observation_build_pin_ids == pin_ids
    for build in (one, two):
        single = orchestrate_multi_source_dataset_build(**(data | dict(observation_builds=(build,))))
        assert result.observation_evidence_content_id != single.observation_evidence_content_id
        assert result.dataset_id != single.dataset_id
        assert result.observation_feature_result.samples[0].values[0].value == single.observation_feature_result.samples[0].values[0].value
    reversed_result = orchestrate_multi_source_dataset_build(**(data | dict(observation_builds=(two, one))))
    assert result.dataset_id == reversed_result.dataset_id
    assert result.observation_evidence == reversed_result.observation_evidence
    for index in (0, 1):
        builds = [one, two]
        builds[index] = observation_factory(created_shift=500)
        changed = orchestrate_multi_source_dataset_build(**(data | dict(observation_builds=tuple(builds))))
        assert result.observation_evidence_content_id != changed.observation_evidence_content_id
        assert result.dataset_id != changed.dataset_id


@pytest.mark.parametrize("empty", [False, True])
def test_duplicate_complete_proof_rejected_even_without_samples(fixtures, observation_factory, empty):
    one, duplicate = observation_factory(), observation_factory()
    with pytest.raises(MultiSourceDatasetError, match="duplicate"):
        orchestrate_multi_source_dataset_build(**inputs(fixtures, one, observation_builds=(one, duplicate),
            requests=() if empty else (request(),)))


def test_canaries_27_28_decision_and_spec_change(fixtures, observation_factory):
    build = observation_factory()
    first = orchestrate_multi_source_dataset_build(**inputs(fixtures, build))
    stale = orchestrate_multi_source_dataset_build(**inputs(fixtures, build, observation_feature_specs=(spec(max_age_us=1),)))
    different_spec = orchestrate_multi_source_dataset_build(**inputs(fixtures, build, observation_feature_specs=(spec(max_age_us=20),)))
    assert len({r.dataset_id for r in (first, stale, different_spec)}) == 3
    assert stale.observation_pit_result.decisions[0].reason == "STALE"
    assert stale.observation_feature_result.samples[0].values[0].consumed_observation_version_id is None


def test_canary_29_order_invariance(fixtures, observation_factory):
    builds = (observation_factory(), observation_factory(rows=()))
    data = inputs(fixtures, builds[0], observation_builds=builds,
        requests=(request(), request(f_start=request().feature_window_start + timedelta(minutes=1))),
        bar_feature_specs=(feature_spec("z_bar"), feature_spec("a_bar")),
        observation_feature_specs=(spec(name="z_obs"), spec("int64", name="a_obs")),
        label_specs=(label_spec("z_label"), label_spec("a_label")))
    one = orchestrate_multi_source_dataset_build(**data)
    reversed_data = {k: v[::-1] if isinstance(v, tuple) else v for k, v in data.items()}
    two = orchestrate_multi_source_dataset_build(**reversed_data)
    assert one.dataset_id == two.dataset_id and one.rows == two.rows
    assert one.sample_audit == two.sample_audit and one.observation_evidence == two.observation_evidence


def test_canary_30_real_relocation(fixtures, observation_factory, tmp_path):
    import shutil
    from market_vault.canonical import load_verified_canonical_build
    from market_vault.observation import load_verified_observation_build
    build = observation_factory()
    data = inputs(fixtures, build)
    one = orchestrate_multi_source_dataset_build(**data)
    relocated = []
    for index, canonical in enumerate(data["canonical_builds"]):
        target = tmp_path / "relocated" / str(index) / canonical.build_path.name
        shutil.copytree(canonical.build_path, target)
        relocated.append(load_verified_canonical_build(target))
    target = tmp_path / "relocated" / "observation" / build.build_dir.name
    shutil.copytree(build.build_dir, target)
    two = orchestrate_multi_source_dataset_build(**(data | dict(canonical_builds=tuple(relocated),
        observation_builds=(load_verified_observation_build(target),))))
    assert one.dataset_id == two.dataset_id and one.rows == two.rows


def test_canary_31_empty_matrix_retains_distinct_outcomes(fixtures, observation_factory):
    build = observation_factory()
    excluded = dict(bar_feature_specs=(feature_spec(window_bars=100),))
    first = orchestrate_multi_source_dataset_build(**inputs(fixtures, build, **excluded))
    second = orchestrate_multi_source_dataset_build(**inputs(fixtures, build,
        observation_feature_specs=(spec(max_age_us=1),), **excluded))
    assert first.rows == second.rows == ()
    assert first.logical_dataset_content_id == second.logical_dataset_content_id
    assert first.dataset_id != second.dataset_id
    assert len(first.sample_audit) == len(first.observation_evidence) == 1
    assert first.identity_input.canonical_builds and first.identity_input.implementations


@pytest.mark.parametrize("field", ["dataset_schema_id", "sample_audit_content_id", "observation_evidence_content_id",
    "combined_association_content_id", "bar_association_content_id"])
def test_public_identity_rejects_inconsistent_claims(fixtures, observation_factory, field):
    result = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory()))
    with pytest.raises(MultiSourceDatasetError):
        replace(result.identity_input, **{field: "0" * 64})


@pytest.mark.parametrize("field", ["bar_pit_result", "observation_pit_result", "bar_feature_result",
    "observation_feature_result", "label_result", "split_result"])
def test_result_revalidates_cross_layer_cardinality(fixtures, observation_factory, field):
    build = observation_factory()
    full = orchestrate_multi_source_dataset_build(**inputs(fixtures, build))
    empty = orchestrate_multi_source_dataset_build(**inputs(fixtures, build, requests=()))
    with pytest.raises(MultiSourceDatasetError):
        replace(full, **{field: getattr(empty, field)})


def test_canary_13_fingerprint_propagates_to_dataset(fixtures, observation_factory, monkeypatch):
    from market_vault.multi_source import feature_registry
    from market_vault.multi_source.feature_identity import _implementation_fingerprint, _source_sha256
    data = inputs(fixtures, observation_factory())
    one = orchestrate_multi_source_dataset_build(**data)
    source_hash = _source_sha256(b"independently-versioned-implementation-fixture\n")
    changed = tuple(replace(r, implementation_content_sha256=_implementation_fingerprint(
        r.transform_ref, source_hash, r.output_logical_type)) for r in feature_registry._REGISTRATIONS)
    monkeypatch.setattr(feature_registry, "_SOURCE_SHA256", source_hash)
    monkeypatch.setattr(feature_registry, "_REGISTRATIONS", changed)
    two = orchestrate_multi_source_dataset_build(**data)
    assert one.rows == two.rows and one.observation_pit_result == two.observation_pit_result
    assert one.observation_feature_values_content_id != two.observation_feature_values_content_id
    assert one.dataset_id != two.dataset_id


def test_A42_INHERITED_REGISTRY_SOURCE_READ_BOUNDARY(fixtures, observation_factory, monkeypatch, record_property):
    import builtins
    import inspect
    import io
    import linecache
    import os
    import socket
    import sys
    import tokenize
    from market_vault.dataset.feature_registry import built_in_feature_registrations
    from market_vault.dataset.label_registry import built_in_label_registrations
    import market_vault.dataset.orchestration as old
    import market_vault.multi_source.orchestration as pipeline

    data = inputs(fixtures, observation_factory())
    registrations = built_in_feature_registrations() + built_in_label_registrations()
    targets = {sys.modules[r.implementation.__module__].__file__ for r in registrations}
    normalized = {os.path.normcase(p) for p in targets}
    linecache.clearcache()
    reads, calls = [], []
    real_open, real_io_open, real_stat = builtins.open, io.open, os.stat

    def allowed(path):
        frame = sys._getframe(1)
        inherited = False
        while frame is not None:
            if (frame.f_globals.get("__name__") == "market_vault.dataset.transform_models"
                    and frame.f_code.co_name == "_module_source_sha256"):
                inherited = True
                break
            frame = frame.f_back
        assert inherited, "filesystem call outside inherited fingerprint stack"
        assert os.path.normcase(os.fspath(path)) in normalized, "unapproved source read target"

    def guarded_open(original):
        def read(path, mode="r", *args, **kwargs):
            allowed(path)
            assert mode in ("r", "rb"), "filesystem write"
            reads.append(os.fspath(path))
            return original(path, mode, *args, **kwargs)
        return read

    def stat(path, *args, **kwargs):
        allowed(path)
        return real_stat(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden filesystem/network/old-orchestrator access")

    layer_names = ("assemble_point_in_time_samples", "assemble_observation_pit_sidecar", "execute_builtin_features",
        "execute_observation_features", "execute_builtin_labels", "assign_chronological_splits")
    for name in layer_names:
        original = getattr(pipeline, name)
        def trace(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(pipeline, name, trace)
    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", guarded_open(real_open))
        guard.setattr(io, "open", guarded_open(real_io_open))
        guard.setattr(tokenize, "_builtin_open", guarded_open(tokenize._builtin_open))
        guard.setattr(os, "stat", stat)
        for name in ("listdir", "scandir", "mkdir", "remove", "rename", "replace", "unlink", "getcwd", "getenv"):
            guard.setattr(os, name, forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(socket.socket, "connect", forbidden)
        guard.setattr(old, "orchestrate_dataset_build", forbidden)
        result = pipeline.orchestrate_multi_source_dataset_build(**data)
        with pytest.raises(AssertionError, match="outside"):
            builtins.open("not-an-inherited-source")
    assert result.rows and calls == list(layer_names)
    assert {os.path.normcase(p) for p in reads} == normalized
    record_property("A4_2_OWN_FILESYSTEM_READ_COUNT", 0)
    record_property("A4_2_OWN_FILESYSTEM_WRITE_COUNT", 0)
    record_property("UNAUTHORIZED_FILESYSTEM_ACCESS_COUNT", 0)
    record_property("INHERITED_REGISTRY_SOURCE_READS_OBSERVED", len(reads))
    record_property("INHERITED_REGISTRY_SOURCE_READ_TARGETS", ";".join(sorted(targets)))


@pytest.mark.parametrize("key", ["canonical_builds", "observation_builds", "requests", "bar_feature_specs",
    "observation_feature_specs", "label_specs"])
def test_duplicate_semantic_inputs_rejected(fixtures, observation_factory, key):
    data = inputs(fixtures, observation_factory())
    data[key] += data[key]
    with pytest.raises(MultiSourceDatasetError):
        orchestrate_multi_source_dataset_build(**data)


def test_cutoff_and_missing_completion(fixtures, observation_factory):
    from datetime import date, datetime, timezone
    scope = dataset_scope(trade_dates=(date(2026, 7, 1), date(2026, 7, 2)))
    cutoff = datetime(2026, 9, 1, tzinfo=timezone.utc)
    r = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory(), scope=scope, dataset_as_of=cutoff))
    assert r.logical_row_mappings()[0]["dataset_as_of"] == cutoff
    assert r.completion.complete_count == r.completion.missing_count == 1
    assert all(a.dataset_as_of == cutoff for a in r.sample_audit)


@pytest.mark.parametrize("what", ["audit_role", "audit_version", "audit_status", "proof_pair", "unpinned_row", "duplicate_spec"])
def test_identity_and_audit_admission(fixtures, observation_factory, what):
    r = orchestrate_multi_source_dataset_build(**inputs(fixtures, observation_factory()))
    with pytest.raises((MultiSourceDatasetError, ValueError)):
        if what == "audit_role":
            replace(r.sample_audit[0], feature_canonical_row_version_ids=())
        elif what == "audit_version":
            replace(r.sample_audit[0], bar_sample_version_id="0"*64)
        elif what == "audit_status":
            replace(r.sample_audit[0], bar_feature_status="EXCLUDED")
        elif what == "proof_pair":
            e = r.observation_evidence[0]
            altered = replace(e, coverages=(replace(e.coverages[0], normalized_request_id="0"*64),))
            replace(r.identity_input, observation_evidence=(altered,))
        elif what == "unpinned_row":
            replace(r.identity_input, canonical_row_version_ids=("0"*64,))
        else:
            replace(r.identity_input, bar_feature_specs=r.identity_input.bar_feature_specs*2)


def test_A42_owned_modules_have_no_io_or_deferred_surface():
    import ast
    from pathlib import Path
    import market_vault.multi_source as package
    root = Path(package.__file__).parent
    names = ("orchestration.py", "orchestration_models.py", "identity.py", "_audit.py", "_evidence.py",
             "_orchestration_closure.py", "_orchestration_validation.py")
    forbidden = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "stat", "resolve", "glob",
                 "iterdir", "listdir", "scandir", "now", "utcnow", "getenv", "getcwd", "rename", "rmtree",
                 "load_verified_canonical_build", "load_verified_observation_build", "orchestrate_dataset_build"}
    for name in names:
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        calls = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert not calls & forbidden, name
    assert all(not (root / name).exists() for name in ("materialization.py", "reader.py", "manifest.py"))
