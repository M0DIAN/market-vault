"""A4.1 canaries use real A2 verification and real A3 assembly, never trust stubs."""

import ast
import builtins
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import socket

import pytest

from market_vault.dataset.models import DatasetField
from market_vault.dataset.spec_models import SpecParameter
from market_vault.observation import assemble_observation_pit_sidecar
from market_vault.observation.pit_identity import observation_decision_id
from market_vault.multi_source import *
from market_vault.multi_source import feature_registry as registry, feature_transforms as transforms
from test_observation_pit_models import artifacts, bar, source, observation, clock


def spec(logical_type="float64", name="obs_rate", **changes):
    return ObservationFeatureSpec("observation-feature-spec-v1", name, "v1", DatasetField(name, logical_type, False),
        source(**({"input_field_names": ("rate" if logical_type == "float64" else "count",)} | changes)),
        "market_vault.multi_source.feature_transforms:identity_" + logical_type)


def assembled(builds, specs=None, *, empty=False, A=None):
    specs = (spec(),) if specs is None else specs
    result = assemble_observation_pit_sidecar(bar(empty=empty, A=A), builds,
                                             tuple(observation_feature_binding(s) for s in specs))
    return result, specs


def execute(builds, specs=None, **kwargs):
    result, specs = assembled(builds, specs, **kwargs)
    return execute_observation_features(result, builds, specs)


def copied(result, **changes):
    duplicate = object.__new__(type(result))
    for f in fields(result):
        object.__setattr__(duplicate, f.name, changes.get(f.name, getattr(result, f.name)))
    return duplicate


@pytest.mark.parametrize("logical_type,index", [("float64", 0), ("int64", 1)])
def test_canaries_05_08_09_exact_selected_value(artifacts, logical_type, index):
    row = observation()
    builds = (artifacts((row,)),)
    pit, specs = assembled(builds, (spec(logical_type),))
    result = execute_observation_features(pit, builds, specs)
    value = result.samples[0].values[0]
    assert value.value == row.values[index] and type(value.value) is type(row.values[index])
    assert value.consumed_observation_version_id == row.observation_version_id
    assert value.decision_id == observation_decision_id(pit.decisions[0])
    assert result.samples[0].multi_source_sample_version_id == pit.sample_bindings[0].multi_source_sample_version_id


@pytest.mark.parametrize("case", ["source", "missing", "extra", "duplicate"])
def test_canary_04_binding_mismatch_before_transform(artifacts, monkeypatch, case):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    altered = {"source": (replace(specs[0], source_spec=source(input_field_names=("rate",), max_age_us=20)),),
               "missing": (), "extra": specs + (spec(name="extra"),), "duplicate": specs + specs}[case]
    calls = []
    def forbidden(input_):
        calls.append(input_)
        pytest.fail("binding mismatch reached transform")
    monkeypatch.setattr(transforms, "identity_float64", forbidden)
    monkeypatch.setattr(registry, "_REGISTRATIONS", (replace(registry._REGISTRATIONS[0], implementation=forbidden), registry._REGISTRATIONS[1]))
    with pytest.raises(ObservationFeatureExecutionError):
        execute_observation_features(pit, builds, altered)
    assert calls == []


@pytest.mark.parametrize("attribute,value", [
    ("value_schema_id", "0" * 64), ("observation_version_id", "0" * 64),
    ("observation_key", "0" * 64), ("values", (9.5, 2)),
    ("source_snapshot_id", "0" * 64), ("known_at_authority_id", "0" * 64),
    ("known_at", clock(150)), ("normalization_content_id", "0" * 64),
])
def test_canaries_05_06_reject_mutated_verified_row(artifacts, attribute, value):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    object.__setattr__(builds[0].rows[0], attribute, value)
    with pytest.raises(ObservationFeatureExecutionError):
        execute_observation_features(pit, builds, specs)


@pytest.mark.parametrize("input_fields", [("missing",), ("rate", "rate")])
def test_canary_07_wrong_or_duplicate_field(artifacts, input_fields):
    builds = (artifacts(),)
    with pytest.raises(ValueError):
        bad = spec(input_field_names=input_fields)
        execute(builds, (bad,))


@pytest.mark.parametrize("logical_type,bad", [
    ("float64", 1), ("float64", True), ("float64", float("nan")),
    ("float64", float("inf")), ("float64", float("-inf")), ("float64", "1.0"),
    ("int64", 1.0), ("int64", True), ("int64", 2**63), ("int64", -(2**63)-1),
])
def test_canary_10_no_coercion(logical_type, bad):
    with pytest.raises(ObservationFeatureExecutionError):
        ObservationFeatureTransformInput(("x",), (logical_type,), (bad,), ())
    # The numeric implementation independently refuses malformed input.
    value = ObservationFeatureTransformInput(("x",), (logical_type,), (1.0 if logical_type == "float64" else 1,), ())
    object.__setattr__(value, "values", (bad,))
    with pytest.raises(ValueError):
        getattr(transforms, "identity_" + logical_type)(value)


def test_negative_zero_and_int64_edges():
    import math
    value = transforms.identity_float64(ObservationFeatureTransformInput(("x",), ("float64",), (-0.0,), ()))
    assert math.copysign(1.0, value) == 1.0
    for value in (-(2**63), 2**63 - 1):
        assert transforms.identity_int64(ObservationFeatureTransformInput(("x",), ("int64",), (value,), ())) == value


@pytest.mark.parametrize("reason", ["STALE", "NOT_REPORTED", "WITHDRAWN", "NO_ELIGIBLE_OBSERVATION", "FUTURE_KNOWN", "ARCHIVE_FUTURE"])
def test_canaries_11_12_excluded_never_calls_transform(artifacts, monkeypatch, reason):
    row = observation()
    A = None
    if reason == "STALE":
        row = observation(event=50)
    elif reason in ("NOT_REPORTED", "WITHDRAWN"):
        row = observation(value_status=reason, values=None)
    elif reason == "FUTURE_KNOWN":
        row = observation(known=101, archive=101)
    elif reason == "ARCHIVE_FUTURE":
        row, A = observation(archive=101), 100
    builds = (artifacts(() if reason == "NO_ELIGIBLE_OBSERVATION" else (row,)),)
    if A is not None:
        builds += (artifacts((), created=100),)
    pit, specs = assembled(builds, A=A)
    def forbidden(_):
        pytest.fail("EXCLUDED invoked transform")
    monkeypatch.setattr(transforms, "identity_float64", forbidden)
    monkeypatch.setattr(registry, "_REGISTRATIONS", (replace(registry._REGISTRATIONS[0], implementation=forbidden), registry._REGISTRATIONS[1]))
    value = execute_observation_features(pit, builds, specs).samples[0].values[0]
    assert value.status == "EXCLUDED" and value.reason_code == reason
    assert value.value is None and value.consumed_observation_version_id is None
    assert (pit.decisions[0].selected_observation_version_id is not None) == (reason in ("STALE", "NOT_REPORTED", "WITHDRAWN"))


@pytest.mark.parametrize("empty", [False, True])
def test_canaries_14_15_unknown_transform_fails(artifacts, empty):
    builds = () if empty else (artifacts(),)
    specs = (replace(spec(), transform_ref="untrusted.module:execute"),)
    pit, specs = assembled(builds, specs, empty=empty)
    with pytest.raises(ObservationFeatureExecutionError, match="unknown"):
        execute_observation_features(pit, builds, specs)


def test_canary_15_zero_sample_still_validates_registry_and_evidence(artifacts, monkeypatch):
    pit, specs = assembled((), empty=True)
    result = execute_observation_features(pit, (), specs)
    assert result.samples == () and len(result.implementation_pins) == 1
    assert len(observation_feature_values_content_id(result)) == 64
    with pytest.raises(ObservationFeatureExecutionError, match="extra"):
        execute_observation_features(pit, (artifacts(),), specs)
    monkeypatch.setattr(registry, "_REGISTRATIONS", registry._REGISTRATIONS[:1])
    with pytest.raises(ObservationFeatureExecutionError, match="registry"):
        execute_observation_features(pit, (), specs)


@pytest.mark.parametrize("case", ["missing", "extra", "duplicate", "created", "coverage", "snapshot"])
def test_exact_supplied_evidence_boundary(artifacts, case):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    if case == "missing":
        builds = ()
    elif case == "extra":
        builds += (artifacts((), effective=(80, 120)),)
    elif case == "duplicate":
        builds += builds
    elif case == "created":
        object.__setattr__(builds[0], "created_at", clock(301))
    elif case == "coverage":
        object.__setattr__(builds[0], "coverage", replace(builds[0].coverage, effective_end=clock(301)))
    else:
        object.__setattr__(builds[0], "source_snapshots", ())
    with pytest.raises(ObservationFeatureExecutionError):
        execute_observation_features(pit, builds, specs)


@pytest.mark.parametrize("field", ["observation_association_content_id", "sample_binding_content_id", "combined_association_content_id", "bar_association_schema_id"])
def test_a3_content_closure(artifacts, field):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    with pytest.raises(ObservationFeatureExecutionError):
        execute_observation_features(copied(pit, **{field: "0" * 64}), builds, specs)


@pytest.mark.parametrize("field", ["decisions", "evidence", "sample_bindings", "bindings"])
def test_a3_cardinality_closure(artifacts, field):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    for bad in ((), getattr(pit, field) * 2):
        with pytest.raises(ObservationFeatureExecutionError):
            execute_observation_features(copied(pit, **{field: bad}), builds, specs)


def test_order_relocation_and_no_io_execution(artifacts, monkeypatch):
    builds = (artifacts(), artifacts((), effective=(80, 120)))
    specs = (spec(), spec("int64", "count"))
    pit, specs = assembled(builds, specs)
    expected = execute_observation_features(pit, builds, specs)
    def forbidden(*args, **kwargs):
        pytest.fail("execution performed I/O or reran selection")
    from market_vault.observation import pit as a3
    monkeypatch.setattr(a3, "_decision", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    for build in builds:
        object.__setattr__(build, "build_dir", Path("D:/nonexistent-relocation"))
    assert execute_observation_features(pit, tuple(reversed(builds)), tuple(reversed(specs))) == expected
    with pytest.raises(FrozenInstanceError):
        expected.samples[0].values[0].value = 5


def test_preflight_all_samples_then_exactly_once(artifacts, monkeypatch):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    calls = []
    original = transforms.identity_float64
    def count(input_):
        calls.append(input_)
        return original(input_)
    monkeypatch.setattr(transforms, "identity_float64", count)
    monkeypatch.setattr(registry, "_REGISTRATIONS", (replace(registry._REGISTRATIONS[0], implementation=count), registry._REGISTRATIONS[1]))
    execute_observation_features(pit, builds, specs)
    assert len(calls) == 1


def test_result_constructor_cross_references(artifacts):
    result = execute((artifacts(),))
    sample = result.samples[0]
    value = sample.values[0]
    for changes in ({"value": True}, {"status": "PARTIAL"}, {"reason_code": "STALE"},
                    {"consumed_observation_version_id": None}, {"feature_name": "other"}):
        with pytest.raises(ValueError):
            replace(value, **changes)
    for changes in ({"values": (value, value)}, {"sample_key": "0" * 64}, {"status": "EXCLUDED"}):
        with pytest.raises(ValueError):
            replace(sample, **changes)
    for changes in ({"feature_spec_pins": ()}, {"implementation_pins": ()}, {"samples": (sample, sample)},
                    {"execution_contract_version": "future"}):
        with pytest.raises(ValueError):
            replace(result, **changes)


def test_package_boundary_no_deferred_api():
    import market_vault.multi_source as package
    assert not any(word in name for name in package.__all__ for word in ("materializ", "reader", "provider", "catalog"))
    root = Path(package.__file__).parent
    for filename in ("feature_execution.py", "_feature_validation.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        forbidden = {"open", "now", "getenv", "read_bytes", "write_bytes", "load_verified_observation_build", "_decision", "eligible"}
        calls = [n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else "" for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert not set(calls) & forbidden


@pytest.mark.parametrize("status", ["VALUE", "NOT_REPORTED"])
def test_field_type_mismatch_fails_even_for_selected_exclusion(artifacts, status):
    row = observation(value_status=status, values=observation().values if status == "VALUE" else None)
    builds = (artifacts((row,)),)
    specs = (spec(input_field_names=("count",)),)
    pit, specs = assembled(builds, specs)
    with pytest.raises(ObservationFeatureExecutionError, match="logical type"):
        execute_observation_features(pit, builds, specs)


@pytest.mark.parametrize("change", [
    {"parameters": (SpecParameter("unused", 1),)},
    {"output": DatasetField("obs_rate", "int64", False)},
])
def test_transform_contract_preflight_zero_samples(change):
    specs = (replace(spec(), **change),)
    pit, specs = assembled((), specs, empty=True)
    with pytest.raises(ObservationFeatureExecutionError, match="contract"):
        execute_observation_features(pit, (), specs)


@pytest.mark.parametrize("bad", [None, "D:/build", {}, []])
def test_executor_rejects_untrusted_input_types(bad):
    pit, specs = assembled((), empty=True)
    for args in ((bad, (), specs), (pit, bad, specs), (pit, (), bad)):
        with pytest.raises(ObservationFeatureExecutionError):
            execute_observation_features(*args)


def test_multiple_samples_specs_and_single_call_per_complete_pair(artifacts, monkeypatch):
    builds = (artifacts(),)
    specs = (spec(), spec("int64", "count"))
    one, two = bar(), bar(close=101)
    multi = replace(one, samples=one.samples + two.samples, diagnostics=replace(one.diagnostics, sample_count=2))
    pit = assemble_observation_pit_sidecar(multi, builds, tuple(observation_feature_binding(s) for s in specs))
    calls = []
    originals = (transforms.identity_float64, transforms.identity_int64)
    registrations = []
    for r, original in zip(registry._REGISTRATIONS, originals):
        def spy(value, original=original):
            calls.append(value)
            return original(value)
        monkeypatch.setattr(transforms, original.__name__, spy)
        registrations.append(replace(r, implementation=spy))
    monkeypatch.setattr(registry, "_REGISTRATIONS", tuple(registrations))
    result = execute_observation_features(pit, builds, tuple(reversed(specs)))
    assert len(calls) == 4
    assert len(result.samples) == 2
    assert [s.sample_key for s in result.samples] == sorted(s.sample_key for s in result.samples)
    assert all([v.feature_name for v in s.values] == ["count", "obs_rate"] for s in result.samples)


@pytest.mark.parametrize("field", ["selected_observation_key", "selected_observation_build_id", "selected_source_snapshot_id",
    "selected_known_at_authority_id", "selected_observation_version_id", "considered_observation_builds_digest"])
def test_selected_claim_tampering_fails(artifacts, field):
    builds = (artifacts(),)
    pit, specs = assembled(builds)
    changed = replace(pit.decisions[0], **{field: "0" * 64})
    with pytest.raises(ObservationFeatureExecutionError):
        execute_observation_features(copied(pit, decisions=(changed,)), builds, specs)


def test_complete_input_validation_precedes_first_transform(artifacts, monkeypatch):
    builds = (artifacts(),)
    specs = (spec(), spec("float64", "wrong", input_field_names=("count",)))
    pit, specs = assembled(builds, specs)
    def forbidden(_):
        pytest.fail("ran a transform before admission of later spec")
    monkeypatch.setattr(transforms, "identity_float64", forbidden)
    monkeypatch.setattr(registry, "_REGISTRATIONS", (replace(registry._REGISTRATIONS[0], implementation=forbidden), registry._REGISTRATIONS[1]))
    with pytest.raises(ObservationFeatureExecutionError, match="logical type"):
        execute_observation_features(pit, builds, specs)
