"""IR1: logical closure is not exact-object, process-local live issuance."""

import ast
import builtins
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
import gc
import importlib
import inspect
import io
import multiprocessing
import os
import socket
from pathlib import Path
from threading import Event
import time
from types import MappingProxyType
import weakref

import pytest

from cross_day_dataset_helpers import fixture, tamper
import market_vault.cross_day_dataset as package
from market_vault.cross_day_dataset import execution as engine
from market_vault.cross_day_dataset import _live_issuance as snapshots
from market_vault.cross_day_dataset.models import MultiSourceCrossDayDatasetResult as Result
from market_vault.cross_day_dataset._validation import MultiSourceCrossDayDatasetError as Error
from market_vault.cross_day_dataset.identity import (
    MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION, _payload, multi_source_cross_day_dataset_id,
)
from market_vault.dataset.encoding import encode_identity


SIGNATURE = "(*, feature_pit: market_vault.dataset.pit_models.PITAssemblyResult, ts2_features: market_vault.ts2_feature.models.TS2FeatureExecutionResult, observation_pit: market_vault.observation.pit_models.ObservationPITAssemblyResult, observation_builds: tuple[market_vault.observation.artifact_models.VerifiedObservationBuild, ...], observation_feature_specs: tuple[market_vault.multi_source.feature_spec_models.ObservationFeatureSpec, ...], observation_features: market_vault.multi_source.feature_models.ObservationFeatureExecutionResult, cross_day_association: market_vault.cross_day.assembly.CrossDayLabelAssemblyResult, cross_day_labels: market_vault.cross_day.execution.CrossDayLabelExecutionResult, schedule: market_vault.cross_day.schedule.VerifiedTradingDaySchedule, scope: market_vault.dataset.models.DatasetScope, split_spec: market_vault.dataset.split_models.ChronologicalSplitSpec, dataset_as_of: datetime.datetime | None) -> market_vault.cross_day_dataset.models.MultiSourceCrossDayDatasetResult"
EXPORTS = ["CrossDayAnchor","generate_cross_day_feature_requests","MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION","MultiSourceCrossDayDatasetError","join_multi_source_cross_day_dataset","MultiSourceCrossDayDatasetIdentityInput","MultiSourceCrossDayDatasetResult","MultiSourceCrossDaySampleAudit","MultiSourceCrossDayCompletionEntry","MultiSourceCrossDayCompletionSummary","MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION","MULTI_SOURCE_CROSS_DAY_DATASET_ORCHESTRATION_CONTRACT_VERSION","MULTI_SOURCE_CROSS_DAY_SAMPLE_AUDIT_VERSION","cross_day_dataset_sequence_id","multi_source_cross_day_dataset_id","multi_source_cross_day_sample_audit_id","multi_source_cross_day_completion_entry_id","multi_source_cross_day_completion_content_id"]
PUBLIC_FIELDS = tuple(["identity_input","dataset_id","scope","dataset_as_of","schema","rows","sample_audit","completion","split_result","feature_pit","ts2_features","observation_pit","observation_builds","observation_feature_specs","observation_features","cross_day_association","cross_day_labels","schedule","status"])
verify = engine._require_live_issued_multi_source_cross_day_dataset_result


def reject(result):
    with pytest.raises(Error, match="RESULT_AUTHORITY"):
        verify(result)


def closure_state():
    # Tests inspect closure state only for deterministic ABA/lifecycle injection.
    # No production enrollment, debug or registry API is provided.
    return inspect.getclosurevars(engine.join_multi_source_cross_day_dataset).nonlocals


@pytest.fixture
def issued(tmp_path):
    inputs = fixture(tmp_path)
    return inputs, engine.join_multi_source_cross_day_dataset(**inputs)


def test_public_abi_and_closed_type_table(issued):
    _, result = issued
    assert tuple(f.name for f in fields(Result)) == PUBLIC_FIELDS
    assert len(fields(Result)) == 19
    assert "__weakref__" not in PUBLIC_FIELDS
    assert weakref.ref(result)() is result
    assert str(inspect.signature(engine.join_multi_source_cross_day_dataset)) == SIGNATURE
    assert package.__all__ == EXPORTS + [
        "MultiSourceCrossDayArtifactError", "MultiSourceCrossDayDatasetMaterializationResult",
        "VerifiedMultiSourceCrossDayDataset", "materialize_multi_source_cross_day_dataset_build",
        "load_verified_multi_source_cross_day_dataset",
    ]
    assert not hasattr(engine, "_make_live_boundary")
    for module in (package, engine, snapshots):
        assert not any(name in vars(module) for name in (
            "_register_result", "_register_live_result", "_mark_issued", "_trust_result", "_enroll", "_issue_token"))
        assert not any(type(v) is dict and id(result) in v for v in vars(module).values())
    assert not vars(engine.join_multi_source_cross_day_dataset)
    for cls, names in snapshots._FIELDS.items():
        assert names == tuple(f.name for f in fields(cls))
    assert snapshots._same_capture(result, *snapshots._capture(result)) is None


@pytest.mark.parametrize("case", ["A", "B", "C", "D", "E", "F", "G", "H_considered", "H_backing"])
def test_genuine_complete_empty_and_full_record_variants(tmp_path, case):
    result = engine.join_multi_source_cross_day_dataset(**fixture(tmp_path, case, two_proofs=True))
    assert verify(result) is None
    assert result.status == ("COMPLETE" if result.rows else "EMPTY")
    assert multi_source_cross_day_dataset_id(result.identity_input) == result.dataset_id


def test_genuine_gap_records_are_in_snapshot(tmp_path):
    inputs = fixture(tmp_path, slots=(0, 1, 3), n=2)
    result = engine.join_multi_source_cross_day_dataset(**inputs)
    assert any(build.gap_ranges for build in result.identity_input.canonical_builds)
    assert verify(result) is None


@pytest.mark.parametrize("kind", ["direct", "replace", "tamper", "object-new", "copied-fields"])
def test_clones_are_never_live_issued(issued, kind):
    _, result = issued
    values = {f.name: getattr(result, f.name) for f in fields(Result)}
    if kind in ("direct", "replace"):
        with pytest.raises(Error, match="RESULT_AUTHORITY"):
            Result(**values) if kind == "direct" else replace(result)
    else:
        clone = tamper(result) if kind == "tamper" else object.__new__(Result)
        for name, value in values.items():
            object.__setattr__(clone, name, value)
        assert multi_source_cross_day_dataset_id(clone.identity_input) == result.dataset_id
        reject(clone)
        # No scalar token slot exists; even a complete public field copy is unissued.
        with pytest.raises((AttributeError, TypeError)):
            object.__setattr__(clone, "_token", result.dataset_id)


@pytest.mark.parametrize("name", PUBLIC_FIELDS)
def test_every_public_projection_replacement_is_detected(issued, name):
    _, result = issued
    original = getattr(result, name)
    if type(original) is tuple:
        replacement = tuple(list(original))
        if replacement is original:
            replacement = (None,)
    elif name in ("dataset_id", "status"):
        replacement = "mutated"
    elif name == "dataset_as_of":
        replacement = original.replace(microsecond=original.microsecond + 1)
    else:
        replacement = tamper(original)
    object.__setattr__(result, name, replacement)
    reject(result)


@pytest.mark.parametrize("kind", ["in-place", "equal-replacement", "signed-zero", "bool-int", "unexpected", "cycle", "root-cycle"])
def test_nested_graph_drift_and_type_exactness(issued, kind):
    _, result = issued
    value = result.ts2_features.samples[0].values[0]
    if kind == "in-place":
        object.__setattr__(value, "value", 999.0)
    elif kind == "equal-replacement":
        object.__setattr__(value, "spec_pin", tamper(value.spec_pin))
    elif kind == "signed-zero":
        # Initial value in this fixture is 0.25. Capture a separate graph baseline at +0.
        object.__setattr__(value, "value", 0.0)
        baseline = snapshots._capture(result)
        object.__setattr__(value, "value", -0.0)
        with pytest.raises(Error, match="typed snapshot"):
            snapshots._same_capture(result, *baseline)
    elif kind == "bool-int":
        audit = result.sample_audit[0]
        object.__setattr__(audit, "matrix_eligible", 1)
    elif kind == "unexpected":
        class TrapMeta(type):
            def __hash__(cls):
                raise AssertionError("caller hash executed")
        class Trap(metaclass=TrapMeta):
            def __eq__(self, other):
                raise AssertionError("caller equality executed")
        object.__setattr__(value, "value", Trap())
    elif kind == "cycle":
        object.__setattr__(value, "spec_pin", value)
    else:
        object.__setattr__(value, "spec_pin", result)
    reject(result)


def forged_result(inputs, genuine):
    sample = genuine.ts2_features.samples[0]
    value = sample.values[0]
    assert value.value == 0.25
    ts2 = tamper(genuine.ts2_features, samples=(tamper(sample, values=(tamper(value, value=999.0),)),))
    admitted = engine.admit_inputs(**(inputs | {"ts2_features": ts2}))
    split = engine._validated_split(admitted, genuine.split_result)
    declaration = engine._declaration(admitted, split, engine._project(admitted, split))
    dataset_id = encode_identity(MULTI_SOURCE_CROSS_DAY_DATASET_ID_VERSION, _payload(declaration))
    changes = {f.name: getattr(declaration, f.name) for f in fields(Result)
               if f.name not in ("identity_input", "dataset_id", "status")}
    return tamper(genuine, **changes, identity_input=declaration, dataset_id=dataset_id)


def test_ir1_exact_historical_coordinated_forgery(issued, record_property):
    inputs, genuine = issued
    forged = forged_result(inputs, genuine)
    # Reproduction evidence only: not additions to the eight frozen Dataset vectors.
    assert genuine.dataset_id == "2f5355e7cc30ab7a984f9ff959b10e8d8b949e89e453b0e43c0d88a6a36f06c8"
    assert forged.dataset_id == "97ecb5d9951e6685475e73d273b44605dcd67fb60d3e724c6c8263d4711e5a9d"
    engine._validate_identity_input(forged.identity_input)
    assert multi_source_cross_day_dataset_id(forged.identity_input) == forged.dataset_id
    reject(forged)
    assert verify(genuine) is None
    # Coordinately overwrite the genuine, ledger-member object too.
    for field in fields(Result):
        object.__setattr__(genuine, field.name, getattr(forged, field.name))
    engine._validate_identity_input(genuine.identity_input)
    reject(genuine)
    record_property("SUPPLEMENTAL_LIVE_ISSUANCE_CANARY", "IR1")
    record_property("LOGICAL_IDENTITY_VALIDATION_NE_LIVE_RESULT_ISSUANCE_AUTHORITY", True)


def test_gc_drops_entry_and_graph_without_retaining_result(tmp_path):
    inputs = fixture(tmp_path)
    result = engine.join_multi_source_cross_day_dataset(**inputs)
    key = id(result)
    state = closure_state()
    ref = weakref.ref(result)
    assert key in state["ledger"]
    del result
    gc.collect()
    assert ref() is None
    assert key not in state["ledger"]


def test_stale_callback_and_id_reuse_do_not_authorize_or_remove_new_entry(issued):
    inputs, original = issued
    other = engine.join_multi_source_cross_day_dataset(**inputs)
    state = closure_state()
    ledger = state["ledger"]
    key = id(original)
    entry = ledger[key]
    callback = entry.ref.__callback__
    # Simulate a reused numeric key with another exact weakref; no registration API.
    replacement = replace(entry, ref=weakref.ref(other))
    ledger[key] = replacement
    try:
        callback(entry.ref)
        assert ledger[key] is replacement
        reject(original)
        assert verify(other) is None
    finally:
        ledger[key] = entry
    replacement = replace(entry, epoch=object())
    ledger[key] = replacement
    try:
        callback(entry.ref)
        assert ledger[key] is replacement
        reject(original)
    finally:
        ledger[key] = entry
    replacement = replace(entry, generation=object())
    ledger[key] = replacement
    try:
        callback(entry.ref)
        assert ledger[key] is replacement
        reject(original)
    finally:
        ledger[key] = entry
    assert verify(original) is None


def test_multiple_independent_results_and_concurrent_join_verify(issued):
    inputs, original = issued
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: engine.join_multi_source_cross_day_dataset(**inputs), range(8)))
        assert all(r is not original and r.dataset_id == original.dataset_id for r in results)
        assert list(pool.map(verify, results * 2)) == [None] * 16
    object.__setattr__(results[0], "status", "EMPTY")
    reject(results[0])
    assert verify(results[1]) is None
    assert verify(original) is None


def test_logical_validation_outside_lock_and_post_validation_drift(issued, monkeypatch):
    inputs, original = issued
    other = engine.join_multi_source_cross_day_dataset(**inputs)
    entered, release = Event(), Event()
    real = engine._validate_identity_input

    def paused(declaration):
        real(declaration)
        if declaration is original.identity_input:
            entered.set()
            assert release.wait(20)

    monkeypatch.setattr(engine, "_validate_identity_input", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(verify, original)
        assert entered.wait(20)
        try:
            assert pool.submit(verify, other).result(timeout=20) is None
            object.__setattr__(original, "rows", tuple(list(original.rows)))
        finally:
            release.set()
        with pytest.raises(Error, match="RESULT_AUTHORITY"):
            first.result(timeout=20)


def test_logical_validation_does_not_consult_or_enroll_ledger(issued):
    _, original = issued
    state = closure_state()
    entry = state["ledger"].pop(id(original))
    try:
        assert multi_source_cross_day_dataset_id(original.identity_input) == original.dataset_id
        assert id(original) not in state["ledger"]
        reject(original)
    finally:
        state["ledger"][id(original)] = entry


def test_capture_failure_cannot_return_or_enroll_result(issued, monkeypatch):
    inputs, original = issued
    ledger = closure_state()["ledger"]
    before = dict(ledger)
    def fail(result):
        raise Error("RESULT_AUTHORITY", "snapshot capture failed")
    monkeypatch.setattr(snapshots, "_capture", fail)
    with pytest.raises(Error, match="capture failed"):
        engine.join_multi_source_cross_day_dataset(**inputs)
    # Unrelated weak entries may expire during validation; none may be added or replaced.
    assert set(ledger) <= set(before)
    assert all(record is before[key] for key, record in ledger.items())
    assert ledger[id(original)] is before[id(original)]
    assert id(original) in ledger


def _process_worker(connection, mode, root, parent=None, dataset_id=None):
    try:
        import market_vault.cross_day_dataset.execution as execution
        def refused(fn, *args, **kwargs):
            try:
                fn(*args, **kwargs)
            except Error:
                return
            raise AssertionError("stale/unissued result admitted")
        check = execution._require_live_issued_multi_source_cross_day_dataset_result
        if mode == "fork":
            refused(check, parent)
            inputs = fixture(root)
            fresh = execution.join_multi_source_cross_day_dataset(**inputs)
            check(fresh)
        elif mode == "spawn":
            inputs = fixture(root)
            # Reconstruct full same-content graph with logical helpers only, never enrollment.
            admitted = execution.admit_inputs(**inputs)
            split = execution._validated_split(admitted, execution.assign_chronological_splits(
                execution._split_samples(admitted), admitted.split_spec))
            declaration = execution._declaration(admitted, split, execution._project(admitted, split))
            clone = object.__new__(Result)
            for field in fields(Result):
                v = declaration if field.name == "identity_input" else dataset_id if field.name == "dataset_id" else (
                    "COMPLETE" if field.name == "status" else getattr(declaration, field.name))
                object.__setattr__(clone, field.name, v)
            assert multi_source_cross_day_dataset_id(declaration) == dataset_id
            refused(check, clone)
        else:
            inputs = fixture(root)
            old_join, old_verify = execution.join_multi_source_cross_day_dataset, check
            old_result = old_join(**inputs)
            importlib.reload(execution)
            refused(old_verify, old_result)
            refused(execution._require_live_issued_multi_source_cross_day_dataset_result, old_result)
            refused(old_join, **inputs)
            fresh = execution.join_multi_source_cross_day_dataset(**inputs)
            execution._require_live_issued_multi_source_cross_day_dataset_result(fresh)
        connection.send("PASS")
    except BaseException as exc:
        connection.send((type(exc).__name__, str(exc)))
    finally:
        connection.close()


@pytest.mark.parametrize("mode", ["reload", "spawn", "fork"])
def test_process_and_reload_hard_gates(tmp_path, mode):
    if mode == "fork" and "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("actual fork qualification runs on Linux")
    inputs = fixture(tmp_path / "parent")
    parent = engine.join_multi_source_cross_day_dataset(**inputs)
    ctx = multiprocessing.get_context("fork" if mode == "fork" else "spawn")
    receiving, sending = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_process_worker,
        args=(sending, mode, tmp_path / "child", parent if mode == "fork" else None, parent.dataset_id))
    process.start()
    sending.close()
    try:
        assert receiving.poll(90), "child proof test timed out"
        assert receiving.recv() == "PASS"
    finally:
        process.join(90)
        if process.is_alive():
            process.terminate()
            process.join()
        receiving.close()
    assert process.exitcode == 0
    assert verify(parent) is None


def test_process_mismatch_fails_before_inherited_lock(issued, monkeypatch):
    _, result = issued
    pid = os.getpid()
    monkeypatch.setattr(engine.os, "getpid", lambda: pid + 1)
    reject(result)
    with pytest.raises(Error, match="stale process"):
        engine.join_multi_source_cross_day_dataset(**issued[0])


def test_snapshotter_rejects_unknown_types_without_user_equality_hash_or_copy(issued):
    _, result = issued
    class Unknown:
        def __eq__(self, other):
            raise AssertionError("caller equality")
        def __hash__(self):
            raise AssertionError("caller hash")
        def __deepcopy__(self, memo):
            raise AssertionError("caller copy")
    object.__setattr__(result, "rows", (Unknown(),))
    reject(result)


def test_source_boundary_has_no_issuance_metadata_or_artifact_api():
    assert not any("issu" in name or "token" in name or "ledger" in name for name in package.__all__)
    source = inspect.getsource(snapshots)
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in ("deepcopy", "dumps", "loads", "asdict", "now", "getenv")
                   for node in ast.walk(tree))
    # L3.3 may consume the private bridge; snapshot authority must not import I/O.
    assert not any(isinstance(node, ast.ImportFrom) and any(word in (node.module or "")
        for word in ("artifact", "materialization", "manifest", "reader")) for node in ast.walk(tree))


def test_genuine_signed_zero_mutation_is_rejected(tmp_path, monkeypatch):
    import cross_day_helpers as cd
    real_bar = cd.bar
    def zero_return_bar(*args, **kwargs):
        return real_bar(*args, **(kwargs | {"close": 100.0}))
    monkeypatch.setattr(cd, "bar", zero_return_bar)
    result = engine.join_multi_source_cross_day_dataset(**fixture(tmp_path))
    value = result.ts2_features.samples[0].values[0]
    assert value.value == 0.0
    assert verify(result) is None
    object.__setattr__(value, "value", -0.0)
    reject(result)


def test_bookkeeping_and_verifier_do_no_io_or_upstream_execution(issued, monkeypatch, record_property):
    import market_vault.cross_day.assembly as label_assembly
    import market_vault.cross_day.execution as label_execution
    import market_vault.ts2_feature.execution as ts2_execution
    import market_vault.multi_source.feature_execution as observation_execution
    import market_vault.observation.pit as a3
    import market_vault.dataset.pit as pit
    from market_vault.ts2_feature import registry as ts2_registry
    from market_vault.cross_day import registry as label_registry
    import sys
    inputs, result = issued
    contracts = ts2_registry._CONTRACTS + label_registry._contracts()
    modules = tuple(sys.modules[c.implementation.__module__] for c in contracts)
    sources = {m: inspect.getsource(m) for m in modules}
    acquisitions = []
    def source(module):
        assert module in sources
        acquisitions.append(module)
        return sources[module]
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected I/O, clock, environment or upstream execution")
    with monkeypatch.context() as patch:
        patch.setattr(inspect, "getsource", source)
        for module, names in (
            (label_assembly, ("_facts", "assemble_cross_day_labels")),
            (label_execution, ("execute_cross_day_labels", "validate_cross_day_execution_result")),
            (ts2_execution, ("execute_ts2_features", "_invoke", "_plans")),
            (observation_execution, ("execute_observation_features",)),
            (a3, ("assemble_observation_pit_sidecar", "_decision", "_assemble", "_verify_result")),
            (pit, ("assemble_point_in_time_samples",)),
        ):
            for name in names:
                patch.setattr(module, name, forbidden)
        patch.setattr(label_assembly.CrossDayLabelAssemblyResult, "__post_init__", forbidden)
        patch.setattr(label_execution.CrossDayLabelExecutionResult, "__post_init__", forbidden)
        for module, names in (
            (builtins, ("open",)), (io, ("open",)), (Path, ("open",)),
            (os, ("open", "stat", "scandir", "listdir", "mkdir", "remove", "unlink", "rename",
                  "replace", "getcwd", "getenv")),
            (socket, ("socket", "create_connection")),
            (time, ("time", "time_ns")),
        ):
            for name in names:
                patch.setattr(module, name, forbidden)
        fresh = engine.join_multi_source_cross_day_dataset(**inputs)
        patch.setattr(engine, "assign_chronological_splits", forbidden)
        assert verify(result) is None
        assert verify(fresh) is None
        reject(tamper(result))
    assert len(acquisitions) == 36
    assert set(acquisitions) == set(modules)
    record_property("OWN_FILESYSTEM_READ_COUNT", 0)
    record_property("OWN_FILESYSTEM_WRITE_COUNT", 0)
    record_property("INHERITED_STATIC_SOURCE_ACQUISITIONS", 36)


def test_reference_graph_covers_descriptive_non_identity_facts(issued):
    _, result = issued
    build = result.identity_input.canonical_builds[0]
    object.__setattr__(build, "build_path", Path("different-descriptive-path"))
    # The existing logical identity deliberately ignores location.
    assert multi_source_cross_day_dataset_id(result.identity_input) == result.dataset_id
    reject(result)


def test_nested_mapping_replacement_and_in_place_content_are_rejected(issued):
    _, result = issued
    split = result.split_result
    original = split.assignment_rows[0]
    mutable = dict(original)
    object.__setattr__(split, "assignment_rows", (MappingProxyType(mutable),) + split.assignment_rows[1:])
    reject(result)
    baseline = snapshots._capture(result)
    mutable["new_untrusted_field"] = True
    with pytest.raises(Error, match="RESULT_AUTHORITY"):
        snapshots._same_capture(result, *baseline)


def test_verifier_never_rebaselines_after_mutation(issued):
    _, result = issued
    state = closure_state()
    record = state["ledger"][id(result)]
    object.__setattr__(result.ts2_features.samples[0].values[0], "value", 999.0)
    reject(result)
    reject(result)
    assert state["ledger"][id(result)] is record


def test_equal_content_alias_edge_substitution_is_detected(issued):
    _, result = issued
    first = result.schema.fields[0]
    twin = tamper(first)
    assert twin == first and twin is not first
    entries = {"first": first, "twin": twin, "again": first}
    # A closed snapshot unit probe: both equal nodes remain independently reachable.
    object.__setattr__(result, "rows", ((MappingProxyType(entries),),))
    baseline = snapshots._capture(result)
    entries["again"] = twin
    with pytest.raises(Error, match="reference graph"):
        snapshots._same_capture(result, *baseline)
