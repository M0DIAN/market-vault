"""Read-only release-readiness checker for MarketVault.

Verifies that pyproject.toml, the package version module, documentation, CI
package assertions, and build hygiene agree before tagging. Never modifies
files. Uses only the Python 3.11 standard library.

Exit code 0 with "RELEASE_CHECK_OK version=..." on success; exit code 1 with
every failure listed otherwise.

This checker never requires a git tag, a GitHub Release, or a PyPI
publication to exist: those actions remain separate, explicit, and are not
part of release readiness.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

EXPECTED_VERSION = "0.5.1"
PEP440_RE = re.compile(
    r"^([1-9]\d*!)?(0|[1-9]\d*)(\.(0|[1-9]\d*))*((a|b|rc)(0|[1-9]\d*))?"
    r"(\.post(0|[1-9]\d*))?(\.dev(0|[1-9]\d*))?$"
)
FORBIDDEN_TRACKED = ("build/", "dist/", ".whl", "data/", "catalog/", "manifests/", "reports/")
# The CI fresh-wheel step asserts the installed package module version and the
# installed distribution metadata version separately; both must be present.
CI_PACKAGE_VERSION_MARKERS = (
    f'assert market_vault.__version__ == "{EXPECTED_VERSION}"',
    f"assert market_vault.__version__ == '{EXPECTED_VERSION}'",
)
CI_METADATA_VERSION_MARKERS = (
    f"assert version('market-vault') == '{EXPECTED_VERSION}'",
)
# The CI fresh-wheel public API smoke marker must use the v0.5.1 marker.
CI_PUBLIC_API_MARKER = "V051_PUBLIC_API_IMPORT_OK"
# The exact NumPy timedelta warning-as-error guard that must stay in
# pyproject.toml; an ignore-based substitute is never accepted.
WARNING_GUARD_MARKER = (
    "error:The 'generic' unit for NumPy timedelta is deprecated"
)
# Stale v0.4-era claims that must never appear in the current README.
STALE_README_PHRASES = (
    "final Dataset builder is not implemented",
    "no final Dataset CLI",
    "no automatic Feature/Label value computation",
    "no final Dataset Parquet export",
    "V0.5 development",
    "V0.5 remains under development",
    "release preparation pending",
)
# Stale v0.5.0 direction status wording that must never appear in the current
# direction document.
STALE_DIRECTION_PHRASES = (
    "Status: proposed",
    "PR-10 has not started",
)
# Stale v0.5.0 pre-release wording that must never appear in the current
# direction document after the v0.5.0 release.
STALE_POST_RELEASE_PHRASES = (
    "Status: implementation complete; v0.5.0 release preparation",
    "PR-10 is the current release-preparation branch",
    "GitHub PR #29 is still OPEN",
    "No v0.5.0 tag exists",
    "No GitHub Release is published",
)
# Facts the v0.5.0 direction document must state after the release.
DIRECTION_RELEASED_FACTS = (
    "Status: released",
    "3b4d03c785123e204885faea08df7b9d7ed07ec0",
    "v0.5.0",
    "GitHub Release",
    "PyPI",
)
# Facts the v0.5.0 release notes must state after the release.
RELEASE_NOTES_FACTS = (
    "PR #29",
    "MERGED",
    "3b4d03c785123e204885faea08df7b9d7ed07ec0",
    "v0.5.0",
    "MarketVault v0.5.0",
    "market_vault-0.5.0-py3-none-any.whl",
    "market_vault-0.5.0.tar.gz",
    "PyPI",
)
# Stale pre-release wording that must never appear in the current release
# notes.
RELEASE_NOTES_STALE_PHRASES = (
    "GitHub PR #29 is still OPEN",
    "No v0.5.0 tag exists",
    "No GitHub Release is published",
)
# Facts the v0.5.1 direction document must state after the release.
DIRECTION_V051_RELEASED_FACTS = (
    "Status: released on 2026-08-06 JST",
    "Stability and Usability Maintenance",
    "PR-1",
    "PR-2",
    "PR-3",
    "PR-4",
    "0.5.1",
    "8de57d497ae5d922e3df29d9475f14b9407865f0",
    "2d9c8a539f04ee2d75e5482c858ec6c3364af135",
    "240f7ccac89a773366a510f10a13d6de801051ea",
    "a978eef291d5e26d20e5cf977bc76609c227cb52",
    "v0.5.1",
    "MarketVault v0.5.1",
    "31029709970",
    "PyPI",
    "v0.6.0",
    "Sample Generator",
    "Dataset Catalog",
    "Python Client",
    "ML Experiment",
)
# The v0.5.1 direction document must mark the future capabilities as
# non-goals and explicitly state they have not started.
DIRECTION_V051_NONGOAL_MARKERS = (
    "Explicit non-goals",
    "does not implement",
    "have not started",
)
# Stale v0.5.1 direction status wording that must never appear in the
# current direction document. The release-preparation history may describe
# the preparation itself, but the precise current-state sentences below are
# forbidden.
STALE_V051_DIRECTION_PHRASES = (
    "Status: planned",
    "Status: proposed",
    "Status: implementation complete; v0.5.1 release preparation",
    "PR-4 is in progress on the release/v0.5.1 branch",
    "The v0.5.1 tag has not been created",
    "no GitHub Release exists",
)
# Facts the v0.5.1 release notes must state after the release.
RELEASE_V051_FACTS = (
    "Formal release status",
    "PR #33",
    "MERGED",
    "2026-08-05T17:22:15Z",
    "a978eef291d5e26d20e5cf977bc76609c227cb52",
    "v0.5.1",
    "MarketVault v0.5.1",
    "2026-08-05T17:33:12Z",
    "31029709970",
    "2286 passed, 7 skipped",
    "market_vault-0.5.1-py3-none-any.whl",
    "market_vault-0.5.1.tar.gz",
    "80965A671AEEF75F315386D9BD4B62EC5DC08E552CB3430AEF92F83C562248C1",
    "FE82FB4FD254C493EC00519EDEB438533C0C5E8D5A7690E1F14AEA39DE4CCDAB",
    "PyPI",
    "TestPyPI",
    "release preparation",
    "3b4d03c785123e204885faea08df7b9d7ed07ec0",
    "PR #30",
    "PR #31",
    "PR #32",
    "8de57d497ae5d922e3df29d9475f14b9407865f0",
    "2d9c8a539f04ee2d75e5482c858ec6c3364af135",
    "240f7ccac89a773366a510f10a13d6de801051ea",
    "warning-as-error",
    "Dataset CLI examples",
    "Renderer hardening",
    # The formal artifacts must be rebuilt after the merge from the exact
    # release commit; the release-preparation branch artifacts are
    # candidate validation only.
    "rebuilt from the exact release commit",
    "candidate validation only",
)
# Stale v0.5.1 wording that must never appear in the current-state region
# of the release notes (the formal text before the historical
# release-preparation record). The historical sections may quote the
# preparation-time state verbatim, but these precise current-state
# sentences are forbidden in the formal region. "v0.5.1 is released" and
# "v0.5.1 released" are now legal formal-state expressions and are not
# stale.
RELEASE_V051_STALE_PHRASES = (
    "PR-4 is open and not merged",
    "The v0.5.1 tag does not exist yet",
    "no GitHub Release exists",
)
# The marker that separates the current-state region of the v0.5.1 release
# notes from the historical release-preparation record.
HISTORICAL_RELEASE_PREPARATION_HEADER = "## Historical release-preparation record"
# Facts the v0.6.0 direction document must state.
V060_DIRECTION_FACTS = (
    "Status: planned",
    "Deterministic Sample Generation and Dataset Catalog",
    "a978eef291d5e26d20e5cf977bc76609c227cb52",
    "PR-1",
    "PR-2",
    "PR-3",
    "PR-4",
    "PR-5",
    "PR-6",
    "PR-7",
    "PR-8",
    "PR-9",
    "Sample Generator",
    "Dataset Catalog",
    "Python Client",
    "Quant Research",
    "Trading Execution",
    "not part of v0.6",
    "bumped to 0.6.0 only in PR-9",
    "package version at planning time: 0.5.1",
)
# The v0.6.0 direction document must mark the explicit non-goals.
V060_DIRECTION_NONGOAL_MARKERS = (
    "explicit non-goals",
    "model training",
    "backtesting",
    "automatic trading",
)
# The v0.6.0 direction document must explicitly state that neither
# capability is implemented yet.
V060_NOT_IMPLEMENTED_MARKER = (
    "neither the Sample Generator nor the Dataset Catalog is implemented"
)
# Facts the v0.6.0 architecture ADR must state.
ADR_V060_FACTS = (
    "Status: Accepted",
    "MarketVault",
    "Quant Research",
    "Trading Execution",
    "Sample Generator",
    "Dataset Catalog",
)
# Both v0.6.0 boundary contracts must state that they are planned and not
# implemented in v0.5.1.
CONTRACT_PLANNED_MARKERS = (
    "not implemented in v0.5.1",
    "Target release: v0.6.0",
)
# Facts the Sample Generation boundary contract must state.
SAMPLE_GENERATION_CONTRACT_FACTS = (
    "market-vault-dataset-build-plan-v1",
    "PITSampleRequest",
    "load_verified",
    "no current time",
)
# Facts the Dataset Catalog boundary contract must state.
DATASET_CATALOG_CONTRACT_FACTS = (
    "market_vault.storage.catalog.Catalog",
    "load_verified_dataset",
    "immutable",
    "_SUCCESS",
    "no-overwrite",
    "no latest",
)
# Explicit false claims that the boundary contracts must never contain.
# The word "implemented" itself is allowed in explanatory text; only these
# precise claim phrasings are rejected.
CONTRACT_STALE_PHRASES = (
    "Status: implemented",
    "available now",
    "released in v0.5.1",
)
# The v0.6.0 Sample Generation contract production modules that must exist.
SAMPLE_GENERATION_MODULES = (
    "src/market_vault/dataset/sample_generation_models.py",
    "src/market_vault/dataset/sample_generation.py",
)
# The exact version constants the contract models module must define.
SAMPLE_GENERATION_VERSION_CONSTANTS = (
    "market-vault-sample-generation-contract-v1",
    "market-vault-sample-generation-plan-v1",
    "market-vault-sample-generation-rule-v1",
    "market-vault-sample-generation-content-v1",
)
# The formal v1 Sample Generation contract document must state the contract
# foundation + generator-core + CLI status and the not-implemented
# boundaries.
SAMPLE_GENERATION_CONTRACT_V1_STATUS = (
    "Status: Sample Generation contract, generator core, and CLI implemented",
    "Target release: v0.6.0",
    "Not available in released v0.5.1",
    "PR-3",
    "PR-4",
    "PR-5+",
)
# The v0.6.0 Sample Generator core production modules that must exist.
SAMPLE_GENERATOR_CORE_MODULES = (
    "src/market_vault/dataset/sample_generation_core.py",
    "src/market_vault/dataset/sample_generation_core_models.py",
)
# The exact core version constant the core models module must define.
SAMPLE_GENERATOR_CORE_VERSION = "market-vault-sample-generator-core-v1"
# The core contract facts the formal Sample Generation contract document
# must state (the implemented core, its public entry, and its segment /
# stride / anchor / gap boundaries).
SAMPLE_GENERATION_CORE_FACTS = (
    "SAMPLE_GENERATOR_CORE_VERSION",
    "market-vault-sample-generator-core-v1",
    "generate_sample_requests",
    "SampleGenerationResult",
    "contiguous segment",
    "stride origin",
    "anchor",
    "gap terminates the segment",
    "no request is generated when the label future is insufficient",
    "never claims a sample is COMPLETE",
    "writes no file",
    "explicit absolute path_base",
    "Overlapping Canonical rows never become a segment boundary",
    "Shared Label configuration contract",
    "recomputes the Generation content ID",
)
# Contradictory claims that must never appear in the formal Sample
# Generation contract document even when the required facts are present.
SAMPLE_GENERATION_CORE_FALSE_CLAIMS = (
    "the generator writes the Dataset build plan",
    "gaps are skipped",
    "gaps are filled",
    "cross-day windows are allowed",
    "Generation content ID enters dataset_id",
)
# The v0.6.0 Sample Generation CLI production modules that must exist.
SAMPLE_GENERATION_CLI_MODULES = (
    "src/market_vault/dataset/sample_generation_cli.py",
    "src/market_vault/dataset/sample_generation_cli_models.py",
    "src/market_vault/dataset/sample_generation_output.py",
    "src/market_vault/dataset/sample_generation_split.py",
)
# The exact CLI version constants the CLI models module must define.
SAMPLE_GENERATION_CLI_VERSION_CONSTANTS = (
    "market-vault-sample-generation-cli-v1",
    "market-vault-sample-generation-cli-result-v1",
)
# The CLI business options that must never be registered.
SAMPLE_GENERATION_CLI_FORBIDDEN_OPTIONS = (
    "--output",
    "--output-root",
    "--built-at",
    "--dataset-as-of",
    "--canonical-build",
    "--feature-spec",
    "--label-spec",
    "--split-spec",
    "--symbol",
    "--date",
    "--force",
    "--overwrite",
    "--latest",
)
# Facts the formal Sample Generation contract document must state about the
# PR-4 CLI and its ordinary build-plan output.
SAMPLE_GENERATION_CLI_CONTRACT_FACTS = (
    "market-vault sample-generate --plan",
    "market-vault-sample-generation-cli-v1",
    "market-vault-sample-generation-cli-result-v1",
    "parse_build_plan_bytes",
    "relative Dataset build-plan paths require output_plan_path to share",
    "refusing to overwrite",
    "created_new_plan",
    "never builds a Dataset",
    "never implements a Catalog",
    "EMPTY is a success",
)
# Contradictory PR-4 claims that must never appear in the formal Sample
# Generation contract document even when the required facts are present.
SAMPLE_GENERATION_CLI_FALSE_CLAIMS = (
    "CLI is not implemented",
    "CLI not implemented",
    "Sample Generator builds the Dataset",
    "the CLI builds the Dataset",
    "the CLI calls orchestrate_dataset_build",
    "the CLI implements Dataset Catalog",
    "output plan overwrites existing files",
    "relative paths may move to another parent",
    "current time supplies built_at",
    "output_plan_path enters the Generation content identity",
)
# Facts the v0.6.0 direction document must state about the PR-4 stage.
V060_DIRECTION_PR4_FACTS = (
    "PR #36",
    "2026-08-06T06:59:35Z",
    "4d5124fa1f1c30db5dcc5b8bb72c7e4f04f1109c",
    "PR-3 is complete",
    "PR-4 (this PR",
    "PR-5 (Dataset Catalog) has not started",
    "not released",
)
# Contradictory claims that must never appear in the v0.6.0 direction
# document's progress record.
V060_DIRECTION_PR4_FALSE_CLAIMS = (
    "V0.6.0 is released",
    "PR-4 is complete",
    "PR-5 (Dataset Catalog) has started",
)
# The exact root field set and rule field set must be stated in the formal
# contract document.
SAMPLE_GENERATION_ROOT_FIELDS = (
    "generation_plan_schema_version",
    "canonical_build_dirs",
    "feature_spec_files",
    "label_spec_files",
    "split_spec_file",
    "scope",
    "generation_rule",
    "dataset_as_of",
    "output_root",
    "built_at",
    "output_plan_path",
)
SAMPLE_GENERATION_RULE_FIELDS = (
    "rule_schema_version",
    "feature_window_bars",
    "label_window_bars",
    "stride_bars",
    "anchor_source",
    "anchor_rule",
    "cross_day_policy",
)
# Identity facts the formal contract document must state: the identity
# binds the verified canonical build identity and the spec content hashes,
# and path / built_at / output facts never enter it.
SAMPLE_GENERATION_IDENTITY_FACTS = (
    "canonical_build_id",
    "content_sha256",
    "never enter the Sample Generation content identity",
    "never enters dataset_id",
)
# Boundary facts the formal contract document must state.
SAMPLE_GENERATION_V1_BOUNDARY_FACTS = (
    "never reads the current time",
    "no current time",
    "no latest",
    "no network",
    "never loads settings",
    "never connects to OpenD",
    "ordinary `market-vault-dataset-build-plan-v1` document",
)
# Contradictory claims that must never appear in the formal Sample
# Generation contract document even when the required facts are present.
SAMPLE_GENERATION_FALSE_CLAIMS = (
    "Paths enter the Sample Generation content identity",
    "built_at enters the Sample Generation content identity",
    "output_root enters the Sample Generation content identity",
    "output_plan_path enters the Sample Generation content identity",
    "Generation content ID enters dataset_id",
)
# "implemented in v0.5.1" is legal only after a negation: "not implemented
# in v0.5.1" is the required planned marker. An affirmative form is a false
# claim and is rejected even when the planned markers are present.
AFFIRMATIVE_IMPLEMENTED_IN_V051_RE = re.compile(
    r"(?<!not )(?<!never )implemented in v0\.5\.1"
)
# The Sample Generation contract must support plural explicit inputs that
# mirror the existing build-plan array fields feature_spec_files and
# label_spec_files; the boundary must never shrink them into single inputs.
SAMPLE_GENERATION_PLURAL_FACTS = (
    "one or more explicit verified Canonical build directories",
    "one or more explicit Feature spec file paths",
    "one or more explicit Label spec file paths",
    "one explicit split spec file/path",
    "feature_spec_files",
    "label_spec_files",
)
# The Dataset Catalog contract must separate Catalog content identity from
# materialization / snapshot metadata.
DATASET_CATALOG_IDENTITY_FACTS = (
    "Catalog content identity",
    "built_at",
    "physical paths",
    "never enter Catalog content identity",
    "separate materialization or snapshot identity",
)
# Contradictory identity claims that must never appear in the Dataset
# Catalog contract even when the identity facts are present.
DATASET_CATALOG_FALSE_IDENTITY_CLAIMS = (
    "built_at enters Catalog content identity",
    "physical output directory enters Catalog content identity",
)
# The v0.6.0 direction must state the same two-layer identity distinction.
V060_DIRECTION_IDENTITY_FACTS = (
    "Catalog content identity",
    "built_at",
    "never enter Catalog content identity",
    "separate materialization or snapshot identity",
)
# Explicit false claims that the v0.6.0 direction must never contain even
# when the required not-implemented markers are present. The Dataset
# Catalog variant is matched as a regex because the required marker
# "neither the Sample Generator nor the Dataset Catalog is implemented by
# it" legitimately contains the sub-string "Dataset Catalog is
# implemented"; only an affirmative claim that does not continue with
# "by" is rejected.
V060_FALSE_IMPLEMENTATION_PHRASES = (
    "Sample Generator is implemented",
    "Sample Generator and the Dataset Catalog are implemented",
    "available now",
    "released in v0.5.1",
)
V060_CATALOG_IMPLEMENTED_RE = re.compile(r"Dataset Catalog is implemented(?!\s+by\b)")
# Facts the v0.5.1 maintenance section of the README must state.
README_MAINTENANCE_FACTS = (
    "V0.5.1 stability and usability maintenance",
    "Compatibility cleanup",
    "warning-as-error",
    "examples/dataset_cli/README.md",
    "stdlib-only",
)
# The example files that must exist, and the renderer markers that prove the
# hardened boundaries stayed in place.
EXAMPLES_REQUIRED = (
    "examples/dataset_cli/README.md",
    "examples/dataset_cli/render_plans.py",
    "examples/dataset_cli/plans/complete.plan.template.json",
    "examples/dataset_cli/plans/empty.plan.template.json",
    "examples/dataset_cli/specs/feature_simple_return_v1.yaml",
    "examples/dataset_cli/specs/label_forward_return_v1.yaml",
    "examples/dataset_cli/split_specs/chronological_v1.json",
)
RENDERER_MARKERS = (
    'isoformat(timespec="microseconds")',
    "destination exists and is not a directory",
    "refusing to overwrite",
    "render_plans: error:",
)


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
    )
    if result.returncode != 0:
        # Not a git worktree (e.g. a temporary copy in tests): nothing tracked.
        return []
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def check_pyproject_version(root: Path) -> list[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return ["pyproject.toml is missing"]
    with path.open("rb") as fh:
        pyproject = tomllib.load(fh)
    version = pyproject["project"]["version"]
    if version != EXPECTED_VERSION:
        return [f"pyproject.toml version is {version!r}, expected {EXPECTED_VERSION!r}"]
    return []


def check_package_version(root: Path) -> list[str]:
    version_file = root / "src" / "market_vault" / "_version.py"
    if not version_file.exists():
        return ["_version.py is missing"]
    text = version_file.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        return ["_version.py does not define __version__"]
    version = match.group(1)
    if version != EXPECTED_VERSION:
        return [f"package __version__ is {version!r}, expected {EXPECTED_VERSION!r}"]
    return []


def check_readme_title(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    if first_line.strip() != "# MarketVault v0.5.1":
        return [f"README first line is {first_line.strip()!r}, expected '# MarketVault v0.5.1'"]
    return []


def check_changelog(root: Path) -> list[str]:
    path = root / "CHANGELOG.md"
    if not path.exists():
        return ["CHANGELOG.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "## [0.5.1] - 2026-08-06" not in text:
        failures.append("CHANGELOG.md is missing '## [0.5.1] - 2026-08-06'")
    if "## [0.5.0] - 2026-08-05" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.5.0] - 2026-08-05'")
    if "## [0.4.0] - 2026-08-05" not in text:
        failures.append("CHANGELOG.md no longer contains '## [0.4.0] - 2026-08-05'")
    if "[0.5.1]: https://github.com/M0DIAN/market-vault/compare/v0.5.0...v0.5.1" not in text:
        failures.append("CHANGELOG.md is missing the v0.5.1 compare link")
    return failures


def check_readme_no_stale_wording(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for phrase in STALE_README_PHRASES:
        if phrase in text:
            failures.append(f"README still contains the outdated wording {phrase!r}")
    if "one calendar day after" in text:
        failures.append("README still contains the outdated 'one calendar day after' phrasing")
    if "next trading date" not in text and "first trading date strictly after" not in text:
        failures.append("README does not describe the next-trading-date calendar semantics")
    return failures


def check_direction_status(root: Path) -> list[str]:
    path = root / "docs" / "v0_5_0_direction.md"
    if not path.exists():
        return ["docs/v0_5_0_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in DIRECTION_RELEASED_FACTS:
        if fact not in text:
            failures.append(
                f"docs/v0_5_0_direction.md does not state the released fact {fact!r}"
            )
    for phrase in STALE_DIRECTION_PHRASES + STALE_POST_RELEASE_PHRASES:
        if phrase in text:
            failures.append(
                f"docs/v0_5_0_direction.md still contains the stale wording {phrase!r}"
            )
    return failures


def check_release_notes(root: Path) -> list[str]:
    path = root / "docs" / "release_v0_5_0.md"
    if not path.exists():
        return ["docs/release_v0_5_0.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in RELEASE_NOTES_FACTS:
        if fact not in text:
            failures.append(
                f"docs/release_v0_5_0.md does not state the release fact {fact!r}"
            )
    for phrase in RELEASE_NOTES_STALE_PHRASES:
        if phrase in text:
            failures.append(
                f"docs/release_v0_5_0.md still contains the stale wording {phrase!r}"
            )
    return failures


def _v051_direction_current_state(text: str) -> str:
    # The current-state regions are the header (title, status, and intro,
    # up to the first planning section) and the Progress section. The
    # historical planning sections (Baseline, Goals, Non-goals, Proposed PR
    # sequence) describe the past and must not be rejected for accurately
    # quoting the preparation-time state.
    regions: list[str] = []
    if "## 1. Baseline" in text:
        regions.append(text.split("## 1. Baseline", 1)[0])
    if "## 6. Progress" in text:
        regions.append(text.split("## 6. Progress", 1)[1])
    return "\n".join(regions)


def check_v051_direction(root: Path) -> list[str]:
    path = root / "docs" / "v0_5_1_direction.md"
    if not path.exists():
        return ["docs/v0_5_1_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in DIRECTION_V051_RELEASED_FACTS:
        if fact not in text:
            failures.append(f"docs/v0_5_1_direction.md does not state the fact {fact!r}")
    for marker in DIRECTION_V051_NONGOAL_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_5_1_direction.md does not mark the future capabilities "
                f"as non-goals ({marker!r})"
            )
    current_state = _v051_direction_current_state(text)
    for phrase in STALE_V051_DIRECTION_PHRASES:
        if phrase in current_state:
            failures.append(
                f"docs/v0_5_1_direction.md still contains the stale wording {phrase!r}"
            )
    return failures


def check_v051_release_notes(root: Path) -> list[str]:
    path = root / "docs" / "release_v0_5_1.md"
    if not path.exists():
        return ["docs/release_v0_5_1.md is missing"]
    text = path.read_text(encoding="utf-8")
    # Required facts are checked against the full document (several facts
    # live in the historical record), but stale current-state sentences are
    # checked only in the formal region before the historical
    # release-preparation record: the historical sections may quote the
    # preparation-time state verbatim.
    formal_text = text.split(HISTORICAL_RELEASE_PREPARATION_HEADER, 1)[0]
    failures = []
    for fact in RELEASE_V051_FACTS:
        if fact not in text:
            failures.append(
                f"docs/release_v0_5_1.md does not state the fact {fact!r}"
            )
    for phrase in RELEASE_V051_STALE_PHRASES:
        if phrase in formal_text:
            failures.append(
                f"docs/release_v0_5_1.md still contains the stale wording {phrase!r}"
            )
    return failures


def check_v060_direction(root: Path) -> list[str]:
    path = root / "docs" / "v0_6_0_direction.md"
    if not path.exists():
        return ["docs/v0_6_0_direction.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in V060_DIRECTION_FACTS:
        if fact not in text:
            failures.append(f"docs/v0_6_0_direction.md does not state the fact {fact!r}")
    for marker in V060_DIRECTION_NONGOAL_MARKERS:
        if marker not in text:
            failures.append(
                "docs/v0_6_0_direction.md does not mark the v0.6.0 "
                f"non-goals ({marker!r})"
            )
    if V060_NOT_IMPLEMENTED_MARKER not in text:
        failures.append(
            "docs/v0_6_0_direction.md must state that neither the Sample "
            "Generator nor the Dataset Catalog is implemented"
        )
    for fact in V060_DIRECTION_IDENTITY_FACTS:
        if fact not in text:
            failures.append(
                "docs/v0_6_0_direction.md does not state the Catalog "
                f"identity fact {fact!r}"
            )
    # False implementation claims are rejected even when the required
    # not-implemented markers are still present.
    for phrase in V060_FALSE_IMPLEMENTATION_PHRASES:
        if phrase in text:
            failures.append(
                f"docs/v0_6_0_direction.md contains the false claim {phrase!r}"
            )
    if V060_CATALOG_IMPLEMENTED_RE.search(text):
        failures.append(
            "docs/v0_6_0_direction.md contains the false claim "
            "'Dataset Catalog is implemented'"
        )
    return failures


def check_v060_adr(root: Path) -> list[str]:
    path = root / "docs" / "adr" / "0003-project-boundaries-and-v060-data-discovery.md"
    if not path.exists():
        return ["docs/adr/0003-project-boundaries-and-v060-data-discovery.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in ADR_V060_FACTS:
        if fact not in text:
            failures.append(f"docs/adr/0003 does not state the fact {fact!r}")
    return failures


def check_sample_generation_modules(root: Path) -> list[str]:
    failures = []
    for rel in SAMPLE_GENERATION_MODULES:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    models_path = root / "src" / "market_vault" / "dataset" / "sample_generation_models.py"
    if models_path.exists():
        text = models_path.read_text(encoding="utf-8")
        for version in SAMPLE_GENERATION_VERSION_CONSTANTS:
            if f'"{version}"' not in text:
                failures.append(
                    "sample_generation_models.py does not define the exact "
                    f"version constant {version!r}"
                )
    return failures


def check_sample_generation_contract(root: Path) -> list[str]:
    path = root / "docs" / "contracts" / "sample_generation.md"
    if not path.exists():
        return ["docs/contracts/sample_generation.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for marker in CONTRACT_PLANNED_MARKERS:
        if marker not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"planned-contract marker {marker!r}"
            )
    for marker in SAMPLE_GENERATION_CONTRACT_V1_STATUS:
        if marker not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"formal v1 contract marker {marker!r}"
            )
    for fact in SAMPLE_GENERATION_CONTRACT_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"fact {fact!r}"
            )
    for fact in SAMPLE_GENERATION_PLURAL_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"plural input fact {fact!r}"
            )
    for field in SAMPLE_GENERATION_ROOT_FIELDS:
        if field not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"exact root field {field!r}"
            )
    for field in SAMPLE_GENERATION_RULE_FIELDS:
        if field not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"exact generation_rule field {field!r}"
            )
    for fact in SAMPLE_GENERATION_IDENTITY_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"identity fact {fact!r}"
            )
    for fact in SAMPLE_GENERATION_V1_BOUNDARY_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/sample_generation.md does not state the "
                f"boundary fact {fact!r}"
            )
    for phrase in CONTRACT_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "docs/contracts/sample_generation.md still contains the "
                f"stale claim {phrase!r}"
            )
    for claim in SAMPLE_GENERATION_FALSE_CLAIMS:
        if claim in text:
            failures.append(
                "docs/contracts/sample_generation.md contains the false "
                f"claim {claim!r}"
            )
    if AFFIRMATIVE_IMPLEMENTED_IN_V051_RE.search(text):
        failures.append(
            "docs/contracts/sample_generation.md claims an affirmative "
            "'implemented in v0.5.1' implementation"
        )
    return failures


def check_sample_generation_core(root: Path) -> list[str]:
    failures = []
    for rel in SAMPLE_GENERATOR_CORE_MODULES:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    core_models = root / "src" / "market_vault" / "dataset" / "sample_generation_core_models.py"
    if core_models.exists():
        text = core_models.read_text(encoding="utf-8")
        if f'"{SAMPLE_GENERATOR_CORE_VERSION}"' not in text:
            failures.append(
                "sample_generation_core_models.py does not define the exact "
                f"core version constant {SAMPLE_GENERATOR_CORE_VERSION!r}"
            )
    core = root / "src" / "market_vault" / "dataset" / "sample_generation_core.py"
    if core.exists():
        text = core.read_text(encoding="utf-8")
        if "def generate_sample_requests" not in text:
            failures.append(
                "sample_generation_core.py does not define "
                "generate_sample_requests"
            )
    contract = root / "docs" / "contracts" / "sample_generation.md"
    if contract.exists():
        text = contract.read_text(encoding="utf-8")
        for fact in SAMPLE_GENERATION_CORE_FACTS:
            if fact not in text:
                failures.append(
                    "docs/contracts/sample_generation.md does not state the "
                    f"core fact {fact!r}"
                )
        for claim in SAMPLE_GENERATION_CORE_FALSE_CLAIMS:
            if claim in text:
                failures.append(
                    "docs/contracts/sample_generation.md contains the false "
                    f"core claim {claim!r}"
                )
    return failures


def check_sample_generation_cli(root: Path) -> list[str]:
    """Static PR-4 checks: the CLI production modules exist, the two CLI
    version constants are exact, ``sample-generate`` is registered in the
    top-level CLI with ``--plan`` as the only business option, the CLI
    never calls orchestration / materialization / the verified Dataset
    reader, the formal contract document states the PR-4 facts and no
    false claim, the direction document records the PR-4 stage, and the CI
    fresh-wheel smoke covers ``sample-generate --help``."""
    failures = []
    for rel in SAMPLE_GENERATION_CLI_MODULES:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    cli_models = root / "src" / "market_vault" / "dataset" / "sample_generation_cli_models.py"
    if cli_models.exists():
        text = cli_models.read_text(encoding="utf-8")
        for version in SAMPLE_GENERATION_CLI_VERSION_CONSTANTS:
            if f'"{version}"' not in text:
                failures.append(
                    "sample_generation_cli_models.py does not define the exact "
                    f"CLI version constant {version!r}"
                )
    cli_module = root / "src" / "market_vault" / "dataset" / "sample_generation_cli.py"
    if cli_module.exists():
        text = cli_module.read_text(encoding="utf-8")
        if 'add_parser(\n        "sample-generate",' not in text:
            failures.append(
                "sample_generation_cli.py does not register sample-generate"
            )
        if "add_argument(\n        \"--plan\"," not in text:
            failures.append(
                "sample_generation_cli.py does not declare --plan"
            )
        for option in SAMPLE_GENERATION_CLI_FORBIDDEN_OPTIONS:
            if option in text:
                failures.append(
                    f"sample_generation_cli.py registers the business option {option!r}"
                )
        for forbidden in (
            "orchestrate_dataset_build",
            "materialize_dataset_artifacts",
            "load_verified_dataset",
        ):
            if forbidden in text:
                failures.append(
                    f"sample_generation_cli.py must never call {forbidden}"
                )
        if "Path.cwd()" not in text:
            failures.append(
                "sample_generation_cli.py must locate an explicit relative "
                "--plan argument against the current working directory"
            )
    top_cli = root / "src" / "market_vault" / "cli.py"
    if top_cli.exists():
        text = top_cli.read_text(encoding="utf-8")
        for marker in (
            "add_sample_generation_subparsers",
            "SAMPLE_GENERATION_COMMANDS",
            "run_sample_generation_command",
        ):
            if marker not in text:
                failures.append(
                    "top-level cli.py is missing the Sample Generation CLI "
                    f"marker {marker!r}"
                )
        if "dataset-catalog" in text:
            failures.append(
                "top-level cli.py must not register a Dataset Catalog command"
            )
    contract = root / "docs" / "contracts" / "sample_generation.md"
    if contract.exists():
        text = contract.read_text(encoding="utf-8")
        for fact in SAMPLE_GENERATION_CLI_CONTRACT_FACTS:
            if fact not in text:
                failures.append(
                    "docs/contracts/sample_generation.md does not state the "
                    f"PR-4 fact {fact!r}"
                )
        for claim in SAMPLE_GENERATION_CLI_FALSE_CLAIMS:
            if claim in text:
                failures.append(
                    "docs/contracts/sample_generation.md contains the false "
                    f"PR-4 claim {claim!r}"
                )
    direction = root / "docs" / "v0_6_0_direction.md"
    if direction.exists():
        text = direction.read_text(encoding="utf-8")
        for fact in V060_DIRECTION_PR4_FACTS:
            if fact not in text:
                failures.append(
                    "docs/v0_6_0_direction.md does not state the PR-4 "
                    f"progress fact {fact!r}"
                )
        for claim in V060_DIRECTION_PR4_FALSE_CLAIMS:
            if claim in text:
                failures.append(
                    "docs/v0_6_0_direction.md contains the false PR-4 "
                    f"claim {claim!r}"
                )
    ci = root / ".github" / "workflows" / "ci.yml"
    if ci.exists():
        text = ci.read_text(encoding="utf-8")
        if "market-vault sample-generate --help" not in text:
            failures.append(
                ".github/workflows/ci.yml fresh-wheel smoke must cover "
                "'market-vault sample-generate --help'"
            )
    return failures


def check_dataset_catalog_contract(root: Path) -> list[str]:
    path = root / "docs" / "contracts" / "dataset_catalog.md"
    if not path.exists():
        return ["docs/contracts/dataset_catalog.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for marker in CONTRACT_PLANNED_MARKERS:
        if marker not in text:
            failures.append(
                "docs/contracts/dataset_catalog.md does not state the "
                f"planned-contract marker {marker!r}"
            )
    for fact in DATASET_CATALOG_CONTRACT_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/dataset_catalog.md does not state the "
                f"fact {fact!r}"
            )
    for fact in DATASET_CATALOG_IDENTITY_FACTS:
        if fact not in text:
            failures.append(
                "docs/contracts/dataset_catalog.md does not state the "
                f"Catalog identity fact {fact!r}"
            )
    for claim in DATASET_CATALOG_FALSE_IDENTITY_CLAIMS:
        if claim in text:
            failures.append(
                "docs/contracts/dataset_catalog.md contains the false "
                f"identity claim {claim!r}"
            )
    for phrase in CONTRACT_STALE_PHRASES:
        if phrase in text:
            failures.append(
                "docs/contracts/dataset_catalog.md still contains the "
                f"stale claim {phrase!r}"
            )
    if AFFIRMATIVE_IMPLEMENTED_IN_V051_RE.search(text):
        failures.append(
            "docs/contracts/dataset_catalog.md claims an affirmative "
            "'implemented in v0.5.1' implementation"
        )
    return failures


def check_old_release_notes(root: Path) -> list[str]:
    failures = []
    if not (root / "docs" / "release_v0_5_0.md").exists():
        failures.append("docs/release_v0_5_0.md is missing")
    if not (root / "docs" / "release_v0_4_0.md").exists():
        failures.append("docs/release_v0_4_0.md is missing")
    if not (root / "docs" / "release_v0_3_0.md").exists():
        failures.append("docs/release_v0_3_0.md is missing")
    return failures


def check_readme_maintenance_section(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    for fact in README_MAINTENANCE_FACTS:
        if fact not in text:
            failures.append(f"README does not state the v0.5.1 maintenance fact {fact!r}")
    return failures


def check_warning_guard(root: Path) -> list[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return ["pyproject.toml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if WARNING_GUARD_MARKER not in text:
        failures.append(
            "pyproject.toml is missing the exact NumPy timedelta "
            "warning-as-error guard"
        )
    if "ignore::DeprecationWarning" in text or "ignore:.*:DeprecationWarning" in text:
        failures.append(
            "pyproject.toml must not ignore DeprecationWarnings instead of "
            "the exact warning-as-error guard"
        )
    return failures


def check_examples(root: Path) -> list[str]:
    failures = []
    for rel in EXAMPLES_REQUIRED:
        if not (root / rel).exists():
            failures.append(f"{rel} is missing")
    readme = root / "examples" / "dataset_cli" / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        if "market-vault 0.5.1" not in text:
            failures.append(
                "examples/dataset_cli/README.md does not state the install "
                "version 'market-vault 0.5.1'"
            )
    renderer = root / "examples" / "dataset_cli" / "render_plans.py"
    if renderer.exists():
        text = renderer.read_text(encoding="utf-8")
        for marker in RENDERER_MARKERS:
            if marker not in text:
                failures.append(
                    f"examples/dataset_cli/render_plans.py is missing the "
                    f"marker {marker!r}"
                )
    return failures


def check_readme_upgrade_sections(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "Upgrade from v0.4" not in text:
        failures.append("README does not contain 'Upgrade from v0.4'")
    if "Upgrade from v0.3" not in text:
        failures.append("README does not contain 'Upgrade from v0.3'")
    return failures


def check_readme_dataset_builder_section(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "V0.5 deterministic Dataset builder" not in text:
        failures.append("README does not contain the 'V0.5 deterministic Dataset builder' section")
    for command in ("dataset-build", "dataset-verify", "dataset-inspect"):
        if command not in text:
            failures.append(f"README does not describe the {command} command")
    if "verified Dataset reader" not in text:
        failures.append("README does not mention the verified Dataset reader")
    if "immutable Dataset materialization" not in text:
        failures.append("README does not mention immutable Dataset materialization")
    return failures


def check_readme_explicit_build_plan(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    if "explicit" not in text or "build-plan JSON" not in text:
        return ["README does not describe the explicit, pinned build-plan JSON input"]
    return []


def check_readme_adjustment_none(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "adjustment" not in text or "NONE" not in text:
        failures.append("README does not mention the adjustment NONE default")
    if "adjusted-price" not in text:
        failures.append("README does not mention the no-adjusted-price boundary")
    return failures


def check_readme_dataset_boundaries(root: Path) -> list[str]:
    path = root / "README.md"
    if not path.exists():
        return ["README.md is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if "cross-trading-day" not in text:
        failures.append("README does not mention the no-cross-trading-day boundary")
    if "arbitrary user code" not in text:
        failures.append("README does not mention the no-arbitrary-user-code boundary")
    if "ML training" not in text or "backtest" not in text or "automatic trading" not in text:
        failures.append(
            "README does not mention the no-ML/backtest/trading boundary"
        )
    return failures


def check_ci_version_assertions(root: Path) -> list[str]:
    path = root / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        return [".github/workflows/ci.yml is missing"]
    text = path.read_text(encoding="utf-8")
    failures = []
    if not any(marker in text for marker in CI_PACKAGE_VERSION_MARKERS):
        failures.append(
            ".github/workflows/ci.yml wheel package module version assertion "
            f"is missing or wrong (expected {EXPECTED_VERSION!r})"
        )
    if not any(marker in text for marker in CI_METADATA_VERSION_MARKERS):
        failures.append(
            ".github/workflows/ci.yml wheel distribution metadata assertion "
            f"is missing or wrong (expected {EXPECTED_VERSION!r})"
        )
    if CI_PUBLIC_API_MARKER not in text:
        failures.append(
            f".github/workflows/ci.yml public API smoke marker {CI_PUBLIC_API_MARKER!r} "
            "is missing or outdated"
        )
    if "0.3.0" in text:
        failures.append(".github/workflows/ci.yml still references the old version 0.3.0")
    if "compileall -q src tests scripts examples" not in text:
        failures.append(
            ".github/workflows/ci.yml compile step must cover the examples "
            "directory"
        )
    if "render_plans.py --help" not in text:
        failures.append(
            ".github/workflows/ci.yml is missing the example renderer help smoke"
        )
    return failures


def check_build_artifacts_untracked(root: Path) -> list[str]:
    failures = []
    for item in tracked_files(root):
        normalized = item.replace("\\", "/")
        for forbidden in FORBIDDEN_TRACKED:
            if normalized.startswith(forbidden) or normalized.endswith(".whl"):
                failures.append(f"tracked build artifact: {item}")
                break
    return failures


def check_pep440(root: Path) -> list[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return ["pyproject.toml is missing"]
    with path.open("rb") as fh:
        pyproject = tomllib.load(fh)
    version = pyproject["project"]["version"]
    if not PEP440_RE.match(version):
        return [f"version {version!r} is not PEP 440 compatible"]
    return []


def check_cli_version(root: Path) -> list[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-m", "market_vault", "--version"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    output = (result.stdout + result.stderr).strip()
    expected = f"market-vault {EXPECTED_VERSION}"
    if result.returncode != 0 or expected not in output:
        return [f"CLI --version output is {output!r}, expected {expected!r} with exit 0"]
    return []


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = [
        ("pyproject version", check_pyproject_version),
        ("package __version__", check_package_version),
        ("README title", check_readme_title),
        ("CHANGELOG entry", check_changelog),
        ("README wording", check_readme_no_stale_wording),
        ("README maintenance section", check_readme_maintenance_section),
        ("direction status", check_direction_status),
        ("release notes", check_release_notes),
        ("v0.5.1 release notes", check_v051_release_notes),
        ("v0.5.1 direction", check_v051_direction),
        ("v0.6.0 direction", check_v060_direction),
        ("v0.6.0 ADR", check_v060_adr),
        ("sample generation modules", check_sample_generation_modules),
        ("sample generation contract", check_sample_generation_contract),
        ("sample generator core", check_sample_generation_core),
        ("sample generation cli", check_sample_generation_cli),
        ("dataset catalog contract", check_dataset_catalog_contract),
        ("old release notes", check_old_release_notes),
        ("warning guard", check_warning_guard),
        ("examples", check_examples),
        ("README upgrade notes", check_readme_upgrade_sections),
        ("README dataset builder", check_readme_dataset_builder_section),
        ("README explicit plan", check_readme_explicit_build_plan),
        ("README adjustment boundary", check_readme_adjustment_none),
        ("README dataset boundaries", check_readme_dataset_boundaries),
        ("CI version assertions", check_ci_version_assertions),
        ("build artifacts untracked", check_build_artifacts_untracked),
        ("PEP 440 version", check_pep440),
        ("CLI version output", check_cli_version),
    ]
    failures: list[str] = []
    for label, check in checks:
        failures.extend(check(root))
    if failures:
        print("RELEASE_CHECK_FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"RELEASE_CHECK_OK version={EXPECTED_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
