"""No successful production authority resolution is possible with empty registries."""

import ast
import inspect
from types import MappingProxyType

import pytest

from market_vault import schedule_artifact
from market_vault.schedule_artifact import _trust
from market_vault.schedule_artifact._errors import _ScheduleArtifactError
from test_schedule_artifact_schema import _bundle, _validate


@pytest.mark.parametrize("registry", [
    _trust._QUALIFIED_SOURCE_PROFILES, _trust._QUALIFIED_CUSTODY_KEYS, _trust._QUALIFIED_VERIFIER_KEYS,
])
def test_reader_owned_registries_are_empty_immutable_without_registration(registry):
    assert type(registry) is MappingProxyType and len(registry) == 0
    assert not hasattr(registry, "add") and not hasattr(registry, "register")
    with pytest.raises(TypeError):
        registry[("UNQUALIFIED",)] = bytes(32)


@pytest.mark.parametrize("resolver,args,reason", [
    (_trust._resolve_source_profile, ("provider", "source", "contract", "v1", "v1", "v1"),
     "SOURCE_CONTRACT_UNQUALIFIED"),
    (_trust._resolve_custody_key, ("authority", "key"), "EVIDENCE_AUTHORITY_UNQUALIFIED"),
    (_trust._resolve_verifier_key, ("authority", "v1", "key"), "EVIDENCE_AUTHORITY_UNQUALIFIED"),
])
def test_production_resolution_remains_fail_closed_after_structural_success(resolver, args, reason):
    assert _validate(_bundle(), reseal=True).schedule_artifact_id
    with pytest.raises(_ScheduleArtifactError) as caught:
        resolver(*args)
    assert caught.value.reason_code == reason
    with pytest.raises(_ScheduleArtifactError) as malformed:
        resolver([], *args[1:])
    assert malformed.value.reason_code == reason
    with pytest.raises(TypeError):
        resolver(*args, trusted=True)
    with pytest.raises(TypeError):
        resolver(*args, public_key=bytes(32))


def test_no_registration_environment_settings_or_qualification_backdoor():
    tree = ast.parse(inspect.getsource(_trust))
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {
        "_resolve_source_profile", "_resolve_custody_key", "_resolve_verifier_key",
    }
    assert not any(isinstance(node, (ast.Import, ast.AsyncFunctionDef)) for node in ast.walk(tree))
    assert {(node.level, node.module) for node in tree.body if isinstance(node, ast.ImportFrom)} == {
        (0, "types"), (1, "_errors"),
    }
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (identifiers | attributes) & {
        "add", "register", "environ", "getenv", "settings", "config", "open", "Path",
        "requests", "os", "trusted", "override", "monkeypatch",
    }
    assert schedule_artifact.__all__ == ()


def test_only_frozen_semantic_error_vocabulary_can_be_reported():
    with pytest.raises(ValueError, match="unsupported pure"):
        _ScheduleArtifactError("CLEANUP_REFUSED", "not a pure semantic reason")
