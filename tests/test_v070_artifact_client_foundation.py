"""Settings-independent ArtifactClient foundation + reader regression
(v0.7.0 PR-2 foundation, PR-3 verified readers).

Asserts the v0.7.0 Python Client boundaries:

- the top-level lazy export: plain ``import market_vault`` loads nothing
  heavy, ``ArtifactClient`` access loads only ``market_vault.artifact_client``,
  and ``MarketVault`` remains available through the same lazy mechanism;
- the strict zero-argument, stateless, side-effect-free constructor:
  positional and ``settings``/``root``/``path`` keywords are rejected,
  instances carry no ``__dict__`` and reject arbitrary state;
- the constructor is usable from an empty directory with no
  ``config/settings.yaml`` and creates no files, imports no settings /
  storage / canonical / dataset modules, and no ``duckdb`` / ``pandas`` /
  ``moomoo`` / ``futu``;
- after PR-3 the public business methods are exactly
  ``load_canonical_build`` and ``load_dataset`` — inspecting or binding
  them stays lightweight (no reader import before actual invocation),
  and no Dataset Catalog method exists (PR-4 is not implemented);
- the production module has no module-level import except
  ``__future__.annotations``; reader imports live at the method-call
  boundary.

This is a repository/behavior regression test, not product code. It never
makes an internet request.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ARTIFACT_CLIENT_MODULE = SRC / "market_vault" / "artifact_client.py"


def run_python(code: str) -> subprocess.CompletedProcess:
    """Run code in a fresh interpreter against the repository source."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    # Force UTF-8 child stdout so the utf-8 decode below matches on any
    # locale (Windows GBK would otherwise mangle non-ASCII output).
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_artifact_client_is_importable_at_top_level():
    from market_vault import ArtifactClient

    assert ArtifactClient.__name__ == "ArtifactClient"
    assert ArtifactClient.__module__ == "market_vault.artifact_client"


def test_artifact_client_is_exported_in_all():
    import market_vault

    assert "ArtifactClient" in market_vault.__all__


def test_plain_import_stays_lazy_and_loads_nothing_heavy():
    result = run_python(
        "\n".join(
            [
                "import sys",
                "import market_vault",
                "assert 'market_vault.api' not in sys.modules",
                "assert 'market_vault.artifact_client' not in sys.modules",
                "assert 'market_vault.config' not in sys.modules",
                "assert 'market_vault.storage' not in sys.modules",
                "assert 'market_vault.canonical' not in sys.modules",
                "assert 'market_vault.dataset' not in sys.modules",
                "assert 'duckdb' not in sys.modules",
                "assert 'pandas' not in sys.modules",
                "assert 'moomoo' not in sys.modules",
                "assert 'futu' not in sys.modules",
                "print('PLAIN_IMPORT_LAZY_OK')",
            ]
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PLAIN_IMPORT_LAZY_OK" in result.stdout


def test_artifact_client_access_loads_only_artifact_client():
    result = run_python(
        "\n".join(
            [
                "import sys",
                "from market_vault import ArtifactClient",
                "assert 'market_vault.artifact_client' in sys.modules",
                "assert 'market_vault.api' not in sys.modules",
                "assert 'market_vault.config' not in sys.modules",
                "assert 'market_vault.storage' not in sys.modules",
                "assert 'market_vault.canonical' not in sys.modules",
                "assert 'market_vault.dataset' not in sys.modules",
                "assert 'duckdb' not in sys.modules",
                "assert 'pandas' not in sys.modules",
                "assert 'moomoo' not in sys.modules",
                "assert 'futu' not in sys.modules",
                "print('ARTIFACT_CLIENT_LAZY_BOUNDARY_OK')",
            ]
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ARTIFACT_CLIENT_LAZY_BOUNDARY_OK" in result.stdout


def test_market_vault_remains_lazily_importable():
    result = run_python(
        "\n".join(
            [
                "import sys",
                "from market_vault import MarketVault",
                "assert MarketVault is not None",
                "assert 'market_vault.api' in sys.modules",
                "assert 'market_vault.artifact_client' not in sys.modules",
                # MarketVault access must not force the ArtifactClient module.
                "print('MARKETVAULT_LAZY_OK')",
            ]
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MARKETVAULT_LAZY_OK" in result.stdout


def test_constructor_accepts_no_arguments():
    from market_vault import ArtifactClient

    client = ArtifactClient()
    assert isinstance(client, ArtifactClient)


def test_constructor_signature_has_no_configuration_parameters():
    from market_vault import ArtifactClient

    assert list(inspect.signature(ArtifactClient).parameters) == []
    assert list(inspect.signature(ArtifactClient.__init__).parameters) == [
        "self"
    ]


def test_constructor_rejects_positional_arguments():
    from market_vault import ArtifactClient

    with pytest.raises(TypeError):
        ArtifactClient("settings")
    with pytest.raises(TypeError):
        ArtifactClient(None)


def test_constructor_rejects_configuration_keywords():
    from market_vault import ArtifactClient

    for kwargs in (
        {"settings": {}},
        {"root": Path(".")},
        {"path": Path(".")},
    ):
        with pytest.raises(TypeError):
            ArtifactClient(**kwargs)


def test_instances_are_stateless_without_dict():
    from market_vault import ArtifactClient

    client = ArtifactClient()
    assert not hasattr(client, "__dict__")


def test_instances_reject_arbitrary_state():
    from market_vault import ArtifactClient

    client = ArtifactClient()
    with pytest.raises(AttributeError):
        client.custom_state = 1


def test_public_business_methods_are_exactly_the_two_readers():
    from market_vault import ArtifactClient

    public_names = sorted(
        n for n in dir(ArtifactClient) if not n.startswith("_")
    )
    # PR-3 freezes exactly two public business methods: the Canonical and
    # Dataset verified reads. No Dataset Catalog method exists yet (PR-4).
    assert public_names == ["load_canonical_build", "load_dataset"]


def test_no_dataset_catalog_method():
    from market_vault import ArtifactClient

    assert not hasattr(ArtifactClient, "load_dataset_catalog")
    client = ArtifactClient()
    assert not hasattr(client, "load_dataset_catalog")


def test_reader_method_signatures_are_frozen():
    from market_vault import ArtifactClient

    canonical_sig = inspect.signature(
        ArtifactClient.load_canonical_build
    )
    assert list(canonical_sig.parameters) == ["self", "build_dir"]
    dataset_sig = inspect.signature(ArtifactClient.load_dataset)
    assert list(dataset_sig.parameters) == ["self", "build_dir"]


def test_constructor_works_in_empty_cwd_without_settings():
    result = run_python(
        "\n".join(
            [
                "import os",
                "import sys",
                "import tempfile",
                "os.chdir(tempfile.mkdtemp())",
                "from market_vault import ArtifactClient",
                "client = ArtifactClient()",
                "assert 'market_vault.config' not in sys.modules",
                "assert 'market_vault.storage' not in sys.modules",
                "assert 'market_vault.canonical' not in sys.modules",
                "assert 'market_vault.dataset' not in sys.modules",
                "assert 'duckdb' not in sys.modules",
                "assert 'pandas' not in sys.modules",
                "assert 'moomoo' not in sys.modules",
                "assert 'futu' not in sys.modules",
                # The constructor must not create any file or directory.
                "assert os.listdir(os.curdir) == []",
                "print('V070_ARTIFACTCLIENT_CONSTRUCTOR_OK')",
            ]
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V070_ARTIFACTCLIENT_CONSTRUCTOR_OK" in result.stdout


def test_binding_reader_methods_stays_lightweight():
    # Inspecting / binding the reader methods must not trigger the reader
    # imports: only actual invocation crosses the method-call boundary.
    result = run_python(
        "\n".join(
            [
                "import sys",
                "from market_vault import ArtifactClient",
                "client = ArtifactClient()",
                "cb = client.load_canonical_build",
                "ds = client.load_dataset",
                "assert callable(cb) and callable(ds)",
                "assert 'market_vault.canonical' not in sys.modules",
                "assert 'market_vault.dataset' not in sys.modules",
                "assert 'market_vault.config' not in sys.modules",
                "assert 'market_vault.storage' not in sys.modules",
                "assert 'duckdb' not in sys.modules",
                "assert 'pandas' not in sys.modules",
                "assert 'moomoo' not in sys.modules",
                "assert 'futu' not in sys.modules",
                "print('V070_METHOD_BINDING_LAZY_OK')",
            ]
        )
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "V070_METHOD_BINDING_LAZY_OK" in result.stdout


def test_artifact_client_module_has_no_module_level_imports_besides_future():
    # PR-3 reader imports live inside the method bodies; the module itself
    # must still have no production import at module-import time.
    tree = ast.parse(ARTIFACT_CLIENT_MODULE.read_text(encoding="utf-8"))
    imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert len(imports) == 1
    node = imports[0]
    assert isinstance(node, ast.ImportFrom)
    assert node.module == "__future__"
    assert [alias.name for alias in node.names] == ["annotations"]


def test_reader_imports_are_method_local_only():
    # The two formal reader imports must be scoped inside the reader
    # methods (method-call boundary), never at module level.
    tree = ast.parse(ARTIFACT_CLIENT_MODULE.read_text(encoding="utf-8"))
    top_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert len(top_imports) == 1  # __future__.annotations only
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in ("load_canonical_build", "load_dataset")
    }
    assert set(methods) == {"load_canonical_build", "load_dataset"}
    body_imports = {
        name: sorted(
            (node.module, node.level, tuple(a.name for a in node.names))
            for node in ast.walk(method)
            if isinstance(node, ast.ImportFrom)
        )
        for name, method in methods.items()
    }
    assert body_imports == {
        "load_canonical_build": [
            ("canonical.reader", 1, ("load_verified_canonical_build",))
        ],
        "load_dataset": [
            ("dataset.reader", 1, ("load_verified_dataset",))
        ],
    }
