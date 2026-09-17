"""Closed registry, private issuance, independence and strict I/O canaries."""

import ast
import builtins
from dataclasses import asdict, FrozenInstanceError, replace
from datetime import datetime, timezone
import inspect
import io
import _io
import linecache
import os
from pathlib import Path
import socket
import sys
import time
import tokenize

import pytest

from ts2_feature_helpers import AS_OF, fixture, execute, pit, spec, tamper
from test_ts2_feature_execution import fails
from market_vault.ts2_feature import (
    TS2FeatureError, TS2FeatureExecutionResult, TS2FeatureSampleResult, TS2FeatureValueResult,
    execute_ts2_features,
)
from market_vault.ts2_feature import registry, execution as engine
from market_vault.dataset.models import ImplementationPin
from market_vault.dataset.encoding import encode_identity


def test_fixed_registry_is_eight_immutable_static_functions():
    entries = registry._registry()
    assert len(entries) == 8
    assert tuple(r.contract.name for r in entries) == (
        "candle_body", "candle_range", "log_return", "rolling_mean", "rolling_std",
        "rolling_volume_mean", "simple_return", "volume_ratio")
    for entry in entries:
        assert entry.contract.implementation is getattr(sys.modules[entry.contract.implementation.__module__], entry.contract.name)
        with pytest.raises(FrozenInstanceError):
            entry.pin = None
    with pytest.raises(TypeError):
        execute_ts2_features((), None, (), dataset_as_of=None, registry=entries)


def test_source_failure_and_wrong_module_binding(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    empty = pit((one,), requests=())
    def unavailable(*a):
        raise OSError("unavailable source")
    with monkeypatch.context() as patch:
        patch.setattr(inspect, "getsource", unavailable)
        fails("SOURCE_FINGERPRINT", lambda: execute(one, empty, ()))
    contract = registry._CONTRACTS[0]
    monkeypatch.setattr(sys.modules[contract.implementation.__module__], contract.name, lambda x: 1.0)
    fails("REGISTRY_AUTHORITY", lambda: execute(one, selected))


def test_source_normalization_and_real_content_change(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    empty = pit((one,), requests=())
    baseline = execute(one, selected)
    baseline_empty = execute(one, empty, ())
    real = inspect.getsource
    with monkeypatch.context() as patch:
        patch.setattr(inspect, "getsource", lambda module: "\r\n\r\n" + real(module).replace("\n", "\r\n") + "\r\n")
        assert execute(one, selected) == baseline
    with monkeypatch.context() as patch:
        patch.setattr(inspect, "getsource", lambda module: real(module) + "\n# changed implementation source\n")
        changed = execute(one, selected)
        changed_empty = execute(one, empty, ())
    assert changed.registry_implementation_pins != baseline.registry_implementation_pins
    assert changed.samples[0].values[0].value == baseline.samples[0].values[0].value
    assert changed.values_content_id != baseline.values_content_id
    assert changed_empty.execution_id != baseline_empty.execution_id


def test_source_path_mtime_cwd_are_not_identity(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    expected = execute(one, selected)
    sources = {c.implementation.__module__: inspect.getsource(sys.modules[c.implementation.__module__]) for c in registry._CONTRACTS}
    monkeypatch.chdir(tmp_path)
    for name in sources:
        monkeypatch.setattr(sys.modules[name], "__file__", str(tmp_path / "relocated.py"))
    monkeypatch.setattr(inspect, "getsource", lambda module: sources[module.__name__])
    assert execute(one, selected) == expected


def test_coordinated_forgery_and_direct_construction(tmp_path):
    one, selected = fixture(tmp_path)
    result = execute(one, selected)
    value = result.samples[0].values[0]
    contract = next(c for c in registry._CONTRACTS if c.transform_ref == value.implementation_pin.name)
    fake_hash = "9" * 64
    fake_fingerprint = encode_identity("ts2-feature-implementation-v1", registry.implementation_payload(contract, fake_hash))
    fake_pin = ImplementationPin(contract.transform_ref, "v1", fake_fingerprint)
    assert fake_pin != value.implementation_pin
    for record in (result, result.samples[0], value):
        fails("RESULT_AUTHORITY", lambda: type(record)(**asdict(record)))
        fails("RESULT_AUTHORITY", lambda: replace(record))
    fails("RESULT_AUTHORITY", lambda: replace(value, implementation_pin=fake_pin))
    fails("RESULT_AUTHORITY", lambda: replace(result, registry_implementation_pins=(fake_pin,)))
    fake_value = {**asdict(value), "implementation_pin": fake_pin}
    fake_sample = {**asdict(result.samples[0]), "values": (fake_value,)}
    forged = {**asdict(result), "samples": (fake_sample,), "registry_implementation_pins": (fake_pin,)}
    fails("RESULT_AUTHORITY", lambda: TS2FeatureExecutionResult(**forged))
    for cls in (TS2FeatureValueResult, TS2FeatureSampleResult, TS2FeatureExecutionResult):
        fails("RESULT_AUTHORITY", lambda: cls(skip_validation=True, source_hash=fake_hash, issuance_token=object()))


def test_deep_immutability_and_caller_aliases(tmp_path):
    one, selected = fixture(tmp_path)
    chosen = spec()
    result = execute(one, selected, (chosen,))
    identity = result.execution_id
    for obj, attribute in ((result, "status"), (result.samples[0], "status"),
                           (result.samples[0].values[0], "value"), (result.feature_specs[0], "name"),
                           (result.registry_implementation_pins[0], "name")):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attribute, None)
    with pytest.raises(TypeError):
        result.samples[0].values[0] = None
    object.__setattr__(chosen, "name", "caller_mutated")
    selected.association_rows[0]["sample_key"] = "0" * 64
    assert result.execution_id == identity


def test_old_layers_and_pit_selection_never_invoked(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    import market_vault.dataset.feature_registry as old_registry
    import market_vault.dataset.feature_execution as old_execution
    import market_vault.dataset.label_registry as old_labels
    import market_vault.dataset.label_execution as old_label_execution
    import market_vault.dataset.pit as old_pit
    def forbidden(*a, **kw):
        pytest.fail("sealed executor/registry/PIT selection invoked")
    for module in (old_registry, old_execution, old_labels, old_label_execution):
        for name, value in vars(module).copy().items():
            if inspect.isfunction(value) and (name.startswith("built_in_") or name.startswith("execute_")):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(old_pit, "assemble_point_in_time_samples", forbidden)
    assert execute(one, selected).status == "COMPLETE"


def test_relocation_is_in_memory_only(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    expected = execute(one, selected)
    relocated = replace(one, build_path=tmp_path / "does-not-exist")
    import market_vault.canonical.reader as reader
    monkeypatch.setattr(reader, "load_verified_canonical_build", lambda *a: pytest.fail("artifact reopened"))
    assert execute(relocated, selected) == expected


def test_only_eight_static_source_reads_no_other_io(tmp_path, monkeypatch):
    one, selected = fixture(tmp_path)
    real_source = inspect.getsource
    allowed = {c.implementation.__module__: sys.modules[c.implementation.__module__].__file__ for c in registry._CONTRACTS}
    paths = {os.path.normcase(os.path.abspath(p)) for p in allowed.values()}
    for p in allowed.values():
        linecache.cache.pop(p, None)
    active = []
    acquisitions, reads, violations = [], [], []
    def source(module):
        assert module.__name__ in allowed
        acquisitions.append(module.__name__)
        active.append(allowed[module.__name__])
        try:
            return real_source(module)
        finally:
            active.pop()
    def guarded(fn, operation, mode_index=None):
        def call(path, *args, **kwargs):
            normalized = os.path.normcase(os.path.abspath(os.fspath(path)))
            mode = kwargs.get("mode", args[mode_index] if mode_index is not None and len(args) > mode_index else "r")
            if not active or normalized not in paths or (isinstance(mode, str) and any(c in mode for c in "wax+")):
                violations.append((operation, str(path)))
                raise AssertionError("unauthorized filesystem access")
            if operation in ("open", "io.open", "open_code"):
                reads.append(normalized)
            return fn(path, *args, **kwargs)
        return call
    def forbidden(*a, **kw):
        violations.append(("forbidden", str(a[:1])))
        raise AssertionError("unexpected I/O or temporal authority")
    with monkeypatch.context() as patch:
        patch.setattr(inspect, "getsource", source)
        patch.setattr(builtins, "open", guarded(builtins.open, "open", 0))
        patch.setattr(io, "open", guarded(io.open, "io.open", 0))
        patch.setattr(_io, "open_code", guarded(_io.open_code, "open_code"))
        patch.setattr(tokenize, "_builtin_open", guarded(tokenize._builtin_open, "open", 0))
        patch.setattr(os, "stat", guarded(os.stat, "stat"))
        for name in ("open", "scandir", "listdir", "mkdir", "remove", "unlink", "rename", "replace"):
            patch.setattr(os, name, forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(os, "getenv", forbidden)
        patch.setattr(os, "getcwd", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "time_ns", forbidden)
        class NoClock(datetime):
            now = utcnow = today = classmethod(forbidden)
        patch.setattr(engine, "datetime", NoClock)
        result = execute(one, selected)
    assert result.status == "COMPLETE"
    assert sorted(acquisitions) == sorted(allowed)
    assert set(reads) == paths
    assert violations == []


def test_schedule_label_and_a3_independence(tmp_path, artifacts):
    from cross_day_helpers import schedule, spec as label_spec, bar, build
    from test_cross_day_execution import a3_sidecar
    from market_vault.cross_day import assemble_cross_day_labels, execute_cross_day_labels
    one, selected = fixture(tmp_path)
    first = execute(one, selected)
    upstream = a3_sidecar(selected, artifacts)
    a3_id = upstream.sample_bindings[0].multi_source_sample_version_id
    labels = build(tmp_path / "labels", (bar("2025-03-04", close=125.0),))
    changed_labels = build(tmp_path / "changed-labels", (bar("2025-03-04", close=150.0),))
    results = []
    for sched, label_build in ((schedule(), labels), (replace(schedule(), source_content_hash="0" * 64), labels),
                               (schedule(), changed_labels)):
        association = assemble_cross_day_labels(selected, (one,), (label_build,), sched, (label_spec(),),
                                               dataset_as_of=AS_OF, observation_pit=upstream)
        results.append(execute_cross_day_labels(association))
        assert execute(one, selected).execution_id == first.execution_id
    assert results[0].values_content_id != results[1].values_content_id
    assert results[0].values[0].value != results[2].values[0].value
    assert upstream.sample_bindings[0].multi_source_sample_version_id == a3_id
    assert all(r.sample_bindings[0].multi_source_sample_version_id == a3_id for r in results)
    def later_proof(rows, **kwargs):
        return artifacts(rows, **(kwargs | {"created": kwargs["created"] + 1}))
    changed_observation = a3_sidecar(selected, later_proof)
    assert execute(one, selected) == first
    assert changed_observation.sample_bindings[0].sample_key == upstream.sample_bindings[0].sample_key
    assert changed_observation.sample_bindings[0].multi_source_sample_version_id != a3_id


from test_observation_pit_models import artifacts


def test_no_dataset_or_provider_exports_and_no_temporal_authority():
    import market_vault.ts2_feature as package
    public = set(package.__all__)
    assert public == {
        "execute_ts2_features", "TS2FeatureError", "TS2FeatureValueResult", "TS2FeatureSampleResult", "TS2FeatureExecutionResult",
        "TS2_FEATURE_REGISTRY_CONTRACT_VERSION", "TS2_FEATURE_EXECUTION_CONTRACT_VERSION",
        "TS2_FEATURE_TRANSFORM_CALL_CONTRACT_VERSION", "TS2_FEATURE_IMPLEMENTATION_FINGERPRINT_VERSION"}
    assert set(inspect.signature(execute_ts2_features).parameters) == {"builds", "pit_result", "feature_specs", "dataset_as_of"}
    forbidden_names = {"open", "read_text", "read_bytes", "now", "utcnow", "getenv", "scandir", "listdir", "mkdir", "unlink", "rmtree"}
    for path in Path(package.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
                assert name not in forbidden_names, (path.name, name)
