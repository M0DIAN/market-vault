"""Offline tests for the strict configuration contract (schema v1) and
the exact/prefix path-rule primitives."""

from __future__ import annotations

import pytest

from ci_optimizer.policy import (
    Config,
    ConfigError,
    load_config,
    rule_matches,
    violations,
)


def write_config(tmp_path, text: str, name: str = "ciopt.toml") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


MINIMAL = """\
schema_version = 1

[paths]
control_plane = [".github/workflows/"]

[reuse]
enabled = false
"""

FULL = """\
schema_version = 1

[repository]
main_branch = "main"
workflow_name = "CI"
workflow_path = ".github/workflows/ci.yml"

[paths]
docs = ["docs/"]
package_docs = ["README.md"]
control_plane = [".github/workflows/", "ciopt.toml"]
control_plane_eligible = [".github/workflows/ci.yml", "ciopt.toml"]

[components.core]
paths = ["src/"]
requires_full = true

[components.package]
paths = ["pyproject.toml", "README.md"]
requires_package = true

[reuse]
enabled = true
required_jobs = ["test (3.11)", "test (3.12)", "package"]
control_plane_paths = [".github/workflows/", "ciopt.toml"]
artifact_prefix = "ci-full-attestation-"
"""


# ---------------------------------------------------------------------------
# Valid configurations.
# ---------------------------------------------------------------------------


def test_minimal_config_with_defaults(tmp_path) -> None:
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.main_branch == "main"
    assert config.workflow_name == "CI"
    assert config.workflow_path == ".github/workflows/ci.yml"
    assert config.docs == ("docs/",)
    assert config.package_docs == ("README.md",)
    assert config.control_plane == (".github/workflows/",)
    # control_plane_eligible defaults to DISABLED (empty): the tier is an
    # opt-in extension, never auto-claimed by the generic framework.
    assert config.control_plane_eligible == ()
    assert config.components == ()
    assert config.reuse_enabled is False
    assert config.reuse_control_plane_paths == (".github/workflows/",)
    assert config.artifact_prefix == "ci-full-attestation-"
    assert config.main_ref == "refs/heads/main"


def test_full_config_parses(tmp_path) -> None:
    config = load_config(write_config(tmp_path, FULL))
    assert config.docs == ("docs/",)
    assert config.package_docs == ("README.md",)
    assert config.control_plane_eligible == (
        ".github/workflows/ci.yml",
        "ciopt.toml",
    )
    assert [c.name for c in config.components] == ["core", "package"]
    assert config.components[0].requires_full is True
    assert config.components[1].requires_package is True
    assert config.required_jobs == ("test (3.11)", "test (3.12)", "package")
    assert config.reuse_control_plane_paths == (".github/workflows/", "ciopt.toml")


def test_main_ref_follows_configured_branch(tmp_path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            MINIMAL.replace("[paths]", '[repository]\nmain_branch = "prod"\n\n[paths]'),
        )
    )
    assert config.main_ref == "refs/heads/prod"


# ---------------------------------------------------------------------------
# Strict parsing: every malformed shape fails closed with ConfigError.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,needle",
    [
        ("schema_version = 2\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n", "unsupported schema_version"),
        ("schema_version = \"1\"\n\n[paths]\ncontrol_plane = []\n", "unsupported schema_version"),
        ("[paths]\ncontrol_plane = [\".github/workflows/\"]\n", "schema_version"),
        ("schema_version = 1\n[unknown_table]\n", "unknown key"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\ntypo_key = []\n", "unknown key"),
        ("schema_version = 1\n\n[paths]\n", "control_plane is required"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = \"not-a-list\"\n", "[paths].control_plane"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = []\n", "[paths].control_plane"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\"\"]\n", "[paths].control_plane"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[repository]\nmain_branch = \"\"\n", "main_branch"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[components.Bad-Name]\npaths = [\"src/\"]\n", "invalid component name"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[components.core]\npaths = []\n", "[components.core].paths"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[components.core]\npaths = [\"src/\"]\nrequires_full = \"yes\"\n", "requires_* flags"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[reuse]\nenabled = true\n", "required_jobs is required"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[reuse]\nenabled = \"yes\"\nrequired_jobs = [\"test\"]\n", "enabled must be a boolean"),
        ("schema_version = 1\n\n[paths]\ncontrol_plane = [\".github/workflows/\"]\n\n[reuse]\nenabled = false\nunknown_key = true\n", "unknown key"),
    ],
)
def test_malformed_config_fails_closed(tmp_path, text: str, needle: str) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write_config(tmp_path, text))
    assert needle in str(exc.value)


def test_missing_file_fails_closed(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "does-not-exist.toml")
    assert "cannot read config" in str(exc.value)


def test_unparseable_toml_fails_closed(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(write_config(tmp_path, "schema_version = = 1\n"))
    assert "malformed config" in str(exc.value)


def test_reuse_disabled_does_not_require_jobs(tmp_path) -> None:
    config = load_config(write_config(tmp_path, MINIMAL))
    assert config.reuse_enabled is False
    assert config.required_jobs == ()


# ---------------------------------------------------------------------------
# control_plane_eligible: opt-in extension, fail-closed by default (§3).
# ---------------------------------------------------------------------------


def test_explicit_empty_eligible_is_valid(tmp_path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            MINIMAL.replace("[paths]", '[paths]\ncontrol_plane_eligible = []'),
        )
    )
    assert config.control_plane_eligible == ()


def test_omission_defaults_to_disabled(tmp_path) -> None:
    config = load_config(write_config(tmp_path, MINIMAL))
    # The generic framework must NEVER auto-claim workflow/config paths
    # as fast-eligible.
    assert config.control_plane_eligible == ()


def test_eligible_rule_outside_control_plane_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(
            write_config(
                tmp_path,
                'schema_version = 1\n\n'
                '[paths]\n'
                'control_plane = [".github/workflows/"]\n'
                'control_plane_eligible = ["src/"]\n',
            )
        )
    assert "not contained by [paths].control_plane" in str(exc.value)


def test_eligible_rule_covered_by_control_plane_prefix_accepted(tmp_path) -> None:
    config = load_config(
        write_config(
            tmp_path,
            'schema_version = 1\n\n'
            '[paths]\n'
            'control_plane = [".github/workflows/"]\n'
            'control_plane_eligible = [".github/workflows/ci.yml"]\n'
            '\n[reuse]\nenabled = false\n',
        )
    )
    assert config.control_plane_eligible == (".github/workflows/ci.yml",)


def test_eligible_empty_string_rule_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(
            write_config(
                tmp_path,
                'schema_version = 1\n\n'
                '[paths]\n'
                'control_plane = [".github/workflows/"]\n'
                'control_plane_eligible = [""]\n',
            )
        )
    assert "[paths].control_plane_eligible" in str(exc.value)


# ---------------------------------------------------------------------------
# Rule matching: exact or directory-prefix only.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule,path,expected",
    [
        ("docs/", "docs/a.md", True),
        ("docs/", "docs/a/b.md", True),
        ("docs", "docs/a.md", True),           # trailing slash ignored
        ("docs/", "docs", True),               # a path exactly "docs" is the docs rule itself
        ("README.md", "README.md", True),
        ("README.md", "docs/README.md", False),
        ("script", "scripts/tool.py", False),  # no substring matching
        (".github/workflows/", ".github/workflows/ci.yml", True),
        (".github/workflows/ci.yml", ".github/workflows/ci.yml", True),
        ("src/", "src/x/y.py", True),
    ],
)
def test_rule_matches(rule: str, path: str, expected: bool) -> None:
    assert rule_matches(rule, path) is expected


def test_violations_reports_unmatched_paths() -> None:
    rules = ["docs/", "README.md"]
    assert violations(["docs/a.md", "README.md"], rules) == []
    assert violations(["docs/a.md", "src/x.py"], rules) == ["src/x.py"]
