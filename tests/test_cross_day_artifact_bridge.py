"""The private artifact bridge returns issuance-time values, never caller facts."""

from dataclasses import FrozenInstanceError, fields, is_dataclass
import importlib
import multiprocessing
import pickle

import pytest

from cross_day_dataset_helpers import fixture, tamper
from market_vault.cross_day_dataset import execution
from market_vault.cross_day_dataset._validation import MultiSourceCrossDayDatasetError
from test_cross_day_live_issuance_runtime import forged_result


@pytest.fixture
def issued(tmp_path):
    inputs = fixture(tmp_path)
    return inputs, execution.join_multi_source_cross_day_dataset(**inputs)


def bridge(result):
    return execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts(result)


def test_bridge_returns_immutable_issuance_snapshot(issued):
    _, result = issued
    first, second = bridge(result), bridge(result)
    assert first.dataset_id == result.dataset_id
    assert first.snapshot is second.snapshot
    assert first.generation is second.generation
    assert first.epoch is second.epoch
    with pytest.raises(FrozenInstanceError):
        first.dataset_id = "0" * 64
    with pytest.raises(TypeError, match="process-private"):
        pickle.dumps(first)


def test_bridge_graph_has_no_result_or_caller_mutable_references(issued):
    _, result = issued
    facts = bridge(result)
    reference_ids = {id(v) for v in execution._live._capture(result)[1]}

    def check(value):
        assert value is not result
        assert not isinstance(value, (list, dict, set, bytearray))
        if type(value) is tuple:
            assert id(value) not in reference_ids or value == ()
            for item in value:
                check(item)
        elif is_dataclass(value):
            for field in fields(value):
                check(getattr(value, field.name))

    check(facts)


@pytest.mark.parametrize("kind", ["clone", "forged", "working_facts", "mutated"])
def test_bridge_does_not_admit_unissued_or_changed_objects(issued, kind):
    inputs, result = issued
    if kind == "clone":
        result = tamper(result)
    elif kind == "forged":
        result = forged_result(inputs, result)
    elif kind == "working_facts":
        result = bridge(result)
    else:
        object.__setattr__(result.ts2_features.samples[0].values[0], "value", 999.0)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="RESULT_AUTHORITY"):
        bridge(result)


def test_post_bridge_mutation_does_not_change_detached_facts(issued):
    _, result = issued
    facts = bridge(result)
    snapshot = facts.snapshot
    object.__setattr__(result.ts2_features.samples[0].values[0], "value", 999.0)
    assert facts.snapshot is snapshot
    assert ("float64", b"?\xd0\x00\x00\x00\x00\x00\x00") in _nodes(snapshot)
    assert ("float64", b"@\x8f8\x00\x00\x00\x00\x00") not in _nodes(snapshot)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="RESULT_AUTHORITY"):
        bridge(result)


def _nodes(value):
    if type(value) is tuple:
        yield value
        for item in value:
            yield from _nodes(item)


def test_bridge_never_enrolls_refreshes_or_rebaselines(issued):
    from test_cross_day_live_issuance_runtime import closure_state

    _, result = issued
    ledger = closure_state()["ledger"]
    original = ledger[id(result)]
    assert bridge(result).snapshot is original.snapshot
    assert ledger[id(result)] is original
    with pytest.raises(MultiSourceCrossDayDatasetError):
        bridge(tamper(result))
    assert ledger[id(result)] is original


def test_bridge_does_not_add_public_api():
    import market_vault.cross_day_dataset as package

    assert not hasattr(package, "_require_live_issued_multi_source_cross_day_dataset_artifact_facts")
    assert not any("artifact_facts" in name for name in package.__all__)


@pytest.mark.parametrize("case", ["A", "E"])
def test_bridge_complete_and_empty(tmp_path, case):
    inputs = fixture(tmp_path, case)
    result = execution.join_multi_source_cross_day_dataset(**inputs)
    facts = bridge(result)
    assert facts.dataset_id == result.dataset_id
    assert facts.status == ("EMPTY" if case == "E" else "COMPLETE")


def _bridge_process_worker(connection, mode, root, parent=None, saved_bridge=None):
    try:
        def refused(fn, value):
            try:
                fn(value)
            except MultiSourceCrossDayDatasetError:
                return
            raise AssertionError("stale/unissued bridge authority admitted")

        if mode == "fork":
            refused(saved_bridge, parent)
            refused(bridge, parent)
        inputs = fixture(root)
        result = execution.join_multi_source_cross_day_dataset(**inputs)
        if mode == "reload":
            old_bridge = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts
            old_facts = old_bridge(result)
            importlib.reload(execution)
            refused(old_bridge, result)
            refused(bridge, result)
            refused(bridge, old_facts)
            result = execution.join_multi_source_cross_day_dataset(**inputs)
        elif mode == "spawn":
            refused(bridge, tamper(result))
        assert bridge(result).dataset_id == result.dataset_id
        connection.send("PASS")
    except BaseException as exc:
        connection.send((type(exc).__name__, str(exc)))
    finally:
        connection.close()


@pytest.mark.parametrize("mode", ["reload", "spawn", "fork"])
def test_bridge_process_and_generation_invalidation(tmp_path, mode):
    if mode == "fork" and "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("native fork evidence requires Linux")
    parent = execution.join_multi_source_cross_day_dataset(**fixture(tmp_path / "parent"))
    saved = execution._require_live_issued_multi_source_cross_day_dataset_artifact_facts
    ctx = multiprocessing.get_context("fork" if mode == "fork" else "spawn")
    receiving, sending = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_bridge_process_worker, args=(
        sending, mode, tmp_path / "child", parent if mode == "fork" else None,
        saved if mode == "fork" else None))
    child.start()
    sending.close()
    try:
        assert receiving.poll(90), "bridge child test timed out"
        assert receiving.recv() == "PASS"
    finally:
        child.join(90)
        if child.is_alive():
            child.terminate()
            child.join()
        receiving.close()
    assert child.exitcode == 0
    assert bridge(parent).dataset_id == parent.dataset_id
