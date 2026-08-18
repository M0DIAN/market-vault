"""Configuration (schema version 1) and path-policy primitives.

The config file (``ciopt.toml`` by convention) is the single place where
project-specific path assumptions live. Parsing is deterministic and
strict: no ``eval``, no shell interpolation. A malformed config fails
closed (``ConfigError``); the CLI converts it to ``tier=full`` /
``reuse=false``.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

DEFAULT_MAIN_BRANCH = "main"
DEFAULT_WORKFLOW_NAME = "CI"
DEFAULT_WORKFLOW_PATH = ".github/workflows/ci.yml"
DEFAULT_DOCS = ("docs/",)
DEFAULT_PACKAGE_DOCS = ("README.md",)
DEFAULT_ARTIFACT_PREFIX = "ci-full-attestation-"

_COMPONENT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")

_TOP_LEVEL_KEYS = frozenset(("schema_version", "repository", "paths", "components", "reuse"))
_REPOSITORY_KEYS = frozenset(("main_branch", "workflow_name", "workflow_path"))
_PATHS_KEYS = frozenset(("docs", "package_docs", "control_plane", "control_plane_eligible"))
_REUSE_KEYS = frozenset(("enabled", "required_jobs", "control_plane_paths", "artifact_prefix"))
_COMPONENT_KEYS = frozenset(("paths", "requires_full", "requires_package"))


class ConfigError(Exception):
    """A malformed / unsupported configuration (fail-closed)."""


@dataclass(frozen=True)
class Component:
    """One registered ``[components.<name>]`` entry."""

    name: str
    paths: tuple[str, ...]
    requires_full: bool = False
    requires_package: bool = False


@dataclass(frozen=True)
class Config:
    """The validated framework configuration."""

    config_path: str
    main_branch: str = DEFAULT_MAIN_BRANCH
    workflow_name: str = DEFAULT_WORKFLOW_NAME
    workflow_path: str = DEFAULT_WORKFLOW_PATH
    docs: tuple[str, ...] = DEFAULT_DOCS
    package_docs: tuple[str, ...] = DEFAULT_PACKAGE_DOCS
    control_plane: tuple[str, ...] = ()
    control_plane_eligible: tuple[str, ...] = ()
    components: tuple[Component, ...] = ()
    reuse_enabled: bool = True
    required_jobs: tuple[str, ...] = ()
    reuse_control_plane_paths: tuple[str, ...] = ()
    artifact_prefix: str = DEFAULT_ARTIFACT_PREFIX

    @property
    def main_ref(self) -> str:
        return f"refs/heads/{self.main_branch}"


def _check_table(data: dict, name: str, keys: frozenset[str], where: str) -> None:
    for key in data:
        if key not in keys:
            raise ConfigError(
                f"invalid config {where}: unknown key {key!r} in [{name}]"
            )


def _string_list(
    value: object, where: str, what: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ConfigError(
            f"invalid config {where}: {what} must be a list of non-empty strings"
        )
    if not value and not allow_empty:
        raise ConfigError(
            f"invalid config {where}: {what} must be a non-empty list of non-empty strings"
        )
    return tuple(value)


def load_config(path: str | Path) -> Config:
    """Parse and strictly validate the framework config file.

    - ``schema_version`` must be present and exactly 1
    - unknown tables / keys are rejected (deterministic)
    - wrong types are rejected
    - a missing or unparseable file raises ``ConfigError``
    - ``[paths].control_plane`` is required: a conservative default
      would silently make control-plane mutations eligible for fast
      paths, which is never acceptable
    - ``[paths].control_plane_eligible`` is an opt-in extension: it
      defaults to empty (disabled), an explicit ``[]`` is valid, and
      every non-empty eligible rule must be contained by
      ``[paths].control_plane``. The generic framework never claims a
      downstream control-plane validation surface exists.
    """
    config_path = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {config_path}: {exc}")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"malformed config {config_path}: {exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"malformed config {config_path}: not a TOML table")
    _check_table(data, "root", _TOP_LEVEL_KEYS, config_path)

    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ConfigError(
            f"invalid config {config_path}: unsupported schema_version "
            f"{schema_version!r} (expected {SCHEMA_VERSION})"
        )

    repository = data.get("repository", {})
    if not isinstance(repository, dict):
        raise ConfigError(f"invalid config {config_path}: [repository] is not a table")
    _check_table(repository, "repository", _REPOSITORY_KEYS, config_path)
    main_branch = repository.get("main_branch", DEFAULT_MAIN_BRANCH)
    if not isinstance(main_branch, str) or not main_branch:
        raise ConfigError(f"invalid config {config_path}: main_branch must be a non-empty string")
    workflow_name = repository.get("workflow_name", DEFAULT_WORKFLOW_NAME)
    if not isinstance(workflow_name, str) or not workflow_name:
        raise ConfigError(f"invalid config {config_path}: workflow_name must be a non-empty string")
    workflow_path = repository.get("workflow_path", DEFAULT_WORKFLOW_PATH)
    if not isinstance(workflow_path, str) or not workflow_path:
        raise ConfigError(f"invalid config {config_path}: workflow_path must be a non-empty string")

    paths = data.get("paths")
    if not isinstance(paths, dict):
        raise ConfigError(f"invalid config {config_path}: [paths] is not a table")
    _check_table(paths, "paths", _PATHS_KEYS, config_path)
    docs = _string_list(paths.get("docs", list(DEFAULT_DOCS)), config_path, "[paths].docs")
    package_docs = _string_list(
        paths.get("package_docs", list(DEFAULT_PACKAGE_DOCS)),
        config_path, "[paths].package_docs",
    )
    if "control_plane" not in paths:
        raise ConfigError(
            f"invalid config {config_path}: [paths].control_plane is required"
        )
    control_plane = _string_list(paths["control_plane"], config_path, "[paths].control_plane")
    if "control_plane_eligible" in paths:
        control_plane_eligible = _string_list(
            paths["control_plane_eligible"], config_path,
            "[paths].control_plane_eligible", allow_empty=True,
        )
    else:
        # Omission defaults to DISABLED (empty). The control_plane tier
        # is an opt-in extension: the generic framework must never
        # silently claim a downstream control-plane validation surface.
        control_plane_eligible = ()
    for rule in control_plane_eligible:
        if not any(rule_matches(surface, rule) for surface in control_plane):
            raise ConfigError(
                f"invalid config {config_path}: [paths].control_plane_eligible "
                f"rule {rule!r} is not contained by [paths].control_plane"
            )

    components: list[Component] = []
    raw_components = data.get("components")
    if raw_components is not None:
        if not isinstance(raw_components, dict):
            raise ConfigError(f"invalid config {config_path}: [components] is not a table")
        for name, entry in raw_components.items():
            if not isinstance(name, str) or not _COMPONENT_NAME_RE.fullmatch(name):
                raise ConfigError(
                    f"invalid config {config_path}: invalid component name {name!r}"
                )
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"invalid config {config_path}: [components.{name}] is not a table"
                )
            _check_table(entry, f"components.{name}", _COMPONENT_KEYS, config_path)
            comp_paths = _string_list(
                entry.get("paths"), config_path, f"[components.{name}].paths"
            )
            requires_full = entry.get("requires_full", False)
            requires_package = entry.get("requires_package", False)
            if not isinstance(requires_full, bool) or not isinstance(requires_package, bool):
                raise ConfigError(
                    f"invalid config {config_path}: [components.{name}] requires_* flags must be booleans"
                )
            components.append(
                Component(name, comp_paths, requires_full, requires_package)
            )

    reuse_enabled = True
    required_jobs: tuple[str, ...] = ()
    reuse_control_plane_paths = control_plane
    artifact_prefix = DEFAULT_ARTIFACT_PREFIX
    raw_reuse = data.get("reuse")
    if raw_reuse is not None:
        if not isinstance(raw_reuse, dict):
            raise ConfigError(f"invalid config {config_path}: [reuse] is not a table")
        _check_table(raw_reuse, "reuse", _REUSE_KEYS, config_path)
        reuse_enabled = raw_reuse.get("enabled", True)
        if not isinstance(reuse_enabled, bool):
            raise ConfigError(f"invalid config {config_path}: [reuse].enabled must be a boolean")
        if "required_jobs" in raw_reuse:
            required_jobs = _string_list(raw_reuse["required_jobs"], config_path, "[reuse].required_jobs")
        if "control_plane_paths" in raw_reuse:
            reuse_control_plane_paths = _string_list(
                raw_reuse["control_plane_paths"], config_path, "[reuse].control_plane_paths"
            )
        artifact_prefix = raw_reuse.get("artifact_prefix", DEFAULT_ARTIFACT_PREFIX)
        if not isinstance(artifact_prefix, str) or not artifact_prefix:
            raise ConfigError(f"invalid config {config_path}: artifact_prefix must be a non-empty string")
    if reuse_enabled and not required_jobs:
        raise ConfigError(
            f"invalid config {config_path}: [reuse].required_jobs is required when reuse is enabled"
        )

    return Config(
        config_path=config_path,
        main_branch=main_branch,
        workflow_name=workflow_name,
        workflow_path=workflow_path,
        docs=docs,
        package_docs=package_docs,
        control_plane=control_plane,
        control_plane_eligible=control_plane_eligible,
        components=tuple(components),
        reuse_enabled=reuse_enabled,
        required_jobs=required_jobs,
        reuse_control_plane_paths=reuse_control_plane_paths,
        artifact_prefix=artifact_prefix,
    )


def rule_matches(rule: str, path: str) -> bool:
    """Exact file match or directory-prefix match.

    A rule matches a path when the path equals the rule or the path
    starts with rule + "/". Trailing slashes in the rule are ignored.
    There is no substring / fuzzy matching: the rule "script" does NOT
    match "scripts/tool.py".
    """
    rule = rule.rstrip("/")
    return path == rule or path.startswith(rule + "/")


def violations(paths: list[str], rules: list[str]) -> list[str]:
    """Paths not matched by any rule (exact or prefix)."""
    return [p for p in paths if not any(rule_matches(r, p) for r in rules)]
