"""Settings-independent ArtifactClient foundation regression (v0.7.0 PR-2).

Asserts the PR-2 foundation boundary of the v0.7.0 Python Client:

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
- the PR-2 foundation exposes no public business methods (no PR-3/PR-4
  reader methods and no future-method stubs exist yet);
- the production module imports only ``__future__.annotations``.

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


def test_foundation_exposes_no_public_business_methods():
    from market_vault import ArtifactClient

    public_names = [n for n in dir(ArtifactClient) if not n.startswith("_")]
    # PR-2 ships the constructor foundation only: no Canonical / Dataset /
    # Dataset Catalog reader methods, and no future-method stubs.
    assert public_names == []


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


def test_artifact_client_module_imports_only_future_annotations():
    tree = ast.parse(ARTIFACT_CLIENT_MODULE.read_text(encoding="utf-8"))
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert len(imports) == 1
    node = imports[0]
    assert isinstance(node, ast.ImportFrom)
    assert node.module == "__future__"
    assert [alias.name for alias in node.names] == ["annotations"]
