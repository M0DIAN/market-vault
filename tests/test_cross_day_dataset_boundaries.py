"""No-reexecution, fixed authority, phase locks and inherited I/O boundaries."""

import ast
import builtins
import _io
import inspect
import io
import linecache
import os
from pathlib import Path
import socket
import sys
import time
import tokenize
from dataclasses import replace

import pytest

from cross_day_dataset_helpers import fixture, tamper
from market_vault.cross_day_dataset import join_multi_source_cross_day_dataset, MultiSourceCrossDayDatasetError
from market_vault.dataset.encoding import encode_identity
from market_vault.dataset.models import ImplementationPin
from market_vault.ts2_feature import registry as ts2_registry
from market_vault.ts2_feature.identity import implementation_pin_id
from market_vault.cross_day import registry as label_registry


def test_no_upstream_execution_and_only_bounded_registry_io(tmp_path, monkeypatch, record_property):
    import market_vault.cross_day.assembly as label_assembly
    import market_vault.cross_day.execution as label_execution
    import market_vault.ts2_feature.execution as ts2_execution
    import market_vault.multi_source.feature_execution as observation_execution
    import market_vault.observation.pit as a3_assembly
    import market_vault.dataset.pit as pit_assembly
    import market_vault.dataset.feature_execution as old_features
    import market_vault.dataset.label_execution as old_labels
    import market_vault.dataset.feature_registry as old_registry
    import market_vault.cross_day_dataset.execution as join_engine
    data = fixture(tmp_path)
    contracts = ts2_registry._CONTRACTS + label_registry._contracts()
    targets = {c.implementation.__module__: sys.modules[c.implementation.__module__].__file__ for c in contracts}
    paths = {os.path.normcase(os.path.abspath(p)) for p in targets.values()}
    for path in targets.values():
        linecache.cache.pop(path, None)
    acquisitions, reads, violations, calls = [], [], [], []
    active = []
    real_source = inspect.getsource
    def source(module):
        assert module.__name__ in targets
        acquisitions.append(module.__name__)
        active.append(targets[module.__name__])
        try:
            return real_source(module)
        finally:
            active.pop()
    def guard(fn, operation):
        def run(path, *args, **kwargs):
            mode = kwargs.get("mode", args[0] if args else "r")
            normalized = os.path.normcase(os.fspath(path))
            if not active or normalized not in paths or (type(mode) is str and any(c in mode for c in "wax+")):
                violations.append(operation)
                raise AssertionError("unauthorized filesystem access")
            if "open" in operation:
                reads.append(normalized)
            return fn(path, *args, **kwargs)
        return run
    def forbidden(*args, **kwargs):
        raise AssertionError("upstream selection/execution or unauthorized I/O")
    real_split = join_engine.assign_chronological_splits
    def split(*args, **kwargs):
        calls.append("split")
        return real_split(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(join_engine, "assign_chronological_splits", split)
        for module, names in ((label_assembly, ("_facts", "assemble_cross_day_labels")),
                              (label_execution, ("execute_cross_day_labels", "validate_cross_day_execution_result")),
                              (ts2_execution, ("execute_ts2_features", "_invoke", "_plans")),
                              (observation_execution, ("execute_observation_features",)),
                              (a3_assembly, ("assemble_observation_pit_sidecar", "_decision", "_assemble", "_verify_result")),
                              (pit_assembly, ("assemble_point_in_time_samples",)),
                              (old_features, ("execute_builtin_features",)), (old_labels, ("execute_builtin_labels",)),
                              (old_registry, ("built_in_feature_registrations",))):
            for name in names:
                patch.setattr(module, name, forbidden)
        patch.setattr(label_assembly.CrossDayLabelAssemblyResult, "__post_init__", forbidden)
        patch.setattr(label_execution.CrossDayLabelExecutionResult, "__post_init__", forbidden)
        patch.setattr(inspect, "getsource", source)
        patch.setattr(builtins, "open", guard(builtins.open, "open"))
        patch.setattr(io, "open", guard(io.open, "io.open"))
        patch.setattr(_io, "open_code", guard(_io.open_code, "open_code"))
        patch.setattr(tokenize, "_builtin_open", guard(tokenize._builtin_open, "tokenize.open"))
        patch.setattr(os, "stat", guard(os.stat, "stat"))
        for name in ("open", "scandir", "listdir", "mkdir", "remove", "unlink", "rename", "replace", "getcwd", "getenv"):
            patch.setattr(os, name, forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(time, "time", forbidden)
        patch.setattr(time, "time_ns", forbidden)
        result = join_multi_source_cross_day_dataset(**data)
    assert result.rows and calls == ["split"]
    assert sorted(acquisitions) == sorted(targets)
    assert len(acquisitions) == 12 and set(reads) == paths and violations == []
    record_property("OWN_FILESYSTEM_READ_COUNT", 0)
    record_property("OWN_FILESYSTEM_WRITE_COUNT", 0)
    record_property("UNAUTHORIZED_FILESYSTEM_ACCESS_COUNT", 0)
    record_property("INHERITED_STATIC_SOURCE_ACQUISITIONS", len(acquisitions))


def test_coordinated_ts2_source_fingerprint_pin_forgery_rejected(tmp_path):
    inputs = fixture(tmp_path)
    result = inputs["ts2_features"]
    sample = result.samples[0]
    value = sample.values[0]
    contract = next(c for c in ts2_registry._CONTRACTS if c.transform_ref == value.implementation_pin.name)
    fingerprint = encode_identity("ts2-feature-implementation-v1", ts2_registry.implementation_payload(contract, "0" * 64))
    fake_pin = ImplementationPin(contract.transform_ref, "v1", fingerprint)
    pins = tuple(sorted((fake_pin if p.name == fake_pin.name else p for p in result.registry_implementation_pins),
                        key=implementation_pin_id))
    forged = tamper(result, registry_implementation_pins=pins,
                    samples=(tamper(sample, values=(tamper(value, implementation_pin=fake_pin),)),))
    assert forged.execution_id != result.execution_id
    with pytest.raises(MultiSourceCrossDayDatasetError, match="IMPLEMENTATION_BINDING"):
        join_multi_source_cross_day_dataset(**(inputs | dict(ts2_features=forged)))


@pytest.mark.parametrize("case", ["A", "E"])
def test_source_fingerprint_failure_fails_closed(tmp_path, monkeypatch, case):
    inputs = fixture(tmp_path, case)
    def unavailable(*args):
        raise OSError("offline source unavailable")
    monkeypatch.setattr(inspect, "getsource", unavailable)
    with pytest.raises(MultiSourceCrossDayDatasetError, match="IMPLEMENTATION_BINDING"):
        join_multi_source_cross_day_dataset(**inputs)


def test_actual_new_label_implementation_pin_changes_dataset_identity(tmp_path, monkeypatch):
    from market_vault.cross_day import execute_cross_day_labels
    inputs = fixture(tmp_path)
    original = join_multi_source_cross_day_dataset(**inputs)
    real = inspect.getsource
    def changed(module):
        text = real(module)
        return text + "\n# implementation source revision\n" if module.__name__.endswith("label_transforms.forward_return") else text
    monkeypatch.setattr(inspect, "getsource", changed)
    labels = execute_cross_day_labels(inputs["cross_day_association"])
    assert labels.implementation_pins != original.cross_day_labels.implementation_pins
    current = join_multi_source_cross_day_dataset(**(inputs | dict(cross_day_labels=labels)))
    assert current.dataset_id != original.dataset_id
    with pytest.raises(MultiSourceCrossDayDatasetError, match="IMPLEMENTATION_BINDING"):
        join_multi_source_cross_day_dataset(**inputs)


def test_coordinated_l2_source_fingerprint_pin_forgery_rejected(tmp_path):
    inputs = fixture(tmp_path)
    labels = inputs["cross_day_labels"]
    value, = labels.values
    contract = next(c for c in label_registry._contracts() if c.transform_ref == value.implementation_pin.name)
    fake_hash = "0" * 64
    fingerprint = encode_identity("cross-day-label-implementation-v1", label_registry.implementation_payload(
        contract.transform_ref, fake_hash, contract.input_fields, contract.output_logical_type, contract.offset_shape))
    pin = ImplementationPin(contract.transform_ref, "v1", fingerprint)
    forged = tamper(labels, implementation_pins=(pin,), implementation_source_hashes=((contract.transform_ref, fake_hash),),
                    values=(tamper(value, implementation_pin=pin),))
    assert forged.values_content_id != labels.values_content_id
    with pytest.raises(MultiSourceCrossDayDatasetError, match="IMPLEMENTATION_BINDING"):
        join_multi_source_cross_day_dataset(**(inputs | dict(cross_day_labels=forged)))


def test_package_is_pure_additive_and_has_no_future_api():
    """Preserve historical canary node ID; sealed logical modules remain I/O-free."""
    import market_vault.cross_day_dataset as package
    root = Path(package.__file__).parent
    forbidden = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "stat", "getcwd", "getenv",
        "glob", "iterdir", "listdir", "scandir", "now", "utcnow", "today", "rename", "rmtree",
        "assemble_point_in_time_samples", "assemble_observation_pit_sidecar", "execute_ts2_features",
        "execute_observation_features", "assemble_cross_day_labels", "execute_cross_day_labels", "_facts"}
    # The authorized L3.3 phase adds artifact modules; the sealed pure modules
    # must still have no I/O or dependency back to that physical boundary.
    logical_modules = ("models", "identity", "closure", "execution", "_live_issuance", "_validation",
                       "_label_closure", "_observation_closure", "_ts2_closure", "generator")
    for module in logical_modules:
        path = root / (module + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                assert name not in forbidden, (path.name, name)
            if isinstance(node, ast.ImportFrom):
                assert not any(word in (node.module or "") for word in ("artifact", "materialization", "manifest", "reader")) or node.level > 1
    assert {"CrossDayAnchor", "generate_cross_day_feature_requests",
            "MULTI_SOURCE_CROSS_DAY_SAMPLE_GENERATOR_VERSION"} <= set(package.__all__)
    assert not any(any(word in name.lower() for word in ("catalog", "provider"))
                   for name in package.__all__)
