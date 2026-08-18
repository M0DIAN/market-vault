"""Offline tests for the component impact model: additive metadata that
never authorizes skipping validation."""

from __future__ import annotations

from ci_optimizer.components import compute_impact
from ci_optimizer.policy import Component

CORE = Component("core", ("src/",), requires_full=True)
PACKAGE = Component("package", ("pyproject.toml",), requires_package=True)
WEB = Component("web", ("web/",))

EMPTY = {"docs_rules": [], "package_docs_files": [], "control_rules": [], "eligible_rules": []}


def impact(paths: list[str], components: list[Component] | None = None, **over) -> object:
    kwargs = dict(EMPTY)
    kwargs.update(over)
    return compute_impact(paths, components or [], **kwargs)


def test_core_component_hit() -> None:
    result = impact(["src/x.py"], [CORE])
    assert result.core_changed is True
    assert result.components == ["core"]
    assert result.unknown_changed is False


def test_package_component_hit() -> None:
    result = impact(["pyproject.toml"], [PACKAGE])
    assert result.package_changed is True
    assert result.components == ["package"]


def test_package_docs_file_hit_without_component() -> None:
    result = impact(["README.md"], package_docs_files=["README.md"])
    assert result.package_changed is True
    assert result.components == []


def test_unknown_path() -> None:
    result = impact(["tests/x.py"])
    assert result.unknown_changed is True
    assert result.components == []


def test_shared_control_plane_path() -> None:
    result = impact([".github/workflows/ci.yml"], control_rules=[".github/workflows/"])
    assert result.shared_changed is True


def test_eligible_subset_is_never_unknown() -> None:
    result = impact(
        [".github/workflows/ci.yml"],
        control_rules=[".github/workflows/"],
        eligible_rules=[".github/workflows/ci.yml"],
    )
    assert result.shared_changed is True  # still control-plane impact
    assert result.unknown_changed is False


def test_docs_path_contributes_nothing() -> None:
    result = impact(["docs/guide.md"], docs_rules=["docs/"])
    assert result.unknown_changed is False
    assert result.components == []


def test_independent_only_for_registered_component() -> None:
    result = impact(["web/page.js"], [WEB])
    assert result.independent_only is True
    assert result.components == ["web"]


def test_independent_only_false_when_core_hit() -> None:
    result = impact(["src/x.py", "web/page.js"], [CORE, WEB])
    assert result.independent_only is False
    assert result.core_changed is True
    assert result.components == ["core", "web"]


def test_independent_only_false_when_unknown_mixed() -> None:
    result = impact(["web/page.js", "tests/x.py"], [WEB])
    assert result.independent_only is False
    assert result.unknown_changed is True


def test_component_names_sorted_deterministically() -> None:
    result = impact(["web/a.js", "src/x.py"], [WEB, CORE])
    assert result.components == ["core", "web"]


def test_empty_paths_never_marks_unknown() -> None:
    result = impact([])
    assert result.unknown_changed is False
    assert result.independent_only is False
    assert result.components == []


def test_full_matrix_required_stays_false_until_classifier_sets_it() -> None:
    # The impact model never claims FULL by itself: the classifier derives
    # full_matrix_required from the ACTIVE tier policy.
    result = impact(["src/x.py"], [CORE])
    assert result.full_matrix_required is False
