"""Pure in-memory Dataset Catalog selection and client-boundary tests.

The forged verified objects in this module exist only to isolate defensive
selector branches. They are deliberately not a supported artifact trust
path; production verified objects remain the reader's responsibility.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import socket
import time
from pathlib import Path

import pytest

import market_vault
from market_vault import ArtifactClient
from market_vault.dataset import (
    DatasetCatalogError,
    DatasetCatalogSelectionError,
    DatasetCatalogSnapshotEntryRecord,
    VerifiedDatasetCatalogSnapshot,
    select_verified_dataset_catalog_entry,
)
import market_vault.dataset.dataset_catalog_reader as reader_module
import market_vault.dataset.dataset_catalog_selection as selection_module


ROOT = Path(__file__).resolve().parents[1]
SELECTION_MODULE = (
    ROOT
    / "src"
    / "market_vault"
    / "dataset"
    / "dataset_catalog_selection.py"
)
ARTIFACT_CLIENT_MODULE = ROOT / "src" / "market_vault" / "artifact_client.py"

DATASET_A = "1" * 64
DATASET_B = "2" * 64
DATASET_C = "3" * 64
MISSING_DATASET = "f" * 64


def _forged_entry(dataset_id: str) -> DatasetCatalogSnapshotEntryRecord:
    entry = object.__new__(DatasetCatalogSnapshotEntryRecord)
    object.__setattr__(entry, "dataset_id", dataset_id)
    return entry


def _forged_catalog(
    entries: tuple[DatasetCatalogSnapshotEntryRecord, ...],
) -> VerifiedDatasetCatalogSnapshot:
    catalog = object.__new__(VerifiedDatasetCatalogSnapshot)
    object.__setattr__(catalog, "entries", entries)
    return catalog


def test_exact_dataset_id_returns_same_entry_object():
    first = _forged_entry(DATASET_A)
    selected = _forged_entry(DATASET_B)
    last = _forged_entry(DATASET_C)
    entries = (first, selected, last)
    catalog = _forged_catalog(entries)

    result = select_verified_dataset_catalog_entry(catalog, DATASET_B)

    assert result is selected
    assert catalog.entries is entries
    assert catalog.entries == (first, selected, last)


def test_selection_error_is_distinct_catalog_error():
    assert issubclass(DatasetCatalogSelectionError, DatasetCatalogError)


@pytest.mark.parametrize("catalog", [None, object(), (), {}])
def test_wrong_catalog_type_fails_closed(catalog):
    with pytest.raises(DatasetCatalogSelectionError):
        select_verified_dataset_catalog_entry(catalog, DATASET_A)


@pytest.mark.parametrize("dataset_id", [None, 1, b"1" * 64, object()])
def test_non_string_dataset_id_fails_closed(dataset_id):
    catalog = _forged_catalog((_forged_entry(DATASET_A),))
    with pytest.raises(DatasetCatalogSelectionError):
        select_verified_dataset_catalog_entry(catalog, dataset_id)


@pytest.mark.parametrize(
    "dataset_id",
    [
        "A" * 64,
        "1" * 63,
        "1" * 65,
        "g" * 64,
        DATASET_A[:16],
        DATASET_A[8:40],
        f" {DATASET_A}",
        f"{DATASET_A} ",
    ],
)
def test_malformed_prefix_and_substring_ids_fail_closed(dataset_id):
    catalog = _forged_catalog((_forged_entry(DATASET_A),))
    with pytest.raises(DatasetCatalogSelectionError):
        select_verified_dataset_catalog_entry(catalog, dataset_id)


def test_absent_id_has_no_latest_first_last_or_order_fallback():
    first = _forged_entry(DATASET_A)
    last = _forged_entry(DATASET_C)
    catalog = _forged_catalog((last, first))

    with pytest.raises(DatasetCatalogSelectionError):
        select_verified_dataset_catalog_entry(catalog, MISSING_DATASET)


def test_defensive_multiple_exact_matches_fail_closed():
    # This intentionally forges an inconsistent verified object only to
    # exercise the defensive cardinality boundary after reader trust.
    first = _forged_entry(DATASET_A)
    duplicate = _forged_entry(DATASET_A)
    catalog = _forged_catalog((first, duplicate))

    with pytest.raises(DatasetCatalogSelectionError):
        select_verified_dataset_catalog_entry(catalog, DATASET_A)


def test_selector_consumes_only_verified_entries_and_dataset_id():
    source = SELECTION_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "Path",
        "open",
        "read_text",
        "read_bytes",
        "stat",
        "resolve",
        "datetime",
        "time",
        "settings",
        "OpenD",
        "network",
        "socket",
        "recorded_build_path",
        "content_id",
        "load_verified_dataset",
        "load_verified_dataset_catalog",
    }
    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert not (used & forbidden), sorted(used & forbidden)
    assert "recorded_build_path" not in source


def test_selector_runtime_performs_no_io_reader_time_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("selector crossed its pure in-memory boundary")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(
        reader_module,
        "load_verified_dataset_catalog",
        forbidden,
    )
    entry = _forged_entry(DATASET_A)
    catalog = _forged_catalog((entry,))

    assert select_verified_dataset_catalog_entry(catalog, DATASET_A) is entry


def test_dataset_package_exports_selector_but_top_level_does_not():
    import market_vault.dataset as dataset_package

    assert "select_verified_dataset_catalog_entry" in dataset_package.__all__
    assert "DatasetCatalogSelectionError" in dataset_package.__all__
    assert "select_verified_dataset_catalog_entry" not in market_vault.__all__
    assert "DatasetCatalogSelectionError" not in market_vault.__all__
    with pytest.raises(AttributeError):
        getattr(market_vault, "select_verified_dataset_catalog_entry")
    with pytest.raises(AttributeError):
        getattr(market_vault, "DatasetCatalogSelectionError")


def test_artifact_client_delegates_once_with_exact_identities(monkeypatch):
    catalog = object()
    dataset_id = "dataset-id-object"
    selected = object()
    calls = []

    def stub(received_catalog, received_dataset_id):
        calls.append((received_catalog, received_dataset_id))
        return selected

    monkeypatch.setattr(
        selection_module,
        "select_verified_dataset_catalog_entry",
        stub,
    )
    result = ArtifactClient().select_dataset_catalog_entry(catalog, dataset_id)

    assert calls == [(catalog, dataset_id)]
    assert calls[0][0] is catalog
    assert calls[0][1] is dataset_id
    assert result is selected


def test_artifact_client_propagates_selection_error_unwrapped(monkeypatch):
    expected = DatasetCatalogSelectionError("selection failed")

    def stub(catalog, dataset_id):
        raise expected

    monkeypatch.setattr(
        selection_module,
        "select_verified_dataset_catalog_entry",
        stub,
    )
    with pytest.raises(DatasetCatalogSelectionError) as excinfo:
        ArtifactClient().select_dataset_catalog_entry(object(), DATASET_A)
    assert excinfo.value is expected


def test_artifact_client_selection_method_structure_is_exact():
    tree = ast.parse(ARTIFACT_CLIENT_MODULE.read_text(encoding="utf-8"))
    client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArtifactClient"
    )
    method = next(
        node
        for node in client.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "select_dataset_catalog_entry"
    )
    assert [arg.arg for arg in method.args.args] == [
        "self",
        "catalog",
        "dataset_id",
    ]
    imports = [node for node in ast.walk(method) if isinstance(node, ast.ImportFrom)]
    assert [
        (node.module, node.level, tuple(alias.name for alias in node.names))
        for node in imports
    ] == [
        (
            "dataset.dataset_catalog_selection",
            1,
            ("select_verified_dataset_catalog_entry",),
        )
    ]
    assert not any(isinstance(node, ast.Try) for node in ast.walk(method))
    returns = [node for node in ast.walk(method) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    call = returns[0].value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name)
    assert call.func.id == "select_verified_dataset_catalog_entry"
    assert [arg.id for arg in call.args if isinstance(arg, ast.Name)] == [
        "catalog",
        "dataset_id",
    ]
    assert call.keywords == []


def test_artifact_client_remains_stateless_with_frozen_method_signatures():
    assert list(inspect.signature(ArtifactClient).parameters) == []
    assert ArtifactClient.__slots__ == ()
    assert not hasattr(ArtifactClient(), "__dict__")
    assert list(
        inspect.signature(ArtifactClient.load_canonical_build).parameters
    ) == ["self", "build_dir"]
    assert list(inspect.signature(ArtifactClient.load_dataset).parameters) == [
        "self",
        "build_dir",
    ]
    assert list(
        inspect.signature(ArtifactClient.load_dataset_catalog).parameters
    ) == ["self", "snapshot_dir"]
    assert list(
        inspect.signature(
            ArtifactClient.select_dataset_catalog_entry
        ).parameters
    ) == ["self", "catalog", "dataset_id"]
