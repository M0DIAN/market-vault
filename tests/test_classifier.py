"""Offline tests for the risk-tier classifier: the stable tiers
(docs_fast / package_docs / control_plane / full), the fail-closed
precedence, and the regression corpus A-O."""

from __future__ import annotations

from ci_optimizer.classifier import (
    REASON_COMPONENT_NO_VALIDATION,
    REASON_CONTROL_PLANE,
    REASON_CORE,
    REASON_DOCS,
    REASON_EMPTY,
    REASON_NOT_IN_SCOPE,
    REASON_PACKAGE_DOCS,
    REASON_SHARED,
    TIER_CONTROL_PLANE,
    TIER_DOCS_FAST,
    TIER_FULL,
    TIER_PACKAGE_DOCS,
    classify,
)


def tier_of(config, paths: list[str]) -> tuple[str, str]:
    tier, reason, impact = classify(paths, config)
    return tier, reason


# ---------------------------------------------------------------------------
# Corpus A: docs-only -> docs_fast
# ---------------------------------------------------------------------------


def test_corpus_a_docs_only_classifies_docs_fast(config) -> None:
    tier, reason = tier_of(config, ["docs/guide.md"])
    assert tier == TIER_DOCS_FAST
    assert reason == REASON_DOCS


def test_docs_fast_full_matrix_not_required(config) -> None:
    _, _, impact = classify(["docs/guide.md"], config)
    assert impact.full_matrix_required is False


def test_docs_fast_with_deep_docs_path(config) -> None:
    tier, _ = tier_of(config, ["docs/sub/dir/page.md"])
    assert tier == TIER_DOCS_FAST


# ---------------------------------------------------------------------------
# Corpus B: docs + README -> package_docs
# ---------------------------------------------------------------------------


def test_corpus_b_docs_and_readme_classifies_package_docs(config) -> None:
    tier, reason = tier_of(config, ["README.md", "docs/guide.md"])
    assert tier == TIER_PACKAGE_DOCS
    assert reason == REASON_PACKAGE_DOCS


def test_readme_alone_classifies_package_docs(config) -> None:
    tier, reason = tier_of(config, ["README.md"])
    assert tier == TIER_PACKAGE_DOCS


def test_package_docs_full_matrix_not_required(config) -> None:
    _, _, impact = classify(["README.md", "docs/guide.md"], config)
    assert impact.full_matrix_required is False


# ---------------------------------------------------------------------------
# Corpus C: control-plane eligible subset -> control_plane
# ---------------------------------------------------------------------------


def test_corpus_c_control_plane_subset_classifies_control_plane(config) -> None:
    tier, reason = tier_of(config, [".github/workflows/ci.yml"])
    assert tier == TIER_CONTROL_PLANE
    assert reason == REASON_CONTROL_PLANE


def test_control_plane_config_file_alone_classifies_control_plane(config) -> None:
    tier, _ = tier_of(config, ["ciopt.toml"])
    assert tier == TIER_CONTROL_PLANE


def test_control_plane_with_docs_mixture_classifies_control_plane(config) -> None:
    tier, _ = tier_of(config, [".github/workflows/ci.yml", "docs/guide.md"])
    assert tier == TIER_CONTROL_PLANE


def test_control_plane_full_matrix_not_required(config) -> None:
    _, _, impact = classify([".github/workflows/ci.yml"], config)
    assert impact.full_matrix_required is False


# ---------------------------------------------------------------------------
# Corpus D: source (core component) -> full
# ---------------------------------------------------------------------------


def test_corpus_d_source_change_classifies_full(config) -> None:
    tier, reason = tier_of(config, ["src/ci_optimizer/classifier.py"])
    assert tier == TIER_FULL
    assert reason == REASON_CORE


def test_core_change_marks_impact(config) -> None:
    _, _, impact = classify(["src/ci_optimizer/classifier.py"], config)
    assert impact.core_changed is True
    assert impact.components == ["core"]
    assert impact.full_matrix_required is True


def test_registered_non_core_component_classifies_full(config) -> None:
    # pyproject.toml is a registered component without an explicit
    # validation contract: the tier stays FULL.
    tier, reason = tier_of(config, ["pyproject.toml"])
    assert tier == TIER_FULL
    assert reason == REASON_COMPONENT_NO_VALIDATION


def test_registered_component_marks_package_impact(config) -> None:
    _, _, impact = classify(["pyproject.toml"], config)
    assert impact.package_changed is True
    assert impact.components == ["package"]


# ---------------------------------------------------------------------------
# Corpus E: test change -> full
# ---------------------------------------------------------------------------


def test_corpus_e_test_change_classifies_full(config) -> None:
    tier, reason = tier_of(config, ["tests/test_dataset.py"])
    assert tier == TIER_FULL
    assert reason == REASON_NOT_IN_SCOPE


def test_test_change_marks_unknown_impact(config) -> None:
    _, _, impact = classify(["tests/test_dataset.py"], config)
    assert impact.unknown_changed is True
    assert impact.full_matrix_required is True


# ---------------------------------------------------------------------------
# Corpus F: unknown path -> full
# ---------------------------------------------------------------------------


def test_corpus_f_unknown_path_classifies_full(config) -> None:
    tier, reason = tier_of(config, ["unknown/new_thing.py"])
    assert tier == TIER_FULL
    assert reason == REASON_NOT_IN_SCOPE


# ---------------------------------------------------------------------------
# Corpus G: empty diff -> full
# ---------------------------------------------------------------------------


def test_corpus_g_empty_diff_classifies_full(config) -> None:
    tier, reason = tier_of(config, [])
    assert tier == TIER_FULL
    assert reason == REASON_EMPTY


def test_empty_diff_full_matrix_required(config) -> None:
    _, _, impact = classify([], config)
    assert impact.full_matrix_required is True


# ---------------------------------------------------------------------------
# Corpus I: rename eligible -> non-eligible -> full (old + new both count)
# ---------------------------------------------------------------------------


def test_corpus_i_rename_out_of_eligible_classifies_full(config) -> None:
    # Old path (eligible) + new path (unknown): both are in the diff.
    tier, reason = tier_of(config, ["ciopt.toml", "ci_opt_renamed.toml"])
    assert tier == TIER_FULL
    assert reason == REASON_NOT_IN_SCOPE


def test_rename_docs_to_source_classifies_full(config) -> None:
    tier, reason = tier_of(config, ["docs/old.md", "src/ci_optimizer/new.py"])
    assert tier == TIER_FULL
    assert reason == REASON_CORE


# ---------------------------------------------------------------------------
# Control-plane mixtures and precedence (fail-closed).
# ---------------------------------------------------------------------------


def test_control_plane_plus_package_doc_classifies_full(config) -> None:
    tier, reason = tier_of(
        config, [".github/workflows/ci.yml", "README.md"]
    )
    assert tier == TIER_FULL
    assert reason == REASON_SHARED


def test_non_eligible_control_plane_path_classifies_full(config) -> None:
    # A second workflow file is control-plane but NOT in the eligible
    # allowlist: FULL, with shared_changed impact.
    tier, reason = tier_of(config, [".github/workflows/release.yml"])
    assert tier == TIER_FULL
    assert reason == REASON_SHARED


def test_non_eligible_control_plane_marks_shared_impact(config) -> None:
    _, _, impact = classify([".github/workflows/release.yml"], config)
    assert impact.shared_changed is True
    # Not in the eligible allowlist either: honest fail-closed metadata.
    assert impact.unknown_changed is True


def test_core_plus_unknown_classifies_full(config) -> None:
    tier, _ = tier_of(config, ["src/ci_optimizer/x.py", "tests/new_test.py"])
    assert tier == TIER_FULL


def test_classify_never_raises_on_any_path_list(config) -> None:
    for paths in ([], ["a"], ["src/", "docs/", "ciopt.toml", "README.md"]):
        tier, _, impact = classify(paths, config)
        assert tier in ("docs_fast", "package_docs", "control_plane", "full")
        assert impact.full_matrix_required == (tier == TIER_FULL)
