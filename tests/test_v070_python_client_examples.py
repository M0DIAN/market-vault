"""v0.7.0 PR-5 hardening: example / documentation guards.

Protects the PR-5 consumer deliverables — the usage document
(``docs/v0_7_0_python_client_usage.md``), the examples README
(``examples/python_client/README.md``), and the executable example
(``examples/python_client/read_verified_artifacts.py``) — against
drift that would break the consumer contract:

- the usage doc states the unreleased lifecycle truth (v0.7.0 NOT
  RELEASED, package metadata 0.6.1 through PR-5, formal v0.6.1 GitHub
  Release without ArtifactClient);
- the executable example registers exactly the three required explicit
  path arguments and nothing else, with no default artifact paths;
- the example calls all three ArtifactClient methods and prints one
  deterministic JSON object (``sort_keys=True``);
- the example performs no artifact parsing, no filesystem discovery, no
  settings / environment-root / current-time / network / OpenD behavior,
  no writes, and no direct ``manifest.json`` / ``catalog.json`` /
  Parquet reads (AST-verified: only a frozen allowlist of calls and
  imports is permitted);
- the Jupyter guidance uses the verified ``dataset`` object first and
  labels the DataFrame conversion consumer-side;
- the ML-consumer handoff documents no ML implementation and no ML /
  visualization framework dependency.

Prose checks are used only where they enforce lifecycle / security
facts; structural checks use the AST.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USAGE_DOC = ROOT / "docs" / "v0_7_0_python_client_usage.md"
EXAMPLES_README = ROOT / "examples" / "python_client" / "README.md"
EXAMPLE_SCRIPT = ROOT / "examples" / "python_client" / "read_verified_artifacts.py"

EXAMPLE_SOURCE = EXAMPLE_SCRIPT.read_text(encoding="utf-8")
EXAMPLE_TREE = ast.parse(EXAMPLE_SOURCE)

#: Attribute calls the executable example may perform. The three
#: ArtifactClient reader methods, argparse plumbing, and json.dumps are
#: the entire allowed surface: no write / build / materialize / repair /
#: discovery / filesystem / network / time call is permitted.
EXAMPLE_ALLOWED_CALL_ATTRS = frozenset(
    {
        "ArgumentParser",
        "add_argument",
        "parse_args",
        "load_canonical_build",
        "load_dataset",
        "load_dataset_catalog",
        "dumps",
    }
)

#: Plain-name calls the executable example may perform.
EXAMPLE_ALLOWED_CALL_NAMES = frozenset(
    {"ArtifactClient", "main", "print", "SystemExit", "len"}
)

#: Imports that must never appear in the executable example.
EXAMPLE_FORBIDDEN_IMPORTS = frozenset(
    {
        "pandas",
        "pyarrow",
        "duckdb",
        "moomoo",
        "futu",
        "sklearn",
        "torch",
        "tensorflow",
        "matplotlib",
        "seaborn",
        "plotly",
        "requests",
        "urllib",
        "socket",
        "os",
        "shutil",
        "glob",
        "time",
        "datetime",
        "hashlib",
    }
)

#: Calls that must never appear in the executable example, regardless of
#: how they are spelled (plain name or attribute).
EXAMPLE_FORBIDDEN_CALL_NAMES = frozenset(
    {
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "glob",
        "rglob",
        "walk",
        "scandir",
        "listdir",
        "scandir",
        "mkdir",
        "unlink",
        "remove",
        "rename",
        "replace",
        "rmdir",
        "copytree",
        "now",
        "utcnow",
        "sleep",
        "connect",
        "urlopen",
        "getenv",
        "loads",
        "load",
        "build",
        "materialize",
        "repair",
        "write",
    }
)


def example_attribute_calls() -> list[ast.Call]:
    return [
        node
        for node in ast.walk(EXAMPLE_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    ]


def example_name_calls() -> list[ast.Call]:
    return [
        node
        for node in ast.walk(EXAMPLE_TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]


def _normalized(text: str) -> str:
    """Collapse whitespace so markdown line wraps never break a phrase."""
    return " ".join(text.split())


def assert_doc_contains(text: str, phrases: tuple[str, ...], doc: str) -> None:
    normalized = _normalized(text)
    missing = [
        phrase for phrase in phrases if _normalized(phrase) not in normalized
    ]
    assert not missing, f"{doc} is missing required facts: {missing}"


# ---------------------------------------------------------------------------
# Presence of the PR-5 consumer deliverables.
# ---------------------------------------------------------------------------


def test_usage_doc_exists():
    assert USAGE_DOC.is_file()


def test_examples_readme_exists():
    assert EXAMPLES_README.is_file()


def test_executable_example_exists_and_is_valid_python():
    assert EXAMPLE_SCRIPT.is_file()
    assert EXAMPLE_TREE is not None


# ---------------------------------------------------------------------------
# Executable example structure (AST).
# ---------------------------------------------------------------------------


def test_example_registers_exactly_the_three_required_path_arguments():
    calls = [
        node
        for node in example_attribute_calls()
        if node.func.attr == "add_argument"
    ]
    names = [
        node.args[0].value
        for node in calls
        if node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    assert names == [
        "--canonical-build-dir",
        "--dataset-build-dir",
        "--catalog-snapshot-dir",
    ]
    for node in calls:
        keywords = {kw.arg: kw.value for kw in node.keywords}
        required = keywords.get("required")
        assert isinstance(required, ast.Constant) and required.value is True
        assert "metavar" in keywords
        assert "default" not in keywords


def test_example_has_no_default_artifact_paths():
    # No add_argument default anywhere, and no string literal that looks
    # like a default artifact path or a filesystem location. (The
    # docstring legitimately documents the "no settings" boundary, so
    # only path-like literals are rejected here.)
    for node in ast.walk(EXAMPLE_TREE):
        if isinstance(node, ast.keyword) and node.arg == "default":
            raise AssertionError("example must not define default argument values")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lower = node.value.lower()
            for marker in (".parquet", "\\data\\", "/data/", ".yaml", ".json"):
                assert marker not in lower, (
                    f"example must not embed a default artifact path or "
                    f"settings file reference {node.value!r}"
                )


def test_example_calls_all_three_artifact_client_methods():
    attrs = {node.func.attr for node in example_attribute_calls()}
    assert {"load_canonical_build", "load_dataset", "load_dataset_catalog"} <= attrs
    names = {node.func.id for node in example_name_calls()}
    assert "ArtifactClient" in names


def test_example_prints_deterministic_json():
    dumps = [
        node
        for node in example_attribute_calls()
        if node.func.attr == "dumps"
    ]
    assert len(dumps) == 1
    keywords = {kw.arg: kw.value for kw in dumps[0].keywords}
    sort_keys = keywords.get("sort_keys")
    assert isinstance(sort_keys, ast.Constant) and sort_keys.value is True


def test_example_calls_are_restricted_to_the_frozen_allowlist():
    for node in example_attribute_calls():
        assert node.func.attr in EXAMPLE_ALLOWED_CALL_ATTRS, (
            f"example must not call {node.func.attr!r} (no discovery / "
            f"filesystem / write / parsing / network / time behavior)"
        )
    for node in example_name_calls():
        assert node.func.id in EXAMPLE_ALLOWED_CALL_NAMES, (
            f"example must not call {node.func.id!r}"
        )
    for node in ast.walk(EXAMPLE_TREE):
        if isinstance(node, ast.Call):
            target = (
                node.func.attr if isinstance(node.func, ast.Attribute) else (
                    node.func.id if isinstance(node.func, ast.Name) else None
                )
            )
            if target in EXAMPLE_FORBIDDEN_CALL_NAMES:
                raise AssertionError(
                    f"example must not call {target!r} (no artifact "
                    f"parsing / discovery / write / repair behavior)"
                )


def test_example_imports_are_stdlib_or_market_vault_only():
    imported = set()
    for node in ast.walk(EXAMPLE_TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    assert not (imported & EXAMPLE_FORBIDDEN_IMPORTS), (
        f"example must not import {sorted(imported & EXAMPLE_FORBIDDEN_IMPORTS)}"
    )
    assert imported <= {
        "__future__",
        "argparse",
        "json",
        "sys",
        "pathlib",
        "market_vault",
    }, sorted(imported)


def test_example_imports_market_vault_through_the_client_only():
    froms = [
        node
        for node in ast.walk(EXAMPLE_TREE)
        if isinstance(node, ast.ImportFrom)
    ]
    # Exactly `from __future__ import annotations`,
    # `from pathlib import Path`, and `from market_vault import
    # ArtifactClient`; no production submodule is ever imported.
    assert sorted(node.module for node in froms) == [
        "__future__",
        "market_vault",
        "pathlib",
    ]
    market = [node for node in froms if node.module == "market_vault"]
    assert len(market) == 1
    assert [alias.name for alias in market[0].names] == ["ArtifactClient"]
    for node in ast.walk(EXAMPLE_TREE):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "market_vault" or alias.name.startswith(
                    "market_vault."
                ):
                    raise AssertionError(
                        "example must import only from market_vault top "
                        "level, never any production submodule"
                    )


def test_example_has_no_direct_artifact_reading():
    # No Path(...).read_bytes / open / attribute access on artifacts:
    # every artifact access goes through the ArtifactClient.
    for node in ast.walk(EXAMPLE_TREE):
        if isinstance(node, ast.Attribute) and node.attr in (
            "read_bytes",
            "read_text",
            "open",
            "read",
        ):
            raise AssertionError(
                f"example must never read artifact bytes itself ({node.attr})"
            )


def test_example_has_main_and_guard():
    mains = [
        node
        for node in EXAMPLE_TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert len(mains) == 1
    args = mains[0].args
    assert [arg.arg for arg in args.args] == ["argv"]
    assert len(args.defaults) == 1
    assert isinstance(args.defaults[0], ast.Constant)
    assert args.defaults[0].value is None
    assert 'if __name__ == "__main__":' in EXAMPLE_SOURCE


# ---------------------------------------------------------------------------
# Usage document lifecycle and boundary facts.
# ---------------------------------------------------------------------------


def test_usage_doc_states_unreleased_lifecycle():
    text = USAGE_DOC.read_text(encoding="utf-8")
    assert_doc_contains(
        text,
        (
            "unreleased v0.7",
            "0.6.1 through PR-5",
            "v0.7.0 is not released yet",
            "formal v0.6.1 GitHub Release artifacts do **NOT** contain",
        ),
        USAGE_DOC.name,
    )


def test_usage_doc_documents_explicit_paths_only():
    text = USAGE_DOC.read_text(encoding="utf-8")
    assert_doc_contains(
        text,
        (
            "Every artifact path is EXPLICIT",
            "never looks up `latest`",
            "never scans or discovers artifacts",
            "never reads the current time",
        ),
        USAGE_DOC.name,
    )
    normalized = _normalized(text)
    for phrase in (
        "use the latest",
        "auto-discovery",
        "default artifact root",
        "discover the",
        "reads settings",
        "loads settings",
        "environment variable root",
    ):
        assert phrase not in normalized, (
            f"{USAGE_DOC.name} must not present discovery/settings "
            f"behavior as functionality ({phrase!r})"
        )


def test_usage_doc_jupyter_section_is_post_verification_consumer_side():
    text = USAGE_DOC.read_text(encoding="utf-8")
    assert_doc_contains(
        text,
        (
            "pd.DataFrame(dataset.rows",
            "verification happened BEFORE the DataFrame",
            "in-memory consumer representation",
            "consumer-side",
            "not a second artifact verification path",
            "Do NOT parse",
            "dataset.parquet",
            "write back into the artifact directory",
        ),
        USAGE_DOC.name,
    )
    # The Jupyter snippet appears after the verified Dataset read section.
    assert text.index("## B. Python — verified Dataset read") < text.index(
        "## Jupyter consumer example"
    )


def test_usage_doc_ml_consumer_handoff_has_no_ml_implementation():
    text = USAGE_DOC.read_text(encoding="utf-8")
    assert_doc_contains(
        text,
        (
            "does NOT train models",
            "automatic feature inference",
            "target inference",
            "train/test policy",
            "choose columns and splits EXPLICITLY",
            "NO sklearn / PyTorch / TensorFlow dependency",
        ),
        USAGE_DOC.name,
    )
    normalized = _normalized(text)
    for phrase in (
        "model.fit(",
        "model.train(",
        "torch.",
        "tensorflow.",
        "sklearn.",
    ):
        assert phrase not in normalized, (
            f"{USAGE_DOC.name} must not contain ML implementation code "
            f"({phrase!r})"
        )


def test_usage_doc_uses_existing_error_classes_only():
    text = USAGE_DOC.read_text(encoding="utf-8")
    assert_doc_contains(
        text,
        (
            "CanonicalArtifactValidationError",
            "DatasetArtifactValidationError",
            "DatasetCatalogArtifactValidationError",
            "no ArtifactClient-specific error type",
        ),
        USAGE_DOC.name,
    )


# ---------------------------------------------------------------------------
# Examples README facts.
# ---------------------------------------------------------------------------


def test_examples_readme_states_source_tree_and_boundaries():
    text = EXAMPLES_README.read_text(encoding="utf-8")
    assert_doc_contains(
        text,
        (
            "source-tree",
            "not shipped as a public client API",
            "0.6.1 through PR-5",
            "v0.7.0 is not released yet",
            "looks up `latest`",
            "network or OpenD",
            "reads the current time",
            "parses `manifest.json`",
            "pandas or any ML / visualization framework",
            "verified readers remain the only trust boundaries",
            "Exit codes: 0 on success, 1 on any documented read failure",
        ),
        EXAMPLES_README.name,
    )
    assert "The example never:" in text


def test_examples_readme_documents_the_exact_invocation():
    text = EXAMPLES_README.read_text(encoding="utf-8")
    assert "--canonical-build-dir" in text
    assert "--dataset-build-dir" in text
    assert "--catalog-snapshot-dir" in text
